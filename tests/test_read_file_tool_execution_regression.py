import unittest
import tempfile
import asyncio
import sys
from pathlib import Path
from unittest.mock import patch, AsyncMock

# Add backend to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from skills.registry import skill_registry
from core.response_sanitizer import ResponseSanitizer
from core.assistant import ByteXCore


class TestReadFileToolExecutionRegression(unittest.IsolatedAsyncioTestCase):
    """
    Regression test suite for tool execution failures:
    - User request: 'Check 04_edge_cases.cpp for compilation errors. If there are any, report them. Don't modify the file.'
    - Guarantees read_file is registered and dispatches to read_code_file.
    - Guarantees file_path, filename, and path arguments are properly extracted.
    - Guarantees missing-file and error cases report truthful failure.
    - Guarantees <tool_call> tags are detected and never leak to user output.
    - Guarantees multi-turn assistant loop executes tool calls and feeds verified results back into context.
    """

    async def asyncSetUp(self):
        self.skill = skill_registry.get_skill("coding_workspace")
        self.temp_dir_obj = tempfile.TemporaryDirectory(prefix="bytex_test_read_tool_")
        self.temp_dir = Path(self.temp_dir_obj.name)
        self.skill._active_project_path = self.temp_dir
        self.skill._active_project_name = self.temp_dir.name
        skill_registry._skills["coding_workspace"] = self.skill

        # Create sample target file in temp workspace
        self.sample_file = self.temp_dir / "04_edge_cases.cpp"
        self.sample_code = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    int n;\n"
            "    if (!(cin >> n)) return 0;\n"
            "    cout << \"Value: \" << n << endl;\n"
            "    return 0;\n"
            "}\n"
        )
        self.sample_file.write_text(self.sample_code, encoding="utf-8")

    async def asyncTearDown(self):
        try:
            self.temp_dir_obj.cleanup()
        except Exception:
            pass

    async def test_01_read_file_registered_in_registry(self):
        """Proves read_file and read_source_file are registered in SkillRegistry."""
        skill = skill_registry.get_skill("read_file")
        self.assertIsNotNone(skill, "read_file must be registered in SkillRegistry")
        self.assertEqual(skill.name, "coding_workspace")

        skill_src = skill_registry.get_skill("read_source_file")
        self.assertIsNotNone(skill_src, "read_source_file must be registered in SkillRegistry")

    async def test_02_read_file_dispatch_with_file_path(self):
        """Proves execute_tool('read_file', {'file_path': '04_edge_cases.cpp'}) returns file contents."""
        result = await skill_registry.execute_tool("read_file", {"file_path": "04_edge_cases.cpp"})
        self.assertTrue(result.success, f"read_file failed: {result.message}")
        self.assertEqual(result.action, "read_code_file")
        self.assertIn("04_edge_cases.cpp", result.message)
        self.assertIn("Value:", result.message)

    async def test_03_read_file_dispatch_with_filename_and_path_variants(self):
        """Proves execute_tool works with filename and path argument keys."""
        # filename
        res1 = await skill_registry.execute_tool("read_file", {"filename": "04_edge_cases.cpp"})
        self.assertTrue(res1.success)
        self.assertIn("Value:", res1.message)

        # path
        res2 = await skill_registry.execute_tool("read_file", {"path": "04_edge_cases.cpp"})
        self.assertTrue(res2.success)
        self.assertIn("Value:", res2.message)

    async def test_04_read_file_missing_file_reports_truthful_failure(self):
        """Proves missing files return explicit failure and do not claim success."""
        result = await skill_registry.execute_tool("read_file", {"file_path": "nonexistent_file.cpp"})
        self.assertFalse(result.success)
        self.assertEqual(result.error, "File not found")
        self.assertIn("couldn't find source file", result.message)

    async def test_05_response_sanitizer_detects_tool_call_protocol(self):
        """Proves ResponseSanitizer.contains_internal_agent_protocol detects <tool_call>."""
        raw_msg = (
            "I'll check the file for compilation errors.\n"
            "<tool_call>\n"
            '{"name": "read_file", "arguments": {"file_path": "04_edge_cases.cpp"}}\n'
            "</tool_call>"
        )
        self.assertTrue(ResponseSanitizer.contains_internal_agent_protocol(raw_msg))

    async def test_06_response_sanitizer_extracts_tool_call(self):
        """Proves ResponseSanitizer.extract_tool_call extracts name and arguments correctly."""
        # XML standard
        raw1 = (
            "I'll check the file.\n"
            "<tool_call>\n"
            '{"name": "read_file", "arguments": {"file_path": "04_edge_cases.cpp"}}\n'
            "</tool_call>"
        )
        tool1 = ResponseSanitizer.extract_tool_call(raw1)
        self.assertIsNotNone(tool1)
        self.assertEqual(tool1[0], "read_file")
        self.assertEqual(tool1[1].get("file_path"), "04_edge_cases.cpp")

        # Flat arguments format
        raw2 = '<tool_call>{"name": "read_file", "file_path": "04_edge_cases.cpp"}</tool_call>'
        tool2 = ResponseSanitizer.extract_tool_call(raw2)
        self.assertIsNotNone(tool2)
        self.assertEqual(tool2[0], "read_file")
        self.assertEqual(tool2[1].get("file_path"), "04_edge_cases.cpp")

        # Unclosed tag format
        raw3 = 'Checking now...\n<tool_call>{"name": "read_file", "arguments": {"file_path": "04_edge_cases.cpp"}}'
        tool3 = ResponseSanitizer.extract_tool_call(raw3)
        self.assertIsNotNone(tool3)
        self.assertEqual(tool3[0], "read_file")
        self.assertEqual(tool3[1].get("file_path"), "04_edge_cases.cpp")

    async def test_07_response_sanitizer_strips_tool_call_without_leakage(self):
        """Proves ResponseSanitizer.sanitize removes raw <tool_call> completely."""
        raw = (
            "I'll check the file for compilation errors.\n"
            "<tool_call>\n"
            '{"name": "read_file", "arguments": {"file_path": "04_edge_cases.cpp"}}\n'
            "</tool_call>"
        )
        sanitized = ResponseSanitizer.sanitize(raw)
        self.assertNotIn("<tool_call>", sanitized)
        self.assertNotIn("</tool_call>", sanitized)
        self.assertNotIn('{"name": "read_file"', sanitized)
        self.assertEqual(sanitized, "I'll check the file for compilation errors.")

    async def test_08_assistant_multi_turn_tool_execution_loop(self):
        """
        Proves ByteXCore executes tool calls emitted by the model, feeds the verified tool result
        back into conversation context, and yields a sanitized final response based on that content.
        """
        core = ByteXCore()
        core.clear_history()

        # Mock ai_router.stream_response:
        # Turn 1: model emits tool call to read 04_edge_cases.cpp
        # Turn 2: model sees file content in history and reports clean compilation
        turn1_output = (
            "I'll check the file for compilation errors.\n"
            "<tool_call>\n"
            '{"name": "read_file", "arguments": {"file_path": "04_edge_cases.cpp"}}\n'
            "</tool_call>"
        )
        turn2_output = (
            "I have inspected `04_edge_cases.cpp`. The source code compiles cleanly with no syntax errors. "
            "It properly includes `<iostream>` and handles input validation."
        )

        call_count = 0

        async def mock_stream_response(history, memory_context=""):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                yield turn1_output
            else:
                # In turn 2, verify tool result is in history!
                last_user_msg = history[-1]["content"]
                assert "[Tool Result for 'read_file']:" in last_user_msg, "Tool result was not passed into model context!"
                assert "04_edge_cases.cpp" in last_user_msg
                yield turn2_output

        with patch("core.assistant.ai_router.stream_response", side_effect=mock_stream_response):
            events = []
            async for ev in core.process_user_message("Check 04_edge_cases.cpp for compilation errors. If there are any, report them. Don't modify the file."):
                events.append(ev)

            # Verify events
            complete_events = [e for e in events if e.type == "ASSISTANT_COMPLETE"]
            self.assertEqual(len(complete_events), 1, "Expected exactly one ASSISTANT_COMPLETE event")
            final_msg = complete_events[0].message or complete_events[0].content

            # Verify no tool call leaked to user
            self.assertNotIn("<tool_call>", final_msg)
            self.assertNotIn("read_file", final_msg)
            self.assertIn("compiles cleanly with no syntax errors", final_msg)

            # Verify model was called twice (tool call + final answer)
            self.assertEqual(call_count, 2)

            # Verify history records tool execution so follow-up requests know the file was read
            tool_res_entries = [h for h in core.history if "[Tool Result for 'read_file']:" in h.get("content", "")]
            self.assertEqual(len(tool_res_entries), 1)


if __name__ == "__main__":
    unittest.main()

import unittest
import sys
import os
import shutil
import tempfile
import asyncio
import ast
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from skills.coding import CodingWorkspaceSkill, file_uri_to_path
from skills.base import ToolResult


class TestCompilerToolchainAndURICompat(unittest.TestCase):
    def setUp(self):
        self.skill = CodingWorkspaceSkill()

    # -------------------------------------------------------------------------
    # Task 3: Source-File URI Parsing
    # -------------------------------------------------------------------------
    def test_file_uri_to_path_macos_posix_absolute(self):
        """Standard macOS/POSIX file URI preserves leading slash and resolves correctly."""
        uri = "file:///Users/yashpatel/projects/main.cpp"
        resolved = file_uri_to_path(uri)
        self.assertEqual(str(resolved), "/Users/yashpatel/projects/main.cpp")
        self.assertTrue(resolved.is_absolute())

    def test_file_uri_to_path_percent_encoding_and_spaces(self):
        """Percent-encoded spaces, symbols, and special characters are correctly unquoted."""
        uri = "file:///Users/yashpatel/my%20code/project%231/01%20basic%2Btest.cpp"
        resolved = file_uri_to_path(uri)
        self.assertEqual(str(resolved), "/Users/yashpatel/my code/project#1/01 basic+test.cpp")

    def test_file_uri_to_path_windows_three_slashes(self):
        """Standard 3-slash Windows URI file:///C:/... strips leading slash from drive letter."""
        uri = "file:///C:/Users/yashpatel/Documents/test.cpp"
        resolved = file_uri_to_path(uri)
        # On POSIX Path('C:/Users/...') preserves 'C:/Users/...', on Windows it is C:\Users\...
        self.assertEqual(str(resolved).replace("\\", "/"), "C:/Users/yashpatel/Documents/test.cpp")

    def test_file_uri_to_path_windows_two_slashes_netloc(self):
        """Windows 2-slash URI file://C:/... where host is drive letter resolves correctly."""
        uri = "file://C:/Users/yashpatel/Documents/test.cpp"
        resolved = file_uri_to_path(uri)
        self.assertEqual(str(resolved).replace("\\", "/"), "C:/Users/yashpatel/Documents/test.cpp")

    def test_file_uri_to_path_unc_path(self):
        """UNC paths file://server/share/file.cpp resolve to //server/share/file.cpp."""
        uri = "file://buildserver/shares/code/main.cpp"
        resolved = file_uri_to_path(uri)
        self.assertEqual(str(resolved).replace("\\", "/"), "//buildserver/shares/code/main.cpp")

    def test_file_uri_to_path_localhost_netloc(self):
        """file://localhost/path URIs treat localhost as empty netloc."""
        uri = "file://localhost/Users/yashpatel/code/main.py"
        resolved = file_uri_to_path(uri)
        self.assertEqual(str(resolved), "/Users/yashpatel/code/main.py")

    def test_file_uri_to_path_plain_filesystem_paths(self):
        """Normal filesystem paths without file: prefix pass through unchanged."""
        p_unix = "/Users/yashpatel/test.cpp"
        p_win = r"C:\Users\yashpatel\test.cpp"
        self.assertEqual(str(file_uri_to_path(p_unix)), p_unix)
        self.assertEqual(str(file_uri_to_path(p_win)), p_win)

    # -------------------------------------------------------------------------
    # Task 1: Platform-Aware Compiler Discovery
    # -------------------------------------------------------------------------
    def test_macos_compiler_discovery(self):
        """On macOS, _resolve_runner safely discovers clang++, g++, or c++ without tracebacks."""
        with patch("sys.platform", "darwin"):
            runner, compiler, name, lang = self.skill._resolve_runner("cpp")
            self.assertEqual(lang, "C++")
            # If clang++ or g++ exists on this macOS machine (Xcode CLT), verify path is valid executable
            if compiler:
                self.assertTrue(os.path.isabs(compiler) or shutil.which(compiler))
                self.assertIn(name, ["clang++", "g++", "c++"])

    def test_macos_c_compiler_discovery(self):
        """On macOS, C compiler discovery finds clang, gcc, or cc."""
        with patch("sys.platform", "darwin"):
            runner, compiler, name, lang = self.skill._resolve_runner("c")
            self.assertEqual(lang, "C")
            if compiler:
                self.assertTrue(os.path.isabs(compiler) or shutil.which(compiler))
                self.assertIn(name, ["clang", "gcc", "cc"])

    def test_windows_compiler_discovery_mocked(self):
        """On Windows, MinGW / LLVM candidates are queried and preserved."""
        def fake_exists(path_obj):
            return "mingw64" in str(path_obj).lower()

        with patch("sys.platform", "win32"), \
             patch("shutil.which", return_value=None), \
             patch.object(Path, "exists", fake_exists):
            runner, compiler, name, lang = self.skill._resolve_runner("cpp")
            self.assertEqual(lang, "C++")
            self.assertIsNotNone(compiler)
            self.assertIn("mingw", compiler.lower())

    def test_missing_compiler_actionable_error_macos(self):
        """Missing compiler on macOS returns actionable install instructions without traceback."""
        async def _run():
            with patch.object(self.skill, "_resolve_runner", return_value=(None, None, "clang++", "C++")):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    src_file = Path(tmp_dir) / "test.cpp"
                    src_file.write_text("int main(){return 0;}", encoding="utf-8")

                    # Test execute_code with missing compiler
                    res_exec = await self.skill._action_execute_code({"filename": str(src_file), "compile": True})
                    self.assertFalse(res_exec.success)
                    self.assertEqual(res_exec.data.get("status"), "COMPILER_NOT_FOUND")
                    self.assertIn("xcode-select --install", res_exec.message)
                    self.assertIn("brew install", res_exec.message)

                    # Test compile_code with missing compiler
                    res_comp = await self.skill._action_compile_code({"filename": str(src_file)})
                    self.assertFalse(res_comp.success)
                    self.assertEqual(res_comp.data.get("status"), "COMPILER_NOT_FOUND")
                    self.assertIn("xcode-select --install", res_comp.message)

        asyncio.run(_run())

    def test_missing_compiler_actionable_error_windows(self):
        """Missing compiler on Windows returns MinGW / Visual Studio guidance."""
        async def _run():
            with patch("sys.platform", "win32"), \
                 patch.object(self.skill, "_resolve_runner", return_value=(None, None, "g++", "C++")):
                with tempfile.TemporaryDirectory() as tmp_dir:
                    src_file = Path(tmp_dir) / "test.cpp"
                    src_file.write_text("int main(){return 0;}", encoding="utf-8")

                    res_comp = await self.skill._action_compile_code({"filename": str(src_file)})
                    self.assertFalse(res_comp.success)
                    self.assertEqual(res_comp.data.get("status"), "COMPILER_NOT_FOUND")
                    self.assertIn("MinGW", res_comp.message)
                    self.assertIn("Visual Studio", res_comp.message)

        asyncio.run(_run())

    # -------------------------------------------------------------------------
    # Task 2: Platform-Appropriate Outputs (No .exe assumption on macOS)
    # -------------------------------------------------------------------------
    def test_native_binary_naming_on_macos(self):
        """Compilation output executable on macOS does not have .exe suffix."""
        async def _run():
            runner, compiler, _, _ = self.skill._resolve_runner("cpp")
            if not compiler:
                self.skipTest("No C++ compiler available on host machine")

            with tempfile.TemporaryDirectory() as tmp_dir:
                src_file = Path(tmp_dir) / "prog.cpp"
                src_file.write_text("#include <iostream>\nint main(){ std::cout << \"OK\" << std::endl; return 0; }", encoding="utf-8")

                with patch("sys.platform", "darwin"):
                    res = await self.skill._action_compile_code({"filename": str(src_file)})
                    self.assertTrue(res.success)
                    # Verify command did not append .exe on macOS
                    cmd = res.data.get("command", "")
                    self.assertNotIn(".exe", cmd)

        asyncio.run(_run())

    def test_windows_binary_naming_has_exe(self):
        """On Windows, compilation output executable uses .exe suffix."""
        async def _run():
            with tempfile.TemporaryDirectory() as tmp_dir:
                src_file = Path(tmp_dir) / "prog.cpp"
                src_file.write_text("#include <iostream>\nint main(){ std::cout << \"OK\" << std::endl; return 0; }", encoding="utf-8")

                async def fake_communicate():
                    return b"", b""

                mock_proc = MagicMock()
                mock_proc.communicate = fake_communicate
                mock_proc.returncode = 0

                async def fake_create_subprocess(*args, **kwargs):
                    return mock_proc

                with patch("sys.platform", "win32"), \
                     patch.object(self.skill, "_resolve_runner", return_value=(r"C:\MinGW\bin\g++.exe", r"C:\MinGW\bin\g++.exe", "g++", "C++")), \
                     patch("asyncio.create_subprocess_exec", side_effect=fake_create_subprocess):
                    res = await self.skill._action_compile_code({"filename": str(src_file)})
                    self.assertTrue(res.success)
                    cmd = res.data.get("command", "")
                    self.assertIn(".exe", cmd)

        asyncio.run(_run())

    # -------------------------------------------------------------------------
    # Task 4: Safe Stdin Handling (No hanging on unsupplied stdin)
    # -------------------------------------------------------------------------
    def test_no_stdin_does_not_hang_on_interactive_reads(self):
        """Program attempting to read stdin receives EOF (DEVNULL) immediately and does not hang."""
        async def _run():
            with tempfile.TemporaryDirectory() as tmp_dir:
                py_file = Path(tmp_dir) / "read_stdin.py"
                # This script attempts to read from stdin. If stdin is connected to an interactive terminal,
                # it would block until EOF or timeout. With stdin=DEVNULL, it immediately reads EOF.
                py_file.write_text(
                    "import sys\n"
                    "data = sys.stdin.read()\n"
                    "print(f'READ_{len(data)}_BYTES')\n",
                    encoding="utf-8"
                )

                # Execute with NO stdin data supplied
                res = await self.skill._action_execute_code({
                    "filename": str(py_file),
                    "timeout_seconds": 3
                })

                self.assertTrue(res.success)
                self.assertFalse(res.data.get("timed_out", True))
                self.assertIn("READ_0_BYTES", res.data.get("stdout", ""))

        asyncio.run(_run())

    def test_supplied_stdin_is_properly_delivered(self):
        """Supplied stdin input is delivered and output reflects the provided data."""
        async def _run():
            with tempfile.TemporaryDirectory() as tmp_dir:
                py_file = Path(tmp_dir) / "echo_stdin.py"
                py_file.write_text(
                    "import sys\n"
                    "line = sys.stdin.readline().strip()\n"
                    "print(f'GREETING:{line}')\n",
                    encoding="utf-8"
                )

                res = await self.skill._action_execute_code({
                    "filename": str(py_file),
                    "stdin": "Hello ByteX AI\n",
                    "timeout_seconds": 3
                })

                self.assertTrue(res.success)
                self.assertIn("GREETING:Hello ByteX AI", res.data.get("stdout", ""))

        asyncio.run(_run())

    # -------------------------------------------------------------------------
    # Task 5: VS Code Workspace Storage Path Resolution
    # -------------------------------------------------------------------------
    def test_vscode_workspace_storage_macos_candidates(self):
        """On macOS, workspace storage candidate paths point to ~/Library/Application Support/Code/..."""
        with patch("sys.platform", "darwin"), \
             patch("psutil.process_iter", return_value=[]):
            info = self.skill._detect_vscode_workspace_info()
            # If no actual VS Code directory exists, source is none and no crash
            self.assertIn(info.get("source"), ["none", "vscode_workspace_storage", "cached_vscode_workspace", "session_active_project"])

    def test_vscode_workspace_storage_mocked_macos_discovery(self):
        """When macOS VS Code workspaceStorage has an entry, it is discovered via file_uri_to_path."""
        with tempfile.TemporaryDirectory() as fake_home:
            fake_home_path = Path(fake_home)
            ws_dir = fake_home_path / "Library" / "Application Support" / "Code" / "User" / "workspaceStorage" / "mock_entry_123"
            ws_dir.mkdir(parents=True, exist_ok=True)

            target_ws = fake_home_path / "My Projects" / "AwesomeApp"
            target_ws.mkdir(parents=True, exist_ok=True)

            ws_json = ws_dir / "workspace.json"
            # Note percent-encoded folder URI with spaces
            ws_json.write_text(
                f'{{"folder": "file://{target_ws.as_posix().replace(" ", "%20")}"}}',
                encoding="utf-8"
            )

            with patch("sys.platform", "darwin"), \
                 patch.object(Path, "home", return_value=fake_home_path), \
                 patch("psutil.process_iter", return_value=[]):
                # Ensure no cached workspace
                self.skill._cached_vscode_workspace = None
                info = self.skill._detect_vscode_workspace_info()

                self.assertIsNotNone(info.get("workspace_root"))
                self.assertEqual(str(info.get("workspace_root")), str(target_ws))
                self.assertEqual(info.get("workspace_name"), "AwesomeApp")
                self.assertEqual(info.get("source"), "vscode_workspace_storage")


# -----------------------------------------------------------------------------
# Regression: CommandRouter _extract_target_file Consolidation & URL Protection
# -----------------------------------------------------------------------------
class TestCommandRouterTargetFileExtraction(unittest.TestCase):
    """
    Focused regression suite verifying:
    1. Only one effective _extract_target_file definition exists in CommandRouter.
    2. 'This file' and 'active file' behavior is preserved.
    3. HTTP/HTTPS URLs ending in code-file extensions (.html, .js, .cpp, etc.) are never extracted as local paths.
    4. Genuine macOS and Windows paths are correctly extracted.
    5. file:// URIs (standard, percent-encoded, and quoted with spaces) are handled.
    6. Messages containing both a web URL and a separate local path properly extract the local path.
    7. Webpage reading requests with URLs ending in code extensions route to read_webpage without collision.
    """

    def test_only_one_extract_target_file_definition_in_router(self):
        """Verify AST has exactly one definition of _extract_target_file in CommandRouter."""
        router_path = Path(__file__).parent.parent / "backend" / "core" / "command_router.py"
        with open(router_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        definitions = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "CommandRouter":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "_extract_target_file":
                        definitions.append(item.lineno)

        self.assertEqual(
            len(definitions),
            1,
            f"Expected exactly 1 definition of _extract_target_file in CommandRouter, found {len(definitions)} at lines {definitions}"
        )

    def test_active_file_and_this_file_handling(self):
        """Verify natural language references to active file return 'this file'."""
        queries = [
            "Read this file and explain it.",
            "Explain the active file.",
            "Tell me what current file does.",
            "Inspect this code please.",
            "Run code here.",
            "Explain the code.",
            "What does this source do?",
        ]
        for q in queries:
            target = CommandRouter._extract_target_file(q)
            self.assertEqual(target, "this file", f"Query '{q}' failed to resolve to 'this file'")

    def test_http_https_urls_not_extracted_as_local_paths(self):
        """Verify HTTP/HTTPS URLs ending in code extensions never extract local filesystem paths."""
        url_queries = [
            "https://example.com/index.html",
            "https://example.com/src/main.cpp",
            "http://localhost:3000/app.js",
            "https://domain.org/scripts/bundle.min.js",
            "http://127.0.0.1:8080/style.css",
            "https://api.github.com/repos/user/project/contents/main.py",
            "Read webpage https://example.com/index.html",
            "Check http://localhost:3000/app.js for documentation",
            "Visit https://example.com/src/main.cpp to see reference",
        ]
        for u in url_queries:
            target = CommandRouter._extract_target_file(u)
            self.assertIsNone(target, f"URL query '{u}' erroneously extracted target path: '{target}'")

    def test_genuine_macos_and_windows_paths(self):
        """Verify genuine local paths on macOS, Linux, and Windows are correctly extracted."""
        cases = [
            ("/Users/example/project/main.cpp", "/Users/example/project/main.cpp"),
            ("/var/folders/example/test.py", "/var/folders/example/test.py"),
            ("Please read /Users/yashpatel/code/app.ts now.", "/Users/yashpatel/code/app.ts"),
            ("src/main.cpp", "src/main.cpp"),
            ("01_basic.cpp", "01_basic.cpp"),
            ("backend/core/command_router.py", "backend/core/command_router.py"),
            (r"C:\project\main.cpp", r"C:\project\main.cpp"),
            (r"C:/project/src/main.cpp", r"C:/project/src/main.cpp"),
            (r"Analyze C:\Users\name\Desktop\test.cpp please", r"C:\Users\name\Desktop\test.cpp"),
        ]
        for text, expected in cases:
            target = CommandRouter._extract_target_file(text)
            self.assertEqual(target, expected, f"Input '{text}' extracted '{target}', expected '{expected}'")

    def test_file_uri_handling(self):
        """Verify file:// URIs (standard, percent-encoded, and quoted with spaces) are properly extracted."""
        cases = [
            ("file:///Users/example/project/main.cpp", "file:///Users/example/project/main.cpp"),
            ("file:///Users/example/my%20code/main.cpp", "file:///Users/example/my%20code/main.cpp"),
            ('"file:///Users/example/my code/main.cpp"', "file:///Users/example/my code/main.cpp"),
            ("(file:///Users/example/project/main.cpp)", "file:///Users/example/project/main.cpp"),
            ("Inspect file:///C:/Users/name/Documents/test.cpp.", "file:///C:/Users/name/Documents/test.cpp"),
        ]
        for text, expected in cases:
            target = CommandRouter._extract_target_file(text)
            self.assertEqual(target, expected, f"Input '{text}' extracted '{target}', expected '{expected}'")

    def test_mixed_web_url_and_separate_local_path(self):
        """Verify messages containing both a web URL and a local path extract the genuine local path."""
        cases = [
            (
                "Compare https://example.com/src/main.cpp with /Users/example/project/main.cpp",
                "/Users/example/project/main.cpp"
            ),
            (
                "Check https://example.com/index.html and update src/main.cpp",
                "src/main.cpp"
            ),
            (
                "Look at https://example.com/app.js and inspect this file",
                "this file"
            ),
            (
                r"Compare http://localhost:3000/app.js with C:\project\main.cpp",
                r"C:\project\main.cpp"
            ),
            (
                "Compare https://example.com/test.py with file:///Users/example/test.py",
                "file:///Users/example/test.py"
            ),
        ]
        for text, expected in cases:
            target = CommandRouter._extract_target_file(text)
            self.assertEqual(target, expected, f"Input '{text}' extracted '{target}', expected '{expected}'")

    def test_read_webpage_routing_with_code_extension_url(self):
        """Verify that webpage reading requests with URLs ending in code extensions route to read_webpage."""
        async def _run():
            res = await CommandRouter.parse_skill_intent("Read webpage https://example.com/index.html")
            self.assertIsNotNone(res, "Failed to route 'Read webpage https://example.com/index.html'")
            skill, args = res
            self.assertEqual(skill, "read_webpage")
            self.assertEqual(args.get("url"), "https://example.com/index.html")

            res2 = await CommandRouter.parse_skill_intent("Read webpage https://example.com/src/main.cpp")
            self.assertIsNotNone(res2, "Failed to route 'Read webpage https://example.com/src/main.cpp'")
            skill2, args2 = res2
            self.assertEqual(skill2, "read_webpage")
            self.assertEqual(args2.get("url"), "https://example.com/src/main.cpp")

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()


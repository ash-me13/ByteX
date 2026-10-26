import asyncio
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from skills.coding import CodingWorkspaceSkill

async def test_live_testing_cpp():
    with tempfile.TemporaryDirectory() as td:
        ws = Path(td)
        tf = ws / "testing.cpp"
        content = (
            "#include <iostream>\n"
            "using namespace std;\n\n"
            "int main() {\n"
            "    for (int i = 1; i <= 100; i++) {\n"
            "        if (i % 2 == 0) {\n"
            "            cout << i << \" \";\n"
            "        }\n"
            "    }\n"
            "    return 0;\n"
            "}\n"
        )
        tf.write_text(content, encoding="utf-8")
        
        skill = CodingWorkspaceSkill()
        skill._cached_vscode_workspace = ws

        prompt = "Optimize testing.cpp to reduce its time complexity. Show me what you would change, but don't modify the file."
        skill_name, args = await CommandRouter.parse_skill_intent(prompt)
        print(f"Skill: {skill_name}")
        print(f"Args: {args}")
        
        res = await skill.execute(args)
        print("\n--- Tool Result ---")
        print(f"Success: {res.success}")
        print(f"Verified: {res.verified}")
        print(f"Read Only: {res.data.get('read_only')}")
        print(f"\nMessage:\n{res.message.encode('ascii', errors='backslashreplace').decode('ascii')}")

        # Assertions
        assert res.success is True
        assert res.data.get("read_only") is True
        assert "binary search" not in res.message.lower()
        assert "unordered_set" not in res.message.lower()
        assert "Direct Step Incrementation" in res.message
        assert "i += 2" in res.message
        assert tf.read_text(encoding="utf-8") == content
        print("\n[PASSED] All live testing.cpp assertions passed successfully!")

if __name__ == "__main__":
    asyncio.run(test_live_testing_cpp())

import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import asyncio
from core.command_router import CommandRouter
from skills.registry import skill_registry

async def main():
    skill = skill_registry.get_skill("coding_workspace")
    temp_dir = Path(tempfile.mkdtemp(prefix="bytex_test_bad_"))
    bad_file = temp_dir / "bad_syntax.cpp"
    bad_code = """#include <iostream>
int main() {
    this_is_invalid_syntax_error();
    return 0;
}
"""
    bad_file.write_text(bad_code, encoding="utf-8")
    
    # Set active project
    skill._active_project_path = temp_dir
    skill._active_project_name = temp_dir.name

    cmd = "Compile and run bad_syntax.cpp. Show me the exact output and report any compilation errors. Don't modify the source file."
    h, r, s, d = await CommandRouter.route_command(cmd)

    print("HANDLED:", h)
    print("STATE:", s)
    print("RESPONSE:\n", r)
    print("DATA:\n", d)

    assert h is True
    assert s == "error"
    assert "Compilation failed" in r
    assert d.get("compiled") is False
    assert d.get("exit_code") != 0
    assert "this_is_invalid_syntax_error" in d.get("stderr")
    assert bad_file.read_text(encoding="utf-8") == bad_code, "Source file was modified!"
    print("\nCOMPILATION ERROR TEST PASSED!")

if __name__ == "__main__":
    asyncio.run(main())

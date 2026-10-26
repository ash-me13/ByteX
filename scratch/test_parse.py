import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from skills.coding import CodingWorkspaceSkill
from core.command_router import CommandRouter
import asyncio

initial_source = """#include <iostream>
using namespace std;

int main() {
    for (int i = 1; i <= 10; i++) {
        cout << i << endl;
        cout << "HELLO_BYTE_X" << endl;
    }
    return 0;
}
"""

targets = ["hellow_world", "RYznn", "HELLO_BYTE_X", "hellow_world"]

async def main():
    skill = CodingWorkspaceSkill()
    current_code = initial_source
    for tgt in targets:
        cmd = f"Fix 01_basic.cpp so {tgt} is printed only once after all the numbers."
        intent = await CommandRouter.parse_skill_intent(cmd)
        skill_name, args = intent
        reqs = skill._extract_semantic_requirements(args.get("instruction"), args.get("prompt"))
        print(f"\n--- Testing Target: '{tgt}' ---")
        print(f"Extracted target_string: '{reqs.get('target_string')}'")
        assert reqs.get("target_string") == tgt, f"Expected {tgt}, got {reqs.get('target_string')}"

        new_code = skill._apply_code_modification(current_code, args.get("instruction"), "01_basic.cpp", reqs)
        print("Resulting code:")
        print(new_code.strip())

        ok, summary, errors = skill._verify_code_semantics(new_code, current_code, args.get("instruction"), "01_basic.cpp", reqs)
        print(f"Verification OK: {ok}, Summary: {summary}")
        assert ok, f"Verification failed for {tgt}: {summary}"
        assert new_code.count(f'"{tgt}"') == 1, f"Expected exactly 1 occurrence of '{tgt}'"
        assert "for (int i = 1; i <= 10; i++)" in new_code, "Loop destroyed!"
        
        current_code = new_code

    print("\nALL CONSECUTIVE TARGET TESTS PASSED!")

if __name__ == "__main__":
    asyncio.run(main())

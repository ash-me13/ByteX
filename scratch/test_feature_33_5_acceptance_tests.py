"""
ByteX - Feature #33.5 Acceptance Tests Suite

Covers the 4 canonical acceptance workflows requested:
1. Acceptance Test 1: C++ Typo Auto-Fix (coutt -> cout) & Re-Execution
2. Acceptance Test 2: Python SyntaxError (def is_prime(n) -> def is_prime(n):)
3. Acceptance Test 3: Unsafe / Ambiguous Multi-Possibility Refusal
4. Acceptance Test 4: Bounded Fix Attempts (MAX_FIX_ATTEMPTS = 3) & Source Rollback
"""

import sys
import shutil
import asyncio
from pathlib import Path

# Set UTF-8
sys.stdout.reconfigure(encoding='utf-8')

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from skills.coding import CodingWorkspaceSkill
from skills.code_fixer import CodeFixEngine, FixMode
from skills.files import resolve_user_directory


async def main():
    print("=" * 80)
    print("RUNNING BYTE X FEATURE #33.5 ACCEPTANCE TESTS")
    print("=" * 80)

    desktop = resolve_user_directory("desktop")
    proj = desktop / "ByteXAcceptanceProj"
    if proj.exists():
        shutil.rmtree(proj, ignore_errors=True)

    skill = CodingWorkspaceSkill()
    await skill.execute({
        "action": "create_project",
        "project_name": "ByteXAcceptanceProj",
        "language": "cpp"
    })

    # ----------------------------------------------------
    # ACCEPTANCE TEST 1: C++ Typo Auto-Fix & Re-Execution
    # ----------------------------------------------------
    main_cpp = proj / "main.cpp"
    main_cpp.write_text("#include <iostream>\nusing namespace std;\n\nint main() {\n    coutt << \"Hello ByteX\";\n    return 0;\n}\n", encoding="utf-8")

    res1 = await skill.execute({
        "action": "fix_code_error",
        "file_path": str(main_cpp),
        "language": "cpp",
        "error_output": "main.cpp:5:5: error: 'coutt' was not declared in this scope",
        "project_name": "ByteXAcceptanceProj"
    })
    pass1 = res1.success and "cout << \"Hello ByteX\";" in main_cpp.read_text(encoding="utf-8")
    print("[Acceptance 1 - C++ Typo]:", "PASSED [OK]" if pass1 else "FAILED [X]")
    print(res1.message)
    print("-" * 60)

    # ----------------------------------------------------
    # ACCEPTANCE TEST 2: Python SyntaxError (Missing Colon)
    # ----------------------------------------------------
    main_py = proj / "main.py"
    main_py.write_text("def is_prime(n)\n    return True\n", encoding="utf-8")
    res2 = await skill.execute({
        "action": "fix_code_error",
        "file_path": str(main_py),
        "language": "python",
        "error_output": "  File \"main.py\", line 1\n    def is_prime(n)\n                   ^\nSyntaxError: expected ':'",
        "project_name": "ByteXAcceptanceProj"
    })
    pass2 = res2.success and "def is_prime(n):" in main_py.read_text(encoding="utf-8")
    print("[Acceptance 2 - Python Syntax]:", "PASSED [OK]" if pass2 else "FAILED [X]")
    print(res2.message)
    print("-" * 60)

    # ----------------------------------------------------
    # ACCEPTANCE TEST 3: Unsafe / Ambiguous Multi-Possibility Refusal
    # ----------------------------------------------------
    ambig_py = proj / "ambig.py"
    ambig_py.write_text("def process(data):\n    return data.magic_transform()\n", encoding="utf-8")
    res3 = await skill.execute({
        "action": "fix_code_error",
        "file_path": str(ambig_py),
        "language": "python",
        "error_output": "AttributeError: 'dict' object has no attribute 'magic_transform'",
        "project_name": "ByteXAcceptanceProj"
    })
    pass3 = not res3.data.get("fix_applied") and not res3.data.get("changed")
    print("[Acceptance 3 - Ambiguous Safe Refusal]:", "PASSED [OK]" if pass3 else "FAILED [X]")
    print(res3.message)
    print("-" * 60)

    # ----------------------------------------------------
    # ACCEPTANCE TEST 4: Fix Attempt Limit & Rollback
    # ----------------------------------------------------
    broken_py = proj / "broken.py"
    orig_code = "prin(1)\n"
    broken_py.write_text(orig_code, encoding="utf-8")

    async def fail_runner(p: Path):
        return {"success": False, "exit_code": 1, "stderr": "Unresolvable runtime error"}

    res4 = await CodeFixEngine.fix_code_file(
        target_file_path=broken_py,
        fix_mode=FixMode.AUTOMATIC,
        language="python",
        error_output="NameError: name 'prin' is not defined",
        execution_runner=fail_runner
    )
    pass4 = res4.rolled_back and broken_py.read_text(encoding="utf-8") == orig_code and res4.attempts <= 3
    print("[Acceptance 4 - Attempt Limit & Rollback]:", "PASSED [OK]" if pass4 else "FAILED [X]")
    print(res4.message)
    print("=" * 80)

    if proj.exists():
        shutil.rmtree(proj, ignore_errors=True)

    if not (pass1 and pass2 and pass3 and pass4):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())


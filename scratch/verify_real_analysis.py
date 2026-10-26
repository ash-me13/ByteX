import asyncio
import sys
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from skills.coding import CodingWorkspaceSkill

async def main():
    ws_dir = Path(r"c:\Users\ryzzn\OneDrive\Desktop\ByteX_Real_Test")
    test_file = ws_dir / "testing.cpp"
    source = (
        "#include <iostream>\n"
        "using namespace std;\n\n"
        "int main() {\n"
        "    cout << \"Even numbers from 1 to 100:\" << endl;\n"
        "    for (int i = 1; i <= 100; i++) {\n"
        "        if (i % 2 == 0) {\n"
        "            cout << i << \" \";\n"
        "        }\n"
        "    }\n"
        "    cout << endl;\n"
        "    return 0;\n"
        "}\n"
    )
    test_file.write_text(source, encoding="utf-8")
    md5_before = hashlib.md5(test_file.read_bytes()).hexdigest()

    skill = CodingWorkspaceSkill()
    skill._cached_vscode_workspace = ws_dir

    prompt = "Analyze testing.cpp and explain its time and space complexity. Don't modify the file. Also tell me if there is a more efficient approach."
    skill_name, args = await CommandRouter.parse_skill_intent(prompt)
    print(f"ROUTED TO: {skill_name} with action='{args.get('action')}', filename='{args.get('filename')}'")

    res = await skill.execute(args)
    print(f"SUCCESS: {res.success}")
    print(f"VERIFIED: {res.verified}")
    print(f"READ ONLY: {res.data.get('read_only')}")

    md5_after = hashlib.md5(test_file.read_bytes()).hexdigest()
    print(f"MD5 MATCH (0 WRITES OCCURRED): {md5_before == md5_after}")
    print("\n" + res.message)

if __name__ == "__main__":
    asyncio.run(main())

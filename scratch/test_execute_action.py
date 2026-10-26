import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import asyncio
from skills.coding import CodingWorkspaceSkill

async def test():
    skill = CodingWorkspaceSkill()
    res = await skill.execute({
        "action": "execute_code",
        "filename": "01_basic.cpp"
    })
    print("SUCCESS:", res.success)
    print("ACTION:", res.action)
    print("MESSAGE:\n", res.message)
    print("DATA:\n", res.data)

asyncio.run(test())

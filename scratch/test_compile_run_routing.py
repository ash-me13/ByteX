import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import asyncio
from core.command_router import CommandRouter
from agent.planner import ByteXPlanner

test_cases = [
    "Compile and run 01_basic.cpp. Show me the exact output and report any compilation errors. Don't modify the source file.",
    "Compile 01_basic.cpp. Show me any compilation errors. Don't modify the source file.",
    "Run 01_basic.cpp",
    "Compile and run main.cpp",
    "Compile 01_basic.cpp but don't run it"
]

async def main():
    for cmd in test_cases:
        print(f"\n==========================================")
        print(f"TEST: {cmd}")
        print(f"==========================================")
        
        parsed = await CommandRouter.parse_skill_intent(cmd)
        print("parse_skill_intent:", parsed)

        classification = await CommandRouter.classify_request(cmd)
        print("classify_request:", classification)

        plan = ByteXPlanner.generate_plan(cmd)
        print("generate_plan:", plan.steps[0].arguments if plan else None)

        h, r, s, d = await CommandRouter.route_command(cmd)
        print(f"route_command: Handled={h}, State={s}")
        print(f"Response preview: {r[:100]}...")

if __name__ == "__main__":
    asyncio.run(main())

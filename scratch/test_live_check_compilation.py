import sys
sys.path.insert(0, 'backend')
import asyncio
from core.assistant import ByteXCore

async def test():
    core = ByteXCore()
    turn1 = "Check 04_edge_cases.cpp for compilation errors. If there are any, report them. Don't modify the file."
    print("--- TURN 1 ---")
    async for ev in core.process_user_message(turn1):
        if ev.type == "ASSISTANT_COMPLETE":
            print("Turn 1 Response:\n", ev.message or ev.content)
            
    turn2 = "Can you confirm if you were able to read or check 04_edge_cases.cpp?"
    print("\n--- TURN 2 ---")
    async for ev in core.process_user_message(turn2):
        if ev.type == "ASSISTANT_COMPLETE":
            print("Turn 2 Response:\n", ev.message or ev.content)

if __name__ == "__main__":
    asyncio.run(test())

import asyncio
import sys
from pathlib import Path

# Add backend to sys.path
sys.path.insert(0, str(Path(r"c:\Users\ryzzn\OneDrive\Desktop\ByteX Core\backend")))

from core.command_router import CommandRouter

test_queries = [
    "Change main.cpp to print Hello World.",
    "Add a loop to main.cpp.",
    "Fix main.cpp.",
    "Explain main.cpp.",
    "Analyze main.cpp.",
    "Optimize main.cpp.",
    "Run main.cpp.",
    "Compile main.cpp.",
    "Add a function to main.cpp that calculates factorial.",
    "Remove the old loop from main.cpp.",
    "Change the output to Hello ByteX.",
]

async def main():
    print("Testing Short Natural-Language Coding Commands Routing:")
    print("-" * 60)
    for q in test_queries:
        skill, args = await CommandRouter.parse_skill_intent(q)
        print(f"Query : '{q}'")
        print(f"Skill : {skill}")
        print(f"Args  : {args}")
        print("-" * 60)

if __name__ == "__main__":
    asyncio.run(main())

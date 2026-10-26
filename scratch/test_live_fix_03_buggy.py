import sys
import asyncio
import tempfile
import re
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from core.command_router import CommandRouter
from agent.planner import ByteXPlanner
from agent.models import AgentPlan, PlanStep, StepState
from skills.diagnostics import CodeDiagnosticEngine
from skills.code_fixer import CodeFixEngine, CodePatch
from skills.coding import CodingWorkspaceSkill

BUGGY_SOURCE = """#include <iostream>
using namespace std;

int main() {
    int a = 10;
    int b = 20;
    int sum = a + b // Intentional compilation error: missing semicolon
    cout << "Sum: " << sum << endl;
    return 0;
}
"""

def test_insert_statement_terminator():
    def _insert_statement_terminator(line: str, terminator: str = ";"):
        m_comment = re.search(r"(\s*(?://|/\*|#).*)$", line)
        if m_comment:
            code_part = line[:m_comment.start()]
            comment_part = line[m_comment.start():]
        else:
            code_part = line
            comment_part = ""

        code_stripped = code_part.rstrip()
        if not code_stripped:
            return None
        if code_stripped.endswith((";", "{", "}", ":", ">", ",")):
            return None

        return code_stripped + terminator + comment_part

    line = "    int sum = a + b // Intentional compilation error: missing semicolon"
    fixed = _insert_statement_terminator(line)
    print("Fixed line:", fixed)
    assert fixed == "    int sum = a + b; // Intentional compilation error: missing semicolon"
    print("test_insert_statement_terminator: PASSED")

async def test_full_pipeline_on_temp_file():
    tmp_dir = Path(tempfile.gettempdir()) / "bytex_test_buggy"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = tmp_dir / "03_buggy.cpp"
    tmp_file.write_text(BUGGY_SOURCE, encoding="utf-8")

    goal = "Fix the compilation error in 03_buggy.cpp. Preserve the existing code and make only the necessary change. Then compile and run it, and show me the output."
    cand = CommandRouter._extract_target_file(goal)
    print("Extracted target:", cand)
    assert cand == "03_buggy.cpp"

if __name__ == "__main__":
    test_insert_statement_terminator()
    asyncio.run(test_full_pipeline_on_temp_file())

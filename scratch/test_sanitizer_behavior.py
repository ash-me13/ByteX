import sys
sys.path.insert(0, 'backend')
import asyncio
from core.response_sanitizer import ResponseSanitizer

async def test():
    raw = '''I'll check the file for compilation errors.
<tool_call>
{"name": "read_file", "arguments": {"file_path": "04_edge_cases.cpp"}}
</tool_call>'''
    tool_info = ResponseSanitizer.extract_tool_call(raw)
    print('Tool info:', tool_info)
    exec_res = await ResponseSanitizer.extract_and_execute_tool_if_present(raw)
    print('Executed msg preview:\n', exec_res[:150] if exec_res else None)
    sanitized = ResponseSanitizer.sanitize(raw)
    print('Sanitized:\n', repr(sanitized))

if __name__ == "__main__":
    asyncio.run(test())

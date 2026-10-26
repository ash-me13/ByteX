import asyncio
import json
import websockets
from pathlib import Path

TARGET_FILE = Path(r"C:\Users\ryzzn\OneDrive\Desktop\ByteX_Test_Lab\03_buggy.cpp")

async def run_live_test():
    uri = "ws://127.0.0.1:8000/ws"
    prompt = "Fix the compilation error in 03_buggy.cpp. Preserve the existing code and make only the necessary change. Then compile and run it, and show me the output."
    
    print(f"Connecting to live backend at {uri}...")
    async with websockets.connect(uri) as ws:
        print(f"Sending prompt: {prompt}")
        await ws.send(json.dumps({"message": prompt}))

        final_msg = None
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=25.0)
                evt = json.loads(raw)
                evt_type = evt.get("type")
                if evt_type == "ASSISTANT_COMPLETE":
                    final_msg = evt.get("message")
                    break
            except asyncio.TimeoutError:
                print("WebSocket receive timed out!")
                break

        print("\n" + "=" * 60)
        print("LIVE WEBSOCKET FINAL RESPONSE:")
        print("=" * 60)
        print(final_msg)
        print("=" * 60 + "\n")

        # Verify on-disk file
        current_content = TARGET_FILE.read_text(encoding="utf-8")
        print("ON-DISK FILE CONTENT:")
        print("-" * 40)
        print(current_content)
        print("-" * 40)

        # Assertions
        assert final_msg is not None, "Did not receive final response message"
        assert "Sum: 30" in final_msg, f"Expected 'Sum: 30' in response, got: {final_msg}"
        assert "int sum = a + b; // Intentional compilation error: missing semicolon" in current_content, "Missing semicolon fix not found on disk!"
        assert "int sum = a + b // Intentional compilation error: missing semicolon" not in current_content, "Unfixed buggy line still present on disk!"
        assert "#include <iostream>" in current_content, "Existing code structure was modified!"
        assert "cout << \"Sum: \" << sum << endl;" in current_content, "cout statement missing or modified!"

        print("\nALL LIVE BACKEND VERIFICATION CHECKS PASSED SUCCESSFULLY!\n")

if __name__ == "__main__":
    asyncio.run(run_live_test())

import asyncio
import json
import websockets

async def run_live_command(ws, cmd):
    print(f"\n==========================================")
    print(f"SENDING: {cmd}")
    print(f"==========================================")
    await ws.send(json.dumps({"message": cmd}))
    response_text = ""
    while True:
        raw = await ws.recv()
        evt = json.loads(raw)
        evt_type = evt.get("type")
        evt_state = evt.get("state")
        if evt_type == "ASSISTANT_COMPLETE":
            response_text = evt.get("message", "")
            print(f"[ASSISTANT RESPONSE]\n{response_text}\n")
        if evt_type == "STATE_CHANGE" and evt_state == "idle":
            break
    return response_text

async def main():
    uri = "ws://127.0.0.1:8000/ws"
    async with websockets.connect(uri) as ws:
        init_raw = await ws.recv()
        print("Initial WS event:", init_raw)

        # 1. hellow_world
        resp1 = await run_live_command(ws, "Fix 01_basic.cpp so hellow_world is printed only once after all the numbers.")
        assert "EXECUTION_VERIFIED: Output verified with target 'hellow_world'." in resp1
        assert "HELLO_BYTE_X" not in resp1

        # 2. RYznn
        resp2 = await run_live_command(ws, "Fix 01_basic.cpp so RYznn is printed only once after all the numbers.")
        assert "EXECUTION_VERIFIED: Output verified with target 'RYznn'." in resp2
        assert "hellow_world" not in resp2
        assert "HELLO_BYTE_X" not in resp2

        # 3. HELLO_BYTE_X
        resp3 = await run_live_command(ws, "Fix 01_basic.cpp so HELLO_BYTE_X is printed only once after all the numbers.")
        assert "EXECUTION_VERIFIED: Output verified with target 'HELLO_BYTE_X'." in resp3
        assert "RYznn" not in resp3

        # 4. Consecutive change back to hellow_world
        resp4 = await run_live_command(ws, "Fix 01_basic.cpp so hellow_world is printed only once after all the numbers.")
        assert "EXECUTION_VERIFIED: Output verified with target 'hellow_world'." in resp4
        assert "HELLO_BYTE_X" not in resp4

        print("\nALL LIVE WEBSOCKET TESTS PASSED PERFECTLY!")

if __name__ == "__main__":
    asyncio.run(main())

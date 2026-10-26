import asyncio
import json
import websockets

async def run_cmd(ws, cmd):
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

        # 1. Exact user command
        cmd1 = "Compile and run 01_basic.cpp. Show me the exact output and report any compilation errors. Don't modify the source file."
        resp1 = await run_cmd(ws, cmd1)
        assert "no registered safe pipeline matches" not in resp1, "Still failed with no registered safe pipeline matches!"
        assert "executed successfully" in resp1 or "Output:" in resp1
        print("EXACT USER COMMAND VERIFIED OVER WEBSOCKET!")

        # 2. Compile-only command
        cmd2 = "Compile 01_basic.cpp. Show me any compilation errors. Don't modify the source file."
        resp2 = await run_cmd(ws, cmd2)
        assert "no registered safe pipeline matches" not in resp2
        assert "Successfully compiled" in resp2
        print("COMPILE-ONLY COMMAND VERIFIED OVER WEBSOCKET!")

        # 3. Run-only command
        cmd3 = "Run 01_basic.cpp"
        resp3 = await run_cmd(ws, cmd3)
        assert "no registered safe pipeline matches" not in resp3
        assert "executed successfully" in resp3
        print("RUN-ONLY COMMAND VERIFIED OVER WEBSOCKET!")

        print("\nALL LIVE WEBSOCKET TESTS PASSED!")

if __name__ == "__main__":
    asyncio.run(main())

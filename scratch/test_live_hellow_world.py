import asyncio
import json
import websockets

async def test_live():
    uri = "ws://127.0.0.1:8000/ws"
    async with websockets.connect(uri) as ws:
        init_raw = await ws.recv()
        print("Initial WS event:", init_raw)

        cmd = "Fix 01_basic.cpp so hellow_world is printed only once after all the numbers."
        print(f"Sending: {cmd}")
        await ws.send(json.dumps({"message": cmd}))
        
        while True:
            raw = await ws.recv()
            evt = json.loads(raw)
            evt_type = evt.get("type")
            evt_state = evt.get("state")
            if evt_type == "ASSISTANT_COMPLETE":
                msg = evt.get("message", "")
                print(f"[ASSISTANT RESPONSE]\n{msg}\n")
            if evt_type == "STATE_CHANGE" and evt_state == "idle":
                break

if __name__ == "__main__":
    asyncio.run(test_live())

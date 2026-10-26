import asyncio
import json
import websockets

async def test_live():
    uri = "ws://127.0.0.1:8000/ws"
    async with websockets.connect(uri) as ws:
        init_raw = await ws.recv()
        print("Initial WS event:", init_raw)

        # Test 1
        print("\n" + "="*60)
        print("TEST 1: Change 01_basic.cpp so it prints numbers from 1 to 10.")
        print("="*60)
        await ws.send(json.dumps({"message": "Change 01_basic.cpp so it prints numbers from 1 to 10."}))
        
        test1_success = False
        while True:
            raw = await ws.recv()
            evt = json.loads(raw)
            evt_type = evt.get("type")
            evt_state = evt.get("state")
            print(f"[WS EVENT] Type: {evt_type}, State: {evt_state}")
            if evt_type == "ASSISTANT_COMPLETE":
                msg = evt.get("message", "")
                print(f"[ASSISTANT RESPONSE]\n{msg}\n")
                if "Successfully modified" in msg and "01_basic.cpp" in msg:
                    test1_success = True
            if evt_type == "STATE_CHANGE" and evt_state == "idle":
                break

        # Test 2
        print("\n" + "="*60)
        print("TEST 2: Add a message after the existing output in 01_basic.cpp that says HELLO_BYTE_X.")
        print("="*60)
        await ws.send(json.dumps({"message": "Add a message after the existing output in 01_basic.cpp that says HELLO_BYTE_X."}))
        
        test2_success = False
        while True:
            raw = await ws.recv()
            evt = json.loads(raw)
            evt_type = evt.get("type")
            evt_state = evt.get("state")
            print(f"[WS EVENT] Type: {evt_type}, State: {evt_state}")
            if evt_type == "ASSISTANT_COMPLETE":
                msg = evt.get("message", "")
                print(f"[ASSISTANT RESPONSE]\n{msg}\n")
                if "Successfully modified" in msg and "01_basic.cpp" in msg:
                    test2_success = True
            if evt_type == "STATE_CHANGE" and evt_state == "idle":
                break

        print("\n" + "="*60)
        print(f"RESULTS: Test 1 Success = {test1_success}, Test 2 Success = {test2_success}")
        print("="*60)
        assert test1_success, "Test 1 failed!"
        assert test2_success, "Test 2 failed!"
        print("ALL LIVE TESTS PASSED!")

if __name__ == "__main__":
    asyncio.run(test_live())

import asyncio
import json
import websockets

async def test_live_ws():
    uri = "ws://127.0.0.1:8000/ws"
    print(f"Connecting to live backend at {uri}...")
    async with websockets.connect(uri) as ws:
        init_raw = await ws.recv()
        print("Connected! Initial event:", init_raw)

        # TURN 1
        prompt1 = "Check 04_edge_cases.cpp for compilation errors. If there are any, report them. Don't modify the file."
        print("\n" + "="*70)
        print(f"SENDING TURN 1: {prompt1}")
        print("="*70)
        await ws.send(json.dumps({"message": prompt1}))

        turn1_response = ""
        while True:
            raw = await ws.recv()
            evt = json.loads(raw)
            evt_type = evt.get("type")
            evt_state = evt.get("state")
            if evt_type == "STATE_CHANGE":
                print(f"[WS STATE] -> {evt_state}")
            elif evt_type == "ASSISTANT_COMPLETE":
                turn1_response = evt.get("message") or evt.get("content") or ""
                print(f"\n[WS ASSISTANT_COMPLETE Turn 1]:\n{turn1_response}\n")
            if evt_type == "STATE_CHANGE" and evt_state == "idle":
                break

        # Verification for Turn 1
        assert "<tool_call>" not in turn1_response, "Leaked <tool_call> in Turn 1!"
        assert "</tool_call>" not in turn1_response, "Leaked </tool_call> in Turn 1!"
        assert "04_edge_cases.cpp" in turn1_response, "Turn 1 did not mention 04_edge_cases.cpp"

        # TURN 2: Follow-up check
        prompt2 = "Can you confirm if you were able to read or check 04_edge_cases.cpp?"
        print("\n" + "="*70)
        print(f"SENDING TURN 2: {prompt2}")
        print("="*70)
        await ws.send(json.dumps({"message": prompt2}))

        turn2_response = ""
        while True:
            raw = await ws.recv()
            evt = json.loads(raw)
            evt_type = evt.get("type")
            evt_state = evt.get("state")
            if evt_type == "STATE_CHANGE":
                print(f"[WS STATE] -> {evt_state}")
            elif evt_type == "ASSISTANT_COMPLETE":
                turn2_response = evt.get("message") or evt.get("content") or ""
                print(f"\n[WS ASSISTANT_COMPLETE Turn 2]:\n{turn2_response}\n")
            if evt_type == "STATE_CHANGE" and evt_state == "idle":
                break

        # Verification for Turn 2
        assert "<tool_call>" not in turn2_response, "Leaked <tool_call> in Turn 2!"
        assert "did not successfully read the file" not in turn2_response.lower(), "Assistant claimed it did not successfully read the file!"
        assert "04_edge_cases.cpp" in turn2_response, "Turn 2 did not mention 04_edge_cases.cpp"

        print("="*70)
        print("LIVE WEBSOCKET TEST PASSED SUCCESSFULLY!")
        print("="*70)

if __name__ == "__main__":
    asyncio.run(test_live_ws())

import os
import sys
import json
import asyncio
import websockets

sys.stdout.reconfigure(encoding='utf-8')

WS_URL = "ws://127.0.0.1:8000/ws"

async def receive_until_complete_or_idle(ws, timeout=30.0):
    events = []
    text_content = ""
    start_time = asyncio.get_event_loop().time()
    
    while True:
        elapsed = asyncio.get_event_loop().time() - start_time
        if elapsed > timeout:
            raise TimeoutError(f"Timed out waiting for completion after {timeout}s")
        
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout - elapsed)
            ev = json.loads(raw)
            events.append(ev)
            ev_type = ev.get("type")
            
            if ev_type == "ASSISTANT_DELTA":
                text_content += ev.get("content") or ev.get("message") or ""
            elif ev_type in ["ASSISTANT_COMPLETE", "ASSISTANT_MESSAGE"]:
                msg = ev.get("message") or ev.get("content") or ""
                if msg:
                    text_content = msg
            elif ev_type == "ERROR":
                text_content = ev.get("message", "Error")
                break
            elif ev_type == "STATE_CHANGE" and ev.get("state") == "idle" and len(events) > 1:
                break
        except asyncio.TimeoutError:
            break
            
    return text_content, events

async def run_websocket_suite():
    print("=" * 80)
    print("BYTEX — WEBSOCKET END-TO-END VERIFICATION SUITE")
    print("=" * 80)

    # -------------------------------------------------------------
    # TEST 1: "Hello ByteX"
    # -------------------------------------------------------------
    print("\n--- TEST 1: Hello ByteX ---")
    async with websockets.connect(WS_URL) as ws:
        # Initial greeting event on connect
        init_raw = await ws.recv()
        init_ev = json.loads(init_raw)
        print(f"WS Handshake Event: {init_ev}")
        assert init_ev.get("type") == "STATE_CHANGE"

        # Send command
        await ws.send(json.dumps({"message": "Hello ByteX"}))
        resp, events = await receive_until_complete_or_idle(ws, timeout=20.0)
        print(f"TEST 1 Response: {resp}")
        print(f"TEST 1 Event Types: {[e.get('type') for e in events]}")
        assert "unavailable" not in resp.lower(), f"Unexpected unavailable response: {resp}"
        assert len(resp.strip()) > 0, "Empty response received"
        print("TEST 1 RESULT: PASSED [OK]")

    # -------------------------------------------------------------
    # TEST 2: "What is JavaScript?"
    # -------------------------------------------------------------
    print("\n--- TEST 2: What is JavaScript? ---")
    async with websockets.connect(WS_URL) as ws:
        await ws.recv() # init event
        await ws.send(json.dumps({"message": "What is JavaScript?"}))
        resp, events = await receive_until_complete_or_idle(ws, timeout=20.0)
        print(f"TEST 2 Response (First 150 chars): {resp[:150]}...")
        assert "javascript" in resp.lower() or "programming" in resp.lower() or "language" in resp.lower()
        print("TEST 2 RESULT: PASSED [OK]")

    # -------------------------------------------------------------
    # TEST 3: "Open Notepad."
    # -------------------------------------------------------------
    print("\n--- TEST 3: Open Notepad. ---")
    async with websockets.connect(WS_URL) as ws:
        await ws.recv()
        await ws.send(json.dumps({"message": "Open Notepad"}))
        resp, events = await receive_until_complete_or_idle(ws, timeout=15.0)
        print(f"TEST 3 Response: {resp}")
        assert "notepad" in resp.lower()
        print("TEST 3 RESULT: PASSED [OK]")

    # -------------------------------------------------------------
    # TEST 4: "Open Notepad and type hello."
    # -------------------------------------------------------------
    print("\n--- TEST 4: Open Notepad and type hello. ---")
    async with websockets.connect(WS_URL) as ws:
        await ws.recv()
        await ws.send(json.dumps({"message": "Open Notepad and type hello."}))
        resp, events = await receive_until_complete_or_idle(ws, timeout=25.0)
        print(f"TEST 4 Response: {resp}")
        assert "notepad" in resp.lower() or "typed" in resp.lower() or "hello" in resp.lower()
        print("TEST 4 RESULT: PASSED [OK]")

    # -------------------------------------------------------------
    # TEST 5: Screen Analysis
    # -------------------------------------------------------------
    print("\n--- TEST 5: Screen Analysis ---")
    async with websockets.connect(WS_URL) as ws:
        await ws.recv()
        await ws.send(json.dumps({"message": "What is on my screen?"}))
        resp, events = await receive_until_complete_or_idle(ws, timeout=20.0)
        print(f"TEST 5 Response: {resp}")
        assert len(resp.strip()) > 0
        print("TEST 5 RESULT: PASSED [OK]")

    # -------------------------------------------------------------
    # TEST 6: Disconnect and Reconnect
    # -------------------------------------------------------------
    print("\n--- TEST 6: Disconnect and Reconnect ---")
    ws1 = await websockets.connect(WS_URL)
    await ws1.recv()
    await ws1.close()
    print("Closed connection 1.")

    await asyncio.sleep(0.5)

    ws2 = await websockets.connect(WS_URL)
    init_ev2 = json.loads(await ws2.recv())
    print(f"Reconnected! Handshake Event: {init_ev2}")
    await ws2.send(json.dumps({"message": "Hello ByteX"}))
    resp, events = await receive_until_complete_or_idle(ws2, timeout=15.0)
    print(f"Post-Reconnect Response: {resp}")
    await ws2.close()
    assert len(resp.strip()) > 0
    print("TEST 6 RESULT: PASSED [OK]")

    # -------------------------------------------------------------
    # TEST 7: Page Refresh Simulation (Simultaneous connection turnover)
    # -------------------------------------------------------------
    print("\n--- TEST 7: Frontend Page Refresh Simulation ---")
    conn_pool = [await websockets.connect(WS_URL) for _ in range(3)]
    for c in conn_pool:
        await c.recv()
    
    # Close old connections simulate navigation
    for c in conn_pool[:-1]:
        await c.close()
    
    active_ws = conn_pool[-1]
    await active_ws.send(json.dumps({"message": "Check system status"}))
    resp, _ = await receive_until_complete_or_idle(active_ws, timeout=15.0)
    print(f"Active Tab Status Response: {resp}")
    await active_ws.close()
    assert "cpu" in resp.lower() or "system" in resp.lower()
    print("TEST 7 RESULT: PASSED [OK]")

    print("\n" + "=" * 80)
    print("ALL 7 WEBSOCKET TESTS COMPLETED WITH 100% SUCCESS!")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_websocket_suite())

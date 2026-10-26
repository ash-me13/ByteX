import asyncio
import json
import time
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import httpx
import websockets
from monitoring.collector import SystemMetricsCollector
from monitoring.service import LiveSystemMonitor
from services.phone_pairing import pairing_session_manager, secure_phone_manager

async def run_feature_37_and_38_test_suite():
    print("=" * 80)
    print("RUNNING FEATURES #37.1 - #37.4 & #38.1 TEST SUITE")
    print("=" * 80)

    # --------------------------------------------------------------------------
    # FEATURE #37.1: System Telemetry Metrics Collection
    # --------------------------------------------------------------------------
    print("\n[TEST #37.1] Testing System Telemetry Metrics Collection...")
    metrics = SystemMetricsCollector.collect_metrics()
    assert metrics.cpu_percent >= 0.0, "CPU percent invalid"
    assert metrics.ram_percent >= 0.0, "RAM percent invalid"
    assert metrics.ram_total_gb > 0.0, "RAM total invalid"
    assert metrics.disk_percent >= 0.0, "Disk percent invalid"
    print(f"-> Metrics collected: CPU={metrics.cpu_percent}%, RAM={metrics.ram_percent}%, Disk={metrics.disk_percent}%")
    print("[TEST #37.1] PASSED [OK]")

    # --------------------------------------------------------------------------
    # FEATURE #37.2: Real-time Metric Threshold Anomaly Detection
    # --------------------------------------------------------------------------
    print("\n[TEST #37.2] Testing Metric Threshold Anomaly Detection...")
    monitor = LiveSystemMonitor()
    events = monitor.evaluate_snapshot(metrics)
    assert isinstance(events, list), "Threshold events must be list"
    print(f"-> Threshold evaluation returned {len(events)} events")
    print("[TEST #37.2] PASSED [OK]")

    # --------------------------------------------------------------------------
    # FEATURE #37.3: Monitoring Service Lifecycle & Status
    # --------------------------------------------------------------------------
    print("\n[TEST #37.3] Testing Monitoring Service Endpoints via API...")
    async with httpx.AsyncClient() as client:
        status_res = await client.get("http://127.0.0.1:8000/api/monitoring/status")
        assert status_res.status_code == 200, f"Status failed: {status_res.text}"
        status_data = status_res.json()
        assert status_data["is_running"] is True, "Monitoring service should be running"
        print(f"-> Live monitoring status: running={status_data['is_running']}, poll_count={status_data['poll_count']}")

        events_res = await client.get("http://127.0.0.1:8000/api/monitoring/events")
        assert events_res.status_code == 200, f"Events failed: {events_res.text}"
        print(f"-> Retrieved {len(events_res.json().get('events', []))} historical events")
    print("[TEST #37.3] PASSED [OK]")

    # --------------------------------------------------------------------------
    # FEATURE #37.4: Live WebSocket Telemetry Broadcast
    # --------------------------------------------------------------------------
    print("\n[TEST #37.4] Testing WebSocket System Events Broadcast...")
    async with websockets.connect("ws://127.0.0.1:8000/ws") as ws:
        init_event = await asyncio.wait_for(ws.recv(), timeout=5.0)
        init_json = json.loads(init_event)
        assert init_json.get("type") == "STATE_CHANGE", f"Unexpected: {init_json}"
        print("-> Connected to /ws and received initial STATE_CHANGE event")
    print("[TEST #37.4] PASSED [OK]")

    # --------------------------------------------------------------------------
    # FEATURE #38.1: Complete Android Phone Pairing & Authentication Flow
    # --------------------------------------------------------------------------
    print("\n[TEST #38.1] Testing Full Feature #38.1 End-to-End Handshake Flow...")
    
    # Step 1: Create session
    async with httpx.AsyncClient() as client:
        create_res = await client.post("http://127.0.0.1:8000/api/phone/pairing/create")
        assert create_res.status_code == 200
        p_data = create_res.json()
        sid = p_data["session_id"]
        sec = p_data["secret"]
        print(f"-> Step 1: Created pairing session {sid}")

    # Step 2: Handshake via WebSocket
    async with websockets.connect("ws://127.0.0.1:8000/ws/phone") as ws:
        # Hello ACK
        hello = await asyncio.wait_for(ws.recv(), timeout=5.0)
        assert json.loads(hello)["type"] == "HELLO_ACK"
        print("-> Step 2: Received HELLO_ACK")

        # Send Pairing Request
        req_msg = {
            "type": "PAIRING_REQUEST",
            "protocol_version": 1,
            "session_id": sid,
            "secret": sec,
            "device_id": "test_pixel_suite_dev",
            "device_name": "Test Pixel Device",
            "platform": "Android"
        }
        await ws.send(json.dumps(req_msg))
        print("-> Step 3: Sent PAIRING_REQUEST")

        # Expect waiting
        wait_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
        assert json.loads(wait_msg)["type"] == "PAIRING_WAITING_APPROVAL"
        print("-> Step 4: Received PAIRING_WAITING_APPROVAL")

        # Step 3: PC Approves
        async with httpx.AsyncClient() as client:
            st_res = await client.get("http://127.0.0.1:8000/api/phone/pairing/status")
            assert st_res.status_code == 200
            assert st_res.json()["status"] == "PENDING_APPROVAL"
            print("-> Step 5: PC detected PENDING_APPROVAL")

            appr_res = await client.post(
                "http://127.0.0.1:8000/api/phone/pairing/approve",
                json={"session_id": sid, "approved": True}
            )
            assert appr_res.status_code == 200
            print("-> Step 6: PC approved session")

        # Step 4: Android receives PAIRING_APPROVED with raw token
        appr_msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
        appr_data = json.loads(appr_msg)
        assert appr_data["type"] == "PAIRING_APPROVED"
        assert appr_data["status"] == "CONNECTED"
        raw_token = appr_data.get("device_token")
        assert raw_token is not None and len(raw_token) > 10
        print("-> Step 7: Android received PAIRING_APPROVED with valid device_token")

    # Step 5: Authenticate reconnection
    async with websockets.connect("ws://127.0.0.1:8000/ws/phone") as ws:
        await ws.recv() # HELLO_ACK
        auth_msg = {
            "type": "AUTHENTICATE",
            "protocol_version": 1,
            "device_id": "test_pixel_suite_dev",
            "device_token": raw_token
        }
        await ws.send(json.dumps(auth_msg))
        auth_ack = await asyncio.wait_for(ws.recv(), timeout=5.0)
        assert json.loads(auth_ack)["type"] == "AUTH_SUCCESS"
        print("-> Step 8: Reconnection authenticated with AUTH_SUCCESS")

    # Step 6: Verify Device Listed and Revoke
    async with httpx.AsyncClient() as client:
        devs_res = await client.get("http://127.0.0.1:8000/api/phone/devices")
        assert any(d["device_id"] == "test_pixel_suite_dev" for d in devs_res.json())
        print("-> Step 9: Device verified in trusted devices list")

        revoke_res = await client.post("http://127.0.0.1:8000/api/phone/devices/test_pixel_suite_dev/revoke")
        assert revoke_res.status_code == 200
        print("-> Step 10: Device revocation verified successfully")

    print("[TEST #38.1] PASSED [OK]")

    print("\n" + "=" * 80)
    print("ALL TESTS IN SUITE PASSED SUCCESSFULLY [100% OK]")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_feature_37_and_38_test_suite())

"""
Pairing-session lifecycle tests. Stdlib only, fake clock, temporary storage:
they never touch backend/storage/trusted_phone_devices.json.

Run:  PYTHONPATH=backend python -m unittest tests.test_phone_pairing_lifecycle
"""
import json
import os
import tempfile
import unittest

from services.phone_pairing import (
    PAIRING_APPROVAL_TIMEOUT_SECONDS,
    PAIRING_EXPIRATION_SECONDS,
    PairingSessionManager,
    SecurePhoneConnectionManager,
    get_pairing_host,
)


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class PairingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = FakeClock()
        self.secure = SecurePhoneConnectionManager(storage_dir=self.tmp.name)
        self.mgr = PairingSessionManager(time_fn=self.clock, secure_manager=self.secure)

    def _request(self, session, device_id="phone-1", secret=None):
        return self.mgr.validate_pairing_request(
            session.session_id, secret if secret is not None else session.secret, device_id, "Test Phone"
        )

    # --- happy path -------------------------------------------------------
    def test_full_flow_registers_device_once_and_token_is_single_use(self):
        s = self.mgr.create_session()
        ok, _ = self._request(s)
        self.assertTrue(ok)
        ok, dev, _, token = self.mgr.approve_session(s.session_id, True)
        self.assertTrue(ok)
        self.assertTrue(self.secure.authenticate_device("phone-1", token))
        # the QR secret cannot be replayed
        ok, msg = self._request(s, device_id="phone-2")
        self.assertFalse(ok)

    # --- authorization ----------------------------------------------------
    def test_wrong_secret_rejected_and_session_stays_usable_for_owner(self):
        s = self.mgr.create_session()
        ok, _ = self._request(s, secret="0" * 32)
        self.assertFalse(ok)
        self.assertEqual(self.secure.list_trusted_devices(), [])
        self.assertTrue(self._request(s)[0])

    def test_non_string_inputs_rejected_not_crashing(self):
        s = self.mgr.create_session()
        self.assertFalse(self.mgr.validate_pairing_request(s.session_id, None, "p", "n")[0])
        self.assertFalse(self.mgr.validate_pairing_request(s.session_id, s.secret, 123, "n")[0])

    def test_oversized_device_identity_rejected(self):
        s = self.mgr.create_session()
        self.assertFalse(self.mgr.validate_pairing_request(s.session_id, s.secret, "x" * 500, "n")[0])

    def test_approve_unknown_session_does_not_fall_back_to_other_pending_session(self):
        s = self.mgr.create_session()
        self.assertTrue(self._request(s)[0])
        ok, dev, msg, token = self.mgr.approve_session("not-a-real-session", True)
        self.assertFalse(ok)
        self.assertIsNone(token)
        self.assertEqual(msg, "Session not found")
        self.assertEqual(self.secure.list_trusted_devices(), [])
        self.assertEqual(s.status, "PENDING_APPROVAL")

    def test_cannot_approve_session_nobody_requested(self):
        s = self.mgr.create_session()  # ACTIVE: no phone has asked yet
        ok, _, msg, token = self.mgr.approve_session(s.session_id, True)
        self.assertFalse(ok)
        self.assertIsNone(token)
        self.assertEqual(self.secure.list_trusted_devices(), [])

    # --- expiry -----------------------------------------------------------
    def test_expired_qr_cannot_start_pairing(self):
        s = self.mgr.create_session()
        self.clock.advance(PAIRING_EXPIRATION_SECONDS + 1)
        ok, msg = self._request(s)
        self.assertFalse(ok)
        self.assertEqual(msg, "Pairing code expired")

    def test_pending_session_cannot_be_approved_after_phone_gave_up(self):
        s = self.mgr.create_session()
        self.assertTrue(self._request(s)[0])
        self.clock.advance(PAIRING_APPROVAL_TIMEOUT_SECONDS + 1)
        ok, _, msg, token = self.mgr.approve_session(s.session_id, True)
        self.assertFalse(ok)
        self.assertIsNone(token)
        self.assertEqual(self.secure.list_trusted_devices(), [], "expired session must not create a trusted device")

    def test_expire_session_blocks_later_approval(self):
        s = self.mgr.create_session()
        self.assertTrue(self._request(s)[0])
        self.mgr.expire_session(s.session_id)  # what the WebSocket handler does on timeout
        ok, _, msg, token = self.mgr.approve_session(s.session_id, True)
        self.assertFalse(ok)
        self.assertEqual(self.secure.list_trusted_devices(), [])

    def test_cleanup_removes_stale_pending_and_approved_sessions(self):
        a = self.mgr.create_session()
        self._request(a)
        self.clock.advance(PAIRING_APPROVAL_TIMEOUT_SECONDS + 1)
        b = self.mgr.create_session()  # create_session runs cleanup
        self.assertNotIn(a.session_id, self.mgr.active_sessions)
        self.assertIn(b.session_id, self.mgr.active_sessions)

    def test_unclaimed_approved_token_is_discarded(self):
        s = self.mgr.create_session()
        self._request(s)
        self.mgr.approve_session(s.session_id, True)
        self.clock.advance(60)
        self.mgr.create_session()
        self.assertNotIn(s.session_id, self.mgr.active_sessions)

    def test_new_qr_replaces_unused_old_qr(self):
        a = self.mgr.create_session()
        b = self.mgr.create_session()
        self.assertFalse(self._request(a)[0])
        self.assertTrue(self._request(b)[0])

    def test_rejection_creates_no_device(self):
        s = self.mgr.create_session()
        self._request(s)
        ok, _, msg, token = self.mgr.approve_session(s.session_id, False)
        self.assertFalse(ok)
        self.assertEqual(self.secure.list_trusted_devices(), [])

    # --- device store -----------------------------------------------------
    def test_revoked_device_cannot_authenticate_and_token_not_stored_in_clear(self):
        s = self.mgr.create_session()
        self._request(s)
        _, _, _, token = self.mgr.approve_session(s.session_id, True)
        with open(os.path.join(self.tmp.name, "trusted_phone_devices.json"), encoding="utf-8") as f:
            raw = f.read()
        self.assertNotIn(token, raw)
        self.assertTrue(json.loads(raw)["phone-1"]["token_hash"])
        self.assertTrue(self.secure.revoke_device("phone-1"))
        self.assertFalse(self.secure.authenticate_device("phone-1", token))

    def test_wrong_token_rejected(self):
        s = self.mgr.create_session()
        self._request(s)
        self.mgr.approve_session(s.session_id, True)
        self.assertFalse(self.secure.authenticate_device("phone-1", "f" * 64))
        self.assertFalse(self.secure.authenticate_device("unknown", "f" * 64))

    def test_storage_dir_env_override_isolated_from_real_store(self):
        os.environ["BYTEX_STORAGE_DIR"] = self.tmp.name
        try:
            mgr = SecurePhoneConnectionManager()
            self.assertEqual(str(mgr.storage_file.parent), self.tmp.name)
        finally:
            del os.environ["BYTEX_STORAGE_DIR"]

    # --- QR address -------------------------------------------------------
    def test_qr_host_defaults_to_loopback_not_lan_ip(self):
        os.environ.pop("BYTEX_PHONE_HOST", None)
        self.assertEqual(get_pairing_host(), "127.0.0.1")
        self.assertEqual(self.mgr.create_session().to_qr_payload()["host"], "127.0.0.1")

    def test_qr_payload_has_no_device_token(self):
        s = self.mgr.create_session()
        payload = s.to_qr_payload()
        self.assertEqual(set(payload), {"v", "sid", "sec", "pc", "host", "port", "exp"})


if __name__ == "__main__":
    unittest.main()

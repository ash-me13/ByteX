# Phone companion: current status and what Wi-Fi support requires

**Status (2026-10-26): local-only.** The backend listens on `127.0.0.1` (`start_bytex.py`, `start_bytex.bat`
and `python backend/main.py` all say so explicitly), `LocalOnlyGuardMiddleware` rejects any non-loopback
peer, and the pairing QR carries `127.0.0.1` (override: `BYTEX_PHONE_HOST`). The phone can therefore pair only
through a loopback route such as an emulator or `adb reverse tcp:8000 tcp:8000`. Pairing over Wi-Fi does **not** work yet, on purpose.

## Why a path exception for `/ws/phone` is not enough
Pairing uses REST (`/api/phone/pairing/create|status|approve`, `/api/phone/devices/*`) **and** the WebSocket, and the
same port serves the general agent API (`/api/chat`, automations, memory, files, terminal skills). Opening the
port to the LAN would expose all of it, and anything on the LAN could create a session, read its secret and approve itself.

## Requirements before enabling it
1. A separate listener (own port / own ASGI app) that serves only the phone protocol. The general API stays on loopback.
2. Pairing creation and approval only on the loopback API, driven by the desktop UI (the human approval cannot be reached from the LAN).
3. Short-lived single-use secrets (done: 60 s, one use), bounded approval wait (done: 45 s), token delivery window (done: 10 s).
4. Transport security: TLS with certificate pinning from the QR, or an equivalent. Today the Android app uses `ws://`, and Android 9+
   blocks cleartext traffic unless the manifest allows it, so it would not connect anyway.
5. Device tokens: stored hashed on the PC (done); revocation takes effect on the next connection and must also close live sockets.
6. A permission model so a paired phone gets only phone features (today the only permission is `PHONE_CONNECTION`, and nothing else is reachable through it).
7. Tests: unauthorized access, replay, expiry, revocation, and "LAN peer cannot reach any general endpoint".
8. Android: real QR scanner, fail-closed token handling (see audit report).

## Residual risk in local-only mode
Any program running as the same user on the same machine can still call the loopback API (it has no login). The guard
stops other machines and web pages; it is not authentication.

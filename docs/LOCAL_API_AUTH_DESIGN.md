# ByteX local API authentication — threat model and design (2026-10-26)

Status: **DESIGN ONLY. Not implemented.** Reason in "Decision" below. Nothing here is a security claim about the running app.

## 1. What exists today
- Backend is bound to 127.0.0.1 (launchers and `main.py`), plus `LocalOnlyGuardMiddleware`: loopback peer, loopback Host, Origin allow-list for WebSockets and state-changing methods.
- There is **no authentication**. Every route (`/api/chat`, `/ws`, `/api/memory/clear`, `/api/automations*`, `/api/tasks`, phone pairing) trusts any caller that passes the guard.
- The UI is a browser page (Vite dev server on :5173) that calls `http://127.0.0.1:8000`. Browsers cannot read files, environment variables or the keychain.

## 2. Threat model
| Actor | Stopped today? | Stopped by auth? |
|---|---|---|
| Other machine on the LAN | Yes (loopback bind + peer check) | Defence in depth |
| Web page in the user's browser (CSRF / cross-site WebSocket) | Yes for unsafe methods and WS (Origin check). GET without Origin is allowed but CORS stops reading the response | Yes, if the token is not available to that page |
| DNS rebinding page | Yes (Host check) | Yes |
| **Another process running as the same user** | **No** | Only if it cannot obtain the token |
| Malware with the user's privileges | No | No (can read the browser profile, memory, files) |
| Prompt injection via web page / file / model output | Not an API-auth problem; see audit section on the tool gate | No |

## 3. The hard part: how does the trusted UI get the token?
Options evaluated:
1. **`VITE_*` variable / baked into the bundle.** The bundle is served to anyone who can fetch `http://127.0.0.1:5173`. Rejected: that is a public secret.
2. **Unauthenticated `/token` endpoint.** Any local process (or rebinding page that slips past the Host check) calls it. Rejected (also forbidden by the brief).
3. **Token in the URL** (`?token=` or `#token=`). Leaks into browser history, logs, `ps` if passed to `open`. Rejected.
4. **Backend serves the UI and sets an HttpOnly, SameSite=Strict cookie after a one-time bootstrap code.** The launcher generates a random one-time code (`secrets.token_urlsafe(32)`), keeps it in memory plus a 0600 file in the user's data dir, and the user's browser is sent to a *backend* page that needs the code. The code still has to reach the browser: through the clipboard, a URL, or a file the browser can't read. Every channel either leaks or needs user action (typing a short pairing code shown by the launcher — workable, but a UX change).
5. **Native shell (Tauri/Electron/Swift wrapper) that holds the token and injects it into requests.** This is the only design where the secret never touches a web-reachable resource. Requires packaging ByteX as a desktop app: a significant architectural change that was not approved.

## 4. Decision
- A browser-hosted UI plus a same-user local backend cannot be given a token that a same-user process cannot also obtain, unless the user takes a manual step (option 4, typed code) or the UI is wrapped natively (option 5).
- Implementing options 1–3 would create a fake boundary. **No authentication code was added.**
- What a token *would* buy even without a native shell: it blocks cross-site browser attacks and DNS rebinding independent of Origin/Host parsing bugs, and it blocks LAN callers if the bind is ever widened. It would **not** stop a same-user process, which can read the token file (0600 only excludes *other* users), read the launcher's environment via `ps eww`-style inspection on some systems, or simply drive the browser/CDP.

## 5. Recommended design if/when approved
- Launcher creates `secrets.token_urlsafe(32)` per launch; passes it to the backend through an inherited pipe or a 0600 file under the user's data dir — never argv, never URL, never logs.
- Backend stores only a SHA-256 of the token; compares with `hmac.compare_digest`; fails closed (503/1008) if auth is enabled but no token was provisioned.
- UI session: native wrapper (preferred) or typed one-time pairing code exchanged for an HttpOnly, SameSite=Strict, Secure-not-needed-on-loopback cookie with a short expiry; WebSocket validates the cookie plus the existing Origin check (cookies are sent on WS handshakes, so Origin must stay mandatory).
- Enforcement as a third pure-ASGI layer after the guard so it covers every HTTP/WS route and alias; explicit allow-list for `/health` (and nothing else); route-table test that every non-allow-listed route rejects an unauthenticated request.
- Rotation: new token per launch; `POST /auth/rotate` (authenticated) and expiry of cookies; revocation = restart.
- Dev vs prod: dev mode (`BYTEX_AUTH=off`) must be explicit, print a warning, and refuse to start if the bind is not loopback.
- Phone companion keeps its existing pairing protocol on `/ws/phone`; LAN exposure is out of scope.

## 6. What a same-user local process can still do (even with auth)
Read the token file, attach to the browser's CDP port 9222 (started by `skills/browser.py` with `--remote-debugging-port`), read the browser profile, write to ByteX's own storage, or run code directly. Local auth raises the bar for *web* attackers; it is not a sandbox against the user's own account.

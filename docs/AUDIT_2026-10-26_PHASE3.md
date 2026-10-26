# ByteX audit — phase 3 (2026-10-26): agent execution policy, confirmation provenance, browser debugging

Continues `AUDIT_2026-10-26.md` and `AUDIT_2026-10-26_PHASE2.md` (history preserved). Status labels: PASS / FAIL / BLOCKED / SKIPPED / NOT VERIFIED. This report does not claim ByteX is secure.

## 1. Risk-classifier bypasses found and fixed
Verified against the current code before changing anything.
| # | Finding | Severity | Status |
|---|---|---|---|
| R1 | Model tool calls (`assistant.py`, `ResponseSanitizer.extract_and_execute_tool_if_present`) reached `skill_registry.execute_tool` with **no** classifier check. | High | FIXED: the registry is now the single enforcement point (see below). |
| R2 | `coding_workspace` with `file_path`/`stdin` and no `action` executes code (the skill infers `execute_code`) but the classifier saw an empty action and returned SAFE. Same for `instruction`/`target_text` (edit). | High | FIXED: classifier mirrors the skill's inference; unknown actions need confirmation. |
| R3 | `screen_vision` with `action:"describe"` plus `text`, or `x`/`y`, or `raw_text:"click…"` types/clicks in the real skill but was classified read-only. Unknown actions defaulted to SAFE. | High | FIXED: `text`, `x`/`y`, click-requests count as input; only a reviewed read-only list is SAFE. |
| R4 | `compile`/`build` runs external toolchains but was SAFE. | Medium | FIXED: needs confirmation. |
| R5 | `download_file`, `website_automation` were SAFE although they write files / act in websites. | Medium | FIXED: SENSITIVE + confirmation. |
| R6 | `terminal_agent`: unknown operations defaulted to SAFE. | Medium | FIXED: only a reviewed read-only list is SAFE; shell metacharacters stay BLOCKED. |
| R7 | `browser_control` `click` and `open_application` with a path-like value (can launch arbitrary files) were SAFE. | Medium | FIXED: confirmation. |
| R8 | Classification keyed on alias names (`classify_action("click")` vs canonical skill), so aliases could differ from the skill actually run. | Medium | FIXED: classification now resolves the alias and normalises arguments exactly like the registry (`normalize_call`). |
| R9 | `agent/pipeline.py` does not pause on `requires_confirmation` (only on BLOCKED); `executor` did. | Medium | NOT FIXED (see 8). Pipeline steps come from the rule-based planner applied to the user's own typed request, so they are marked user-origin. |

**Enforcement design.** `SkillRegistry.execute_tool(name, args, *, approval=None, origin=ORIGIN_UNTRUSTED)`:
1. confirmation flags (`confirmed`, `user_confirmed`, …) are always stripped from caller arguments;
2. unless `origin=ORIGIN_USER` (set only at the two command-router call sites that execute a command the user typed), the classifier runs on the skill's *effective* behaviour: BLOCKED is refused, confirmation-required actions are **not executed** and return `confirmation_required` with a generic, honest summary of the exact call;
3. classifier errors fail closed (confirmation required);
4. the model cannot supply a risk level: extra keys such as `risk_level`/`is_safe` are ignored by construction (tested).
Default origin is untrusted, so any new/unknown caller is gated.

### Tool-risk matrix (model/plan origin; executable in `tests/test_tool_policy_enforcement.py`)
| Class | Examples | Behaviour |
|---|---|---|
| Read-only | file_search, list_files, web_search, read_webpage, system_status, application_status, summarize, research, take_screenshot, play_media, fill_form (never submits), read_file/generate_code, terminal version/list ops, screen_vision read/OCR/locate, browser tabs/status, open_application by name | runs |
| Reversible / creates | create_folder, rename/move/copy file, file_operations create | confirmation (existing SENSITIVE rule kept) |
| Potentially destructive | delete_file / delete / file_operations delete, close_application, clipboard set/clear/paste | confirmation |
| High impact | execute/run/compile/build code, fix_code (confirm mode), terminal install/build/test/server, download_file, website_automation, browser click, screen_vision click/type/scroll/coordinates, open_application by path | confirmation |
| Blocked | unregistered skills; terminal args with `&& \|\| ; \| \` $(` etc. | refused |

Behaviour change to expect: when the **model** (not you) asks for any of the confirm rows, ByteX now asks first. Commands you type keep their existing behaviour.

## 2. Confirmation provenance and cross-connection findings
* C1 (High, FIXED): `ConfirmationManager` held **one global pending slot**; any connection's "yes" approved another connection's pending action. Now pending records live per conversation (`ContextVar`, set to a fresh id per WebSocket in `api/websocket.py`; REST `/chat` uses a separate `http-chat` id). Each record has a request id, fingerprint, creation and expiry (300 s).
* C2 (High, FIXED): approval was a boolean the router injected as `confirmed:true`. Now a real user "yes" makes trusted code call `approve_pending()`, which removes the record (single use) and returns an `ApprovalGrant`: HMAC-signed with a per-process key, bound to conversation + tool + SHA-256 fingerprint of the exact arguments, valid 60 s, consumed on first successful verification. The registry executes only if every check holds, then sets `confirmed` itself.
* C3 (FIXED): plan resume (`executor.resume_step`) now issues a grant for exactly that step's skill and arguments; other steps still pause, and changed arguments are rejected.
* C4 (FIXED): `ResponseSanitizer.extract_and_execute_tool_if_present` returned the tool's confirmation text without recording a pending request; it now records one.
* Model text such as "yes" never reaches `evaluate_response`/`approve_pending`; only the router (user input) and the executor resume path issue approvals (tested by source scan).
* Limit: this defends against model output, plans, other connections and replays. Code already running inside the backend process can still mint grants.
* NOT FIXED: `bytex_core.history` and `session_manager` are still process-global, so conversation *context* (not approvals) is shared between connections. Background automations run in the default conversation, so any prompt they create is not answerable from a WebSocket (NOT VERIFIED which flows use this).

## 3. Test-only skills in the production registry
`RiskyTestActionSkill` and `MockVerificationFailureSkill` were registered in production and a typed phrase ("risky test") in `command_router` routed to the first. Usage search found no other users (no tests, no frontend). Resolved: removed from `_register_default_skills`, router phrase removed, `risky_test.py` kept as a documented fixture file; `SkillRegistry(register_defaults=False)` + `register_fixture()` lets tests build isolated registries. There is no environment variable or flag that registers test tools. Tests assert the exact production class set (27), that no production code calls `register_fixture`, and that fixtures stay policy-gated.

## 4. Browser remote debugging (CDP)
Verified in `skills/browser.py`: Edge 9222, Chrome 9223, Brave 9224 (Firefox 0); started **only on demand** when a browser command needs it, in ByteX's own profile directories (`ByteX_*_Profile`), never the user's main profile; ByteX talks to `http://127.0.0.1:<port>`; the launch had no explicit address; nothing ever closed the browser, so the port outlived ByteX; an already-running endpoint on that port is trusted as-is.
Changes: `security/browser_launch.py` builds the flags (`--remote-debugging-address=127.0.0.1`, validated port, mandatory dedicated profile) and tracks browsers ByteX launched; they are terminated at backend exit (`atexit`; set `BYTEX_BROWSER_CLOSE_ON_EXIT=0` to keep them). The address flag is defence in depth: Chromium may ignore it for headed browsers, NOT VERIFIED on your Mac.
Not solved and not claimable: CDP has no authentication. Any process running as you can connect to 127.0.0.1:922x, drive that browser and read cookies/sessions of sites you sign into in the ByteX profile; loopback only stops other machines. Note the UI itself is opened in this profile. Also not done: verifying that whatever answers on the port is really the browser (port squatting by a same-user process).

## 5. Local API authentication — recommendation
Threat models: (1) **hostile website**: already blocked by the loopback guard (Origin on WS and unsafe methods, Host check); a token would add defence in depth if the Origin logic had a bug. (2) **LAN device**: blocked by loopback bind plus peer check; a token only matters if the bind is ever widened. (3) **other process, same user**: not stopped by any token the browser can hold: a cookie/token in the browser profile is readable from disk or via CDP 9222, and a token file is readable by the same user. (4) **malware as the user**: cannot be stopped at this layer.
Options compared against this architecture (browser UI on :5173 + FastAPI on :8000):
* *Browser UI + token*: delivery to a web page needs a secret in the bundle, URL, an open endpoint or a cookie; all are obtainable by case (3). Gives (1)/(2) only.
* *Typed pairing code*: adds a user step but the code is shown on a channel the same-user process can read (screen, clipboard, terminal output); the resulting cookie has the same problem. Acceptable only as a CSRF-class control, not strong authentication, unless replay protection and one-time use are enforced.
* *Trusted local bootstrap by the launcher*: launcher and backend can share a secret (inherited pipe/0600 file), but the browser cannot, so it still needs one of the delivery channels above.
* *Native wrapper (Tauri/Electron/Swift)*: the wrapper process holds the token (OS keychain), injects it into requests and the WebSocket handshake, the web content never sees it, and the UI loads from the wrapper rather than a web server. The only option that removes the secret from browser-readable storage; (3) is then reduced to "must read the wrapper's memory/keychain entry".
**Recommendation:** native wrapper; do not ship a browser-visible token and call it protection. Minimum viable plan: (a) wrapper starts the backend with a random 32-byte token via an inherited pipe (never argv/URL/logs); (b) backend stores a SHA-256 and compares with `hmac.compare_digest`, fail closed when unset; (c) third ASGI layer after `LocalOnlyGuardMiddleware` requiring `Authorization` (HTTP) and a token in the first WS message or subprotocol, allow-listing only `/health`; (d) route-table test that every non-allowed route rejects unauthenticated calls; (e) rotate per launch; (f) keep the phone protocol on its own pairing path. **Not implemented** in this phase: it changes how the UI is delivered.

## 6. Files changed (backups: `audit-backup-2026-10-26-phase3.tgz`)
Modified: `backend/skills/registry.py`, `backend/core/confirmation.py`, `backend/core/risk_classifier.py`, `backend/core/command_router.py`, `backend/core/response_sanitizer.py`, `backend/agent/executor.py`, `backend/agent/pipeline.py`, `backend/api/websocket.py`, `backend/api/routes.py`, `backend/skills/browser.py`, `backend/skills/risky_test.py` (docstring only), `tests/test_tool_confirmation_gate.py` (rewritten for the new API).
New: `backend/security/browser_launch.py`, `tests/registry_harness.py`, `tests/test_tool_policy_enforcement.py`, this report. Nothing committed to git, no `.env`, database, phone registration or archive touched.

## 7. Tests actually executed
| Check | Result |
|---|---|
| `tests.test_tool_policy_enforcement` + `tests.test_tool_confirmation_gate` (Python 3.13, pydantic 2.13, sandbox) | PASS, 46 tests: risk matrix, all 10 requested confirmation scenarios, forged grants, production class set, fixtures isolated, CDP flags/cleanup, wiring scans |
| Mutation checks (gate off / fingerprint ignored / conversation ignored / no consume / global slot) | each makes tests FAIL (42, 2, 1, 1, 9 failures) |
| Same suites + guard + pairing + wiring on the device Linux VM (Python 3.10, no pydantic) | PASS 64 run, 26 SKIPPED (pydantic-dependent tests cannot run there); `py_compile` of 11 edited files PASS |
| `tsc -b` (frontend) | PASS (exit 0); no frontend files changed this phase |
| Existing `tests/*.py` e2e suites incl. `test_read_file_tool_execution_regression.py` | NOT RUN (need the project venv); by reading, `read_file` resolves to SAFE and should be unaffected: NOT VERIFIED |
| `scratch/` live tests | SKIPPED (control the real backend/desktop) |

## 8. Remaining vulnerabilities
1. No API authentication (section 5). 2. CDP unauthenticated, same-user reachable (section 4). 3. User-typed multi-step pipeline does not pause on classifier-sensitive steps (R9). 4. Prompt-injection exfiltration channels remain open for read-class tools: model-called web search/read_webpage/navigation can send data to attacker URLs without a prompt; the model also reads file contents via `read_file`. 5. Process-global chat history/session state shared across connections. 6. Per-skill path validation (files/coding/terminal) was reviewed only at the policy layer in this phase, not re-audited. 7. Behavioural impact of the new gate on everyday model-driven flows is untested end-to-end.

## 9. Runtime and dependency blockers
Device shell is a Linux VM (no macOS `.venv`, no pydantic/httpx/psutil, no native Vite/oxlint binaries); package installs are blocked by the network proxy and were not retried. **The Mac application has not been started**; health, chat, WebSocket confirmation flow, browser launch/cleanup and route table are NOT VERIFIED.

## 10. Next three steps
1. On the Mac, in the project venv: run the new suites (the 26 skipped should execute), the existing e2e suites, then manually test: model-driven "create a folder" (expect a yes/no prompt, then success once), two browser tabs confirming separately, and Edge launch (check `lsof -iTCP:9222` is 127.0.0.1 and the browser closes with the backend).
2. Decide on the native-wrapper plan and implement the token layer per section 5.
3. Close R9 (pause multi-step plans on sensitive steps via the executor grants), scope chat history per connection, and add a confirmation gate or URL allow-list for model-driven navigation/reading.

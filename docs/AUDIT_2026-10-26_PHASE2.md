# ByteX audit — phase 2 (2026-10-26)

Continues `docs/AUDIT_2026-10-26.md`. Status labels: PASS / FAIL / BLOCKED / NOT VERIFIED. This is not a statement that ByteX is secure.

## 1. Local API authentication
Designed, **not implemented**. See `docs/LOCAL_API_AUTH_DESIGN.md`. A browser UI cannot receive a secret that a same-user process cannot also obtain without a native wrapper or a manual pairing step; adding a token via `VITE_*`, an open token endpoint or a URL would be a fake boundary. Existing loopback bind + peer/Host/Origin guard remains the only HTTP/WS protection.

## 2. Deep security findings
### High
- **H1 — Model-controlled confirmation bypass (FIXED).** `core/assistant.py` executed any model-emitted tool call through `skill_registry.execute_tool`. Skills trust an argument named `confirmed` (`files.py` delete, `risky_test.py`), and `permanent`/`force_permanent` select irreversible deletion. A model (or a prompt-injected web page/file steering the model) could emit `{"tool":"delete_file","confirmed":true,"permanent":true}` and delete with no human prompt. `confirmation_required` results were also ignored and fed back to the model.
  Fix: `execute_tool(..., *, user_confirmed=False)` strips `confirmed`/`user_confirmed`/`skip_confirmation`/`auto_confirm`/`force_confirm` from caller arguments unless `user_confirmed=True`; only the human-yes path in `command_router` and `agent/executor.resume_step` pass it. `assistant.py` now stores `confirmation_required` results in `confirmation_manager` and asks the user instead of looping to the model.
- **H2 — Plan could self-approve (FIXED).** `executor.execute_plan` skipped the confirmation pause for any step whose status was `RUNNING`, and `resume_step` injected `confirmed` into the step arguments. Now approval is an explicit `approved_step_ids` parameter set only by `resume_step`.
### High — NOT fixed (needs your decision)
- **H3 — Model-initiated tools without their own prompt run unprompted.** `core/risk_classifier.py` is applied in `agent/pipeline.py` and `agent/executor.py` but not on the `assistant.py` model-tool path, nor on `ResponseSanitizer.extract_and_execute_tool_if_present`. Skills that do not self-confirm (code execution, terminal ops, clipboard, screen clicks/typing, downloads, form filling, open/close app) can be run by model output. Not fixed because the classifier defaults unknown aliases to "sensitive/confirm", which would change everyday UX in ways I cannot test without running the app. Recommended: enforce the classifier in `assistant.py` and test with real aliases on the Mac.
- **H4 — No local API authentication** (section 1).
### Medium
- M1 — Tool output is fed back to the model as a `user` message. Now labelled as untrusted data; this reduces but does not prevent prompt injection.
- M2 — Test skills (`RiskyTestActionSkill`, `MockVerificationFailureSkill`) are registered in the production registry and advertised aliases may reach them. Not changed.
- M3 — `ConfirmationManager` is a single global slot: any "yes" confirms whatever is pending, across all WebSocket connections and the shared `bytex_core.history`. Concurrent clients can confirm each other's prompts. Not changed.
- M4 — Browser launcher starts Edge/Chrome/Brave with `--remote-debugging-port` 9222/9223/9224 in a dedicated ByteX profile directory (good: not the user's main profile). The port is loopback-only by default in Chromium, but any same-user process or local script can drive that browser, including its signed-in sessions if the user logs in there. Not changed.
- M5 — Code execution (`coding.py`) runs user/model-authored source with the user's privileges; confirmation depends on the caller path (see H3). No sandbox.
### Low / verified OK (by reading, not by running)
- Terminal skill uses `create_subprocess_exec` with an executable allow-list and workspace cwd checks; no `shell=True` found in terminal/coding/browser/downloader/files/planner. `apps.py` non-Windows launch fixed in phase 1.
- Downloader: scheme/private-network checks, redirect cap (5), 100 MB cap, filename sanitising, unique names, `follow_redirects=False`. NOT VERIFIED by running.
- Planner caps plans at 5 steps; executor/pipeline classify every step and block unknown skills.
- Raw user messages and tool arguments are no longer printed by `assistant.py`/`registry.py`; other modules (e.g. `command_router`, skills) still print some arguments — NOT audited exhaustively.

## 3. Changes made this phase
`backend/skills/registry.py`, `backend/core/assistant.py`, `backend/core/command_router.py` (one call), `backend/agent/executor.py`, new `tests/test_tool_confirmation_gate.py`. Originals: `audit-backup-2026-10-26-phase2.tgz`.
Regression tests (10): flag stripped for every alias, human path still executes, caller dict not mutated, unknown tool fails closed, static wiring checks for router/assistant/executor and log privacy. Mutation check: with stripping disabled, `test_model_supplied_confirmed_flag_is_ignored` FAILS.

## 4. Test results (real)
- New gate tests: 10/10 PASS in the sandbox (Python 3.13, pydantic 2.13.5). On the device Linux VM they SKIP (no pydantic) — not run on the Mac.
- Earlier suites (guard, pairing, wiring: 47 tests): PASS in phase 1. After phase 2 the device VM run shows only the gate class skipped; `py_compile` of the four edited files PASS.
- NOT RUN: existing `tests/*.py` e2e suites (need the project venv; some may call `execute_tool` with `confirmed` — a grep found none outside direct `skill.execute` calls in `test_deletion_safety_regression.py`, which bypass the registry).

## 5. Runtime verification — BLOCKED
The device shell is a Linux VM (no project macOS `.venv`, no native Vite/oxlint binaries). The app was **not** started; health, chat, route table, listening sockets and startup logs were **not** checked. Run on the Mac: `git status`, the stdlib tests, existing e2e tests touching delete/confirmation, `cd ByteX && npm run build`, launch via `start_bytex.py`, `lsof -iTCP:8000 -sTCP:LISTEN` (expect 127.0.0.1 only), `curl -i -X POST -H 'Origin: https://evil.example' http://127.0.0.1:8000/api/health` (expect 403; harmless endpoint, **not** `/api/memory/clear`).

## 6. Key-shaped string (scratch/test_feature_34…:394)
Assigned to `raw` in a sanitizer/redaction-style test. Measured properties without printing it: length 43 (a real Google API key is 39 characters), not present in `backend/.env`, no placeholder words. Conclusion: **very likely a synthetic fixture, not a live credential** (NOT proven). The file is untracked and not git-ignored; replace it with an obviously fake value before any commit, and rotate only if you recognise the value.

## 7. Not done
Android (deferred per priority); H3; M2/M3; no authentication; Mac runtime checks.

## 8. Next actions
1. On the Mac, run the gate tests + existing delete/confirmation e2e tests + build + launch checks (section 5). Confirm the UI approval flow ("delete X" → yes) still works.
2. Enforce `ActionRiskClassifier` on every model-originated tool call (H3), make confirmations per-connection with the pending action id, and unregister test skills from production (M2/M3).
3. Decide on the auth route: native wrapper (strong) or typed pairing code (cheaper), then implement per `LOCAL_API_AUTH_DESIGN.md`.


## Phase 3 follow-up
See docs/AUDIT_2026-10-26_PHASE3.md: H3 (classifier on model tool calls), M2 (test skills) and M3 (shared confirmation slot) are addressed there; H4 (API authentication) remains unimplemented with a recommendation.

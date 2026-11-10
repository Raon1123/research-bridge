# Node-side job approval (SEC-01) — design

Date: 2026-11-03 · Status: draft, not user-approved; built: merged from branch `claude/sec-01-02-fixes` in PR 27 (merge commit 933edc3, branch tip 682509c; `rb_node/approval.py`) · Author: research-bridge session "MVP scope review" · Code: `rb_node/approval.py` (new), `rb_node/jobs.py`, `rb_node/remote.py`, `rb_node/cli.py`, `rb_node/config.py`, `rb_node/audit.py`, `rb_host/jobs.py`, `rb_host/cli.py`, `vault-export/dashboard/rb_pending.py` · Data: node `~/.research-bridge/approve.json`, node `mailbox/state/approve_fail.json`

Status history:
- 2026-11-03 draft; implemented on branch `claude/sec-01-02-fixes` at the user's request ("fix both", for SEC-01 and SEC-02 in GitHub issue 26). The design itself has not been reviewed by the user.
- 2026-11-10 status set to built (lifecycle in `docs/design/README.md`): merged to `main` on 2026-11-03 in PR 27 (merge commit 933edc3). The verifier on node1 is not confirmed (issue 8). The design is still not user-approved.

## 1. Intent

The security review (GitHub issue 26, item SEC-01) found that job approval existed only on the laptop. The node queued any `job_submit` that arrived over the bridge key. A laptop process that can use that key could talk to the node directly, upload a config and queue a job, skipping the ledger, `rb approve` and `/rb/pending`. That includes a Claude session with a shell. The user's requirement: only a legitimate user may make a request take effect.

## 2. Goals

- G1. The node runs `job_submit` and `job_cancel` only when the request carries a key that requires the user's passphrase.
- G2. A refused request leaves nothing on the node: no idempotency entry, no stored config, no queue file.
- G3. Nothing on the laptop lets a process derive the key offline. The laptop holds no secret, and the node keeps only a verifier.
- G4. Both approval paths keep working: `rb approve` and `/rb/approve` on port 8765.
- G5. A wrong passphrase leaves the ledger record `pending_approval`, never `approved`.

## 3. Non-goals

- Authenticating every bridge request (messages, reads) and pinning the node host key: GitHub issue 25.
- Defending against a process that rewrites `rb_host` itself, or reads `rb approve`'s memory while it runs. The same OS account can do both. See §7.
- Restricting the node responder session's tools (PM-02).

## 4. Anti-goals (failure even if it works)

- A job queued or cancelled without the user typing the passphrase.
- The passphrase or the key written to the ledger, an audit log, a URL or a response body.
- A bridge op that sets, reads or resets the verifier.
- A holder of the bridge key locking the user out permanently by sending wrong keys.

## 5. Constraints

- Hard rule 1: still no approval over MCP, and the ten-tool set is unchanged.
- Node code is standard library only: `hashlib.pbkdf2_hmac`, `hmac.compare_digest`, `secrets`.
- No new SSH key and no `authorized_keys` change. A passphrase-protected key file was considered and rejected (§12).

## 6. Architecture

```
user types passphrase ──> rb approve / 8765 form (laptop)
                              │ approve_params  ──────────────>  node: {salt, iterations}
                              │ K = PBKDF2-SHA256(passphrase, salt, iterations)
                              │ job_submit {..., approval_key: K} ─> node: sha256(K) == verifier ?
                                                                       yes: existing submit path
                                                                       no:  not_authorized, nothing written
user on node console: rb-node approve-key set ─> ~/.research-bridge/approve.json {salt, iterations, verifier}
```

All connections still go from the laptop to the node (hard rule 2).

### 6.1 Interfaces

| Name | Kind | Notes |
|---|---|---|
| `approve_params` (node op) | read | Returns `{salt, iterations}`, or `no_verifier`. No secret. |
| `job_submit`, `job_cancel` (node ops) | mutation | New required argument `approval_key` (64 hex characters). Errors: `not_authorized`, `approval_wait`. |
| `rb-node approve-key set\|clear` | node console | Not reachable through either forced command. |
| `jobs.approve(ledger, cfg, job_id, passphrase)` | laptop | `passphrase` is now required. Callers: `rb approve` (getpass) and `rb_pending.handle_post` (form field). |

The MCP tool set is unchanged.

## 7. Security

- **Verifier, not key.** The node stores `sha256(K)`. The node responder session runs under the same node account, and PM-02 says its tools are not restricted, so it may read `approve.json`. Reading the verifier does not let it forge an approval: it would still need a PBKDF2 preimage. 600 000 iterations of SHA-256 per guess, with the passphrase at least 12 characters.
- **Laptop holds nothing reusable.** The salt and iteration count are public. `K` exists only in `rb approve`'s memory while it runs, and is sent once over SSH. The laptop refuses node parameters below 100 000 or above 10 000 000 iterations, so a node cannot weaken the derivation or stall the laptop.
- **Wrong keys.** Five are free. After that the node refuses for 30 s × 2^(n−5), at most 1 h, and a right key resets the count. This is a wait, not a lock, so the bridge key cannot lock the user out for good. Only the error code is audited; `approval_key` is dropped from audit fields.
- **Binding.** The key authorizes exactly the arguments in the same request. The config sha256 is in those arguments and is checked against the upload, as before. A replayed request with the same idempotency key returns the earlier result and queues nothing new.
- **Residual risk, out of scope:**
  - A laptop process running as the user can modify `rb_host` or the 8765 page to capture the passphrase the next time it is typed. Defending against that needs a separate OS account or hardware confirmation.
  - On the node, a process under the node account, including the responder if PM-02 is not fixed, can write a `.job` file straight into the queue directory or replace `approve.json`. The bridge key cannot do either: no bridge op writes outside `mailbox/in`, and there is no op for the verifier.
- **8765 logs:** the vault `server.py` passes every form field to `handle_post`, and its `log_message` writes only the request line to stderr, not the POST body. So the passphrase is not logged (checked 2026-11-03 against the live file, read only).
- **PM-03 (DNS rebinding on 8765):** a rebinding page can still read the CSRF token, but it cannot approve without the passphrase. That is a partial mitigation; the `Host` header check is still needed.

## 8. Data and ledger

- No new ledger fields. `approved_at` is cleared again when the node refuses.
- Node files:
  - `approve.json`: `{salt, iterations, verifier}`, mode 600.
  - `mailbox/state/approve_fail.json`: `{count, last}`.

## 9. Scope of this phase

1. Code and tests (this branch).
2. User: `rb-node approve-key set` on node1 after installing the new `rb_node` (B1, issue 7). Until then every approval fails with `not_authorized`.
3. User: replace the vault `dashboard/rb_pending.py` and restart 8765 (`vault-export/README.md`).

## 10. Verification

| Goal / anti-goal | Check | Kind | Status |
|---|---|---|---|
| G1 | `tests/test_jobs.py::test_submit_without_valid_approval_key_writes_nothing`, `::test_cancel_without_key_refused`, `::test_no_verifier_refuses_submit_and_cancel`; `tests/test_host_tools.py::test_bridge_key_alone_cannot_queue` | unit test | passes |
| G2 | `test_submit_without_valid_approval_key_writes_nothing` (`_nothing_written`) | unit test | passes |
| G3 | `test_approve_params_public_only`, `test_weak_node_params_refused` | unit test | passes |
| G4 | `test_approve_queues_and_is_idempotent`, `test_cli_approve_prompt`, `tests/test_rb_pending.py::test_valid_calls_approve_and_reject` | unit test | passes |
| G5 | `test_wrong_passphrase_refused_and_ledger_back_to_pending` | unit test | passes |
| Console enrolment | `test_cli_approve_key_set_and_clear` (short, mismatch, set, clear; no passphrase in the file) | unit test | passes |
| Wait, not lock | `test_wrong_keys_start_a_wait_then_reset` | unit test | passes |
| Live run on node1 | `approve-key set`, then one approve with a wrong and a right passphrase | live check | not run (needs node1, user) |

## 11. Decided by the user

- 2026-11-03: fix SEC-01 and SEC-02 ("Yes, fix both").

## 12. My calls (user to check)

- **A passphrase verifier on the node instead of a separate passphrase-protected approval SSH key.** The key file would sit on the laptop, where a session could brute-force it offline. It would stop protecting anything if the key were added to `ssh-agent`. And 8765 has no terminal for the passphrase prompt.
- `/rb/approve` keeps working with a passphrase field, instead of becoming CLI-only.
- PBKDF2-SHA256 with 600 000 iterations; passphrase of at least 12 characters.
- Five free wrong keys, then a wait of 30 s doubling to 1 h, instead of a hard lock.
- Fail closed: no verifier means no job can be queued or cancelled.

## 13. Decision log (while building)

| # | Ruling | Cost if wrong | Where recorded |
|---|---|---|---|
| 1 | The check runs after the idempotency-key argument check and before the idempotency lookup, so even a replay needs the key | A legitimate retry after a lost response needs the passphrase again | `rb_node/jobs.py` |
| 2 | The laptop resets the record to `pending_approval` on `not_authorized`, `approval_wait`, `no_verifier` or bad parameters; other errors keep `approved` (retry allowed, as before) | A transport error leaves `approved` with nothing queued, as before | `rb_host/jobs.py` |
| 3 | `tests/test_rb_pending.py` imports the repository copy | The vault copy is no longer tested directly | `vault-export/README.md` |

## 14. Left to the builder

- Error wording; the `approve_fail.json` format.

## 15. Open questions

- Should `/rb/approve` stay, now with a passphrase field? Default: yes.
- Should rotating the passphrase (`approve-key set` again) be logged in the node audit? Default: no; the node console is outside the bridge.

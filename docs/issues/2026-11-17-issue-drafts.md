# Issue drafts — 2026-11-17

**Posted on 2026-11-17** with the user's go-ahead: each heading names the issue it became (#62 to #83). The text below is the body as posted; later edits happen on GitHub. Public repository: placeholders only (`docs/CONTRIBUTING.md` §3).

Sources: `docs/issues/2026-11-10-triage.md` §3 (proposed new issues N-01 to N-18), `docs/issues/2026-11-11-audit.md` §3 to §5, `docs/HANDOFF.md`, the open items of `docs/postmortems/`, and local hub files read on 2026-11-17 (no node contact).

Not drafted, with the reason:
- N-05 (approval form on the hub page) and N-14 (self-approval residual): settled by the user on 2026-11-10 (no form; residual accepted; `docs/HANDOFF.md` §Pending decisions).
- N-12 (`get_file` re-reads the file per chunk): fixed in PR 57 (`_transfer_bytes` in `rb_node/remote.py` keeps one masked copy per transfer, keyed by path, mtime and size).
- B3 row 7 (the first job's `job_finished` event): already tracked by #8. On 2026-11-17 the hub ledger still shows the job as `queued`.
- Node `sessions_dir` (first version of draft 17): the user corrected it on the node console on 2026-11-17; the 06:20 UTC sync pass listed sessions. Replaced by the truncation draft.
- `authorized_keys` options and the key directory on node1 (first version of draft 19): checked by the user on the node console on 2026-11-17.
- The two follow-ups of the 2026-11-10 incidents (first version of draft 20): the user decided on 2026-11-17 to keep the session transcript that holds withheld names; `~/.claude.json` on node1 was checked by the user on the node console on 2026-11-17.

Changes to existing issues, applied on 2026-11-17 (`docs/issues/2026-11-10-triage.md` §1, with these updates): closed #3, #5, #6, #7, #12, #26 (SEC-05 and SEC-06 continue in #73) and #39 (superseded by the hub page `/status`, PRs 58 and 59); rewritten #4, #9, #15, #20, #21 (now lists every open issue by workstream), #25, #41; commented #2, #8, #11, #13 (label `user-action` added), #14, #16 to #19 (the non-existent "HANDOFF §Follow-ups" reference replaced in #16 to #19); label `host` now reads "Hub side (rb_host)".

## Draft 1. design: resend failed messages from the outbox → #63

Labels: `design`, `host`. Source: triage N-01; docs/design/2026-11-10-sync-and-hub-page.md §6.9.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

**Problem**
`send_message` returns `pending_send` when the node is unreachable, and the hub keeps a masked copy under `outbox/<node>/<msg_id>/`. Nothing resends it; `rb sync` does not.

**Proposed change**
A retry path (in `rb sync` or a separate command). The design must settle: the stored copy is masked, so it is not the sent text when lines were blanked; attachment files are not copied; the node compares only attachments on a retry with the same `msg_id` (`msg_begin`); messages a session already resent by hand.

**Hard rules touched**
None (3 and 5 apply).

**Decisions needed from the user**
Whether the outbox copy may serve as a resend source (triage §5 item 8).

Related: #15, #16.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 2. design: record session-to-session messages on one machine → #66

Labels: `design`, `host`. Source: triage N-02.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

**Problem**
The bridge records only node traffic. Messages between two Claude sessions on the hub are not visible on the hub page.

**Proposed change**
Recording them needs either a Claude Code hook on the message tool (a change to the user's settings) or reading session transcripts (private, outside the masking rules). Decide whether it is wanted at all; then design.

**Hard rules touched**
None.

**Decisions needed from the user**
Whether this is wanted, and which of the two sources is acceptable.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 3. hub: reuse one SSH connection per pass (ControlMaster) → #70

Labels: `enhancement`, `host`. Source: triage N-03.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

One `rb sync` pass opens one connection for `hello`, `poll`, `git_status` and `sessions`, and the board sources open their own. OpenSSH connection sharing (`ControlMaster`) would cut connections. Needs a decision on the socket directory and its lifetime, and a check that a shared master cannot outlive a revoked key. Checked 2026-11-17: `rb_host/` does not use `ControlMaster`.

Deferred in `docs/design/2026-11-10-setup-and-diagnosis.md` §3 and `docs/design/2026-11-10-sync-and-hub-page.md` §3.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 4. node: mailbox size limit and pruning → #75

Labels: `enhancement`, `node`. Source: triage N-04; audit §4 (in/ and out/ never pruned).

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

The node mailbox (`in/`, `out/`, `state/`) has no total size limit: each attachment is capped at 50 MB, the number of messages is not. `in/` and `out/` are also never pruned (`docs/issues/2026-11-11-audit.md` §4). Checked 2026-11-17: no quota in `rb_node/`.

Define a quota, what happens when it is reached (refuse new messages with a code), a pruning rule for delivered items, and how `rb-node doctor` reports usage. Design from `docs/design/TEMPLATE.md`.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 5. hub: return the SSH error code separately from the hint in MCP results → #79

Labels: `enhancement`, `host`. Source: triage N-06; postmortem 2026-11-06-hub-key-agent-setup.md §5.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

MCP tool results return `{"error": str(exc)}`; for a classified SSH error the string carries the code's message and the next command in one text, so a session cannot branch on the code without parsing text. Add `code` and `hint` fields next to `error` (additive; old fields unchanged), with a test per tool. Checked 2026-11-17: `rb_host/server.py` has neither field.

Design: `docs/design/2026-11-10-setup-and-diagnosis.md` §6.4 and §12.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 6. tracking: project profiles (one node, several research trees) → #82

Labels: `design`, `node`, `host`. Source: triage N-07; docs/design/2026-11-10-project-profiles.md §9.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

Design only so far. Build order: P0 documents (done in PR 48); P1 node configuration (`project_root` alias, `profiles` parsed and checked, not served); P2 node masking (union of all pattern sources, `queue_status` name masking, `hello.withheld_digest`); P3 profiles on the wire (`protocol: 3`, `hello.profiles`, `profile` arguments); P4 hub gate and optional MCP `profile` arguments (allowed by the user on 2026-11-11); P5 hub configuration; P6 first named profile (user); P7 documents. The five fallback patterns stay on for every profile.

Design: `docs/design/2026-11-10-project-profiles.md` (draft; author's calls in §12 for the user to check).

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 7. tracking: experiment requests and result records → #65

Labels: `design`, `node`, `host`. Source: triage N-08; docs/design/2026-11-10-experiment-records.md §9.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

Design only so far. Build order: 1 run directory and `run.json` without families; 2 withheld reduction of `job_finished`; 3 families in `node.json`; 4 `runs` op; 5 user updates the node and declares a family; 6 hub requests and approval (optional MCP arguments allowed by the user on 2026-11-11); 7 hub reconciliation; 8 `rb runs`, `rb verdict`, MCP result fields; 9 hub page `/runs`, `/job/<id>`; 10 documents. Per-job passphrase approval is kept; unattended run loops are rejected.

Design: `docs/design/2026-11-10-experiment-records.md` (draft; open questions §15).

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 8. decision and fix: withheld matching gaps (case, split lines, zero-width characters) → #69

Labels: `security`, `node`, `sev:S3`. Source: triage N-09; postmortem 2026-11-03-whole-branch-review.md PM-18.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

Withheld patterns compile case-sensitively (checked 2026-11-17: no `re.IGNORECASE` in `rb_node/withheld.py`); text split across lines and zero-width characters are not handled. Whether such variants occur in node documents is not known.

The user decides which variants must be masked (triage §5 item 6); then add one test per pattern and variant and change `rb_node/withheld.py` (used by node and hub).

- Severity: S3 until a variant is seen in a real document.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 9. security: SEC-05 config loader and SEC-06 pdftotext exposure (split from #26) → #73

Labels: `security`, `node`, `host`, `sev:S2`. Source: triage N-10; issue #26.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

SEC-05: the session-chosen config goes to the fixed `job_template`; whether that is code execution depends on the project's config loader. Confirm data-only loading; `rb approve` already shows path and sha256.
SEC-06: the hub re-check runs `pdftotext` on node-supplied PDFs (`rb_node/withheld.py`); keep poppler updated or quarantine PDFs unparsed.

After this is opened, #26 can be closed (SEC-01 to SEC-04 and SEC-07 are fixed in PRs 27 and 35).
Design: issue 26 table; SEC-05 also `docs/design/2026-11-10-experiment-records.md` §7.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 10. design: hub attachment root for send_message → #77

Labels: `design`, `security`, `host`. Source: triage N-11; postmortem 2026-11-03-whole-branch-review.md PM-13.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

**Problem**
`send_message` accepts any hub file path as an attachment (`rb_host/server.py`, checked 2026-11-17: only `is_file()`), so a session can send any file the hub user can read, up to 50 MB, to the node.

**Proposed change**
An allowlisted attachment directory (or a per-call confirmation); keep the 50 MB cap; test that paths outside it are refused.

**Hard rules touched**
5 (attachments).

**Decisions needed from the user**
Directory or confirmation, and where the directory is.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 11. defect: board refresh uses fetch_file and shares fetched/<node>/ with sessions → #81

Labels: `defect`, `host`, `board`, `sev:S2`. Source: triage N-13; postmortem 2026-11-03-whole-branch-review.md PM-16.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

**Severity**: S2

**What happened**
`rb_host/board.py` calls `server.fetch_file` (checked 2026-11-17, line 206), which writes to `fetched/<node>/<basename>` and then deletes the copy. A file a session fetched under the same name is overwritten and deleted. `server.*` also reloads `host.json`.

**Reproduction**
Fetch a file with MCP `fetch_file`, then run a board refresh that reads a node file of the same base name (local subprocess node in tests).

**Expected**
A board-private fetch helper that takes `cfg` and writes under `board/tmp/`.

**Postmortem item**: `docs/postmortems/2026-11-03-whole-branch-review.md` PM-16

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 12. node: confine the responder's Read, Grep and Glob to the read roots → #83

Labels: `security`, `node`, `design`. Source: triage N-15; postmortem 2026-11-03-whole-branch-review.md PM-02.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

**Problem**
The spawned responder runs with `--tools Read,Grep,Glob` with the research root as working directory (`rb_node/spawn.py`); nothing limits those tools to `read_roots`. The reply is still masked when the hub polls it.

**Proposed change**
Run the responder in a directory that holds only the read roots, or pass a settings file with path rules; test with a file outside the roots.

**Hard rules touched**
8 (spawned server session).

**Decisions needed from the user**
None expected; the design picks one option.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 13. laptop 8765: deploy or retire the vault-export files → #64

Labels: `dashboard`, `security`, `user-action`. Source: triage N-16; audit U6; postmortem 2026-11-03-whole-branch-review.md PM-03, PM-17, PM-19.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

`vault-export/dashboard/rb_pending.py`, `rb_board.py`, `server.py.patch` and `vault-export/session-calendar/bridge_edges.py` are not in the vault, so the running 8765 has no `Host` check (PM-03). Approval still runs in the single-threaded vault server (PM-17), and `/board` needs `mcp` in the dashboard Python (PM-19). In `vault-export/` itself, `CHECKSUMS.txt` and `server.py.board.patch` were not regenerated after commit 7224d1d, `README.md` there is out of date, and the refusal text of `rb_pending.py` no longer fits job refusals (audit U6).

Only if the laptop dashboard stays in use for the bridge: regenerate the files, then the user copies them and restarts 8765. Otherwise close together with #13, #18, #19 as not planned.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 14. hub: harness channel on agent discovery → #68

Labels: `enhancement`, `host`. Source: triage N-17.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

`rb_host/harness.py` builds its ssh command without the agent discovery that `NodeClient` uses (checked 2026-11-17: no `agent_socket` there), so `rb harness push|pull|diff` needs `SSH_AUTH_SOCK` exported by hand. Use `sshenv.agent_socket` there as well. Blocked by #4 (whether the harness channel is used at all).

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 15. small gaps from the 2026-11-05 handoff notes → #72

Labels: `enhancement`, `node`, `host`, `sev:S3`. Source: triage N-18.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

(1) The node's `withheld_lines` and `withheld_attachments` counts are not kept in hub provenance (the hub keeps its own `body_withheld_lines`); (2) the node audit warning for an unparseable withheld source repeats on every connection; (3) an attachment name long enough to exceed the Windows path limit is retried on every poll (Windows hubs only). Check each against the code before work; split if any grows.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 16. defect: job idempotency record is written after the action → #76

Labels: `defect`, `node`, `sev:S2`. Source: audit §4 (rb_node/jobs.py).

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

**Severity**: S2 (not observed)

**What happened**
`rb_node/jobs.py` stores the idempotency record after acting: `job_submit` after the queue file is renamed (`_idem_store` at line 207), `job_cancel` after the pending file is unlinked (line 247). A call killed between the two is not replayed on a retry:
- a repeated `job_submit` can queue the job a second time (the hub uploads the config again on every approve);
- a repeated `job_cancel` answers `not_found`, which the hub reads as a refusal and returns the cancel record to `pending_approval` although the cancel acted.

**Reproduction**
Test against a local node: make `_idem_store` raise once after the rename, then repeat the call with the same `idempotency_key`.

**Expected**
Before queueing, look for an existing queue file of the job id; treat an existing `cancelled` state record as a replay.

**Postmortem item**: none yet (`docs/issues/2026-11-11-audit.md` §4)

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 17. node: sessions answer is truncated on the real node; say which bound was hit → #80

Labels: `enhancement`, `node`, `sev:S3`. Source: live answer of 2026-11-17; rb_node/sessions.py bounds.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

After `sessions_dir` was corrected on node1 (2026-11-17), the first real answer listed sessions (`unparsed: 0`, so the assumed record format holds) but had `truncated: true` with `files: 77`. `rb_node/sessions.py` sets `truncated` for any of five bounds (`MAX_LISTED` directory entries, `MAX_FILES`, `MAX_NEW_BYTES`, `MAX_SECONDS`, `MAX_SESSIONS`), and the answer does not say which one, so the hub cannot tell whether sessions are missing.

Proposed: an additive field naming the bound that was hit (e.g. `truncated_by`), shown by `rb-node doctor` and on `/status`; then decide whether the bound needs raising for a large `~/.claude/projects`. Also check why 77 files gave 13 listed and 7 outside sessions (other record files in the same project directories?).

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 18. user-action: live check of cancel_job with rb approve → #62

Labels: `user-action`, `node`, `host`. Source: HANDOFF "Open after these tests" item 3; postmortem 2026-11-10-node-local-checks.md §5.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

**Step**
`docs/HANDOFF.md` §Node state, "Open after these tests" item 3: the cancel path has never run on the real link.

On the node console: `rb-node run-job ... -- sleep 600` (a job the node knows). From a hub session: MCP `cancel_job` for it; in a hub terminal: `rb approve <id>`.

**Who runs it**: user (node console, hub terminal); session for the MCP call after the user confirms

**Done when**
The job ends as cancelled on the node, the hub record is `cancelled`, and the node audit log has the `job_cancel` entry. Result recorded in `docs/provisioning.md` §Results.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 19. hub and node: small code gaps left by the 2026-11-11 audit → #67

Labels: `enhancement`, `host`, `node`, `sev:S3`. Source: audit §4.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

Each was found and not fixed (`docs/issues/2026-11-11-audit.md` §4); checked against `main` on 2026-11-17 where marked.

- `NodeClient.call` has no read timeout; the node-side bounds are the only limit on a long call (e.g. `sessions`).
- `share.ERROR_CODE` (`^[a-z_]{1,40}$`) allows no digit while `sync.CODE` does, so a code with a digit shows as `bad_error_code` on `/status` (checked).
- "Active now" on `/status` compares node record times with the hub fetch time and ignores the answer's `now`; a clock difference shifts it.
- `Ledger._lines` reads a directory at the ledger path as an empty ledger without an error.
- `share.snapshot` marks an unconfigured source as stale; `share._clean` repeats `jobs.clean`.
- `rb_host/doctor.py` `_verdict` and `_withheld_hub` repeat rules now in `rb_node.doctor.verdict` and `Withheld.problem()`, in a different order, and call an unreadable file "not valid JSON".
- `validate_budget` keeps an `allowed_gpus=None` path no caller uses.
- `rb-node doctor` reads session record files on every run; every ledger `append` parses the whole file under its lock (harmless at present size).

Split out any item that turns into a defect.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 20. tests and documents: hygiene left by the 2026-11-11 audit → #71

Labels: `documentation`, `sev:S3`. Source: audit §4 (tests), §5, U8, U10, U11; triage §4 workstream 6.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

Tests:
- `_hcfg`, `_sha` and the `_isolated` fixture are copied across three to four test files; three unused locals (`test_host_tools.py`, `test_configure.py`, `test_setup.py`).
- Test names and one comment still say "laptop" for hub code (`tests/test_board.py`, `tests/test_harness.py`); one name is cited by the unified-board design.
- `tests/test_service.py` reads its expected unit text from §6.10 of the sync design; note that in the design.

Documents:
- `docs/HANDOFF.md` states the B3 outcome three times and keeps the superseded "Node state" section; rewrite when B3 row 7 closes.
- `docs/design/2026-11-10-setup-and-diagnosis.md` writes the agent order and the host-key rule five times each.
- `docs/projects/trm.md` §9 checks and the "Before B2" boxes of `docs/provisioning.md` were never run or ticked.
- Notes about removed scripts remain in the hub manual and in HANDOFF.

Repository (each needs the user's go-ahead):
- `uv.lock` is in `.gitignore` although uv manages the environment (audit U8).
- Label `host` is described as "Laptop side (rb_host)"; the hub is a Linux server since 2026-11-05 (audit U10).
- Postmortem item ids PM-01… repeat across files; rename to per-file prefixes or keep per-document numbering (audit U11).

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 21. hub: show the node's allowed GPUs before approval → #74

Labels: `enhancement`, `host`, `node`. Source: HANDOFF "Open after these tests" item 5.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

The hub does not know the node's `allowed_gpus`: a wrong GPU in `submit_job` is refused only at approval (`invalid`). `hello` carries only the boolean `allowed_gpus_set`. Add the list to the `gpu_status` result (additive field) or to `hello`, and let `submit_job` or `rb approve` warn early. The node stays the authority (hard rule 1).

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```

## Draft 22. design: multi-GPU jobs → #78

Labels: `design`, `node`. Source: HANDOFF "Open after these tests" item 4; docs/design/2026-11-10-allowed-gpus.md.

```markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

**Problem**
`job_submit` refuses more than one GPU (`invalid`), because the research queue gives each worker one GPU and `run-job` runs a one-GPU job on the worker's GPU.

**Proposed change**
Only once the queue can give one job several GPUs: how a multi-GPU job is claimed, how `gpus_used` and the GPU-hour budget count it, and how `allowed_gpus` applies.

**Hard rules touched**
None expected.

**Decisions needed from the user**
Whether multi-GPU jobs are needed through the bridge at all.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
```


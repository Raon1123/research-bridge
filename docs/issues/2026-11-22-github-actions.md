# GitHub actions proposed on 2026-11-22

Drafts from the status review `docs/issues/2026-11-22-status.md` §4. Nothing here has been applied. Each action needs the user's go-ahead; a session then applies it with `gh issue edit N --body-file ...` or `gh issue comment N --body-file ...`. No closure and no branch deletion is proposed.

Order: apply the new body of #21 only after the status file is merged into `main`, so that its link resolves. The other actions can go in any order.

## edit body: issue #69

````markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

Checked on 2026-11-22 at 752d5a3. Zero-width characters, other Unicode format characters (category Cf), U+2028, U+0085 and ASCII control characters inside a name are handled: `_hit` in `rb_node/withheld.py` also tests copies of the text without them (tests in `tests/test_withheld.py` and `tests/test_host_store.py`). Two gaps remain:

- Patterns compile case-sensitively (`re.compile(p)` in `rb_node/withheld.py`, no `re.IGNORECASE`).
- A name split across two lines is not matched: matching is per line by design, and the copies keep the newline.

Whether such variants occur in node documents is not known. The user decides (triage §5 item 6): mask case variants, yes or no; mask names split across lines, yes or no (this would need a join step and a rule for which lines to blank). Then add one test per pattern and variant and change `rb_node/withheld.py` (used by node and hub). Do this together with SEC-06 of #73, which changes the same module.

- Severity: S3 until a variant is seen in a real document.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
````

## edit body: issue #71

````markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

Checked on 2026-11-22 at 752d5a3.

Tests (no decision needed):
- `_hcfg`, `_sha` and the `_isolated` fixture are copied across two to three test files each (`_hcfg` in 2, `_sha` in 2, `_isolated` in 3); three unused locals (`test_host_tools.py`, `test_configure.py`, `test_setup.py`; `ruff check --select F841`).
- Test names and one comment still say "laptop" for hub code (`tests/test_board.py`, `tests/test_harness.py`); one name is cited by the unified-board design.
- `tests/test_service.py` reads its expected unit text from §6.10 of the sync design; note that in the design.

Documents:
- `docs/HANDOFF.md` states the B3 outcome several times and keeps the superseded "Node state" section; rewrite when B3 row 7 closes.
- `docs/design/2026-11-10-setup-and-diagnosis.md` writes the agent order and the host-key rule five times each (count not rechecked on 2026-11-22).
- `docs/projects/trm.md` §9 checks and the "Before B2" boxes of `docs/provisioning.md` were never run or ticked.
- Notes about removed scripts remain in the hub manual and in HANDOFF.

Repository (each needs the user's go-ahead):
- `uv.lock` is in `.gitignore` although uv manages the environment (audit U8).
- ~~Label `host` is described as "Laptop side (rb_host)" (audit U10).~~ Done on 2026-11-17: the label reads "Hub side (rb_host)".
- Postmortem item ids PM-01… repeat across files; rename to per-file prefixes or keep per-document numbering (audit U11). #11 fills its postmortem after this is decided.

- [x] I checked that this issue contains placeholders only and no withheld or server content.
````

## comment: issue #8

````markdown
Checked against main at 752d5a3 on 2026-11-22. B2 and rows 1 to 6, 8 and 9 of the B3 live run are recorded as PASS in `docs/provisioning.md` §Results, and the postmortem `docs/postmortems/2026-11-10-first-live-run.md` exists. The only open item is B3 row 7: the `job_finished` event of the first approved job. On 2026-11-22 the job's last ledger state is still `queued` (since 2026-11-10), the sync timer's last pass stored no new item, and neither of the two undelivered events in the hub store is that event. When it arrives, row 7 and section 5 of the postmortem are updated and this issue can be closed. All three boxes above can be ticked; none of them names B3 row 7, which keeps this issue open until it is recorded.
````

## comment: issue #11

````markdown
Checked against main at 752d5a3 on 2026-11-22. Still open: `docs/postmortems/2026-10-27-sdd-build.md` has six `<to fill>` markers (lines 124, 137, 149, 161, 167, 176), its status is `draft, unaudited`, and it has no `Audit:` lines. The path `docs/history/sdd-2026-10-27/task-11-report.md` in the description is outdated: the file is now `docs/99_Archive/sdd-2026-10-27/task-11-report.md` and is still the stale round-1 report (PM-10 of the postmortem). The renaming of repeated item ids is tracked in #71; filling this file after that decision avoids renumbering twice.
````

## comment: issue #13

````markdown
Checked against main at 752d5a3 on 2026-11-22. The repository part is done: `vault-export/dashboard/rb_board.py` and `vault-export/dashboard/server.py.board.patch` exist, and `tests/test_rb_board.py` pins loopback 200, non-loopback 403 and no connection on page load. The first checkbox can be ticked. Left: apply the patch on the laptop, restart 8765 and do the live check (loopback 200, LAN 403); this deploy is tracked with the other vault-export files in #64. Close as not planned if the laptop dashboard is no longer used for the bridge.
````

## comment: issue #20

````markdown
Checked against main at 752d5a3 on 2026-11-22. The branch `research-bridge/impl` no longer exists on GitHub (`git ls-remote --heads origin` and the branches API list only `main`). Left: (1) remove its old worktree on the laptop if it is still there, then drop its row from `docs/CONTRIBUTING.md` (line 12); (2) decide branch protection for `main`, which is not protected now. The merge settings (merge commits only, branch deleted after merge) match `docs/CONTRIBUTING.md` §1.
````

## comment: issue #25

````markdown
Checked against main at 752d5a3 on 2026-11-22. Unchanged: `rb_host/client.py` passes no `StrictHostKeyChecking` or `UserKnownHostsFile`, `host.json` stores no host key fingerprint, and there is no request authenticator, sequence number or approval spec hash. Correction to item 4: the `from=` restriction is now documented (`docs/manual/node-setup.md`, the `authorized_keys` lines) and checked by `rb-node doctor`; key rotation, revocation and the passphrase or agent policy are still not documented. Documenting rotation and revocation in `docs/manual/` needs no design decision; the rest waits for the decisions listed above.
````

## comment: issue #64

````markdown
Checked against main at 752d5a3 on 2026-11-22. In the repository, `vault-export/dashboard/rb_pending.py` has the Host and Origin check and `vault-export/dashboard/server.py.patch` passes the Host header; `vault-export/CHECKSUMS.txt` is still dated 2026-11-02. Whether the running laptop dashboard has the check cannot be seen from the hub. Issues #13, #18 and #19 are still open. The decision needed: does the laptop 8765 dashboard stay in use for the bridge? If yes, a session regenerates `CHECKSUMS.txt`, `server.py.board.patch` and the README text and fixes the job refusal text in `rb_pending.py` (audit item U6), and the user copies the files and restarts 8765. If no, this issue closes together with #13, #18 and #19 as not planned.
````

## comment: issue #67

````markdown
Checked against main at 752d5a3 on 2026-11-22. All eight items are still open. Suggestion: split item 2 into its own defect: `share.ERROR_CODE` in `rb_host/share.py` (line 30) allows no digit while `CODE` in `rb_host/sync.py` (line 29) does, so a status code containing a digit is shown as `bad_error_code` on `/status`. Items 1 (no read timeout in `NodeClient.call`) and 3 (`Active now` ignores the node's `now`) change behaviour and need a test each; the other items can stay in this list.
````

## comment: issue #72

````markdown
Checked against main at 752d5a3 on 2026-11-22. All three items are still open in the code. (1) The hub provenance record written by `store_incoming` (`rb_host/store.py`) does not keep the node's `withheld_lines` and `withheld_attachments`. (2) `Node.__init__` in `rb_node/remote.py` writes the unparseable-source audit entry on every connection. (3) The Windows path limit no longer applies to the hub (Linux since 2026-11-05), but `Mailbox.sanitize` in `rb_node/mailbox.py` has no length cap; a local test with a very long attachment name should show whether Linux has the same problem. Suggest splitting (3) from (1) and (2) after that test.
````

## comment: issue #73

````markdown
Checked against main at 752d5a3 on 2026-11-22. #26 is closed, so that part of the body is done. SEC-06 is still open: `_pdf_text` in `rb_node/withheld.py` runs `pdftotext` on node-supplied PDFs, on the hub as well as on the node, with a 30 second timeout and no other confinement; the manuals say only that `pdftotext` is needed. SEC-05 still needs the node owner to confirm that the project's config loader reads data only; the repository cannot show that. For SEC-06 the user chooses between a manual note to keep poppler-utils updated, an optional setting that quarantines PDFs without parsing them, or both. #69 changes the same module; do them in one pass.
````

## comment: issue #80

````markdown
Checked against main at 752d5a3 on 2026-11-22. The question about 77 files giving 13 listed and 7 outside sessions is answered by the multi-pass rule in `docs/design/2026-11-11-node-sessions.md` §10, and `truncated` cleared on later passes. What remains is the code change: the answer sets one boolean `truncated` for five bounds (`rb_node/sessions.py`, around lines 417 to 475), and neither `rb_host/sessions.py`, `/status` nor `rb-node doctor` can say which bound was hit. Proposed scope: an additive field naming the bound (for example `truncated_by`), checked on the hub like the other keys and accepted when an older node leaves it out, shown by `rb-node doctor` and `/status`, with tests. The bounds themselves stay unless a node keeps hitting one.
````

## edit body: issue #21 (apply after the status file is on `main`)

````markdown
<!-- Public repository. Placeholders only; no withheld content or message bodies. -->

Tracking issue for the remaining research-bridge work. Open work and its order are in `docs/issues/2026-11-10-triage.md` (§1 table, §4 workstreams, §5 decisions). Issue drafts of 2026-11-17: `docs/issues/2026-11-17-issue-drafts.md`. State of every open issue on 2026-11-22, with what a session can do now and what only the user can do: `docs/issues/2026-11-22-status.md`. Setup manuals: `docs/manual/`.

Triage proposals N-05, N-12 and N-14 were not opened as issues; see the triage file.

Order: 1, then 2, then 3; 4 and 5 after 3; 6 at any time.

### 1. First live run on the real link
Done on 2026-11-10 except B3 row 7 (`docs/provisioning.md` §Results). Remaining: B3 row 7 (the `job_finished` event of the first approved job, waits for the research queue; on 2026-11-22 the job was still `queued` and no such event was in the hub store), then #8; #9 (read roots). Blocked by: the research queue.
- [ ] #8 provisioning B2-B3: security checks and live run (only row 7 left)
- [ ] #9 node read roots and document paths

### 2. Security follow-ups
Blocked by decisions 2, 3, 5, 6 (triage §5).
- [ ] #25 MITM protection (rewritten; `from=` is documented and checked since, rotation and revocation are not)
- [ ] #73 SEC-05 config loader and SEC-06 pdftotext exposure
- [ ] #77 hub attachment root for send_message
- [ ] #69 withheld matching gaps (zero-width characters handled; case and line splits left)
- [ ] #83 confine the responder's Read, Grep and Glob to the read roots
- [ ] #2 shared key on node1
- [ ] #64 laptop 8765: deploy or retire the vault-export files (if the laptop dashboard is used; if it is retired, #64, #13, #18, #19 close as not planned)

### 3. Sync and hub page
Built in PRs 48 and 49; the live check passed on 2026-11-10 (B3 rows 4, 8, 9). Blocked by decisions 3, 8, 9, 10, 11, 18.
- [ ] #79 return the SSH error code separately from the hint in MCP results
- [ ] #63 resend failed messages from the outbox
- [ ] #70 reuse one SSH connection per pass
- [ ] #75 mailbox size limit and pruning
- [ ] #66 record session-to-session messages on one machine
- [ ] #15 ledger: to_session and attachment byte totals
- [ ] #16 protocol: carry reply_to to the node
- [ ] Laptop side: #13 (repository part done; laptop deploy left), #18, #19

### 4. Project neutrality
Blocked by decisions 7 and 13, and by workstream 1 (node update path proven on the real node).
- [ ] #82 project profiles (one node, several research trees)
- [ ] #9 node read roots and document paths
- [ ] #41 live research session link and responder arbitration
- [ ] #4 harness allowlist and harness_root
- [ ] #68 harness channel on agent discovery (blocked by #4)
- [ ] #17 node queue: lock numbering for concurrent submitters

### 5. Experiment records
Blocked by workstream 1 (job path with a real `job_template`), decisions 4, 7, 14; the family rules follow the profile design (#82). Steps 1 to 4 are node-only and may start after workstream 1.
- [ ] #65 experiment requests and result records

### 6. Repository hygiene
Nothing blocks these.
- [ ] #11 postmortem: complete the first-build draft (the postmortem item ids are renamed under #71)
- [ ] #20 repo: branch protection for `main` and the laptop worktree of `research-bridge/impl` (the branch is already gone from GitHub)
- [ ] #21 this issue
- [ ] `uv.lock` in `.gitignore`: tracked in #71
- [x] The "HANDOFF §Follow-ups" references in the bodies of #15 to #19 (replaced on 2026-11-17)

### Other
- [ ] #14 board: decide open questions
- [ ] #72 small gaps from the 2026-11-05 handoff notes
- [ ] #81 board refresh uses fetch_file and shares fetched/<node>/ with sessions
- [ ] #76 defect: job idempotency record is written after the action
- [ ] #80 node: sessions answer is truncated on the real node (truncation cleared; naming the bound is left)
- [ ] #62 user-action: live check of cancel_job with rb approve
- [ ] #67 small code gaps left by the 2026-11-11 audit (item 2, the status code without digits, proposed as its own defect)
- [ ] #71 tests and documents: hygiene left by the 2026-11-11 audit (includes `uv.lock` and postmortem ids; the `host` label item was done on 2026-11-17)
- [ ] #74 hub: show the node's allowed GPUs before approval
- [ ] #78 design: multi-GPU jobs

No issue is proposed for closing on 2026-11-22.

Closed on 2026-11-17: #3, #5, #6, #7, #12, #26, #39.

Rewritten 2026-11-17 from docs/issues/2026-11-10-triage.md §1; updated 2026-11-22 from docs/issues/2026-11-22-status.md.
````

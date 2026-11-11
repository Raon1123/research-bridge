# Archive

Finished or superseded material, kept for provenance. Nothing here describes the current state; current rules are in `AGENTS.md`, current state in `docs/HANDOFF.md`.

A file that is no longer needed is moved here with `git mv`, not deleted. Each move adds one row below and updates the references to the old path in living documents. Dated records that mention an old path (postmortems, the files in this directory) are left as they are.

| Moved | Path here | Came from | Why |
|---|---|---|---|
| 2026-11-11 | `sdd-2026-10-27/` (29 files) | `docs/history/sdd-2026-10-27/` | Controller ledger, task briefs and implementer reports of the first build (2026-10-27). Provenance only. The hashes in the ledger predate the 2026-11-02 rewrite of `main` and do not resolve. `docs/history/` held nothing else, so this directory replaces it. |
| 2026-11-11 | `plans/2026-10-27-research-bridge.md` | `docs/superpowers/plans/` | The first plan (Tasks 0–13). Tasks 0–12 are built; Task 13 (provisioning) was replaced by B2 and B3 of `docs/provisioning.md`, run on 2026-11-10. Its step boxes were never ticked. |
| 2026-11-11 | `plans/2026-11-06-shared-status-page.md` | `docs/superpowers/plans/` | Plan of the shared status page; its Tasks A–C are built (commits e68109a, 218d60a). Its "Global Constraints §A" is still the only record of the assumed input formats, and `docs/design/2026-11-06-shared-status-page.md` links to it here. |
| 2026-11-11 | `manual-appendix-a/hub-setup.md`, `hub-setup.ko.md` | Appendix A of `docs/manual/hub-setup.md` and its Korean file | Windows or laptop hub instructions (requirements, data directory, keys, MCP entry, 8765 approval, checks), not maintained since 2026-11-05. The 8765 routes are described in `docs/session-dashboard.md`; the manual keeps a pointer line. |
| 2026-11-11 | `manual-appendix-a/node-setup.md`, `node-setup.ko.md` | Appendix A of `docs/manual/node-setup.md` and its Korean file | Windows-hub notes for the node (line endings, old reply path, laptop `from=`, the by-hand install that `scripts/node-install.sh` replaced), not maintained since 2026-11-05. The manual keeps a pointer line. |
| 2026-11-11 | `shared-status-page/share_serve.py`, `shared-status-page/test_share_serve.py` | `rb_host/share_serve.py`; the tests of `share.build`, the tiers, `rb share build` and `rb share serve` from `tests/test_share.py` | The status summary moved into the hub page as the route `/status` (`docs/design/2026-11-11-hub-status-page.md`, decided by the user on 2026-11-11, audit row U3). `share.build`, its two files, its audit line, the tiers and the `rb share` commands were removed in the same change. The test file is not collected (pytest collects `tests/` only); to run it, check out the commit before the removal. |

History rewrites of `main`: a table of old and new hashes goes in this directory (`docs/CONTRIBUTING.md` §1 rule 4).

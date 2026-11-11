# Design documents

A design document records what a change is for, what it must never do, and which decisions the user made versus which the author made. Write one before any change that adds a tool, a route, a key, a node-side root, or a ledger field, or that touches one of the hard rules in `AGENTS.md`. Small fixes inside an existing design do not need one; record them in the plan or ledger of that work.

Copy [TEMPLATE.md](TEMPLATE.md) to `docs/design/YYYY-MM-DD-<slug>.md`.

## Status lifecycle

Each document carries one status line at the top. Update it in place and keep the earlier states with their dates.

| Status | Meaning |
|---|---|
| `draft` | Written; the user has not approved it. |
| `user-approved` | The user read it and approved it. Record the date and what was changed on review. |
| `built` | The implementation landed. Record the commit range. |
| `superseded` | A later design replaces it. Link the replacement; do not delete the old file. |

A design built before the user approved it carries both parts: `draft, not user-approved; built: <where>`.

## Rules

- Separate the user's decisions ("Decided by the user") from the author's ("My calls (user to check)"). Never move an item from the second list to the first without the user saying so.
- Each ruling made while building goes into the decision log with its cost if wrong (the format of `docs/99_Archive/sdd-2026-10-27/ledger.md`).
- Each goal needs a verification entry: a test name, a live check, or "not verified" with the reason.
- Placeholders only for private values, from the one list in `docs/manual/README.md` (Conventions). Real values belong in the gitignored `private/` directory.
- No withheld content (`AGENTS.md` hard rule 3) and no experiment results in a design document. Name withheld families only by the patterns already listed in `AGENTS.md`.

## Index

| Date | Document | Status |
|---|---|---|
| 2026-10-27 | [research-bridge design](../superpowers/specs/2026-10-27-research-bridge-design.md) | user-approved; built through Task 12 (hashes in the ledger predate the 2026-11-02 rewrite of `main`) |
| 2026-11-02 | [Unified research board](2026-11-02-unified-board.md) | draft, not user-approved; built: steps 3–5 (board module, `rb board` CLI, `/board` page patch in `vault-export/`) merged in PR 23 (merge commit 2bd8841); the vault copy of the patch is a pending user step (`docs/issues/2026-11-10-triage.md`, issue N-16) |
| 2026-11-03 | [Node-side job approval (SEC-01)](2026-11-03-node-side-approval.md) | draft, not user-approved; built: merged from branch `claude/sec-01-02-fixes` in PR 27 (merge commit 933edc3; `rb_node/approval.py`) |
| 2026-11-06 | [Shared research status page](2026-11-06-shared-status-page.md) | superseded 2026-11-11 by the status page on the hub (its reducers stay in `rb_host/share.py`; `rb share build|serve` and `share_serve.py` archived in `docs/99_Archive/shared-status-page/`) |
| 2026-11-10 | [Setup and diagnosis](2026-11-10-setup-and-diagnosis.md) | draft, not user-approved; built: merged from branch `claude/review-optimize-2026-11-10` in PR 48 (merge commit c503667) |
| 2026-11-10 | [Unattended sync and the hub page](2026-11-10-sync-and-hub-page.md) | draft, not user-approved; built: merged from branch `claude/review-optimize-2026-11-10` in PR 48 (merge commit c503667); access key in PR 49 (merge commit d3db45a) |
| 2026-11-10 | [Project profiles](2026-11-10-project-profiles.md) | draft (design only) |
| 2026-11-10 | [Experiment requests and result records](2026-11-10-experiment-records.md) | draft (design only) |
| 2026-11-10 | [Node GPU allowlist and worker-assigned GPU](2026-11-10-allowed-gpus.md) | draft, not user-approved; built: merged from branch `claude/node-allowed-gpus` in PR 47 (merge commit e95be9c) |
| 2026-11-11 | [Status page on the hub](2026-11-11-hub-status-page.md) | draft, not user-approved; built on branch `claude/hub-status-page` (PR 58, not merged): `share.snapshot`, route `/status`, `rb share` archived |
| 2026-11-11 | [Sessions on the nodes, collected on the hub](2026-11-11-node-sessions.md) | draft, not user-approved; built on branch `claude/node-sessions` (on top of `claude/hub-status-page`, not merged): node operation `sessions`, `rb-node sessions`, the doctor check, the `rb sync` step, the hub store, the `/status` lines; live checks open |

The first design stays at `docs/superpowers/specs/` because `AGENTS.md` and other documents refer to that path; its plan is in `docs/99_Archive/plans/`. New designs go in this directory.

## Candidates

Open items that need a design first are kept in one place: `docs/issues/2026-11-10-triage.md`, the rows marked "design first" in §1 and the proposed issues of §3 marked "Design: none yet".

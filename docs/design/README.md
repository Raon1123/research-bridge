# Design documents

A design document records what a change is for, what it must never do, and which decisions the user made versus which the author made. Write one before any change that adds a tool, a route, a key, a node-side root, or a ledger field, or that touches one of the hard rules in `AGENTS.md`. Small fixes inside an existing design do not need one; record them in the plan or ledger of that work.

Copy [TEMPLATE.md](TEMPLATE.md) to `docs/design/YYYY-MM-DD-<slug>.md`.

## Status lifecycle

Each document carries one status line at the top. Update it in place and keep the earlier states with their dates.

| Status | Meaning |
|---|---|
| `draft` | Written, not yet shown to the user. |
| `user-approved` | The user read it and approved it. Record the date and what was changed on review. |
| `built` | The implementation landed. Record the commit range. |
| `superseded` | A later design replaces it. Link the replacement; do not delete the old file. |

## Rules

- Separate the user's decisions ("Decided by the user") from the author's ("My calls (user to check)"). Never move an item from the second list to the first without the user saying so.
- Each ruling made while building goes into the decision log with its cost if wrong (the format of `docs/history/sdd-2026-10-27/ledger.md`).
- Each goal needs a verification entry: a test name, a live check, or "not verified" with the reason.
- Placeholders only for server facts: `<NODE_HOST>`, `<NODE_PORT>`, `<NODE_USER>`, `<LAPTOP_ETH_SUBNET>`, `<SHARED_KEY>`. Real values belong in the gitignored `private/` directory.
- No withheld content (`AGENTS.md` hard rule 3) and no experiment results in a design document. Name withheld families only by the patterns already listed in `AGENTS.md`.

## Index

| Date | Document | Status |
|---|---|---|
| 2026-10-27 | [research-bridge design](../superpowers/specs/2026-10-27-research-bridge-design.md) | user-approved; built through Task 12 (hashes in the ledger predate the 2026-11-02 rewrite of `main`) |
| 2026-11-02 | [Unified research board](2026-11-02-unified-board.md) | draft |
| 2026-11-03 | [Node-side job approval (SEC-01)](2026-11-03-node-side-approval.md) | draft; implemented on branch `claude/sec-01-02-fixes` |
| 2026-11-06 | [Shared research status page](2026-11-06-shared-status-page.md) | built (steps 3–4, commits e68109a, 218d60a); steps 2, 5, 6 open |
| 2026-11-10 | [Node GPU allowlist and worker-assigned GPU](2026-11-10-allowed-gpus.md) | draft; implemented on branch `claude/node-allowed-gpus` |

The first design stays at `docs/superpowers/specs/` because the plan and `AGENTS.md` refer to that path. New designs go in this directory.

## Candidates

Open items in `docs/HANDOFF.md` §Follow-ups that change the protocol or the ledger and so need a design first:

- `to_session` and attachment byte totals in ledger records (bridge edges show `<node>:responder` and 0 bytes today).
- `reply_to` on the node side (`msg_begin` has no such field).
- Locking of node queue numbering for more than one submitter.
- Restricting or removing `<SHARED_KEY>` on node1 (pending decision 2).

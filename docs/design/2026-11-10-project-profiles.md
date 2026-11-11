# Project profiles: serving research projects other than the first one — design

Date: 2026-11-10 · Status: draft · Author: session research-bridge-f6 (2026-11-10) · Code (proposed, none in this branch): `rb_node/config.py`, `rb_node/configure.py`, `rb_node/remote.py`, `rb_node/withheld.py`, `rb_node/jobs.py`, `rb_node/run_job.py`, `rb_node/spawn.py`, `rb_node/local.py`, `rb_node/cli.py`, `rb_host/client.py`, `rb_host/server.py`, `rb_host/jobs.py`, `rb_host/cli.py`, `rb_host/config.py`, `rb_host/store.py`, `rb_host/board.py`, `rb_host/share.py`, `vault-export/dashboard/rb_pending.py`, the sync and page modules of contract §1.3 · Data: node `~/.research-bridge/node.json` (new `profiles` object), hub `ledger.jsonl` (new optional `profile` field), hub `board/`, `fetched/`, `sync/`

Status history:
- 2026-11-10 draft (design only; nothing built; not shown to the user)
- 2026-11-10 independent audit applied (cancel profile, rollback effects, name checks in `hello`, default reads without `ref`, families per profile, responder and hard rule 8, mailbox hold, G8 site list, template checks)
- 2026-11-10 aligned with the experiment-records design and the built node code after a cross-check: `ref` meaning limited to `read_doc`; `withheld_digest` moved to the top level of `hello`; N2 `config check` behaviour on unknown keys corrected; ledger flag `capability_unverified`; profiles under `status.<node>.profiles` of the `nodes` result; forced-command note in §16.3; hard rule 8 wording note (§6.7); new MCP arguments listed as a user decision (§15 question 7). Still a draft.
- 2026-11-11 note: node1 runs `rb_node` 0.2.0 (N2, protocol 2) from `main` since the reinstall of 2026-11-10 (`docs/HANDOFF.md`; `docs/provisioning.md` section Results), and N2 and H2 are merged (PR 48). The words "today" and "installed node", the N0 row and the "today" column of §6.9 describe the state before that; they are left as written.
- 2026-11-11 corrected after the audit of that day (`docs/issues/2026-11-11-audit.md`); still design only, approval state unchanged. Topics: the installed node is N2 since the reinstall of 2026-11-10; the `queued_name` result and the check in `jobs.approve`; `families` in named `hello.profiles` entries and a `runs` row; `queue_status` name masking built in PR 53; the six defaults confirmed by the user on 2026-11-10; hard rule 8 wording; `poll` and `get_file` kind `out` held by the mailbox hold; the three `job_template` placeholders; `allowed_gpus` as a node-wide setting; the definition of "contract". Dated tables and open questions stay as written, with dated notes.

Abbreviations used below: MCP = Model Context Protocol (the tool interface Claude sessions use); SSH = Secure Shell; JSON = JavaScript Object Notation; GPU = graphics processing unit; YAML = a text configuration format the node does not parse; SHA-256 = the 256-bit Secure Hash Algorithm; HTML = HyperText Markup Language; sshd = the SSH server program on the node; GPU-hours = GPUs times wall-clock hours, the job budget unit. The generation names N0, N2, N3, H0, H2 and H3 are defined in the table below. Item codes such as PM-02 and SEC-03 are defined at first use with their source document. "Wire" means the line-delimited JSON request/response protocol between the hub's `NodeClient` (`rb_host/client.py`) and the node's `rb-node serve-remote` (`rb_node/remote.py`). "Egress" means any path by which bytes produced from node files leave the node. "Contract" is the coordinator contract of the 2026-11-10 review, working material that is not in the repository; references such as "contract §3" point into it. Its section 3 defaults are recorded in §11 and §12 below and in `docs/issues/2026-11-10-triage.md` §5. PR = pull request, a change merged into `main` on GitHub.

Node and hub code generations used in this document:

| Name | What it is | Answers `hello` with |
|---|---|---|
| N0 | `rb_node` 0.1.0, the code installed on node1 today | `node`, `version`, `withheld_extra` (`rb_node/remote.py:62-64`) |
| N2 | `rb_node` 0.2.0, built in this branch (contract §1.4) | adds `protocol: 2`, `ops`, `state` |
| N3 | the profile-aware node proposed here | adds `protocol: 3` and `profiles` |
| H0 | hub code on `main` before this branch | never sends `hello` (no use in `rb_host/`) |
| H2 | hub code built in this branch (contract §1.1–1.3) | sends `hello` once per sync pass and in `rb doctor` |
| H3 | the profile-aware hub proposed here | sends `hello` on every connection that carries a profile |

"Old node" means N0 or N2. Both ignore an unknown argument without error (`rb_node/remote.py:384-389`: `args` is passed whole to the op, which reads only the keys it names), so for profiles they behave the same. "Old hub" means H0 or H2. Neither ever sends a `profile` argument, so for profiles they behave the same.

Note (2026-11-11): N2 and H2 are merged into `main` (PR 48, merge commit c503667), and node1 no longer runs N0. After the reinstall from `main` on 2026-11-10 it runs `rb_node` 0.2.0 with protocol 2, which is N2 in this table (`docs/HANDOFF.md`, section "Node state and node-local tests"; `docs/provisioning.md` section Results; `rb_node/__init__.py`). The `node.json` observed on 2026-11-10 holds a `job_template` and an `allowed_gpus` list. The words "today" and "installed node", and N0 as the installed code, describe the state before that reinstall. They occur in this document (the table above, §5, §6.9, question 6) and in the experiment-records design (§6.12). The compatibility rows for N0 stay valid for any node that still runs the older code.

## 1. Intent

research-bridge was built for one research tree on one node. The current test project is called trm, and its name, its directory layout, its document identifiers and its withheld series are written into code and into the wire protocol (inventory in §6.1). The user wants the bridge to serve other experiments as well. Two needs follow:

1. Stop assuming trm: a second project must be able to declare its own research root, readable directories, document kinds, withheld patterns, queue and job command without a code change.
2. Let one node serve more than one project at the same time, with each request saying which project it is for, without weakening the withheld rule (hard rule 3) and without breaking the node that is installed today, which the hub cannot update.

This document defines a **project profile**, where it is stored, how the hub learns which profiles a node has, how every operation, record and page gains a project dimension, and the order in which the change can be made so that each step leaves the system working. §16 says what can be done for a new project today, before any of this is built.

## 2. Goals

- G1. One node serves two or more research trees. Every operation that touches a tree (document read, file fetch, queue status, git state, message, job submission and cancellation) can name the tree by profile name. A request that names no profile behaves exactly as today.
- G2. A request that names a non-default profile never reaches a node that cannot honour it. The hub refuses it locally, with nothing sent, when the node's `hello` on the same connection does not list that profile.
- G3. The five fallback withheld patterns of hard rule 3 stay on for every profile. Masking on the node and the re-check on the hub use the union of the patterns of all profiles on every egress path, so adding a profile can only make masking stricter. When a named profile's pattern source fails to load, the union is incomplete; the node then holds back mailbox egress node-wide until it loads again, while document reads of the other profiles continue with the incomplete union, a stated residual (§7.2 rule 4). The default profile's flat source is the one exception: when it fails, the node keeps today's behaviour (fallback patterns plus the other sources, and a `fail` in `rb-node doctor`), so masking during that time is weaker than the union (open question 2).
- G4. Profile settings come only from `node.json`, edited on the node console. No bridge operation reads or writes them, the hub never sends a path root, and nothing is loaded from the research tree.
- G5. Every combination of old or new hub with old or new node keeps working for the default profile (§6.9 tables).
- G6. Ledger records, board cache, fetched files, stored messages, the hub page and the MCP `nodes` result show the profile. Existing data files stay valid without a migration.
- G7. Both approval surfaces of hard rule 1 name the profile of every job: the text shown by `rb approve` and `rb pending`, and the loopback `/rb/pending` page on port 8765.
- G8. The bridge code (`rb_node/`, `rb_host/`) holds project facts only at an explicit list of sites: (a) the five fallback patterns in `rb_node/withheld.py` (hard rule 3); (b) the legacy `trm_root` key, its built-in default and the `trm` wire and console keys, with their alias handling (the `NodeConfig` field `trm_root` stays, inventory #52, but N3 code reads it only in the function that forms the default profile and in `config set`/`config check`; every other site uses the profile's `project_root`); (c) the legacy default kinds `exp` and `h` derived from `experiments_dir` and `hypotheses_path` (`rb_node/remote.py:28-29`, §6.4); (d) the hub's `_DOC_ID` (`rb_host/server.py:23`), which stays for default-profile reads on every node (§6.6); (e) the built-in defaults of `NodeConfig` (`rb_node/config.py:17-40`: default root, read roots, queue, pattern source, document paths), which an older reader also uses; (f) the hub's default-profile board and share facts: vault default paths, event and kanban field names and the stage pattern `^S[0-8]$` (`rb_host/config.py:14-15`, `rb_host/board.py:24,28-32`, `rb_host/share.py:30-31`; named profiles set their own through `nodes.<n>.profiles.<p>`, §8.3). No other site names a project, a layout or a series. Facts about a project live in `docs/projects/<name>.md`, filled in from `docs/projects/TEMPLATE.md`. Existing design documents that describe trm facts (the 2026-10-27 design §2, §6.5, §7; the board and share designs) get a note pointing to `docs/projects/trm.md` in step P7; their text is not rewritten.

## 3. Non-goals

- Coordinating GPUs between profiles. Each job's budget is checked as today; two queues on one node may compete for the same GPUs. The node does not arbitrate.
- A second queue kind (for example running a job directly without a queue runner). The profile field `queue_kind` is defined so that one can be added later; the only value is `file-queue`.
- Per-profile approval passphrases. One verifier per node stays (open question 5).
- Per-profile masking (masking a reply for profile A with A's patterns only). Rejected in §7.2.
- Changing the ten MCP tool names, or the meaning of any hard rule. Where the wording of a rule names a detail this design changes (hard rule 8, §6.7), the rule text in `AGENTS.md` is updated in the same change and the meaning stays.
- Renaming wire keys or `node.json` keys in a way that breaks an older reader. Every change is additive.
- Moving the harness channel (`rb harness`) into profiles. It is tied to the user's Claude configuration, not to a research tree (`rb_host/harness.py`, `rb_node/harness.py`), and stays node-wide.

## 4. Anti-goals (failure even if it works)

- Withheld content of one project leaving the node because a request, reply or file was masked with another project's patterns only.
- A request for profile B answered silently from the default tree: a document of the same relative path, a job queued into the default queue with the default job command, or a git state of the wrong tree. This is what an old node does with an unchecked `profile` argument (§6.5).
- A Claude session working in a research tree widening its own read roots, changing the command an approved job runs, or switching off a pattern, by editing a file in that tree.
- A renamed or removed `node.json` key making a node fall back to the built-in default tree `~/project/trm` (`rb_node/config.py:17,22`) without an error. The loader drops unknown keys silently (`rb_node/config.py:59-60`).
- A job approved without the approver seeing which project's queue and command it goes to.
- From the research-bridge design §4: an unauthorized read or write, a job submitted twice or without approval, agent text in manuscripts.

## 5. Constraints

- Contract §0: hard rules 1 to 9 are unchanged in meaning (the wording of rule 8 is updated as stated in §6.7); exactly ten MCP tools with unchanged names; every wire change is additive; node code is standard library only, Python >= 3.8, `from __future__ import annotations` in every module; placeholders only.
- The installed node runs N0 and cannot be updated from the hub. The user runs `scripts/node-install.sh --update` on the node console, and a session asks before any node command (AGENTS.md). Note (2026-11-11): since the reinstall of 2026-11-10 the installed node runs N2; the hub still cannot update it (note under the table of code generations at the top).
- Hard rule 1: `submit_job` and `cancel_job` make no SSH call, so a profile can be checked against the node only when the user approves, not when the session submits.
- Hard rule 3: fallback patterns always on; text masked line by line; pdf, tex and images denied on a hit; unknown extensions denied; the hub re-checks everything it stores.
- Hard rule 4: paths come from node configuration only, never from the host.
- Hard rule 8: one spawned server session at a time per node.
- The design builds on the state after contract §1.4 (N2, H2). Sibling designs in this branch: `2026-11-10-setup-and-diagnosis.md` (`hello.state`, `rb doctor`, `rb-node doctor`), `2026-11-10-sync-and-hub-page.md` (sync file `sync/<node>.json`, `rb web serve` routes), `2026-11-10-experiment-records.md` (experiment families, run records). Names below follow those documents where they overlap. Three overlaps with the experiment-records design are settled here as follows (My call (user to check); the experiment-records design states the same rules in its §5, §6.2, §6.3 and §7.3):
  - Protocol number: both gates test the presence of a field (`hello.families`, `hello.profiles`), never the number. `protocol` is informational; a node that has both features reports the higher number (3).
  - Argument name `ref`: the name appears in both designs with different meanings. On `read_doc` (this design, §6.6) it is a document reference resolved by the node with the profile's kinds, then as a path; that meaning applies to `read_doc` only. On `job_submit` (experiment-records design §6.3) it is a label that neither the hub nor the node opens.
  - Families and profiles: families of the default profile are the top-level `families` object of `node.json` (as the experiment-records design writes them); families of a named profile are declared in `profiles.<p>.families` with the same fields, and their relative paths resolve against that profile's `project_root`. A family belongs to exactly one profile. The flat `job_template` is the implicit family `default` of the default profile; a named profile's `job_template` is the implicit family `default` of that profile. A `job_submit` that names a family runs the family's `job_template`, never the profile's. The GPU-hour ceiling of a job is the smallest of the family's `max_gpu_hours`, the profile's `max_gpu_hours` and the node limit. On the approval connection the hub checks both: the profile in `hello.profiles` (§6.5) and the family among that profile's families (top-level `hello.families` for the default profile, as the experiment-records design defines it; a `families` list in the named profile's `hello.profiles` entry), before any upload.

## 6. Architecture

```
hub (Linux server)                                     node1 (one SSH account)
───────────────────────────────────                    ───────────────────────────────────────────
Claude session ─stdio─ rb-host-mcp ─┐                   rb-node serve-remote (forced command)
rb approve / rb sync / rb web ──────┼─ssh (one connection per call)─▶  reads ~/.research-bridge/node.json once
                                    │   1. hello  ──────────────────▶  {protocol: 3, profiles: [...]}
                                    │   2. op {..., profile: "b"} ──▶  profile "b": root, read roots, kinds,
                                    │   ◀── result {..., profile: "b"}            queue, job command
                                    │                                  masking: fallback + union of all profiles
ledger.jsonl {…, profile: "b"}      │                                  mailbox, approval verifier, responder lock,
board/node1@b_events.json           │                                  GPU pool: node-wide
fetched/node1/b/…                   │
                                                       rb-node respond <msg> ─ claude -p, working dir = profile root
                                                       rb-node serve-profile b (live session in tree b)
```

Connections still go from the hub to the node only (hard rule 2). The node never learns a path from the hub.

### 6.1 Inventory: where code and wire assume one project or one layout

Verified in the worktree code on 2026-11-10 (line numbers of branch `claude/review-optimize-2026-11-10` before contract §1 changes land; the builder re-checks them). Side: W = on the wire, N = node only, H = hub only, T = tests.

| # | Where | Assumption | Side | Answer in this design |
|---|---|---|---|---|
| 1 | `rb_node/config.py:17,22` | one research root `trm_root`, default `~/project/trm` | N | §6.4 `project_root`, alias `trm_root`; profiles |
| 2 | `rb_node/config.py:23-25` | default read roots are one project's layout | N | per-profile `read_roots` |
| 3 | `rb_node/config.py:26-28` | write roots and queue directory under the one root | N | per-profile `queue_dir`; `write_roots` stays node-wide (no bridge op writes through it: only `rb_node/harness.py:179` calls `resolve_write`) |
| 4 | `rb_node/config.py:29` | one withheld source, defaulting to a YAML file the loader cannot parse | N | per-profile sources; contract §1.4 already moves the default to `~/.research-bridge/withheld-patterns.json` |
| 5 | `rb_node/config.py:31` | one `job_template` | N | per-profile `job_template` |
| 6 | `rb_node/config.py:38-40` | one experiments directory and one hypotheses file | N | per-profile document kinds (§6.2) |
| 7 | `rb_node/config.py:59-60` | unknown keys are dropped without a message | N | never remove or rename a flat key (§6.4) |
| 8 | `rb_node/configure.py:101-118` | `config set` takes one flat key; values are strings, lists of strings or integers; an unknown key is refused (`:103-104`) | N | new `rb-node config profile …` subcommand for nested values |
| 9 | `rb_node/configure.py:126-128,139-142` | `config check` reports `profiles` as unknown; messages say `trm_root` | N | N3 checks profiles; messages say `project_root` |
| 10 | `rb_node/remote.py:26` | one set of masked text types | N | node-wide; optional per-profile additions later (§14) |
| 11 | `rb_node/remote.py:28-29,286-296` | document identifiers are only `EXP-<n>` and `H-<n>`; anything else is `bad_id` | W (`read_doc` argument `id`) | kinds per profile; new argument `ref` (§6.6) |
| 12 | `rb_node/remote.py:44` | one `PathPolicy`, built once per connection from `trm_root` | N | one policy per profile, built at connection start |
| 13 | `rb_node/remote.py:45-46` | one `Withheld` from one source | N | one node-wide `Withheld` from the union (§7.2) |
| 14 | `rb_node/remote.py:62-64` | `hello` carries no capability or profile data | W | `protocol: 3`, `profiles` (§6.5) |
| 15 | `rb_node/remote.py:75-105` | `msg_begin` has no project field; `message.json` is built from named keys only (`:102-104`), so an extra key is dropped | W | optional `profile`, stored in `message.json` |
| 16 | `rb_node/remote.py:257-284` | heading-section lookup in one file; one-file-per-id lookup in one directory under `trm_root` | N | kind lookup rules (§6.2) |
| 17 | `rb_node/remote.py:310-325` | one queue directory; entry names returned unmasked | W (`queue_status`) | per-profile queue; names masked with the union (§7.3) |
| 18 | `rb_node/remote.py:362-368` | `git_status` reports one tree under the wire key `trm` | W | key `tree` added, `trm` kept for the default profile |
| 19 | `rb_node/remote.py:381-389` | unknown ops answer `unknown_op`; unknown arguments are ignored | W | the reason for the same-connection check (§6.5) |
| 20 | `rb_node/withheld.py:11-17` | five fallback patterns name one project's series | N, imported by the hub | stay on for every profile (hard rule 3) |
| 21 | `rb_node/withheld.py:48-80` | one source file | N | union of all declared sources |
| 22 | `rb_node/jobs.py:16-17` | config extensions and the 168 GPU-hour limit fixed for every project | N | per-profile `config_ext`, `max_gpu_hours` (capped at the node limit) |
| 23 | `rb_node/jobs.py:79-89,157-160` | job numbering and job files in one queue directory | N | per-profile queue directory |
| 24 | `rb_node/jobs.py:146-152` | one job command | N | per-profile `job_template`; job file passes `--profile` for named profiles only (§6.6) |
| 25 | `rb_node/jobs.py:153` | git state pinned from `trm_root` | N | from the profile root |
| 26 | `rb_node/jobs.py:165` | `queued` returns the absolute queue path, stored in the hub ledger | W | named profiles return `queued_name` (file name only) |
| 27 | `rb_node/jobs.py:178-189` | cancel looks in one queue | N | profile recorded per job at submit |
| 28 | `rb_node/run_job.py:45,55-59,105-108` | git state from `trm_root`; `job_finished` event carries no project | N, W (poll item) | `run-job --profile`; event gains `profile` |
| 29 | `rb_node/spawn.py:100-110,131` | responder runs `claude -p` in `trm_root`; `serve-local` gets no project | N | working directory from the message's profile; `serve-profile <name>` for named profiles (§6.7) |
| 30 | `rb_node/local.py:57,108-114` | `serve-local` policy from `trm_root`; `inbox_list` shows every message | N | policy and inbox filter per profile (§6.7) |
| 31 | `rb_node/mailbox.py:148-170` | outgoing items have no project field | N, W (poll item) | `post_out` gains optional `profile` |
| 32 | `rb_node/cli.py:139-140,154` | `run-job` and `git-status` use `trm_root`; console output key `trm` | N | `--profile`; output key `tree` |
| 33 | `scripts/node-install.sh:12-14,24,62` | option `--trm-root` writes `trm_root` | N | contract §1.4 adds `--research-root` (alias kept) |
| 34 | `scripts/trm-link.sh:2,7,10,16` | live-session link for one tree, no project | N | contract §1.4 replaces it with `rb-node link`; add `--profile` |
| 35 | `deploy/node.json.example:2,4-7,12,14` | `trm_root` and one project's layout | N | example shows the flat keys plus one `profiles` entry |
| 36 | `rb_host/server.py:23,154` | hub regular expression `^(H\|EXP)-\d+$` decides whether `read_doc` sends `id` or `path` | H, selects W argument | kept for default-profile reads on every node; `ref` sent only for named profiles (§6.6) |
| 37 | `rb_host/server.py:26-35` | `_run` opens one connection per call and runs one function; no `hello` | H | connection-scoped `hello` gate (§6.5) |
| 38 | `rb_host/server.py:38-40` | `nodes` returns names only | H | adds `status.<node>.profiles` from the sync file (display only) |
| 39 | `rb_host/server.py:84-87,112-115` | message ledger records carry `node`, no project | H | optional `profile` |
| 40 | `rb_host/server.py:164` | fetched files stored as `fetched/<node>/<basename>`; two trees with the same file name overwrite each other | H | `fetched/<node>/<profile>/` for named profiles |
| 41 | `rb_host/server.py:183`, `store.py:93`, `board.py:47`, `share.py:281` | one hub pattern file at four load sites | H | the hub set must hold the union; extra files under a new key (§7.2 rule 7) |
| 42 | `rb_host/server.py:191-214` | `queue_status`, `submit_job`, `cancel_job` take no project | H | optional `profile` argument (§6.8) |
| 43 | `rb_host/jobs.py:83-86,99-101` | job records carry no project | H | optional `profile` |
| 44 | `rb_host/jobs.py:124-134` | approval text shows no project | H | `profile:` line (§8.5) |
| 44a | `vault-export/dashboard/rb_pending.py:58-74` | the 8765 `/rb/pending` table builds its own columns (job, node, config, gpus, gpu_hours, note), not through `describe()`; no project column | H (vault copy) | profile column (§8.5); vault file edited through `vault-export/` only |
| 45 | `rb_host/jobs.py:191-202` | approval connection sends `approve_params`, `put_file`, `job_submit` with no capability check | H | `hello` gate before `put_file` |
| 46 | `rb_host/cli.py:157-167,191-194` | `rb git-status` and `rb sync` read wire key `trm` and print `trm_head`, `trm_dirty` | H, depends on W key | read `tree`, fall back to `trm` |
| 47 | `rb_host/config.py:14-15,41,57` | Windows vault defaults; one pattern file; `host.json` has no per-project section | H | `nodes.<n>.profiles.<p>` section |
| 48 | `rb_host/board.py:24,28-32,232` | node sources, vault defaults, event and kanban field names, cache id `<node>:<source>` | H | cache id `<node>@<profile>:<source>` for named profiles |
| 49 | `rb_host/share.py:30-31,283-287,333` | stage codes `S0`–`S8`; one hub-wide label allowlist; cache id `<node>:<source>` | H | per-profile stage pattern and label (§8.3) |
| 50 | `tests/test_withheld.py:96`, `tests/test_remote.py:264-270` | the fallback list has exactly five entries | T | unchanged (hard rule 3) |
| 51 | `tests/test_host_tools.py:19,68-71` | the exact set of ten tool names | T | unchanged; only optional arguments are added |
| 52 | `tests/test_remote.py:42,240-243`, `test_local.py:21`, `test_gitinfo.py:47` | `NodeConfig(trm_root=...)` and the file key `trm_root` | T | `trm_root` stays a constructor field and a file key |

Note (2026-11-11): this table records the code of 2026-11-10 and stays as written. Four rows have changed in `main` since. Row 17: `queue_status` names are masked on the node and checked again on the hub, shown as `(withheld)` and counted in `withheld_entries` (commit eccd19b, PR 53). Row 33: `scripts/node-install.sh` takes `--research-root DIR`, with `--trm-root` as an alias. Row 34: `scripts/trm-link.sh` is deleted (commit 684c948) and `rb-node link` exists. Row 46: `rb sync` reads the node's wire key `tree` first and `trm` second and writes `tree_head` and `tree_dirty` to the sync file; `rb git-status` prints the node's JSON unchanged and has no `trm_head`. The node still answers `git_status` with the wire key `trm` only (`rb_node/remote.py`, `git_status`).

### 6.2 The profile concept

A **profile** is a named set of the settings that describe one research tree on one node. The name matches `^[a-z][a-z0-9_-]{0,31}$`. The name `default` is reserved for the profile formed by today's flat keys (§6.4), and names starting with `withheld-` are reserved for the placeholder below. A node has at most 16 profiles, `default` included (so at most 15 named profiles): `rb-node config profile add` refuses a 16th named profile, and `config check` reports `fail` when `node.json` holds more (an N3 loader serves the first 16 in file order and marks the rest `available: false, reason: too_many`). A profile name and every kind name must not match any withheld pattern (fallback patterns plus the union of §7.2), because these names travel on the wire and into the hub ledger, page and sync file. `config check` and `config profile add|set` reject such a name. The N3 loader repeats the check at connection start, after building the union, because `node.json` may have been edited without `config check`: a profile whose name hits is reported in `hello` under the placeholder name `withheld-<n>` (n = its position) with `available: false, reason: bad_name` and cannot be selected; a kind whose name hits is left out of that profile's `kinds` list and is not served.

What a profile declares (all paths are on the node; relative paths join to `project_root`):

| Field | Type | Meaning | Required |
|---|---|---|---|
| `project_root` | absolute path | research root: base of relative paths, git state, responder working directory | yes |
| `read_roots` | list of paths | directories the bridge may read for this profile; must lie inside `project_root` unless absolute | yes |
| `kinds` | list of objects | document kinds, see below | no (path reads still work) |
| `withheld_source` | absolute path or empty | pattern file in one of the three accepted shapes (`rb_node/withheld.py:65-73`) | no |
| `withheld_patterns` | list of strings | inline patterns, for a project with few patterns | no |
| `queue_dir` | absolute path or empty | queue directory with `jobs/ processing/ done/ failed/`; empty means jobs are refused for this profile (`no_queue`) | no |
| `queue_kind` | string | `file-queue` (the only value) | no, default `file-queue` |
| `job_template` | list of strings | job command with a config placeholder (`{config}`, `{config_dir}` or `{config_stem}`, as the flat `job_template` accepts since PR 46); empty means `no_job_template` | no |
| `config_ext` | list of strings | accepted config extensions; default `.yaml .yml .json` | no |
| `max_gpu_hours` | number | per-job ceiling, at most the node limit (168 today); with a family, the smallest of family, profile and node limits applies (§5) | no |
| `families` | object | experiment families of this profile, same fields as the top-level `families` of the experiment-records design §6.2; a family's `job_template` replaces the profile's for requests that name it (§5) | no |
| `responder` | boolean | whether a committed message for this profile starts `rb-node respond`; default `true` | no |
| `responder_dir` | path | working directory of the responder, inside `project_root`; default `project_root` | no |

A **document kind** is an object `{"kind": <name>, "id_regex": <anchored regular expression>, …lookup}` with one of two lookup rules:

- one file per identifier: `{"dir": <relative dir>, "names": ["{id}.md", "{id}_*.md"]}`. The node tries each name pattern in order; the first pattern with at least one match is used; exactly one match is required, otherwise `not_found`. This is today's `_exp_ref` (`rb_node/remote.py:276-284`).
- one heading section per identifier: `{"file": <relative file>, "section": "heading"}`. The node returns the first heading that contains the identifier, up to the next heading of the same or higher level. This is today's `_h_section` (`rb_node/remote.py:257-274`).

Rules: kind names match the profile-name pattern; an identifier is at most 64 characters; `id_regex` is at most 200 characters and must start with `^` and end with `$`; kinds are tried in declared order and the first match wins; every `dir` or `file` must resolve inside one of the profile's `read_roots` (checked by `config check`, so a configured kind never answers a bare `denied`).

Node-wide settings that are **not** per profile: `mailbox_root`, `audit_path`, `approval_path` (one verifier), `claude_bin`, `max_file`, `harness_root`, `write_roots`, the responder lock and limits (hard rule 8), the GPU pool and `allowed_gpus` (the GPUs `job_submit` accepts and `run-job` may use; PR 47, `docs/design/2026-11-10-allowed-gpus.md`), job identifiers and idempotency keys, message identifiers.

### 6.3 Where profiles live

Profiles live in `node.json` on the node, in a new top-level object `profiles` keyed by name. They are edited only on the node console with `rb-node config profile add|set|show|remove|check`. No bridge operation reads or writes them, and `hello` reports names, availability and kind names only, never paths.

Reason (hard rule 4): paths come from node configuration only. A file inside the research tree would be writable by the Claude sessions that work there: a live session linked with `rb-node link` has write and shell tools, and the hub sends it messages. If read roots, `job_template` or withheld settings came from the tree, such a session could widen its own read roots, switch off a pattern file, or change the command that the next approved job runs. The approval covers the arguments of one request (`docs/design/2026-11-03-node-side-approval.md` §7 "Binding"), not the node's job command, so a changed `job_template` would run under a valid approval. `node.json` is outside every read and write root and is written mode 600 after a git exposure check (`rb_node/configure.py:22-67`).

A research tree may hold a descriptive file (for example `PROJECT.md`) that a session reads through `read_doc` like any other document, masked. The node never loads configuration from it.

### 6.4 Flat keys map to the profile `default`; naming

Today's flat keys in `node.json` **are** the profile `default`. They stay on disk with their current names, so N0, N2 and N3 read the same file and agree on the default tree.

| Flat key today | Profile field of `default` | Notes |
|---|---|---|
| `trm_root` | `project_root` | see naming rule below |
| `read_roots` | `read_roots` | unchanged, still includes the mailbox `out/` root as today |
| `queue_dir` | `queue_dir` | |
| `job_template` | `job_template` | |
| `withheld_source` | `withheld_source` | |
| `experiments_dir` | kind `exp`: `{"id_regex": "^EXP-\\d+$", "dir": experiments_dir, "names": ["{id}.md", "{id}_*.md"]}` | derived in code from the two keys and the regular expressions at `rb_node/remote.py:28-29`; not written to disk |
| `hypotheses_path` | kind `h`: `{"id_regex": "^H-\\d+$", "file": hypotheses_path, "section": "heading"}` | as above |
| constants `CONFIG_EXT`, `MAX_GPU_HOURS` (`rb_node/jobs.py:16-17`) | `config_ext`, `max_gpu_hours` | defaults; the default profile cannot change them (no new flat keys) |
| responder working directory = `trm_root` (`rb_node/spawn.py:131`) | `responder_dir` | default |

Naming rule for the root:

- The reader (N3 loader and `config check`) accepts the flat key `project_root` as an alias of `trm_root`. If both are present and equal, fine. If both are present and differ, `config check` and `rb-node doctor` report `fail` and the loader uses `trm_root`, because that is the value an N0 or N2 node would use; the two sides must never disagree about the default tree.
- The writer (`rb-node config set project_root DIR` and `config set trm_root DIR`) writes the flat key `trm_root` only. It does not write `project_root` to disk. Reason: an older node reinstalled over N3 reads only `trm_root`; a file holding only `project_root` would make it fall back to `~/project/trm` without an error (inventory #7).
- Inside `profiles`, named profiles use `project_root` only; older nodes ignore the whole `profiles` object.
- No value of the default profile ever moves from the flat keys into `profiles`. `profiles.default` is rejected by `config check`.
- Display text, messages and new documentation say "research root" and `project_root`; `trm_root` is documented as the legacy spelling that stays on disk.

Wire key for git state: `git_status` on N3 returns `{"profile": <name>, "tree": <state>, "install": <record>}` and, for the default profile only, also `"trm": <state>` with the same value, so H0 keeps working. H2 and H3 read `tree` and fall back to `trm`. Hub output and the sync file use `tree_head` and `tree_dirty` (contract §1.3).

What an older node does with a file that has `profiles`: N0 and N2 drop the key on load (`rb_node/config.py:59-60`), so they serve the default profile only. N0's `config check` prints `unknown key 'profiles' is ignored` and exits 1 (`rb_node/configure.py:126-128`). The N2 code built in this branch reports the unknown key as a warning (check `config_keys`, setup-and-diagnosis design §6.3) and exits 0, because `config check` exits 1 only on a `fail`; so on N2 a file with `profiles` passes `config check` with one warning line. Both refuse `config set profiles …` as an unknown key (`rb_node/configure.py:103-104`), so they cannot damage the object.

### 6.5 Wire: `hello.profiles` and the same-connection check

N3 extends the `hello` result of contract §1.4 (`protocol`, `ops`, `state`):

```json
{"node": "...", "version": "0.3.0", "protocol": 3, "withheld_extra": 12,
 "withheld_digest": "<64 hex>",
 "ops": ["..."], "state": {"...": "...", "mailbox_held": false},
 "profiles": [
   {"name": "default", "available": true, "kinds": ["exp", "h"], "queue": true, "responder": true},
   {"name": "b", "available": false, "reason": "withheld_source", "kinds": ["run"], "queue": true, "responder": true, "families": [{"id": "..."}]}
 ]}
```

`withheld_digest` is a top-level field, next to `withheld_extra`, because `hello.state` holds only booleans and counts (plus the `python` version string) under the setup-and-diagnosis design §6.5; `state` gains only the boolean `mailbox_held` (§7.2 rule 4). `profiles` lists every configured profile, `default` first. `available: false` carries a short reason code (`root_missing`, `withheld_source`, `bad_kind`, `bad_name`, `too_many`; §6.2 says when `bad_name` and `too_many` are set). An entry of a named profile also carries `families`, a list of the family objects that the experiment-records design §6.2 defines for the top-level `hello.families` (id, metric, caps, `egress`; never argv or paths); the default profile's families stay in the top-level `hello.families` (§5), so its entry has no `families` field (added 2026-11-11, see §5 and §12). No paths, no pattern text, no `id_regex` text. Profile and kind names in `hello` have passed the withheld check of §6.2 on this connection.

Why the hub must check on the same connection: an old node silently ignores the `profile` argument (`rb_node/remote.py:384-389`) and answers from the default tree. A `read_doc` by path would return the default tree's file of the same relative name; a `job_submit` would queue into the default queue with the default job command. Neither returns an error. Each hub call opens its own SSH connection, and each connection starts a fresh `serve-remote` process that loads `node.json` and the code once (`rb_node/remote.py:41-59`, `rb_node/cli.py:183-192`). The answer to `hello` on that connection therefore describes exactly the process that will run the next operation. A cached `hello` (for example from the sync file) can be stale: the user may reinstall older code, or remove a profile, between the cache and the call.

The rule, for every hub call that sends a `profile` argument other than `default`:

1. Open the connection, send `hello`.
2. If the result has no `profiles` list, refuse locally with `node_too_old`. If the name is absent, refuse with `unknown_profile`. If `available` is false, refuse with `profile_unavailable` and the reason. For a `job_submit` that names a family, also refuse when the family is not among that profile's families (§5). Nothing else is sent on that connection.
3. Send the operation with `profile`.
4. Check that the result echoes `"profile": <name>` (N3 echoes `profile` on every op that takes it, whether or not the argument was sent; the hub checks the echo only for named profiles). A missing or different echo for a read means the result is discarded and the call returns `profile_mismatch`. For `job_submit` the echo arrives after the job is queued, so it is a second check only; a mismatch marks the ledger record `queued_unverified` and the page shows it. Steps 1–2 are the guard.

The hub never sends `profile: "default"`; it omits the argument, which every node generation understands. The gate is not keyed on `protocol`, because N2 reports `protocol: 2` and also ignores `profile`; the presence of the requested name in `profiles` is the only test.

Hub code sites where the gate runs inside the open connection (one helper on `NodeClient`, `hello` cached on the client object for the life of that connection only):

| Site | Today | Change |
|---|---|---|
| `server._run` (`rb_host/server.py:26-35`) | runs one function on a fresh client | takes an optional `profile`; runs the gate before the function. Covers `send_message`, `read_doc`, `fetch_file`, `queue_status`, and the board fetches, which call `server.read_doc` and `server.fetch_file` (`rb_host/board.py:202,207`) |
| `jobs.approve` (`rb_host/jobs.py:191-202`) | `approve_params`, `put_file`, `job_submit` or `job_cancel` | gate first, before `put_file`, so a refused profile leaves no upload on the node |
| `rb git-status` (`rb_host/cli.py:161-162`) | `git_status` | gate when `--profile` is given |
| sync pass (`rb_host/cli.py:191-194`; `rb_host/sync.py` after contract §1.3) | `git_status` per node | already sends `hello` (contract §1.3); runs `git_status` once per available profile |

The sync file (`sync/<node>.json`) may feed display (the page, the `nodes` tool, `submit_job`'s early warning in §6.8) but never the gate.

### 6.6 Per-operation behaviour on N3

| Op | Profile argument | Behaviour |
|---|---|---|
| `hello` | none | adds `protocol: 3`, `profiles`, `withheld_digest` (top level), `state.mailbox_held` (§7.2 rule 4) |
| `msg_begin` | optional | stores `profile` in `message.json`; a retry with the same `msg_id` and a different profile is `conflict` |
| `put_chunk`, `msg_commit` | none | unchanged; `msg_commit` triggers the responder only when the message's profile has `responder: true` |
| `poll` | none | node-wide; every item gains `profile` (from `post_out`); masking with the union (§7.2); no items while a named profile's source fails (§7.2 rule 4) |
| `ack` | none | unchanged |
| `get_file` kind `doc` | optional | resolves `ref` with the profile's policy; masking with the union |
| `get_file` kind `out` | ignored | mailbox is node-wide; refused with `profile_unavailable` while a named profile's source fails (§7.2 rule 4) |
| `read_doc` | optional | new argument `ref`, used by H3 only together with a named profile: the node tries the profile's kinds in order; a `ref` that matches a kind's `id_regex` but finds no unique document is `not_found` and is not retried as a path; a `ref` that matches no kind is treated as a path. The legacy arguments `id` and `path` keep working and are what every hub sends for the default profile |
| `queue_status` | optional | reads the profile's `queue_dir`; names masked with the union (§7.3) |
| `gpu_status` | none | node-wide |
| `runs` (new op of the experiment-records design §6.7; added 2026-11-11) | none | for each job id the node looks in the queue directories of the profile recorded for that id (`state/job-profile/<job_id>`; `default` when none) and answers as that design says; the answer carries `profile` like every result here; how a `since` query covers several queues is left to the builder |
| `job_submit` | optional | profile's queue, `job_template` (or the named family's, §5), `config_ext`, `max_gpu_hours` (smallest of family, profile and node limits); git state of the profile root; records the profile for the job id (`state/job-profile/<job_id>`); the job file of a named profile runs `run-job --profile <name>`, the job file of the default profile runs `run-job` without `--profile`, exactly as today; result adds `profile` and `queued_name` (file name only; for named profiles the absolute `queued` path is omitted). Note (2026-11-11): since commits 0a1e35b and fce8b2b, `jobs.approve` in `rb_host/jobs.py` marks a submit `queued` only when `queued` is a string ending `_<job_id>.job`; otherwise it resets the record to `pending_approval` and raises. H3 changes that check to read `queued_name` (also ending `_<job_id>.job`) when `queued` is absent for a named profile (P4) |
| `job_cancel` | optional | without the argument, the node uses the profile recorded at submit (default when none); with it, a different recorded profile is `profile_mismatch`. H3 always sends the profile it showed the approver when that profile is named (§8.5), so the node acts on the profile the approver saw |
| `approve_params` | none | unchanged (one verifier) |
| `git_status` | optional | `tree` for the profile; `trm` too for the default profile (§6.4) |

The node audit record (`rb_node/remote.py:379-388` today keeps `id`, `op`, `msg_id`, `name`) gains `profile` when the argument is present. A profile name is configuration, not message content, so hard rule 6 is kept.

Every op that takes `profile` returns it in its result on N3, whether or not the argument was sent, including the default (`"profile": "default"`). The hub checks this echo only for named profiles (§6.5 step 4). An unknown or malformed name is `unknown_profile`; an unavailable profile is `profile_unavailable`. Both error codes are new and are only ever seen by H3, because old hubs never send the argument.

`read_doc` with `ref` lets the node, which owns the kinds, decide whether a reference to a named profile's tree is an identifier, so named profiles need no identifier pattern on the hub. For the default profile H3 keeps `_DOC_ID` and the legacy `id`/`path` choice on every node generation (inventory #36). Reason: §6.5 sends `hello` only for named profiles, so for a default read the hub does not know whether the node understands `ref`; N0 and N2 ignore `ref` and fail with `bad_args` because `path` is missing (`rb_node/remote.py:286-298`). Nothing is lost, because the default profile's kinds are always the derived `exp` and `h` (§6.4), which `_DOC_ID` already covers.

### 6.7 Responder, `serve-local`, `run-job`

- `rb-node respond <msg_id>` reads the message's profile from `message.json` (absent means `default`) and runs `claude -p` with working directory `responder_dir` of that profile. The MCP configuration it writes (`rb_node/spawn.py:100-110`) starts `serve-profile <name>` for a named profile and plain `serve-local` for the default profile (see the `link` bullet below). The lock stays node-wide (hard rule 8): one responder at a time across all profiles. One detail of this change differs from the wording of hard rule 8 in `AGENTS.md` ("tools = serve-local MCP"): for a named profile the responder's bridge tools come from `serve-profile <name>`, which serves the same tools as `serve-local` restricted to that profile. The rule text in `AGENTS.md` is updated in the change that builds `serve-profile`. (Corrected 2026-11-11: this text also named a second difference, the lock whose holder process and process group are both gone counting as stale before the age threshold, setup-and-diagnosis design §6.7. That wording is in `AGENTS.md` since commit fb5ccc2, paragraph "Rule 8, dead holder".) The meaning of rule 8 (one responder at a time, read-only tools, writes only through `reply`) is unchanged.
- While any named profile is unavailable because its withheld source failed to load, the node does not spawn a responder for any message (messages stay `new`; one `responder_failed` event with reason `withheld_source` is queued per message and leaves the node only after the source loads again, §7.2 rule 4). Reason in §7.2.
- `serve-local --profile <name>` builds its policy from that profile; `inbox_list` and `inbox_read` show only messages whose profile is `<name>` (absent counts as `default`); `reply` copies the replied message's profile into the outgoing item; `post_event` uses the server's profile. `serve-local` without `--profile` is the default profile, so a node with one project behaves as today.
- `rb-node link DIR --profile <name>` (contract §1.4 command) writes the profile into the printed MCP entry. My call (user to check): for a named profile, the entry that `link` writes, and the MCP configuration the responder writes, run `rb-node serve-profile <name>`, a subcommand that does the same as `serve-local --profile <name>`. Reason: older `rb-node` ignores unknown options after `serve-local` (the top-level parser uses `parse_known_args` and the `serve-local` branch never reads the rest, `rb_node/cli.py:182,193-206`), so an entry `serve-local --profile b` left in a tree after a rollback would silently serve the default tree's policy and every inbox message. Older code refuses an unknown subcommand name (the parser accepts only names in `SUBCOMMANDS`) and exits 2, so the session's bridge server fails to start instead. Entries for the default profile stay plain `serve-local`. An environment variable naming the profile would not help here, because older `serve-local` reads no such variable either. `rb-node doctor` on N3 lists the `.mcp.json` files that `link --apply` wrote (recorded in `~/.research-bridge/state/links.json`) and says which name a profile.
- `run-job --profile <name>` takes the git state from that profile's root and adds `profile` to the job record and to the `job_finished` event.

### 6.8 Interfaces

| Name | Kind | Notes |
|---|---|---|
| `hello` result fields `profiles`, `protocol: 3`, `withheld_digest` (top level), `state.mailbox_held` | read | additive |
| optional `profile` on `msg_begin`, `read_doc`, `get_file`, `queue_status`, `job_submit`, `job_cancel`, `git_status` | read / mutation | ignored by old nodes, hence the gate |
| `read_doc` argument `ref` | read | N3 only; H3 sends it only with a named profile, after the gate; default-profile reads always use `id`/`path` (§6.6) |
| `profile` echoed in results and on poll items | read | |
| new error codes `unknown_profile`, `profile_unavailable`, `profile_mismatch`, `no_queue`; hub-local `node_too_old`, `queued_unverified` | — | |
| MCP tools `send_message`, `read_doc`, `fetch_file`, `queue_status`, `submit_job`, `cancel_job` gain an optional argument `profile` (default: the default profile); not built before the user confirms (open question 7) | read / mutation (pending) | tool set and names unchanged (hard rule 1, `tests/test_host_tools.py:68-71`). `poll`, `thread`, `gpu_status` stay node-wide; their results carry `profile` per item |
| MCP `nodes` result gains `status.<node>.profiles` (inside the per-node `status` object of sync-and-page design §6.8) from the sync file; that object already carries `last_ok_at` | read | display only |
| `cancel_job` copies `profile` from the ledger record of `target_job_id`; an explicit `profile` that differs from it is refused (`profile_mismatch`, nothing written); when the target is not in the ledger, the record gets `profile_unknown: true` and no `profile` | mutation (pending) | no SSH call; the approver sees the profile the node will act on (§8.5) |
| `submit_job` checks the name grammar; if the sync file lists the node's profiles and the name is absent it refuses with `unknown_profile`; if there is no sync data it records `capability_unverified: true` (the flag name the experiment-records design uses for the same case, §6.3 there) | mutation (pending) | no SSH call (hard rule 1); the authoritative check is the gate in `rb approve` |
| `rb-node config profile add\|set\|show\|remove\|check` | node console | only way to edit `profiles` |
| `rb-node serve-local --profile`, `rb-node serve-profile <name>` (written into MCP entries, §6.7), `rb-node run-job --profile`, `rb-node link --profile`, `rb-node git-status --profile` | node console / internal | |
| `rb git-status --profile`, `rb web serve` profile column and filter | hub | |

### 6.9 Compatibility tables

"default" = a request that names no profile; "named" = a request that names another profile. Old hub = H0/H2, new hub = H3, old node = N0/N2, new node = N3.

**Per operation, default profile**

| Op | Old hub → old node (today) | Old hub → new node | New hub → old node | New hub → new node |
|---|---|---|---|---|
| `hello` | H0 never calls; H2 reads `protocol`, `ops`, `state` (N2) or only `withheld_extra` (N0) | extra fields ignored | no `profiles`: hub marks node "single project" | full |
| `msg_begin` / `put_chunk` / `msg_commit` | works | works; message stored without `profile` = default | works; no argument sent | works |
| `poll` / `ack` | works | items carry `profile`; old hub ignores the field (`store_incoming` copies named keys only, `rb_host/store.py:161-162`) | items lack `profile`; hub attributes from its ledger (§8.1) | works |
| `get_file` doc / out | works | works; masking with the union (stricter) | works | works |
| `read_doc` | `id` or `path` | `id` or `path` still accepted for default | hub uses `_DOC_ID` and `id`/`path` | hub uses `_DOC_ID` and `id`/`path` (no `hello` for default calls, so no `ref`) |
| `queue_status` | works | works; names masked | works | works |
| `gpu_status` | works | works | works | works |
| `job_submit` / `job_cancel` | works | works; result adds `profile`, `queued_name` | works | works |
| `approve_params` | works | works | works | works |
| `git_status` | key `trm` (see note) | `trm` and `tree` | hub reads `tree`, falls back to `trm` | reads `tree` |
| responder / `serve-local` | default tree | default tree; `serve-local` without `--profile` = default | default tree | default tree |

Note on the "today" column: the commit installed on node1 is not known from the repository. `git_status` (commit `1fa1f12`), `approve_params` (`d8e3958`) and configurable `read_doc` paths (`2a4f0ec`) were added after 0.1.0 without a version change, so the installed N0 may answer `unknown_op` for the first two and use the old fixed document paths. Open question 6 asks to check this. Note (2026-11-11): node1 now runs 0.2.0 (N2), so this note and the "Old hub → old node (today)" column describe the state before the reinstall of 2026-11-10 (see the note under the table of code generations at the top of this document).

**Per operation, named profile** (only a new hub can send one; an old hub has no way to name a profile, so its column is "not possible")

| Op | Old hub → either node | New hub → old node | New hub → new node |
|---|---|---|---|
| `msg_begin` (message for profile b) | not possible | refused locally (`node_too_old`), nothing sent | stored with `profile`; responder in b's directory |
| `read_doc`, `get_file` doc | not possible | refused locally | b's policy and kinds; union masking |
| `queue_status` | not possible | refused locally | b's queue |
| `job_submit` | not possible | `submit_job` records `pending_approval`; `rb approve` refuses at the gate, record back to `pending_approval`, nothing uploaded | b's queue and job command; echo checked |
| `job_cancel` | not possible | refused at the gate | recorded profile; mismatch refused |
| `git_status` | not possible | refused locally | `tree` of b |
| `poll` items of b | old hub on a new node receives them with a `profile` field it ignores; ledger records them without a profile | — | attributed to b |

The last row is the one place an old hub sees named-profile data: if a new hub created b's messages and an old hub polls the same node, the old hub stores b's replies without a profile. Masking is unaffected (union on the node). Mixed hubs against one node are not a supported setup (§12).

## 7. Security

### 7.1 Path roots and configuration (hard rule 4)

- Each profile has its own `PathPolicy`, built from `node.json` at connection start. The hub sends a profile name, never a path root. A name selects one of the node's own configurations; it cannot create one.
- `config check` warns when read roots of two profiles overlap (one file readable under two names; masking is the union, so no leak follows, but provenance becomes ambiguous) and fails when a profile's read root contains `node.json`, `approval_path` or `mailbox_root/state`.
- The responder's Read, Grep and Glob tools are not confined to read roots (`docs/postmortems/2026-11-03-whole-branch-review.md`, item PM-02). A responder started for profile A can read files of profile B and of anything else the node account can read. Profiles do not change this; §7.2 is designed around it.

### 7.2 Withheld patterns with several profiles (hard rule 3)

Rules:

1. The five fallback patterns (`rb_node/withheld.py:11-17`) stay on for every profile. A profile cannot opt out. Over-masking another project's text is safe; under-masking is not. `tests/test_withheld.py:96` keeps pinning the count.
2. The node builds **one** `Withheld` per connection from: the fallback patterns, the flat `withheld_source`, every profile's `withheld_source`, and every profile's `withheld_patterns`. That one set masks every egress path for every profile (§7.3).
3. Reason for the union instead of per-profile masking: a reply posted for profile A can contain text the responder read from profile B's tree (§7.1), and an outgoing item does not record which files it was built from. Masking A's reply with A's patterns only would let B's withheld lines out. The same holds for a live session linked to tree A. Per-profile masking would be correct only if every reader were confined to its tree, which is not the case.
4. A non-default profile whose declared source cannot be read or parsed is `available: false, reason: withheld_source`. Its ops are refused, and the responder is suspended node-wide (§6.7), because a suspended pattern set weakens the union for every reply. For the same reason, My call (user to check), mailbox egress is held back node-wide while the source fails: `poll` returns no items (they stay undelivered on the node, and `ack` is unchanged) and `get_file` kind `out` is refused with `profile_unavailable`. Holding back only profile b's items would not be enough, because by rule 3 a reply for any profile, including one a live session posted through `serve-local` before the failure, may contain b's text. The hold also stops default-profile replies and `job_finished` events for every hub. An H3 hub sees it as an empty `poll` plus the profile's `available: false` in `hello`, and `rb doctor` and the sync file report it; N3 also sets `hello.state.mailbox_held: true`. An H0 or H2 hub sees only an empty `poll` (H2's `rb doctor` shows the `withheld_loaded` count and the node's `rb-node doctor` shows the `fail`). Residual, stated rather than closed: document reads (`read_doc`, `get_file` kind `doc`, `git_status`, `queue_status`) of the other profiles continue with the incomplete union; they return text from those profiles' own trees, which hold b's withheld lines only if someone copied them there. Rule 6 (the flat source holds the union) is the mitigation, since the flat source keeps b's patterns in force when b's own file fails. The default profile keeps today's behaviour for its flat source (fallback patterns plus a `fail` in `rb-node doctor`, contract §1.4), because changing it would change an installed system; open question 2.
5. `withheld_extra` in `hello` becomes the compiled count of the whole union minus the fallback; `withheld_digest`, a top-level field of `hello` (§6.5), is the SHA-256 of the sorted, de-duplicated list of compiled pattern strings of the union. No pattern text crosses the wire.
6. Rollback containment: if the node is later reinstalled with N0 or N2, it masks with the fallback plus the flat `withheld_source` only. `rb-node doctor` on N3 therefore warns, per profile, when that profile's patterns are not all contained in the flat source ("older node code would mask without these patterns"). Recommended practice, written into the project template: the flat `withheld_source` file is the node's union file, holding the patterns of every project on the node.
7. Hub side: the four load sites (`rb_host/server.py:183`, `store.py:93`, `board.py:47`, `share.py:281`) keep one pattern set. `withheld_patterns_file` in `host.json` stays a single path, because an H0 or H2 hub reading the same file passes it to `Path()` and would fail on a list. A new optional key `withheld_patterns_extra` (list of paths) is read by H3 only; one helper loads the single file and the extra files into one `Withheld`. An older hub ignores the new key (`rb_host/config.py:57` reads named keys only) and therefore re-checks with the single file, which should itself be the union. The hub's set must contain the union of every node's profiles. `rb doctor` compares the hub's digest with each node's `hello.withheld_digest` and reports `warn` on a difference (the hub may hold more, which is stricter; it cannot tell more from different).

### 7.3 Egress paths and what masks them

| Egress path | Code today | Masking with profiles |
|---|---|---|
| `poll` bodies, `reply_to`, attachment names | `rb_node/remote.py:174-200` | union, at egress time (older undelivered items are covered too); held back node-wide while a named profile's source fails (§7.2 rule 4) |
| `get_file` kind `doc` | `remote.py:210-227,233-234` | union; name check and content check as today |
| `get_file` kind `out` | `remote.py:235-244` | union; refused while a named profile's source fails (§7.2 rule 4) |
| `read_doc` text | `remote.py:286-307` | union |
| `git_status` branch, upstream, origin | `rb_node/gitinfo.py:60-67` via `remote.py:364-367` | union |
| `queue_status` entry names | `remote.py:310-325`, unmasked today (2026-11-10, as written) | masked since PR 53 (commit eccd19b, with the check repeated in `rb_host/server.py` `queue_status`): a name that hits the node's patterns becomes `(withheld)` and is counted in `withheld_entries`. N3 (step P2) masks with the union of all profiles' patterns instead of the flat source and fallback patterns |
| `job_submit` result `queued` | `rb_node/jobs.py:165`, stored in the hub ledger | contains only the configured queue directory and a hub-chosen job id, no tree content; for named profiles only `queued_name` is returned so the profile's layout does not reach the hub. Note (2026-11-11): the hub check in `jobs.approve` that `queued` ends with `_<job_id>.job` must then accept `queued_name` (§6.6, P4) |
| `hello` | `remote.py:62-64` | counts, names, booleans and a digest only; profile and kind names are checked against the union at connection start, a hit is replaced by a placeholder or left out (§6.2) |
| error messages | `remote.py:392-403` | unchanged: codes and type names only; `no unique document for <id>` echoes the hub's own identifier |
| hub: stored messages, fetched files, board cache, share snapshot, hub page | four load sites above; page re-masks at render (contract §1.3) | hub union |

### 7.4 Approval

- The node checks the approval key only: `sha256(key)` against the stored verifier (`rb_node/approval.py:104-121`, unchanged). The key is not bound to `profile`, `gpus` or any other argument by cryptography. What ties the profile shown to the profile sent is the hub: `rb approve` reads one ledger record, shows it through `describe()` and sends the same record's fields, `profile` included, on the approval connection. Tests: `tests/test_host_tools.py::test_describe_shows_profile` together with `::test_approve_sends_shown_profile` (asserts that the `profile` in the sent `job_submit` or `job_cancel` equals the one in the shown text).
- The approver must see the profile, because the profile selects the queue and the job command: §8.5.
- The gate runs before any upload on the approval connection, so a refused profile leaves no `job-<id>` message on the node. Hub-local refusals (`node_too_old`, `unknown_profile`, `profile_unavailable`) are added to the set that resets the record to `pending_approval` (`rb_host/jobs.py:19-20,203-207`).

### 7.5 Threat model

In scope: a hub that sends a profile to a node that cannot honour it; a session in one tree trying to read or influence another; a pattern file that fails to load; a node reinstalled with older code. Out of scope, as in the research-bridge design §7: root on the node, the hub's own user account, a process that rewrites `rb_host`.

## 8. Data and ledger

### 8.1 Ledger (`<data_root>/ledger.jsonl`)

- New optional field `profile` on `message` records (both directions) and `job` records. Written only when the profile is not `default`, so ledger lines of a one-project hub stay as today. Readers treat an absent field as `default`.
- Attribution of inbound items: an item's own `profile` (N3) wins. For items without it (old node, or events written before N3): a reply inherits the profile of the outgoing message named in `reply_to`; a `job_finished` event inherits the profile of the job record with the same id (the hub's job id is the node's job id, `rb_host/jobs.py:196`); a `responder_failed` event inherits from its `msg_id`; anything else is `default`.
- `queued_unverified` (§6.5), `capability_unverified` (§6.8; shared with the experiment-records design) and `profile_unknown` (§6.8, a cancel whose target job is not in the ledger) are optional booleans on job records. A cancel record copies `profile` from its target's submit record, so an absent `profile` on a cancel means `default` only when `profile_unknown` is absent.

### 8.2 Stored and fetched files

- `inbox/<node>/<msg_id>/` and `outbox/<node>/<msg_id>/` (contract §1.3) keep their paths, because message ids are unique per node. `provenance.json` and the outbox metadata gain `profile`.
- Fetched files: `fetched/<node>/<safe name>` for the default profile (unchanged); `fetched/<node>/<profile>/<safe name>` for named profiles, so two trees with the same file name do not overwrite each other (inventory #40).

### 8.3 Board cache and share page

- Source id `<node>:<source>` for the default profile (existing cache files stay valid); `<node>@<profile>:<source>` for named profiles. `@` cannot occur in a profile name (§6.2 grammar). Node names are checked against `^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$` today only by `rb share` (`rb_host/share.py:26`; `HostConfig.alias` accepts any key, `rb_host/config.py:45-49`), so H3 validates node names against that grammar when `host.json` is loaded, and validates every profile name, whether it comes from `hello`, from `host.json` or from a session's tool argument, against the §6.2 grammar before it is used in a path (`fetched/<node>/<profile>/`, §8.2), a cache id or a page link. With both checks the id is unambiguous. The existing `_within` check on the fetched path stays. Cache file name: the id with `:` replaced by `_` (`rb_host/board.py:42-43`), for example `node1@b_events.json`.
- `host.json`: `nodes.<n>.board` stays the default profile's board paths. Named profiles: `nodes.<n>.profiles.<p>.board` with the same keys (`state`, `events`, `kanban`), `nodes.<n>.profiles.<p>.label` (public label, still subject to the `share.labels` allowlist), and `nodes.<n>.profiles.<p>.stages` (regular expression for stage codes, replacing the fixed `^S[0-8]$` for that profile, `rb_host/share.py:31`). The hub stores no roots, queue paths, job commands or pattern text for a profile.
- `rb board refresh` iterates over the default profile and each named profile that has board paths, using the gate for named ones.

### 8.4 Sync file and hub page (contract §1.3)

- `sync/<node>.json` gains `profiles` (the `hello.profiles` list), `withheld_digest`, and `trees: {<profile>: {"tree_head", "tree_dirty"}}` for named profiles; `tree_head`/`tree_dirty` stay the default profile's values.
- Page: `/nodes` lists each node's profiles with availability and reason; `/threads`, `/thread/<id>` and `/jobs` show a profile column and accept `?profile=<name>`; the overview's pending approvals show the profile next to the `rb approve <id>` command. Profile names are HTML-escaped like every other field.

### 8.5 Approval text

`jobs.describe` (`rb_host/jobs.py:124-134`) adds one line after `node:` for every submit, and the profile to the cancel line, always. The value is the record's `profile`; `default` when the field is absent; for a cancel with `profile_unknown` (target not in the ledger, §8.1) it is `unknown (taken from the node's record)`. Because `cancel_job` copies the target's profile (§6.8) and `rb approve` sends a named profile with the cancel, the profile shown is the profile the node acts on:

```
SUBMIT job 3f…
  node: node1
  profile: b
  config: <file>
  …
CANCEL job 3f… on node node1, profile b (key …)
```

The value passes through `clean()` like every other ledger field (security item SEC-03 of GitHub issue 26: ledger text is stripped of control and bidirectional-format characters before an approver sees it, `rb_host/jobs.py:106-121`).

The 8765 `/rb/pending` page (`vault-export/dashboard/rb_pending.py:58-74`) builds its own table instead of calling `describe()`. It gains a `profile` column between `node` and `config`, and the cancel line names the profile, with the same values as `describe()` (`default` when absent, `unknown (taken from the node's record)` for `profile_unknown`) and the same `clean()` and HTML escaping; `tests/test_rb_pending.py::test_pending_page_shows_profile` covers all three values. The change is made to the repository copy in `vault-export/` and applied to the vault by the user (AGENTS.md, ask before editing vault files or restarting 8765).

## 9. Scope of this phase

Design only in this branch (contract §2). The migration below starts from the state after contract §1 (N2 and H2 built and installed). Each step leaves the system working with every older counterpart; "user" marks steps the user runs.

| Step | Change | Who | After this step |
|---|---|---|---|
| P0 | Documents: `docs/projects/TEMPLATE.md` (this branch), `docs/projects/trm.md` (contract §1.5); manuals say "research root". `node-install.sh --research-root` and `rb-node link` already come from contract §1.4 (note 2026-11-11: `docs/projects/TEMPLATE.md` and `docs/projects/trm.md` exist in `main`, and so do `--research-root` and `rb-node link`) | repository | no code or wire change |
| P1 | Node configuration only: loader accepts flat `project_root` as an alias (§6.4 rules); `profiles` object parsed and validated by `config check` and `rb-node doctor` but not served; `rb-node config profile …` | node code; user installs | wire unchanged; any hub works; an older node reinstalled over it ignores `profiles` |
| P2 | Node masking: union of all declared sources on every egress path (§7.3), `hello.withheld_digest` (top level), rollback-containment warning (`queue_status` name masking was built earlier, PR 53; P2 only widens it to the union) | node code; user installs | stricter only; any hub works |
| P3 | Node profiles on the wire: `protocol: 3`, `hello.profiles` (names checked against the union), `profile` arguments and echoes, `read_doc ref`, `git_status tree`, `msg_begin profile`, responder, `serve-local --profile` and `serve-profile`, `run-job --profile` (named profiles only), job-profile record, `queued_name`, mailbox hold while a named source fails, `rb-node doctor` list of profile link files | node code; user installs | old hubs never send `profile` and read `trm`: unchanged |
| P4 | Hub: connection-scoped `hello` gate at the four sites (§6.5); optional MCP `profile` arguments; `ref` for named profiles only; `cancel_job` copies the target's profile; node and profile name validation before paths and ids; ledger, fetched, provenance, approval text; hub-local refusal codes; the queue-file-name check of `jobs.approve` reads `queued_name` for a named profile (§6.6) | hub code | against N0/N2: default works, named refused locally with nothing sent; against N3: all profiles |
| P5 | Hub configuration: `nodes.<n>.profiles.<p>` in `host.json`, pattern file list, digest comparison in `rb doctor`, sync file and page fields, board ids | hub code | additive files and fields |
| P6 | First named profile: on the node console, `rb-node config profile add <name> …`, place its pattern file and merge its patterns into the flat source (§7.2 rule 6), `rb-node doctor`; on the hub, extend the hub pattern set, add `host.json` profile section, `rb doctor --node node1` | user | second project served |
| P7 | Documents: flat keys described as the default profile's legacy spelling (never removed); a one-line note in the 2026-10-27 design and the board and share designs pointing to `docs/projects/trm.md` for project facts; the 8765 `/rb/pending` column (§8.5) through `vault-export/`, applied by the user | repository; user for the vault copy | |

P3 and P4 are independent: P4 before P3 leaves named profiles refused; P3 before P4 leaves them unused. Rollback after P6: reinstalling N2 or N0 drops named profiles; the hub gate sees no `profiles` and refuses named calls; ledger records with `profile` stay; pending approvals for a named profile are refused at `rb approve` with nothing sent; masking falls back to the flat source, which P6 made the union. Two effects of older code meeting what N3 wrote: (a) job files of named profiles run `rb-node run-job --profile <name>`, which older `run-job` rejects (`rb_node/cli.py:124-128`, exit 2); such queued jobs fail without a `job_finished` event and their ledger records stay `queued`, so the user cancels or re-submits them after the rollback (default-profile job files carry no `--profile` and keep working). (b) `.mcp.json` files that `rb-node link --profile` wrote run `rb-node serve-profile <name>`, which older code refuses, so those sessions lose the bridge tools instead of being served the default tree (§6.7); the user removes them, using the list `rb-node doctor` printed before the rollback.

Tests per step (names are proposals): P1 `tests/test_config_profiles.py::test_flat_keys_are_default`, `::test_project_root_alias_and_conflict`, `::test_writer_keeps_trm_root`, `::test_profiles_default_name_rejected`, `::test_profile_cap_and_withheld_names_rejected`; P2 `tests/test_withheld.py::test_union_of_profile_sources`, and the existing `tests/test_remote.py::test_queue_and_gpu_status` for the `(withheld)` name (a profile-union case is added to it); P3 `tests/test_remote.py::test_hello_lists_profiles`, `::test_profile_echo_on_every_op`, `::test_read_doc_ref_uses_profile_kinds`, `tests/test_jobs.py::test_submit_uses_profile_queue_and_template`, `::test_cancel_uses_recorded_profile`, `::test_default_job_file_has_no_profile_option`, `tests/test_remote.py::test_hello_hides_withheld_profile_and_kind_names`, `::test_poll_held_while_named_source_fails`, `tests/test_spawn.py::test_responder_dir_from_message_profile`, `::test_responder_suspended_on_failed_source`, `tests/test_local.py::test_inbox_filtered_by_profile`, `tests/test_cli.py::test_link_named_profile_uses_serve_profile`; P4 `tests/test_host_tools.py::test_named_profile_refused_on_old_node_nothing_sent` (subprocess node with N2 behaviour), `::test_default_read_doc_sends_id_or_path`, `::test_echo_mismatch_discarded`, `::test_approve_gate_before_upload`, `::test_approve_accepts_queued_name_for_named_profile` (added 2026-11-11: a named profile's result with `queued_name` and no `queued` marks the record `queued`; a `queued_name` of another job's file still resets it to `pending_approval`), `::test_describe_shows_profile`, `::test_approve_sends_shown_profile`, `::test_cancel_copies_target_profile`, `::test_bad_profile_name_never_builds_a_path`, `::test_exact_tool_set` (unchanged).

## 10. Verification

| Goal / anti-goal | Check | Kind | Status |
|---|---|---|---|
| G1 | `tests/test_remote.py::test_profile_echo_on_every_op`, `::test_read_doc_ref_uses_profile_kinds`, `tests/test_jobs.py::test_submit_uses_profile_queue_and_template` | unit test | not run (design only) |
| G2 | `tests/test_host_tools.py::test_named_profile_refused_on_old_node_nothing_sent` (subprocess node that ignores `profile`, as N0/N2 do; assert no op after `hello` reached it), `::test_approve_gate_before_upload` | unit test | not run (design only) |
| G3 | `tests/test_withheld.py::test_union_of_profile_sources`, the existing assertion `len(FALLBACK_PATTERNS) == 5` at `tests/test_withheld.py:96`, `tests/test_remote.py::test_reply_for_a_masked_with_b_patterns` (also with b's source failed: the reply is held back, not sent with the incomplete union), `::test_poll_held_while_named_source_fails`, the existing `::test_queue_and_gpu_status` (a name that hits is `(withheld)`; extended with a case for a pattern of another profile), `::test_hello_hides_withheld_profile_and_kind_names` | unit test | not run (design only); `test_queue_and_gpu_status` exists in `main` |
| G4 | `tests/test_config_profiles.py::test_no_op_reads_or_writes_profiles` (every op in `Node.ops` run against a node.json with profiles; file unchanged; no path in any named-profile result; the one allowed path is `queued` in a default-profile `job_submit` result, kept for old hubs), review that no code reads configuration from the research tree | unit test, review | not run (design only) |
| G5 | the two compatibility tables as parametrized tests over N2-behaviour and N3 subprocess nodes and H2/H3 clients: `tests/test_compat_profiles.py` | unit test | not run (design only) |
| G5, live | `rb sync` and one `read_doc` from H3 against the installed N0 on node1 | live check | not run (needs node1 and the user's go-ahead) |
| G6 | `tests/test_host_tools.py::test_ledger_profile_absent_for_default`, `tests/test_board.py::test_named_profile_cache_id`, `tests/test_host_store.py::test_fetched_named_profile_dir` | unit test | not run (design only) |
| G7 | `tests/test_host_tools.py::test_describe_shows_profile` (default and named, submit and cancel), `::test_cancel_copies_target_profile` (a `cancel_job` without `profile` for a job submitted under profile b shows `profile b`; an explicit different profile is refused; a target not in the ledger shows `unknown`), `::test_approve_sends_shown_profile`; `tests/test_rb_pending.py::test_pending_page_shows_profile` | unit test | not run (design only) |
| G8 | `tests/test_project_facts.py::test_project_facts_only_at_listed_sites`: greps `rb_node/` and `rb_host/` for a fixed pattern set (`trm`, the `EXP`/`H` identifier expressions, the fallback pattern strings taken from `FALLBACK_PATTERNS` at run time and not repeated in the test, the old default layout paths) and asserts that every hit lies at one of the sites listed in G8 (file and symbol pinned in the test); `grep -ln trm docs/design docs/superpowers/specs` lists only documents that carry the pointer note | unit test, manual | not run (design only) |
| Anti-goal: silent answer from default tree | covered by G2 tests | unit test | not run (design only) |
| Anti-goal: session edits configuration | G4 review | review | not run (design only) |
| Anti-goal: silent fallback to the built-in tree | `tests/test_config_profiles.py::test_writer_keeps_trm_root`, `::test_project_root_alias_and_conflict` | unit test | not run (design only) |
| Anti-goal: approval without the project | G7 tests (both approval surfaces) | unit test | not run (design only) |

## 11. Decided by the user

- 2026-11-05: the hub is the Linux development server (`docs/manual/hub-setup.md` §12).
- The runtime environment is managed by uv.
- 2026-11-10: the user confirmed the six coordinator defaults of contract §3 (`docs/HANDOFF.md`, "Decided by the user on 2026-11-10"; `docs/issues/2026-11-10-triage.md` §5, first paragraph): (1) outgoing bodies are stored under `outbox/` after the withheld check, masked; (2) "the ten MCP tools stay with their names and arguments" (triage item 7: "the ten MCP tools stay"); (3) the hub page has no approval form, approval stays `rb approve` in a hub terminal; (4) unattended sync runs only through `rb service install`, run by the user; (5) the Windows instructions shrink to an appendix; (6) the `trm` names in config keys and on the wire are not renamed now. Whether (2) also refuses new optional arguments on the ten tools is an open decision of the user (question U2 of `docs/issues/2026-11-11-audit.md`); this document does not decide it.
- 2026-11-10, goals stated for this review: material gathered on the hub; session conversations visible on a page served by the hub; SSH transport with automatic update after the first link; experiment handling following autoresearch practice; the project not fixed to trm; flexible MCP synchronisation; scripts simplified so that the README suffices.

## 12. My calls (user to check)

Design choices in this document:

- A profile is a named section of `node.json`; the flat keys are the profile `default` and stay authoritative for it.
- Profiles live only in `node.json` on the node console; an in-tree descriptive file is data, never configuration.
- The writer keeps writing `trm_root`; `project_root` is accepted on input only; disagreement is a `fail` and the loader uses `trm_root`.
- The hub gate keys on the requested name being listed in `hello.profiles`, not on a protocol number, and runs on the same connection; the sync file never feeds it.
- The hub omits `profile` for the default profile instead of sending `"default"`.
- Union masking on every egress path; no per-profile masking; the five fallback patterns cannot be switched off.
- A named profile with a broken pattern source is unavailable and suspends the responder node-wide; the default profile keeps today's degrade-and-warn behaviour.
- `hello.withheld_digest` (SHA-256 of the sorted union), a top-level field so that `hello.state` keeps only booleans and counts (plus `python`), for comparing hub and node pattern sets.
- `queue_status` names masked; named profiles return `queued_name` instead of the absolute queue path.
- Optional `profile` argument on six MCP tools instead of addressing `node@profile` through the existing `node` argument. The alternative needs no signature change but mixes two things in one field and makes `poll(node)` ambiguous. This goes beyond contract §3 item 2 and is open question 7.
- `read_doc` gains `ref` so the node, not the hub, decides whether a reference to a named profile's tree is an identifier; default-profile reads keep `id`/`path` and `_DOC_ID` on every node, so default calls need no `hello`. A `ref` that matches a kind but finds no document is `not_found`, not retried as a path.
- `cancel_job` copies the target job's profile from the ledger and refuses a different explicit one; an unknown target is shown as `profile: unknown`.
- Named-profile MCP entries run `rb-node serve-profile <name>`, which older code refuses, instead of `serve-local --profile <name>`, which older code would silently serve as the default profile; default-profile job files carry no `--profile`.
- The wording of hard rule 8 in `AGENTS.md` is updated in the same change that introduces `serve-profile`; its meaning is unchanged (§6.7). (Corrected 2026-11-11: the dead-holder lock condition is already in the rule text.)
- Mailbox egress (`poll`, `get_file` kind `out`) is held back node-wide while a named profile's pattern source fails; document reads of other profiles continue (stated residual).
- Profile and kind names are checked against the union at connection start; a hit is hidden in `hello`.
- Experiment families of a named profile live in `profiles.<p>.families`; the family command replaces the profile command; the GPU-hour ceiling is the smallest of family, profile and node limits (§5).
- Job identifiers, idempotency keys, message identifiers, the approval verifier, the responder lock and the GPU pool stay node-wide.
- `submit_job` refuses an unknown profile early only when the sync file lists the node's profiles; otherwise it records `capability_unverified`, one flag name for both designs.
- Profiles appear in the MCP `nodes` result under `status.<node>.profiles`.
- Ledger `profile` written only for non-default profiles.
- Board id separator `@`; fetched files under `fetched/<node>/<profile>/`.
- `write_roots` stays node-wide because no bridge operation writes through it.
- A cap of 16 profiles per node (keeps `hello` small; §6.2).
- Name and size limits: profile and kind names `^[a-z][a-z0-9_-]{0,31}$`; identifiers at most 64 characters; `id_regex` at most 200 characters, anchored; kinds tried in declared order; profile and kind names must not match a withheld pattern; the `withheld-` prefix is reserved.
- `protocol: 3` as the number for the profile-aware node (the gate does not depend on it).
- Per-profile `responder` switch; responder suspended node-wide while a named profile's pattern source fails.
- `serve-local --profile` filters `inbox_list` and `inbox_read` to that profile; without `--profile` it serves the default profile only (today it shows every message, which is the same on a one-project node).
- Attribution of inbound items without a `profile` field from the hub's own ledger (`reply_to`, job id, `msg_id`), otherwise `default` (§8.1).
- Hub pattern files: `withheld_patterns_file` stays a single path; extra files go under a new key `withheld_patterns_extra`.
- Hub per-profile fields in `host.json`: `nodes.<n>.profiles.<p>.board`, `.label`, `.stages`; nothing else about a profile is stored on the hub.
- The node audit record gains `profile`.
- Mixed hubs (an old and a new hub) against one node are unsupported.
- Added 2026-11-11 after the audit of that day, to make the text agree with itself and with the built code (author's calls, to check): a named profile's `hello.profiles` entry carries its `families` (§6.5); the `runs` op reads the queue of the profile recorded for the job id (§6.6); `jobs.approve` reads `queued_name` for a named profile (§6.6).

Coordinator defaults of contract §3, in force for this branch and listed here because the user has not confirmed them (all six were confirmed by the user on 2026-11-10; see §11; the list is kept as written):

1. The hub stores outgoing message bodies under `outbox/` after the withheld check.
2. The ten MCP tools stay; flexibility comes from added result fields and refined `poll` (this design adds optional arguments as well, which go beyond this default and need the user's confirmation, open question 7).
3. The hub page has no approval form; approval stays `rb approve` in a hub terminal.
4. Unattended sync runs as systemd user units installed only when the user runs `rb service install`.
5. Windows instructions shrink to an appendix; Windows code paths stay untouched.
6. `trm` naming in configuration keys and on the wire is not renamed now; this design proposes aliases.

## 13. Decision log (while building)

| # | Ruling | Cost if wrong | Where recorded |
|---|---|---|---|
| — | nothing built yet | — | — |

## 14. Left to the builder

- Exact `hello.profiles` entry fields beyond `name`, `available`, `reason`, `kinds`, `queue`, `responder` and, for named profiles, `families` (§6.5).
- File name and format of the per-job profile record on the node (`state/job-profile/<job_id>` proposed).
- Argument names of `rb-node config profile …`; whether it takes JSON for `kinds`.
- Whether `rb approve` runs the gate in a first connection before asking for the passphrase (preferred, so the user is not asked for a passphrase that cannot be used) or after. An early check in a first connection is in addition to the gate on the approval connection, never instead of it (§6.5).
- Per-profile extra text types (for example `.jsonl`, unified-board design Open question 6); defined as a field only after that question is answered.
- Error message wording.

## 15. Open questions

1. Is a second project on the same node a near-term need, or is the goal only to stop naming trm in code? If only the latter, P0 and P1 are enough and P2–P6 wait. Default: build P0–P2 first, P3–P5 when a second project is named.
2. Should the default profile also fail closed when its flat pattern file cannot be loaded (refuse document reads, suspend the responder), as named profiles do? Default: no; `fail` in `rb-node doctor` only, as contract §1.4.
3. May the hub compare pattern sets by digest (§7.2 rule 5)? A digest lets someone who already holds a full candidate set confirm it, nothing more. Default: yes.
4. May the five fallback patterns stay on for every profile, including projects that have nothing to do with them? Default: yes (hard rule 3 as written).
5. Should a project be able to have its own approver (one verifier per profile)? Default: no, one verifier per node.
6. Before P3 is built, may the installed node be asked, after a go-ahead, for `rb-node git-status` and `rb-node config show`, so the compatibility tables are checked against the real N0 install record instead of commit history? Default: ask at P4. Note (2026-11-11): the installed node is no longer N0; it runs 0.2.0 (N2) from `main` (note under the table of code generations at the top). The question stays open for the user: whether to ask the node for `rb-node git-status` and `rb-node config show` before P3 now concerns N2 and the `install.json` record, and `docs/issues/2026-11-10-triage.md` §5 item 13 still lists it.
7. May six MCP tools (`send_message`, `read_doc`, `fetch_file`, `queue_status`, `submit_job`, `cancel_job`) gain an optional argument `profile` (§6.8)? Contract §3 item 2 says flexibility comes from added result fields and a refined `poll`; this is an added argument, with names and the tool count unchanged. The experiment-records design adds four optional arguments to `submit_job` (`family`, `purpose`, `ref`, `parent_run`; its §6.3 and open question 9). Both additions go beyond "added result fields", so they need the user's confirmation before they are built; the coordinator cannot confirm them. Proposed answer: yes, optional, absent = the default profile (and the legacy request path); nothing of it is built before the user confirms.
8. Before profiles exist, may a second bridge instance on the same node machine (§16.2, §16.3) run a responder of its own? Hard rule 8 allows one spawned server session at a time; two instances have two locks (`<mailbox_root>/state/responder.lock`, `rb_node/spawn.py:39-40`). Default: no; the second instance runs with its responder disabled as described in §16.2, and messages to it are answered by a live session.

## 16. Using the bridge for a new project today, before profiles exist

Three ways, from least to most separation. None needs a code change; all need user steps on the node console and the hub, which a session does not run. None has been tried.

### 16.1 Re-point the research root (one project at a time)

On the node console: `rb-node config set trm_root <new root>` (with contract §1.4, `queue_dir`, `write_roots` and `withheld_source` follow when they still hold their old defaults), then set `read_roots`, `queue_dir`, `job_template`, `experiments_dir`, `hypotheses_path` and `withheld_source` for the new tree; `rb-node config check`. On the hub: change `nodes.node1.board` paths if the board is used.

Limits:

- Only one project is served at a time; switching back repeats every step.
- `rb pending` must be empty before the switch. A job approved after it goes into the new queue with the new job command, and the approval text does not say which project.
- Document identifiers stay `EXP-<n>` and `H-<n>` (`rb_node/remote.py:28-29`; `rb_host/server.py:23`). A project with another identifier form can be read by path only.
- Keep the old project's patterns in the pattern file (make it the union). `poll` masks at egress with the current patterns, so undelivered outbox items of the old project would otherwise leave masked with the new project's patterns only.
- Hub ledger, inbox and board history mix both projects under one node name. Fetched files collide in `fetched/node1/<basename>` (`rb_host/server.py:164`).
- The responder's working directory follows the root (`rb_node/spawn.py:131`).

### 16.2 A second node entry backed by a second account on the same machine

A second Unix account on the node machine gets its own `~/.research-bridge/` (mailbox, `node.json`, approval verifier, audit) through the normal `scripts/node-install.sh`, with the new tree as research root. On the hub: a second node entry, for example `node1-b`, with its own SSH alias and keys (`rb setup --node node1-b …`, contract §1.2), and its `authorized_keys` lines in the second account.

What works: separation of mailbox, ledger node name, fetched files, board and approval passphrase. Jobs work only if the queue runner of the new tree runs under the second account: `run-job` reads `~/.research-bridge/node.json` of whichever account executes the job file (`rb_node/cli.py:132`, `rb_node/config.py:44-46`), so with the runner in the second account, job records, cancel markers and `job_finished` events land in the second mailbox. If the runner runs under the first account, the job file executes with the first account's configuration and the jobs problem of §16.3 appears.

Limits:

- Needs an administrator to create the account and to give it read access to the tree, write access to the queue's `jobs/` directory (the node writes the `.job` file as the second account, `rb_node/jobs.py:157-164`), and access to the GPUs. If the tree belongs to the first account, these permissions must be granted on the first account's files.
- Each account has its own responder lock (`<mailbox_root>/state/responder.lock`, `rb_node/spawn.py:39-40`), so two server sessions could run at once. That conflicts with hard rule 8 (one spawned server session at a time) unless the responder is disabled in the second instance. There is no `responder` switch yet (issue 41 design). What works with today's code: set `claude_bin` in the second instance to a path that does not exist (`rb-node config set claude_bin /nonexistent`). `msg_commit` still starts `rb-node respond`, but `_run_one` fails at once with a spawn error (`rb_node/spawn.py:122-137`): no server session starts, the message becomes `failed` (not `new`), and one `responder_failed` event per message reaches the hub. Messages to the second instance are then answered only by a live session linked there (`inbox_list` shows `failed` messages too). Two caveats: `rb-node config check` and `rb-node doctor` report the missing binary, and `scripts/node-install.sh --update` resets an invalid `claude_bin` (contract §1.4), so the setting must be restored after every update of that instance. Running two responders anyway is a user decision (open question 8), not an accepted limit.
- Each account masks with its own patterns only. Both pattern files, and the hub's file, should hold the union, because a responder in one account may be able to read the other tree if file permissions allow it.
- Document identifiers are still `EXP-<n>` and `H-<n>`; other forms by path only.
- The two queues share the GPUs without coordination.

### 16.3 A second node entry backed by a second configuration in the same account

Same account, a second directory (for example `~/.research-bridge-b/`) with its own `node.json`. `mailbox_root`, `audit_path` and `approval_path` must be set to that directory by hand, because `config init` writes defaults under `~/.research-bridge/` (`rb_node/config.py:10,33-37`). A second hub key with its own `authorized_keys` line whose forced command sets the configuration path, for example `command="RB_NODE_CONFIG=/home/<NODE_USER>/.research-bridge-b/node.json /home/<NODE_USER>/.local/bin/rb-node serve-remote"`. The node reads `RB_NODE_CONFIG` (`rb_node/config.py:44-46`), and `trigger` and the responder's MCP configuration pass it on (`rb_node/spawn.py:96,103-104`). Whether sshd (the SSH server program) runs this forced command with the variable set as written has not been tested. The built `rb-node doctor` (N2, setup-and-diagnosis design §6.3 check `ak_bridge`) requires the forced command to start with an absolute path to `rb-node serve-remote`, so it reports a line with an environment prefix as a failed `authorized_keys` check. For this variant that `fail` is expected: check the second line by hand (`restrict`, `from=`, the configuration path) instead of relying on the doctor, and do not remove the prefix or rerun `node-install.sh --apply-authorized-keys` to "fix" it, because without the prefix the second key would serve the first configuration.

Limits, in addition to those of 16.2 (including the responder: the second configuration has its own mailbox root and therefore its own lock, so its `claude_bin` must point to a path that does not exist, as described in 16.2, to keep hard rule 8):

- Jobs do not work correctly. The queued job file runs `rb-node run-job` without `RB_NODE_CONFIG` (`rb_node/jobs.py:150-156`), so `run-job` loads the first configuration (`rb_node/cli.py:132`): the job record, the git state and the `job_finished` event go to the first instance's mailbox and tree, and a cancel request written by the second instance (`rb_node/jobs.py:198-199`) is never seen by the running job. Use this variant for messages and document reads only, with `job_template` left empty.
- `rb-node` console commands act on the first configuration unless `RB_NODE_CONFIG` is set in the shell.
- `node-install.sh` does not know the second directory; every setting is manual.

For anything beyond reading documents and exchanging messages, 16.2 is the workable choice until profiles exist.

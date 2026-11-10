# <project name> — project sheet

<!--
Copy to docs/projects/<name>.md. One sheet per research project that a node serves.
This sheet describes the project; it is not configuration. The node reads its settings only from
node.json on the node console (AGENTS.md hard rule 4). The person who sets up the node enters the
values below with `rb-node config set KEY VALUE` on the node console, never by editing node.json
by hand: `config set` refuses a key the installed code does not know, while the loader drops an
unknown key without a message and keeps serving the built-in tree. Values marked "after profiles"
need the profile steps P1-P5 of docs/design/2026-11-10-project-profiles.md and cannot be set yet.

Placeholders only for server facts: node1, <NODE_HOST>, <NODE_USER>, <HUB_ADDR>. No withheld
content and no experiment results in this file (AGENTS.md hard rule 3). Name withheld series only
by the pattern file that holds them, never by their names.
Delete the comment blocks once filled.
-->

Abbreviations: JSON = JavaScript Object Notation; GPU = graphics processing unit.

Date: YYYY-MM-DD · Sheet owner: <person> · Node: `node1` · Profile name: `<profile>` (or `default` while the node serves one project)

## 1. Research root

| Item | Value |
|---|---|
| Research root (absolute path on the node). For the default profile it is written with `rb-node config set trm_root DIR`; the key on disk stays `trm_root`. `project_root` applies only inside a named profile, after profiles (step P3), through `rb-node config profile add` | `/home/<NODE_USER>/<path to research tree>` |
| Is it a git work tree? (git state is reported read-only) | yes / no |
| Who else writes in this tree (live sessions, runners, people) | <list> |

## 2. Readable directories

Every directory the bridge may read, relative to the research root. Everything else is unreadable through the bridge. Keep the list short; a directory listed here can be read by the hub session in full, after masking.

| Directory (relative) | What it holds | File types in it |
|---|---|---|
| `<dir>/` | <one line> | <e.g. .md, .csv, .pdf> |

File types the node can mask or check: `.md .txt .csv .json` are masked line by line; `.tex` and `.svg` are scanned and denied on a hit; `.pdf` is scanned when `pdftotext` is installed; `.png .jpg .jpeg` are checked by name only. Any other type is denied. List here any other text type the project needs read (it needs a node change first):

- <extension, or "none">

## 3. Document kinds

Documents that a session asks for by identifier instead of by path. One row per kind. Leave the table empty if the project has none; path reads still work.

| Kind | Identifier form (anchored regular expression) | Lookup rule | Where (relative to the research root) |
|---|---|---|---|
| `<kind>` | `^<PREFIX>-\d+$` | one file per identifier, names tried in order: `{id}.md`, `{id}_*.md`; exactly one match | `<dir>/` |
| `<kind>` | `^<PREFIX>-\d+$` | one heading section per identifier inside one file | `<dir>/<file>.md` |

Rules: identifier forms of different kinds must not overlap (the first kind that matches is used); each "where" must lie inside a readable directory of §2. Until profiles exist the node knows only two kinds, `EXP-<n>` (one file per identifier, directory set with `rb-node config set experiments_dir DIR`) and `H-<n>` (heading section, file set with `rb-node config set hypotheses_path FILE`); other identifier forms are "after profiles" and are read by path until then.

## 4. Withheld patterns

| Item | Value |
|---|---|
| Pattern file on the node (absolute path, JSON) | `/home/<NODE_USER>/.research-bridge/<file>.json` |
| Format | one of: a JSON list of strings; `{"patterns": [...]}`; `{"families": [{"patterns": [...]}]}` (keys named `exp_id_patterns` are ignored) |
| How the file is produced (tool, command, or by hand) | <description; no pattern text here> |
| Who updates it, and when | <person or tool; trigger> |
| Short inline patterns kept in node.json instead of a file (after profiles, named profiles only; until then put every pattern in the file) | <count only, or "none"> |
| Copy on the hub (the hub re-checks everything it stores with its own file, which must hold every pattern of every project the hub serves) | <path under the hub data root> |

The five fallback patterns of AGENTS.md hard rule 3 stay on for this project as well. They cannot be switched off.

## 5. Jobs

| Item | Value |
|---|---|
| Job entry command (JSON list of words; `{config}` is replaced by the stored config file path) | `["<program>", "<arg>", "--config", "{config}"]` |
| Config file format and extensions accepted | <e.g. .yaml, .yml, .json> |
| Queue directory (absolute path on the node) | `/home/<NODE_USER>/<path>/queue` |
| Queue kind | `file-queue`: a runner claims `NNNN_<job_id>.job` from `jobs/` and moves it through `processing/`, `done/`, `failed/` |
| Who runs the queue runner, and how it is started | <description> |
| Does the runner set `CUDA_VISIBLE_DEVICES` (the environment variable that selects the GPUs a process may use) itself? (the bridge's `run-job` wrapper sets it to the approved GPUs) | yes / no / unknown |
| Largest GPU-hour budget one job may ask for | <number; the node limit today is 168> |
| Result files a job writes (relative to the research root) and whether they lie in a readable directory | `<dir>/<pattern>` · readable: yes / no |

## 6. Responder

| Item | Value |
|---|---|
| Should a message for this project start the server-side Claude session automatically? ("no" needs the per-profile `responder` switch, after profiles) | yes / no |
| Working directory of that session (relative to the research root; default: the root; another directory is "after profiles") | `<dir>` or `.` |
| Is a live session in this tree linked to the bridge (`rb-node link`)? | yes / no |

## 7. Approval

| Item | Value |
|---|---|
| Who approves jobs for this project (types the approval passphrase in `rb approve` on the hub) | <person> |
| Is the approval passphrase shared with other projects on the same node? (today there is one verifier per node) | yes |

## 8. Hub display (optional)

| Item | Value |
|---|---|
| Label shown on hub pages | `<label>` |
| Board sources (paths relative to the research root, inside §2): state, events, kanban | <paths or "none"> |
| Stage codes used in event files | <regular expression or "none"> |

## 9. Checks after setup

Checks that work with the code in this branch:

- [ ] `rb-node config check` on the node console prints no `unknown key` line (other lines, such as an empty `job_template`, may be expected for this project).
- [ ] `rb-node doctor` on the node console reports no `fail` line.
- [ ] `rb doctor --node node1` on the hub reports no `fail` line.
- [ ] A read of one document of each kind in §3 returns text.
- [ ] Masking probe: create an untracked temporary text file inside a readable directory of §2, containing one line that matches one of the five fallback patterns of AGENTS.md hard rule 3; read it through the bridge and confirm that line comes back blank; delete the file afterwards (and check that `git status` in the tree no longer lists it).

Checks that apply after profiles (steps P3-P5 of the profile design):

- [ ] `rb-node doctor` reports no `fail` line for this profile.
- [ ] `rb doctor --node node1` lists this profile in the node's `hello` answer.
- [ ] `rb pending` on the hub shows the profile name in the approval text of a test submission (reject it afterwards).

# Task 10 report: manual harness channel

Status: DONE_WITH_CONCERNS

## RED
`tests/test_harness.py` first run: collection error `ImportError: cannot import name 'harness' from 'rb_host'` (1 error, 0 run).

## GREEN
Full suite: `151 passed` (28 new in tests/test_harness.py; 123 prior). One intermediate run printed names of the
real ~/.claude files because `test_unknown_node` lacked a `claude_home` patch (dry-run, names only, nothing sent,
nothing written). Fixed: the code now validates the node before reading any file, and the test patches claude_home.

## Files
- new: rb_node/harness.py, rb_host/harness.py, tests/test_harness.py
- changed: rb_node/cli.py (harness-receive routing; `harness-send` removed from SUBCOMMANDS), rb_node/config.py
  (`harness_root`, default ""), rb_host/cli.py (push/pull/diff subparsers), README.md (section + copy command),
  tests/test_host_tools.py (old "not implemented, exit 2" assertion replaced).

## Concern: allowlist source
The brief says deliver.ps1's allowlist is the source of truth. Its real path is D:/raw/harness-sync/deliver.ps1
(not under 60_Tools), and it has NO allowlist: it copies whatever `-Path` it is given. The only allowlist is
`HARNESS_FILES/HARNESS_DIRS/HARNESS_EXCLUDE_SUFFIX` in 60_Tools/sync/prepare_staging.py, which
push_harness_gdrive.py documents as the single-source whitelist. I used that.
Allowlist (names only): files `CLAUDE.md`, `settings.json`, `rtk-reference.md`; dirs `commands`, `agents`,
`hooks`, `workflows`; excluded suffixes `.pyc`, `.bak`; `__pycache__` skipped. Controller should confirm.

## portablize_harness: VENDORED
Vendored into rb_host/harness.py (comment names the source). Not importable at runtime: it lives in the vault,
which must not be a runtime dependency, and it reads ~/.claude at import. Kept: MAPPING, classify (AUTO only),
rewrite, md table insertion. Dropped: scan/backup/CLI. Applies to .md / .md.off only (code files untouched, as in
the original). The credential-key regex was vendored from prepare_staging.py into rb_node/harness.py (stdlib).

## Rulings relied on
1 routing (harness-send internal, empty/harness-push = push, else exit 1); 2 tar safety (validate all members
before writing: no absolute, `..`, backslash, drive, links, devices, non-allowlisted top level; extract to a
`.stamp.part` dir through PathPolicy, then rename); 3 vendored; 4 push + --dry-run (alias `rb-<node>-harness`,
overridable by `harness_alias`); 5 pull to data_root/harness-staging/<stamp>; 6 diff only, no apply
(`rb harness apply` is a SystemExit); 7 `harness_root` default empty -> `no_harness_root` on push and pull (node side).
Added by me: fail-closed credential-key check on every .json on both sides; symlinks skipped on collect.

## Self-review
- Path escape: node push and host pull share `extract_tar`; every member is validated first, writes go through
  PathPolicy; tested for `../`, nested `..`, absolute, backslash, symlink, hardlink, device, non-allowlisted.
- Rejected tar: tests assert nothing is created (staging dir does not even exist).
- Pull reads only the allowlist (projects/, .credentials.json not in tar; tested); symlinks skipped.
- No apply path exists. diff only reads.
- Logs: node audit records op, ok, code, file count only (tested: no names or content). Host prints file names to
  the user's own terminal only.
- Not tested against real sshd: the `SSH_ORIGINAL_COMMAND` value is simulated by env in the fake node.
- Pulled files are not de-portablized, so `diff` shows path differences for portablized markdown (informational).

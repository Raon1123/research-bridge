# Task 8 report: host client, ledger, store

Commit d2c6935 `feat(host): client, ledger, store`.

## RED
I wrote the implementation files first by mistake, then moved them aside and ran the new tests:
`ModuleNotFoundError: No module named 'rb_host.ledger'` (2 collection errors). Moved the files back, so RED
is a collection failure and not a per-test failure.

## GREEN
Focused: 13 passed. Full suite: 109 passed.

## Files
rb_host/config.py, client.py, ledger.py, store.py; tests/test_host_client.py, tests/test_ledger.py.

## Kill-mid-transfer test
`killer.py` (written to tmp_path) stands in for ssh. It runs `rb_node.remote.Node` in-process and calls
`os._exit(7)` right after writing the first `get_file` response. The 2 MiB+ png on the node therefore
has its first chunk delivered and the second never. `get_file` raises `TransportError`; the test asserts
`dest` does not exist and nothing except `*.part` is in the directory. A retry over a healthy
connection then succeeds.

## Rulings relied on
1-7 from the task message. Specifics:
- `NodeClient(alias, ssh_argv, env)`; env is merged over os.environ.
- Exit 255 plus `Permission denied (publickey` in stderr gives `AgentLockedError`; other EOF gives `TransportError`.
- `put_file(msg_id, path, body="", from_session=None)`: the optional body and from_session are an addition.
  It is idempotent on retry because the node returns the stored names on a repeated `msg_begin` and ignores
  `put_chunk` for already-committed files.
- Ledger: append dedupes by `(kind, id)`; update appends a full merged line; readers take the last line per id.
  Torn trailing JSON lines are skipped.
- `thread(msg_id)` matches records where id, reply_to or msg_id equals msg_id.

## Design decisions to review
- `store_incoming` fetches attachments with `client.get_file("out", "<msg_id>/<name>", ...)` into
  `quarantine/<node>/<id>/.stage/`, so nothing unchecked is ever in inbox/. After the check it is moved to
  inbox/ (ok) or quarantine/ (name hit, or `check_file` != ok). `.stage` is removed afterwards.
- If the node denies the fetch (`RemoteError` code `denied`), the entry is recorded as quarantined with
  reason `node_denied` and no file exists. A real `pp_ltf_*` name is refused by the node itself.
  The test for `pp_ltf_fig.png` uses a fake client that serves the file, so the host-side check is exercised.
- `provenance.json` lives in `inbox/<node>/<id>/` (the dir is always created). Quarantined entries omit
  the file name and keep only index, reason, sha256 and bytes, so the withheld name is not copied outside
  quarantine/. The test asserts `pp_ltf` and `H108N` do not appear in the provenance text.
- The returned body is masked via `mask_text`; the raw body is never returned or written.
- Tests use `job-` message ids so `msg_commit` does not trigger the responder spawn. `claude_bin` points to
  a nonexistent path anyway.

## Self-review
- Tests touch only tmp_path (node tree, data_root); no node1, no real D:/raw/research-bridge.
- The session-calendar withheld file is not read in tests (patterns file set to a nonexistent tmp path,
  so fallback patterns only). The default path is used only when the config is loaded without an override.
- `RemoteError` messages come from the node's generic codes; no document text is echoed by the host.
- Quarantine is a sibling of inbox, never inside it.
- Not done: `load_host_config` has no test of its own; the ledger has no file lock (single-writer assumed for phase 1).

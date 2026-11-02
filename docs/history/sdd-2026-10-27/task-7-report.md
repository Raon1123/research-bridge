# Task 7 report: serve-local and responder

## RED
`pytest tests/test_local.py tests/test_spawn.py` -> collection error:
`ModuleNotFoundError: No module named 'rb_node.local'` (1 error, interrupted).

## GREEN
Focused: 14 passed (after fixing a test-helper arg-name clash, `call(rid, name, **args)` -> `tool`).
Full: `95 passed`.

## Files
- new `rb_node/local.py` (LocalServer, serve_local; 5 tools only)
- replaced `rb_node/spawn.py` (PROMPT, RESPONDER_TIMEOUT, LOCK_STALE, trigger, respond, _acquire/_release)
- `rb_node/cli.py`: `serve-local`, `respond <msg_id>` subcommands
- new `tests/test_local.py`, `tests/test_spawn.py`
- `tests/test_remote.py`: autouse fixture stubbing `spawn.trigger` so msg_commit tests don't launch real `rb-node respond` processes (needed now that the stub is real).

## Lock approach (portable option 2)
`state/responder.lock` created with `os.open(O_CREAT|O_EXCL)`, pid written. If it exists and mtime age > 1800 s (`LOCK_STALE`) it is unlinked and retaken; else held. No fcntl. `trigger` checks only the lock's age (does not take it); `respond` takes it per message and releases between messages, then loops to the oldest remaining `new` message (sorted by received, id; `job-` ids skipped). If `respond` finds the lock held it returns 0 leaving status `new`.
Caveat: lock mtime is not refreshed during a run, and the wall timeout equals the stale threshold (1800), so a run that hits the full timeout could be seen as stale at the boundary; rulings fixed both numbers.

## Fake claude approach
`claude_bin` is a single path: tests write a `.cmd` wrapper on Windows (`@"python" "fake.py" %*`) and a `#!/bin/sh exec` wrapper on POSIX. Behaviour chosen by env `FAKE_MODE` (exit1 / sleep / noop / answer). "answer" mode imports `rb_node.local.LocalServer` (PYTHONPATH set to repo) and calls `reply` for messages in `responding`. Claude subprocess stdout/stderr go to DEVNULL (output unused) so killing the wrapper on timeout cannot hang on inherited pipes.

## Rulings relied on
1 (event body JSON with `event` key; `responder_failed` = {event, msg_id, reason}; post_event body = {"event": kind, "body": text}), 2 (MCP newline JSON-RPC, 5 tools), 3 (reply attachments: absolute paths must be inside `out/_work/<msg_id>/`; relative paths go through `PathPolicy.resolve_read`; else JSON-RPC error -32000), 4 (reply sets `answered`, only after attachments validated and post_out succeeded), 5 (trigger/Popen flags: start_new_session on POSIX, DETACHED_PROCESS on Windows), 6 (argv, cwd=trm_root, timeout, failed+event, loop), 7 (job- never triggers; kept in remote.py, unchanged).

## Self-review
- Only the 5 tools; unknown tool -> JSON-RPC error. No job tools.
- Audit records only op, msg_id, ok, code/reason; no bodies. `responder_failed` carries only the reason string ("exit code N", "timeout", "no reply", "spawn error: <Type>").
- reply cannot write outside allowed dirs: realpath + commonpath check on work dir; relative via PathPolicy; non-file rejected; copies are made by `post_out` only after validation. Read-root attachments to the outbox still pass through `get_file` masking when the host fetches them.
- `out/_work` has no message.json, so `undelivered()` ignores it, and `get_file kind=out` rejects `_work` (id regex).
- Responder prompt treats message content as peer data; allowedTools limited to `mcp__rb__*,Read,Grep,Glob`.
- Absolute read-root paths (e.g. `<mailbox>/out/...` or trm absolute) are not accepted for reply attachments: PathPolicy rejects absolute paths, so read-root files must be given relative to trm_root. Noted limitation.
- `inbox_list` omits bodies (id, status, received, attachment names).
- Detached spawn not tested for real (Popen monkeypatched, per ruling 5); serve-local/respond CLI paths not exercised by a subprocess test.

## Fix round 1
Concern 2 fixed: `LOCK_STALE` literal removed; `_lock_stale()` returns `RESPONDER_TIMEOUT + LOCK_MARGIN` (margin 300, so 2100 s by default) and is evaluated at call time, so monkeypatching RESPONDER_TIMEOUT keeps the invariant. `trigger` and `_acquire` use it. New test `test_lock_stale_threshold_tracks_responder_timeout` (timeout patched to 1 s: lock aged timeout+10 stays held; aged stale+10 is taken over). RED: AttributeError (`_lock_stale` missing), 1 failed / 7 passed. GREEN: full suite 96 passed. Existing stale-lock test now uses `_lock_stale()`.

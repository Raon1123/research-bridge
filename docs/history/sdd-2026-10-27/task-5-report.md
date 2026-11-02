# Task 5 report: serve-remote

Commit: 571ecaf `feat(node): serve-remote`

## RED
`pytest tests/test_remote.py` -> `ModuleNotFoundError: No module named 'rb_node.config'` (collection error, 1 error).

## GREEN
Full suite: `59 passed` (18 new in tests/test_remote.py). Intermediate run had 2 failures from my own test/impl choices (CRLF in fixture on Windows; `get_file out` wrongly ran `check_file` on a .bin), both fixed.

## Files
- new: rb_node/config.py, remote.py, cli.py, audit.py, spawn.py (stub), tests/test_remote.py
- changed: rb_node/__init__.py (`__version__ = "0.1.0"`)

## Design choices not fixed by the brief
- Request shape: `{"id", "op", "args"}`; responses via `protocol.ok/err`. poll returns `{"items": [...]}`, queue_status `{"entries": [{name, mtime, state}]}`.
- NodeConfig has two extra fields: `mailbox_root` (default ~/.research-bridge/mailbox) and `audit_path` (default ~/.research-bridge/audit.jsonl). All fields have defaults.
- msg_begin stores sanitized names and sizes/sha in message.json with status `uploading` (not in mailbox.STATUSES; set directly at creation). msg_commit sets `new` only from `uploading`, so re-commit/retry does not regress status or re-trigger. Retry of msg_begin with the same content returns the same names; different content -> `conflict`. put_chunk seq 0 truncates `.part`, seq n requires the part to be exactly n*CHUNK; a committed attachment makes put_chunk a no-op. Commit with a short `.part` returns `incomplete` and leaves the `.part` in place (Mailbox.commit_part deletes on checksum mismatch, which only happens when sizes match).
- I did not use Mailbox.open_part (not idempotent on retry: it would suffix `-2`); names come from Mailbox.sanitize at begin.
- Ruling 6 nuance: `check_file` returns `deny_content` for .md/.txt/.csv/.json hits, which would make masking unreachable. For those extensions (MASK_EXT) get_file and read_doc mask lines instead of denying (matches Global Constraints: "text docs have hit lines blanked"). deny_name always denies; other types (pdf, tex, images) must pass check_file or get `denied`.
- get_file `out`: ref is `<out_id>/<name>`; name hit denies, text masked, but no `check_file` (server-authored attachments of any type allowed).
- read_doc by path accepts MASK_EXT plus .tex; H-section extraction runs on raw text, then masks only the section, so `withheld_lines` counts the section only.
- Errors: ProtocolError code passthrough (`too_large`, `unknown_op`, `bad_args`, `bad_id`, `checksum`, ...); PolicyError -> `denied` with generic message "denied"; OSError -> `io_error`, other -> `internal`, both with exception class name only. No path or text is echoed on denial.
- Audit records id, op, ok, code, msg_id, name only; never args/body.
- spawn.trigger is called via the module (`spawn.trigger`) so tests can patch it; failure is audited, not raised.
- Rulings applied: 1 (RB_NODE_CONFIG, FileNotFoundError), 2 (job- ids no trigger), 3, 4, 5, 6, 7, 8, 9. Ruling 3 was ambiguous: I made `harness-receive` exit 2 "not implemented yet" for SSH_ORIGINAL_COMMAND in ("", "harness-send") and exit 1 for anything else; `serve-local`, `run-job`, `respond`, `harness-send` subcommands are stubs exiting 2.

## Self-review
- Review Focus 1: truncated upload leaves only `.part`; retry with same msg_id verified (test_truncated_upload_only_part_and_retry_safe). Host-side named errors belong to Task 8.
- Review Focus 4: poll twice identical, ack removes (test_poll_ack). Ledger dedupe is Task 8.
- Review Focus 5 is covered at serve level (read_doc/get_file mask `pp_ltf_x`).
- No overbuilding: job ops, spawn logic and harness are untouched. POSIX mode bits not asserted.
- Concern: Python 3.8 compatibility was kept by style only (no 3.8 interpreter run here); node runs 3.12.

## Fix round 1
- Finding: get_file kind=out skipped check_file, so non-text outbox files were delivered unscanned.
- RED: new test test_get_file_out_scanned_like_docs (.tex in mailbox/out with a withheld token) failed with KeyError 'error' (file was delivered).
- Fix: `_bytes_for` now always runs check_file for non-MASK_EXT files (scan parameter removed); md/txt/csv/json are still masked. The existing out-chunk test now uses a .png (name-only type) since .bin is unscannable and denied.
- GREEN: full suite 60 passed.
- Supersedes concern 3 in the handback (out files are now scanned like docs).

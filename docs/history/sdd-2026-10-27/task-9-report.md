# Task 9 report

Status: DONE

Venv: D:/raw/Codes/research-bridge-wt/.venv (Scripts/python), `pip install -e ".[host]" pytest`; `.venv/` added to .gitignore.

RED: `pytest tests/test_host_tools.py` -> `ImportError: cannot import name 'cli' from 'rb_host'` (collection error, 1 error).
GREEN: 14 passed in tests/test_host_tools.py; full suite 123 passed.

Files: rb_host/server.py, rb_host/cli.py, rb_host/jobs.py, tests/test_host_tools.py, README.md, .gitignore.

Tools exposed (exact): nodes, send_message, poll, thread, read_doc, fetch_file, queue_status, gpu_status, submit_job, cancel_job. Test asserts the set equality via mcp.list_tools().

Design notes
- Client factory is `rb_host.jobs.connect(cfg, node)`; server and approve call it via module attribute so tests monkeypatch it. Host config from RB_HOST_CONFIG or default path.
- submit_job/cancel_job: ledger record only (kind job, status pending_approval), deduped by (op, idempotency_key). Test monkeypatches connect to raise.
- submit records config sha256; approve refuses if the file changed since submit.
- approve (jobs.py): status approved -> put_file("job-<id>") -> job_submit/job_cancel -> queued / cancelled_requested; stored result; repeat approve returns the same record without a node call. Failure mid-way leaves status approved, re-approve retries (node idempotent).
- reject: status rejected, no node call. CLI: y/N via stdin, EOF = no, --yes explicit; harness -> "not implemented yet", exit 2.
- send_message: extra optional `msg_id` param for retry; ledger record (metadata only: no body, only body_chars) pending_send -> sent; TransportError returns {msg_id,status,error}.
- poll: store_incoming, ledger once (dedupe by id with direction in; already-seen items are only acked), ack. Ledger holds no body and no quarantined names.
- read_doc/fetch_file go only through node ops; errors returned as the node error code only. fetch_file additionally re-checks the downloaded file against laptop withheld patterns and deletes it on a hit.

Rulings relied on: 1-10 all (tool set, no SSH on submit/cancel, approve in jobs.py CLI-only, reject, send_message, poll, read_doc/fetch_file, rb pending + harness stubs, main runs stdio, README).

Self-review: no approve/reject tool exposed; no SSH in submit/cancel; no body/withheld content in ledger or returned errors; CLI never approves without y unless --yes.

Concerns: Bash heredocs failed in this shell, so files were written with the Write tool. `reply_to` is ledgered but not sent on the wire (node msg_begin has no such field). Tests not run on Python 3.8 (venv is 3.14; `Path.is_relative_to` used in a test).

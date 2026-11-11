# Task 6 report: budgeted jobs

Status: DONE_WITH_CONCERNS

## RED (tests/test_jobs.py before wiring ops into remote.py)
14 failed, 5 passed (job_submit/job_cancel -> unknown_op; invalid/no_job_template/checksum/cancel cases failed).
Caveat: rb_node/jobs.py and run_job.py were written before the test file, so the 5 run_job tests passed on first run; RED covers only the remote ops.
A first GREEN attempt failed 5 tests because this laptop has nvidia-smi with other indices; fixed by an autouse fixture that hides nvidia-smi, plus a dedicated test for the index check.

## GREEN
`rtk proxy python -m pytest -q` -> 80 passed in 5.60s (budget test ~1.9 s).

## Files
- rb_node/jobs.py (new): submit, cancel, idempotency store (state/idempotency.json, tmp+os.replace), config finalize helper
- rb_node/run_job.py (new): run_job with wall limit, SIGTERM/SIGKILL, cancel polling, state/jobs/<id>.json, job_finished event
- rb_node/remote.py: ops job_submit, job_cancel (gpu index set from gpu_status; empty => check skipped)
- rb_node/cli.py: `rb-node run-job --gpus .. --gpu-hours .. --job-id .. -- argv` wired (needed for queue files to work); not exercised by a test
- tests/test_jobs.py (new)

## Rulings relied on
1 (job- upload, no msg_commit; helper _finalize_config verifies sha, commits .part, moves to state/configs/<job_id>/<name>), 2 (no_job_template, checked after validation, writes nothing, stores no key), 3 (`#!/bin/bash` + `exec <shlex-quoted argv>`), 4 (limit and killpg/terminate), 5 (cancel file, poll_interval param), 6 (idempotency; only successes stored; key reused for a different op -> `conflict`), 7 (event body {"job_id","status"}), 8 (invalid).

## Self-review / concerns
- Event body has no "job_finished" marker (ruling 7 says job_id and status only; kind is only "event"). Host cannot tell job events by kind; it can by JSON shape. Flag for Task 8.
- job_cancel of an unknown id returns `not_found`; a job is "running" if a processing/ file exists or state/jobs/<id>.json says running. Cancelled pending jobs get a state record with status cancelled.
- Queue number = max existing NNNN across jobs/processing/done/failed + 1; no lock against a concurrent submitter (single serve-remote per SSH call; small race with another submitter).
- Audit records only id/op/msg_id/name; no config contents anywhere. POSIX killpg path untested on Windows.

## Fix round 1
- RED: updated event test failed (body lacked "event"); new CLI test failed with SyntaxError in rb_node/cli.py: my earlier edit had turned the `\n` escapes in the run-job stderr messages into real newlines, so the module did not parse (the `run-job` path was broken, and importing cli failed). This was a real bug the new test caught.
- Fix: run_job body is now {"event": "job_finished", "job_id", "status"}; cli.py string escapes repaired.
- Added test_cli_run_job (cli.main run-job, exit 0, job_finished event in undelivered).
- GREEN: `rtk proxy python -m pytest -q` -> 81 passed.

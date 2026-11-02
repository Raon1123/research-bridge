### Task 6: Jobs and budget wrapper

**Files:**
- Create: `rb_node/jobs.py`, `rb_node/run_job.py`, `tests/test_jobs.py`
- Modify: `rb_node/remote.py` (add ops)

**Interfaces:**
- Consumes: Task 0 queue format; Task 5 `NodeConfig.job_template`, `queue_dir`.
- Produces:
  - op `job_submit {job_id, idempotency_key, config_name, config_sha256, gpus: list[int], gpu_hours: float, note}` (config uploaded first with `put_chunk` under `msg_id = "job-" + job_id`) → writes a queue job in the Task-0 format whose command is `["rb-node","run-job","--gpus",",".join(gpus),"--gpu-hours",str(h),"--job-id",job_id,"--"] + job_template` with `{config}` replaced by the stored config path; returns `{"queued": path}`. Reused `idempotency_key` → returns the original result, writes nothing. Validation: `gpus` non-empty ints within `nvidia-smi` indices (skip check if unavailable), `0 < gpu_hours <= 168`, config ext ∈ `.yaml .yml .json`.
  - op `job_cancel {job_id, idempotency_key}` → removes a pending queue file or writes `state/cancel/<job_id>` for a running job (`run-job` polls it every 10 s).
  - `run_job(gpus: list[int], gpu_hours: float, job_id: str, argv: list[str], state_dir: Path) -> int`: env `CUDA_VISIBLE_DEVICES`, wall limit `gpu_hours * 3600 / len(gpus)` s, on limit SIGTERM then SIGKILL after 60 s, writes `state/jobs/<job_id>.json` with `status ∈ {done, failed, budget_exceeded, cancelled}`, exit code, start/end; posts a mailbox `event` kind `job_finished`.

- [ ] **Step 1:** Tests: same idempotency key twice → one queue file; `gpu_hours=0` → `invalid`; `run_job` with argv `[sys.executable, "-c", "import time; time.sleep(5)"]` and `gpu_hours=0.0005, gpus=[0]` (1.8 s) → `budget_exceeded`; child sees `CUDA_VISIBLE_DEVICES == "0,2"` for `gpus=[0,2]`; cancel file stops a running job → `cancelled`; `job_finished` event appears in `undelivered()`.
- [ ] **Step 2–4:** FAIL → implement → PASS. Commit `feat(node): budgeted jobs`.


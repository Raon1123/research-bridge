"""run-job: run a queued command under a GPU-hour wall budget (stdlib only)."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import List, Optional, Set

from . import gitinfo
from .mailbox import Mailbox, _mkdir, _write_json

KILL_GRACE = 60.0
CANCEL_POLL = 10.0


def _stop(proc: "subprocess.Popen", grace: float, posix: bool) -> None:
    """SIGTERM (whole process group on POSIX), then SIGKILL after `grace` seconds."""
    if posix:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
    else:
        proc.terminate()
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    if posix:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    else:
        proc.kill()
    proc.wait()


def run_job(gpus: List[int], gpu_hours: float, job_id: str, argv: List[str], state_dir: Path,
            poll_interval: float = CANCEL_POLL, kill_grace: float = KILL_GRACE,
            trm_root: Optional[Path] = None, allowed_gpus: Optional[Set[int]] = None,
            assigned_gpu: Optional[int] = None) -> int:
    """Run `argv` under the wall budget.

    assigned_gpu: the GPU the queue worker gave this job (its CUDA_VISIBLE_DEVICES). A one-GPU
    job runs there, not on the requested index, so it never lands on a GPU another worker is
    using. allowed_gpus: when given, nothing is launched on a GPU outside it.
    """
    state_dir = Path(state_dir)
    jobs = state_dir / "jobs"
    _mkdir(jobs)
    cancel_file = state_dir / "cancel" / job_id
    record = jobs / (job_id + ".json")
    limit = gpu_hours * 3600.0 / len(gpus)
    start = time.time()
    used = [assigned_gpu] if assigned_gpu is not None and len(gpus) == 1 else list(gpus)
    base = {"job_id": job_id, "gpus": list(gpus), "gpu_hours": gpu_hours,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    if used != list(gpus):
        base["gpus_used"] = used
    if trm_root is not None:
        # git at submit (pinned by job_submit) vs at start: a different head means the tree moved
        # while the job waited in the queue.
        start_git = gitinfo.repo_state(Path(trm_root))
        base["git_start"] = {k: start_git.get(k) for k in ("head", "branch", "dirty_files")}
        try:
            sub = json.loads((state_dir / "git" / (job_id + ".json")).read_text(encoding="utf-8"))
            base["git_submit"] = {k: sub.get(k) for k in ("head", "branch", "dirty_files")}
        except (OSError, ValueError):
            pass
    _write_json(record, dict(base, status="running"))
    env = dict(os.environ)
    env["CUDA_VISIBLE_DEVICES"] = ",".join(str(g) for g in used)
    posix = os.name == "posix"
    status = None
    reason = None  # type: Optional[str]
    proc = None
    if allowed_gpus is not None and not set(used) <= set(allowed_gpus):
        rc = 126
        status = "failed"
        reason = "gpu_not_allowed"
    else:
        try:
            proc = subprocess.Popen(argv, env=env, start_new_session=posix)
        except OSError:
            rc = 127
            status = "failed"
    if proc is not None:
        deadline = time.monotonic() + limit
        next_poll = time.monotonic() + poll_interval
        while True:
            try:
                rc = proc.wait(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.monotonic()
            if now >= next_poll:
                next_poll = now + poll_interval
                if cancel_file.exists():
                    status = "cancelled"
            if status is None and now >= deadline:
                status = "budget_exceeded"
            if status is not None:
                _stop(proc, kill_grace, posix)
                rc = proc.returncode
                break
        if status is None:
            status = "done" if rc == 0 else "failed"
    try:
        cancel_file.unlink()
    except OSError:
        pass
    final = dict(base, status=status, exit_code=rc, ended=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                 seconds=round(time.time() - start, 3))
    event = {"event": "job_finished", "job_id": job_id, "status": status}
    if reason is not None:
        final["reason"] = reason
        event["reason"] = reason
    if "gpus_used" in base:
        event["gpus_used"] = used
    _write_json(record, final)
    if "git_start" in base:
        event["git_head"] = base["git_start"].get("head")
    Mailbox(state_dir.parent).post_out("event", json.dumps(event), [], None)
    return rc

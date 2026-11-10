from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
from pathlib import Path

import pytest

from rb_node import approval
from rb_node.mailbox import Mailbox
from rb_node.run_job import run_job
from test_remote import b64, begin_req, call, cfg  # noqa: F401  (cfg is a fixture)


def _upload_config(cfg, job_id, payload=b"lr: 0.1\n", name="train.yaml"):
    resp = call(cfg, begin_req("job-" + job_id, payload, name),
                ("put_chunk", {"msg_id": "job-" + job_id, "name": name, "seq": 0,
                               "data_b64": b64(payload)}))
    assert all(r["ok"] for r in resp), resp
    return hashlib.sha256(payload).hexdigest()


RECORD, KEY = approval.make_record("test passphrase", iterations=1000, salt_hex="00" * 16)


def _submit_args(job_id, sha, **kw):
    a = {"job_id": job_id, "idempotency_key": "k-" + job_id, "config_name": "train.yaml",
         "config_sha256": sha, "gpus": [2], "gpu_hours": 1.5, "note": "n",
         "approval_key": KEY}
    a.update(kw)
    return a


def _cancel_args(job_id, key):
    return {"job_id": job_id, "idempotency_key": key, "approval_key": KEY}


def _jobs(cfg):
    return sorted((Path(cfg.queue_dir) / "jobs").glob("*.job"))


@pytest.fixture(autouse=True)
def fake_gpus(monkeypatch):
    """PM-12: submission needs a readable GPU list, so default to four fake GPUs."""
    import rb_node.remote as remote
    monkeypatch.setattr(remote.Node, "gpu_status",
                        lambda self, a: {"gpus": [{"index": i} for i in range(4)]})


@pytest.fixture
def no_nvidia_smi(monkeypatch):
    import rb_node.remote as remote
    monkeypatch.setattr(remote.Node, "gpu_status",
                        lambda self, a: {"gpus": [], "error": "nvidia-smi not found"})


@pytest.fixture
def tcfg(cfg):
    cfg.job_template = ["uv", "run", "pretrain.py", "config={config}"]
    cfg.allowed_gpus = [0, 1, 2]
    approval.write_record(Path(cfg.approval_path), RECORD)
    return cfg


def test_submit_writes_queue_job(tcfg):
    sha = _upload_config(tcfg, "j1")
    r = call(tcfg, ("job_submit", _submit_args("j1", sha)))[0]
    assert r["ok"], r
    files = _jobs(tcfg)
    assert len(files) == 1 and r["result"]["queued"] == str(files[0])
    assert files[0].name == "0001_j1.job"
    body = files[0].read_text(encoding="utf-8")
    assert "rb-node run-job --gpus 2 --gpu-hours 1.5 --job-id j1 -- uv run pretrain.py" in body
    stored = Path(tcfg.mailbox_root) / "state" / "configs" / "j1" / "train.yaml"
    assert stored.read_bytes() == b"lr: 0.1\n"
    assert "{config}" not in body
    audit = Path(tcfg.audit_path).read_text(encoding="utf-8")
    assert "lr: 0.1" not in audit


def test_same_idempotency_key_one_queue_file(tcfg):
    sha = _upload_config(tcfg, "j2")
    a = _submit_args("j2", sha)
    r1, r2 = call(tcfg, ("job_submit", a), ("job_submit", a))
    assert r1["ok"] and r2["ok"] and r1["result"] == r2["result"]
    assert len(_jobs(tcfg)) == 1
    r3 = call(tcfg, ("job_submit", a))[0]  # separate process lifetime: key persisted
    assert r3["result"] == r1["result"] and len(_jobs(tcfg)) == 1
    idem = json.loads((Path(tcfg.mailbox_root) / "state" / "idempotency.json").read_text("utf-8"))
    assert "k-j2" in idem


@pytest.mark.parametrize("kw", [
    {"gpu_hours": 0}, {"gpu_hours": -1}, {"gpu_hours": 169}, {"gpus": []}, {"gpus": ["0"]},
    {"gpus": "0"}, {"config_name": "train.sh"}])
def test_invalid_args(tcfg, kw):
    sha = _upload_config(tcfg, "j3")
    r = call(tcfg, ("job_submit", _submit_args("j3", sha, **kw)))[0]
    assert not r["ok"] and r["error"]["code"] == "invalid", r
    assert _jobs(tcfg) == []


def test_gpu_index_checked_when_nvidia_smi_reports(tcfg, monkeypatch):
    import rb_node.remote as remote
    monkeypatch.setattr(remote.Node, "gpu_status", lambda self, a: {"gpus": [{"index": 0}, {"index": 1}]})
    sha = _upload_config(tcfg, "j8")
    bad = call(tcfg, ("job_submit", _submit_args("j8", sha, gpus=[2])))[0]
    assert not bad["ok"] and bad["error"]["code"] == "invalid"
    good = call(tcfg, ("job_submit", _submit_args("j8", sha, gpus=[1])))[0]
    assert good["ok"]


def test_no_job_template(cfg):
    approval.write_record(Path(cfg.approval_path), RECORD)
    sha = _upload_config(cfg, "j4")
    r = call(cfg, ("job_submit", _submit_args("j4", sha)))[0]
    assert not r["ok"] and r["error"]["code"] == "no_job_template"
    assert _jobs(cfg) == []
    assert not (Path(cfg.mailbox_root) / "state" / "idempotency.json").exists()


def test_checksum_mismatch_writes_nothing(tcfg):
    _upload_config(tcfg, "j5")
    r = call(tcfg, ("job_submit", _submit_args("j5", "0" * 64)))[0]
    assert not r["ok"] and r["error"]["code"] == "checksum"
    assert _jobs(tcfg) == []


def test_cancel_pending_removes_queue_file(tcfg):
    sha = _upload_config(tcfg, "j6")
    call(tcfg, ("job_submit", _submit_args("j6", sha)))
    c = _cancel_args("j6", "c-j6")
    r = call(tcfg, ("job_cancel", c), ("job_cancel", c))
    assert r[0]["ok"] and r[1]["ok"] and r[0]["result"] == r[1]["result"]
    assert _jobs(tcfg) == []


def test_cancel_running_writes_cancel_file(tcfg):
    state = Path(tcfg.mailbox_root) / "state"
    (state / "jobs").mkdir(parents=True, exist_ok=True)
    (state / "jobs" / "j7.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    r = call(tcfg, ("job_cancel", _cancel_args("j7", "c-j7")))[0]
    assert r["ok"] and (state / "cancel" / "j7").is_file()


def test_cancel_unknown(tcfg):
    r = call(tcfg, ("job_cancel", _cancel_args("nope", "c-n")))[0]
    assert not r["ok"] and r["error"]["code"] == "not_found"


# -- approval (SEC-01) --------------------------------------------------------
def _nothing_written(cfg, job_id):
    state = Path(cfg.mailbox_root) / "state"
    return (_jobs(cfg) == [] and not (state / "idempotency.json").exists()
            and not (state / "configs" / job_id).exists())


@pytest.mark.parametrize("key", [None, "", "0" * 64, KEY.upper(), KEY[:-2], 5])
def test_submit_without_valid_approval_key_writes_nothing(tcfg, key):
    sha = _upload_config(tcfg, "s1")
    a = _submit_args("s1", sha)
    if key is None:
        del a["approval_key"]
    else:
        a["approval_key"] = key
    r = call(tcfg, ("job_submit", a))[0]
    assert not r["ok"] and r["error"]["code"] == "not_authorized", r
    assert _nothing_written(tcfg, "s1")
    assert KEY not in Path(tcfg.audit_path).read_text(encoding="utf-8")


def test_no_verifier_refuses_submit_and_cancel(cfg):
    cfg.job_template = ["echo", "{config}"]
    sha = _upload_config(cfg, "s2")
    r = call(cfg, ("job_submit", _submit_args("s2", sha)),
             ("job_cancel", _cancel_args("s2", "c-s2")), ("approve_params", {}))
    assert [x["error"]["code"] for x in r] == ["not_authorized", "not_authorized", "no_verifier"]
    assert _nothing_written(cfg, "s2")


def test_cancel_without_key_refused(tcfg):
    sha = _upload_config(tcfg, "s3")
    call(tcfg, ("job_submit", _submit_args("s3", sha)))
    r = call(tcfg, ("job_cancel", {"job_id": "s3", "idempotency_key": "c-s3"}))[0]
    assert r["error"]["code"] == "not_authorized" and len(_jobs(tcfg)) == 1


def test_approve_params_public_only(tcfg):
    r = call(tcfg, ("approve_params", {}))[0]
    assert r["result"] == {"salt": RECORD["salt"], "iterations": 1000}
    assert approval.derive("test passphrase", r["result"]["salt"], 1000) == KEY


def test_cli_approve_key_set_and_clear(tmp_path, monkeypatch, capsys):
    from rb_node import cli
    path = tmp_path / "approve.json"
    cfgfile = tmp_path / "node.json"
    cfgfile.write_text(json.dumps({"approval_path": str(path)}), encoding="utf-8")
    monkeypatch.setenv("RB_NODE_CONFIG", str(cfgfile))
    answers = iter(["short", "a long passphrase", "a different one!", "a long passphrase",
                    "a long passphrase"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    assert cli.main(["approve-key", "set"]) == 1 and not path.exists()  # too short
    assert cli.main(["approve-key", "set"]) == 1 and not path.exists()  # mismatch
    assert cli.main(["approve-key", "set"]) == 0
    text = path.read_text(encoding="utf-8")
    rec = json.loads(text)
    assert set(rec) == {"salt", "iterations", "verifier"} and "passphrase" not in text
    key = approval.derive("a long passphrase", rec["salt"], rec["iterations"])
    approval.check(path, tmp_path / "state", {"approval_key": key})
    assert cli.main(["approve-key", "bogus"]) == 2
    assert cli.main(["approve-key", "clear"]) == 0 and not path.exists()


def test_wrong_keys_start_a_wait_then_reset(tcfg):
    state = Path(tcfg.mailbox_root) / "state"
    path = Path(tcfg.approval_path)
    for _ in range(approval.FREE_FAILURES):
        with pytest.raises(approval.ProtocolError) as e:
            approval.check(path, state, {"approval_key": "0" * 64}, now=1000.0)
        assert e.value.code == "not_authorized"
    with pytest.raises(approval.ProtocolError) as e:  # right key, but inside the wait
        approval.check(path, state, {"approval_key": KEY}, now=1001.0)
    assert e.value.code == "approval_wait"
    approval.check(path, state, {"approval_key": KEY}, now=1000.0 + approval.BASE_WAIT + 1)
    assert not (state / "approve_fail.json").exists()


# -- run_job ----------------------------------------------------------------
def _state(tmp_path):
    Mailbox(tmp_path / "mb")
    return tmp_path / "mb" / "state"


def _record(state, job_id):
    return json.loads((state / "jobs" / (job_id + ".json")).read_text(encoding="utf-8"))


def test_run_job_budget_exceeded(tmp_path):
    state = _state(tmp_path)
    t0 = time.time()
    rc = run_job([0], 0.0005, "b1", [sys.executable, "-c", "import time; time.sleep(5)"],
                 state, kill_grace=5)
    assert time.time() - t0 < 4.5
    rec = _record(state, "b1")
    assert rec["status"] == "budget_exceeded" and rec["exit_code"] == rc
    assert rec["started"] and rec["ended"]


def test_run_job_done_and_failed(tmp_path):
    state = _state(tmp_path)
    assert run_job([0], 1, "d1", [sys.executable, "-c", "pass"], state) == 0
    assert _record(state, "d1")["status"] == "done"
    assert run_job([0], 1, "d2", [sys.executable, "-c", "raise SystemExit(3)"], state) == 3
    rec = _record(state, "d2")
    assert rec["status"] == "failed" and rec["exit_code"] == 3


def test_run_job_cuda_visible_devices(tmp_path):
    state = _state(tmp_path)
    out = tmp_path / "env.txt"
    code = "import os,sys; open(sys.argv[1],'w').write(os.environ['CUDA_VISIBLE_DEVICES'])"
    assert run_job([0, 2], 1, "e1", [sys.executable, "-c", code, str(out)], state) == 0
    assert out.read_text() == "0,2"


def test_run_job_cancel_file(tmp_path):
    state = _state(tmp_path)
    (state / "cancel").mkdir(exist_ok=True)

    def later():
        time.sleep(0.5)
        (state / "cancel" / "c1").write_text("cancel", encoding="utf-8")

    threading.Thread(target=later).start()
    run_job([0], 1, "c1", [sys.executable, "-c", "import time; time.sleep(20)"], state,
            poll_interval=0.1, kill_grace=5)
    assert _record(state, "c1")["status"] == "cancelled"
    assert not (state / "cancel" / "c1").exists()


def test_job_finished_event_in_undelivered(tmp_path):
    state = _state(tmp_path)
    run_job([0], 1, "ev1", [sys.executable, "-c", "pass"], state)
    items = Mailbox(tmp_path / "mb").undelivered()
    assert len(items) == 1 and items[0]["kind"] == "event"
    assert json.loads(items[0]["body"]) == {
        "event": "job_finished", "job_id": "ev1", "status": "done"}


def test_cli_run_job(tmp_path, monkeypatch):
    from rb_node import cli
    mb = tmp_path / "mb"
    cfgfile = tmp_path / "node.json"
    cfgfile.write_text(json.dumps({"mailbox_root": str(mb), "allowed_gpus": [0]}),
                       encoding="utf-8")
    monkeypatch.setenv("RB_NODE_CONFIG", str(cfgfile))
    monkeypatch.delenv("CUDA_VISIBLE_DEVICES", raising=False)
    rc = cli.main(["run-job", "--gpus", "0", "--gpu-hours", "1", "--job-id", "cli1", "--",
                   sys.executable, "-c", "pass"])
    assert rc == 0
    items = Mailbox(mb).undelivered()
    assert len(items) == 1
    assert json.loads(items[0]["body"])["event"] == "job_finished"


# --- PM-12: no GPU list -> refuse ------------------------------------------------
def test_submit_refused_when_gpu_list_unreadable(tcfg, no_nvidia_smi):
    sha = _upload_config(tcfg, "j12")
    r = call(tcfg, ("job_submit", _submit_args("j12", sha)))[0]
    assert not r["ok"] and r["error"]["code"] == "gpu_status_unavailable", r
    assert _jobs(tcfg) == []


# --- PM-12 ordering: the GPU refusal comes after approval and idempotency ---------
def test_wrong_key_with_gpu_list_unreadable_gets_approval_error(tcfg, no_nvidia_smi):
    sha = _upload_config(tcfg, "j13")
    r = call(tcfg, ("job_submit", _submit_args("j13", sha, approval_key="0" * 64)))[0]
    assert not r["ok"] and r["error"]["code"] != "gpu_status_unavailable", r
    assert _jobs(tcfg) == []


def test_replay_with_gpu_list_unreadable_returns_stored_result(tcfg, monkeypatch):
    import rb_node.remote as remote
    sha = _upload_config(tcfg, "j14")
    first = call(tcfg, ("job_submit", _submit_args("j14", sha)))[0]
    assert first["ok"]
    monkeypatch.setattr(remote.Node, "gpu_status", lambda self, a: {"gpus": [], "error": "x"})
    again = call(tcfg, ("job_submit", _submit_args("j14", sha)))[0]
    assert again["ok"] and again["result"] == first["result"]
    assert len(_jobs(tcfg)) == 1


def test_zero_gpus_read_successfully_is_no_gpus(tcfg, monkeypatch):
    import rb_node.remote as remote
    monkeypatch.setattr(remote.Node, "gpu_status", lambda self, a: {"gpus": []})
    sha = _upload_config(tcfg, "j15")
    r = call(tcfg, ("job_submit", _submit_args("j15", sha)))[0]
    assert not r["ok"] and r["error"]["code"] == "no_gpus", r
    assert _jobs(tcfg) == []


def test_template_dir_and_stem_placeholders(tcfg):
    tcfg.job_template = ["uv", "run", "pretrain.py", "--config-dir", "{config_dir}",
                         "--config-name", "{config_stem}"]
    sha = _upload_config(tcfg, "j9")
    assert call(tcfg, ("job_submit", _submit_args("j9", sha)))[0]["ok"]
    body = _jobs(tcfg)[0].read_text(encoding="utf-8")
    d = Path(tcfg.mailbox_root) / "state" / "configs" / "j9"
    assert "--config-dir %s --config-name train" % d in body and "{config" not in body


# --- allowed_gpus: the node owner's GPUs; the queue worker's GPU wins -------------
def test_submit_refused_without_allowed_gpus(tcfg):
    tcfg.allowed_gpus = []
    sha = _upload_config(tcfg, "g1")
    r = call(tcfg, ("job_submit", _submit_args("g1", sha)))[0]
    assert not r["ok"] and r["error"]["code"] == "no_allowed_gpus", r
    assert _jobs(tcfg) == []
    assert not (Path(tcfg.mailbox_root) / "state" / "idempotency.json").exists()


def test_submit_refuses_gpu_outside_allowed(tcfg):
    """GPU 3 exists (fake_gpus reports 0-3) but is not the node owner's."""
    sha = _upload_config(tcfg, "g2")
    r = call(tcfg, ("job_submit", _submit_args("g2", sha, gpus=[3])))[0]
    assert not r["ok"] and r["error"]["code"] == "invalid", r
    assert _jobs(tcfg) == []


def test_submit_refuses_multi_gpu(tcfg):
    sha = _upload_config(tcfg, "g3")
    r = call(tcfg, ("job_submit", _submit_args("g3", sha, gpus=[0, 2])))[0]
    assert not r["ok"] and r["error"]["code"] == "invalid", r
    assert "multi-GPU" in r["error"]["message"]
    assert _jobs(tcfg) == []


@pytest.mark.parametrize("bad", [[0, "1"], [True], [-1], "0", None])
def test_malformed_allowed_gpus_fails_closed(tcfg, bad):
    tcfg.allowed_gpus = bad
    sha = _upload_config(tcfg, "g4")
    r = call(tcfg, ("job_submit", _submit_args("g4", sha)))[0]
    assert not r["ok"] and r["error"]["code"] == "no_allowed_gpus", r


_ENV_CODE = "import os,sys; open(sys.argv[1],'w').write(os.environ['CUDA_VISIBLE_DEVICES'])"


def test_run_job_uses_the_workers_gpu(tmp_path):
    """Requested GPU 5, claimed by the gpu4 worker: the job runs on 4, not on 5."""
    state = _state(tmp_path)
    out = tmp_path / "env.txt"
    rc = run_job([5], 1, "w1", [sys.executable, "-c", _ENV_CODE, str(out)], state,
                 allowed_gpus={4, 5}, assigned_gpu=4)
    assert rc == 0 and out.read_text() == "4"
    rec = _record(state, "w1")
    assert rec["gpus"] == [5] and rec["gpus_used"] == [4] and rec["status"] == "done"
    body = json.loads(Mailbox(tmp_path / "mb").undelivered()[0]["body"])
    assert body["gpus_used"] == [4]


@pytest.mark.parametrize("gpus,assigned,allowed", [
    ([0], None, {4, 5}),      # console run on a GPU that is not the owner's
    ([5], 2, {4, 5}),         # worker started on a foreign GPU (FORCE_GPUS)
    ([4], None, set()),       # allowed_gpus cleared after the job was queued
])
def test_run_job_launches_nothing_outside_allowed(tmp_path, gpus, assigned, allowed):
    state = _state(tmp_path)
    out = tmp_path / "ran.txt"
    rc = run_job(gpus, 1, "w2", [sys.executable, "-c", _ENV_CODE, str(out)], state,
                 allowed_gpus=allowed, assigned_gpu=assigned)
    assert rc == 126 and not out.exists()
    rec = _record(state, "w2")
    assert rec["status"] == "failed" and rec["reason"] == "gpu_not_allowed"
    body = json.loads(Mailbox(tmp_path / "mb").undelivered()[0]["body"])
    assert body["status"] == "failed" and body["reason"] == "gpu_not_allowed"


def test_cli_run_job_reads_the_workers_gpu(tmp_path, monkeypatch):
    from rb_node import cli
    mb = tmp_path / "mb"
    cfgfile = tmp_path / "node.json"
    cfgfile.write_text(json.dumps({"mailbox_root": str(mb), "allowed_gpus": [4, 5]}),
                       encoding="utf-8")
    monkeypatch.setenv("RB_NODE_CONFIG", str(cfgfile))
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "4")
    out = tmp_path / "env.txt"
    rc = cli.main(["run-job", "--gpus", "5", "--gpu-hours", "1", "--job-id", "cli2", "--",
                   sys.executable, "-c", _ENV_CODE, str(out)])
    assert rc == 0 and out.read_text() == "4"


@pytest.mark.parametrize("name", ["train.yml", "train.json", "train.YAML"])
def test_by_name_template_takes_yaml_only(tcfg, name):
    """Checked on the node with Hydra: --config-name finds train.yaml, not train.yml or train.json."""
    tcfg.job_template = ["uv", "run", "pretrain.py", "--config-dir", "{config_dir}",
                         "--config-name", "{config_stem}"]
    sha = _upload_config(tcfg, "y1", name=name)
    r = call(tcfg, ("job_submit", _submit_args("y1", sha, config_name=name)))[0]
    assert not r["ok"] and r["error"]["code"] == "invalid", r
    assert _jobs(tcfg) == []
    tcfg.job_template = ["uv", "run", "pretrain.py", "config={config}"]  # by path: still accepted
    assert call(tcfg, ("job_submit", _submit_args("y1", sha, config_name=name)))[0]["ok"]

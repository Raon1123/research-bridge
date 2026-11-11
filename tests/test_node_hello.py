from __future__ import annotations

import io
import json
import sys

import pytest

import rb_node
from rb_node import approval, cli
from rb_node.protocol import encode
from rb_node.remote import Node
from test_remote import call, cfg  # noqa: F401  (cfg is a fixture)

STATE_KEYS = {"configured", "approval_verifier", "job_template_set", "allowed_gpus_set",
              "withheld_source_set",
              "withheld_loaded", "withheld_rejected", "harness_root_set", "claude_bin_found",
              "queue_dir_exists", "python"}


@pytest.fixture
def hcfg(cfg):  # noqa: F811
    from pathlib import Path
    rec, _key = approval.make_record("a passphrase long enough", iterations=1000)
    approval.write_record(Path(cfg.approval_path), rec)
    return cfg


def hello(cfg):
    return call(cfg, ("hello", {}))[0]["result"]


def test_hello_protocol2_fields(hcfg):
    r = hello(hcfg)
    assert r["protocol"] == 2
    assert set(r["state"]) == STATE_KEYS
    assert r["state"]["approval_verifier"] is True
    assert r["state"]["configured"] is True


def test_hello_keeps_protocol1_keys(hcfg):
    r = hello(hcfg)
    assert isinstance(r["node"], str) and r["node"]
    assert r["version"] == "0.2.0"
    assert isinstance(r["withheld_extra"], int)


def test_hello_state_has_no_paths(hcfg, tmp_path):
    st = hello(hcfg)["state"]
    for k, v in st.items():
        if k == "python":
            continue
        assert isinstance(v, (bool, int)), k
    assert "/" not in json.dumps(st) and str(tmp_path) not in json.dumps(st)


def test_hello_approval_unreadable_is_false(cfg):  # noqa: F811
    cfg.approval_path = "/proc/nonexistent/x/approve.json"
    assert hello(cfg)["state"]["approval_verifier"] is False


def test_hello_ops_sorted_and_complete(hcfg):
    r = hello(hcfg)
    assert r["ops"] == sorted(Node(hcfg).ops)
    assert len(r["ops"]) == 15 and "hello" in r["ops"] and "job_submit" in r["ops"]


def _run_unconfigured(monkeypatch, tmp_path, ops):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setenv("RB_NODE_CONFIG", str(tmp_path / "missing.json"))
    data = b"".join(encode({"id": str(i), "op": op, "args": {}}) for i, op in enumerate(ops))

    class Fake:
        buffer = None
    fin, fout = Fake(), Fake()
    fin.buffer = io.BytesIO(data)
    fout.buffer = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", fin)
    monkeypatch.setattr(sys, "stdout", fout)
    code = cli.main(["serve-remote"])
    return code, [json.loads(l) for l in fout.buffer.getvalue().decode().splitlines()]


def test_unconfigured_serve_remote_answers_hello_only(monkeypatch, tmp_path):
    code, out = _run_unconfigured(monkeypatch, tmp_path, ["hello", "poll"])
    assert code == 0
    assert out[0]["ok"] is True
    assert out[0]["result"]["state"] == {"configured": False}
    assert out[0]["result"]["ops"] == ["hello"]
    assert out[0]["result"]["protocol"] == 2
    assert out[1]["ok"] is False and out[1]["error"]["code"] == "not_configured"


def test_unconfigured_creates_no_directories(monkeypatch, tmp_path):
    _run_unconfigured(monkeypatch, tmp_path, ["hello", "poll"])
    assert list((tmp_path / "home").iterdir()) == []


def test_unconfigured_non_object_json(monkeypatch, tmp_path):
    (tmp_path / "bad.json").write_text("[1]", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("RB_NODE_CONFIG", str(tmp_path / "bad.json"))

    class Fake:
        pass
    fin, fout = Fake(), Fake()
    fin.buffer = io.BytesIO(encode({"id": "1", "op": "hello", "args": {}}))
    fout.buffer = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", fin)
    monkeypatch.setattr(sys, "stdout", fout)
    assert cli.main(["serve-remote"]) == 0
    assert json.loads(fout.buffer.getvalue().decode().splitlines()[0])["result"]["state"] == {
        "configured": False}


def test_version_is_0_2_0():
    assert rb_node.__version__ == "0.2.0" and rb_node.PROTOCOL == 2


def test_withheld_extra_counts_compiled_only(hcfg, tmp_path):
    src = tmp_path / "w.json"
    src.write_text(json.dumps({"patterns": ["good_[a-z]+", "bad(["]}), encoding="utf-8")
    hcfg.withheld_source = str(src)
    r = hello(hcfg)
    assert r["withheld_extra"] == 1
    assert r["state"]["withheld_loaded"] == 1
    assert r["state"]["withheld_rejected"] == 1
    assert r["state"]["withheld_source_set"] is True


def test_hello_job_template_set_needs_config_placeholder(hcfg):
    hcfg.job_template = ["python", "train.py"]
    assert hello(hcfg)["state"]["job_template_set"] is False
    hcfg.job_template = ["python", "train.py", "--config", "{config}"]
    assert hello(hcfg)["state"]["job_template_set"] is True
    hcfg.job_template = []
    assert hello(hcfg)["state"]["job_template_set"] is False
    hcfg.job_template = ["python", "train.py", "--config-name", "{config_stem}"]
    assert hello(hcfg)["state"]["job_template_set"] is True


def test_hello_allowed_gpus_set(hcfg):
    for value, want in (([], False), ([4, 5], True), (["4"], False), ([True], False), (None, False)):
        hcfg.allowed_gpus = value
        assert hello(hcfg)["state"]["allowed_gpus_set"] is want, value

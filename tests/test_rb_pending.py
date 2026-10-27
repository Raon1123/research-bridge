"""Tests for the 8765 dashboard approval endpoint module (lives in the vault dashboard dir)."""
import sys

sys.path.insert(0, "D:/raw/vault-primary/90_Claude/60_Tools/dashboard")
import rb_pending  # noqa: E402

from rb_host.ledger import Ledger  # noqa: E402


def _ledger(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append({"kind": "job", "id": "j1", "status": "pending_approval", "node": "node1",
                "config_name": "cfg.yaml", "gpus": [0, 1], "gpu_hours": 2.5, "note": "try lr"})
    return led


def test_render_has_fields_and_csrf(tmp_path):
    html = rb_pending.render_pending(_ledger(tmp_path))
    for s in ("node1", "cfg.yaml", "2.5", "try lr", "j1", "/rb/approve", "/rb/reject"):
        assert s in html
    assert 'name="csrf"' in html and rb_pending.CSRF_TOKEN in html


def test_non_localhost_is_403(monkeypatch):
    monkeypatch.setattr(rb_pending.jobs, "approve", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    st, _ = rb_pending.handle_post("<LAPTOP_WIFI_IP>", {"csrf": "t", "job_id": "j1"}, "t", "approve")
    assert st == 403


def test_bad_token_is_403(monkeypatch):
    monkeypatch.setattr(rb_pending.jobs, "approve", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    st, _ = rb_pending.handle_post("127.0.0.1", {"csrf": "bad", "job_id": "j1"}, "t", "approve")
    assert st == 403


def test_valid_calls_approve_and_reject(monkeypatch):
    calls = []
    monkeypatch.setattr(rb_pending.jobs, "approve", lambda led, cfg, jid: calls.append(("a", jid)) or {})
    monkeypatch.setattr(rb_pending.jobs, "reject", lambda led, jid: calls.append(("r", jid)) or {})
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (None, None))
    assert rb_pending.handle_post("127.0.0.1", {"csrf": "t", "job_id": "j1"}, "t", "approve")[0] == 200
    assert rb_pending.handle_post("127.0.0.1", {"csrf": "t", "job_id": "j2"}, "t", "reject")[0] == 200
    assert calls == [("a", "j1"), ("r", "j2")]


def test_bad_action_is_400(monkeypatch):
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (None, None))
    assert rb_pending.handle_post("127.0.0.1", {"csrf": "t", "job_id": "j1"}, "t", "delete")[0] == 400


def test_jobs_exception_is_500_generic(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internals")
    monkeypatch.setattr(rb_pending.jobs, "approve", boom)
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (None, None))
    st, body = rb_pending.handle_post("127.0.0.1", {"csrf": "t", "job_id": "j1"}, "t", "approve")
    assert st == 500 and "secret" not in body


def test_render_escapes(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append({"kind": "job", "id": "j2", "status": "pending_approval", "node": "n",
                "config_name": "<script>x</script>", "gpus": [0], "gpu_hours": 1, "note": "a&b"})
    html = rb_pending.render_pending(led)
    assert "<script>x" not in html and "&lt;script&gt;" in html and "a&amp;b" in html


def test_get_non_localhost_is_403(monkeypatch):
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (_ for _ in ()).throw(AssertionError))
    st, body = rb_pending.handle_get("<LAPTOP_WIFI_IP>")
    assert st == 403 and rb_pending.CSRF_TOKEN not in body


def test_get_localhost_renders(tmp_path, monkeypatch):
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (_ledger(tmp_path), None))
    st, body = rb_pending.handle_get("127.0.0.1")
    assert st == 200 and "cfg.yaml" in body

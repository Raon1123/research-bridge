"""Tests for the 8765 dashboard approval endpoint module. Imports the copy in this repo's
vault-export/dashboard/ (the vault copy is applied by the user, see vault-export/README.md)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vault-export" / "dashboard"))
import rb_pending  # noqa: E402

from rb_host.client import RemoteError  # noqa: E402

from rb_host.ledger import Ledger  # noqa: E402


HOST = "127.0.0.1:8765"


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


def test_foreign_host_is_403_for_get_and_post(tmp_path, monkeypatch):
    # PM-03: DNS rebinding arrives from 127.0.0.1 with the attacker's own Host
    monkeypatch.setattr(rb_pending.jobs, "approve", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (_ledger(tmp_path), None))
    form = {"csrf": "t", "job_id": "j1", "passphrase": "pw"}
    for bad in ("evil.example:8765", "evil.example", "127.0.0.1", "127.0.0.1:8766",
                "127.0.0.1:8765.evil.example", "", None):
        st, body = rb_pending.handle_get("127.0.0.1", bad)
        assert st == 403 and rb_pending.CSRF_TOKEN not in body
        assert rb_pending.handle_post("127.0.0.1", form, "t", "approve", bad)[0] == 403
    assert rb_pending.handle_get("127.0.0.1")[0] == 403  # no Host header: refused
    assert rb_pending.handle_get("127.0.0.1", "localhost:8765")[0] == 200


def test_foreign_origin_post_is_403(monkeypatch):
    calls = []
    monkeypatch.setattr(rb_pending.jobs, "approve", lambda *a: calls.append(a) or {})
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (None, None))
    form = {"csrf": "t", "job_id": "j1", "passphrase": "pw"}
    for bad in ("http://evil.example", "http://127.0.0.1:8766", "null", "https://127.0.0.1:8765", ""):
        assert rb_pending.handle_post("127.0.0.1", form, "t", "approve", HOST, bad)[0] == 403
    assert calls == []
    for ok in (None, "http://127.0.0.1:8765", "http://localhost:8765"):
        assert rb_pending.handle_post("127.0.0.1", form, "t", "approve", HOST, ok)[0] == 200
    assert rb_pending.handle_post("127.0.0.1", form, "t", "approve", "localhost:8765")[0] == 200


def test_page_shows_config_path_and_hash_pm17(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append({"kind": "job", "op": "submit", "id": "j3", "status": "pending_approval",
                "node": "n", "config_name": "c.yaml", "config_path": "D:/work/runs/c.yaml",
                "config_sha256": "0123456789abcdef" * 4, "gpus": [0], "gpu_hours": 1, "note": ""})
    html = rb_pending.render_pending(led)
    assert "config_path" in html and "D:/work/runs/c.yaml" in html and "0123456789ab" in html
    assert "0123456789abc" not in html  # only the first 12 characters


def test_page_strips_control_characters_sec03(tmp_path):
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append({"kind": "job", "op": "submit", "id": "j4", "status": "pending_approval",
                "node": "n", "config_name": "c.yaml\x1b[2J", "config_path": "p",
                "gpus": [0], "gpu_hours": 1, "note": "ok\x1b[31mred\u202e\x00 done"})
    html = rb_pending.render_pending(led)
    assert "\x1b" not in html and "\u202e" not in html and "\x00" not in html
    assert "red" in html and "done" in html


def test_non_localhost_is_403(monkeypatch):
    monkeypatch.setattr(rb_pending.jobs, "approve", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    st, _ = rb_pending.handle_post("<LAPTOP_WIFI_IP>", {"csrf": "t", "job_id": "j1"}, "t", "approve")
    assert st == 403


def test_bad_token_is_403(monkeypatch):
    monkeypatch.setattr(rb_pending.jobs, "approve", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    st, _ = rb_pending.handle_post("127.0.0.1", {"csrf": "bad", "job_id": "j1"}, "t", "approve", HOST)
    assert st == 403


def test_valid_calls_approve_and_reject(monkeypatch):
    calls = []
    monkeypatch.setattr(rb_pending.jobs, "approve",
                        lambda led, cfg, jid, pw: calls.append(("a", jid, pw)) or {})
    monkeypatch.setattr(rb_pending.jobs, "reject", lambda led, jid: calls.append(("r", jid)) or {})
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (None, None))
    form = {"csrf": "t", "job_id": "j1", "passphrase": "pw"}
    assert rb_pending.handle_post("127.0.0.1", form, "t", "approve", HOST)[0] == 200
    assert rb_pending.handle_post("127.0.0.1", {"csrf": "t", "job_id": "j2"}, "t", "reject", HOST)[0] == 200
    assert calls == [("a", "j1", "pw"), ("r", "j2")]


def test_approve_needs_passphrase_and_maps_refusal(monkeypatch):
    # SEC-01: the CSRF token alone (readable by a rebinding page, PM-03) cannot approve
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (None, None))
    monkeypatch.setattr(rb_pending.jobs, "approve", lambda *a: (_ for _ in ()).throw(AssertionError))
    assert rb_pending.handle_post("127.0.0.1", {"csrf": "t", "job_id": "j1"}, "t", "approve", HOST)[0] == 400

    def refused(*a):
        raise RemoteError("not_authorized", "approval key not accepted")
    monkeypatch.setattr(rb_pending.jobs, "approve", refused)
    form = {"csrf": "t", "job_id": "j1", "passphrase": "wrong-secret"}
    st, body = rb_pending.handle_post("127.0.0.1", form, "t", "approve", HOST)
    assert st == 403 and "wrong-secret" not in body


def test_render_has_password_field_only_on_approve(tmp_path):
    html = rb_pending.render_pending(_ledger(tmp_path))
    assert html.count('type="password"') == 1 and 'autocomplete="off"' in html


def test_bad_action_is_400(monkeypatch):
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (None, None))
    assert rb_pending.handle_post("127.0.0.1", {"csrf": "t", "job_id": "j1"}, "t", "delete", HOST)[0] == 400


def test_jobs_exception_is_500_generic(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internals")
    monkeypatch.setattr(rb_pending.jobs, "approve", boom)
    monkeypatch.setattr(rb_pending, "_ctx", lambda: (None, None))
    form = {"csrf": "t", "job_id": "j1", "passphrase": "pw"}
    st, body = rb_pending.handle_post("127.0.0.1", form, "t", "approve", HOST)
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
    st, body = rb_pending.handle_get("127.0.0.1", HOST)
    assert st == 200 and "cfg.yaml" in body

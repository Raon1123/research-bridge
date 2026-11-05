"""Tests for the 8765 /board page module. Imports the copy in this repo's vault-export/dashboard/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vault-export" / "dashboard"))
import rb_board  # noqa: E402

from rb_host.config import HostConfig  # noqa: E402
from rb_host.ledger import Ledger  # noqa: E402


def _cfg(tmp_path):
    Ledger(tmp_path / "ledger.jsonl").append(
        {"kind": "job", "op": "submit", "id": "j1", "node": "n1", "config_name": "<b>c.yaml",
         "gpu_hours": 1, "status": "pending_approval", "created": "t"})
    return HostConfig(nodes={"n1": {"alias": "x"}}, data_root=str(tmp_path),
                      board={"portfolio": str(tmp_path / "none.json"),
                             "priorities": str(tmp_path / "none.json")})


def test_get_non_localhost_is_403(monkeypatch):
    monkeypatch.setattr(rb_board, "_cfg", lambda: (_ for _ in ()).throw(AssertionError))
    st, body = rb_board.handle_get("<LAPTOP_WIFI_IP>")
    assert st == 403 and body == "forbidden"


def test_get_localhost_renders_waiting_first_and_escapes(tmp_path, monkeypatch):
    monkeypatch.setattr(rb_board, "_cfg", lambda: _cfg(tmp_path))
    st, body = rb_board.handle_get("127.0.0.1", "127.0.0.1:8765")
    assert st == 200
    assert body.index("Waiting on you (1)") < body.index("rb:ledger</h3>")
    assert "j1" in body and "<b>c.yaml" not in body and "&lt;b&gt;c.yaml" in body
    assert "never_fetched" in body and "n1:queue" in body and 'href="/rb/pending"' in body
    assert "<form" not in body  # no approval on the board


def test_page_load_opens_no_connection(tmp_path, monkeypatch):
    from rb_host import jobs
    monkeypatch.setattr(jobs, "connect", lambda *a: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(rb_board, "_cfg", lambda: _cfg(tmp_path))
    assert rb_board.handle_get("127.0.0.1", "127.0.0.1:8765")[0] == 200


def test_error_is_500_generic(monkeypatch):
    def boom(cfg):
        raise RuntimeError("secret internals")
    monkeypatch.setattr(rb_board.board, "load", boom)
    monkeypatch.setattr(rb_board, "_cfg", lambda: HostConfig())
    st, body = rb_board.handle_get("127.0.0.1", "127.0.0.1:8765")
    assert st == 500 and "secret" not in body


def test_foreign_host_is_403(monkeypatch):
    monkeypatch.setattr(rb_board, "_cfg", lambda: (_ for _ in ()).throw(AssertionError))
    for bad in ("evil.example:8765", "127.0.0.1", None):
        assert rb_board.handle_get("127.0.0.1", bad)[0] == 403

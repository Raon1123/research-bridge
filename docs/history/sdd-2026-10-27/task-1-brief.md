### Task 1: Scaffold and wire protocol

**Files:**
- Create: `pyproject.toml`, `rb_node/__init__.py`, `rb_node/protocol.py`, `rb_host/__init__.py`, `tests/test_protocol.py`, `.gitignore`

**Interfaces:**
- Produces (`rb_node/protocol.py`):
  - `CHUNK = 1 << 20`, `MAX_FILE = 50 * 1024 * 1024`
  - `class ProtocolError(Exception)` with `code: str`
  - `encode(obj: dict) -> bytes` (one JSON line, UTF-8, `\n`-terminated, `ensure_ascii=False`)
  - `read_message(stream: BinaryIO, max_line: int = 4 * CHUNK) -> dict | None` (None on EOF; `ProtocolError("line_too_long")` past `max_line`)
  - Request `{"id": str, "op": str, "args": dict}`; response `{"id": str, "ok": bool, "result": any}` or `{"id", "ok": false, "error": {"code": str, "message": str}}`
  - `ok(req_id, result) -> dict`, `err(req_id, code, message) -> dict`

- [ ] **Step 1:** Tests: round trip of a dict with Korean text; `read_message` returns None on empty stream; an over-long line raises `ProtocolError` with `code == "line_too_long"`; `err("1","denied","x")["error"]["code"] == "denied"`.
- [ ] **Step 2:** Run `rtk pytest tests/test_protocol.py -v` → FAIL (module missing).
- [ ] **Step 3:** Implement. `pyproject.toml`: packages `rb_node`, `rb_host`; scripts `rb-node = rb_node.cli:main`, `rb = rb_host.cli:main`, `rb-host-mcp = rb_host.server:main`; host extra deps `mcp>=1.27,<2`; pytest `pythonpath=["."]`.
- [ ] **Step 4:** Run tests → PASS.
- [ ] **Step 5:** `git init` already done; commit `feat: scaffold and wire protocol`.


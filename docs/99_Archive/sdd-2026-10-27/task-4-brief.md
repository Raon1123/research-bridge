### Task 4: Mailbox

**Files:**
- Create: `rb_node/mailbox.py`, `tests/test_mailbox.py`

**Interfaces:**
- Produces: `class Mailbox(root: Path)` (creates `in/`, `out/`, `state/` with 0700/0600 where the OS supports it):
  - `new_message(msg_id: str, meta: dict) -> Path` (`in/<msg_id>/message.json`; existing `msg_id` → returns existing dir, idempotent)
  - `open_part(msg_id: str, box: str, name: str) -> tuple[str, BinaryIO]` returns sanitized name; `commit_part(msg_id, box, name, sha256: str) -> None` verifies and renames `.part`; mismatch → `ProtocolError("checksum")` and deletes part
  - `sanitize(name: str, taken: set[str]) -> str` (basename after `\\`/`/`, strip control chars, keep Unicode, collision → `stem-2.ext`)
  - `post_out(kind: str, body: str, attachments: list[Path], reply_to: str | None) -> str` (new `out/<id>/`, kind ∈ `reply|event`)
  - `undelivered() -> list[dict]` (out items without `state/acked/<id>`), `ack(ids: list[str]) -> None`
  - `inbox(status: str | None = None) -> list[dict]`, `set_status(msg_id, status)` with status ∈ `new|responding|answered|failed`

- [ ] **Step 1:** Tests: `sanitize("C:\\x\\결과 그림.png", set())` == `"결과 그림.png"`; second same name → `"결과 그림-2.png"`; checksum mismatch leaves no file; `undelivered` returns item until `ack`; `new_message` twice same id → one dir.
- [ ] **Step 2–4:** FAIL → implement → PASS. Commit `feat(node): mailbox`.


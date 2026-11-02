# Task 4 report: Mailbox

Status: DONE_WITH_CONCERNS

## RED
`pytest tests/test_mailbox.py` -> collection error: `ModuleNotFoundError: No module named 'rb_node.mailbox'` (1 error in 0.99s).
(An earlier collection error was a test typo: unescaped backslashes in a string literal; fixed with raw strings.)

## GREEN
- `tests/test_mailbox.py`: 14 passed
- full suite: 41 passed

## Files
- rb_node/mailbox.py (new), tests/test_mailbox.py (new)

## Decisions beyond the brief
- ids (msg_id, out id, ack ids) validated by regex `[A-Za-z0-9][A-Za-z0-9._-]*`, no trailing dot; else ProtocolError("bad_id").
- message.json gets `id` and `status="new"` added on new_message; out items carry id, kind, body, reply_to, attachments [{name, original}].
- Original attachment names for inbox files kept in `in/<id>/attachment_names.json` (stored -> original); exposed via `Mailbox.attachment_names(msg_id, box)`.
- Out ids are `<time_ns:020d>-<8 hex>` so sorted order is chronological.
- commit_part also enforces MAX_FILE (deletes part, ProtocolError("too_large")); missing part -> ProtocolError("no_part"). Mismatch deletes part and raises "checksum"; test asserts attachments dir is empty.
- Two open_part calls with the same name get distinct names (taken set includes pending .part files).

## Self-review
No overbuilding found beyond the above; sanitize/ordering/idempotency follow controller rulings. Unused `Dict` import is used; no dead code known.

## Concern: POSIX modes
os.chmod cannot enforce 0700/0600 on Windows; code ignores OSError and the test asserts the 0700 root mode only under `os.name == "posix"`. Mode enforcement is unverified on this machine.

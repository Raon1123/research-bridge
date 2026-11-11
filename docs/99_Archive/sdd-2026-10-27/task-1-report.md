# Task 1 report
RED: `ImportError: cannot import name 'protocol' from 'rb_node'` (1 error during collection).
GREEN: 4 passed (round trip Korean, EOF None, line_too_long, ok/err shapes).
Files: pyproject.toml, .gitignore, rb_node/__init__.py, rb_node/protocol.py, rb_host/__init__.py, tests/test_protocol.py.
Self-review: stdlib only, py3.8-compatible (Optional, no match). Added extra code "bad_json" for malformed lines (not in brief; small, keeps read_message from leaking ValueError). `ok` name shadows nothing in module. Note: `rtk pytest` swallowed output on this machine ("No tests collected"); used `rtk proxy python -m pytest`.

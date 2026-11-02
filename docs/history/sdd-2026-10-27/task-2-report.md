# Task 2 report: path policy
RED: tests/test_paths.py -> ModuleNotFoundError: No module named 'rb_node.paths' (collection error).
GREEN: tests/test_paths.py 8 passed (symlink test ran, not skipped); full suite 12 passed.
Files: rb_node/paths.py, tests/test_paths.py.
Behavior per controller ruling: relative input joined to base, realpath'd, must lie under a realpath'd root of the matching list; absolute, NUL, `..`/symlink escapes, sibling-prefix (lab2 vs lab) raise PolicyError.
Self-review: minimal; no root-name-prefix shortcut (not needed). Absolute paths rejected even if inside a root (per ruling).

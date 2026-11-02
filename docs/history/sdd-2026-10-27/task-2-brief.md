### Task 2: Path policy

**Files:**
- Create: `rb_node/paths.py`, `tests/test_paths.py`

**Interfaces:**
- Produces: `class PolicyError(Exception)`; `class PathPolicy(read_roots: list[Path], write_roots: list[Path])` with `resolve_read(rel_or_abs: str) -> Path` and `resolve_write(rel: str) -> Path`. Relative paths resolve against the first root of the respective list unless they start with a root's name prefix (`lab/…` resolves against the trm repo root given as `base`); constructor signature `PathPolicy(base: Path, read_roots: list[str], write_roots: list[str])` where roots are relative to `base` or absolute.

- [ ] **Step 1:** Tests (use `tmp_path`): reading `lab/registry/HYPOTHESES.md` inside root succeeds; `lab/registry/../../etc/passwd` → `PolicyError`; absolute `/etc/passwd` → `PolicyError`; a symlink inside a root pointing outside → `PolicyError` (skip with `pytest.skip` if `os.symlink` raises `OSError` on Windows); write to a read-only root → `PolicyError`; NUL byte in path → `PolicyError`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement with `os.path.realpath` then `commonpath` containment against realpath'd roots.
- [ ] **Step 4:** Run → PASS. Commit `feat(node): path policy`.


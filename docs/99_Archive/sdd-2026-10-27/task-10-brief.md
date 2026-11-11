### Task 10: Harness sync channel (manual)

**Files:**
- Create: `rb_node/harness.py`, `rb_host/harness.py`, `tests/test_harness.py`
- Read first: `D:/raw/vault-primary/90_Claude/60_Tools/sync/portablize_harness.py`, `D:/raw/vault-primary/90_Claude/60_Tools/harness-sync/deliver.ps1` (allowlist source)

**Interfaces:**
- Produces:
  - `rb harness push --node node1 [--dry-run]`: builds a tar of the allowlisted harness files (same allowlist as `deliver.ps1`, paths portablized by `portablize_harness.py` logic imported or vendored), sends through alias `rb-node1-harness` to `rb-node harness-receive`, which unpacks into `~/.research-bridge/harness-staging/<UTC stamp>/` only (tar members checked with `PathPolicy` — no absolute, no `..`, no links).
  - `rb harness pull --node node1`: `rb-node harness-send` tars the server's allowlisted `~/.claude` subset into the laptop `D:/raw/research-bridge/harness-staging/<stamp>/`.
  - `rb harness diff <stamp>` prints a unified diff against the live harness; applying stays manual (README documents the copy command). No apply command.

- [ ] **Step 1:** Tests: tar with member `../evil` or a symlink → rejected, nothing written; push to local fake node lands under `harness-staging/<stamp>/`; `--dry-run` lists files and sends nothing.
- [ ] **Step 2–4:** FAIL → implement → PASS. Commit `feat: manual harness channel`.


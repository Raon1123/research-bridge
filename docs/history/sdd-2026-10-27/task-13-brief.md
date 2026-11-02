### Task 13: Provisioning and live run on node1 (user-approved steps)

**Files:**
- Create: `docs/provisioning.md`, `deploy/node.json.example`, `deploy/authorized_keys.example`

**Interfaces:**
- Consumes: everything above; Task 0 facts.

- [ ] **Step 1:** Write `docs/provisioning.md` with the exact commands below, then ask the user to run or approve each.
- [ ] **Step 2 (user):** `ssh-keygen -t ed25519 -f C:/keys/research-bridge/node1_ed25519 -C research-bridge-laptop` (with passphrase) and `…/node1_harness_ed25519 -C research-bridge-harness`; `ssh-add` both into the Windows ssh-agent service.
- [ ] **Step 3 (user):** `~/.ssh/config` entries `rb-node1` and `rb-node1-harness`: `HostName <NODE_HOST>`, `Port <NODE_PORT>`, `User <NODE_USER>`, `IdentityFile` the new key, `IdentitiesOnly yes`, `StrictHostKeyChecking yes`.
- [ ] **Step 4 (user-approved scp via existing `node1` alias):** copy `rb_node/` to `~/.local/share/research-bridge/rb_node/`, install `~/.local/bin/rb-node` wrapper (`exec python3 -m rb_node.cli "$@"` with `PYTHONPATH`), write `~/.research-bridge/node.json` from the example with Task 0 values, `chmod 700 ~/.research-bridge`.
- [ ] **Step 5 (user):** append two lines to `~/.ssh/authorized_keys`:
  `restrict,from="<laptop subnet from Task 0>",command="/home/<NODE_USER>/.local/bin/rb-node serve-remote" ssh-ed25519 … research-bridge-laptop`
  `restrict,from="<same>",command="/home/<NODE_USER>/.local/bin/rb-node harness-receive" ssh-ed25519 … research-bridge-harness` (pull uses `SSH_ORIGINAL_COMMAND == "harness-send"` checked inside `harness-receive`'s entry; any other value → exit 1).
- [ ] **Step 6:** Security checks, each must hold: `ssh rb-node1` gives no shell (output is protocol `hello` only after sending a request); `ssh rb-node1 cat /etc/passwd` returns nothing from cat; `ssh -o IdentityFile=C:/keys/<SHARED_KEY> -o IdentitiesOnly=yes rb-node1` still reaches a normal shell (that key is unchanged) — record that the new keys, not the old, are restricted; `read_doc` of `../../.ssh/authorized_keys` → `denied`.
- [ ] **Step 7:** Register `rb-host-mcp` in `~/.claude.json` user scope; in a new laptop session: `send_message("node1", "EXP-015 그림 해석을 요약해 달라", [<a small pdf>])`, wait, `poll` → reply with attachment stored under `D:/raw/research-bridge/inbox/node1/<msg_id>/` with `provenance.json`; `read_doc("node1","H-001")`; `submit_job` a tiny config with `gpu_hours=0.01` → `rb approve` → `job_finished` event with `budget_exceeded` or `done`.
- [ ] **Step 8:** Write `docs/provisioning.md` results section (what passed); commit `docs: provisioning and live verification`. Write the vault daily log `90_Claude/90_Daily/2026-10-27.md` entry.

# Provisioning research-bridge on node1

Node: node1, <NODE_HOST> port <NODE_PORT>, user <NODE_USER>, python3 3.12.3. Written by the controller; the controller runs nothing on node1 until the user confirms each step. Facts: `docs/server-facts.md`.

## Decisions the user must make first

1. **Laptop subnet for `from=`.** Which interface reaches node1: Wi-Fi <LAPTOP_WIFI_SUBNET>, or Ethernet <LAPTOP_ETH_SUBNET> or <LAPTOP_ETH_SUBNET>? Check with `route print` or a test `ssh node1`. This replaces `<LAPTOP_SUBNET>` in `deploy/authorized_keys.example`.
2. **Does the shared key `<SHARED_KEY>` stay in node1's `authorized_keys`?** Plan Decision 2: yes, unless the user removes it. Step 6 relies on it as the unrestricted login.
3. **`job_template` value for node.json.** The example ships `[]` (argv list with a `{config}` placeholder). No job can run until the user sets it. The controller does not invent it.
4. **Harness allowlist.** Is it the one in `60_Tools/sync/prepare_staging.py` (`HARNESS_FILES`, `HARNESS_DIRS`)? The plan's `deliver.ps1` path does not exist. `harness_root` is empty in the example; harness push/pull is refused (`no_harness_root`) until it is set.

## A. User runs

### A1. Keys (plan Step 2)

```
ssh-keygen -t ed25519 -f C:/keys/research-bridge/node1_ed25519 -C research-bridge-laptop
ssh-keygen -t ed25519 -f C:/keys/research-bridge/node1_harness_ed25519 -C research-bridge-harness
ssh-add C:/keys/research-bridge/node1_ed25519
ssh-add C:/keys/research-bridge/node1_harness_ed25519
```

Use a passphrase on both. The Windows `ssh-agent` service must be running. Public keys (`*.pub`) are the `<PUBKEY>` values; never share the private files.

### A2. `~/.ssh/config` (plan Step 3)

```
Host rb-node1
    HostName <NODE_HOST>
    Port <NODE_PORT>
    User <NODE_USER>
    IdentityFile C:/keys/research-bridge/node1_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes

Host rb-node1-harness
    HostName <NODE_HOST>
    Port <NODE_PORT>
    User <NODE_USER>
    IdentityFile C:/keys/research-bridge/node1_harness_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes
```

`IdentitiesOnly yes` stops the agent offering other keys. `StrictHostKeyChecking yes` refuses an unknown or changed host key, so node1 must already be in `known_hosts` (the existing `node1` alias does this).

### A3. Authorized keys (plan Step 5)

On node1, append the two lines of `deploy/authorized_keys.example` to `~/.ssh/authorized_keys`, with `<LAPTOP_SUBNET>` set per decision 1 and `<PUBKEY>` set to the contents of the matching `.pub` file (the base64 field only). The harness line's entry point accepts only `harness-push` or `harness-send` as `SSH_ORIGINAL_COMMAND`; any other value exits 1.

## B. Controller runs after the user confirms

### B1. Install (plan Step 4, via the existing `node1` alias)

Each command needs the user's go-ahead.

```
ssh node1 "mkdir -p ~/.local/share/research-bridge ~/.local/bin ~/.research-bridge"
scp -r rb_node node1:~/.local/share/research-bridge/
```

Wrapper `~/.local/bin/rb-node` (mode 755):

```
#!/bin/sh
PYTHONPATH="$HOME/.local/share/research-bridge" exec python3 -m rb_node.cli "$@"
```

Then write `~/.research-bridge/node.json` from `deploy/node.json.example` with decisions 3 and 4 applied, and run `chmod 700 ~/.research-bridge`.

### B2. Security checks (plan Step 6)

After A3 is confirmed. Each must hold.

| Command | Expected |
|---|---|
| `ssh rb-node1` (send nothing) | No shell prompt. Protocol output only; a `hello` appears only after a request is sent. |
| `ssh rb-node1 cat /etc/passwd` | Nothing from `cat`; no passwd contents. |
| `ssh -o IdentityFile=C:/keys/<SHARED_KEY> -o IdentitiesOnly=yes rb-node1` | Normal interactive shell (the old key is unchanged). Record that the new keys, not the old one, are restricted. |
| `read_doc("node1", "../../.ssh/authorized_keys")` | `denied` |

### B3. MCP registration and live run (plan Step 7)

User applies this to `~/.claude.json` at user scope (entry point is `rb_host.server`; adjust the interpreter path to the installed venv):

```json
{
  "mcpServers": {
    "rb-host-mcp": {
      "type": "stdio",
      "command": "D:/raw/Codes/research-bridge/.venv/Scripts/python.exe",
      "args": ["-m", "rb_host.server"]
    }
  }
}
```

In a new laptop session:

1. `send_message("node1", "EXP-015 그림 해석을 요약해 달라", [<a small pdf>])`, wait, then `poll`. Expect a reply whose attachment is stored under `D:/raw/research-bridge/inbox/node1/<msg_id>/` with `provenance.json`.
2. `read_doc("node1", "H-001")` returns the document.
3. `submit_job` with a tiny config, `gpu_hours=0.01`, then `rb approve`. Expect a `job_finished` event with `budget_exceeded` or `done`. Requires decision 3.

## Results

(Filled in after the live run, plan Step 8.)

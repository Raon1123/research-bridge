> Came from: Appendix A of `docs/manual/node-setup.md`; moved here on 2026-11-11.
> Not maintained (not kept in step with the code since 2026-11-05). The current text is `docs/manual/node-setup.md`.

## Appendix A. Windows hub notes (not maintained since 2026-11-05)

Last checked on 2026-11-05 with the laptop as hub; not kept in step with the code.

- Copy the code with LF line endings. On a Windows hub, check out with `core.autocrlf=input` or convert first; CRLF breaks the wrapper script. The installer today runs from a checkout on the node, so this matters only if the checkout is made on Windows and copied.
- The hub-side checks of §7.1 name the laptop paths in the old manual: replies were stored under `D:/raw/research-bridge/inbox/node1/<msg_id>/`.
- `from=` in `authorized_keys` was the laptop's subnet (`research-bridge-laptop` in the old comment). The installer now writes the comment `research-bridge-hub` and the hub's address.
- The by-hand install of the first node was: `ssh node1 "mkdir -p ~/.local/share/research-bridge ~/.local/bin ~/.research-bridge && chmod 700 ~/.research-bridge"` then `scp -r rb_node node1:~/.local/share/research-bridge/` (with `node1` the ordinary login alias, not the restricted `rb-node1`) and the three-line wrapper of §3 with `python3` instead of an absolute path. `scripts/node-install.sh` replaces it.

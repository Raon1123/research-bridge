# 설정 매뉴얼

이 문서는 영어 원문 [README.md](README.md)의 번역이며, 두 문서가 다르면 영어 원문을 기준으로 한다.

research-bridge에는 두 역할이 참여하며, 역할마다 매뉴얼이 따로 있다.

| 역할 | 실행하는 것 | 현재 | 매뉴얼 |
|---|---|---|---|
| **Hub** | `rb_host`: Claude 세션용 MCP 서버(`rb-host-mcp`), `rb` CLI, 원장(ledger)과 inbox, 8765 대시보드의 승인 페이지 | laptop | [hub-setup.md](hub-setup.md) · [국문](hub-setup.ko.md) |
| **Node** | `rb_node`: SSH forced command 엔드포인트(`rb-node serve-remote`), mailbox, 예산이 지정된 job, 메시지마다 시작되는 서버 Claude 세션(`serve-local` MCP), harness staging 채널 | node1 (실험 서버) | [node-setup.md](node-setup.md) · [국문](node-setup.ko.md) |

hub가 중심이다. 원장은 hub에만 있고, 연결을 여는 쪽도 hub뿐이며(hub에서 node로만, node에서 hub로는 열지 않는다), 사용자가 job을 승인하는 곳도 hub이다. hub 하나가 여러 node를 담당할 수 있다. node마다 별도의 키, SSH alias, hub `host.json` 항목을 갖는다.

```
Claude session ──stdio MCP── hub (rb-host-mcp, rb CLI, ledger, 8765 /rb/pending)
                                  │ ssh, alias rb-<node>         (message key, forced command)
                                  │ ssh, alias rb-<node>-harness (harness key, forced command)
                                  ▼
                              node (rb-node serve-remote / harness-receive)
                                  │ starts on each message
                                  ▼
                              server Claude session ──stdio MCP── rb-node serve-local
```

새 node의 설정 순서: hub 매뉴얼 §1–§3을 한 번 수행하고, node 매뉴얼 §1–§6을 수행한 뒤, 그 node에 대해 hub 매뉴얼 §4–§6을 수행하고, 마지막으로 node 매뉴얼 §7의 점검을 실행한다.

## 이 매뉴얼의 표기 규칙

- placeholder는 비공개 값을 대신한다: `<NODE_HOST>`, `<NODE_PORT>`, `<NODE_USER>`, `<NODE_HOME>`, `<HUB_SUBNET>`, `<HUB_LAN_IP>`. 실제 값은 gitignore 대상인 `private/placeholders.md`에 보관하며 커밋하지 않는다(`docs/CONTRIBUTING.md` §3).
- "User runs"(사용자가 실행)는 키를 만들거나, SSH 설정을 수정하거나, node에서 명령을 실행하는 단계를 가리킨다. `AGENTS.md`는 이 단계를 사용자가 직접 실행하거나 명령마다 승인하도록 요구한다.
- 영어 파일이 기준이다. `.ko.md` 파일은 번역이며, 두 파일이 다르면 영어 파일이 우선한다. 두 파일은 같은 변경에서 함께 갱신한다.

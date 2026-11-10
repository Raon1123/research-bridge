> 영어 파일 [README.md](README.md)가 기준 문서이고, 이 파일은 2026-11-10에 번역한 것이다.

# 설치 매뉴얼

이 두 매뉴얼은 저장소 `README.md`의 배경이 되는 참조 문서다. README는 저장소를 clone한 뒤 연결이 동작하고 일상 사용에 이르기까지를 안내한다. 매뉴얼은 각 명령이 무엇을 하고, 무엇을 읽고, 무엇을 쓰고, 무엇을 묻는지 설명하고, 해당 역할의 모든 명령·플래그·설정 키를 나열하며, doctor의 각 검사가 무엇을 뜻하는지 설명한다.

research-bridge에는 두 역할이 있다. 각 역할에 별도의 매뉴얼이 있다.

| 역할 | 실행하는 것 | 현재 | 매뉴얼 |
|---|---|---|---|
| **허브(Hub)** | `rb_host`: Claude 세션용 MCP (Model Context Protocol) 서버(`rb-host-mcp`), `rb` 명령, 원장(ledger)과 저장된 메시지, 무인 동기화, 읽기 전용 허브 페이지 | 이 Linux 서버, 2026-11-05부터 | [hub-setup.md](hub-setup.md) · [국문](hub-setup.ko.md) |
| **노드(Node)** | `rb_node`: SSH 강제 명령(forced command) 종단점(`rb-node serve-remote`), 메일함, 예산이 있는 작업, 메시지마다 시작되는 서버 Claude 세션(`serve-local` MCP), 하네스 스테이징 채널 | `node1` (실험 서버) | [node-setup.md](node-setup.md) · [국문](node-setup.ko.md) |

허브가 중심이다. 허브가 유일한 원장을 가지고, 연결을 여는 쪽은 허브뿐이며(허브에서 노드로만 열고, 노드에서 허브로는 열지 않는다), 사용자가 작업을 승인하는 곳도 허브다. 허브 하나가 여러 노드를 담당할 수 있으며, 노드마다 자체 키, SSH 별칭, 허브 `host.json`의 항목을 가진다. 노트북은 허브가 아니다. vault와 그 8765 대시보드는 노트북에만 있고, 허브 페이지는 노트북에서 SSH 로컬 포워드로 접속한다(허브 매뉴얼 §14).

```
Claude session ──stdio MCP── hub (rb-host-mcp, rb CLI, ledger, rb sync timer, hub page 127.0.0.1:8767)
                                  │ ssh, alias rb-<node>         (message key, forced command)
                                  │ ssh, alias rb-<node>-harness (harness key, forced command)
                                  ▼
                              node (rb-node serve-remote / harness-receive)
                                  │ starts on each message
                                  ▼
                              server Claude session ──stdio MCP── rb-node serve-local
```

## 새 노드 설치 순서

예전에는 두 매뉴얼에 나뉘어 있던 작업을 명령 두 개가 처리한다. 허브의 `rb setup`과 노드의 `scripts/node-install.sh`다. 각각 상대편에 필요한 명령을 출력한다.

| 단계 | 위치 | 명령 또는 작업 | 매뉴얼 |
|---|---|---|---|
| 1 | 허브 | `uv sync --extra host`와 테스트 | 허브 §1, §2 |
| 2 | 허브 터미널 | `rb setup --node node1 --host <NODE_HOST> --port <NODE_PORT> --user <NODE_USER>` | 허브 §4 |
| 3 | 노드 콘솔 | 출력된 `scripts/node-install.sh ...` 명령, 이어서 `rb-node approve-key set` | 노드 §2, §4.2 |
| 4 | 허브 터미널 | `rb setup --node node1`을 다시 실행(호스트 키 비교) | 허브 §4.2 |
| 5 | 허브 터미널 | 출력된 `claude mcp add-json ...`, 이어서 새 Claude 세션 시작 | 허브 §6 |
| 6 | 허브 | `rb doctor` | 허브 §10 |
| 7 | 허브 터미널 | `rb service install`, 이어서 출력된 `systemctl` 명령 | 허브 §13, §14 |
| 8 | 허브 | 보안 검사와 작업 한 건 | 노드 §7.1 |

일상 사용: 재부팅할 때마다 `rb agent`, 그리고 `rb pending` / `rb approve`, 허브 페이지, 문제가 생기면 `rb doctor`.

## 섹션 번호

다른 문서가 매뉴얼 섹션을 번호로 인용하므로 번호는 고정이다. 허브 §12는 Linux 허브, 노드 §5는 `authorized_keys` 줄, 노드 §7은 검사다. 새 내용은 부록 앞의 끝에 추가한다. Windows와 노트북 허브 설명은 각 매뉴얼의 부록 A에 있으며 2026-11-05부터 유지하지 않는다.

## 매뉴얼의 표기 규칙

- 자리표시자는 비공개 값을 대신한다. `node1`(노드 이름), `<NODE_HOST>`, `<NODE_PORT>`, `<NODE_USER>`(노드의 주소, SSH 포트, 로그인 이름), `<HUB_ADDR>`(노드가 보는 허브의 주소), `<HUB_SUBNET>`(허브의 네트워크 범위), `<HUB_HOST>`(노트북에서 허브 페이지로 SSH 포워드할 때 허브에 로그인하는 이름), `<NODE_HOME>`(노드 사용자의 홈 디렉터리), `<HUB_HOME>`(허브에서 harness 파일에 경로가 나타나는 홈 디렉터리; `local.example.json`), `<LAPTOP_LAN_IP>`(노트북 자신의 주소로, `docs/session-dashboard.md`의 8765 대시보드에만 쓴다), `<SHARED_KEY>`(노드의 옛 공유 키)이다. 이 목록이 유일한 목록이며 다른 문서는 이것을 가리킨다. 실제 값은 git이 무시하는 `private/placeholders.md`에 보관하며 커밋하지 않는다(`docs/CONTRIBUTING.md` §3).
- "허브 터미널"과 "노드 콘솔"은 사람이 그 기계에서 열어 둔 터미널을 뜻한다. `y/N`이나 passphrase를 묻는 명령은 터미널 없이는 실행을 거부하므로 Claude 세션이 실행할 수 없다. `AGENTS.md`는 노드의 모든 명령을 사용자가 직접 실행하거나 승인하도록 요구한다.
- 런타임은 uv만 쓴다. 허브 매뉴얼의 `rb ...`는 메인 체크아웃에서 `uv run --extra host rb ...`를 뜻한다. 사람은 평범한 명령을 입력하고, 세션은 셸 명령 앞에 `rtk`를 붙인다.
- 영어 파일이 기준이다. `.ko.md` 파일은 번역이며, 둘이 다르면 영어 파일을 따른다. 같은 변경에서 둘 다 갱신한다.

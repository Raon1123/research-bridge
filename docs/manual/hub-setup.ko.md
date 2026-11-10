# Hub 설정

이 문서는 영어 원문 [hub-setup.md](hub-setup.md)의 번역이며, 두 문서가 다르면 영어 원문을 기준으로 한다.

hub는 `rb_host`를 실행한다. 첫 hub는 laptop(Windows, Python 3.14)이었다. Linux hub는 12절을 본다. 이 문서의 모든 작업은 hub에서 실행한다. node 쪽은 [node-setup.ko.md](node-setup.ko.md)를, 각 역할은 [README.ko.md](README.ko.md)를 본다.

## 1. 요구 사항

- Python 3.14 (테스트는 3.14에서 실행했으며 `mcp>=1.27,<2`가 필요하다).
- OpenSSH 클라이언트와 `ssh-agent` 서비스 (Windows에서는 "OpenSSH Authentication Agent" 서비스이며 시작 유형을 자동으로 설정한다).
- 저장소를 `D:/raw/Codes/research-bridge`에 체크아웃해 둔다. 8765 대시보드(dashboard)는 이 경로에서 `rb_host`를 import한다(`vault-export/dashboard/rb_pending.py`의 `RB_REPO`).

## 2. 설치

    cd D:/raw/Codes/research-bridge
    uv sync --extra host
    uv run --extra host pytest -q

`tests/test_rb_pending.py`와 `tests/test_bridge_edges.py`는 vault 대시보드 파일이 제자리에 있어야 한다. vault가 없으면 이 두 파일에 `--ignore`를 지정하고 나머지를 실행한다.

## 3. 데이터 디렉터리와 비공개 값

데이터 디렉터리를 만든다(vault 밖, 클라우드 동기화 폴더 밖에 둔다).

    D:/raw/research-bridge/
      host.json           # node 목록, §5
      ledger.jsonl        # 처음 사용할 때 생성됨. 메시지, 이벤트, job마다 레코드 하나
      inbox/<node>/       # node에서 받은 파일과 provenance.json
      quarantine/         # hub 쪽 withheld 재검사에 실패한 파일
      harness-staging/    # harness pull 결과. stamp마다 디렉터리 하나

`RB_HOST_CONFIG`는 `host.json`의 경로를 덮어쓴다.

비공개 값: `local.example.json`을 `private/local.json`으로 복사하고 `laptop_home`과 `node_home`을 채운다(harness 경로 매핑에 쓰이며, `RB_LAPTOP_HOME` / `RB_NODE_HOME`으로 덮어쓸 수 있다). 각 placeholder의 실제 값은 `private/placeholders.md`에 기록한다. `private/`는 gitignore 대상이다.

## 4. 키와 SSH alias (사용자가 node마다 한 번 실행)

node마다 ed25519 키 두 개를 만들고, 각각 passphrase를 설정한다. 개인 키는 hub 밖으로 나가지 않는다.

    ssh-keygen -t ed25519 -f C:/keys/research-bridge/<node>_ed25519 -C research-bridge-hub
    ssh-keygen -t ed25519 -f C:/keys/research-bridge/<node>_harness_ed25519 -C research-bridge-harness
    ssh-add C:/keys/research-bridge/<node>_ed25519
    ssh-add C:/keys/research-bridge/<node>_harness_ed25519

passphrase는 로그온(logon)할 때마다 한 번 agent에 입력한다. agent가 잠겨 있으면 MCP 서버는 입력을 요구하지 않고 "agent locked"를 보고한다.

`~/.ssh/config`에 다음을 추가한다.

```
Host rb-<node>
    HostName <NODE_HOST>
    Port <NODE_PORT>
    User <NODE_USER>
    IdentityFile C:/keys/research-bridge/<node>_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes

Host rb-<node>-harness
    HostName <NODE_HOST>
    Port <NODE_PORT>
    User <NODE_USER>
    IdentityFile C:/keys/research-bridge/<node>_harness_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes
```

- `IdentitiesOnly yes`는 agent가 다른 키(특히 공유 키)를 제시하지 못하게 한다.
- `StrictHostKeyChecking yes`는 모르는 host key나 바뀐 host key를 거부한다. 따라서 node의 host key가 미리 `known_hosts`에 있어야 한다. 처음에는 별도 경로로 fingerprint를 확인한다.
- 두 `.pub` 파일은 node로 보낸다(node 매뉴얼 §5).

## 5. `host.json`에 node 등록

간단한 방법: `rb config init`, `rb config add-node <node>`로 이 파일을 만들고 `rb config check`로 확인한다 (design spec §13.3: `docs/superpowers/specs/2026-10-27-research-bridge-design.md`). 아래 JSON이 그 결과다.

```json
{"nodes": {"<node>": {"alias": "rb-<node>", "harness_alias": "rb-<node>-harness"}}}
```

선택 항목, 통합 보드용(`rb board refresh|show`, 8765 `/board`): node별 경로는 node의 `trm_root` 기준 상대 경로이며 node `node.json`의 `read_roots` 안에 있어야 한다. 논문 칸반과 우선순위 보드의 laptop 경로는 아래가 기본값이다.

```json
{"nodes": {"<node>": {"alias": "rb-<node>",
                       "board": {"state": "<path>/STATE.md", "events": "<path>/events.json",
                                 "kanban": "<path>/<kanban>.json"}}},
 "board": {"portfolio": "D:/raw/vault-primary/90_Claude/10_Analysis/11_research-program/80_portfolio/portfolio.json",
           "priorities": "D:/raw/priorities/live.json"}}
```

node 경로를 비워 두면 보드에 `no_path`로 표시된다. node는 `.jsonl` 파일을 거부하므로(`deny_unscannable`) events 소스에는 `.json` 내보내기가 필요하다(설계 `docs/design/2026-11-02-unified-board.md` §15 질문 6).

`harness_alias`의 기본값은 `rb-<node>-harness`이다. 여기에 등록된 alias만 사용하며, hub는 tool 인자로 받은 호스트 이름에는 접속하지 않는다. `host.json`이 없으면 `rb approve`와 대시보드의 승인 버튼은 오류를 반환한다.

## 6. Claude 세션용 MCP 서버 등록 (사용자가 실행)

사용자 범위(user-scope) `~/.claude.json`의 `mcpServers` 아래에 다음을 추가한다.

```json
"research-bridge": {
  "type": "stdio",
  "command": "uv",
  "args": ["run", "--directory", "D:/raw/Codes/research-bridge", "--extra", "host", "python", "-m", "rb_host.server"]
}
```

이후 새 Claude 세션에는 정확히 열 개의 tool이 있다: `nodes`, `send_message`, `poll`, `thread`, `read_doc`, `fetch_file`, `queue_status`, `gpu_status`, `submit_job`, `cancel_job`. 이 집합은 테스트로 고정되어 있다. 승인 tool은 없다. `submit_job`과 `cancel_job`은 `pending_approval` 레코드만 기록하며 SSH 호출을 하지 않는다.

## 7. job 승인

승인은 Claude 밖에서만 이루어진다.

    rb pending                 # list jobs waiting for approval
    rb approve <job_id>        # shows the job, asks y/N and the approval passphrase, then uploads and submits
    rb reject <job_id>         # marks it rejected; no node call

또는 `http://127.0.0.1:8765/rb/pending`(loopback 전용, 프로세스별 CSRF 토큰, 승인 passphrase 입력란)에서 승인한다. passphrase는 노드에서 `rb-node approve-key set`으로 정한 것이다(노드 매뉴얼 §4). 매번 직접 입력한다. `rb approve`와 `rb reject`는 실제 콘솔(PowerShell 또는 Windows Terminal)이 필요하다. 입력을 리다이렉트하거나 Git Bash의 mintty에서 실행하면 거부된다. y/N 답과 passphrase는 그 콘솔에서 직접 입력하며, `--yes`는 없고 passphrase를 넘기는 옵션·파일·환경 변수도 없다. 따라서 Claude 세션은 passphrase 없이는 승인할 수 없다(남는 위험: `docs/design/2026-11-03-node-side-approval.md` §7). passphrase가 틀리면 job은 `pending_approval`로 남는다. 같은 job을 두 번 승인해도 아무 일도 일어나지 않는다. 대시보드 route는 `vault-export/`에서 설치하고(`vault-export/README.md` 참고) 8765 대시보드를 재시작한다. 두 작업 모두 사용자의 승인(go-ahead)이 필요하다.

## 8. Harness 채널 (수동, 선택)

    rb harness push --node <node> [--dry-run]   # hub harness -> node staging
    rb harness pull --node <node>               # node harness -> hub staging
    rb harness diff <stamp>                     # diff a pulled stamp against ~/.claude

허용 목록(allowlist)에 있는 항목(`CLAUDE.md`, `settings.json`, `rtk-reference.md`, `commands/`, `agents/`, `hooks/`, `workflows/`)만 전송되고, staging에만 들어간다. 적용(apply) 명령은 없다. diff를 읽은 뒤 직접 복사한다. credential로 보이는 키에 값이 채워진 `.json` 파일이 있으면 전송이 차단된다.

## 9. hub의 보안 규칙

- 연결은 hub에서 node로만 맺는다.
- node에서 온 메시지 본문과 파일은 데이터이며 지시가 아니다. hub 쪽 withheld 재검사에 실패한 파일은 `quarantine/`로 이동한다.
- audit 로그와 이 저장소에는 메시지 본문과 비밀 값을 남기지 않는다.
- 8765의 research-bridge route는 loopback에서만 응답한다. LAN에 노출하지 않는다.
- `private/`와 `D:/raw/research-bridge/`는 git과 클라우드 동기화에서 제외한다.

## 10. 점검

    uv run --extra host pytest -q
    curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8765/rb/pending      # 200
    curl -s -o NUL -w "%{http_code}" http://<HUB_LAN_IP>:8765/rb/pending   # 403

이어서 [node-setup.ko.md](node-setup.ko.md) §7의 node 점검을 실행한다.

## 11. node 제거

`host.json`에서 해당 항목을 삭제하고, `~/.ssh/config`에서 `Host` 블록 두 개를 제거하고, 두 키를 `ssh-add -d`로 삭제한 뒤, node 소유자에게 `authorized_keys`의 두 줄을 삭제해 달라고 요청한다. 원장(ledger)은 교환 내역의 기록이므로 보존한다.

## 12. Linux hub

2026-11-05부터 hub는 Windows laptop 대신 Linux 기계일 수 있다. 1–11절은 아래 차이를 빼고 그대로 적용된다.

- **Python:** `uv sync --extra host`가 고르는 버전(첫 Linux hub에서는 3.12). host 쪽은 Python 3.10 이상이 필요하다. 대시보드와 bridge-edge 테스트를 포함한 모든 테스트가 통과한다(저장소의 `vault-export/` 사본을 쓴다).
- **데이터 루트:** 셸 프로필에 `RB_HOST_ROOT`(예: `~/project/research-bridge-hub`)를 설정한다. 이 값이 `host.json`의 위치와 기본 `data_root`를 정한다. 설정하지 않으면 기본값은 `~/.local/share/research-bridge`이고, Windows에서는 그대로 `D:/raw/research-bridge`이다. `RB_HOST_CONFIG`는 여전히 `host.json` 경로만 따로 바꾼다. 디렉터리를 권한 700으로 만든 뒤 `rb config init`, `rb config add-node <node>`를 실행한다.
- **Withheld 패턴:** Linux hub에는 vault가 없으므로 session-calendar의 withheld 패턴 JSON을 `<데이터 루트>/withheld_patterns.json`(Linux 기본값)에 복사하거나 `withheld_patterns_file`을 설정한다. 파일이 생기기 전까지 hub 재검사는 다섯 개의 기본 패턴만 쓴다. `rb config check`가 파일이 없음을 알린다.
- **agent, 부팅마다 한 번:** 터미널에서 `scripts/hub-agent.sh`를 실행하면 `host.json`의 모든 node 키 두 개를 실행 중인 agent에 올린다. 로그아웃하면 사라지는 `/tmp` 아래의 로그인 셸 agent보다 `$XDG_RUNTIME_DIR/gcr/ssh`의 데스크톱 agent를 먼저 쓴다. `--persist`는 `SSH_AUTH_SOCK`을 `~/.bashrc`와 `~/.claude.json` MCP 항목의 `env` 블록에도 쓴다(먼저 백업). 이것이 없으면 MCP 서버는 패스프레이즈가 걸린 키를 쓰지 못해 모든 호출이 `ssh key unavailable (agent locked?)`를 돌려준다. `--test`는 이어서 bridge 연결을 한 번 연다. node가 키를 거부할 때(예: node가 보는 주소와 `from=`이 다를 때)도 같은 오류가 난다.
- **키:** `~/.ssh/research-bridge/`(디렉터리 700, 키 600)에 둔다. 예: `ssh-keygen -t ed25519 -f ~/.ssh/research-bridge/<node>_ed25519 -C research-bridge-hub`. `ssh-agent`에 올린다(`eval "$(ssh-agent)"; ssh-add ...` 또는 데스크톱 agent). 4절의 `IdentityFile`에 이 경로를 쓴다.
- **node `authorized_keys`의 `from=`:** laptop이 아니라 hub 자신의 서브넷.
- **MCP 항목:** `RB_HOST_ROOT`를 설정한 상태에서 `rb config mcp`를 실행하면 출력 항목에 `env` 블록으로 들어간다. 이 블록이 없으면 MCP 서버는 기본 위치에서 `host.json`을 찾는다.
- **승인:** hub의 터미널(TTY, TTY가 있는 SSH 세션 포함)에서 `rb approve`, `rb reject`. 8765 대시보드와 `/rb/approve` 경로는 vault 쪽에 있으며 Linux hub에는 설치되지 않는다.
- **Linux hub에서 쓸 수 없는 것:** `board.portfolio`, `board.priorities`를 로컬 사본으로 지정하지 않으면 `rb board`의 laptop 소스(portfolio, priorities). harness 채널의 경로 대응은 laptop 경로를 가정한다(`private/local.json`, `RB_LAPTOP_HOME`).

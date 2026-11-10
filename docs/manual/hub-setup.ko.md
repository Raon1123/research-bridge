> 영어 파일 [hub-setup.md](hub-setup.md)가 기준 문서이고, 이 파일은 2026-11-10에 번역한 것이다.

# Hub setup

허브는 `rb_host`를 실행한다. MCP 서버(Model Context Protocol, Claude 세션이 도구를 호출할 때 쓰는 인터페이스), `rb` 명령, 원장(ledger), 저장된 메시지가 여기에 속한다. 2026-11-05부터 허브는 Linux 서버다(사용자 결정, §12). 노트북은 더 이상 허브가 아니며, vault와 그 8765 대시보드는 노트북에만 있다. 이 매뉴얼의 모든 내용은 단계에서 달리 말하지 않는 한 허브에서 실행한다. Windows와 노트북 허브 설명은 부록 A에 모아 두었으며 유지하지 않는다. 노드 쪽은 [node-setup.md](node-setup.md)를, 역할은 [README.md](README.md)를 본다.

## How to read this manual

- **명령을 누가 실행하는가.** "허브 터미널"은 사용자가 허브에서 열어 둔 터미널을 뜻한다. 질문(`y/N`, passphrase)을 하는 명령은 터미널 없이는 실행을 거부하므로(stdin과 stdout이 모두 터미널이어야 한다) Claude 세션이 실행할 수 없다. 세션은 "session-safe"로 표시된 형태를 실행할 수 있다. `rb setup --yes-print-only`, `rb doctor --offline`, `rb service install --print`, `rb config path`, `rb config show`, `rb config check`, `rb config mcp`, `rb board show`다. 그 밖의 `rb config` 형태(`init`, `add-node`, `remove-node`, `set`, `local`)는 묻지 않고 `host.json`이나 `private/local.json`을 쓰고, `rb web serve`는 프로세스를 시작하므로 세션은 사용자의 승인이 필요하다(`AGENTS.md`의 "Ask the user before"). 옵션 `--offline` 없는 `rb doctor`와 `rb sync`는 노드에 연결하므로 이것도 승인이 필요하다.
- **`rb`를 실행하는 방법.** 런타임은 uv가 관리한다. 이 매뉴얼에서 `rb ...`는 메인 체크아웃에서 실행하는 `uv run --extra host rb ...`(또는 `.venv/bin/rb ...`)를 뜻한다. 세션은 셸 명령 앞에 `rtk`를 붙이고, 사람은 평범한 명령을 입력한다.
- **자리표시자.** `node1`은 예시에 쓰는 노드 이름이다. `<NODE_HOST>`, `<NODE_PORT>`, `<NODE_USER>`는 노드의 주소, SSH 포트, 로그인 이름이다. `<HUB_ADDR>`는 노드가 보는 허브의 주소이고, `<HUB_SUBNET>`은 허브의 네트워크 범위이며, `<HUB_HOST>`는 노트북에서 허브에 로그인할 때 쓰는 이름이다. 전체 목록은 `docs/manual/README.md`에 있다. 실제 값은 git이 무시하는 파일에만 둔다.
- **약어.** SSH = Secure Shell. MCP = Model Context Protocol. TOFU = trust on first use(호스트 키를 처음 볼 때 받아들이는 방식). systemd = Linux 서비스 관리자이며, "user unit"은 사용자 계정으로 실행된다.

### Order of a first setup

| 단계 | 위치 | 내용 | 섹션 |
|---|---|---|---|
| 1 | 허브 | 설치, 테스트 실행 | §1, §2 |
| 2 | 허브 | `rb setup --node node1 --host <NODE_HOST> --port <NODE_PORT> --user <NODE_USER>`: 설정, 키, SSH 블록, agent. 노드 명령과 MCP 명령을 출력한다 | §4 |
| 3 | 노드 콘솔 | 출력된 `scripts/node-install.sh ...`를 실행하고, 이어서 `rb-node approve-key set` | [node-setup.md](node-setup.md) §2, §4 |
| 4 | 허브 | `rb setup --node node1`을 다시 실행: 호스트 키 비교 | §4 |
| 5 | 허브 | 출력된 `claude mcp add-json ...`을 실행하고 새 Claude 세션을 시작 | §6 |
| 6 | 허브 | `rb doctor` | §10 |
| 7 | 허브 | `rb service install`, 이어서 출력된 `systemctl` 명령 | §13, §14 |

## 1. Requirements

- systemd user manager가 있는 Linux(타이머와 페이지에 필요하다. §13), 그리고 모드 700의 런타임 디렉터리 `/run/user/<uid>`(일반 로그인 세션이 만든다).
- Python 3.10 이상. `uv sync --extra host`가 이를 선택한다(첫 Linux 허브에서는 3.12). 버전 1.27 이상 2 미만의 `mcp` 패키지가 이 명령으로 설치된다.
- uv, git, OpenSSH 클라이언트 도구: `ssh`, `ssh-keygen`, `ssh-keyscan`, `ssh-agent`, `ssh-add`. `ip`(iproute2)는 허브 주소를 추정할 때 한 번 쓰이고, `loginctl`과 `systemctl`은 unit에 쓰인다.
- Claude Code CLI(`claude`). MCP 서버를 등록할 때만 필요하다(§6). `rb` 자체는 `~/.claude.json`을 편집하지 않는다.
- 네트워크: 허브가 노드로 SSH 연결을 연다(허브에서 노드로만). 노드는 허브에 연결하지 않는다.

## 2. Install

저장소의 메인 체크아웃에서 실행한다(git worktree는 안 된다. worktree는 나중에 삭제되어 MCP 항목과 unit 파일이 없는 경로를 가리키게 된다).

    uv sync --extra host
    uv run --extra host pytest -q

`python -m venv`나 `pip`는 쓰지 않는다. 테스트는 로컬 하위 프로세스를 노드로 띄우며 실제 노드에는 접속하지 않는다. 대시보드와 bridge-edge 테스트는 저장소의 `vault-export/` 사본을 쓰므로 vault가 필요 없다.

## 3. Data directory and config files

데이터 루트에는 허브가 저장하는 모든 것이 있다. 저장소 밖이며 클라우드 동기화 폴더 밖이다.

| 데이터 루트 아래 경로 | 내용 | 쓰는 주체 |
|---|---|---|
| `host.json` | 노드 목록과 옵션(§5, §16). 모드 600 | `rb setup`, `rb config` |
| `ledger.jsonl` | 메시지, 이벤트, 작업마다 레코드 하나 | MCP 서버, `rb`, `rb sync` |
| `inbox/<node>/<msg_id>/` | 저장된 노드 메시지: `body.txt`, `provenance.json`, 첨부 파일 | `poll`, `rb sync` |
| `outbox/<node>/<msg_id>/` | 보낸 본문의 마스킹된 사본과 각 첨부 파일의 이름, 크기, 해시(파일은 복사하지 않는다) | `send_message` |
| `quarantine/<node>/` | 허브 쪽 withheld 재검사에 실패한 파일 | `poll`, `rb sync` |
| `fetched/<node>/` | `fetch_file`로 받은 파일 | `fetch_file` |
| `sync/<node>.json` | 마지막 동기화 한 번의 상태(§13.2). 모드 600 | `rb sync` |
| `board/` | 통합 board 캐시 | `rb board refresh`, `rb sync` |
| `share/` | 공유 상태 페이지 스냅숏 | `rb share build` |
| `harness-staging/<stamp>/` | harness pull 결과(§8) | `rb harness pull` |
| `withheld_patterns.json` | withheld 패턴의 허브 사본(§3.1) | 사용자가 복사한다 |

데이터 루트의 위치: `RB_HOST_ROOT` 환경 변수가 설정돼 있으면 그 값이고, 아니면 `~/.local/share/research-bridge`다. `RB_HOST_CONFIG`는 `host.json`의 경로만 바꾼다. `host.json`의 `data_root` 키는 나머지 모든 것의 저장 위치를 정하며, `rb config init --data-root DIR`이 이를 쓴다. 디렉터리는 모드 700으로 만든다(`rb setup`이 한다).

체크아웃의 `private/local.json`(gitignore 대상)은 harness 경로 매핑에만 쓰이는 `laptop_home`과 `node_home`을 담는다(§8). `rb config local --laptop-home DIR --node-home DIR`이 이를 쓴다. 그 밖에는 이 파일이 필요하지 않다.

### 3.1 Withheld pattern file on the hub

허브는 저장하는 모든 것을 내장 fallback 패턴 다섯 개(`AGENTS.md` 핵심 규칙 3)와, 파일이 있으면 그 패턴 파일에 대해 다시 검사한다. 이 허브에는 vault가 없으므로 이 파일은 session-calendar 내보내기의 사본이다. `<data root>/withheld_patterns.json`(이름에 밑줄)에 두거나, `host.json`의 `withheld_patterns_file`이 이를 가리키게 한다.

형식: JSON이며 다음 중 하나다. 정규식 문자열의 목록, `{"patterns": [...]}`, `{"families": [{"patterns": [...]}, ...]}`. YAML은 읽지 않으며 `exp_id_patterns` 키는 무시한다. 지어낸 패턴의 예: `{"patterns": ["secretproject_[0-9]+"]}`. 파일을 읽을 수 없거나, 유효한 JSON이 아니거나, 패턴이 없거나, 컴파일되지 않는 패턴이 있으면 `rb doctor`가 `withheld_hub`를 `fail`로 보고하며, 그때 허브는 내장 패턴 다섯 개만 적용한다. 노드는 이름이 다른 자체 사본(`withheld-patterns.json`, 하이픈. 노드 매뉴얼 §4.3)을 가진다.

## 4. Link a node: `rb setup`

`rb setup --node NAME`은 예전에는 여러 문서에 걸쳐 있던 작업을 명령 하나로 처리한다. 설정, 키 두 개, SSH 블록, known-hosts 항목을 만들고, 키를 agent에 올리고, 사용자가 직접 실행해야 하는 명령 두 개(노드 명령과 MCP 명령)를 출력한다. 멱등적이다. 이미 충족된 단계는 모두 건너뛰므로 언제든 다시 실행할 수 있다.

    rb setup --node node1 --host <NODE_HOST> --port <NODE_PORT> --user <NODE_USER>

| Flag | Meaning |
|---|---|
| `--node NAME` | 필수. 노드 이름: 영문자, 숫자, `_`, `-`, 최대 32자, 첫 글자는 영문자 또는 숫자. |
| `--host`, `--user` | 첫 실행에서는 필수. 이후 실행은 `ssh -G rb-NAME`(4단계가 쓴 블록)에서 다시 읽는다. |
| `--port` | SSH 포트. 기본값 22(또는 기존 블록의 포트). |
| `--keydir DIR` | 키가 있는 곳(기본값 `~/.ssh/research-bridge`). 디렉터리가 이를 무시하지 않는 git 작업 트리 안에 있으면 거부된다. |
| `--hub-from ADDR` | 노드가 이 허브로 보는 주소. 출력되는 노드 명령에 들어간다. 기본값: `ip -o route get <NODE_HOST>`의 출발지 주소. 기계 사이에서 라우터가 주소를 변환하면 명시적으로 준다. |
| `--research-root DIR` | 노드의 연구 트리. 출력되는 노드 명령에 복사될 뿐 허브 어디에도 저장되지 않는다. |
| `--yes-print-only` | 모든 변경과 명령을 보여 주고, 아무것도 쓰지 않고, 묻지 않고, 스캔하지 않고, 네트워크 트래픽도 만들지 않는다(session-safe). 이름과 달리 아무것도 확인하지 않는다. |

`--yes-print-only` 없이는 3~6단계에서 질문을 하므로 터미널이 필요하다.

### 4.1 What the nine steps do

| # | Step | Reads | Writes | Asks |
|---|---|---|---|---|
| 1 | 데이터 루트와 `host.json` | `RB_HOST_ROOT`, `RB_HOST_CONFIG`, `host.json` | 데이터 루트(모드 700)와 `host.json`(모드 600, git이 추적하게 되면 거부) | 없음. 유효한 JSON이 아닌 기존 `host.json`이 있으면 설정이 멈춘다. |
| 2 | 노드 항목 | `host.json` | `nodes.NAME = {alias: rb-NAME, harness_alias: rb-NAME-harness}` | 없음. 다른 별칭을 가진 기존 항목은 유지하고 그 별칭을 쓴다. |
| 3 | 키 두 개 | `<keydir>/NAME_ed25519{,.pub}`, `<keydir>/NAME_harness_ed25519{,.pub}` | 없는 쌍을 `ssh-keygen -t ed25519`로 만든다. 주석은 `research-bridge-hub`와 `research-bridge-harness`이고 디렉터리는 모드 700 | `Generate ...? [y/N]`, 이어서 `ssh-keygen`이 키마다 passphrase를 두 번 묻는다(두 키에 같은 passphrase를 써도 된다). `.pub` 없는 개인 키는 보고만 하고 고치지 않는다. |
| 4 | SSH 블록 | 두 별칭에 대한 `ssh -G` | 백업 `config.bak.<stamp>`을 만든 뒤 `Host` 블록 두 개를 `~/.ssh/config`에 추가 | 블록을 보여 주고 `Append to ...? [y/N]`을 묻는다. 별칭이 이미 정의돼 있으면 아무것도 추가하지 않는다. 설정은 다른 옵션을 하나씩 나열하고 합칠 수 있게 기대하는 블록을 출력한다. 심볼릭 링크 대상이나 git이 추적할 파일에는 쓰지 않고 텍스트를 출력한다. |
| 5 | 호스트 키 | `ssh -G`, `known_hosts` | 스캔한 호스트 키 줄(`ssh-keyscan`이 `ed25519`, `ecdsa`, `rsa` 순으로 시도하여 응답하는 첫 종류를 유지)을 백업 후 첫 번째 known-hosts 파일에 추가 | 노드 명령을 이미 실행한 경우에만: `ssh-keyscan`으로 한 번 스캔하고, 지문을 보여 주고, `... Does the fingerprint equal the node's? Append to ...? [y/N]`을 묻는다. 키를 생성한 실행에서는 아무것도 스캔하지 않고 노드 명령을 실행한 뒤 다시 실행하라고 알려 준다. |
| 6 | Agent와 키 | `$XDG_RUNTIME_DIR`의 agent 소켓만(§4.3) | 응답하는 agent가 없으면 `$XDG_RUNTIME_DIR/rb-ssh-agent`에 agent를 시작한다. 아직 목록에 없는 키마다 `ssh-add` | `ssh-add`가 키마다 passphrase를 묻는다. |
| 7 | 노드 명령 | 두 `.pub` 파일, `--hub-from` 또는 `ip route get`, 허브 withheld 파일, 체크아웃의 `origin` URL | 없음 | 없음. 두 공개 키를 인라인으로 넣은 `scripts/node-install.sh ...` 명령을 출력한다. `--hub-from`, `--withheld-file`(허브 패턴 파일이 있을 때만), `--research-root`(주어졌을 때만)도 포함한다. |
| 8 | MCP 등록 | `~/.claude.json`(읽기만), `PATH`의 `uv`, 체크아웃 경로 | 없음 | 없음. 같은 항목이 이미 있지 않으면 `claude mcp add-json --scope user research-bridge '<json>'`을 출력한다(§6). |
| 9 | Doctor | `rb doctor --node NAME`과 같음(오프라인은 `--yes-print-only`일 때만) | 없음 | 없음. 노드 명령을 실행하기 전에는 온라인 부분이 실패하는 것이 정상이다. |

각 단계는 `-> done`, `-> skipped`, `-> printed`, `-> failed: <reason>` 중 하나로 끝난다. 1단계나 2단계의 실패는 설정을 멈추고, 3~8단계의 실패는 마지막에 보고하며(`setup did not finish: ...`, 종료 코드 1) 나머지 단계는 계속 실행한다. 종료 코드는 9단계 doctor의 결과를 반영하지 않으므로 그 결과는 `rb doctor`로 확인한다.

### 4.2 The two-pass first run

1. 허브 터미널: `rb setup --node node1 --host <NODE_HOST> --port <NODE_PORT> --user <NODE_USER>`. 1~4단계와 6단계가 실행되고, 5단계는 미뤄지며, 7단계가 노드 명령을 출력한다.
2. 허브 withheld 패턴 파일을 노드의 `~/withheld-patterns.json`으로 복사한다(`scp`, 허브에서 노드로). `known_hosts`에 노드 항목이 아직 없으면 `scp`가 자체적으로 yes/no를 묻고 항목을 기록하며, 그러면 `rb setup`의 5단계는 그 항목을 찾아 비교를 건너뛴다. `yes`라고 답하기 전에 `scp`가 보여 주는 지문을 노드 콘솔의 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` 결과와 비교하고, 다르면 `no`로 답한다. 그다음 출력된 명령을 이 저장소의 체크아웃이 있는 노드 콘솔에서 실행한다(노드 매뉴얼 §2). 끝에서 노드의 호스트 키 지문을 출력한다.
3. 허브 터미널: `rb setup --node node1`. 이제 5단계가 스캔한 지문을 보여 준다. 노드가 출력한 같은 종류의 줄과 같을 때만 `y`로 답한다. 다르면 연결하지 말고, 노드 콘솔에서 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`로 확인하여 먼저 원인을 찾는다.
4. 8단계의 MCP 명령을 실행한다(§6).

### 4.3 Which agent `rb` uses

규칙은 둘이며 의도적으로 다르다.

- **키 올리기**(`rb setup` 6단계, `rb agent`): 런타임 디렉터리 아래의 소켓만 쓰며, 순서는 `$XDG_RUNTIME_DIR/gcr/ssh`(데스크톱 키링 agent), `openssh_agent`, `rb-ssh-agent`, 그리고 `$SSH_AUTH_SOCK`이 그 디렉터리 안에 있으면 그것이다. 응답하는 것이 없으면 `rb`가 `ssh-agent -a $XDG_RUNTIME_DIR/rb-ssh-agent`를 시작한다. 키는 그 디렉터리 밖에서 상속된 agent(예를 들어 포워딩된 agent)에는 추가하지 않으므로, 무인 동기화가 나중에 그 키를 쓸 수 있다.
- **연결하기**(MCP 서버, `rb sync`, `rb doctor`): `$SSH_AUTH_SOCK`을 먼저, 이어서 런타임 디렉터리의 같은 소켓 세 개를 시도하며, 응답하는 소켓 중 해당 별칭의 키를 가진 것이 선택된다. 찾은 소켓은 30초 동안 기억한다. 그래서 MCP 항목에 `SSH_AUTH_SOCK`이 필요 없고, agent가 바뀌어도 세션을 다시 시작할 필요가 없다.

재부팅 뒤 agent는 비어 있다. 허브 터미널에서 `rb agent`를 실행한다(§4.4).

### 4.4 `rb agent`

    rb agent [--node NAME]

허브 터미널에서만 실행한다. `host.json`의 각 노드의 두 별칭에 대한 `ssh -G`에서 키 파일 이름을 읽고(모든 노드, 또는 `--node`), agent에 아직 없는 키를 올리고(키마다 passphrase를 묻는다), agent 소켓 경로와 다른 셸용 `export SSH_AUTH_SOCK=...`를 출력한다(`rb harness`에만 필요하다). harness 블록이 없는 것은 오류가 아니라 안내다. bridge 키 파일이 없거나, `ssh-add`가 실패하거나, agent에 닿을 수 없으면 종료 코드 1이다.

### 4.5 By hand

<details>
<summary>By hand: keys, SSH blocks, host key, agent</summary>

`rb setup`을 실행할 수 없을 때만 쓴다(예를 들어 그 출력이 맞춤형 `~/.ssh/config`에 맞지 않는 경우).

키는 노드마다 두 개이고, 각각 passphrase를 가진다. 개인 키는 허브를 떠나지 않는다.

    mkdir -p ~/.ssh/research-bridge && chmod 700 ~/.ssh/research-bridge
    ssh-keygen -t ed25519 -f ~/.ssh/research-bridge/node1_ed25519 -C research-bridge-hub
    ssh-keygen -t ed25519 -f ~/.ssh/research-bridge/node1_harness_ed25519 -C research-bridge-harness

`~/.ssh/config`에 추가한다(4단계가 쓰는 것과 정확히 같다).

```
Host rb-node1
    HostName <NODE_HOST>
    Port <NODE_PORT>
    User <NODE_USER>
    IdentityFile ~/.ssh/research-bridge/node1_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes
    ServerAliveInterval 15
    ServerAliveCountMax 3

Host rb-node1-harness
    HostName <NODE_HOST>
    Port <NODE_PORT>
    User <NODE_USER>
    IdentityFile ~/.ssh/research-bridge/node1_harness_ed25519
    IdentitiesOnly yes
    StrictHostKeyChecking yes
    ServerAliveInterval 15
    ServerAliveCountMax 3
```

- `IdentitiesOnly yes`는 agent가 다른 키를 제시하지 못하게 한다.
- `StrictHostKeyChecking yes`는 알 수 없거나 바뀐 호스트 키를 거부하므로, 노드의 키가 먼저 `known_hosts`에 있어야 한다.

호스트 키(처음 본 키를 안전하게 신뢰하는 방법): 스캔하고, 지문을 출력하고, 노드 콘솔에 출력된 지문과 비교한 뒤에만 추가한다.

    ssh-keyscan -t ed25519 -p <NODE_PORT> <NODE_HOST> > /tmp/node1.hostkey
    ssh-keygen -lf /tmp/node1.hostkey
    # compare with: ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub  (on the node console)
    cat /tmp/node1.hostkey >> ~/.ssh/known_hosts

`HashKnownHosts yes`가 설정돼 있으면 `ssh-keyscan`에 `-H`를 추가한다.

Agent:

    ssh-agent -a "$XDG_RUNTIME_DIR/rb-ssh-agent"      # only if no agent answers
    SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/rb-ssh-agent" ssh-add ~/.ssh/research-bridge/node1_ed25519 ~/.ssh/research-bridge/node1_harness_ed25519

노드의 `authorized_keys` 줄은 `scripts/node-install.sh`가 쓴다. 수동 방법은 노드 매뉴얼 §5에 있다.

</details>

## 5. `host.json`

`rb setup`이 `host.json`을 만들고 채운다(1단계와 2단계). 명령이 있는 부분은 직접 고치지 말고 `rb config`로 편집한다(§15). 일반적인 경우의 JSON은 다음과 같다.

```json
{"nodes": {"node1": {"alias": "rb-node1", "harness_alias": "rb-node1-harness"}}}
```

이 파일에 있는 별칭만 쓰인다. 허브는 도구 인자로 받은 호스트 이름에는 절대 연결하지 않는다. 모든 키는 §16.1에 있다. 선택 항목은 다음과 같다.

- **통합 board**(`rb board refresh|show`, 그리고 동기화 한 번마다의 board 부분). 노드별 경로이며, 노드의 연구 루트에 대한 상대 경로이고 노드의 `read_roots` 중 하나 안에 있어야 한다. `nodes.node1.board.state|events|kanban`(`rb config set nodes.node1.board.state PATH`). 생략한 경로는 `no_path`로 기록된다. `.jsonl` 파일은 노드가 거부하므로(`deny_unscannable`) events 소스에는 `.json` 내보내기가 필요하다. 노트북의 소스(`board.portfolio`, `board.priorities`)는 노트북 파일의 로컬 사본을 가리킨다. 사본이 없으면 이 허브에서 그 두 board 행은 없는 것으로 표시된다.
- **공유 상태 페이지**(`rb share`): `rb config set`으로 설정하는 `share.calendar_sessions|calendar_status|runs`. `share.labels`(허용되는 프로젝트와 트랙 레이블의 목록)는 명령이 없으므로 `host.json`에 직접 추가한다. 없으면 모든 레이블이 `other`로 표시된다.

사용할 수 있는 `host.json`이 없으면, 그것이 필요한 모든 `rb` 명령이 한 줄 `error: no usable host.json at <path>; run: rb setup --node NAME --host HOST --user USER`를 출력하고 종료 코드 1로 끝난다.

## 6. Register the MCP server for Claude sessions

`rb setup` 8단계가 명령을 출력한다. 메인 체크아웃에서 허브 터미널로 직접 실행한다(`rb`는 `~/.claude.json`을 편집하지 않는다).

    claude mcp add-json --scope user research-bridge '{"type": "stdio", "command": "/usr/bin/uv", "args": ["run", "--directory", "/path/to/research-bridge", "--extra", "host", "python", "-m", "rb_host.server"], "env": {"RB_HOST_CONFIG": "/path/to/host.json"}}'

실제 명령에는 사용자의 경로가 들어 있다. `env`에는 항상 `RB_HOST_CONFIG`(`host.json`의 절대 경로)가 있고, `RB_HOST_ROOT`는 `rb setup`을 실행한 셸에 설정돼 있었을 때만 있다. 평소 쓰는 셸 설정과 같은 셸에서 `rb setup`이나 `rb config mcp`를 실행한다. 항목에는 `SSH_AUTH_SOCK`이 없다(§4.3). 그것이 있는 옛 항목도 계속 동작한다.

`rb config mcp`는 같은 항목을 JSON으로 출력한다. 등록된 항목이 없거나, 없는 경로나 worktree를 가리키거나, `rb setup`이 출력하는 항목과 다르면 `rb doctor`의 `mcp_entry` 검사가 경고한다. 그때는 항목을 제거하고(`claude mcp remove research-bridge`) 다시 등록한다. 이 `rb`가 git worktree에서 실행되고 등록된 항목이 체크아웃 경로만 다를 때도 경고(`from_worktree`)하며, 이때 다음 단계는 메인 체크아웃에서 `rb`를 실행하는 것이다.

그러면 새 Claude 세션은 정확히 도구 열 개를 가진다. `nodes`, `send_message`, `poll`, `thread`, `read_doc`, `fetch_file`, `queue_status`, `gpu_status`, `submit_job`, `cancel_job`이다. 테스트가 이 집합을 고정한다. 승인 도구는 없다. `submit_job`과 `cancel_job`은 `pending_approval` 레코드만 쓰고 SSH 호출은 하지 않는다.

- `nodes`는 노드별로 마지막 동기화 결과도 돌려준다. `synced`, `ok`, `error`, `stage`, `last_attempt_at`, `last_ok_at`, `age_s`, `stale`(900초 동안 성공한 한 번이 없음), `node_seen_at`, `node_version`, `protocol`, `withheld_extra`, `undelivered`.
- `poll`은 노드의 각 항목을 한 번씩 돌려준다. `rb sync`가 앞서 저장한 항목은 `stored: true`로 포함되며, 연결할 수 없는 노드도 저장된 항목은 돌려준다.
- `send_message`는 본문의 마스킹된 사본을 `outbox/`에 보관한다(§3). `thread`는 세션이 저장된 본문을 읽을 수 있도록 각 레코드에 `has_body`와 `stored_dir`를 돌려준다.

## 7. Approving jobs

승인은 Claude 밖의 허브 터미널에서만 이루어진다.

    rb pending                 # list jobs waiting for approval
    rb approve <job_id>        # shows the job, asks y/N and the approval passphrase, then uploads and submits
    rb reject <job_id>         # marks it rejected; no node call

passphrase는 노드에서 `rb-node approve-key set`으로 설정한 것이다(노드 매뉴얼 §4.2). 매번 직접 입력한다. `rb approve`와 `rb reject`는 터미널이 필요하고(터미널이 있는 SSH 로그인도 해당한다), `--yes`가 없으며, passphrase를 위한 플래그, 파일, 환경 변수도 없으므로 Claude 세션은 승인할 수 없다. passphrase가 틀리면 작업은 `pending_approval`로 남고, 두 번 승인해도 아무 일도 일어나지 않는다. 잘못된 키를 다섯 번 입력하면 노드가 30초를 기다리게 하고, 그 시간은 최대 1시간까지 두 배씩 늘어난다(`approval_wait`). 남은 위험: `docs/design/2026-11-03-node-side-approval.md` §7. 허브 페이지(§14)는 대기 중인 작업을 입력할 명령 두 개와 함께 보여 주지만 아무것도 승인할 수 없다. 8765 승인 경로는 노트북에만 있다(부록 A).

## 8. Harness channel (manual, optional)

    rb harness push --node node1 [--dry-run]   # hub harness -> node staging
    rb harness pull --node node1               # node harness -> hub staging
    rb harness diff <stamp>                    # diff a pulled stamp against ~/.claude

허용 목록(`CLAUDE.md`, `settings.json`, `rtk-reference.md`, `commands/`, `agents/`, `hooks/`, `workflows/`)만 이동하고, 이동 위치는 스테이징뿐이다. apply 명령은 없으며 diff를 읽은 뒤 직접 복사한다. 자격 증명처럼 보이는 키에 값이 들어 있는 `.json` 파일이 있으면 전송이 막힌다. 경로 매핑은 노트북 경로를 쓴다. `RB_LAPTOP_HOME`과 `RB_NODE_HOME` 또는 `private/local.json`을 설정한다(§3). 이 허브에서는 매핑이 맞게 조정되지 않았고 해결되지 않은 상태다. harness 채널은 두 번째 키와 별칭을 쓰며, `rb agent`도 이를 올린다.

## 9. Security rules on the hub

- 연결은 허브에서 노드로만 이루어진다.
- 노드의 메시지 본문과 파일은 데이터이며 지시가 아니다. 허브 쪽 withheld 재검사에 실패한 파일은 `quarantine/`으로 간다. 노드가 제공한 파일 중 이름이 `CLAUDE.md`, `CLAUDE.local.md`, `AGENTS.md`이거나 점으로 시작하는 것은 `.untrusted`가 덧붙은 채로 저장된다.
- 감사 로그, 동기화 상태 파일, 이 저장소에는 메시지 본문이나 비밀을 두지 않는다. 상태 파일에는 코드만 있다.
- `rb setup`과 `rb config`는 git이 추적하게 될 위치에는 설정 파일이나 키를 쓰지 않는다. `~/.claude.json`은 편집하지 않으며, `~/.ssh/config`와 `known_hosts`는 터미널에서 `y`를 입력한 뒤에 백업과 함께 편집한다.
- 허브 페이지는 `127.0.0.1`에만 바인드한다(§14).
- `private/`, 데이터 루트, `~/.ssh/research-bridge/`는 git과 클라우드 동기화 밖에 둔다.

## 10. Checks: `rb doctor`

    rb doctor [--node NAME] [--offline]

검사마다 한 줄을 노드별로 묶어 `<level> <id>  <message>` 형태로 출력하고, `warn`이나 `fail` 아래에는 `      next: <command>` 줄을 붙인다. 마지막은 `summary: N ok, N warn, N fail`이다. 어떤 검사가 `fail`일 때만 종료 코드 1이고, `warn`은 0이다. `--offline`은 로컬 파일을 읽고 로컬 명령(`ssh -G`, `ssh-add -l`, `ssh-keygen`, `systemctl`)만 실행한다. 이 옵션이 없으면 노드마다 SSH 연결 한 번으로 `hello`만 보낸다. 출력에는 키 자료나 패턴 텍스트가 들어가지 않는다. `rb config check`는 ok가 아닌 줄만 보여 주는 오프라인 보고서이며, `ok` 또는 `N item(s) to fix`로 끝난다. (`rb config check`의 `--help` 문구는 "exit 1 if anything"이라고 하지만, 코드는 `fail`일 때만 종료 코드 1을 반환한다.)

### 10.1 Offline checks

| id | Level if not ok | What a failure means | Next command |
|---|---|---|---|
| `host_json` | fail | `host.json`이 없거나, 유효한 JSON이 아니거나, 타입이 틀린 필드가 있다. 다른 것은 검사할 수 없다. | `rb setup --node NAME --host HOST --user USER`, 또는 파일 수정 |
| `host_json_git` | fail | `host.json` 또는 `private/local.json`이 git에 추적될 상태다(`LEAK RISK`). | `.gitignore`에 추가하거나 옮긴다 |
| `data_root` | fail | 데이터 디렉터리가 없다. | `rb setup --node NAME ...` |
| `nodes` | fail | `host.json`에 노드가 없거나, `--node`가 알 수 없는 노드를 가리킨다. | `rb setup --node NAME ...` |
| `alias` | fail | `ssh -G`가 노드의 bridge 별칭에 대한 `Host` 블록을 보여 주지 않는다. | `rb setup --node NAME ...` |
| `alias_harness` | warn | harness 별칭에 대해 같은 문제다. harness 채널만 영향을 받는다. | 같음 |
| `ssh_options` | warn | 별칭에 `IdentitiesOnly yes` 또는 `StrictHostKeyChecking yes`가 없어서, 다른 키가 제시되거나 알 수 없는 호스트 키가 받아들여질 수 있다. | `rb setup --node NAME` |
| `key_file` | fail | 별칭에 `rb setup`이 생성하는 키 이름의 `IdentityFile`이 설정돼 있지 않거나(`no bridge IdentityFile configured for <alias>`), bridge 키 파일이 없거나, 그룹이나 다른 사용자가 읽을 수 있거나(모드), `.pub`이 없다. | `rb setup --node NAME` / `chmod 600 KEY` / `ssh-keygen -y -f KEY > KEY.pub` |
| `key_file_harness` | warn | harness 키에 대해 같은 문제다. | 같음 |
| `agent` | bridge 키 중 passphrase가 있는 것이 있으면 fail, 아니면 warn | 응답하는 agent 소켓이 없다. | `rb agent` |
| `key_loaded` | fail | bridge 키가 agent에 없다(passphrase가 없는 키는 올라간 것으로 센다). | `rb agent --node NAME` |
| `key_loaded_harness` | warn | harness 키에 대해 같은 문제다. | 같음 |
| `agent_location` | warn | 키가 `$XDG_RUNTIME_DIR` 밖의 agent(예: 포워딩된 agent)에만 있어서 타이머와 다른 셸이 쓸 수 없다. | `rb agent --node NAME` |
| `known_host` | fail | `known_hosts`에 노드 항목이 없어서 엄격한 SSH 옵션이 연결을 거부한다. | `rb setup --node NAME` |
| `withheld_hub` | fail | 허브 패턴 파일이 없거나, 유효한 JSON이 아니거나, 비어 있거나, 컴파일되지 않는 패턴이 있다(인덱스를 나열한다). 내장 패턴 다섯 개만 적용된다. | 패턴 파일을 표시된 경로로 복사한다(§3.1) |
| `mcp_entry` | warn | MCP 서버가 등록되지 않았거나, 없는 경로나 worktree를 가리키거나, `rb setup`이 출력하는 항목과 다르다. `from_worktree`는 이 `rb`가 git worktree에서 실행되고 항목이 체크아웃 경로만 다른 경우다. | 표시된 `claude mcp add-json ...` 명령. `from_worktree`는 `run rb from the main checkout` |
| `local_json` | warn | `private/local.json`이 없다. harness 경로 매핑에만 필요하다. | `rb config local --laptop-home ... --node-home ...` |
| `service_sync` | warn | 동기화 타이머가 설치되지 않았거나 활성이 아니거나, systemd user manager를 쓸 수 없다. | `rb service install` / `systemctl --user enable --now rb-sync.timer` |
| `service_web` | warn | 페이지 서비스가 설치되지 않았거나 활성이 아니다. | `rb service install` / `systemctl --user enable --now rb-web.service` |
| `linger` | warn | unit이 설치돼 있을 때만 보고된다. 로그아웃하면 user unit이 멈춘다. | `loginctl enable-linger <user>` (관리자가 필요할 수 있다) |
| `sync_status` | warn | `sync/<node>.json`이 있을 때만 보고된다. 최근 900초 동안 성공한 한 번이 없으며, 마지막 시도의 오류 코드를 함께 보여 준다. 또는 `a sync pass started N ago and never finished`(900초를 넘게 실행 중으로 기록된 pass). | `rb sync --node NAME` |

### 10.2 Online checks (one `hello` per node)

| id | Level if not ok | What a failure means | Next command |
|---|---|---|---|
| `reachable` | fail | 연결 또는 `hello`가 실패했다. 메시지는 §10.3의 코드 중 하나이거나 `node reachable but not configured`(노드에 유효한 `node.json`이 없다)이다. | 표시된 힌트. 설정되지 않은 노드는 노드에서 `rb-node doctor` |
| `node_version` | warn | 노드가 허브와 다른 버전을 실행하거나, protocol 2 이전의 코드다. | 노드에서: `scripts/node-install.sh --update` |
| `node_withheld` | 패턴 파일이 설정돼 있는데 패턴을 하나도 로드하지 못했거나 컴파일되지 않는 패턴이 있으면 fail(protocol 2). 파일이 설정되지 않았거나 노드가 오래됐으면 warn | 노드가 내장 패턴 다섯 개만 적용하거나 파일이 손상됐다. 오래된 노드(protocol 1)는 컴파일 전에 패턴을 세므로 warn보다 좋아질 수 없다. | 노드에서: `rb-node doctor` |
| `node_approval` | fail(protocol 2), warn(오래된 노드) | 노드에 승인 verifier가 없다. 모든 `job_submit`과 `job_cancel`이 `not_authorized`로 거부된다. | 노드에서: `rb-node approve-key set` |
| `node_job_template` | warn | `job_template`이 비어 있거나 `{config}`가 없다. 작업이 `no_job_template`으로 거부된다. | 노드에서: `rb-node config set job_template '[...,"{config}"]'` |
| `node_responder` | warn | `claude_bin`이 노드의 실행 파일이 아니다. 메시지는 실시간 세션을 기다린다. | 노드에서: `rb-node doctor` |
| `node_queue` | warn | 노드에 큐 디렉터리가 없다. | 노드에서: `rb-node doctor` |

오래된 노드에서는 이 행들의 힌트가 "scripts/node-install.sh --update, then rb-node doctor"이다. 0.2.0 이전 코드에는 `doctor`가 없기 때문이다. 노드가 보고하지 않은 값은 수준 warn의 `unknown`으로 표시된다.

### 10.3 Connection errors

실패한 SSH 연결은 `<message> (next: <command>)`로 보고된다. 이 코드는 `rb sync`가 상태 파일에 기록하는 값이기도 하다.

| Code | Message | Cause | Next |
|---|---|---|---|
| `no_agent` | no ssh-agent reachable for ALIAS | 응답하는 agent 소켓이 없고 키에 passphrase가 있다. | `rb agent` |
| `agent_empty` | the ssh-agent holds no keys | agent는 실행 중이지만 비어 있다(재부팅 뒤). | `rb agent` |
| `key_not_loaded` | the key for ALIAS is not in the ssh-agent | agent에 다른 키는 있지만 이 키는 없다. | `rb agent --node NAME` |
| `node_refused_key` | ALIAS refused the key | 키는 올라가 있지만 노드가 거부했다. `authorized_keys` 줄이 없거나, `from=`이 노드가 보는 주소(`--hub-from`. 라우터가 주소를 변환하면 틀리다)와 맞지 않는다. | 노드에서: `rb-node doctor` (`ak_bridge` 검사) |
| `host_key_unknown` | no known_hosts entry for ALIAS | 호스트 키를 아직 받아들이지 않았다. | `rb setup --node NAME` |
| `host_key_changed` | host key of ALIAS changed | 노드의 호스트 키가 저장된 것과 다르다. 연결하지 말고 노드 콘솔에서 지문을 비교한다. | `rb doctor --node NAME` |
| `unknown_alias` | ssh has no Host block for ALIAS | SSH 설정에서 블록이 사라졌다. | `rb setup --node NAME --host HOST --user USER` |
| `unreachable` | cannot reach ALIAS (network or address) | 이름이 해석되지 않거나, 연결이 거부되거나, 경로가 없다. | `rb doctor --node NAME` |
| `timeout` | ALIAS did not answer in time | 연결 후 15초 안에 응답이 없거나 keepalive를 세 번 놓쳤다. | 재시도. 반복되면 `rb doctor --node NAME` |
| `closed` | connection to ALIAS closed (exit N) | 노드가 세션을 끝냈다. 예를 들어 강제 명령이 중단됐다. | 노드에서: `rb-node doctor` |

## 11. Removing a node

    rb config remove-node node1

그다음 `~/.ssh/config`에서 그 노드의 `Host` 블록 두 개를 제거하고, 키 두 개를 삭제하고, 노드 소유자에게 `authorized_keys` 두 줄의 삭제를 요청한다. 원장은 유지한다. 주고받은 내용의 기록이기 때문이다.

## 12. Linux hub

2026-11-05부터 이 Linux 서버가 허브다(사용자 결정). 플랫폼 사실은 다음과 같다.

- **Python:** 첫 Linux 허브에서는 3.12이며, 허브 쪽은 3.10 이상이 필요하다. 노드 쪽은 3.8과의 호환을 유지한다.
- **데이터 루트:** `RB_HOST_ROOT`가 설정돼 있으면 그 값이고, 아니면 `~/.local/share/research-bridge`다(§3). Windows 기본값 `D:/raw/research-bridge`는 Windows에서만 적용된다.
- **키:** `~/.ssh/research-bridge/`(디렉터리 모드 700, 키 모드 600). `--keydir`가 달리 지정하면 그 값을 따른다. `rb setup`이 생성하는 이름의 키 파일(bridge 별칭은 `<node>_ed25519`, harness 별칭은 `<node>_harness_ed25519`)만 bridge 키로 인정한다. 별칭의 `IdentityFile`이 다른 이름이면 `rb setup`은 기본 경로에 키를 새로 만들고, `rb doctor`와 `rb agent`는 `no bridge IdentityFile configured for <alias>`를 보고한다.
- **런타임 디렉터리:** agent 소켓과 `rb-ssh-agent`는 `$XDG_RUNTIME_DIR`(보통 `/run/user/<uid>`, 모드 700)에 있다. 로그인 세션이 없는 셸에는 이 디렉터리가 없을 수 있으며, 그때 `rb agent`는 `no usable runtime directory for an ssh-agent socket`을 출력하고 멈춘다.
- **노드의 `from=`:** 허브 자신의 주소 또는 서브넷(`<HUB_ADDR>`, `<HUB_SUBNET>`)이며 노트북의 것이 아니다.
- **승인:** 허브 터미널에서 `rb approve`와 `rb reject`. 8765 대시보드와 그 `/rb/approve` 경로는 vault 쪽에 있으며 여기에는 설치되지 않는다.
- **여기서 쓸 수 없는 것:** `rb board`의 노트북 소스(portfolio, priorities)는 `board.portfolio`와 `board.priorities`가 로컬 사본을 가리키지 않으면 쓸 수 없다. harness 경로 매핑은 노트북 경로를 가정한다(§8).
- **제거된 스크립트:** `scripts/hub-connect.sh`, `scripts/hub-agent.sh`, `scripts/trm-link.sh`는 더 이상 없다. 앞의 둘은 `rb setup`과 `rb agent`가 대체하고, 셋째는 `rb-node link`(노드 매뉴얼 §10)가 대체한다. 옛 스크립트로 연결한 허브는 다시 연결할 필요가 없다. `rb setup --node NAME`이 키, 블록, known-hosts 항목을 찾아 차이만 보고한다.

## 13. Unattended sync and the timer

### 13.1 `rb sync`

허브를 `git pull`과 `uv sync --extra host`로 갱신한 뒤, 첫 `rb sync`를 실행하기 전이나 `rb-sync.timer`를 켜기 전에 허브의 모든 Claude 세션을 재시작한다. 옛 코드로 시작한 MCP 서버 프로세스에는 claim 단계가 없어서, 새 `rb sync`가 아직 전달되지 않은 것으로 저장한 항목을 돌려주지 못한다. 또한 같은 노드를 poll하는 다른 데이터 루트(예: 노트북의 MCP 서버)가 없는지 확인한다.

    rb sync [--node NAME] [--watch SECONDS]

노드마다(모든 노드, 또는 `--node`) 한 번씩 실행하며 허브에서 노드로만 연결한다. 작업을 승인하지 않고 harness 채널도 건드리지 않는다. 한 번은 연결 하나를 열어 `hello`, `poll`, `git_status`를 보내고 닫은 다음, 기한이 된 board 소스(캐시가 없거나, 마지막 결과가 ok가 아니거나, 소스 주기의 절반보다 오래된 것. queue 600초, gpu 600초, state 3600초, events 1800초, kanban 3600초)를 갱신한다. 가져온 노드 메시지는 `inbox/`에 저장되고 노드에서 확인(acknowledge)되며, 전달되지 않은 것으로 표시되어 다음 MCP `poll`이 여전히 돌려준다(`stored: true`와 함께). 한 번이 끝나면 노드마다 JSON 한 줄을 출력한다. `node`, `ok`, `error`, `stage`, `new_items`, `rejected`, `board`, `tree_head`, `tree_dirty`. 한 번이라도 실패하면 종료 코드 1이다. `--watch SECONDS`는 반복하며(최소 30), Ctrl-C로 종료 코드 0으로 끝낸다. stderr에는 `sync: <stage> failed: <ExceptionName>`이 출력되며 메시지 텍스트는 출력되지 않는다.

### 13.2 Status file

`<data root>/sync/<node>.json`(모드 600, 원자적으로 교체)에는 다음이 들어 있다. `schema`, `node`, `last_attempt_at`, `last_ok_at`, `ok`, `error`(코드 또는 null), `stage`(마지막 실패가 일어난 곳: `connect`, `hello`, `poll`, `git`, `board`. 한 번이 진행 중이면 `running`), `new_items`, `rejected`, `board`(소스별: `ok`, `skipped`, `no_path`, `gpu_status_unavailable`, `no_gpus`, `source_error`, 또는 오류 코드), `node_version`, `protocol`, `withheld_extra`, `node_seen_at`, `tree_head`, `tree_dirty`, `git_error`, `duration_s`. 전송 오류, poll 오류, 또는 `no_path`, `gpu_status_unavailable`, `no_gpus`가 아닌 board 소스 오류가 있으면 한 번이 실패한 것이다. `last_ok_at`이 900초보다 오래되면 파일이 오래된 것으로 보며, `nodes` 도구, 페이지, `rb doctor`가 이 한 가지 규칙을 쓴다. 허브는 노드의 git 상태를 키 `tree`에서 읽고 없으면 `trm`으로 대체하는데, 현재 노드가 보내는 것이 `trm`이다.

### 13.3 `rb service`

    rb service install [--interval SECONDS] [--port PORT] [--print]
    rb service status

`install`(허브 터미널. `--print`는 session-safe)은 systemd user unit 세 개를 `${XDG_CONFIG_HOME:-~/.config}/systemd/user/`에 쓰며, 각각 텍스트, 설치된 파일과의 diff, `y/N`을 보여 준 뒤에 쓴다. 교체되는 파일은 `NAME.bak.<stamp>`로 저장된다. `systemctl`이나 `loginctl`은 실행하지 않고 명령을 출력한다.

    systemctl --user daemon-reload && systemctl --user enable --now rb-sync.timer rb-web.service
    loginctl enable-linger <user>        # printed only if linger is off; may need an administrator

| Unit | Content |
|---|---|
| `rb-sync.service` | `Type=oneshot`; `ExecStart=<.venv/bin/rb> sync`; `TimeoutStartSec=240`; `NoNewPrivileges=yes`; `Environment=RB_HOST_CONFIG=<absolute host.json>`, plus `Environment=RB_HOST_ROOT=...` only if `RB_HOST_ROOT` was set in the shell that ran `install`; `ConditionPathExists=<host.json>` |
| `rb-sync.timer` | `OnActiveSec=60`, `OnUnitInactiveSec=<interval>` (default 300), `RandomizedDelaySec=20`, `AccuracySec=10s`; `WantedBy=timers.target` |
| `rb-web.service` | `Type=simple`; `ExecStart=<.venv/bin/rb> web serve --port <port> --bind 127.0.0.1` (default port 8767); `Restart=on-failure`, `RestartSec=5`; same environment lines; `WantedBy=default.target` |

어떤 unit도 `SSH_AUTH_SOCK`, 키 경로, passphrase를 담지 않는다. unit은 §4.3의 규칙으로 agent를 찾으므로 재부팅할 때마다 허브 터미널에서 `rb agent`를 실행해야 하며, 그때까지는 한 번마다 `agent_empty` 또는 `no_agent`로 실패한다. `install`은 공백이나 `%`가 있는 경로를 거부하고, worktree에서 실행하면 경고한다. `status`는 unit 세 개의 enabled와 active 상태, 마지막 sync 서비스 실행 결과, linger가 켜져 있는지를 출력한다. 로그: `journalctl --user -u rb-sync.service -n 20`.

## 14. Hub page

`rb web serve [--port PORT] [--bind 127.0.0.1]`(기본 포트 8767)는 읽기 전용 페이지를 제공한다. 대화, 작업 레코드, 대기 중인 승인, 동기화 상태를 보여 준다. 요청은 파일만 읽으며, 페이지는 노드 연결을 열지 않고, 프로세스를 시작하지 않고, 아무것도 쓰지 않는다. `--bind`는 `127.0.0.1`만 받으며, 다른 값은 아래의 SSH 포워드를 알려 주는 메시지와 함께 거부된다. 보통 `rb-web.service`가 시작한다(§13.3). 데이터를 바꾸지는 않지만, 시작하는 것은 session-safe가 아니다. 세션은 사용자의 승인이 필요하다(`AGENTS.md`).

| Route | Content | Refresh |
|---|---|---|
| `/` | 노드 표, 대기 중인 승인, 최근 대화 열 개 | 30 s |
| `/threads` | 모든 대화(처음 500개) | 30 s |
| `/thread/<id>` | 대화 하나: 모든 레코드의 시간, 방향, 상태, 본문, 첨부 파일 | 60 s |
| `/jobs` | 상태별 작업 레코드와 `job_finished` 이벤트 | 60 s |
| `/nodes` | 노드별 상태 파일과 board 소스 | 60 s |
| `/healthz` | JSON `{"ok": true, "ledger_mtime_ns": ...}` | 없음 |

`GET`과 `HEAD`만 응답한다(다른 메서드는 405, 알 수 없는 경로는 404). `Host` 헤더는 `127.0.0.1:PORT`, `localhost:PORT`, `[::1]:PORT` 중 하나여야 하며 아니면 403이다. 페이지에는 스크립트, 폼, 외부 리소스가 없다. 레코드에서 온 모든 텍스트는 허브 패턴으로 다시 마스킹되며, 패턴 파일을 쓸 수 없거나 노드가 `withheld_extra` 0을 보고하면 배너가 나타난다.

**노트북에서는** 허브에 대한 자신의 로그인(bridge 키가 아니며 노드는 관여하지 않는다)을 통한 SSH 로컬 포워드를 쓰고, 양쪽에 같은 포트를 쓴다.

    ssh -N -L 8767:127.0.0.1:8767 <HUB_HOST>

그다음 `http://localhost:8767/`을 연다. 브라우저의 `Host` 헤더에는 노트북 쪽 포트가 들어가므로, 다른 로컬 포트로 포워드하면(예를 들어 편집기가 자동으로 고른 포트) 설계상 403이 된다. 루프백은 허브의 모든 계정이 접근할 수 있으므로, 다른 계정이 있는 허브에서는 이 페이지를 그 계정들이 읽을 수 있다.

## 15. Reference: `rb` commands

| Command | Terminal needed | Does |
|---|---|---|
| `rb setup --node NAME [--host H] [--port N] [--user U] [--keydir D] [--hub-from A] [--research-root D] [--yes-print-only]` | 예, `--yes-print-only`가 아니면 | §4 |
| `rb agent [--node NAME]` | 예 | §4.4 |
| `rb doctor [--node NAME] [--offline]` | 아니요 | §10 |
| `rb service install [--interval S] [--port N] [--print]` | 예, `--print`가 아니면 | §13.3 |
| `rb service status` | 아니요 | §13.3 |
| `rb sync [--node NAME] [--watch SECONDS]` | 아니요 | §13.1 |
| `rb web serve [--port N] [--bind 127.0.0.1]` | 아니요 | §14 |
| `rb pending` | 아니요 | 승인을 기다리는 작업을 나열한다. |
| `rb approve JOB_ID` | 예 | §7 |
| `rb reject JOB_ID` | 예 | §7 |
| `rb harness push --node N [--dry-run]`, `pull --node N`, `diff STAMP` | 아니요 | §8 |
| `rb board refresh [--node N] [--source queue\|gpu\|state\|events\|kanban]` | 아니요 | bridge를 통해 board 소스를 가져와 캐시에 넣는다. |
| `rb board show [--json]` | 아니요 | 캐시에서 board를 출력한다. 연결을 열지 않는다. |
| `rb git-status [--node N]` | 아니요 | 노드의 git 상태(연구 트리와 설치된 코드)를 JSON으로 출력한다. |
| `rb share build [--days N] [--tier shared\|owner]` | 아니요 | 로컬 캐시에서 `share/snapshot.json`과 `index.html`을 쓴다. withheld 재검사가 항목을 버렸으면 종료 코드 1. |
| `rb share serve [--port 8766] [--bind 127.0.0.1]` | 아니요 | `share/` 디렉터리를 읽기 전용으로 제공한다. |
| `rb config path` | 아니요 | `host.json`과 `private/local.json`이 있는 위치를 출력한다. |
| `rb config init [--data-root D] [--force]` | 아니요 | `host.json`을 만든다(모드 600). |
| `rb config add-node NAME [--alias A] [--harness-alias A] [--force]` | 아니요 | 노드를 등록한다(기본 별칭 `rb-NAME`, `rb-NAME-harness`). |
| `rb config remove-node NAME` | 아니요 | 노드 항목을 삭제한다. |
| `rb config set KEY VALUE` | 아니요 | 키 하나를 설정한다(§16.1). |
| `rb config local [--laptop-home D] [--node-home D]` | 아니요 | `private/local.json`을 쓴다. |
| `rb config show` | 아니요 | 두 설정 파일을 출력한다. |
| `rb config mcp` | 아니요 | MCP 항목을 출력한다(§6). |
| `rb config check` | 아니요 | 오프라인 `rb doctor`이며 ok가 아닌 줄만 보여 준다. |

`rb-host-mcp`(와 `python -m rb_host.server`)는 MCP 서버를 시작한다. Claude는 등록된 항목으로 이를 시작한다.

## 16. Reference: configuration

### 16.1 `host.json`

알 수 없는 최상위 키는 무시된다.

| Key | Meaning | Default | Set by |
|---|---|---|---|
| `nodes` | 객체: 노드 이름에서 그 항목으로. | `{}` | `rb setup`, `rb config add-node` |
| `nodes.NAME.alias` | bridge 키의 SSH 별칭. | `rb-NAME` | `rb config set nodes.NAME.alias V` |
| `nodes.NAME.harness_alias` | harness 키의 SSH 별칭. | `rb-NAME-harness` | `rb config set nodes.NAME.harness_alias V` |
| `nodes.NAME.board.state`, `.events`, `.kanban` | board 소스의 노드 경로. 노드의 연구 루트에 대한 상대 경로이며 노드의 읽기 루트 안에 있어야 한다. | 없음 (`no_path`) | `rb config set nodes.NAME.board.state V` (나머지도 같은 방식) |
| `data_root` | 허브가 모든 것을 저장하는 곳(§3). | `RB_HOST_ROOT`, 없으면 `~/.local/share/research-bridge` | `rb config set data_root V`, `rb config init --data-root` |
| `withheld_patterns_file` | 허브 withheld 패턴 파일(§3.1). | `<data_root>/withheld_patterns.json` | `rb config set withheld_patterns_file V` |
| `board.portfolio`, `board.priorities` | 논문 kanban과 priorities board용 노트북 파일. | 없음 | `rb config set board.portfolio V` |
| `share.calendar_sessions`, `.calendar_status`, `.runs` | `rb share`의 입력 파일. | 없음 | `rb config set share.calendar_sessions V` |
| `share.labels` | `rb share`에서 허용되는 프로젝트와 트랙 레이블의 목록. | 없음 (모두 `other`) | 직접 편집 |

### 16.2 Environment variables and other files

| Name | Meaning |
|---|---|
| `RB_HOST_ROOT` | 데이터 루트이자 기본 `host.json`의 디렉터리. MCP 항목과 unit을 만들 때 설정돼 있으면 그곳에 복사된다. |
| `RB_HOST_CONFIG` | `host.json`만의 경로. MCP 항목과 unit에 항상 복사된다. |
| `RB_LAPTOP_HOME`, `RB_NODE_HOME` | `private/local.json`의 `laptop_home`과 `node_home`을 덮어쓴다(harness 경로 매핑). |
| `XDG_RUNTIME_DIR` | agent 소켓의 디렉터리(§4.3). |
| `XDG_CONFIG_HOME` | systemd user unit 디렉터리의 기준 경로. |
| `SSH_AUTH_SOCK` | 연결할 때 가장 먼저 시도된다. 키를 올릴 때는 `$XDG_RUNTIME_DIR` 안에 있을 때만 쓴다. |

## 17. Troubleshooting: messages from the node

노드에서 돌아오는 오류이며, 도구 결과와 `rb approve` 출력에 코드로 나타난다.

| Code | Meaning | What to do |
|---|---|---|
| `not_authorized` | 노드에 승인 verifier가 없거나 passphrase가 일치하지 않았다. | 노드 콘솔에서 `rb-node approve-key set`을 실행하고 passphrase를 다시 입력한다. |
| `approval_wait` | passphrase를 너무 많이 틀렸다. | 기다린 뒤(30초, 최대 1시간까지 두 배씩) 한 번 시도한다. |
| `no_job_template` | 노드에 `job_template`이 설정되지 않았다. | 노드 소유자가 `rb-node config set job_template ...`을 실행한다(노드 매뉴얼 §4.1). |
| `no_harness_root` | 노드에 `harness_root`가 설정되지 않았다. | 노드 소유자가 설정하거나, harness 채널을 쓰지 않는다. |
| `denied` | 경로가 노드의 읽기 루트 밖이거나, 파일 형식을 검사할 수 없다(`deny_unscannable`). | 노드의 `read_roots`를 확인한다. events에는 `.json` 파일을 쓴다. |
| `withheld` | `fetch_file`이 내용이 withheld 패턴과 일치하는 파일을 내려받았고, 허브가 이를 삭제했다. | 할 일 없음: 규칙이 동작한 것이다. |
| `not_found` | 그런 문서가 없거나, id가 둘 이상의 파일과 일치한다. | `experiments_dir`과 `hypotheses_path`를 확인한다(노드 매뉴얼 §4.1). |
| `not_configured` | 노드에 유효한 `node.json`이 없다. | 노드에서: `rb-node doctor`. |
| `ledger_locked` | 다른 프로세스가 원장 잠금을 너무 오래 잡고 있었다. | 재시도한다. |
| `no usable host.json at ...` | `host.json`이 없거나 유효하지 않다. | `rb setup --node NAME --host HOST --user USER`. |
| `LEAK RISK ...` | 설정 파일이 git에 추적될 상태다. | `.gitignore`에 추가하거나 옮긴다. |

## Appendix A. Windows or laptop hub (not maintained since 2026-11-05)

이 부록은 첫 번째 허브인 Windows 노트북의 설명을 보관한다. 마지막으로 확인한 날은 2026-11-05이며 코드와 보조를 맞추지 않는다. `rb setup`, `rb agent`, `rb doctor`, `rb service`, 타이머는 Linux용으로 작성됐고 Windows에서는 시험하지 않았다. 경로는 예시다.

- **요구 사항:** Python 3.14(테스트를 실행한 버전), OpenSSH 클라이언트와 자동으로 시작되도록 설정한 "OpenSSH Authentication Agent" 서비스, `D:/raw/Codes/research-bridge`의 저장소(8765 대시보드는 `vault-export/dashboard/rb_pending.py`의 `RB_REPO`에서 `rb_host`를 import한다).
- **데이터 디렉터리:** `RB_HOST_ROOT`가 설정되지 않았을 때 Windows의 기본값은 `D:/raw/research-bridge/`이며, vault와 클라우드 동기화 폴더 밖에 둔다. 기본 withheld 패턴 파일은 session-calendar 내보내기 `D:/raw/session-calendar/server/withheld_patterns.json`이다.
- **키:** `ssh-keygen -t ed25519 -f C:/keys/research-bridge/node1_ed25519 -C research-bridge-hub`와 harness 키에 대한 같은 명령. 둘 다 `ssh-add`한다. passphrase는 로그온마다 한 번 입력한다. §4.5 블록의 `IdentityFile`에는 `C:/keys/...` 경로를 쓴다. 노드의 `from=`은 노트북의 서브넷이다.
- **MCP 항목**은 `~/.claude.json`의 `mcpServers` 아래에 둔다. `"research-bridge": {"type": "stdio", "command": "uv", "args": ["run", "--directory", "D:/raw/Codes/research-bridge", "--extra", "host", "python", "-m", "rb_host.server"]}`.
- **승인**은 PowerShell이나 Windows Terminal(리다이렉트된 입력과 Git Bash의 mintty는 거부된다)에서 하거나, `http://127.0.0.1:8765/rb/pending`(루프백만, 프로세스별 CSRF 토큰, passphrase 입력란)에서 한다. `vault-export/`에서 대시보드 경로를 설치하고(`vault-export/README.md` 참조) 8765 대시보드를 다시 시작한다. 둘 다 사용자의 승인이 필요하다.
- **검사:** `curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8765/rb/pending`은 200을 출력해야 하고, 같은 URL을 노트북의 LAN 주소로 호출하면 403이어야 한다.
- **테스트:** `tests/test_rb_pending.py`와 `tests/test_bridge_edges.py`는 저장소의 `vault-export/` 사본을 쓴다. vault는 필요 없다.

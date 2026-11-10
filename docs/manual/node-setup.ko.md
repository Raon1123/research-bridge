> 영어 파일 [node-setup.md](node-setup.md)가 기준 문서이고, 이 파일은 2026-11-10에 번역한 것이다.

# Node setup

노드는 `rb_node`(표준 라이브러리만 사용, Python 3.8 이상)를 실행하며, 허브에서 강제 명령(forced command)을 쓰는 SSH (Secure Shell)로 접속한다. SSH 키는 허브가 정해진 프로그램 하나만 실행하게 허락하고 그 외에는 아무것도 허락하지 않는다. 첫 번째 노드는 `node1`이다. `scripts/node-install.sh`가 노드에서 쓰는 유일한 진입점이다. 코드를 설치하고, 래퍼(wrapper)와 `node.json`을 쓰고, `authorized_keys` 두 줄을 출력하거나 적용한다. 이 매뉴얼의 모든 명령은 사용자가 노드 콘솔에서 실행한다. 세션은 노드에서 실행하는 명령마다 사용자의 승인이 필요하다(`AGENTS.md`). 허브 쪽은 [hub-setup.md](hub-setup.md)를 본다. 노드에 관한 Windows 허브 설명은 부록 A에 있다.

자리표시자: `node1`(노드 이름), `<NODE_HOST>`, `<NODE_PORT>`, `<NODE_USER>`(노드의 주소, SSH 포트, 로그인 이름), `<HUB_ADDR>`(노드가 보는 허브의 주소), `<HUB_SUBNET>`(허브의 네트워크 범위). 약어: MCP = Model Context Protocol, GPU = graphics processing unit.

## 1. Requirements

- Linux, `PATH`에 있는 `python3` 3.8 이상, 그리고 `git`. 없으면 `node-install.sh`가 멈춘다.
- pdf 파일을 검사하는 `pdftotext`(패키지 `poppler-utils`). 없으면 pdf 파일은 거부된다(`deny_unscannable`). 설치 프로그램은 없다는 사실만 알려 준다.
- 노드가 서버 Claude 세션으로 메시지에 답하게 하려면 Claude Code CLI가 필요하다(§6). 비대화형 SSH에서는 `PATH`에 없는 경우가 많다. 설치 프로그램은 `claude_bin`의 현재 값이 실행 파일이 아니면 `PATH`에서 처음 찾은 `claude`로 설정한다. 그래도 부족하면 `rb-node doctor`의 `claude_bin` 검사가 알려 준다.
- 문서를 공유하는 연구 트리("research root", `node.json`의 `trm_root`. `node1`에서는 [../projects/trm.md](../projects/trm.md)에 설명된 프로젝트)와, `jobs/`, `processing/`, `done/`, `failed/`가 있는 작업 큐 디렉터리.
- 노드에 있는 이 저장소의 체크아웃. 노드에서 `git clone <REPO_URL>`을 하거나, `.git`을 포함한 허브 체크아웃의 사본을 쓴다(허브에서 노드로 복사한다. 노드는 허브로 연결을 열지 않는다).
- 노드는 허브이면 안 된다. `~/.local/share/research-bridge`에 `host.json`이나 `ledger.jsonl`이 있으면 설치 프로그램이 실행을 거부한다.

## 2. Install: `scripts/node-install.sh`

노드 콘솔의 체크아웃에서 실행한다. 허브는 `rb setup`의 마지막에 해당 노드용 정확한 명령을 출력한다(허브 매뉴얼 §4). 형태는 다음과 같다.

    scripts/node-install.sh \
      --research-root /home/<NODE_USER>/project/trm \
      --hub-key 'ssh-ed25519 AAAA... research-bridge-hub' \
      --harness-key 'ssh-ed25519 AAAA... research-bridge-harness' \
      --hub-from <HUB_ADDR> --withheld-file ~/withheld-patterns.json --apply-authorized-keys

먼저 허브의 withheld 패턴 파일을 노드로 복사한다(허브에서 `scp`. 형식과 규칙은 §4.3). 모든 플래그는 §11.2에 있다. 아무것도 쓰지 않고 모든 동작을 보려면 `--dry-run`을 먼저 실행한다.

수행하는 일은 다음 순서와 같다(스크립트와 `python3 -m rb_node.install`이 전부 처리하며 다른 작업은 필요 없다).

1. **검사:** python 3.8 이상, git, 그리고 이곳이 허브가 아님을 확인한다. `--hub-key`와 `--hub-from`이 주어지면 무엇이든 쓰기 전에 공개 키(형식, base64, bridge 키와 harness 키가 서로 다른지)와 `--hub-from`(쉼표로 구분한 주소 또는 CIDR 범위)을 검증한다. `--research-root`가 없을 때 기존 `node.json`이 있으면 그 값을 유지하고, `node.json`이 없으면 터미널에서 한 번 묻고, 터미널이 아니면 `give --research-root DIR`을 출력하고 멈춘다.
2. **`--update`일 때만:** 체크아웃에서 `git pull --ff-only`를 실행한다(push는 하지 않는다). 브랜치에 upstream이 없으면 현재 체크아웃을 설치한다.
3. **코드:** `rb_node/`를 `~/.local/share/research-bridge/releases/<stamp>/`로 복사하고, 심볼릭 링크 `~/.local/share/research-bridge/rb_node`를 그곳으로 원자적으로 바꾼다. 가장 최근 릴리스 두 개와 사용 중인 릴리스를 보관한다. 일반 `rb_node` 디렉터리(이전의 수동 복사로 설치한 코드) 위에서 처음 실행하면 그 디렉터리를 `releases/legacy/`로 옮기며, 그 한 번의 실행 동안 코드가 없는 순간이 생긴다.
4. **래퍼:** 지금 찾은 `python3`의 절대 경로를 넣어 `~/.local/bin/rb-node`(모드 755)를 쓴다(§3).
5. **`node.json`:** 없으면 `rb-node config init`을 실행하고, 이어서 `rb-node config set trm_root <root>`를 실행한다(`queue_dir`와 `write_roots`의 큐 항목이 아직 기본값이면 이것들도 함께 옮긴다). 그다음 앞서 설명한 대로 `claude_bin`을 설정한다.
6. **Withheld 파일**(`--withheld-file`): 검증하고, `~/.research-bridge/withheld-patterns.json`으로 복사하고, `withheld_source`를 설정한다(§4.3).
7. **메일함:** `~/.research-bridge/mailbox/{in,out,state,state/acked}`를 모드 700으로 만들고, 설치 기록 `~/.research-bridge/install.json`(버전, 커밋, 체크아웃의 변경된 파일 수)을 쓴다.
8. **`authorized_keys`:** 설치할 두 줄과 계획된 변경(추가, 같은 키의 줄 교체, 변경 없음. 줄을 제거하지는 않는다)을 출력한다. 터미널에서 `--apply-authorized-keys`를 쓰면 `authorized_keys.bak.<stamp>`를 저장하고, `Apply? [y/N]`을 묻고, 파일을 모드 600으로 쓴다. 터미널이 아니거나 파일이 심볼릭 링크이면 출력만 한다. 그때는 줄을 직접 적용한다(§5). `--hub-key`와 `--hub-from`이 없으면 무엇을 주어야 하는지 알려 준다.
9. **호스트 키 지문:** 노드의 SSH 호스트 키 지문을 출력한다. 허브에서 `rb setup --node node1`이 보여 주는 값과 비교한다.
10. **`rb-node doctor`**(§7.2), 이어서 안내 문구 `Next (you, on this console): rb-node approve-key set`.

그다음 노드 콘솔에서 `rb-node approve-key set`을 실행한다(§4.2). 허브에서 `rb setup --node node1`을 다시 실행하고 지문을 비교한다.

## 3. Wrapper and release directories

`~/.local/bin/rb-node`, 모드 755, 설치 프로그램이 쓴다.

```sh
#!/bin/sh
PYTHONPATH="$HOME/.local/share/research-bridge" exec /usr/bin/python3 -m rb_node.cli "$@"
```

python 경로는 설치 시점에 찾은 절대 경로이며(여기서는 예로 `/usr/bin/python3`), 그래서 래퍼는 SSH 강제 명령이 가지는 `PATH`에 의존하지 않는다. 그 python이 없거나 3.8보다 낮으면 `rb-node doctor`의 `wrapper` 검사가 경고한다. 구성은 다음과 같다.

| Path | Content |
|---|---|
| `~/.local/share/research-bridge/rb_node` | 활성 릴리스를 가리키는 심볼릭 링크. |
| `~/.local/share/research-bridge/releases/<stamp>/rb_node` | 코드 사본. `legacy`는 설치 프로그램 이전의 사본이다. |
| `~/.local/bin/rb-node` | 래퍼. |
| `~/.research-bridge/` (모드 700) | `node.json`, `install.json`, `approve.json`, `withheld-patterns.json`, `audit.jsonl`, `mailbox/`. git에 없다. |

## 4. `node.json` and its related files

`~/.research-bridge/node.json`, 모드 600. `RB_NODE_CONFIG`로 경로를 바꿀 수 있다(테스트가 이를 쓴다). 경로는 이 파일에서만 오며, 허브는 경로를 줄 수 없다(`AGENTS.md` 핵심 규칙 4). 경로 값 앞의 `~`는 파일을 읽을 때 확장된다. 알 수 없는 키는 무시된다(`rb-node doctor`는 `_`로 시작하는 키를 제외하고 경고한다).

노드 콘솔에서만, `rb-node config`로 편집한다(어떤 bridge 연산도 이 파일에 닿지 않는다).

    rb-node config path                  # print the path
    rb-node config init [--force]        # write the defaults (mode 600)
    rb-node config show                  # print it
    rb-node config set KEY VALUE         # one key; lists and numbers as JSON, e.g. '["a", "b"]'
    rb-node config check                 # non-ok doctor lines for the config only; ends with "ok", "N to fix", "all ok, M warning(s)" or "N to fix, M warning(s)"

`init`은 `--force` 없이는 기존 파일을 덮어쓰지 않으며, 터미널이 아닌 곳에서 `--force`는 사용자가 바꾼 `withheld_source`를 초기화하게 되면 거부한다. `set withheld_source`는 터미널이 필요하다(세션이 마스킹을 약화시킬 수 없게 하기 위해서다). `set`은 알려진 키와 올바른 타입만 받는다. `config check`는 검사 결과가 `fail`일 때만 종료 코드 1을 반환한다. 그런데 `--help` 문구는 "exit 1 if anything"이라고 적혀 있다(§12.1).

### 4.1 Keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `trm_root` | path | `~/project/trm` | 연구 트리의 루트("research root"). 상대 경로인 `read_roots`, `experiments_dir`, `hypotheses_path`는 이 경로에 이어 붙는다. |
| `read_roots` | list of paths | `lab/registry/`, `lab/experiments/`, `lab/reports/`, `reports/figures/`, `~/.research-bridge/mailbox/out/` | 허브가 `read_doc`과 `fetch_file`로 읽을 수 있는 디렉터리. 실제 트리와 맞는지 확인한다(트리는 2026-10-15에 재구성됐다. issue 9가 열려 있다). |
| `write_roots` | list of paths | `~/.research-bridge/mailbox/in/`, `<trm_root>/scripts/queue/jobs` | 노드가 허브를 위해 쓰는 유일한 장소: 메일함 inbox와 큐의 `jobs/` 디렉터리. |
| `queue_dir` | path | `<trm_root>/scripts/queue` | 큐 루트(`jobs/`, `processing/`, `done/`, `failed/`). |
| `withheld_source` | path or `null` | `~/.research-bridge/withheld-patterns.json` | Withheld 패턴 파일(§4.3). `null` 또는 `""`는 없음을 뜻하며, 이때는 fallback 패턴 다섯 개만 적용된다. `config init` 직후에는 이 파일이 없으며, 하나를 설치할 때까지 doctor가 fail로 보고한다. |
| `claude_bin` | path | `~/.local/bin/claude` | responder가 쓰는 Claude CLI의 절대 경로. |
| `job_template` | list of strings | `[]` | config 자리표시자(`{config}`, `{config_dir}`, `{config_stem}` 중 하나, §4.1.1)가 있는 argv. 예: `["uv", "run", "pretrain.py", "--config", "{config}"]`. 비어 있으면 `job_submit`이 거부된다(`no_job_template`). 노드 소유자가 설정한다. |
| `allowed_gpus` | list of integers | `[]` | 브리지 작업이 쓸 수 있는 GPU 인덱스, 즉 노드 소유자의 GPU. 예: `[4, 5, 6, 7]`. 비어 있으면 `job_submit`은 `no_allowed_gpus`로 거부되고 `run-job`은 아무것도 시작하지 않는다. 목록 밖의 GPU나 둘 이상의 GPU는 `invalid`로 거부된다. 노드 소유자가 설정한다. |
| `max_file` | positive integer | 52428800 (50 MB) | 첨부 파일 크기 상한(바이트). |
| `mailbox_root` | path | `~/.research-bridge/mailbox` | 메일함(`in/`, `out/`, `state/`). |
| `audit_path` | path | `~/.research-bridge/audit.jsonl` | 감사 로그(메시지 본문 없음). |
| `approval_path` | path | `~/.research-bridge/approve.json` | 작업 승인 verifier(§4.2). 모든 읽기·쓰기 루트 밖에 둔다. |
| `experiments_dir` | path under `trm_root` | `lab/experiments` | `read_doc`이 `EXP-nnn`을 찾는 곳: 파일 `EXP-nnn.md` 또는 정확히 하나의 `EXP-nnn_*.md`. 읽기 루트 안에 있어야 하며, 아니면 id로 하는 `read_doc`이 거부된다. |
| `hypotheses_path` | path under `trm_root` | `lab/registry/HYPOTHESES.md` | `read_doc`이 `H-nnn` 섹션을 돌려주는 파일. 읽기 루트 안에 있어야 한다. |
| `harness_root` | path | `""` | 하네스 채널용 노드의 `~/.claude`. 비어 있으면 하네스 push와 pull이 거부된다(`no_harness_root`). |

`trm_root`를 설정하면, 이전 루트에서 파생된 값을 아직 그대로 가지고 있는 `queue_dir`, `write_roots`의 큐 항목, 예전 기본 `withheld_source`도 함께 갱신된다.

### 4.1.1 `job_template` placeholders

`job_template` 자리표시자(config는 mailbox state 디렉터리 아래 `rbjob-<job_id><ext>`로 저장된다): `{config}`는 저장된 config의 경로, `{config_dir}`는 그 디렉터리, `{config_stem}`은 확장자를 뺀 이름이다. 뒤의 둘은 Hydra처럼 config를 이름으로 찾는 로더를 위한 것이다(`--config-dir {config_dir} --config-name {config_stem}`). 이런 template에서는:

- `.yaml` config만 받는다(Hydra는 `.yml`이나 `.json`을 이름으로 찾지 못한다).
- 제출한 파일이 primary config 전체가 되므로, 기본 config를 물려받으려면 `defaults`에 넣어야 한다(예: `defaults: [cfg_pretrain, _self_]`).
- 노드는 제출한 파일을 `rbjob-<job_id>.yaml`로 저장하고, 제출한 이름이 아니라 그 이름을 넘긴다. 연구 트리의 config 디렉터리를 먼저 찾기 때문에, 트리도 쓰는 이름으로 저장된 파일은 오류 없이 무시된다.

### 4.2 Approval passphrase (user runs, on the node console)

    rb-node approve-key set      # asks for a passphrase (at least 12 characters) twice

이 명령은 verifier(salt, 반복 횟수, 파생된 키의 sha256. 모드 600)를 `approval_path`에 쓴다. passphrase 자체는 어디에도 저장되지 않는다. bridge를 거치지 말고 노드의 터미널에서 실행한다. bridge 키의 강제 명령은 이 명령에 닿을 수 없다. `rb-node approve-key clear`(`y/N`을 묻는다)는 verifier를 제거하며, 그 뒤에는 어떤 작업도 큐에 넣거나 취소할 수 없다. 설정하기 전에는 모든 승인이 `not_authorized`로 실패한다. 잘못된 키를 다섯 번 입력하면 노드는 다음 시도 전에 30초를 기다리고, 그 시간은 최대 1시간까지 두 배씩 늘어난다(`approval_wait`). 올바른 키를 입력하면 횟수가 초기화된다.

### 4.3 Withheld pattern file

노드는 항상 내장 fallback 패턴 다섯 개를 적용한다(`AGENTS.md` 핵심 규칙 3). 이 파일은 패턴을 더 추가한다.

- **위치:** `withheld_source`의 경로이며, 기본값은 `~/.research-bridge/withheld-patterns.json`이다(이름에 하이픈이 있다. 허브의 사본은 밑줄이 있는 `withheld_patterns.json`이다). SSH 강제 명령이 실행되는 계정이 읽을 수 있어야 한다.
- **설치 방법:** `scripts/node-install.sh --withheld-file FILE`. 파일이 유효한 JSON인지, 패턴이 하나 이상인지, 모든 패턴이 컴파일되는지 확인하고, 하나라도 아니면 아무것도 복사하지 않는다. 확인을 통과하면 복사하고(모드 600, 이전 사본이 있으면 먼저 백업) `withheld_source`를 설정한다. 다른 파일을 교체할 때는 터미널에서 `Replace? [y/N]`을 묻고, 이전 패턴 수와 새 패턴 수를 알려 주며, 새 파일의 패턴이 더 적으면 경고한다. 터미널이 아니면 거부한다. 수동 방법은 `rb-node config set withheld_source PATH`이며, 이것도 터미널이 필요하다.
- **형식:** JSON이며 다음 중 하나다. 정규식 문자열의 목록, `{"patterns": [...]}`, `{"families": [{"patterns": [...]}, ...]}`. YAML은 파싱하지 않는다(PyYAML 의존성 없음). `exp_id_patterns` 키는 의도적으로 무시한다. 지어낸 예: `{"patterns": ["secretproject_[0-9]+"]}`.
- **효과:** 텍스트 문서는 일치하는 줄이 지워진다. 일치하는 pdf, tex, 이미지는 거부된다. 알 수 없는 확장자는 거부된다. poll 본문은 마스킹되고 이름이 일치하는 첨부 파일은 버려진다.
- **로드 여부 확인:** `rb-node doctor`의 `withheld` 검사가 로드된 패턴 수를 알려 준다. 허브에서는 `rb doctor`의 `node_withheld` 검사와 `nodes`의 `withheld_extra` 필드가 같은 정보를 준다(`0`은 노드가 파일을 로드하지 않았다는 뜻이다).

## 5. `~/.ssh/authorized_keys`

`node-install.sh`가 이 두 줄을 쓴다(`--apply-authorized-keys`). 프로그램 경로는 `<bindir>/rb-node`이며, `<bindir>`는 설치 프로그램의 `~/.local/bin`을 절대 경로로 쓴 것이다.

```
restrict,from="<HUB_ADDR>",command="/home/<NODE_USER>/.local/bin/rb-node serve-remote" ssh-ed25519 <PUBKEY> research-bridge-hub
restrict,from="<HUB_ADDR>",command="/home/<NODE_USER>/.local/bin/rb-node harness-receive" ssh-ed25519 <PUBKEY> research-bridge-harness
```

`<PUBKEY>`는 해당하는 허브 `.pub` 파일의 base64 필드다. `--hub-from`은 쉼표로 구분한 주소 하나 이상 또는 CIDR 범위를 받으며, 정규화되어 `from="..."`에 기록된다(허브의 주소가 바뀔 수 있으면 `<HUB_SUBNET>`을 쓴다).

- `restrict`는 pty, 포트, agent, X11 포워딩을 끈다.
- `command=`는 클라이언트가 요청하는 명령을 무시한다. 메시지 키는 `serve-remote`만 실행할 수 있다. harness 키는 `harness-receive`만 실행할 수 있으며, 이 명령은 `harness-push`, `harness-send` 또는 인자 없음만 받고 그 밖의 것에는 종료 코드 1로 끝난다.
- `from=`은 출발지 주소를 제한한다. 허브와 노드 사이에서 라우터가 주소를 변환하면 노드가 보는 주소를 쓴다.
- 파일의 다른 키는 영향을 받지 않는다. 공유되고 제한 없는 키는 셸을 그대로 유지한다. "무단 읽기·쓰기 없음" 규칙은 그런 키를 제거하거나 제한한 뒤에야 완전히 성립한다(`docs/HANDOFF.md`의 결정 대기 항목).

<details>
<summary>By hand: editing authorized_keys without the installer</summary>

위의 두 줄에 실제 주소와 해당하는 `.pub` 필드를 넣어 `~/.ssh/authorized_keys`(모드 600, `~/.ssh`는 모드 700)에 추가한다. 두 키는 서로 달라야 하며, 어느 키도 파일의 다른 줄에 나타나면 안 된다(`rb-node doctor`의 `ak_duplicate` 검사). 추가한 뒤에는 `rb-node doctor`(§7.2)로 줄을 확인한다. 노드의 호스트 키 지문은 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`로 출력한다.

</details>

## 6. Server Claude session (the responder)

메시지가 커밋되면 `serve-remote`가 분리된 프로세스로 `rb-node respond <msg_id>`를 시작한다. 이 프로세스는 `trm_root`에서 `claude -p`를 실행하며, `serve-local`이 유일한 MCP 서버이고 다음 제한이 있다. 한 번에 세션 하나(잠금 파일, timeout + 300 s 후 오래된 것으로 간주), 벽시계 timeout 1800 s, `--max-turns 40`, 도구 = `serve-local` + Read/Grep/Glob. Bash, Write, Edit, WebFetch, WebSearch는 허용되지 않는다. 세션은 `reply` 도구로만 쓴다. 실패하면 outbox에 `responder_failed` 이벤트를 올린다.

`serve-local` 도구는 `inbox_list`, `inbox_read`, `attachment_path`, `reply`, `post_event`다. 서버 세션은 작업을 제출할 수 없다.

실행할 때마다 `~/.research-bridge/mailbox/state/respond-<msg_id>.log`(모드 600. JSON 상태 필드와 마스킹된 stderr의 끝부분, 최대 64 KB)에 사실을 덧붙이며, 14일이 지난 로그는 삭제된다. 메시지가 10분 넘게 실행 중인 responder 없이 대기하거나 잠금의 stale 시간을 넘겨 `responding` 상태에 머물면, `rb-node doctor`의 `stuck_messages` 검사가 그 메시지와, 로그를 읽거나 다시 실행하는 명령(`rb-node respond <msg_id>`)을 알려 준다.

## 7. Checks

### 7.1 Security checks from the hub (provisioning step B2)

허브 매뉴얼 §4~§6을 마친 뒤 실행한다. 결과는 자리표시자를 쓴 형태로 `docs/provisioning.md` §Results에 기록한다.

| Command on the hub | Expected |
|---|---|
| `ssh rb-node1` (아무것도 보내지 않는다) | 셸 프롬프트가 없다. |
| `ssh rb-node1 cat /etc/passwd` | passwd 내용이 나오지 않는다. |
| `ssh rb-node1-harness <anything except harness-push / harness-send>` | 종료 코드 1. |
| Claude 세션에서 `read_doc("node1", "../../.ssh/authorized_keys")` | `denied` |
| `send_message("node1", "test", [<small pdf>])`, 이어서 `poll` | 답장이 `provenance.json`과 함께 `<data root>/inbox/node1/<msg_id>/` 아래에 저장된다 |
| `gpu_hours=0.01`로 `submit_job`, 이어서 `rb approve` | 상태가 `done` 또는 `budget_exceeded`인 `job_finished` 이벤트 |

전송 검사와 읽기 검사는 노드가 withheld 패턴 파일을 로드한 뒤에만 의미가 있다(§4.3).

### 7.2 `rb-node doctor` (on the node console)

    rb-node doctor

읽기 전용이다. 디렉터리를 만들지 않고 감사 기록도 쓰지 않는다. 출력은 `[ok|warn|fail] <id>: <message>`이고, ok가 아닌 각 줄 아래에 `      next: <command>`가 붙으며, 마지막은 `ok`, `N to fix`, `all ok, M warning(s)`, `N to fix, M warning(s)` 중 하나다(fail과 warn을 따로 센다). 어떤 검사가 `fail`일 때만 종료 코드 1이다. 키 자료나 패턴 텍스트는 출력하지 않는다.

| id | Level if not ok | What a failure means | Next |
|---|---|---|---|
| `config` | fail | `node.json`이 없거나, 유효한 JSON이 아니거나, 객체가 아니다. 다른 것은 검사하지 않는다. | `rb-node config init` 또는 `scripts/node-install.sh`를 다시 실행 |
| `config_keys` | warn | 알 수 없는 키나 타입이 틀린 값은 무시된다. | `rb-node config show` |
| `research_root` | fail | `trm_root`가 디렉터리가 아니다. | `rb-node config set trm_root DIR` |
| `read_roots` | warn | 읽기 루트가 존재하지 않는다. | `mkdir -p DIR` 또는 `rb-node config set read_roots '[...]'` |
| `doc_paths` | warn | `experiments_dir` 또는 `hypotheses_path`가 모든 읽기 루트 밖에 있어서 id로 하는 `read_doc`이 거부된다. | `rb-node config set KEY PATH` |
| `queue_dir` | warn | `queue_dir/jobs`가 없거나 쓸 수 없다. 작업이 어떤 runner도 보지 않는 곳으로 가게 된다. | `mkdir -p DIR/jobs` 또는 `queue_dir` 설정 |
| `withheld` | 파일이 없거나, 읽을 수 없거나, 유효한 JSON이 아니거나, 비어 있거나, 컴파일되지 않는 패턴이 있으면 fail. `withheld_source`가 설정되지 않았으면 warn | fallback 패턴 다섯 개만 적용된다(또는 파일이 손상됐다). | `scripts/node-install.sh --withheld-file FILE` 또는 `rb-node config set withheld_source PATH` |
| `approval` | fail | verifier가 없거나 읽을 수 없다. 모든 `job_submit`과 `job_cancel`이 거부된다. | `rb-node approve-key set` |
| `approval_path` | fail | `approval_path`가 읽기 또는 쓰기 루트 안에 있어서 허브가 닿을 수 있다. | `rb-node config set approval_path ~/.research-bridge/approve.json` |
| `job_template` | 비어 있으면 warn, `{config}`, `{config_dir}`, `{config_stem}` 중 어느 것도 없으면 fail | 작업이 거부되거나(`no_job_template`) config 파일을 받을 수 없다. | `rb-node config set job_template '[...,"{config}"]'` |
| `allowed_gpus` | 비어 있으면 warn | `allowed_gpus`가 비었거나 형식이 틀렸다. 모든 `job_submit`이 `no_allowed_gpus`로 거부된다. | `rb-node config set allowed_gpus '[4, 5, 6, 7]'`(본인 GPU 인덱스) |
| `claude_bin` | warn | responder를 시작할 수 없다. 메시지는 살아 있는 세션을 기다린다. | `rb-node config set claude_bin PATH` |
| `pdftotext` | warn | pdf 파일이 거부된다. | `poppler-utils` 설치 |
| `ak_bridge` | fail | `authorized_keys`에 `serve-remote` 줄이 없거나, `restrict` 또는 `from=`이 없거나, 명령 경로가 존재하는 실행 파일의 절대 경로가 아니다. 허브가 거부된다(`node_refused_key`). | `scripts/node-install.sh --hub-key '...' --hub-from ADDR --apply-authorized-keys` |
| `ak_harness` | warn | `harness-receive` 줄에 대해 같은 문제다. harness 채널만 영향을 받는다. | `--harness-key`를 붙여 같은 명령 |
| `ak_duplicate` | fail | bridge 키가 강제 명령 없이, 또는 harness 키로서 다른 줄에도 나타난다(`AGENTS.md` 핵심 규칙 9). | `~/.ssh/authorized_keys`에서 그 줄을 제거 |
| `mailbox` | warn | `mailbox/{in,out,state}`가 없거나 모드가 700이 아니다. | `scripts/node-install.sh`를 다시 실행 |
| `responder_lock` | warn | 더 이상 실행되지 않는 프로세스가 남긴 responder 잠금이 있거나, timeout + 300 s보다 오래됐다. | `rm ~/.research-bridge/mailbox/state/responder.lock` |
| `stuck_messages` | warn | 메시지가 답을 받지 못하고 대기하거나 `responding`에 멈춰 있다(§6). | `rb-node respond <msg_id>` 또는 로그 읽기 |
| `install` | warn | 설치 기록이 없거나, 그 버전이 실행 중인 코드와 다르다. | `scripts/node-install.sh`를 다시 실행 |
| `wrapper` | warn | 래퍼가 없거나, `PATH`의 python을 쓰거나, 그 python이 없거나 3.8보다 낮다. | `scripts/node-install.sh`를 다시 실행 |

허브의 `rb doctor`는 `hello` 상태(§12)를 바탕으로 SSH를 거쳐 짧은 온라인 버전을 실행한다(허브 매뉴얼 §10.2).

## 8. Budget enforcement

승인된 작업의 큐 파일은 템플릿 명령을 `rb-node run-job --gpus ... --gpu-hours ...`로 감싼다. 래퍼는 작업을 벽시계 시간 `gpu_hours / len(gpus)`에서 멈춘다(상태 `budget_exceeded`). 취소 요청은 10초마다 확인한다. `job_submit`은 연구 트리의 `HEAD`를 `state/git/<job_id>.json`에 고정한다. `run-job`은 작업 기록에 `git_submit`과 `git_start`를 남기고, `job_finished` 이벤트는 `git_head`를 싣는다.

작업이 받는 GPU: 노드의 큐 러너는 GPU마다 worker를 하나씩 두고 그 GPU를 `CUDA_VISIBLE_DEVICES`로 내보낸다. 브리지로 큐에 넣는 작업은 `allowed_gpus` 중 GPU 하나를 요청하며, wrapper는 그 작업을 집은 worker의 GPU에서 실행한다. 이 GPU는 요청한 인덱스와 다를 수 있고, 그때 작업 기록과 `job_finished` 이벤트에 `gpus_used`가 들어간다. wrapper는 `allowed_gpus` 밖의 GPU에서는 아무것도 시작하지 않는다. 그 작업은 사유 `gpu_not_allowed`, 종료 코드 126의 `failed`로 끝난다. worker 없이 콘솔에서 실행하면 wrapper는 `CUDA_VISIBLE_DEVICES`를 `--gpus` 값으로 설정한다.

## 9. Updating and removing

**업데이트:** 노드의 체크아웃에서 `scripts/node-install.sh --update`를 실행한다(`--ff-only`로 pull하고, 새 릴리스를 복사하고, 심볼릭 링크를 바꾸고, 설치 기록을 다시 쓰고, doctor를 실행한다). `node.json`, 메일함, 승인 verifier는 유지된다. 세션이 실행하는 경우에는 사용자의 승인이 필요하다. 허브는 그 차이를 `rb doctor`의 `node_version`으로 보여 준다.

**2026-11-10 현재 상태:** 등록된 노드는 아직 `rb_node` 0.1.0, 곧 `claude/node-allowed-gpus` 브랜치의 병합 전 코드(`main`의 PR 48 이전)를 실행하고 있다. 그 코드에는 `doctor`와 `link`가 없고, `hello`에 protocol 필드 없이 답한다. 허브는 이를 protocol 1로 보고 그 검사를 `unknown`으로 보고한다. `main` 체크아웃에서 `scripts/node-install.sh`를 처음 실행하면 갱신된다(옛 디렉터리를 한 번 옮기는 과정은 §2의 3단계에 설명돼 있다).

**제거:** `authorized_keys`의 두 줄을 삭제하고, 이어서 `~/.local/bin/rb-node`, `~/.local/share/research-bridge/`, 그리고 내용이 더 이상 필요 없을 때 `~/.research-bridge/`를 삭제한다.

## 10. Git tracking and the live research session

- **Git 상태, 읽기 전용, 파일 이름과 커밋 제목 없음:** `rb-node git-status`(노드 콘솔), bridge 연산 `git_status`, `rb git-status --node node1`(허브)이 `trm_root`와 설치된 코드의 브랜치, HEAD, 변경된 파일 수, ahead/behind, origin URL(자격 증명 제거)을 보고한다. `rb sync`를 한 번 돌 때마다 이 상태를 읽는다.
- **연구 트리의 실시간 세션:** `rb-node link [DIR] [--apply]`는 `rb-node serve-local`을 프로젝트 MCP 서버로 등록하여, `DIR`(기본값 `trm_root`)에서 시작한 Claude 세션이 허브 메시지를 읽고 `reply`와 `post_event`를 호출할 수 있게 한다. `--apply` 없이는 쓰게 될 `.mcp.json`을 출력한다.

      {"mcpServers": {"rb-node": {"type": "stdio", "command": "/home/<NODE_USER>/.local/bin/rb-node", "args": ["serve-local"]}}}

  (그 변수가 설정돼 있으면 `"env": {"RB_NODE_CONFIG": ...}`가 추가된다.) `--apply`를 쓰면 `DIR/.mcp.json`을 만든다. 파일이 이미 있으면 아무것도 바꾸지 않고, 대신 실행할 `claude mcp add --scope project rb-node -- <rb-node> serve-local` 명령을 출력한다. `~/.local/bin/rb-node`가 필요하다(먼저 설치 프로그램을 실행한다). Claude Code가 처음에 프로젝트 MCP 서버를 승인하라고 물을 수 있다. 이 명령은 다음 경고를 출력하며, 이 경고는 현재도 유효하다. 시작된 responder(§6)와 실시간 세션은 서로 조정되지 않으므로 둘 다 같은 메시지에 답할 수 있다(GitHub issue 41). 실시간 세션을 쓴다면 responder를 꺼야 하는지 검토한다(`claude_bin`이 실행 파일을 가리키지 않으면 `rb-node doctor`가 경고하고 responder가 시작되지 않는다).

## 11. Reference: commands

### 11.1 `rb-node` subcommands

| Subcommand | Who runs it | Does |
|---|---|---|
| `serve-remote` | 허브의 bridge 키(강제 명령) | stdin과 stdout으로 허브 요청을 처리한다. 유효한 `node.json`이 없으면 종료하지 않고 `state.configured: false`로 `hello`에 답한다. |
| `harness-receive` | 허브의 harness 키(강제 명령) | `SSH_ORIGINAL_COMMAND`에 따라 분기한다. `harness-send`는 pull이고, 비어 있거나 `harness-push`이면 스테이징 디렉터리에만 stage한다. 그 밖의 것은 종료 코드 1로 끝난다. apply 명령은 없다. |
| `serve-local` | 서버 Claude 세션 또는 실시간 세션 | `inbox_list`, `inbox_read`, `attachment_path`, `reply`, `post_event`를 갖춘 MCP 서버. |
| `respond MSG_ID` | `serve-remote` 또는 사용자 | 메시지 하나에 대해 서버 Claude 세션 하나를 실행한다(§6). |
| `run-job --gpus G[,G...] --gpu-hours H --job-id ID -- ARGV...` | 큐 | 예산 래퍼(§8). |
| `approve-key set` / `approve-key clear` | 사용자, 터미널 | §4.2. |
| `config path\|init [--force]\|show\|set KEY VALUE\|check` | 사용자 | §4. |
| `git-status` | 사용자 | `trm_root`의 git 상태와 설치 기록을 JSON으로 출력한다. |
| `install-record CHECKOUT` | `node-install.sh` | `~/.research-bridge/install.json`을 쓴다. |
| `doctor` | 사용자 | §7.2. |
| `link [DIR] [--apply]` | 사용자 | §10. |

### 11.2 `scripts/node-install.sh` flags

| Flag | Meaning |
|---|---|
| `--research-root DIR` (별칭 `--trm-root`) | 이 노드의 연구 트리. `trm_root`와 그에서 파생된 경로를 설정한다. 존재하는 디렉터리여야 한다. |
| `--hub-key 'KEY'` | 허브의 bridge 공개 키를 인라인으로 준다(`type blob [comment]`). |
| `--hub-pubkey FILE` | 같은 키를 파일로 준다. |
| `--harness-key 'KEY'`, `--harness-pubkey FILE` | 허브의 harness 공개 키. 선택 사항이며, 없으면 bridge 줄만 처리한다. |
| `--hub-from ADDR` (별칭 `--hub-subnet`) | `from="..."`에 들어갈 값: 쉼표로 구분한 주소 또는 CIDR 범위. 줄을 출력하려면 `--hub-key`와 함께 필요하다. |
| `--withheld-file FILE` | §4.3. |
| `--apply-authorized-keys` | `~/.ssh/authorized_keys`에 대한 변경을 보여 주고, 터미널에서 `y/N`을 확인한 뒤 적용한다. |
| `--update` | 먼저 이 체크아웃에서 `git pull --ff-only`를 실행한다. |
| `--dry-run` | 모든 동작을 출력하고 아무것도 쓰지 않는다. |
| `-h`, `--help` | 사용법. |

알 수 없는 플래그는 사용법을 출력하고 종료 코드 2로 끝난다.

## 12. The hello operation (protocol 2) and the other operations

허브는 `hello`를 가장 먼저 보낸다. protocol 2 노드(`rb_node` 0.2.0 이상)는 `node`, `version`, `withheld_extra`(fallback 외에 파일에서 로드한 패턴 수), `protocol`(숫자 2), `ops`(처리하는 연산의 정렬된 목록), `state`로 답한다. `state`는 경로나 패턴 텍스트가 없는 불리언과 개수의 맵이다. 이전 코드의 노드는 `protocol`과 `state`를 생략하며, 허브는 이를 protocol 1로 본다. `node.json`이 없거나 유효하지 않은 노드도 `state.configured`를 false로, `ops`를 `["hello"]`로 하여 `hello`에 답하고, 다른 모든 연산에는 `not_configured`로 답한다.

`state` 키: `configured`, `approval_verifier`, `job_template_set`, `allowed_gpus_set`, `withheld_source_set`, `withheld_loaded`, `withheld_rejected`(컴파일되지 않는 패턴), `harness_root_set`, `claude_bin_found`, `queue_dir_exists`, `python`. 그 밖의 연산: `msg_begin`, `put_chunk`, `msg_commit`, `poll`, `ack`, `get_file`, `read_doc`, `queue_status`, `gpu_status`, `job_submit`, `job_cancel`, `approve_params`, `git_status`.

### 12.1 Differences between the documents and the code

독자가 당황하지 않도록 여기에 기록한다.

- `rb-node config check --help`와 `rb config check --help`는 "exit 1 if anything"이라고 하지만, 코드는 검사가 `fail`일 때만 종료 코드 1을 반환하며 `warn`에서는 반환하지 않는다.
- git 연산은 트리를 `trm`이라는 키로 보낸다. 허브는 `tree`를 먼저 받아들이고 없으면 `trm`으로 대체한다.
- `pyproject.toml`의 패키지 버전은 0.1.0이다. 노드가 보고하는 버전은 `rb_node.__version__`이며 0.2.0이다.

### 12.2 Removed scripts

`scripts/hub-connect.sh`, `scripts/hub-agent.sh`, `scripts/trm-link.sh`는 더 이상 없다. 이 스크립트들의 일은 `rb setup`, `rb agent`(허브 매뉴얼 §4), `rb-node link`(§10)가 한다.

## Appendix A. Windows hub notes (not maintained since 2026-11-05)

2026-11-05에 노트북을 허브로 쓰던 상태에서 마지막으로 확인했으며, 코드와 보조를 맞추지 않는다.

- 코드를 LF 줄 끝으로 복사한다. Windows 허브에서는 `core.autocrlf=input`으로 체크아웃하거나 먼저 변환한다. CRLF는 래퍼 스크립트를 깨뜨린다. 지금의 설치 프로그램은 노드의 체크아웃에서 실행되므로, 체크아웃을 Windows에서 만들어 복사하는 경우에만 해당한다.
- §7.1의 허브 쪽 검사는 옛 매뉴얼에서 노트북 경로를 지정했다. 답장은 `D:/raw/research-bridge/inbox/node1/<msg_id>/` 아래에 저장됐다.
- `authorized_keys`의 `from=`은 노트북의 서브넷이었다(옛 주석의 `research-bridge-laptop`). 설치 프로그램은 이제 주석 `research-bridge-hub`와 허브의 주소를 쓴다.
- 첫 노드의 수동 설치 방법은 다음과 같았다. `ssh node1 "mkdir -p ~/.local/share/research-bridge ~/.local/bin ~/.research-bridge && chmod 700 ~/.research-bridge"`, 이어서 `scp -r rb_node node1:~/.local/share/research-bridge/`(여기서 `node1`은 제한된 `rb-node1`이 아니라 일반 로그인 별칭이다), 그리고 절대 경로 대신 `python3`를 쓴 §3의 세 줄짜리 래퍼. `scripts/node-install.sh`가 이를 대체한다.

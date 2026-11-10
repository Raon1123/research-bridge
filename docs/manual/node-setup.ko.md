# 노드 설정

이 문서는 [node-setup.md](node-setup.md)의 한국어 번역이며, 두 문서의 내용이 다르면 영어 원문을 기준으로 한다.

노드(node)는 `rb_node`(표준 라이브러리만 사용, Python 3.8 이상)를 실행하며, 허브(hub)가 forced command를 사용하는 SSH로 접속한다. 첫 번째 노드는 node1(Linux, Python 3.12)이다. 이 매뉴얼의 모든 명령은 노드에서 실행하며 사용자의 승인이 필요하다(`AGENTS.md`). 허브 쪽 설정은 [hub-setup.ko.md](hub-setup.ko.md)를 본다.

## 1. 요구 사항

- `python3`로 호출되는 Python 3.8 이상.
- pdf 파일을 검사하기 위한 `pdftotext`(poppler). 없으면 pdf 파일은 거부된다(`deny_unscannable`).
- 노드가 서버 Claude 세션으로 메시지에 답하게 하려면 Claude Code CLI가 필요하다. 비대화형 SSH에서는 `PATH`에 없는 경우가 많으므로 절대 경로를 `claude_bin`에 넣는다(§4).
- 문서를 공유할 연구 작업 트리, 그리고 `jobs/`, `processing/`, `done/`, `failed/`를 가진 작업 큐 디렉터리. node1에서 작업 트리는 `trm` 트리(`trm_root`)이다.

## 2. 코드 복사

LF 줄바꿈으로 복사한다. Windows 허브에서는 `core.autocrlf=input`으로 체크아웃하거나 먼저 변환한다. CRLF가 있으면 wrapper 스크립트가 동작하지 않는다.

    ssh <node> "mkdir -p ~/.local/share/research-bridge ~/.local/bin ~/.research-bridge && chmod 700 ~/.research-bridge"
    scp -r rb_node <node>:~/.local/share/research-bridge/

여기서 `<node>`는 노드의 일반 로그인 alias이다(node1에서는 기존의 `node1` alias). 명령을 실행할 수 없는 제한된 `rb-<node>` alias가 아니다.

## 3. Wrapper

`~/.local/bin/rb-node`, 모드 755:

```sh
#!/bin/sh
PYTHONPATH="$HOME/.local/share/research-bridge" exec python3 -m rb_node.cli "$@"
```

하위 명령: `serve-remote`(stdin으로 받는 허브 요청), `serve-local`(서버 Claude 세션용 MCP), `respond <msg_id>`(서버 세션 한 번 실행), `run-job --gpus G --gpu-hours H --job-id ID -- <argv>`(예산 wrapper), `harness-receive`(harness forced command).

## 4. `~/.research-bridge/node.json`

간단한 방법 (node 콘솔에서): `rb-node config init`, `rb-node config set <key> <value>` (목록은 JSON), `rb-node config check` (design spec §13.4: `docs/superpowers/specs/2026-10-27-research-bridge-design.md`).

`deploy/node.json.example`에서 시작한다. 경로는 이 파일에서만 가져오며, 허브는 경로를 지정할 수 없다(`AGENTS.md` hard rule 4). 모드 600.

| 키 | 의미 |
|---|---|
| `trm_root` | 연구 작업 트리의 루트. 상대 경로로 적은 read root는 이 경로에 결합된다. |
| `read_roots` | 허브가 `read_doc` / `fetch_file`로 읽을 수 있는 디렉터리. 현재 경로를 적는다. 예시 파일에는 서버의 2026-10-15 구조 개편 이전 이름이 남아 있다. |
| `write_roots` | 메일박스 inbox와 큐의 `jobs/` 디렉터리만 허용한다. |
| `queue_dir` | 큐 루트(`jobs/`, `processing/`, `done/`, `failed/`). |
| `withheld_source` | withheld 패턴이 담긴 파일. JSON 리스트, `{"patterns": [...]}`, `{"families": [{"patterns": [...]}]}` 형식을 받는다. YAML은 파싱하지 않는다(PyYAML 없음). YAML 파일이면 fallback 패턴만 적용된다. |
| `claude_bin` | Claude CLI의 절대 경로. |
| `job_template` | `{config}` placeholder를 포함하는 argv 리스트. 예: `["uv", "run", "pretrain.py", "--config", "{config}"]`. 비어 있으면 `submit_job`이 `no_job_template`으로 거부된다. 노드의 소유자가 설정한다. |
| `allowed_gpus` | 브리지 작업이 쓸 수 있는 GPU 인덱스, 즉 노드 소유자의 GPU. 예: `[4, 5, 6, 7]`. 비어 있으면 `submit_job`은 `no_allowed_gpus`로 거부되고 `run-job`은 아무것도 시작하지 않는다. 목록 밖의 GPU나 둘 이상의 GPU는 `invalid`로 거부된다. |
| `max_file` | 첨부 파일 크기 상한(바이트, 기본값 50 MB). |
| `mailbox_root`, `audit_path` | `~/.research-bridge/` 아래에 둔다. |
| `harness_root` | 노드의 `~/.claude`. 비어 있으면 harness push와 pull이 거부된다(`no_harness_root`). |
| `approval_path` | job 승인 verifier. 기본값은 `~/.research-bridge/approve.json`. `read_roots`와 `write_roots` 밖에 둔다. 없으면 `job_submit`과 `job_cancel`이 거부된다(`not_authorized`). |

`RB_NODE_CONFIG`로 경로를 덮어쓸 수 있다(테스트에서 사용).

`job_template` 자리표시자: `{config}`는 저장된 config의 경로, `{config_dir}`는 그 디렉터리, `{config_stem}`은 확장자를 뺀 이름이다. 뒤의 둘은 Hydra처럼 config를 이름으로 찾는 로더를 위한 것이다(`--config-dir {config_dir} --config-name {config_stem}`). 이런 template에서는:

- `.yaml` config만 받는다(Hydra는 `.yml`이나 `.json`을 이름으로 찾지 못한다).
- 제출한 파일이 primary config 전체가 되므로, 기본 config를 물려받으려면 `defaults`에 넣어야 한다(예: `defaults: [cfg_pretrain, _self_]`).
- 연구 트리의 config 디렉터리에 있는 config와 이름이 같은 파일을 제출하면 오류 없이 무시된다. 그 디렉터리를 먼저 찾기 때문이다. 제출하는 config에는 트리가 쓰지 않는 이름을 붙인다.

withheld 처리는 항상 켜져 있다. `withheld_source`가 없어도 `AGENTS.md` hard rule 3에 나열된 fallback 패턴이 적용된다. 텍스트 문서는 일치한 줄이 비워지고, 일치하는 pdf, tex, 이미지는 거부되며, 알 수 없는 확장자도 거부된다.

### 승인 passphrase (사용자가 노드 콘솔에서 실행)

    rb-node approve-key set      # passphrase(12자 이상)를 두 번 묻는다

verifier(salt, 반복 횟수, 유도한 키의 sha256, 권한 600)를 `approval_path`에 쓴다. passphrase 자체는 어디에도 저장하지 않는다. bridge를 거치지 말고 노드의 터미널에서 실행한다. bridge 키의 forced command로는 이 명령에 닿을 수 없다. `rb-node approve-key clear`는 verifier를 지우며, 그 뒤에는 어떤 job도 넣거나 취소할 수 없다. 설정하기 전에는 모든 승인이 `not_authorized`로 실패한다. 틀린 키가 다섯 번 들어오면 노드는 다음 시도까지 30초를 기다리게 하고, 이 대기는 두 배씩 늘어 최대 1시간이 된다. 맞는 키가 들어오면 횟수가 초기화된다.

## 5. `~/.ssh/authorized_keys` (사용자가 실행)

`deploy/authorized_keys.example`을 바탕으로 두 줄을 추가한다. `<HUB_SUBNET>`은 허브의 서브넷으로, `<PUBKEY>`는 해당 `.pub` 파일의 base64 필드로 바꾼다.

```
restrict,from="<HUB_SUBNET>",command="<NODE_HOME>/.local/bin/rb-node serve-remote" ssh-ed25519 <PUBKEY> research-bridge-hub
restrict,from="<HUB_SUBNET>",command="<NODE_HOME>/.local/bin/rb-node harness-receive" ssh-ed25519 <PUBKEY> research-bridge-harness
```

- `restrict`는 pty, 포트, agent, X11 포워딩을 끈다.
- `command=`는 클라이언트가 요청한 명령을 무시한다. 메시지 키는 `serve-remote`만, harness 키는 `harness-receive`만 실행할 수 있다. `harness-receive`는 `harness-push`, `harness-send` 또는 인자 없음만 받고 그 외에는 exit 1로 종료한다.
- `from=`은 접속 출발지 주소를 제한한다. 허브의 주소가 바뀌면(DHCP) 서브넷을 사용한다.
- 파일의 다른 키에는 영향이 없다. 공유되고 제한되지 않은 키는 shell을 그대로 유지한다. "허가되지 않은 읽기·쓰기 없음" 규칙은 그런 키를 제거하거나 제한한 뒤에야 완전히 성립한다(`docs/HANDOFF.md`의 보류 결정 사항).

## 6. 서버 Claude 세션 (선택)

메시지가 commit되면 `serve-remote`가 `rb-node respond <msg_id>`를 분리된(detached) 프로세스로 시작한다. 이 프로세스는 `trm_root`에서 `claude -p`를 실행하며, MCP 서버는 `serve-local` 하나뿐이고 다음 제한이 적용된다. 한 번에 세션 하나(lock 파일, timeout + 300 s 후 stale), wall timeout 1800 s, `--max-turns 40`, 도구는 `serve-local` + Read/Grep/Glob. 세션은 `reply` 도구로만 쓰기를 할 수 있다. 실패하면 `responder_failed` 이벤트를 outbox에 게시한다.

`serve-local`의 도구는 `inbox_list`, `inbox_read`, `attachment_path`, `reply`, `post_event`이다. 서버 세션은 작업을 제출할 수 없다.

## 7. 확인 (허브 매뉴얼 §4–§6 이후 허브에서 실행)

| 허브에서 실행하는 명령 | 기대 결과 |
|---|---|
| `ssh rb-<node>` (아무것도 보내지 않음) | shell 프롬프트가 나오지 않는다. |
| `ssh rb-<node> cat /etc/passwd` | passwd 내용이 나오지 않는다. |
| `ssh rb-<node>-harness <anything except harness-push / harness-send>` | Exit 1. |
| Claude 세션에서 `read_doc("<node>", "../../.ssh/authorized_keys")` | `denied` |
| `send_message("<node>", "test", [<small pdf>])` 후 `poll` | 답신이 `D:/raw/research-bridge/inbox/<node>/<msg_id>/` 아래에 `provenance.json`과 함께 저장된다. |
| `gpu_hours=0.01`로 `submit_job` 후 `rb approve` | 상태가 `done` 또는 `budget_exceeded`인 `job_finished` 이벤트 |

결과는 placeholder를 유지한 채 `docs/provisioning.md` §Results에 기록한다.

## 8. 예산 강제

승인된 작업의 큐 파일은 template 명령을 `rb-node run-job --gpus ... --gpu-hours ...`로 감싼다. wrapper는 wall time `gpu_hours / len(gpus)`에서 작업을 중단한다(상태 `budget_exceeded`). 취소 요청은 10 s마다 폴링한다.

작업이 받는 GPU: 노드의 큐 러너는 GPU마다 worker를 하나씩 두고 그 GPU를 `CUDA_VISIBLE_DEVICES`로 내보낸다. 브리지로 큐에 넣는 작업은 `allowed_gpus` 중 GPU 하나를 요청하며, wrapper는 그 작업을 집은 worker의 GPU에서 실행한다. 이 GPU는 요청한 인덱스와 다를 수 있고, 그때 작업 기록과 `job_finished` 이벤트에 `gpus_used`가 들어간다. wrapper는 `allowed_gpus` 밖의 GPU에서는 아무것도 시작하지 않는다. 그 작업은 사유 `gpu_not_allowed`, 종료 코드 126의 `failed`로 끝난다. worker 없이 콘솔에서 실행하면 wrapper는 `CUDA_VISIBLE_DEVICES`를 `--gpus` 값으로 설정한다.

## 9. 업그레이드와 제거

업그레이드: 사용자의 승인을 받아 새 `rb_node/`를 기존 것 위에 복사한다(LF 규칙 동일). `node.json`과 메일박스는 유지된다. 제거: `authorized_keys`의 두 줄을 삭제한 뒤 `~/.local/bin/rb-node`, `~/.local/share/research-bridge/`를 삭제하고, 내용이 더 필요하지 않으면 `~/.research-bridge/`도 삭제한다.

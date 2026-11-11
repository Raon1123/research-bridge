> 출처: `docs/manual/hub-setup.ko.md`의 부록 A. 2026-11-11에 이곳으로 옮겼다.
> 유지하지 않는다(2026-11-05 이후 코드와 맞추지 않았다). 현재 설명은 `docs/manual/hub-setup.ko.md`에 있다.

## Appendix A. Windows or laptop hub (not maintained since 2026-11-05)

이 부록은 첫 번째 허브인 Windows 노트북의 설명을 보관한다. 마지막으로 확인한 날은 2026-11-05이며 코드와 보조를 맞추지 않는다. `rb setup`, `rb agent`, `rb doctor`, `rb service`, 타이머는 Linux용으로 작성됐고 Windows에서는 시험하지 않았다. 경로는 예시다.

- **요구 사항:** Python 3.14(테스트를 실행한 버전), OpenSSH 클라이언트와 자동으로 시작되도록 설정한 "OpenSSH Authentication Agent" 서비스, `D:/raw/Codes/research-bridge`의 저장소(8765 대시보드는 `vault-export/dashboard/rb_pending.py`의 `RB_REPO`에서 `rb_host`를 import한다).
- **데이터 디렉터리:** `RB_HOST_ROOT`가 설정되지 않았을 때 Windows의 기본값은 `D:/raw/research-bridge/`이며, vault와 클라우드 동기화 폴더 밖에 둔다. 기본 withheld 패턴 파일은 session-calendar 내보내기 `D:/raw/session-calendar/server/withheld_patterns.json`이다.
- **키:** `ssh-keygen -t ed25519 -f C:/keys/research-bridge/node1_ed25519 -C research-bridge-hub`와 harness 키에 대한 같은 명령. 둘 다 `ssh-add`한다. passphrase는 로그온마다 한 번 입력한다. §4.5 블록의 `IdentityFile`에는 `C:/keys/...` 경로를 쓴다. 노드의 `from=`은 노트북의 서브넷이다.
- **MCP 항목**은 `~/.claude.json`의 `mcpServers` 아래에 둔다. `"research-bridge": {"type": "stdio", "command": "uv", "args": ["run", "--directory", "D:/raw/Codes/research-bridge", "--extra", "host", "python", "-m", "rb_host.server"]}`.
- **승인**은 PowerShell이나 Windows Terminal(리다이렉트된 입력과 Git Bash의 mintty는 거부된다)에서 하거나, `http://127.0.0.1:8765/rb/pending`(루프백만, 프로세스별 CSRF 토큰, passphrase 입력란)에서 한다. `vault-export/`에서 대시보드 경로를 설치하고(`vault-export/README.md` 참조) 8765 대시보드를 다시 시작한다. 둘 다 사용자의 승인이 필요하다.
- **검사:** `curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8765/rb/pending`은 200을 출력해야 하고, 같은 URL을 노트북의 LAN 주소로 호출하면 403이어야 한다.
- **테스트:** `tests/test_rb_pending.py`와 `tests/test_bridge_edges.py`는 저장소의 `vault-export/` 사본을 쓴다. vault는 필요 없다.

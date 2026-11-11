> 출처: `docs/manual/node-setup.ko.md`의 부록 A. 2026-11-11에 이곳으로 옮겼다.
> 유지하지 않는다(2026-11-05 이후 코드와 맞추지 않았다). 현재 설명은 `docs/manual/node-setup.ko.md`에 있다.

## Appendix A. Windows hub notes (not maintained since 2026-11-05)

2026-11-05에 노트북을 허브로 쓰던 상태에서 마지막으로 확인했으며, 코드와 보조를 맞추지 않는다.

- 코드를 LF 줄 끝으로 복사한다. Windows 허브에서는 `core.autocrlf=input`으로 체크아웃하거나 먼저 변환한다. CRLF는 래퍼 스크립트를 깨뜨린다. 지금의 설치 프로그램은 노드의 체크아웃에서 실행되므로, 체크아웃을 Windows에서 만들어 복사하는 경우에만 해당한다.
- §7.1의 허브 쪽 검사는 옛 매뉴얼에서 노트북 경로를 지정했다. 답장은 `D:/raw/research-bridge/inbox/node1/<msg_id>/` 아래에 저장됐다.
- `authorized_keys`의 `from=`은 노트북의 서브넷이었다(옛 주석의 `research-bridge-laptop`). 설치 프로그램은 이제 주석 `research-bridge-hub`와 허브의 주소를 쓴다.
- 첫 노드의 수동 설치 방법은 다음과 같았다. `ssh node1 "mkdir -p ~/.local/share/research-bridge ~/.local/bin ~/.research-bridge && chmod 700 ~/.research-bridge"`, 이어서 `scp -r rb_node node1:~/.local/share/research-bridge/`(여기서 `node1`은 제한된 `rb-node1`이 아니라 일반 로그인 별칭이다), 그리고 절대 경로 대신 `python3`를 쓴 §3의 세 줄짜리 래퍼. `scripts/node-install.sh`가 이를 대체한다.

# 호스트 연동

| 호스트 | 프로젝트 스킬 | 선택적 역할 |
|---|---|---|
| Codex | .agents/skills/<id> | .codex/agents/book-followup-*.toml |
| Claude Code | .claude/skills/<id>의 공통 폴더 개별 링크 | .claude/agents/book-followup-*.md |
| Antigravity | .agents/skills/<id> | .agents/agents/book-followup-*.md |

스킬 전체에 역할 지침과 보조기가 포함된다. 전용 프로필이 없어도 네이티브 새 에이전트에 계약을 전달할 수 있다. 전역 설정·모델·인증을 바꾸지 않는다. 독립 세션도 불가능하면 필수 평가를 blocked로 기록한다.

대상 지식 스킬의 프런트매터는 세 호스트가 함께 받아들이는 키(name, description 등 공통 검증기가 허용하는 키)만 쓴다. Claude의 `argument-hint`처럼 한 호스트 전용 키는 다른 호스트의 검증기가 거부할 수 있으므로 넣지 않는다.

Codex는 $book-to-skill-followup, Claude Code는 /book-to-skill-followup, Antigravity는 지원 버전의 slash 또는 스킬 이름을 포함한 자연어로 호출한다. 구형 IDE workflow는 만들지 않는다. [Claude 스킬](https://code.claude.com/docs/en/skills), [Claude 에이전트](https://code.claude.com/docs/en/sub-agents), [Antigravity 스킬](https://antigravity.google/docs/skills), [Antigravity 에이전트](https://antigravity.google/docs/subagents/), [전환 안내](https://antigravity.google/docs/migration/workflows-to-skills/)와 실제 버전 도움말을 대조한다.

## 실제 호출

최종 지식 스킬을 byte-identical 격리 프로젝트에 복사한다. 후속 스킬을 재귀 호출하지 않는다. 입력은 실제 사용 요청 한 개이며 스킬 본문·정답·절대 경로를 주입하지 않는다. 메인은 사용 호스트의 버전 확인 결과를 별도 실행 기록에 보관한다. helper는 quota를 호출 전에 소비하고 실제 인자·입력·로그·종료·복사 파일 해시를 보존한다.

읽기 범위를 제한하고 제한을 보장할 수 없으면 blocked로 처리한다. hooks/MCP 차단은 해당 호출 override이며 개인 설정을 바꾸지 않는다. 로그인·승인 우회를 하지 않는다. 사용 호스트 1개는 실제 검사, 나머지는 정적 형식 수준으로 표시한다.

통과는 실제 스킬 로드/읽기 추적, 요청 수행, 정상 종료, 고정 해시 일치가 필요하다. 답변의 자기 주장·링크 존재·exit 0만으로 loaded를 참으로 두지 않는다. CLI 결과는 GUI 메뉴 발견을 보증하지 않는다. 실패·시간 초과·인증 부재 뒤 재호출하지 않고 새 run에서 보완한다.

## Claude Code 로드 증거와 격리

Claude Code가 `Skill` 도구로 스킬을 불러올 때는 SKILL.md를 Read 도구로 읽지 않는다. 스킬 이름을 넣은 요청이나 자연어 요청에서 모델이 `Skill` 도구를 고르면 `Skill` 도구 호출 → `Launching skill: <id>` 결과 → `isSynthetic` 사용자 메시지 순서로 불러온다. 이 메시지는 `Base directory for this skill: <경로>` 한 줄과 프런트매터를 뺀 SKILL.md 본문, 인자가 있으면 끝의 `ARGUMENTS:` 줄로 이뤄진다. `Skill` 도구가 있어도 모델이 SKILL.md를 Read로 직접 여는 경우가 있다.

helper는 성공한 `Skill` 결과 바로 다음의 이 메시지만 인정한다. 기준 경로가 격리 복사본 안에 있고, 본문이 고정 SKILL.md 본문과 같으며 뒤에 `ARGUMENTS:` 줄 말고는 없을 때 그 SKILL.md read로 정규화한다. 줄바꿈 형식과 BOM 차이는 Claude Code와 같은 방식으로 맞춘다. record에는 `native_skill_load`를 남기고, run_state가 원래 로그에서 같은 값을 다시 계산해 대조한다. 모델이 Read로 SKILL.md를 연 기록은 파일 사용 증거로 인정하되 네이티브 로드와 구분해 보고한다.

Claude Code는 불러온 본문의 `$ARGUMENTS`, `$0`·`$1` 같은 위치 인자, `${CLAUDE_SKILL_DIR}` 같은 변수를 바꿔 쓰고 `` !`명령` ``은 셸로 실행하려 한다. 인자가 있으면 "$1,000"이 인자의 단어로 바뀌는 것을 2.1.296에서 확인했다. 이런 표기는 실제 사용에서도 본문을 바꾸므로 대상 SKILL.md에 두지 않는다. helper는 이런 표기가 있으면 호출 한도를 쓰기 전에 `claude-skill-substitution`으로 차단하고, static-checks는 `claude-load-substitution` 경고를 낸다.

`-p` 모드에서 `/<id>`로 시작한 요청은 stream-json에 로드 이벤트를 남기지 않는다(2.1.296에서 확인). 그래서 자동 host-smoke 입력은 `<id> 스킬을 사용해서 …`처럼 스킬 이름을 넣은 실제 사용 요청으로 쓴다. slash 로드는 `-p` 로그로 증명할 수 없다. behavior-tests에서는 간접 근거로만 기록하고, 직접 확인은 대화형 세션에서 따로 하거나 한계로 남긴다.

어댑터는 `--setting-sources project`로 사용자 수준 스킬·플러그인·설정을 이 호출에서만 제외한다. 원래 로그 init 이벤트의 `skills` 수가 프로젝트 수준으로 줄었는지 확인한다. 사용자 설정의 모델 선택, `env`, `apiKeyHelper`도 빠지므로 init 이벤트의 `model`을 보고에 적고, 이런 설정에 기대는 인증 환경이면 호출 전에 확인한다. 실행 폴더의 상위 폴더에 있는 `.claude/skills`는 여전히 발견된다. 상위 폴더의 `CLAUDE.md`·`AGENTS.md`가 이 호출의 지시로 함께 읽히는지는 시험하지 않았으므로, 대상 프로젝트에 이런 파일이 있으면 한계로 적는다. 같은 id가 있으면 2.1.296에서는 가까운 격리 복사본이 선택됐다. 상위 사본이 선택되면 기준 경로가 격리 복사본 밖이므로 로드 증거로 인정하지 않는다. 권한 확인이 필요한 도구 호출은 `--permission-prompts none`으로 자동 거부되며 `permission_denied` system 이벤트로 남는다. 스킬 폴더 밖 파일을 열려던 시도는 이 이벤트와 도구 입력으로 확인한다.

## 장시간 실행 도구

helper의 600초 제한과 바깥 도구의 대기 시간은 별개다. Codex App의 exec_command는 짧게 yield하고 응답 객체 전체의 session_id를 보존한 뒤 write_stdin으로 완료까지 확인한다. functions.exec의 cell ID가 나오면 functions.wait로 이어간다. stdout만 출력해 session/cell ID를 버리지 않는다. 30초짜리 동기 실행 도구를 600초 호스트 검사에 사용하지 않는다.

helper는 호출 시작 시 host/attempt.json을 만들고 raw-trace.jsonl/stderr.log에 실행 중 출력도 저장한다. 외부 중단으로 최종 receipt가 없으면 부분 로그와 소비된 quota를 보존하고 성공으로 표시하지 않는다. 같은 run에서 재호출하지 않고 새 run에서 입력·기존 산출물의 신선도를 확인한다.

## Antigravity 네이티브 실행 로그

현재 AGY CLI 도움말만으로 최소 읽기 도구와 MCP 차단을 보장할 수 없어 자동 CLI 호출은 blocked다. 네이티브 호스트에서 읽기 전용 범위를 지키며 실제 로그를 얻을 수 있으면 다음 경로로 마무리한다. 설치되어 있다는 이유만으로 이 단계를 통과시키지 않는다.

```bash
python3 -B "$FOLLOWUP_SKILL_DIR/scripts/host_smoke.py" --run-dir "$FOLLOWUP_RUN_DIR" --prompt coordinator/host-input.txt --prepare
python3 -B "$FOLLOWUP_SKILL_DIR/scripts/run_state.py" claim-host --run-dir "$FOLLOWUP_RUN_DIR"
```

준비된 host/project를 대상으로 native 호스트에서 지식 스킬을 실제로 한 번 호출하고 원래 도구/결과 로그를 host/native-trace.json에 저장한다. 검증기는 원래 view_file 요청·결과와 실행 완료를 확인해 성공 읽기 및 turn.completed로 정규화한다. 정규화 이벤트를 원래 로그에 작성해 넣지 않는다. 코드의 실제 파서가 이해하지 못하는 로그는 pass로 변환하지 않는다. 자기 보고 목록을 실제 trace로 만들어 내지 않는다.

AGY CLI 1.3.3의 원래 stdout NDJSON도 import할 수 있다. `event: init`의 conversation ID, `event: step_update`의 같은 conversation/step_index에 대한 ACTIVE → DONE, `tool_info.name: view_file`과 `parameters.AbsolutePath`를 결속한다. DONE만으로 성공을 판단하지 않고 출력과 오류 부재를 확인한다. `event: result`의 같은 conversation과 `status: SUCCESS`는 turn 종료를 나타내며, 모든 도구 성공이나 내용 정확성을 증명하지 않는다. [공식 stdout 스키마](https://www.antigravity.google/docs/cli/headless/#tool-calls-in-the-stream).

`--mode plan --sandbox`는 최소 읽기 도구·MCP 전체 격리의 보장이 아니다. 직접 CLI 시험은 사용 도구와 파일 변경을 사후 확인하는 범위로 기록하며, 자동 host 어댑터의 격리 게이트를 우회하는 근거로 쓰지 않는다.

```bash
python3 -B "$FOLLOWUP_SKILL_DIR/scripts/host_smoke.py" --run-dir "$FOLLOWUP_RUN_DIR" --prompt coordinator/host-input.txt --import-trace host/native-trace.json
```

import는 기존 quota 1회와 동일한 격리 복사본을 검증하며 재호출하거나 재복사하지 않는다. 실제 trace나 읽기 격리를 얻을 수 없으면 필수 호스트 단계를 차단한다. Codex/Claude 자동 어댑터와 이 경로의 검증 수준을 구분해 보고한다.

## 후속 스킬 자체의 진입 시험

위의 최종 지식 스킬 검사는 후속 스킬의 slash 발견·확장을 직접 증명하지 않는다. 후속 스킬 자체는 별도 시험 프로젝트·별도 실행 ID에서 `/book-to-skill-followup`과 대상·원문을 제공해 시험한다. 읽기 전용으로 0–2단계 예비 검토만 요청했다면 실제 발견/확장, 자료 읽기, 답변, 종료와 남은 조건을 기록하고 전체 FLOW 완료로 표현하지 않는다.

Claude의 init `skills`/`agents`는 발견·등록 증거이며 요청 수행의 증거도, 스킬 로드의 증거도 아니다. `result.is_error: true`는 subtype이나 종료 메시지와 무관하게 실패다. Read의 정상 tool_result는 공식 예제처럼 is_error를 생략할 수도 있으므로 요청 ID와 결과 내용을 결속한다. [공식 도구 결과](https://platform.claude.com/docs/en/agents-and-tools/tool-use/handle-tool-calls).

Antigravity init의 `expanded_commands`는 실제 slash 확장 증거이며 view_file 읽기와 별도로 표시한다. 발견/확장을 파일 읽기라고 바꾸어 기록하지 않는다. OAuth 만료 등 인증 실패는 원래 로그를 남기고, 다른 인증이나 권한 우회로 성공을 만들지 않는다. 사용자가 해당 호스트를 건너뛰라고 하면 추가 호출하지 않는다.

## Codex 배치 읽기 로그와 답변 해시

Codex 로그는 실제 `item.completed`의 command_execution, `status: completed`, 정수 exit_code 0을 확인한다. 단순 `cat`을 세미콜론으로 이어 실행한 로그는 셸로 다시 실행하지 않고 인자를 분석한다. 순서대로 연결한 실제 UTF-8 파일 내용과 원래 aggregated_output가 정확히 같을 때만 격리 프로젝트 내부의 파일을 읽기 증거로 인정한다. 파이프·조건부 실행·리다이렉션·명령 치환·쓰기 명령은 허용하지 않는다. 단순 sed/head/tail/rg/grep는 개별 읽기 로그만 판정하며, 여러 명령의 마지막 종료 코드만으로 앞선 명령의 성공을 추정하지 않는다.

최종 답변은 호스트의 실제 최종 응답에서 추출해 `host/answer.txt`로 보존한다. `answer_sha256`는 답변 파일의 정확한 UTF-8 바이트를, `raw_trace_sha256`는 원래 로그를 가리킨다. 답변이 없거나 해시가 다르면 완료 근거로 사용하지 않는다. 실제 호출 없이 기존 로그를 재생한 단위 검증과, 새 실행의 최종 호스트 호출은 별도로 기록한다.

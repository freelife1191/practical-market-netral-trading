# 에이전트별 사용

## 배치와 호출

| 호스트 | 자료 위치 | 호출 |
|---|---|---|
| Codex | `.agents/skills/danswer-market-trading/` | `$danswer-market-trading` |
| Claude Code | `.claude/skills/danswer-market-trading` → 공통 원본의 개별 상대 링크 | `/danswer-market-trading` |
| Antigravity | `.agents/skills/danswer-market-trading/` | “danswer-market-trading 스킬을 사용해”라는 자연어. slash 지원은 사용하는 버전에서 확인 |

호스트의 프로젝트 위치가 이 폴더인지 확인합니다. 설치 후 새 대화에서 스킬 목록을 다시 확인합니다. 목록에 없을 때는 [문제 해결](troubleshooting.md)의 직접 경로 확인을 사용합니다. `agents/openai.yaml`은 표시·호출 메타데이터이며 별도 트레이딩 에이전트가 아닙니다.

Claude 별칭은 폴더 전체를 같은 원본으로 연결합니다. 다른 이름의 스킬을 포함하는 `.claude/skills` 전체 링크로 바꾸지 않습니다. 현재 프로젝트의 기존 항목을 보존하는 설치 명령은 [README](../README.md#installation)에 있습니다.

## 호출 예시

```text
$danswer-market-trading 5장의 직장인 원칙을 근거·예외·준비 조건으로 설명해줘.
```

Claude Code는 위의 `$`를 `/`로 바꿉니다. Antigravity는 앞부분을 “danswer-market-trading 스킬을 사용해”로 바꿉니다. 내용과 미정 조건은 그대로 유지합니다.

## 후속 제작과 일반 사용

일반 사용은 지식 스킬을 호출합니다. 재검수는 별도 설치한 `book-to-skill-followup` 스킬에 프로젝트·대상 지식 스킬·원문·호스트를 지정합니다. 독립 원문 검토·시험·최종 검토는 새 컨텍스트에 역할 계약을 전달합니다. 이 프로젝트의 네이티브 검토에는 별도 역할 프로필 설치가 필요하지 않습니다.

## 확인 수준

이번 후속 절차의 실제 호출 호스트는 **Codex CLI**입니다. 실제 파일 읽기 로그·정상 종료·고정 해시를 실행 기록으로 확인합니다. Codex 데스크톱의 메뉴 표시 확인과 CLI 호출은 구분합니다.

**Claude Code**(2.1.296, Opus 5.5)는 2026-10-14에 `claude -p`로 다섯 번 실제 호출했습니다. `/danswer-market-trading` 슬래시 호출, Codex식 `$danswer-market-trading` 입력, 책 이름이 있는 질문과 없는 질문 모두 스킬을 불러와 `.claude/skills` 링크 경로로 장·참조 파일을 읽었습니다. 답변의 인쇄/PDF쪽은 모두 스킬 자료와 일치했습니다. 첫 시험에서 Claude가 원본 PDF를 직접 열려고 한 문제는 스킬 지침을 보완한 뒤 재시험에서 사라졌습니다. 시험 기록은 [Claude 검토 보고서](../_workspace/claude-skill-review/2026-10-14/report.md)에 있습니다. Antigravity는 자료 배치와 호출 안내 수준이며 실제 사용 시험 대상이 아닙니다. 최종 판정은 [검수 기록](validation.md#evidence)에서 확인합니다.

전역 모델·인증·사용자 설정은 설치 절차에서 변경하지 않습니다.

후속 스킬의 마지막 검수에는 고정 리비전의 한국어 세 자료가 포함됩니다. 추가 전역 설치 없이 동일 자료를 사용하며, 실제로 사용하는 호스트의 새 독립 컨텍스트에서 검수합니다. `language-review`의 검토·해시 기록은 자동 호스트 호출 전에 고정합니다.

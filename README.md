# 실전 시황 트레이딩 지식 스킬

이진호(디앤서)의 『실전 시황 트레이딩』을 **개념 학습·자료 탐색·매매 계획 검토·일지 복기**에 활용하는 프로젝트입니다. 시황에서 종목과 기법을 고르고, 손절·가용 시간·생활 기반까지 함께 점검합니다.

실제 호출 이름은 **`danswer-market-trading`**, 프로젝트 폴더 이름은 `practical-market-netral-trading`입니다. 본문 **7장·주요 소절 33개**, 상세 참조 자료 13개와 용어·패턴·판단표를 제공합니다.

> [!IMPORTANT]
> 책의 원칙, 저자의 당시 거래 사례, 작성자가 만든 적용 양식을 구분합니다. 최신 시세·시장 제도는 별도 확인이 필요하며, 이 스킬의 결과는 자동 주문이나 성과 보증이 아닙니다.

---

<a id="installation"></a>

## 설치

### 프롬프트로 설치

다른 프로젝트에서 아래처럼 요청합니다. 경로를 실제 원본 프로젝트와 설치 대상 프로젝트로 바꿉니다.

```text
/absolute/source-project/.agents/skills/danswer-market-trading 폴더 전체를
현재 프로젝트의 .agents/skills/에 설치하고 Claude Code용 개별 상대 링크도 연결해줘.
기존 스킬이나 링크가 있으면 덮어쓰지 말고 보존해줘.
```

### CLI로 설치

설치할 프로젝트로 이동한 뒤 실행합니다. Python은 폴더 복사·별칭 생성에만 사용하며 지식 스킬 호출에는 필요하지 않습니다.

```bash
python3 - <<'PYINSTALL'
from pathlib import Path
import shutil
source = Path('/absolute/source-project/.agents/skills/danswer-market-trading')
project = Path.cwd()
target = project / '.agents/skills/danswer-market-trading'
alias = project / '.claude/skills/danswer-market-trading'
if not source.is_dir():
    raise SystemExit('원본 스킬 폴더를 찾을 수 없습니다.')
if target.exists() or target.is_symlink() or alias.exists() or alias.is_symlink():
    raise SystemExit('기존 스킬 또는 별칭을 보존합니다. 설치를 중단합니다.')
target.parent.mkdir(parents=True, exist_ok=True)
alias.parent.mkdir(parents=True, exist_ok=True)
shutil.copytree(source, target)
alias.symlink_to('../../.agents/skills/danswer-market-trading', target_is_directory=True)
print(target)
PYINSTALL
```

> [!NOTE]
> **`SKILL.md` 한 파일이 아닌 폴더 전체**를 설치합니다. 책 PDF·추출 원문·검수 작업 폴더는 기본 사용에 필요하지 않습니다. README와 가이드도 필요하면 이 프로젝트의 `README.md`와 `docs/`를 함께 가져옵니다. 기존 앱 README가 있다면 안내 링크만 추가합니다.

---

<a id="quick-start"></a>

## 시작하기

설치한 프로젝트의 새 대화에서 다음 요청을 실행합니다.

```text
$danswer-market-trading 종가 베팅을 공부하고 싶어.
관련 장과 상세 참조를 먼저 읽고, 후보 선정·진입 근거·무효화·다음 날 대응을 설명해줘.
저자의 원칙과 과거 사례, 새 적용 양식을 구분하고 인쇄쪽/PDF쪽을 적어줘.
```

Codex에서는 `$danswer-market-trading`, Claude Code에서는 `/danswer-market-trading`, Antigravity에서는 “danswer-market-trading 스킬을 사용해”라는 자연어로 요청을 시작합니다. 호스트별 발견·호출과 확인 범위는 [에이전트별 사용](docs/agents.md)에 있습니다.

학습 답변을 받은 다음에는 같은 대화에서 이어갑니다.

```text
$danswer-market-trading 방금 설명의 갭 상승·보합·갭 하락 대응을 비교표로 보완해줘.
현재 종목·가격·손절률은 입력하지 않았으니 미확인으로 남겨줘.
```

---

<a id="toc"></a>

## 목차

- [설치](#installation)
- [시작하기](#quick-start)
- [간단한 활용과 입력](#usage)
- [전체 자료 구성](#materials)
- [상세 가이드](#guides)
- [출처와 검증 범위](#source)

<a id="usage"></a>

## 간단한 활용과 입력

| 목적 | 요청 예시 | 기대 결과 |
|---|---|---|
| 개념 학습 | `$danswer-market-trading 2-2-2와 0순위의 차이를 설명해줘.` | 관찰 후보와 매수 확정의 구별 |
| 자료 탐색 | `$danswer-market-trading TCC스틸 종가 사례의 참조 파일과 원문 위치를 찾아줘.` | 상세 자료·인쇄/PDF쪽·확인할 판단 |
| 계획 검토 | `$danswer-market-trading 장중 대응이 어려운 직장인의 종가 계획을 검토해줘. 다음 날 대응은 미정이야.` | 여건·누락·보류·무효화 조건 |
| 기법 비교 | `$danswer-market-trading 같은 가상 입력에서 돌파와 수급주 접근을 비교해줘.` | 필요한 관찰·서로 다른 조건·미확인 |
| 위험 점검 | `$danswer-market-trading 손실 뒤 추가 매수한 일지를 검토해줘.` | 근거 강화와 본전 심리 구별 |
| 복기 | `$danswer-market-trading 손익만 있는 메모를 의사결정 일지로 바꿔줘.` | 당시 정보·사후 정보·다음 훈련 |
| HTS 탐색 | `$danswer-market-trading 거래원 화면의 목적과 원문 번호 차이를 알려줘.` | 목적·본문/화면 표기·현재성 한계 |

### 내 상황에 맞게 요청하기

```text
$danswer-market-trading [학습할 주제/검토할 계획/일지]를 다뤄줘.
관찰 시점·시장: [날짜와 시장 또는 가상 입력]
자료: [파일 경로/붙여넣은 메모/장 번호]
확인한 것: [시황·재료·가격 위치·수급·유동성]
제약: [관찰 가능 시간·본업·생활비와 분리된 자금]
확정: [유지할 조건] / 미정: [아직 정하지 않은 것]
산출물: [설명/자료 목록/검토표/분기표/일지]
관련 장·참조 자료를 먼저 읽어줘. 학습·자료 탐색은 요청한 설명이나 자료 목록으로,
계획 검토는 판단→근거→미확인→대응·철회 조건 순으로 정리해줘.
```

새 대화에서는 이전 답변이나 문서도 함께 제공합니다. 숫자를 입력하지 않은 손절률·수량·가격은 채워 넣지 않습니다. 현재 자료를 바탕으로 판단을 요청할 때는 출처와 관찰 시점을 함께 제공합니다. [고급 활용](docs/advanced-usage.md)에는 본문 7장과 앞뒤 자료·부록의 서로 다른 예시와 후속 요청이 있습니다.

### 조건과 예외를 더 자세히 다루기

보완한 상세 참조를 이용하면 사례의 판단 근거와 다음 날 대응까지 비교할 수 있습니다. 아래 예시는 실제 매매 추천이 아니라 책의 조건을 학습하거나 가상 계획을 검토하는 요청입니다. 각 예시의 후속 요청은 같은 대화에서 받은 답변에 이어 사용합니다.

| 확인할 내용 | 고급 예시와 후속 요청 | 근거 자료 |
|---|---|---|
| 당일 수량·방향과 일별 연속성, 프로그램·거래원의 구별 | [3장 예시 B](docs/advanced-usage.md#chapter-3-b) · [후속](docs/advanced-usage.md#chapter-3-followup) | [종목 선정](.agents/skills/danswer-market-trading/references/stock-selection.md) |
| 한화시스템·펄어비스의 고유 근거, 광주신세계의 보유 결과, 정규장 전용 후보 기준 | [종가 심화](docs/advanced-usage.md#reference-closing) · [후속](docs/advanced-usage.md#reference-closing-followup) | [종가](.agents/skills/danswer-market-trading/references/closing-bet.md) |
| SK하이닉스·삼성전자-2와 -3의 거래 날짜, 당시 일정과 사후 급등의 구별 | [종가 심화](docs/advanced-usage.md#reference-closing) · [후속](docs/advanced-usage.md#reference-closing-followup) | [사례 색인](.agents/skills/danswer-market-trading/references/case-index.md) |
| 매드업의 자금 이동·재돌파, 네 묶음 충족과 손익비 확인 | [돌파 심화](docs/advanced-usage.md#reference-breakout) · [후속](docs/advanced-usage.md#reference-breakout-followup) | [돌파](.agents/skills/danswer-market-trading/references/breakout.md) |
| 로보스타의 정규장 이탈·보합과 대체거래소 재상한가 | [테마 심화](docs/advanced-usage.md#reference-theme) · [후속](docs/advanced-usage.md#reference-theme-followup) | [테마](.agents/skills/danswer-market-trading/references/theme-trading.md) |
| PPI 일정·ADR 상품 출시 기대와 수급, 현재 사실·미공개 정보 추정의 경계 | [수급 심화](docs/advanced-usage.md#reference-flow) · [후속](docs/advanced-usage.md#reference-flow-followup) | [수급](.agents/skills/danswer-market-trading/references/flow-trading.md) |
| 선도전기의 가치 판단·연상 보유 예외와 일반적인 다음 날 갭 청산 | [상따 심화](docs/advanced-usage.md#reference-limit-up) · [후속](docs/advanced-usage.md#reference-limit-up-followup) | [상따](.agents/skills/danswer-market-trading/references/limit-up.md) |

거래를 특정할 때는 종목명과 함께 사례 번호·날짜를 적습니다.

```text
$danswer-market-trading SK하이닉스·삼성전자-2(2026-05-25)와 -3(2026-07-14~15)를 비교해줘.
종가·수급 상세와 사례 색인을 읽고 거래별 당시 근거·밤사이 새 정보·다음 날 결과를 나눠줘.
미국 휴장 뒤 재개 일정과 마이크론 급등 결과, CPI/PPI 표기 차이가 어느 거래에 속하는지 확인해줘.
가격 기준은 전일 종가·전일 고가·당일 고가를 구별해 적어줘.
인쇄/PDF쪽은 쪽 대응 자료로 검산해 붙이고 본문에 없는 매도 가격·시각은 만들지 마.
```

```text
$danswer-market-trading 방금 두 사례 표를 바탕으로,
사후 결과를 진입 전에 알았던 정보처럼 썼거나 전일·당일 가격 기준을 바꾼 문장이 있는지 참조와 대조해 고쳐줘.
사례 번호·날짜와 미기재 값을 유지하고 원문 내부의 CPI/PPI 차이를 임의로 정정하지 마.
```

---

<a id="materials"></a>

## 전체 자료 구성

관련 자료를 선택한 뒤 장·상세 참조를 읽고, 책 근거와 적용 가정을 구분해 설명·검토와 후속 보완에 사용합니다.

```text
.agents/skills/danswer-market-trading/
├── SKILL.md              # 호출 지침·장/주제 색인
├── chapters/             # 본문 7장
├── references/           # 13개 상세 자료·사례·출처 색인
├── glossary.md           # 용어
├── patterns.md           # 작성자의 계획·복기 양식
├── cheatsheet.md         # 빠른 점검
├── source.json           # 원본 지문·장/소절·쪽 대응·한계
└── agents/openai.yaml    # Codex 표시 메타데이터
```

| 장 | 원문 제목 | 활용 |
|---|---|---|
| [1](.agents/skills/danswer-market-trading/chapters/ch01-survival-and-learning.md) | 나는 주식에 모든 것을 걸었다 | 실패·소액 훈련·동료 비교 |
| [2](.agents/skills/danswer-market-trading/chapters/ch02-market-perspective.md) | 관점 만들기, 시황과 돈의 흐름 | 시황·장전 시나리오·2-2-2 |
| [3](.agents/skills/danswer-market-trading/chapters/ch03-stock-selection.md) | 가장 효율적인 종목 선정법 | 재료·0순위·수급·거래원 |
| [4](.agents/skills/danswer-market-trading/chapters/ch04-five-weapons.md) | 나의 다섯 가지 트레이딩 무기들 | 종가·돌파·테마·수급·상따 |
| [5](.agents/skills/danswer-market-trading/chapters/ch05-worker-trading.md) | 직장인과 자영업자를 위한 매매 | 가용 시간·본업·전업 준비 |
| [6](.agents/skills/danswer-market-trading/chapters/ch06-risk-and-capital.md) | 잃지 않는 트레이더가 되는 법 | 손절·추가 매수·미수·출금·비중 |
| [7](.agents/skills/danswer-market-trading/chapters/ch07-routine-and-psychology.md) | 방 안의 시간, 트레이더의 일상과 심리 | 루틴·일지·슬럼프·생활 기반 |

### 상세 참조는 어디에 있나요?

[참조 색인](.agents/skills/danswer-market-trading/references/index.md)에서 질문으로 자료를 고릅니다. 4장은 [종가](.agents/skills/danswer-market-trading/references/closing-bet.md)·[돌파](.agents/skills/danswer-market-trading/references/breakout.md)·[테마](.agents/skills/danswer-market-trading/references/theme-trading.md)·[수급](.agents/skills/danswer-market-trading/references/flow-trading.md)·[상따](.agents/skills/danswer-market-trading/references/limit-up.md)의 상세 파일로 이어집니다. [사례 색인](.agents/skills/danswer-market-trading/references/case-index.md)은 번호 붙은 사례 22개와 LG 비교 1개를 구별한 **탐색 항목 23개**를 연결합니다.

[HTS 부록](.agents/skills/danswer-market-trading/references/hts-setup.md)은 화면의 목적을, [저자 맥락](.agents/skills/danswer-market-trading/references/author-context.md)은 프롤로그·에필로그·수익인증의 범위를 설명합니다. 전체 자료가 책의 원문·모든 차트·QR 영상 복제본인 것은 아닙니다.

---

<a id="guides"></a>

## 상세 가이드

| 문서 | 내용 |
|---|---|
| [가이드 홈](docs/index.md) | 읽는 순서와 목적별 안내 |
| [시작하기](docs/getting-started.md) | 입력·자료 선택·첫 답변 확인 |
| [에이전트별 사용](docs/agents.md) | Codex·Claude Code·Antigravity 호출과 범위 |
| [작업 흐름](docs/workflow.md) | 학습·계획 검토·복기·변경 후 확인 |
| [고급 활용](docs/advanced-usage.md) | 고급 예시 32개·후속 요청 15개, 매매법별 조건·예외 심화 |
| [검수와 시험](docs/validation.md) | 출처·기간·비중·계산·독립 시험의 확인 기준 |
| [문제 해결](docs/troubleshooting.md) | 인식·파일·누락·원문 확인 문제 |

---

<a id="source"></a>

## 출처와 검증 범위

- 참고 도서: 이진호(디앤서), 『실전 시황 트레이딩』, 사피엔테스(주)·스티어(Steer).
- 제공 원문: 299쪽 PDF. 판권의 초판 발행일 **2026-10-21**은 제공본의 표기이며, 검수일 2026-10-14 시점의 실제 유통 확인과 구분합니다.
- 지문·장/소절·인쇄/PDF 대응: [출처 메타데이터](.agents/skills/danswer-market-trading/source.json), [쪽 대응](.agents/skills/danswer-market-trading/references/source-map.md).
- 기존 복구 기록과 이번 후속 검증의 증거는 [검수 가이드](docs/validation.md)에서 구별합니다. 코드 형식·내용 대조·한국어 문장과 용어·독립 응답·실제 호출은 각각 다른 검증입니다.
- 이번 참조 보완의 원문 대조·실패 보존·재시험은 [skill-creator 검토 보고서](_workspace/skill-creator-review/2026-10-14/report.md)에 있습니다. 이 기록과 실제 활용 예시의 시험은 구분합니다.

> [!WARNING]
> 책과 이미지의 권리는 권리자에게 있습니다. 원본 PDF·전체 추출 원문·계좌 화면은 설치·공개 배포 대상에서 제외합니다. 정확한 도판 판독이 필요할 때는 접근 가능한 원문의 해당 쪽을 확인합니다. 외부 QR 영상과 모든 차트 숫자를 전수 확인한 자료는 아닙니다.

한국어 표현은 [DaleSeo/korean-skills](https://github.com/DaleSeo/korean-skills)의 humanizer→grammar-checker→style-guide로 검수합니다. 원문 조건과 전문 용어를 보존하는 기준, 이전 수동 검증과 새 자동 검증의 구분은 [검수 가이드](docs/validation.md)에 있습니다.

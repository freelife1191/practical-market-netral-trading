# 시작하기

## 준비할 입력

학습은 주제나 장 번호만으로 시작할 수 있습니다. 계획 검토에는 날짜·시장·자료 출처·재료·가격 위치·수급·관찰 가능한 시간·확정/미정 조건이 필요합니다. 일지에는 당시 실제로 본 자료와 사후에 확인한 결과를 구분해 적습니다. 민감한 계좌 식별 정보는 자료 선택에 필요하지 않습니다.

## 첫 요청

```text
$danswer-market-trading 시황→관점→종목 선정→기법의 관계를 가상 예시로 설명해줘.
2장과 필요한 3장을 먼저 읽고, 후보 관찰과 매수 확정의 차이를 보여줘.
책의 원칙·가상 입력·작성자의 제안을 구분하고 확인 문제 3개를 내줘.
```

확인할 것은 **어떤 파일을 읽었는지, 어떤 조건이 아직 없으며, 그때 왜 관망하는지**입니다. 파일 링크가 있다는 이유만으로 실제 내용을 읽었다고 단정하지 않습니다.

## 장 번호를 모를 때

| 질문 | 자료 경로 | 이어 읽기 |
|---|---|---|
| 퇴근 뒤 후보를 보고 싶다 | [5장](../.agents/skills/danswer-market-trading/chapters/ch05-worker-trading.md) | 종가 상세 → 6장 |
| 대장·후속주가 헷갈린다 | [테마 상세](../.agents/skills/danswer-market-trading/references/theme-trading.md) | 3장 → 6장 |
| 프로그램 숫자 하나로 진입해도 되나 | [3장](../.agents/skills/danswer-market-trading/chapters/ch03-stock-selection.md) | 수급 상세 |
| 선도전기 사례를 찾고 싶다 | [사례 색인](../.agents/skills/danswer-market-trading/references/case-index.md) | 상따 상세·PDF 위치 |
| 손실 뒤 금액을 키웠다 | [6장](../.agents/skills/danswer-market-trading/chapters/ch06-risk-and-capital.md) | 1장·7장 |

자세한 경로는 [참조 색인](../.agents/skills/danswer-market-trading/references/index.md)에서 찾습니다. 정확한 수치가 필요하면 인쇄쪽과 PDF쪽을 함께 확인합니다. 책 전체에 같은 쪽수 차이를 적용하지 않습니다.

## 같은 대화와 새 대화

같은 대화에서는 “방금 표의 미확인 조건만 보완해줘”처럼 좁힙니다. 새 대화에서는 기존 표·자료·확정 조건을 다시 제공합니다. 원문 없이 책에 없는 내용을 질문하면 원문 확인 필요와 미확인을 구분하도록 요청합니다.

[다음: 작업 흐름](workflow.md) · [고급 예시](advanced-usage.md)

## 명확한 주도 섹터가 없을 때

```text
$danswer-market-trading 주도 섹터가 명확하지 않은 가상 상황이야.
개별 실적·수주·정책 재료를 어떻게 관찰할지 3장과 선정 상세를 읽고 설명해줘.
재료 이름만으로 진입을 확정하지 말고 필요한 거래대금·변동성·가격 반응을 질문으로 남겨줘.
```

주도 섹터를 먼저 보는 원칙과, 명확한 주도 섹터가 없을 때 강한 개별 재료를 살피는 갈래를 함께 확인합니다.

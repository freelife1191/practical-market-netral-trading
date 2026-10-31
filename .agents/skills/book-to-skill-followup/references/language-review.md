# 한국어 마지막 검수

이 단계는 `improvement` 다음, `freeze` 직전에 현재 대상 스킬과 선언 문서를 실제로 읽고 수행한다. 담당자는 기존 `release-reviewer` 역할을 사용한다. 상시 새 에이전트 프로필은 만들지 않는다.

## 순서와 범위

vendored 파일 `assets/korean-skills/skills/humanizer/SKILL.md`, `grammar-checker/SKILL.md`, `style-guide/SKILL.md`를 다음 정확한 순서로 읽는다.

1. `humanizer`로 부자연스러운 AI 작문 패턴과 어색한 문장을 문맥으로 판정한다. 이 스킬의 추정 AUC는 문장별 검수 점수나 통과 근거가 아니다.
2. `grammar-checker`로 맞춤법·띄어쓰기·문법·구두점을 확인한다.
3. `style-guide`로 문서 전체 어조·용어·숫자·목록·인용·날짜·링크 표기의 일관성을 확인한다.

현재 subject snapshot의 `.md`, `.markdown`, `.json`, `.yaml`, `.yml` 파일을 빠짐없이 `reviewed_files`에 경로와 SHA-256으로 기록한다. 영어 source, 원문 제목, 코드 블록, 식별자, URL, 해당 분야의 전문 용어는 문맥상 맞으면 보존한다. 자동 스캔의 존재나 정규식 일치만으로 어색한 문장 검수가 끝났다고 보고하지 않는다.

## 보정과 재실행

문장·용어를 고칠 필요가 있으면 `freeze` 전에 coordinator가 대상의 선언 write set만 최소 수정한다. 대상 지식·레퍼런스를 고쳤으면 `revise --from-stage skill-refinement --reason '한국어 마지막 검수 finding: …'`을, README·가이드 등 문서만 고쳤으면 `revise --from-stage documentation --reason '한국어 마지막 검수 finding: …'`을 기록한다. 두 경로 모두 정적 검사·독립 행동 시험·보완·언어 검수·freeze와 그 뒤 단계를 stale로 만들고, 수정된 subject에서 새 증거를 만든다. run당 최대 2회 보완 제한을 넘기지 않는다. `freeze` 이후에는 교정하지 않고 새 run을 시작한다.

`blockers` 또는 `remaining_findings`가 있으면 이 게이트를 pass로 끝내지 않는다. 작성자와 다른 reviewer가 사람이거나 새 컨텍스트의 에이전트인지, 별도 검토 기록 파일과 SHA-256으로 남긴다. Codex agent 검토는 실제 fresh native dispatch의 `fork_turns: none` 기록과 execution record를 결속한다. Claude와 Antigravity agent 검토는 같은 호스트의 native surface, `fresh_context: true`, 실제 session ID와 execution record를 결속한다. human 검토는 실제 검토 주체를 기록한다. 각 pipeline 단계의 검토 기록과 vendored 스킬·subject 파일 전체의 UTF-8 JSON read manifest도 결속한다.

이 보조기는 vendor tree·파일 해시·기록 구조·선언된 reviewer와 dispatch만 검사한다. 파일이 존재하거나 길이가 충분하다고 해서 실제 독립성, 어색함 판정, 또는 의미 보존을 자동으로 증명하지 않는다. 실제 검토자는 세 단계 결과와 대상 문맥을 읽어 판단한다. 아래 예시는 구조 시험용 mock으로, 실제 독립 검토 기록이 아니다.

## pass 증거 예시

```json
{
  "verdict": "pass",
  "subject_digest": "현재 subject digest",
  "reviewer_id": "independent-language-reviewer",
  "pipeline": ["humanizer", "grammar-checker", "style-guide"],
  "upstream_skills": [
    {"id": "humanizer", "path": "assets/korean-skills/skills/humanizer/SKILL.md", "sha256": "vendored SHA-256", "commit": "ae12ba27982ebeff03b46dc738365aaa34260d9a"}
  ],
  "reviewed_files": [{"path": ".agents/skills/target/SKILL.md", "sha256": "현재 SHA-256"}],
  "pipeline_records": [
    {"id": "humanizer", "reviewer_id": "independent-language-reviewer", "path": "release-reviewer/humanizer.md", "sha256": "검토 기록 SHA-256"}
  ],
  "read_manifest": {"path": "release-reviewer/read-manifest.json", "sha256": "manifest SHA-256", "skills": ["upstream_skills 전체"], "subject_files": ["reviewed_files 전체"]},
  "review_method": {"kind": "agent", "reviewer_id": "independent-language-reviewer", "fresh": true, "dispatch": {"surface": "codex-native", "fork_turns": "none"}},
  "execution_record": {"path": "release-reviewer/dispatch.json", "sha256": "dispatch SHA-256", "reviewer_id": "independent-language-reviewer", "method": "agent"},
  "meaning_preservation": {
    "conditions": true,
    "numbers": true,
    "citations": true,
    "negations": true,
    "periods": true,
    "attributions": true
  },
  "blockers": [],
  "remaining_findings": [],
  "independent_review_evidence": [{
    "kind": "agent",
    "reviewer_id": "independent-language-reviewer",
    "path": "release-reviewer/language-review.md",
    "sha256": "검토 기록 SHA-256"
  }]
}
```

실제 evidence에는 세 `upstream_skills` 항목이 pipeline과 같은 순서로 모두 있어야 한다. `provenance.json`의 commit·파일 SHA-256과 다르면 state checker가 거부한다.

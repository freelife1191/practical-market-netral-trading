# 실행·증거 계약

보조기는 구조와 해시를 확인한다. JSON만 채웠다고 실제 작업을 수행한 것이 아니다. 실행 전에 하위 명령 --help를 확인한다. init은 프로젝트·상대 스킬·원문 절대 경로(반복 가능)·상대 문서 경로(반복 가능)·호스트를 받으며 _workspace/harness/book-to-skill-followup/<run-id>/에 기록한다.

원문 source, 설치된 후속 스킬 toolchain, 대상 지식·문서·관련 프로필 subject의 fingerprint를 분리한다. run과 캐시는 subject에서 제외한다. artifact는 run 상대 실제 regular file이며 symlink/루트 탈출을 허용하지 않는다. source 외부 입력은 명시적 읽기 전용이다.

toolchain의 fingerprint는 제작 도구를 책 subject에 복사하라는 뜻이 아니다. 실행·배포 위치는 [배포 분리](packaging.md)를 따른다. 정적 검사의 파일·링크·해시 범위와 배포 혼입 검사의 파일시스템·Git index·제외 범위를 따로 적는다. 검사된 책 자료 밖의 도구를 배포로 포함하지 않으며 실제 아카이브는 별도 파일 목록을 확인한다.

## 단계별 구조

공통 verdict는 pass/fail/blocked다. 검사 단계는 snapshot의 현재 digest를 subject_digest로 기록한다. 제작자 producer_id는 run 상태에 있고 독립 reviewer/evaluator는 다른 실제 세션 ID를 쓴다.

| 단계 | 내용 |
|---|---|
| preflight | project/skill_rel/source_hashes/write_paths를 init 상태와 결속, scope_confirmed: true |
| inventory | expected_unit_ids, units: id/source_path/source_locator/skill_files/status/reason |
| source-audit | 전체 units, claims: id/unit_id/origin/source_locator/verdict, reviewer_id, visual_candidates/visual_checks |
| skill-refinement | changes: 상대 path/이유, units_covered, resolutions |
| documentation | units_covered, reviewed_prompt_ids, 전체 전략·장별2예시/후속1·공통4/연계3 의미 검토 |
| static-checks | 검사기의 errors/scanned_files/files_digest/subject_digest/project/skill과 현재 스냅샷 일치 |
| behavior-tests | subject_digest, cases: retrieval/application/critique 각 1개 이상과 발견 오류 regression |
| improvement | changes, units_covered, revisions(상태의 현재 값), 보완·재검사 범위 |
| language-review | subject_digest, 제작자와 다른 reviewer_id, `humanizer → grammar-checker → style-guide` pipeline, pinned upstream path/hash/commit, reviewed_files, meaning_preservation, 빈 blockers/remaining_findings, 별도 human/agent 검토 기록 |
| freeze | subject_digest, 독립 reviewer_id, blockers 빈 배열, addressed_findings, independent_review_evidence와 직접 내용 검토 |
| host-smoke | host/returncode/loaded/turn_completed/subject_digest/trace_file/trace_sha256/proof_files와 한계, Claude는 native_skill_load |
| final-review | subject_digest, 독립 reviewer_id, blockers, post_host: true |

changes는 허용된 프로젝트 상대 path만 쓴다. 변화가 없으면 빈 배열이다. inventory status는 mapped/missing/excluded이며 누락/제외는 reason을 쓴다. 주장 origin은 author/synthesis/validation-guidance/proposal이다.

source-audit의 pass는 전체 감사를 수행해 발견 사항을 정확히 기록했다는 뜻이다. 초기 스킬에서 mismatch/needs-refinement를 발견하면 finding으로 보존하고 다음 보완 단계로 진행한다. 원문에 접근하지 못했거나 단위를 실제 검토하지 못한 경우는 blocked다. 최종 freeze에서는 중요한 미해결 오류·누락을 차단한다. 원문 자체의 불확실성을 정확히 표시하는 것은 결함과 구분한다.

source-audit units는 id와 verdict(pass 또는 needs-refinement)를 갖는 객체다. claims는 각 단위의 id/unit_id/origin/source_locator/verdict(pass/mismatch/uncertain) 객체이며 전체 단위에 최소 하나씩 있어야 한다. source_path는 선언된 원문, skill_files는 대상 스킬 아래 프로젝트 상대 파일이다.

단위별 최소 claim 하나는 구조 검사의 하한이며 상세 내용 충실도의 통과 기준이 아니다. 의미 검토에서는 [원문 검수](source-audit.md)의 기법·성립 조건·예외·대조 사례까지 대조하고 필요한 claim과 근거 위치를 나눈다. 문서 인계에서는 [문서 구성](documentation.md)의 조건 판정·근거·미확인 사항을 실제 선행/후속 요청으로 확인한다. 적용 판단의 네 상태를 source-audit verdict나 실행 상태와 섞지 않는다.

보완할 claim(mismatch)은 claim:<id>, unit(needs-refinement)은 unit:<id>로 식별한다. skill-refinement의 resolutions는 이 ID 전체를 정확히 포함하는 id/kind/reason/paths 객체 목록이다. kind는 fixed/documented/false-positive이며 실제 파일 위치와 처리 이유를 적는다. findings가 없으면 빈 배열이다. freeze의 addressed_findings는 같은 전체 ID 목록이고 독립 검토자는 실제 파일에서 처리가 적절한지 확인한다. ID를 채우는 것만으로 의미상 해결된 것은 아니다.

behavior case는 id/kind/fresh/evaluator_id/verdict/input_file/answer_file/rubric_file/assertions/read_files를 가진다. 기본 kind는 retrieval/application/critique, 추가 오류 사례는 regression이다. input/answer/rubric은 run 상대 파일이다. rubric은 결과를 보기 전에 고정하고 수행자에게 예상 답안을 누설하지 않는다. assertions는 id/passed/reason 객체이며 실제 의미를 검토한다.

read_files는 path/sha256/scope를 기록한다. scope=project는 프로젝트 상대 경로, run은 run 상대 경로, source는 선언된 원문의 절대 경로다. 목록이 없으면 빈 배열이며 증거 종류를 별도로 표시한다. 실존·해시 확인은 실제 과거 tooltrace를 대체하지 않는다. 추가 rubric·원래 trace 등 참조 자료는 evidence_artifacts의 path/sha256/scope로 결속한다.

대표 연계 시험은 기존 case와 input/answer/evidence_artifacts로 선행 결과·채운 후속 입력·새 컨텍스트의 후속 답변을 연결한다. 앞선 결과를 후속 입력으로 제공한 것과 평가 결론을 누설한 것을 구분한다. 시험한 버전·실제 읽기 범위·판정 기준을 기록하고 전체 문서 검토와 수행한 case의 통과 범위를 별도로 보고한다.

host proof_files는 run 상대 path/sha256 객체 목록이다. trace_file의 JSON에는 실제 호스트 로그에서 추출한 성공 read 이벤트와 turn.completed가 있어야 하고, 격리 복사한 SKILL.md가 읽힌 증거를 포함해야 한다. 정상 종료와 loaded 자기 주장만으로는 부족하다. Claude는 `Skill` 도구로 스킬을 불러올 때 SKILL.md를 Read로 읽지 않는다. 그래서 성공한 `Skill` 결과 바로 다음의 합성 메시지가 격리 복사본의 기준 경로와 고정 SKILL.md 본문에 정확히 맞을 때만 그 SKILL.md read로 정규화한다. 세부 조건은 [호스트 연동](host-adapters.md#claude-code-로드-증거와-격리)을 따른다. record의 `native_skill_load`는 Read로 연 기록과 네이티브 로드를 구분하며, verify가 원래 로그에서 다시 계산한 값과 같아야 한다.

language-review의 `pipeline`과 `upstream_skills`는 `humanizer`, `grammar-checker`, `style-guide` 순서의 정확한 3개 항목이다. 각 upstream 항목은 `id`, `path`, `sha256`, `commit`을 가지며 `assets/korean-skills/provenance.json`의 DaleSeo/korean-skills commit `ae12ba27982ebeff03b46dc738365aaa34260d9a`와 현재 vendored `SKILL.md` 바이트에 일치해야 한다. provenance는 자체 파일을 제외한 vendor tree의 모든 regular file을 중복 없는 path/SHA-256으로 정확히 선언하고, symlink·누락·미선언 파일·변조를 허용하지 않는다. `LICENSE`에는 비어 있지 않은 MIT 고지가 있어야 하며 local patch는 원본·bundled SHA-256을 기록한다.

`reviewed_files`는 현재 subject의 Markdown·JSON·YAML 파일을 path/sha256으로 정확히 전부 열거한다. `pipeline_records`는 세 단계 각각의 run 상대 검토 기록을 같은 순서로 path/sha256 결속한다. `read_manifest`는 UTF-8 JSON으로 같은 `upstream_skills`와 `reviewed_files`를 포함해 실제 읽기 범위를 결속한다. `review_method`와 UTF-8 JSON `execution_record`는 reviewer_id와 검토 방식을 결속한다. agent 방식은 `fresh: true`를 기록한다. Codex run은 `dispatch.surface: codex-native`, `dispatch.fork_turns: none`을 요구한다. Claude/Antigravity run은 각각 `claude-native`/`antigravity-native` surface, `fresh_context: true`, 실제 session_id를 요구한다. execution record도 같은 dispatch를 보관한다. human 방식은 실제 검토 주체를 기록한다. `meaning_preservation`은 `conditions`, `numbers`, `citations`, `negations`, `periods`, `attributions` 여섯 boolean true만 가진다. `independent_review_evidence`는 reviewer_id가 주 reviewer와 같고 kind가 human 또는 agent인 run 상대 검토 기록 파일의 path/sha256을 적어 해시 결속한다.

이 Python 검사는 파일·해시·선언된 주체·fresh dispatch 기록만 확인한다. 파일 존재, 길이, JSON 구조, 또는 metadata가 실제 독립성이나 내용·의미 보존 판정을 자동으로 증명하지는 않는다. 실제 검토자는 세 단계 결과와 문맥을 읽고 그 판정을 기록한다. 단위 fixture는 이 구조 검증을 위한 mock이며 실제 독립 검수 기록이 아니다.

## 무효화와 완료

증거·case 입력/답변/rubric/trace의 해시를 결속한다. 최초 실패를 보존하고 정정·재생성·새 독립 평가를 분리한다. 생산 단계는 내용을 바꿀 수 있지만 검사 이후의 변경은 관련 검증을 stale로 만든다. source/spec/toolchain 변경은 이전 완료 근거를 무효화한다. 보완 뒤 필요한 단계를 재실행한다.

제작자 ID를 지정하지 않으면 run별 coordinator ID를 발급한다. 실제 수행·검토 세션 ID를 기록하고 보완 후 최종 평가자는 이전 통과 평가자를 재사용하지 않는다. 보조기의 ID/메타데이터 검사는 실제 프로세스 격리를 자동 증명하지 않으므로 네이티브 호출의 fresh 설정과 가능한 도구 trace를 함께 검토한다. language-review에서 미해결 finding 또는 보정이 나오면 `freeze` 전에 revise로 관련 static-checks·behavior-tests·improvement·language-review를 새 subject에 맞춰 다시 실행한다.

verify는 실제 파일/해시/단계 의존성을 확인한다. finalize는 모든 필수 성공과 유효한 1회 host 증거를 요구한다. host 증거는 normalized trace 외에 run 상대 raw_trace_file/raw_trace_sha256, 비어 있지 않은 UTF-8 answer_file/answer_sha256, answer_event_id를 가진다. helper의 host별 순수 terminal-answer extractor가 raw trace에서 찾은 event ID·정확한 텍스트와 answer_file을 일치시켜야 한다. 같은 helper가 raw trace와 격리 복사 project에서 재계산한 normalized events는 trace.events와 순서까지 정확히 일치해야 하며, bound proof의 실제 read와 turn.completed도 이 raw-derived 결과에서 확인한다. proof는 정확히 `host/project/.agents/skills/<skill-id>/SKILL.md`여야 하고, frozen source master와 복사본 master는 regular file·비symlink·동일 SHA-256이어야 한다. source skill subtree와 copied skill subtree의 `digest_tree` 결과는 `copy_digest`/`copied_files`와 정확히 같아야 한다. host project의 별도 profile 복사는 이 subtree 비교 범위 밖이다. 이 파일들은 모두 archive에 결속한다. normalized read·turn 이벤트만 있고 임의 answer 파일을 둔 기록은 통과하지 않는다. frozen subject가 바뀌거나 호스트 후 수정이 필요하면 새 run을 만든다. host/최종 결과를 스킬 source.json에 덧붙여 검증 버전을 바꾸지 않고 기록에만 저장한다. GUI와 다른 호스트의 미검증은 별도 한계다.

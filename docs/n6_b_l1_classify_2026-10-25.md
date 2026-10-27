# N6 B L1 분류 스크립트 (2026-10-25)

상태: 완료. 승인·담당: miiz. 새 파일은 `scripts/n6_b_l1_classify.py`와 이 기록뿐이다. 이번 지시의 기존 파일 수정·cargo 실행 금지가 우선하므로 계획 표는 갱신하지 않았다. B 판정 데이터 열람·분류 실행, 엔진·빌드·Docker·설치, 실행 중인 프로세스 조작, git 쓰기는 하지 않았다.

스크립트는 [N5 개정 §4 1·2항](n5_amendment_b_judging_2026-10-17.md)에 따라 L1의 공개 입력·공개 출력·entrypoint를 분류한다. JSON에는 요청 ID·리비전 ID·클래스 번호와 분류 필드·건수만 쓴다. 입력·witness·신호 값·후보 내용은 출력하지 않는다. 오류에도 원문 값이나 예외 내용을 넣지 않는다.

입력은 `--index PATH --index-sha256 SHA`와 `--state PATH --state-sha256 SHA`, 또는 반복 가능한 `--result PATH SHA`다. state의 `result_path/result_sha256`만 따라가며 요청·후보·로그·캐시 파일은 열지 않는다. 모든 JSON은 **읽은 바이트의 SHA-256을 확인한 뒤** 파싱하고 결과의 요청 해시를 index에 대조한다. 해시 불일치·중복 요청·인스턴스 도달/배제 충돌은 거부한다. 미제공·미완료·준비 실패는 `unclassified_requests`로 남긴다. 엔진별로 따로 실행하며, 일부 결과만 제공하면 공유 도달의 범위도 그 부분집합으로 제한된다.

| 항목 | 매핑과 소스 근거 |
|---|---|
| 결과 위치·연결 | B6g/h의 `.../requests/.../attempt-NNNN/result.json`, state의 경로·해시. `scripts/n6_b6g_j_runner.py:374`, `scripts/n6_b6h_j_runner.py:390`, `:403`, `:873`. 두 엔진 모두 `zkfdo-lifting-result-v1`과 `classes[]` 사용 |
| L1 | 자체 `verdict == entrypoint_violation` 또는 공유 집계의 `assumption_violation_reachable`. `scripts/n6_b6h_result_gate.py:129`–`:137`. `assumption_input_reachable` 단독은 L1 아님 |
| 공유 집계 | 모든 제공 결과의 predicate를 `(scope, revision_id)`별로, entrypoint의 R1CS·sym·O0 R1CS 해시와 instance로 합침. target 중 하나라도 도달이면 effective 도달. `src/candidate_review/lifting/instances.rs:83`–`:105`, `:119`–`:170`. 엔진 실행 없이 이 규칙만 재현 |
| 공개 입력 | `ClassResult.public_inputs_equal`: true → `private_reach`, false → `public_input_change_reach`, 누락/null → `unknown`. unknown은 실제 후보 조건을 충족하지 않음. `src/candidate_review/lifting/mod.rs:190`–`:206`, `:2224`–`:2226` |
| 공개 출력 | `outputs_differing > 0` → `output_change`, 0 → `internal_only`, 누락/null → `unknown`. **main 공개 출력 wire `1..=public_outputs`만** 비교하며 공개 입력·내부 신호는 포함하지 않음. `src/candidate_review/lifting/mod.rs:2221`–`:2232`, `src/candidate_review/r1cs.rs:62`–`:65` |
| entrypoint | index의 `(revision_id, original_entrypoint)` 우선, 이후 `main_file/main/entrypoint`를 표의 `(revision_id, main_file)`에 정확히 대응. 미일치·main 누락은 harness. 표 형식은 `scripts/n6_b5_batch1_prepare.py:413`–`:424`, staging 이전 main 보존은 `scripts/n6_b6b_batch1x_prepare.py:269`–`:272`, `scripts/n6_b6g_j_runner.py:211`–`:235` |
| 최종 분류 | **동일 L1 클래스**의 `private_reach × output_change × deployed`만 `real_vulnerability_candidate=true`; 나머지는 `constraint_defect_confirmed`. 요청은 실제 후보 클래스가 하나라도 있으면 실제 후보로 셈. 요청 수와 클래스 수를 별도 출력 |

고정 v1 소스 `cb40e3e0`와 v2.2 `8065e2b7`의 인스턴스 집계 구현이 동일함을 소스로 확인했다. v1의 공개 입력·출력 비교도 같은 의미다(`src/candidate_review/lifting/mod.rs:2072`–`:2086`, 해당 리비전 기준). 위 표의 다른 줄 번호는 현재 소스/v2.2 기준이다.

**해석 한계:** `public_inputs_equal`은 합성·치환 이후 같은 입력으로 만든 두 witness의 비교이며 원래 기준 입력의 공개 값 보존을 독립적으로 입증하지 않는다(`lifting/mod.rs:1902`–`:1908`, `:2014`–`:2032`). honest 비교자는 다른 hint 주입·수리를 유지할 수 있다(`:2007`–`:2023`). 공유 predicate 도달의 witness와 클래스의 출력 비교 witness도 다를 수 있다(`:977`–`:990`, `lifting/predicate.rs:337`–`:387`). 지시대로 클래스 필드를 매핑하되 `public_input_comparison`, `public_output_comparison`, `comparison_evidence`, `l1_basis`에 한계를 표시한다. 누락값을 도달 판정이나 다른 요청의 값으로 보충하지 않는다.

일반 모드는 `--entrypoint-table PATH --entrypoint-table-sha256 SHA`가 필수다. 지정 표 `runs/n6-b5-2026-10-17.noindex/batch1-prep.noindex/entrypoint-classification.json`의 SHA-256을 **`126745ca432de49f4ee7bdf901d8f4eb81082b96eb11b4b623c29f61057bd660`으로 확인한 뒤** 형식만 확인했다. 스크립트도 이 고정 해시가 아니면 거부한다. `--a-calibration`은 모든 읽기 경로를 지정된 A 보정 폴더 안으로 제한하며, 표 생략 시 전부 harness다. 같은 형식의 A 표와 해시를 명시할 수도 있다.

A 시험 명령(저장소 루트, 출력 JSON은 메모리에서 검산하고 파일로 저장하지 않음):

```sh
A=runs/n6-b6-2026-10-18.noindex/a-calibration.noindex
python3 -B scripts/n6_b_l1_classify.py --a-calibration \
  --index "$A/prepared/strict-request-index.json" \
  --index-sha256 c8f8f1aa9b12a953b78685bafda49d7afe02edf2b0c2c27016dd2d71eee0f362 \
  --state "$A/strict-j/state.json" \
  --state-sha256 e62a28db4f994995b3e063dd48daf86cee4ec63cccbbefdc1bb80f5e593072bb
python3 -B scripts/n6_b_l1_classify.py --a-calibration \
  --index "$A/prepared/constructed-request-index.json" \
  --index-sha256 ebf7fa598fc1ddb4fd9f8e42e7376ab5e99429ccc4ff110c3b83df72151c5fe5 \
  --state "$A/constructed-j/state.json" \
  --state-sha256 5625b73a5e52b5a9802447089a4faf7e283c40df811f0e9f4cbd9b0fd7c0f55f
```

| A 자료 | 전체 요청 | L1 요청 / 클래스 | 사설 / 공개 입력 변경 / 미상 클래스 | 출력 변경 / 내부만 / 미상 클래스 | 실제 후보 요청 / 제약 결함 요청 |
|---|---:|---:|---:|---:|---:|
| strict | 122 | 80 / 90 | 20 / 0 / 70 | 20 / 0 / 70 | 0 / 80 |
| constructed | 122 | 54 / 54 | 0 / 0 / 54 | 0 / 0 / 54 | 0 / 54 |

두 실행 모두 미분류 요청 0, 모든 L1 클래스 harness(각 90·54), 제약 결함 클래스 각 90·54다. non-L1은 각 42·68요청이다. 기존 A `summary.json`의 L1 요청 ID 집합과 일치했다. state 방식과 모든 result 경로·해시를 명시한 방식의 JSON이 같았고, index/state/result 해시 불일치 및 잘못된 고정 표 해시의 거부를 확인했다. 출력 필드 허용 목록도 확인했다.

`python3 -m py_compile scripts/n6_b_l1_classify.py` 통과. `PYTHONPYCACHEPREFIX`를 임시 폴더로 지정하고 검사 뒤 제거했다. 실제 후보의 0건은 **A harness 대체 모드의 결과**이며 B 결과가 아니다.

`shasum -a 256 scripts/n6_b_l1_classify.py`:

```text
e162d44058bfcee3c324d64862e0ca3c66ea713675d0d85f498ed60094d16ac5  scripts/n6_b_l1_classify.py
```

# 후보 검토 공통 형식 설계

작성일: 2026-09-26. **상태: T4a 결정, T4b 구현 전.** 이 문서는 기존 v1.1·v2·v3 판정 파일을 바꾸지 않고, 이후 backend 후보 검토와 주입 결함 ground truth 검증에 쓸 공통 형식을 정한다. 구현 중 의미를 바꿔야 하면 이 문서를 조용히 고치지 않고 새 버전과 변경 이유를 남긴다.

## 1. 목표와 경계

공용 검토 엔진은 다음 두 흐름을 같은 판정 핵심으로 처리한다.

1. **backend 후보 검토:** 저장된 plan·outcome의 후보가 입력 계약을 만족하고, 고정된 대상 R1CS 전체 제약을 만족하며, 실행 전에 정한 속성을 위반하는지 확인한다.
2. **주입 ground truth 검증:** 교란 쌍둥이가 만든 assignment가 위 세 조건과 clean relation exclusion, production 도달을 모두 만족하는지 zkFuzz 없이 확인한다.

두 흐름은 같은 값 없는 report 형식을 쓰지만 의미는 섞지 않는다. 주입 ground truth는 평가 전에 알려진 정답을 만드는 자료이지 execution discovery가 아니다. `experiment evaluate --confirmations`에 넣는 schema 2 confirmation은 저장된 backend 실행 후보에서만 만든다.

다음은 이 작업의 범위가 아니다.

- 기존 고정 protocol, manifest, contract, 실행 결과, 판정 파일 수정
- property를 후보 결과를 본 뒤 만드는 일
- 파일 존재나 사람이 적은 verdict만으로 substantive 판정을 참으로 간주하는 일
- component 판정만으로 project 도달성을 추정하는 일
- 원시 signal·input·witness 값을 Git 추적 파일이나 표준 출력에 쓰는 일

## 2. 기존 형식에서 확인한 차이

| 항목 | v1.1·v2 | v3 | 공통 형식의 결정 |
|---|---|---|---|
| 실행 단위 | campaign ledger의 36개 plan/outcome | plan/outcome 한 쌍 | request가 plan/outcome 쌍을 1개 이상 가진다 |
| 사례 설정 | 경로·target·root cause·predicate가 스크립트에 하드코딩 | Decoder 한 건에 하드코딩 | 경로·해시·계약·predicate를 review-spec으로 이동한다 |
| 후보 수 | 정확히 36개를 요구 | 정확히 1개를 요구 | 모든 outcome의 후보 0..N개를 전부 열거한다 |
| 결과 배열 | `candidate_reviews` | `reviews` | `reviews` 하나로 통일한다 |
| 세 기준 | evidence·note 포함 | confirmation에 evidence·note를 수작업 복사 | report에서 한 번 만들고 confirmation을 기계적으로 파생한다 |
| R1CS | review와 prepared의 현재 파일 해시를 비교 | 같은 방식 | 실행 전 기대 raw SHA-256을 spec에 고정한다 |
| SYM | 현재 파일 해시만 기록 | 현재 파일 해시만 기록 | 기대 raw SHA-256과 signal/wire 대응 규칙을 함께 고정한다 |
| field 값 | canonical 여부를 기록하지만 v1.1·v2 disposition에는 미사용 | canonical 여부를 제약 판정에 포함 | 모든 실제 R1CS wire 값에 canonical 표현을 요구한다 |
| 빈 결과 | 전체 스크립트 실패 또는 행 없음 | 전체 스크립트 실패 | 후보가 없는 run을 정상적인 `no-candidate` 실행 행으로 기록한다 |
| 오류 | 첫 예외에서 전체 중단 | 첫 예외에서 전체 중단 | 공유 입력 무결성 실패와 후보별 review error를 구분한다 |

기존 세 실험의 보존 후보는 모두 canonical field 표현을 사용하므로 canonical 규칙을 강화해도 기대 판정은 바뀌지 않는다. 회귀 목표는 과거 스크립트의 우연한 누락까지 복제하는 것이 아니라, 보존된 세 원인의 substantive 판정과 evaluator 결과를 같은 의미로 재현하는 것이다.

## 3. 산출물과 해시 방향

공용 형식은 역할이 다른 네 종류의 파일을 둔다.

1. **review-spec:** 사례의 고정 의미. 대상 source/R1CS/SYM, 입력 계약, 사전 속성, root cause와 scope를 가진다.
2. **review-request:** 이번 검토의 값 있는 원시 입력과 실행 연결. backend plan/outcome 묶음 또는 주입 twin assignment를 가리킨다.
3. **review-report:** 판정과 provenance를 담는 값 없는 결과다.
4. **bundle index:** spec·request·report와 생성한 confirmation·evaluator output의 경로와 해시를 연결한다.

해시 의존성은 반드시 `원시 artifact → spec → request → report → index`의 비순환 방향이다. 주입 spec은 아직 생기지 않은 ground-truth report를 참조하지 않는다. 주입 검증 뒤 만드는 ground-truth index가 spec·request·report를 참조하고, 나중 B 실행의 request나 manifest가 이 index를 참조한다.

모든 경로는 그 경로를 적은 JSON 파일을 기준으로 한 상대경로를 기본으로 한다. SHA-256은 파일 raw bytes에 대한 소문자 64자리 hex다. 디렉터리는 정렬된 상대경로·파일 크기·raw SHA-256을 담은 manifest를 만들고 그 manifest의 raw SHA-256을 고정한다. 새 schema의 JSON parser는 unknown field를 거부한다. 아래 구조의 필드는 모두 필수이며, 해당하지 않는 값만 명시적으로 `null`을 쓴다.

새 raw candidate, assignment, R1CS, SYM, compiler 출력은 ignored `runs/` 아래에 둔다. tracked spec·report·index에는 상대경로와 해시만 남긴다. 기존에 이미 고정·추적된 과거 artifact는 이동하거나 다시 쓰지 않는다.

## 4. Review-spec schema 1

review-spec 하나는 root cause 하나와 컴파일된 target 하나의 계약이다. 같은 root cause가 여러 target에서 도달하면 spec을 target별로 만들되 `root_cause_id`를 공유한다. 여러 call path가 같은 주입 위치에 닿아도 root cause 수는 하나다.

최소 구조는 다음과 같다. `HEX`, `ID`, `PATH`, 숫자 0은 예시 자리표시자이며 실제 값으로 바꾼다.

```json
{
  "schema_version": 1,
  "review_spec_id": "PROJECT/CAUSE/SUBJECT",
  "root_cause_id": "PROJECT/CAUSE",
  "subject_kind": "published-vulnerable-source",
  "expected_scope": "original-component",
  "target_binding": {
    "target_id": "sha256:TARGET",
    "instance_key": null,
    "template": "Template",
    "concrete_parameters": [
      {"position": 0, "name": "w", "kind": "integer", "value_decimal": "4"}
    ],
    "source_path": "PATH",
    "source_sha256": "HEX",
    "source_closure_manifest_path": "PATH",
    "source_closure_manifest_sha256": "HEX"
  },
  "field": {
    "name": "bn128",
    "modulus_decimal": "21888242871839275222246405745257275088548364400416034343698204186575808495617",
    "assignment_encoding": "canonical-field-elements"
  },
  "compiled_subject": {
    "r1cs_path": "PATH",
    "r1cs_sha256": "HEX",
    "sym_path": "PATH",
    "sym_sha256": "HEX",
    "expected_shape": {
      "wires": 0,
      "labels": 0,
      "public_outputs": 0,
      "public_inputs": 0,
      "private_inputs": 0,
      "constraints": 0
    }
  },
  "compiler": {
    "version": "2.2.3",
    "binary_sha256": "HEX",
    "arguments": [],
    "library_manifest_path": "PATH",
    "library_manifest_sha256": "HEX"
  },
  "contract": {
    "definition_path": "PATH",
    "definition_sha256": "HEX",
    "input_contract_id": "ID",
    "property_id": "ID",
    "input_contract_statement": "VALUE_FREE_TEXT",
    "property_statement": "VALUE_FREE_TEXT",
    "input_signal_names": ["main.in"],
    "property_signal_names": ["main.out"],
    "predicate": {
      "api_version": 1,
      "path": "predicates/case.py",
      "sha256": "HEX",
      "entrypoint": "evaluate",
      "config": {},
      "allowed_results": [
        {
          "criterion": "input_preconditions",
          "verdict": "satisfied",
          "reason_code": "contract-satisfied",
          "note": "The predeclared input contract is satisfied."
        },
        {
          "criterion": "specified_property_violation",
          "verdict": "satisfied",
          "reason_code": "property-violated",
          "note": "The predeclared property is violated."
        }
      ],
      "allowed_violation_classes": ["CASE_DEFINED_CLASS"]
    }
  },
  "attribution": {
    "method": "known-defect-single-target",
    "evidence_path": "PATH",
    "evidence_sha256": "HEX"
  },
  "production_reachability": {
    "verdict": "unknown",
    "entrypoint_target_id": null,
    "instance_key": null,
    "evidence_path": null,
    "evidence_sha256": null,
    "verifier_manifest_path": null,
    "verifier_manifest_sha256": null
  },
  "injection_ground_truth": null
}
```

`expected_scope`는 `project`, `original-component`, `wrapper-only`, `reachability-unknown` 중 하나다. compile-time parameter는 field wire 값이 아니므로 위치·이름·type·정확한 정수 표현을 별도로 검사한다. adapter가 발견한 비-wire 항목은 spec에 선언된 parameter와 정확히 일치해야 하며, 예상 밖 항목은 후보별 review error다.

실제 spec의 `allowed_results`는 predicate가 정상적으로 낼 수 있는 `satisfied`·`not-satisfied`·`unknown` 조합을 모두 열거한다. 위 배열은 구조를 보여 주는 최소 예시다. 목록에 없는 verdict/reason code/class는 과학적 음성이 아니라 predicate 계약 위반이다.

`attribution.method`는 처음에는 다음 세 값만 쓴다.

- `known-defect-single-target`: 고정된 취약 revision·패치 근거, target binding, root-cause 전용 property가 모두 일치할 때만 `matched`다.
- `injection-single-diff`: qualification request에서는 아직 index가 없으므로 고정된 단일 주입 diff, source closure, injection ID, target binding이 모두 일치할 때 `matched`다. 이후 backend request에서는 여기에 같은 spec을 가리키는 qualified ground-truth index까지 있어야 `matched`다.
- `unattributed`: 후보의 substantive 판정은 할 수 있지만 알려진 원인으로 귀속하지 않으며 attribution은 `unknown`이다.

root-cause attribution은 predicate가 스스로 주장하지 않는다. 엔진이 고정 evidence와 binding으로 별도 판정한다. 따라서 사전 property를 위반하지만 알려진 원인과 맞지 않는 후보도 `validated` finding으로 남길 수 있고, 알려진 원인의 confirmation에는 넣지 않을 수 있다.

### 4.1 주입 spec의 추가 필드

주입 spec은 `subject_kind: "injected-mutant"`, `attribution.method: "injection-single-diff"`이고 `injection_ground_truth`에 다음을 넣는다.

```json
{
  "injection_id": "ID",
  "operator_id": "O1",
  "source_location": {
    "path": "PATH",
    "source_sha256": "HEX",
    "start_byte": 0,
    "end_byte": 0
  },
  "clean_revision": "FULL_REVISION",
  "single_diff": {"path": "PATH", "sha256": "HEX"},
  "source_closures": {
    "clean": {"path": "PATH", "sha256": "HEX"},
    "mutant": {"path": "PATH", "sha256": "HEX"},
    "disturbance_twin": {"path": "PATH", "sha256": "HEX"}
  },
  "compiled_variants": {
    "clean": {
      "r1cs_path": "PATH",
      "r1cs_sha256": "HEX",
      "sym_path": "PATH",
      "sym_sha256": "HEX",
      "shape": {"wires": 0, "labels": 0, "public_outputs": 0, "public_inputs": 0, "private_inputs": 0, "constraints": 0}
    },
    "mutant": {
      "r1cs_path": "PATH",
      "r1cs_sha256": "HEX",
      "sym_path": "PATH",
      "sym_sha256": "HEX",
      "shape": {"wires": 0, "labels": 0, "public_outputs": 0, "public_inputs": 0, "private_inputs": 0, "constraints": 0}
    },
    "disturbance_twin": {
      "r1cs_path": "PATH",
      "r1cs_sha256": "HEX",
      "sym_path": "PATH",
      "sym_sha256": "HEX",
      "shape": {"wires": 0, "labels": 0, "public_outputs": 0, "public_inputs": 0, "private_inputs": 0, "constraints": 0}
    }
  },
  "projection_manifest": {"path": "PATH", "sha256": "HEX"},
  "expected_clean_constraint_indices": [0],
  "clean_relation_exclusion": {
    "method": "fully-fixed-constraint",
    "certificate_path": "PATH",
    "certificate_sha256": "HEX",
    "verifier_manifest_path": "PATH",
    "verifier_manifest_sha256": "HEX"
  }
}
```

`source_location`은 half-open byte range다. 세 shape의 key와 type은 `compiled_subject.expected_shape`와 같다. `expected_clean_constraint_indices`는 정렬되고 중복이 없어야 한다.

`compiled_subject`는 이 안의 mutant R1CS/SYM과 같아야 한다. ground-truth report나 그 해시는 spec에 넣지 않는다.

projection manifest schema 1은 모든 nonconstant clean wire에 대해 다음 항목을 정확히 하나 가진다.

```json
{
  "schema_version": 1,
  "operator_id": "O1",
  "operator_justification": "VALUE_FREE_TEXT",
  "mappings": [
    {
      "clean_wire_index": 1,
      "clean_signal_names": ["main.out"],
      "source_kind": "disturbance-signal",
      "source_signal_name": "main.out"
    },
    {
      "clean_wire_index": 2,
      "clean_signal_names": ["main.internal"],
      "source_kind": "clean-reference-wire",
      "source_signal_name": null
    }
  ]
}
```

`source_kind`는 `disturbance-signal` 또는 `clean-reference-wire`다. 전자는 SYM 이름으로 mutant/twin 값을 찾고, 후자는 같은 clean R1CS의 동일 wire index에서 이미 검증한 clean reference 값을 가져온다. constant wire 0은 엔진이 field one으로 채운다. mapping은 나머지 clean wire index 오름차순이고 중복·누락이 없어야 한다.

clean과 mutant의 wire 번호가 같다고 가정하지 않는다. 공유 신호 projection은 SYM의 signal 이름을 사용한다. clean-only wire를 안전하게 채울 수 없거나 이름 대응이 모호하거나 clean에서 실패한 제약이 사전 식별한 주입 관련 집합과 만나지 않으면 `clean_rejection`은 `unknown`이고 그 위치는 B ground truth로 채택하지 않는다.

한 projected assignment의 실패만으로 같은 input/property signal에 대한 다른 clean extension까지 배제되지는 않는다. 그래서 `clean_relation_exclusion`은 다음 세 certificate method 중 하나를 추가로 요구한다.

- `fully-fixed-constraint`: 실패한 주입 관련 clean constraint 하나의 모든 nonconstant wire가 contract의 `input_signal_names` 또는 `property_signal_names`에 직접 대응함을 verifier가 확인한다. 그러면 다른 clean-only wire 선택으로 그 constraint를 고칠 수 없다.
- `operator-proof`: 고정된 operator별 checker가, 예를 들어 범위를 벗어난 비교기 입력이나 alias 값처럼 같은 input/property signal에 대해 clean constraint를 만족하는 extension이 없음을 기계적으로 확인한다.
- `solver-unsat-certificate`: 고정된 input/property signal 아래 clean R1CS가 UNSAT임을 독립 solver가 만든 certificate와 별도 verifier로 확인한다.

certificate와 verifier source/binary manifest의 path/hash를 spec에 고정한다. 단순한 설명문, solver의 종료 코드, projected assignment 한 건의 실패만으로는 이 criterion을 만족시키지 않는다. 어느 method도 적용할 수 없으면 위치를 B ground truth로 쓰지 않는다.

relation-exclusion verifier manifest schema 1은 다음과 같다.

```json
{
  "schema_version": 1,
  "api_version": 1,
  "verifier_id": "ID",
  "method": "fully-fixed-constraint",
  "implementation": {
    "kind": "engine-builtin",
    "executable_path": null,
    "executable_sha256": null,
    "source_manifest_path": "PATH",
    "source_manifest_sha256": "HEX"
  },
  "certificate_format": "fully-fixed-constraint-v1",
  "allowed_results": [
    {"verdict": "satisfied", "reason_code": "clean-relation-excluded"},
    {"verdict": "not-satisfied", "reason_code": "clean-extension-not-excluded"},
    {"verdict": "unknown", "reason_code": "exclusion-proof-incomplete"}
  ]
}
```

`method` enum은 위 세 method이고 `implementation.kind`는 `engine-builtin` 또는 `external`이다. T4b의 built-in `fully-fixed-constraint-v1`은 executable 필드가 `null`이고 engine source manifest로 구현을 고정한다. `operator-proof`와 `solver-unsat-certificate`는 executable path/hash가 필수이며, source manifest도 함께 고정한다. 각 certificate format parser는 unknown field를 거부한다.

내장 `fully-fixed-constraint-v1` certificate의 정확한 구조는 다음과 같다.

```json
{
  "schema_version": 1,
  "method": "fully-fixed-constraint",
  "clean_constraint_indices": [0],
  "fixed_signal_names": ["main.in", "main.out"]
}
```

두 배열은 정렬되고 중복이 없어야 한다. 외부 method의 certificate schema는 해당 verifier source manifest에 포함하고 그 manifest hash로 고정하며, 공용 엔진은 내용을 해석하지 않고 pinned verifier의 value-free 결과와 모든 입력 hash를 교차 확인한다.

엔진이나 외부 verifier에 넘기는 ephemeral context schema 1은 다음과 같다. `fixed_signals`의 raw 값이 들어가므로 ignored 임시 위치나 전용 IPC에서만 쓰고 report에 남기지 않는다.

```json
{
  "schema_version": 1,
  "method": "fully-fixed-constraint",
  "field_modulus_decimal": "DECIMAL",
  "clean_r1cs": {"path": "PATH", "sha256": "HEX"},
  "clean_sym": {"path": "PATH", "sha256": "HEX"},
  "projection_manifest_sha256": "HEX",
  "expected_clean_constraint_indices": [0],
  "contract_input_signal_names": ["main.in"],
  "property_signal_names": ["main.out"],
  "fixed_signals": {"main.in": "DECIMAL", "main.out": "DECIMAL"},
  "certificate": {"path": "PATH", "sha256": "HEX"}
}
```

verifier 결과 schema 1은 value-free다.

```json
{
  "schema_version": 1,
  "method": "fully-fixed-constraint",
  "verdict": "satisfied",
  "reason_code": "clean-relation-excluded",
  "checked_clean_constraint_indices": [0],
  "fixed_signal_names": ["main.in", "main.out"],
  "certificate_sha256": "HEX"
}
```

엔진은 method, clean artifact hash, projection hash, certificate hash, 정렬·중복 없는 index/name 목록, allowed result를 교차 확인한다. `fully-fixed-constraint`는 satisfied를 내기 전에 checked constraint 하나 이상의 모든 nonconstant wire가 `fixed_signals`의 SYM wire에 속하고 실제 대입에서 실패함을 직접 재계산한다. 외부 verifier도 predicate worker와 같은 격리·빈 stdout/stderr 규칙을 따르며, result channel 외 출력은 review error다. solver는 `UNSAT` 문자열만 반환해서는 안 되고 manifest에 고정된 proof format을 verifier가 검증해야 한다.

### 4.2 production 도달 증거

`scope: project`와 주입 ground truth의 production 도달은 사람이 적은 verdict만 믿지 않는다. reachability evidence는 고정 discovery 도구가 만든 schema-versioned artifact여야 하며 다음을 포함한다.

- production entrypoint target ID와 source hash
- 주입 target의 `instance_key`와 전체 `parent_instance_key` chain
- 각 단계의 template, concrete parameter, source 위치
- 탐색 completion 상태와 unsupported/unresolved 항목

엔진은 evidence와 verifier manifest의 해시, source closure 해시, 중복·cycle 없는 parent chain, chain의 entrypoint 종결, target/spec binding, `complete` 상태를 다시 검사한다. 하나라도 확인할 수 없으면 project scope로 올리지 않는다. 기존 v1.1·v2·v3처럼 direct component만 검토한 사례는 `original-component` 또는 `reachability-unknown`을 유지한다.

## 5. Review-request schema 1

### 5.1 Backend 후보 request

v1.1·v2의 36개 plan/outcome도 한 번에 검토할 수 있도록 backend request는 쌍을 1개 이상 가진다.

```json
{
  "schema_version": 1,
  "request_id": "ID",
  "kind": "backend-candidates",
  "review_specs": [
    {"path": "specs/case.json", "sha256": "HEX"}
  ],
  "executions": [
    {
      "execution_id": "ID",
      "campaign_coordinates": {"block": 1, "strategy": "risk-only"},
      "plan": {"path": "PATH", "sha256": "HEX"},
      "outcome": {"path": "PATH", "sha256": "HEX"}
    }
  ],
  "candidate_adapter": {
    "id": "zkfuzz-counterexample-v1",
    "implementation_sha256": "HEX"
  },
  "candidate_policy": "all-outcome-candidates",
  "unmatched_candidate_policy": "record-unreviewed",
  "qualification_bundles": [
    {"injection_id": "ID", "path": "PATH", "sha256": "HEX"}
  ]
}
```

단일 pilot처럼 campaign 좌표가 없으면 `campaign_coordinates`는 `null`, 주입 평가가 아니면 `qualification_bundles`는 빈 배열이다. bundle을 쓸 때 엔진은 index의 kind, spec/request/report hash, report `complete`, `ground_truth_qualification: qualified`, injection ID 일치를 다시 검증한다.

엔진은 각 plan ID와 outcome의 plan ID·hash, 모든 target ID, backend status, candidate record와 파일 hash, target의 plan 포함 여부를 확인한다. execution ID, plan/outcome pair, 존재하는 run ID, candidate path는 request 안에서 유일해야 한다. plan의 target 순서와 outcome의 `planned_target_ids`가 같아야 하고, 각 `(index, target_id)`는 `runs + failures + skipped` 전체에서 정확히 한 번 accounting돼야 한다.

각 outcome의 모든 run·failure·skipped target과 모든 candidate record를 열거한다.

- 정상 run은 `run_id`를 가지며, spawn failure와 budget skip은 `run_id: null`인 별도 execution 행이다.
- candidate record 하나는 정확히 한 `bug_found` run에 연결돼야 한다.
- `bug_found` run에는 candidate record가 1개 이상 있어야 한다. 하나도 없으면 정상 음성이 아니라 보존 증거 누락이므로 top-level `failed`다.
- `bug_found`가 아닌 run에 candidate record가 있으면 top-level `failed`다.
- candidate record는 있는데 파일이 없거나 hash가 다르면 candidate inventory의 `candidate_error`이고 report는 `incomplete`다. usable candidate-spec pair가 아니므로 substantive disposition을 만들지 않는다.
- 후보가 0개인 non-`bug_found` run만 정상 `no-candidate` 실행 행이 된다.
- spawn failure는 `backend_status: runner_failure`, budget skip은 `backend_status: not_started`이고 둘 다 `candidate_status: not-applicable`이다.

후보는 target ID가 일치하는 모든 spec과 candidate-spec review pair를 만든다. 일치하는 spec이 없으면 후보를 버리지 않고 `unreviewed`로 남긴다. 같은 target에 root cause spec이 여러 개면 모두 평가하므로 복수 일치 자체는 오류가 아니다.

### 5.2 주입 ground-truth request

주입 request는 zkFuzz plan이나 가짜 run ID를 만들지 않는다.

```json
{
  "schema_version": 1,
  "request_id": "ID",
  "kind": "injection-ground-truth",
  "review_spec": {"path": "specs/injection.json", "sha256": "HEX"},
  "generation_manifest": {"path": "PATH", "sha256": "HEX"},
  "disturbance_assignment": {
    "origin": "disturbance-twin",
    "format": "wtns-json-v1",
    "path": "PATH",
    "sha256": "HEX",
    "adapter_implementation_sha256": "HEX"
  },
  "clean_reference_assignment": {
    "origin": "clean-witness-generator",
    "format": "wtns-json-v1",
    "path": "PATH",
    "sha256": "HEX",
    "adapter_implementation_sha256": "HEX"
  }
}
```

generation manifest의 schema 1은 다음 구조다.

```json
{
  "schema_version": 1,
  "common_input": {"path": "PATH", "sha256": "HEX"},
  "generators": {
    "clean": {
      "runner_path": "PATH",
      "runner_sha256": "HEX",
      "artifact_manifest_path": "PATH",
      "artifact_manifest_sha256": "HEX",
      "arguments": [],
      "witness_path": "PATH",
      "witness_sha256": "HEX",
      "assignment_path": "PATH",
      "assignment_sha256": "HEX"
    },
    "disturbance_twin": {
      "runner_path": "PATH",
      "runner_sha256": "HEX",
      "artifact_manifest_path": "PATH",
      "artifact_manifest_sha256": "HEX",
      "arguments": [],
      "witness_path": "PATH",
      "witness_sha256": "HEX",
      "assignment_path": "PATH",
      "assignment_sha256": "HEX"
    }
  }
}
```

공통 raw input과 생성 artifact는 ignored `runs/`에 두고 tracked request에는 manifest path/hash만 둔다. 엔진은 qualification 때 manifest를 검증하고 같은 input으로 두 generator를 다시 실행해 witness와 assignment hash가 재현되는지 확인한다.

두 assignment의 외부 입력은 이름과 값이 같아야 한다. disturbance assignment는 mutant 제약과 property 검증에 쓴다. clean reference는 canonical·complete해야 하고 clean R1CS 전체 제약을 만족해야 한다. 이것을 확인한 뒤에만 같은 입력의 정상 의미 비교와 projection의 clean-only wire 보충에 쓴다. 공유 signal은 disturbance 값을 우선하며, projection 출처와 충돌 규칙을 manifest에 고정한다.

지원할 assignment adapter는 처음에는 기존 zkFuzz JSON의 `7_assignment`를 읽는 `zkfuzz-assignment-v1`과 witness JSON의 wire 배열을 읽는 `wtns-json-v1` 두 개다. adapter는 값을 다음 네 범주로 분리해 정규화할 뿐 과학적 판정을 하지 않는다.

1. nonnegative SYM wire에 대응하는 `r1cs-wire`
2. SYM에 이름이 있고 wire가 음수인 `eliminated-signal`
3. spec의 typed parameter와 일치하는 `compile-time-parameter`
4. 어느 범주에도 들지 않는 `unexpected-entry`

`eliminated-signal`은 Banyan처럼 raw 후보에 실제로 들어올 수 있다. 이름은 고정 SYM의 negative-label 집합과 정확히 대조하고 값은 canonical field element인지 확인하지만 R1CS wire vector나 제약 계산에는 넣지 않는다. predicate context에서도 wire signal과 분리한다. `unexpected-entry`는 review error다.

## 6. 공용 엔진과 binding 검증

공용 엔진이 맡는 일은 다음과 같다.

1. spec·request와 모든 공유 참조 파일의 SHA-256 검증
2. plan/outcome/run/target/candidate 전체 inventory와 연결 검증
3. raw candidate의 target path, template, parameter와 spec binding 검증
4. R1CS header·field·section·shape 파싱
5. SYM signal label과 R1CS wire 대응 검증
6. assignment의 wire 수·누락·중복·canonical field 표현 검증
7. 대상 R1CS의 **모든** 제약 `A × B = C mod p` 재계산
8. predicate 실행, attribution·scope·ground-truth qualification 판정
9. 값 없는 report와 validated+attributed backend review의 confirmation 생성

adapter는 R1CS witness vector, SYM-declared eliminated signal, compile-time parameter를 섞지 않는다. v3의 `main.w == 4` 같은 parameter는 target binding으로 검사하지만 field canonical 검사 대상은 아니다. 실제 wire와 eliminated signal의 값은 canonical field element여야 한다. R1CS wire vector는 정확한 길이를 가져야 하고, 중복·누락 wire가 있으면 과학적 음성이 아니라 review error다. positive-wire alias가 여러 이름으로 나타나면 값이 서로 같아야 한다. 어느 허용 범주에도 없는 assignment key나 metadata는 조용히 버리지 않는다.

R1CS constant wire 0은 엔진이 field one으로 채운다. raw assignment에 명시돼 있지 않아도 누락으로 세지 않으며, 명시돼 있다면 canonical `1`과 같아야 한다.

공유 spec/request/plan/outcome/R1CS/SYM/predicate/reachability artifact의 hash·parse·binding 실패는 inventory 전체를 신뢰할 수 없으므로 top-level `failed`다. 개별 candidate 파일 자체의 누락·hash 오류는 candidate inventory의 `candidate_error`, usable candidate를 읽은 뒤의 adapter·predicate 호출 실패는 candidate-spec pair의 `review-error`이고 둘 다 top-level `incomplete`다.

## 7. 사례별 predicate API

predicate는 입력 계약과 사전 속성만 판정한다. root cause와 reachability는 엔진이 별도로 판정한다. T4b 첫 구현은 hash-pinned Python 단일 파일을 다음 API로 호출한다.

```python
API_VERSION = 1

def evaluate(context):
    return {
        "input_preconditions": {
            "verdict": "satisfied",
            "reason_code": "contract-satisfied"
        },
        "specified_property_violation": {
            "verdict": "satisfied",
            "reason_code": "property-violated",
            "violation_class": "CASE_DEFINED_CLASS"
        }
    }
```

`context`는 다음 read-only 자료만 제공한다.

- field modulus
- subject의 canonical R1CS-wire signal map과 별도 eliminated-signal map
- spec에 고정된 typed parameter와 predicate config
- request kind와 injection ID
- injection request일 때 같은 입력의 clean reference named signal map

반환 가능한 조합은 spec의 `allowed_results`와 `allowed_violation_classes`에 미리 있어야 한다. verdict는 `satisfied`, `not-satisfied`, `unknown` 중 하나다. arbitrary note나 evidence path는 predicate가 만들지 않는다. 엔진이 reason catalog의 고정 note와 실제 검증 artifact에서 evidence를 만든다.

`specified_property_violation`은 clean rejection과 독립적으로 판정한다. 출력이 있는 사례는 같은 입력의 clean 출력과 subject 출력의 차이처럼 사전 속성을 쓸 수 있다. 출력이 없는 사례도 비트성·범위·보존식처럼 `property_signal_names`에서 직접 평가할 사전 불변식이 있어야 한다. 그런 속성을 적을 수 없으면 `clean_rejection`으로 대신하지 않고 그 주입 위치를 탈락시킨다.

predicate는 고정·검토한 연구 코드이며 적대적 코드를 안전하게 실행하는 보안 경계로 주장하지 않는다. 그래도 우발적인 값 유출과 환경 의존을 줄이기 위해 다음을 강제한다.

- 단일 파일, local import 없음, 사전 source audit와 raw SHA-256 고정
- 격리된 worker process, `python -I -S`, 정리한 환경변수, 빈 임시 cwd, stdin 없음
- 결과는 전용 result channel로만 받고 stdout·stderr는 모두 비어 있어야 함
- stdout·stderr가 한 byte라도 있거나 허용되지 않은 결과가 나오면 후보별 `review-error`; stream 내용·길이·hash는 보존하지 않고 tracked report에는 `predicate_stream_nonempty: true`만 기록

이는 kernel-level filesystem/network sandbox를 뜻하지 않는다. 최종 고정 전 predicate source를 검토하고 hash를 고정하는 것이 신뢰 경계다.

## 8. Criterion, disposition, attribution

criterion의 공통 형식은 다음과 같다.

```json
{
  "verdict": "satisfied",
  "reason_code": "STABLE_CODE",
  "evidence": [
    {"path": "VALUE_FREE_EVIDENCE", "sha256": "HEX"}
  ],
  "note": "값을 포함하지 않는 고정 설명"
}
```

공통 substantive criterion ID는 다음 네 개다.

- `assignment_encoding`
- `input_preconditions`
- `fixed_target_constraints`
- `specified_property_violation`

`fixed_target_constraints`는 hash-pinned vulnerable component나 injected mutant처럼 이번 검토의 고정 subject R1CS 전체를 뜻한다. schema 2 confirmation으로 내보낼 때만 이름을 `fixed_original_constraints`로 투영한다.

backend 후보의 `disposition`은 네 criterion이 모두 `satisfied`면 `validated`, 정상적으로 판정된 하나 이상이 `not-satisfied`면 `rejected`, `not-satisfied` 없이 하나 이상이 `unknown`이면 `unresolved`, 후보별 도구 오류면 `review-error`다. `unreviewed`는 어떤 spec에도 연결되지 않은 후보이며 disposition과 별도 inventory 상태다.

`cause_attribution`은 `matched`, `not-matched`, `unknown` 중 하나로 별도 기록한다. `validated`이지만 attribution이 `unknown`인 후보는 잠재적인 다른 finding이지 알려진 root cause 발견은 아니다.

주입 request에는 다음 qualification criterion을 더 둔다.

- `twin_r1cs_identity`
- `twin_sym_identity`
- `generation_reproducibility`
- `clean_reference_assignment_encoding`
- `clean_reference_constraints`
- `clean_input_equivalence`
- `clean_rejection`
- `clean_relation_exclusion`
- `production_reachability`

공통 disposition이 `validated`이고 추가 criterion과 qualification 단계의 single-diff attribution이 모두 `satisfied`/`matched`일 때만 `ground_truth_qualification: qualified`다. 이 최초 판정은 아직 존재하지 않는 ground-truth index를 요구하지 않는다. 정상적인 `not-satisfied`가 있으면 `rejected`, `unknown`이 있으면 `unresolved`, 도구 오류면 `review-error`다. B에는 `qualified`만 넣고, 이후 backend attribution에서 그 결과 index를 요구한다.

## 9. 값 없는 Review-report schema 1

tracked report에는 signal·input·output·witness 값을 넣지 않는다. raw candidate와 assignment는 ignored `runs/`에만 두고 path와 hash만 기록한다.

```json
{
  "schema_version": 1,
  "report_id": "ID",
  "kind": "backend-candidates",
  "status": "complete",
  "review_request": {"path": "request.json", "sha256": "HEX"},
  "review_specs": [{"path": "spec.json", "sha256": "HEX"}],
  "engine": {
    "version": "VERSION",
    "source_revision": "REVISION",
    "source_manifest_path": "PATH",
    "source_manifest_sha256": "HEX",
    "executable_path": "PATH",
    "executable_sha256": "HEX"
  },
  "adapters": [
    {"id": "zkfuzz-counterexample-v1", "implementation_sha256": "HEX"}
  ],
  "failure": null,
  "candidate_inventory": {
    "outcome_candidate_count": 0,
    "matched_candidate_count": 0,
    "unmatched_candidate_count": 0,
    "candidate_error_count": 0,
    "review_pair_count": 0,
    "terminal_review_pair_count": 0,
    "complete": true
  },
  "executions": [
    {
      "execution_id": "ID",
      "plan_index": 0,
      "run_id": "RUN",
      "target_id": "sha256:TARGET",
      "backend_status": "no_counterexample",
      "candidate_count": 0,
      "candidate_status": "no-candidate"
    }
  ],
  "candidate_errors": [],
  "unreviewed_candidates": [],
  "reviews": [],
  "summary": {
    "validated": 0,
    "rejected": 0,
    "unresolved": 0,
    "review_error": 0,
    "unreviewed_candidates": 0,
    "attributed_validated": 0,
    "unique_validated_root_causes": 0
  },
  "semantic_result_sha256": "HEX",
  "raw_values_persisted": false
}
```

candidate inventory에는 다음 불변식이 있다.

`outcome_candidate_count = matched_candidate_count + unmatched_candidate_count + candidate_error_count`

matched candidate 하나가 여러 spec과 연결될 수 있으므로 `review_pair_count`는 matched candidate 수보다 클 수 있다. `complete: true`이면 모든 matched candidate-spec pair가 terminal disposition을 갖고, unmatched와 candidate error가 모두 0이어야 한다.

`summary`의 validated/rejected/unresolved/review-error 수는 candidate가 아니라 candidate-spec review pair 단위다. candidate 수는 오직 `candidate_inventory`에서 센다.

`executions[].candidate_status` enum은 정상 run의 `candidate-present`·`no-candidate`, spawn failure/skip의 `not-applicable`, accounting 무결성 오류의 `evidence-error`다. `run_id`는 정상 run에서 string이고 failure/skip에서 `null`이다. `backend_status`는 실제 run status 외에 `runner_failure`, `not_started`를 허용한다.

`candidate_errors[]`는 `{candidate_record_id, execution_id, target_id, path, expected_sha256, observed_sha256, reason_code}`를 가진다. 읽을 수 없어 observed hash가 없으면 `null`이다. `unreviewed_candidates[]`는 candidate record ID와 `{path, sha256}`, execution/run/target binding, `reason_code: no-matching-spec`을 가진다. 두 배열은 candidate record ID 순이고, 각 길이는 inventory의 해당 count와 같아야 한다.

backend `reviews[]` 항목의 정확한 구조는 다음과 같다. criterion 값은 8절 형식이고, `review-error` 전까지 실행되지 못한 criterion만 `null`일 수 있다.

```json
{
  "review_kind": "backend-candidate",
  "candidate_record_id": "EXECUTION_ID/0000",
  "candidate": {"path": "PATH", "sha256": "HEX"},
  "binding": {
    "execution_id": "ID",
    "plan_index": 0,
    "run_id": "RUN",
    "target_id": "sha256:TARGET",
    "candidate_hash_verified": true,
    "candidate_metadata_verified": true
  },
  "review_spec": {"id": "ID", "path": "PATH", "sha256": "HEX"},
  "artifact_verification": {
    "r1cs_sha256_verified": true,
    "sym_sha256_verified": true,
    "assignment_complete": true
  },
  "failed_target_constraint_count": 0,
  "failed_target_constraint_indices": [],
  "criteria": {
    "assignment_encoding": {"verdict": "satisfied", "reason_code": "canonical", "evidence": [{"path": "PATH", "sha256": "HEX"}], "note": "All field-valued assignment entries are canonical."},
    "input_preconditions": {"verdict": "satisfied", "reason_code": "contract-satisfied", "evidence": [{"path": "PATH", "sha256": "HEX"}], "note": "The predeclared input contract is satisfied."},
    "fixed_target_constraints": {"verdict": "satisfied", "reason_code": "all-constraints-satisfied", "evidence": [{"path": "PATH", "sha256": "HEX"}], "note": "All constraints in the fixed target R1CS are satisfied."},
    "specified_property_violation": {"verdict": "satisfied", "reason_code": "property-violated", "evidence": [{"path": "PATH", "sha256": "HEX"}], "note": "The predeclared property is violated."}
  },
  "disposition": "validated",
  "cause_attribution": {
    "verdict": "matched",
    "reason_code": "known-defect-binding-matched",
    "evidence": [{"path": "PATH", "sha256": "HEX"}]
  },
  "ground_truth_qualification": null,
  "violation_class": null,
  "confirmation_eligible": true,
  "automated_review_seconds": 0.0
}
```

`candidate_record_id`는 outcome `counterexample_candidates` 배열의 zero-based 위치로부터 `execution_id/NNNN` 형식으로 만든다. 배열 순서도 outcome hash에 고정된다.

후보 review 하나는 다음 필드를 모두 가진다.

- candidate path/hash와 execution/run/target binding
- spec ID/hash와 raw candidate metadata binding 결과
- R1CS/SYM/assignment 검증 결과
- 실패한 target constraint의 **개수와 zero-based index**(값은 제외)
- 네 substantive criteria와 disposition
- cause attribution, confirmation eligibility, optional value-free violation class
- automated review time

`status`는 모든 inventory와 review가 완전하면 `complete`, 후보별 `review-error`나 `unreviewed`가 하나라도 있으면 `incomplete`, 공유 입력이나 inventory 무결성을 신뢰할 수 없으면 `failed`다. `complete`·`incomplete`에서는 `failure`가 `null`이다. `failed` variant는 `failure`에 stage, stable reason code, 값 없는 path/hash evidence를 넣고, 만들 수 없는 `candidate_inventory`는 `null`, `executions`와 `reviews`는 빈 배열로 둔다. `incomplete`나 `failed` report로 최종 전략 비교를 발표하지 않는다.

`kind: injection-ground-truth` report는 같은 envelope과 engine/adapters/failure 형식을 쓴다. `candidate_inventory`는 `null`, `executions`, `candidate_errors`, `unreviewed_candidates`는 빈 배열이다. `status`가 `complete` 또는 `incomplete`이면 `reviews`는 항목 정확히 하나이고, 공유 입력 검증 전 실패한 `failed`이면 `reviews`는 빈 배열이다. review 항목은 `review_kind: injection-ground-truth`, `candidate_record_id: null`, `candidate: null`, 두 assignment의 path/hash, spec link, artifact verification, 공통 네 criteria, `qualification_criteria`의 아홉 criterion, attribution, disposition, `ground_truth_qualification`, `violation_class`, `confirmation_eligible: false`, automated time을 가진다. backend 전용 `binding`은 `null`이다. summary는 `{validated, rejected, unresolved, review_error, qualified}` 정수 필드만 가진다. 이 tagged union 외의 필드는 허용하지 않는다.

injection review의 nested object도 다음처럼 고정한다.

- `assignments`: `disturbance`와 `clean_reference` 각각 `{path, sha256}`인 object
- `artifact_verification`: `mutant_r1cs`, `mutant_sym`, `clean_r1cs`, `clean_sym`, `twin_r1cs`, `twin_sym`, `generation_reproduced`라는 boolean만 가진 object
- `failed_target_constraint_count`와 `failed_target_constraint_indices`: mutant 검사 결과
- `failed_clean_constraint_count`와 `failed_clean_constraint_indices`: projected disturbance의 clean 검사 결과
- `criteria`: 공통 네 criterion key를 정확히 한 번씩 가진 object
- `qualification_criteria`: `twin_r1cs_identity`, `twin_sym_identity`, `generation_reproducibility`, `clean_reference_assignment_encoding`, `clean_reference_constraints`, `clean_input_equivalence`, `clean_rejection`, `clean_relation_exclusion`, `production_reachability`를 정확히 한 번씩 가진 object
- `ground_truth_qualification`: `qualified`, `rejected`, `unresolved`, `review-error` 중 하나

공통 `FileRef`는 `{path: string, sha256: 64자리 소문자 hex}`, `SpecRef`는 `{id: string, path: string, sha256: 64자리 소문자 hex}`다. enum과 key spelling은 이 문서에 적힌 문자열 그대로이며 alias를 허용하지 않는다.

`semantic_result_sha256`은 아래 projection을 RFC 8785 JSON Canonicalization Scheme(JCS)으로 직렬화한 raw UTF-8 bytes의 SHA-256이다. projection에는 float를 넣지 않고 정수·문자열·boolean·null만 쓴다.

```json
{
  "schema_version": 1,
  "kind": "backend-candidates",
  "request_sha256": "HEX",
  "spec_sha256s": ["HEX"],
  "engine": {"source_manifest_sha256": "HEX", "executable_sha256": "HEX"},
  "adapters": [{"id": "ID", "implementation_sha256": "HEX"}],
  "candidate_inventory": {},
  "executions": [],
  "candidate_errors": [],
  "unreviewed_candidates": [],
  "reviews": []
}
```

- `spec_sha256s`는 byte-order, adapters는 `(id, implementation_sha256)`, executions는 `(execution_id, plan_index, target_id, run_id-or-empty)` 순으로 정렬한다.
- backend reviews는 `(candidate_record_id, spec_sha256)`, injection review는 `(injection_id, spec_sha256)` 순으로 정렬한다.
- candidate errors와 unreviewed candidates는 `candidate_record_id` 순으로 정렬한다.
- review projection에는 candidate/assignment SHA-256, run/target/spec binding, artifact 검증 boolean, 실패 constraint index, criteria의 verdict·reason code·evidence SHA-256, value-free violation class, disposition, attribution, qualification, confirmation eligibility를 넣는다.
- criteria는 object key로, evidence SHA-256 배열과 실패 index는 중복 제거 후 byte-order/숫자 오름차순으로 정렬한다.
- candidate inventory와 execution 항목은 report의 같은 값 전체를 넣는다.

시각, duration, output path, evidence path, 절대경로는 projection에서 제외한다. engine/adapter가 바뀌면 판정이 같아도 digest가 달라지는 것이 의도다. 같은 도구와 raw 자료를 다시 검토했을 때 이 digest와 substantive 판정이 같아야 재현된 것이다.

## 10. R1CS·SYM과 교란 쌍둥이 고정

R1CS identity는 raw bytes SHA-256이다. constraint 수나 구조가 같다는 사실만으로 같은 R1CS라고 보지 않는다.

- 준비 단계에서 실제 실행에 쓸 R1CS와 같은 compile에서 나온 SYM을 보존하고 둘의 해시를 spec에 넣는다.
- 별도 review compile이 필요하면 prepared R1CS와 raw SHA-256이 같아야 한다. 다르면 공유 무결성 실패다.
- R1CS parser는 magic/version, section 집합, field modulus, wire·label·input/output/constraint 수를 검증한다.
- SYM은 name→wire multimap으로 읽는다. 여러 이름이 같은 wire를 가리키는 alias는 보존하고, eliminated/negative wire label은 별도 `eliminated-signal` 이름 집합으로 보존하되 assignment wire로 취급하지 않는다. 같은 이름이 상충하는 wire를 가리키면 실패한다.
- R1CS wire 전체는 index vector로 검증한다. 모든 wire가 사람이 읽을 수 있는 SYM 이름을 가져야 한다고 가정하지 않는다.
- source closure, dependency/library closure, compiler binary와 compile arguments를 manifest로 고정한다.
- 주입 검증에서는 twin/mutant R1CS raw SHA-256과 twin/mutant SYM raw SHA-256이 각각 같아야 한다.
- clean 비교는 wire index가 아니라 고정 projection의 SYM signal 이름을 쓴다. clean-only wire는 canonical이고 clean R1CS를 만족한다고 먼저 확인한 같은-input clean reference에서만 가져온다.
- clean에서 실패한 제약 중 하나 이상이 사전 고정한 주입 관련 index 집합에 들어야 한다. 대응이 불완전하면 `clean_rejection: unknown`이다.

`clean_rejection`은 “동일 witness가 clean에서 거부됐다”가 아니라 **“고정 규칙으로 만든 projected disturbance assignment가 clean R1CS에서 거부됐다”**고만 보고한다. 이 한 건은 진단 증거이고 relation exclusion의 증명은 아니다. 다른 clean-only extension이 같은 input/property signal을 허용하지 않는다는 주장은 별도 `clean_relation_exclusion` certificate가 검증된 경우에만 한다.

## 11. Schema 2 confirmation과 bundle index

confirmation은 report에서 기계적으로 생성하며 사람이 criterion을 다시 베껴 쓰지 않는다. eligibility는 다음을 모두 요구한다.

- backend request이고 run/target link와 backend `bug_found`가 검증됨
- disposition `validated`, cause attribution `matched`
- assignment encoding, input, target constraints, property가 모두 `satisfied`
- root cause와 scope가 spec 및 reachability 판정과 일치

schema 2에는 정확히 다음처럼 투영한다.

- `input_preconditions` → 같은 이름
- `fixed_target_constraints` → `fixed_original_constraints`
- `specified_property_violation` → 같은 이름
- `assignment_encoding`과 cause attribution은 생성 gate로만 쓰며 schema 2 review에 추가하지 않음
- `evidence_origin`은 `backend-execution`
- report의 `{path, sha256}` evidence는 먼저 report 기준으로 resolve하고 hash를 다시 확인한 뒤 confirmation 파일의 parent 기준 상대경로로 다시 쓴다. 그 path만 confirmation의 `Vec<PathBuf>`로 내보내고 hash는 report/index에 보존한다.
- criterion note는 spec의 reason catalog, top-level note는 engine의 고정 template에서 생성
- top-level evidence에는 최소 report와 spec 경로를 넣음

`scope: original-component`와 `scope: project`에는 위 세 필드로 만든 satisfied `original_component_review`를 넣는다. `wrapper-only`와 `reachability-unknown`에는 이를 넣지 않아 component 판정으로 오인되지 않게 한다. 같은 `(run_id, root_cause_id, scope, evidence_origin)`에 eligible 후보가 여러 개면 report에는 전부 남기되 confirmation은 하나만 만든다. `(candidate_sha256, spec_sha256, candidate_record_id)` 오름차순의 첫 review를 대표로 고르고, top-level evidence는 전체 report를 가리킨다. 이 규칙은 동일 bytes나 복수 spec에서도 전순서를 만들며 현재 evaluator의 중복 금지와 맞는다.

evaluator는 plan/outcome 한 쌍씩 받으므로 confirmation도 execution pair별 파일로 만든다. eligible review가 0개인 pair는 다음 빈 파일이 정상이다.

```json
{"schema_version": 2, "confirmations": []}
```

주입 ground-truth request는 run ID가 없으며 confirmation을 만들지 않는다. 대신 검증 뒤 다음 방향의 ground-truth bundle index를 만든다.

```json
{
  "schema_version": 1,
  "kind": "injection-ground-truth",
  "review_spec": {"path": "PATH", "sha256": "HEX"},
  "review_request": {"path": "PATH", "sha256": "HEX"},
  "review_report": {"path": "PATH", "sha256": "HEX"},
  "qualification": "qualified"
}
```

B의 backend request와 manifest는 이 index의 path/hash를 `qualification_bundles`에 넣는다. index는 자신을 참조하는 spec/request/report를 거꾸로 참조시키지 않는다.

일반 backend bundle index의 최소 구조는 다음과 같다.

```json
{
  "schema_version": 1,
  "kind": "backend-review-bundle",
  "review_specs": [{"path": "PATH", "sha256": "HEX"}],
  "review_request": {"path": "PATH", "sha256": "HEX"},
  "review_report": {"path": "PATH", "sha256": "HEX"},
  "execution_evaluations": [
    {
      "execution_id": "ID",
      "confirmation": {"path": "PATH", "sha256": "HEX"},
      "evaluator_output": {"path": "PATH", "sha256": "HEX"}
    }
  ],
  "campaign_summary": {
    "pair_count": 1,
    "by_execution": [
      {
        "execution_id": "ID",
        "campaign_coordinates": {"block": 1, "strategy": "risk-only"},
        "validated_attributed_root_cause_ids": ["PROJECT/CAUSE"]
      }
    ],
    "unique_validated_root_cause_ids": ["PROJECT/CAUSE"],
    "unique_validated_root_cause_count": 1
  }
}
```

모든 request execution은 `execution_evaluations`와 `by_execution`에 정확히 한 번 있어야 한다. 각 execution의 root cause 목록은 그 execution에서 `disposition: validated`이고 `cause_attribution: matched`인 review의 `root_cause_id`를 중복 제거해 byte-order로 정렬한 것이다. campaign 목록은 모든 execution 목록의 합집합을 같은 방식으로 정렬한 것이며 count는 그 길이다. pair별 evaluator count를 단순 합산하지 않는다. pilot처럼 campaign 좌표가 없으면 해당 값은 `null`이다. T4b는 report criterion과 confirmation의 verdict·root cause·run/target이 byte-level source data에서 파생됐는지 다시 검증하는 테스트를 둔다.

## 12. T4b 회귀와 실패 시험

기존 파일은 덮어쓰지 않고 새 출력 디렉터리에서 공용 엔진을 실행한다. 필수 회귀 결과는 다음과 같다.

| 자료 | 기대 결과 |
|---|---|
| v1.1 Subtract, 36 plan/outcome pair | 후보 36개 모두 validated+attributed, 캠페인 고유 root cause 1개 |
| v2 Banyan, 36 plan/outcome pair | 후보 36개 모두 validated+attributed, 캠페인 고유 root cause 1개 |
| v3 Decoder, 1 plan/outcome pair | 후보 1개 validated+attributed, 고유 root cause 1개 |
| 같은 outcome 안의 fixed/Tangle/timeout 등 비후보 run | execution 행은 `no-candidate`, 그 run에서 나온 confirmation 0개 |
| 별도 zero-candidate fixture | complete report, 빈 schema 2 confirmation |

새 pair별 confirmation을 실제 `experiment evaluate`에 넣어야 한다. 기존과 같은 project/original-component count, root-cause 중복 제거, run/target, completion-time upper bound가 나와야 한다. 캠페인 index에서 반복 strategy·seed의 같은 root cause는 하나로 집계한다.

현재 보존 후보는 모두 canonical이므로 새 canonical 규칙에서도 기대 결과가 같다. 과거 report와 새 report의 필드 이름이나 timing bytes가 같은 것은 완료 조건이 아니다. substantive disposition, 세 schema 2 criterion, attribution, root-cause 중복 제거, run/target 연결, evaluator 결과가 같아야 한다.

다음 실패 시험도 필요하다.

- 공유 spec/request/plan/outcome/R1CS/SYM/predicate/reachability hash 불일치 → top-level failed
- 후보 0개, 후보 여러 개, candidate-spec 복수 일치
- `bug_found`인데 candidate record 0개, non-`bug_found`인데 candidate record 존재
- plan target이 runs/failures/skipped에서 누락·중복되거나 index가 다른 경우
- candidate record 일부 누락·중복·파일 hash 불일치와 inventory 불변식
- plan 밖 target, run/target 불일치, raw candidate template·parameter 불일치
- wire 누락·중복, positive-wire alias 값 충돌, 허용된 negative-label eliminated signal, 예상 밖 비-wire key, noncanonical field assignment, R1CS 제약 불만족
- predicate `unknown`, 예외, 허용되지 않은 reason code/class, stdout/stderr 출력
- twin/mutant R1CS 또는 SYM 불일치, witness 재생성 불일치, clean reference noncanonical·불완전·제약 불만족, clean input 불일치, signal projection 불완전
- projected clean rejection은 있지만 relation-exclusion certificate가 없거나 verifier가 실패하는 경우
- 출력 없는 target에서 독립적인 사전 property를 정의하지 않고 clean rejection으로 대체하려는 경우
- reachability parent chain cycle·단절·source hash 불일치·incomplete 탐색
- 같은 root cause 후보가 한 run에 여러 개일 때 confirmation tuple 하나만 생성
- 같은 root cause가 여러 target·seed·strategy에서 반복될 때 캠페인에서는 한 번만 집계

## 13. T4b 완료 조건

T4b는 다음을 모두 만족해야 끝난다.

1. schema 1 spec/request/report/index parser와 unknown-field 거부 구현
2. 공용 R1CS/SYM/assignment 검사와 predicate worker 구현
3. backend와 injection-ground-truth adapter 구현
4. reachability evidence, injection projection, clean relation-exclusion certificate 검증 구현
5. report에서 pair별 confirmation schema 2와 bundle index 자동 생성
6. 12절 회귀·실패 시험과 실제 evaluator 회귀 통과
7. 기존 판정 파일과 raw 후보를 덮어쓰지 않음
8. 원시 값이 tracked output에 없고 predicate stdout·stderr가 비어 있는지 자동 검사
9. `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test` 통과(구현 언어가 추가되면 해당 테스트도 함께 실행)

T4b가 끝나기 전에는 주입 평가 spec을 최종 고정하지 않는다. 개발용 주입은 B 전용 제외 스냅샷에 이미 있는 프로젝트에서만 수행한다.

# S 태그 래퍼 조사·설계 — 2026-10-27

**중단·미완료.** 디스크 여유가 2026-10-26 19:35:27–20:08:16 UTC 동안 33분 연속 15 GiB 미만이었다. 5분 간격 확인값은 13.96→13.90→13.90→13.37→13.37→12.82→14.64 GiB다. 사용자 규칙에 따라 신규 실행을 중단하고 이 부분 보고서만 작성했다. 합성 R1CS 동등성, 정책 A/B 정량표, 별도 Markdown 태그 상세표는 미완료다. [cpu-contention.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/cpu-contention.json)

## 0. 보존 확인

**변경 없음.** HEAD `8065e2b7e165ef3f4c1523f240f5d34ecaefdb22`. 2차 full.diff SHA `01c129fda2241ff892f5d7306506a8928f40e41c0d59d6dc92fe26356e27933f`와 당시 소스 해시를 대조했고, 이전 3차 요청으로 되돌릴 src 파일은 없었다. 이번 src diff SHA `979b95b971b457d606c9c4a23f98702aee471ffa7a421179b509b21ec21d7f5f`. [step0.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/step0.json) · [src-round2-verified.diff](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/src-round2-verified.diff)

이번 작업은 새 Python 도구·시제품·보고서만 작성했다. src, 기존 scripts, 동결 엔진, 프로토콜·기록을 수정하지 않았고 cargo/J/zkFuzz를 실행하지 않았다. 실행 중인 판정과 그 출력·외부 캐시에는 접근하지 않았다. 동결 v2.2 엔진 SHA `c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835`는 읽기 검증만 했다. [Jdesign.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/Jdesign.json)

## 1. 태그 집계와 시제품

2차 적격 1,933개(964+969) 전체와 지정 템플릿의 비적격 6개를 추가해 1,939개를 분류했다. 전체 대상·입력·태그·원본 소스 줄은 [prototype-v2/tag-table.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/prototype-v2/tag-table.json)에 있다. 아래 수는 저장된 inventory를 보고서에 집계한 것이다. [prototype-v2/inventory.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/prototype-v2/inventory.json)

| 리비전 | 2차 적격 | 적격 중 태그 입력 있음 | 적격 중 무태그 | 추가 비적격 |
|---|---:|---:|---:|---:|
| aq-024-6f6781246415 | 964 | 31 | 933 | 3 |
| aq-017-9703bbce0c43 | 969 | 32 | 937 | 3 |



총 태그 대상 69개, 태그 입력 선언 575개. 배열 원소는 확정된 것만 1153개이며 26개 선언의 원소 수는 미확정이다. 따라서 1,153을 전체 입력 수로 해석하지 않는다. [prototype-v2/inventory.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/prototype-v2/inventory.json)

| 태그 종류 | 관측 대상 수 | 범위 |
|---|---:|---|
| 값 없이 선언된 태그 | 69 | 기록된 소스 범위의 presence-only |
| 대상 내부에서 `.태그` 값을 읽음 | 0 | 대상 본문 |
| 부모가 값을 넣음 | 0 | 준비 기록에 포함된 소스 closure |



부모 탐색은 기록된 소스 범위만 포함하므로 전역 호출자의 완전성을 주장하지 않는다. 태그 값 접근·관측된 부모 값 대입을 발견하면 추측하지 않고 생성 거부한다. 미확정 배열 크기는 수치로 세지 않고 원래 정확한 식을 래퍼에 유지한다. 보수적으로 고른 이유는 값/호출자 범위가 불완전한 경우 의미 보존을 단정할 수 없기 때문이다.

강제 없이 붙인 태그: `binary`, `external`, `non_zero_uint64`, `sub_order_bj_p`, `sub_order_bj_sf`, `uint16`, `uint160`, `uint168`, `uint196`, `uint24`, `uint240`, `uint252`, `uint32`, `uint4`, `uint40`, `uint48`, `uint6`, `uint64`, `uint70`, `uint8`, `uint96`. 각 선언의 `value:null`, `enforcement:attached_without_enforcement`, 원본 파일·줄은 생성된 fragment-spec 및 [prototype-v2/planned.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/prototype-v2/planned.json)에 기록했다.

시제품은 무태그 main 입력 → 태그 중간 신호 → `main.c` 대상에 등식으로 전달한다. 태그 뜻을 강제하는 범위·이진 제약을 추가하지 않는다. 원본 target body는 include로 그대로 읽는다. 이는 코드 구조 확인이며 회로 동등성 증명의 대체가 아니다. [scripts/s_tag_wrapper_prototype_20261027.py:389](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/s_tag_wrapper_prototype_20261027.py:389) · [src/targets.rs:2662](/Users/miiz/Desktop/kwzzzz_zkfr/src/targets.rs:2662)

무태그 적격 1870/1870개는 기존 wrapper와 바이트 동일, 미분류 0, 보존 검사 통과. 첫 집계는 별도 루프의 `var i`를 잘못 중복으로 취급해 실패했으며 그 기록을 유지했다. 새 Python 시제품만 고쳐 최종 자체 검사 **17개 통과** 및 전체 재집계를 완료했다. [prototype-v2/untagged-preservation.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/prototype-v2/untagged-preservation.json) · [commands/prototype-self-test-v2/stderr.log](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/commands/prototype-self-test-v2/stderr.log) · [commands/tag-inventory/command.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/commands/tag-inventory/command.json)

## 2. 실제 컴파일 결과

기존 T2051 실패 46개 + 지정 RQ-C 템플릿의 합집합 **48개(리비전당 24개), 성공 48 / 실패 0 / 생성 거부 0**. 각 실제 circom 인자·UTC·진단·R1CS 헤더·산출물 SHA는 [compile/summary.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/compile/summary.json)가 가리키는 개별 result.json에 보존했다. 이번에 만든 R1CS/sym만 해시·헤더 추출 후 제거했다.

| 템플릿 | aq-024 검사 적격 | aq-024 컴파일 / 제약 | aq-017 검사 적격 | aq-017 컴파일 / 제약 |
|---|---|---|---|---|
| RewardsExtended | 통과 | 성공 / 532 [근거](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/compile/0006/result.json) | 통과 | 성공 / 532 [근거](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/compile/0030/result.json) |
| ZoneIdInclusionProver | 통과 | 성공 / 390 [근거](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/compile/0015/result.json) | 통과 | 성공 / 390 [근거](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/compile/0040/result.json) |
| DataEscrowElGamalEncryption | 제외 유지 | 성공 / 125,529 [근거](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/compile/0002/result.json) | 제외 유지 | 성공 / 125,529 [근거](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/compile/0026/result.json) |
| TrustProvidersKyt | 제외 유지 | 성공 / 39,337 [근거](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/compile/0007/result.json) | 제외 유지 | 성공 / 39,337 [근거](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/compile/0031/result.json) |
| ZSwapV1 | 제외 유지 | 성공 / 358,182 [근거](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/compile/0000/result.json) | 제외 유지 | 성공 / 374,372 [근거](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/compile/0024/result.json) |



비적격 6개는 참고 컴파일 성공이며 준비 적격으로 승격시키지 않았다. 시제품 컴파일 성공도 동결 J와의 연결 성공을 뜻하지 않는다.

합성 tagged/reference/bridge 소스와 비교 계획은 [synthetic/fixture-plan.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/synthetic/fixture-plan.json)에 생성했다. 전체 O1 제약 비교 및 O0 복사 등식 투영 검증기는 작성만 했고 구문 검사·자체 테스트·실제 컴파일 모두 미실행이다. **대상 제약 동등성은 미확인**이며 예상 제약 수를 측정값으로 보고하지 않는다. [s_tag_wrapper_synthetic_check_20261027.py](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/s_tag_wrapper_synthetic_check_20261027.py)

## 3. J 연결 설계

핵심 J 소스 5개는 8065e2b와 바이트 동일했다. J는 component wrapper를 자체 O0 R1CS/sym으로 재컴파일하고 전체 신호 suffix 집합을 사이트와 비교한다. 따라서 S에서 이름만 바꾸고 bridge 신호를 제거하는 것으로는 현재 계약을 만족시킬 수 없다. [lifting/mod.rs:520](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:520) · [lifting/mod.rs:1042](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1042) · [lifting/mod.rs:1438](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1438)

| 안 | 필요한 위치·변경 | 동결 엔진/과거 결과 영향·재현 | 판단 |
|---|---|---|---|
| A: S 이름·심볼 투영 | 새 어댑터; J 입력 계약 56–68, 재컴파일 520–575, wire 대조 1063–1099, 전체 집합 1438–1464를 만족하는 artifact/witness 대응 필요 | v2.2 바이트 유지 가능하나 외부 sym 주입 필드가 없어 이름 변환만으로 연결 불가. 기존 원본 입력/도구로 옛 결과 재현 경로는 유지 | 현 형태 비권고, 확신 낮음 |
| B: 새 v2.3 명시적 prefix/view | lifting/mod.rs 38–68, 520–619, 645–697, 1042–1099, 1438–1464, 1653–1687, 2370–2420, 3488–3502; condition.rs 77–116 | raw 전체 R1CS 검증 후 검증된 subtree view. 새 엔진 SHA·개정 기록·별도 cache/결과·해당 요청 재판정 필요. 옛 v2.2와 입력을 보존하면 옛 재현 경로 유지 | 향후 정식 연동 권고, 설계 확신 중간 이상; 구현 미검증 |
| C: 외부 compiler/artifact 어댑터 | 새 도구; lifting/mod.rs 382–393, 520–575, 622–697, 3542–3608 계약에 맞춘 R1CS/sym/witness 일괄 변환 | J 바이트가 같아도 toolchain 변경. 별도 버전/재판정 필요하며 현 동결 실험의 우회로가 아님 | B보다 검증 부담 큼, 확신 낮음 |

각 코드 주장·전체 파일:줄 및 필요한 양방향 projection 증명은 [Jdesign.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/Jdesign.json)의 alternatives/evidence에 기록했다. 복사 등식, alias, 모든 wire 값, honest witness, 원본 template/source와 public IO의 대응을 함께 검증해야 한다. 세 안 모두 실행 검증하지 않았다.

## 4. 영향 측정 계획만

향후 같은 target/source/compiler/seed/대상별 시간/순서로 짝을 고정한다. 공통 대상의 입력 영역 효과와 새 대상 증가 효과를 분리하고, 태그 이름만 보고 임의 의미 제약을 넣지 않는다. raw/중복 제거 후보 수, 생성·실행 J 요청 수, 실패·미처리 수, S+J 시간·준비비용·최대 작업공간을 함께 기록한다. 승인된 미래 J 버전과 request/dedup 규칙을 고정하고 투영 전후 SHA를 보존한다. 지금 후보 증가·오탐·판정 변화는 측정하지 않았다. [Jdesign.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/Jdesign.json)

## 5. 계산 전 고정한 정책 B

정책 B: (템플릿 이름, 정의 소스 파일)로 그룹을 만든다. 그룹 안 인스턴스는 (전체 제약 수, target_id, label) 오름차순이다. 각 라운드에서 모든 남은 그룹의 다음 인스턴스를 하나씩 방문한 뒤 다음 라운드로 간다. 매 라운드 그룹 순서는 자체 소스 우선, third-party 다음이며, 같은 분류에서는 (그룹의 최소 전체 제약 수, 템플릿 이름, 정의 소스 파일) 오름차순이다. 정의 소스의 디렉터리 요소가 node_modules 또는 circomlib이면 third-party다. 그 밖의 vendor 이름만으로 third-party로 분류하지 않는다. 모든 인스턴스를 한 번 방문한 뒤 같은 전체 순서를 반복한다. 총예산 600초, 시도 상한 30초, 남은 예산이 양수이면 min(30초, 남은 예산)을 할당한다. 결함 이름·RQ-C 위치·후보·판정·관측 시간은 순서에 사용하지 않는다. 준비 적격이 아니거나 제약 수가 없는 대상은 가용성 집합에서 제외하며 값을 추측하지 않는다.

정책 SHA `edfc21d7c82353ce01a0b1a83958a7f885cd55ec4e5cb83815cc45f138319076`. 2026-10-26 19:22:45 UTC에 문장·파일 SHA를 보고서에 먼저 기록했다. [policy-preregistration.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/policy-preregistration.json) · [policy-preregistered-report.md](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/policy-preregistered-report.md) · [run_policy_b_order.py](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/run_policy_b_order.py)

Policy B 합성 검사 9개, 계산기 최종 합성 검사 15개 통과. 600초/seed·시도 30초를 유지하고, 순서는 버그 위치·RQ-C·관측 시간과 독립이다. 계산기는 기존 세 seed ledger의 대상별 시간을 쓰고 미관측은 30초로 처리하도록 작성했으나, 실제 결과 저장은 **2 MB 출력 제한 초과로 실패**했다. 그 후 디스크 대기로 출력 중복 제거와 재실행을 하지 못했다. 입력 경로·SHA는 [coverage-input.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/coverage-input.json), 오류는 [commands/coverage-calculation/stderr.log](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/commands/coverage-calculation/stderr.log). 원본 ledger는 인자에 고정된 정확한 파일만 읽었다.

| 리비전 | 현재 컴파일 기준 A/B 묶음·대상·버그 도달 | 시제품 컴파일 기준 A/B 묶음·대상·버그 도달 |
|---|---|---|
| aq-024 | 미완료·수치 미발행 | 미완료·수치 미발행 |
| aq-017 | 미완료·수치 미발행 |

계산 실행은 19:34:22 UTC, 사전 정책 기록 이후였다. 저장되지 않은 중간 결과를 성공으로 간주하지 않는다. 실제 시도 시간 표와 관측/기본값 분모도 미완료다.

## 6. 남은 원인·수정 위치만

| 원인 | 2차 제외 수 aq-024 / aq-017 | 근거·향후 위치 |
|---|---:|---|
| Active/BinaryTag 의존성 누락, TAC01 | 1 / 1 | BlackList 소스 39·42; utils.circom 315–323·874–879. targets.rs:2662 include closure, inspection_fallback.rs:637 함수 수집 |
| 전개 예산 한도 | 3 / 3 | escalarmulany.circom 34·43·95; targets.rs:23, inspection_fallback.rs:180–197·575–609 |
| 함수 검사 예산 한도 | 3 / 3 | poseidon.circom 147·148·178; compile_time_functions.rs:15–16·169–190·218–253 |
| signal 의존 alias 값 미확정 | 4 / 3 | zAssetChecker.circom:87–90; inspection_fallback.rs:106–169·248–280, compile_time.rs:340–342 |

전체 원본 파일 경로·줄과 값은 [Jdesign.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/Jdesign.json)의 remaining_failures/measurements에 있다. `BinaryTag(Active())`는 실제 이진 제약을 만들므로 태그 메타데이터로 대체하면 안 된다. 예산은 무제한 상향하지 않고 정확한 캐시/의존성 분석을 별도 설계해야 한다. signal alias는 임의 0/1로 평가하지 않는다. 이번에는 수정하지 않았다.

## 실행·해시 기록

실행은 모두 nice 19였다. 실제 circom 48회는 2026-10-26 19:33:32–19:33:53 UTC에 한 번씩 직렬 실행했다. 소스와 컴파일러 SHA·명령은 각 receipt, Python 실행 시작/끝과 디스크 대기는 [cpu-contention.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/cpu-contention.json)에 있다. 판정 고정 기간과 겹친 실행은 CPU contention으로 기록했다. cargo 0회, J 0회, 퍼징 0회.

아래는 이 작업의 새 스크립트 해시다. 전체 새 출력·보고서의 파일별 SHA는 [new-files-sha256.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-tag-wrapper-2026-10-27/new-files-sha256.json)에 있다. 보고서는 자기 해시를 본문에 넣지 않고 이 목록 및 별도 report.sha256으로 기록한다. 삭제한 새 R1CS/sym의 해시는 컴파일 receipt에 남긴다.

| 새 파일 | SHA-256 |
|---|---|
| [run_policy_b_order.py](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/run_policy_b_order.py) | `edfc21d7c82353ce01a0b1a83958a7f885cd55ec4e5cb83815cc45f138319076` |
| [s_policy_coverage_20261027.py](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/s_policy_coverage_20261027.py) | `2f3aa222a00098b5813f711f76426551e45d07ec6389726105fc50ca861c9d65` |
| [s_tag_wrapper_prototype_20261027.py](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/s_tag_wrapper_prototype_20261027.py) | `df66878b3de7db94d6048199c2de8cf3432f51fdd8dfabeb9ac1eea3560d1f11` |
| [s_tag_wrapper_run_20261027.py](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/s_tag_wrapper_run_20261027.py) | `bd7ac3a40382bebc37b1d383e7b7337fdf9801a620883782a61236b689d4d302` |
| [s_tag_wrapper_compile_20261027.py](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/s_tag_wrapper_compile_20261027.py) | `906eeff87f61dd3368f7502f1091b39e74d4ada22bfd756eea3f0388221df804` |
| [s_tag_wrapper_synthetic_check_20261027.py](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/s_tag_wrapper_synthetic_check_20261027.py) | `f65e46bc4e414da14e398ade7004a598f501c021c303a47bf28a4593358893ed` |



재개 시 정확한 명령은 저장된 commands/*/command.json에 있다. 기존 출력은 덮어쓰지 않고 새 하위 폴더·새 label을 사용해야 한다. 다음 계산 명령은 **현재 2 MB 제한 실패가 남아 있어 그대로 성공한다고 보장하지 않는다**. 출력 중복 제거 후 재검증해야 한다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr
nice -n 19 python3 -B scripts/s_tag_wrapper_run_20261027.py --label coverage-calculation-resume --timeout 600 -- python3 -B scripts/s_policy_coverage_20261027.py calculate --input runs/s-tag-wrapper-2026-10-27/coverage-input.json --output runs/s-tag-wrapper-2026-10-27/coverage-resumed.json
```

## 확인한 것

- 2차 src 상태에서 변경 없음. 새 시제품만 작성했고 무태그 적격 1,870개 wrapper 바이트 보존을 확인했다.
- 태그 입력과 원본 줄을 JSON 표로 집계했고, 선택한 래퍼 48/48이 실제 컴파일됐다.
- J의 재컴파일·전체 신호 집합 계약 때문에 단순 S 이름 변환만으로 충분하지 않다.
- 정책은 계산 전에 고정됐다. 실제 계산 결과 저장 실패와 디스크 중단을 숨기지 않았다.

## 추정한 것

- 시제품이 원본 target의 전체 제약을 보존한다는 결론은 합성 비교 미실행으로 미확인이다.
- 부모 소스 탐색은 기록된 범위에 한정되며 전체 호출자에서 태그 값이 없다고 단정하지 않는다.
- 정책 B의 도달률, 태그 미강제의 후보/J 요청 증가, v2.3 설계의 실제 호환성은 아직 확인하지 못했다.

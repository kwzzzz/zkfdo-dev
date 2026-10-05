# NB-01 정상 경계 입력 연결 결과

2026-10-02 · 담당 miiz · 버전 `normal-boundary-replay-v1`.

## 목적

완료된 NC-01의 fixture별 수동 입력 공식을 제거할 수 있는지 확인했다. 기존 세 정상 fixture·입력 세 개씩·O0에서, **검증된 원본 witness → 자동 호출 위치 대응 → 입력만 연결 → wrapper 정상 재계산·전체 제약 검사 → 원본 출력 경계 비교**를 실제 실행했다. [사전 범위](SCOPE.md), [값 없는 근거](evidence.json), [착수 전 인계](../../docs/next_step_handoff_2026-10-02.md)를 연결한다.

## 사전 조건별 실제 결과

| 대상 | 기존 입력 ID | 자동 구성 경계 | 원본 계산·전체 제약 | 입력 연결 | wrapper 계산·전체 제약 | 입력 전달 재확인 | 독립 출력 비교 | 판정 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| 기존 discovery fixture | scalar-0 | 7/7 | 1/1 | 7/7 | 7/7 | 7/7 | 7/7 | 성공 |
| 기존 discovery fixture | scalar-2 | 7/7 | 1/1 | 7/7 | 7/7 | 7/7 | 7/7 | 성공 |
| 기존 discovery fixture | scalar-7 | 7/7 | 1/1 | 7/7 | 7/7 | 7/7 | 7/7 | 성공 |
| 반복/상이 파라미터 산술 | scalar-0 | 5/5 | 1/1 | 5/5 | 5/5 | 5/5 | 5/5 | 성공 |
| 반복/상이 파라미터 산술 | scalar-2 | 5/5 | 1/1 | 5/5 | 5/5 | 5/5 | 5/5 | 성공 |
| 반복/상이 파라미터 산술 | scalar-7 | 5/5 | 1/1 | 5/5 | 5/5 | 5/5 | 5/5 | 성공 |
| 작은 배열 통제 | vector-zero | 3/3 | 1/1 | 3/3 | 3/3 | 3/3 | 3/3 | 성공 |
| 작은 배열 통제 | vector-small | 3/3 | 1/1 | 3/3 | 3/3 | 3/3 | 3/3 | 성공 |
| 작은 배열 통제 | vector-mixed | 3/3 | 1/1 | 3/3 | 3/3 | 3/3 | 3/3 | 성공 |

원본 입력 **9/9**, 호출 위치×입력 **45/45**가 모두 완료됐다. 경계는 고유 호출 위치 7/5/3개에 입력 3개씩이며 고유 호출 위치 총 15개다. 원본 계산/제약 검사는 9회, wrapper 계산/제약 검사는 45회로 각각 성공했다. 실패·미지원·미실행은 0개이며, 실패해도 남기도록 사전 생성한 9/45 분모를 유지했다.

입력 연결/전달은 **57/57 입력 leaf**, wrapper가 새로 계산한 출력 비교는 **57/57 출력 leaf**다. 입력 전달 재확인은 원본에서 읽은 값이 그대로 들어갔는지 확인한 것이므로 독립 출력 성과와 합산하지 않는다. 이번 45개를 NC-01 O0의 45개에 더해 독립 사례 수를 늘리지 않는다.

자동 discovery 3회, 실제 컴파일 **15/15**(대상별 원본 포함 8/4/3회), 컴파일 인터페이스 조회 15회가 성공했다. 컴파일 구성은 wrapper 7/3/2개이고 호출 위치 7/5/3개를 별도로 유지했다. 산술의 같은 `Step(2)` 구성 3곳, 배열의 같은 `VecStep(2,2)` 2곳은 컴파일만 재사용했다. 각 입력 조건에서 이 경로들의 입력 값과 원본 index 집합이 실제로 서로 달랐으며 각각 새 witness를 계산했다. 수동 wrapper 대체는 없다.

## 자동화한 부분과 출처

새 [measure_normal_boundary_replay.py](../../scripts/measure_normal_boundary_replay.py)의 `infer_port`·`read_inputs`·`compare_port`가 제한된 연결 경로를 구현한다. 기존 discovery/wrapper 생성은 그대로 사용하고, NC-01의 컴파일·정상 계산 helper만 재사용한다. 이전 측정 코드는 수정하지 않았다.

- 원본 정상 계산·전체 witness R1CS 검사(exit 0 및 `WITNESS IS CORRECT`)·export가 모두 통과해야 `read_inputs`를 호출해 값을 읽는다. 원본 실패/미완료는 하위 실행을 막고 분모에 남긴다.
- 입력 함수는 원본 symbol/witness, 자동 discovery의 prefix, wrapper symbol과 컴파일 입력 개수만 받는다. fixture 이름이나 경로별 offset/크기 표를 받지 않는다. wrapper `.sym`의 `main.in/out` 모양과 `snarkjs r1cs info`의 입력/출력 개수를 대조한 후 원본 호출 위치의 정확한 leaf 집합을 확인한다. 사전 호출 목록은 분모 확인용이다.
- 원본의 `prefix.in`만 읽는다. 출처 입력 ID·witness/export/symbol 해시·검사 명령·신호 이름·wire index와 wrapper 입력 파일 해시를 경계별로 남겼다. 이전 `adapter()`·`oracle()`는 새 실행에서 호출하면 즉시 실패하도록 차단했다. 진단 대조도 입력 공급원으로 쓰지 않았다.
- wrapper 입력 파일 45개는 모두 `in` 키만 포함한다. 원본 출력·witness 파일을 wrapper 계산 인자로 전달하지 않았으며, wrapper 자신의 WASM이 입력 JSON으로 새 witness와 출력을 생성했다. 전체 R1CS 검사 뒤 `main.in` 재확인과 `main.out` 독립 비교를 별도 필드로 기록했다.

[원본 도구 ledger](../../runs/n4-1-normal-boundary-replay-2026-10-02/run-v1/commands.jsonl)와 [출처·보존 확인](../../runs/n4-1-normal-boundary-replay-2026-10-02/validation-v1/source-and-preservation-check.json)이 수치의 근거다. 오프라인 record/aggregate는 사용·수정하지 않았다. 원시 정상 입력·witness·컴파일 산출물은 ignored runs에만 있고 이 보고서와 evidence에는 값 대신 참조·해시·판정·시간을 남겼다.

## 실측 비용과 재실행 조건

단위는 wall 초다. 각 fixture의 기존 입력 세 개를 순차 1회 실행했고 조건 사이 application compile cache는 비웠다. 조건 내 동일 wrapper/dependency/compiler hash·flags·library 경로·timeout인 구성만 재사용했으며 OS cache는 비우지 않았다.

| 대상 | 준비 | 원본 계산/검사/export | 입력 연결 | wrapper 계산/검사/export | 입력 재확인·출력 비교 |
|---|---:|---:|---:|---:|---:|
| 기존 discovery fixture | 2.482852 | 1.324448 | 0.001566 | 9.042834 | 0.000654 |
| 반복/상이 파라미터 산술 | 1.102179 | 1.318405 | 0.001059 | 6.784218 | 0.000428 |
| 작은 배열 통제 | 0.771328 | 1.325368 | 0.000740 | 3.730704 | 0.000365 |
| 합계 | 4.356359 | 3.968221 | 0.003365 | 19.557756 | 0.001447 |

준비는 자동 구성·원본/필요 wrapper 컴파일·R1CS 인터페이스 조회·symbol/cache 확인까지다. 원본/조각 시간은 입력 JSON 준비·정상 계산·전체 제약 검사·export를 포함한다. 입력 연결은 직접 대응·출처 참조 생성이며, 비교는 검증된 두 witness의 입력 재확인·출력 비교다. subprocess별 계산·제약 검사·export wall도 ledger에 별도 보존했다. source/tool snapshot·버전 조회·최종 manifest·보고·회귀 검사는 표에서 제외했다. NC-01과 준비 계측 범위도 같지 않으며 소수 실행으로 속도 우위를 주장하지 않는다.

Circom 2.2.3, Node v26.0.0, snarkjs 0.7.6, zkfDO 0.1.0, Python 3.14.7, Darwin arm64. 옵션은 `--O0 --r1cs --wasm --sym --inspect --prime bn128`다. snarkjs의 버전 조회만 기존과 같이 exit 99로 버전/help를 출력했고 모든 실제 discovery·compile·interface·calculate·check·export 명령은 exit 0이다. 도구·소스·스크립트 hash는 첫 실제 조건 실행 전에 [conditions.json](../../runs/n4-1-normal-boundary-replay-2026-10-02/run-v1/conditions.json)에 기록했다.

실제 실행 구간은 한국 시각 **2026-10-02 00:37:04.907949–00:37:32.799517**(UTC 10-01 15:37:04.907949–15:37:32.799517)이다. 입력 계획 고정 시각과 필수 검사별 실제 wall은 evidence에 기록했다. N4-1 작업 상한 12시간을 유지한다. 과거 active-work 사용시간은 unknown이며 이 구간을 사람의 누적 사용시간 또는 잔여 예산으로 바꾸지 않는다.

## 회귀·수용 기준·보존

[새 회귀 검사](../../tests/normal_boundary_replay_test.py) 15개와 기존 정상 검사 13개, 총 **Python 28개 통과**다. 검증 전 gate, 서로 다른 호출의 입력, 호출명 변경과 witness 값 변화, scalar/배열 모양, 일부 입력 결측, 중복 symbol·중복/결측 인터페이스 개수, 부분 출력 미지원과 실제 불일치의 공존을 확인했다. 출력 mismatch 회귀는 비보안용 합성 metadata 비교이며 실제 결함 재현 자료를 만들지 않았다.

`cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`를 실행했다. Rust **297 passed, 0 failed, 22 ignored**다. 실행 후 측정 코드는 변경하지 않았으므로 추가로 다시 실행할 영향 조건은 없다. 모든 사전 조건을 설명한 이 시점에서 종료한다.

도착한 [사전 수용 기준](../normal-boundary-replay-contract-2026-10-02/REVIEW.md)은 구현 검증 보고서가 아니다. 파일은 수정하지 않았으며, 실행 전에 부분 입력 leaf의 실패 사유 보존과 출력 결측이 확인된 불일치를 숨기지 않는 처리를 보완했다.

| 기준 | 이번 근거와 처리 | 한계 |
|---|---|---|
| 선행 성공·출처 | 원본 9개 gate 통과, 45개 입력 파일·57leaf 출처 연결 | 고정 정상 실행만 다룸 |
| 파라미터·shape·호출 | instance key/구체 파라미터/컴파일 단위 유지, 재사용 호출별 다른 입력·index 확인 | 실제 배열 길이 2/3만 실행 |
| 수동 공식 비의존 | 입력 함수에 fixture 인자 없음, adapter/oracle 실행 차단, 이름·witness 변화 회귀 | 원본 입력은 기존 고정값 |
| 전달과 독립 출력 | 입력 재확인 57leaf와 새 계산 출력 57leaf를 별도 기록 | 전달 일치를 독립 성과로 합산하지 않음 |
| 결측·모호성 | gate·shape·index·부분 결과 회귀, 사전 9/45 분모 보존 | 실제 고정 조건의 미지원은 0개이며 모든 오류 종류가 실제 fixture에서 발생했다는 뜻은 아님 |

기존 NC-01/정상 실행 자료·측정 코드·record/aggregate·원고를 포함한 **3,263개 파일**이 시작 baseline과 같은 hash다. 검토 파일도 수신 시점 hash와 일치한다. 별도 전면 검토를 완료 조건으로 추가하지 않았다. commit/push/PR 없이 로컬 결과만 남겼다.

## 남은 수작업·미지원과 주장 한계

이번 9/45 범위에서는 미지원 0개다. 원본 entrypoint를 위한 정상 입력 세 개씩은 여전히 사람이 이미 고정한 값이고, 대상·입력 선정이 자동화된 것은 아니다. 지원은 `in/out` scalar/1차원 1–8 요소로 제한하며 실제 배열 확인은 2/3이다. 다른 포트·다차원·모호한 symbol·소실 index가 필요하면 미지원으로 남긴다. O1 복원은 시도하지 않았고 NC-01의 O1 미지원은 그대로다.

주장할 수 있는 범위는 **기존 세 정상 fixture의 O0와 고정 입력 세 개에서, 경계 45개의 입력을 수동 공식 없이 검증된 원본 witness에서 읽어 연결했고 wrapper가 독립 계산한 출력이 해당 원본 출력 경계와 모두 일치했다**는 것이다. 기존 컴포넌트 경계 기반 자동 구성의 제한된 정상 경로 증거이며 임의 회로의 일반 분해 알고리즘이나 신규성 증거가 아니다.

범용 정상 입력 합성, 모든 입력·악의적 할당의 의미 보존, 결함 후보 투영·원인 귀속·호출 맥락 판정·프로젝트 결함·탐지 우위·총비용 우위는 입증하지 않았다. NC-01과 같은 자료이므로 독립 사례를 늘리지 않는다. N4-1 전체 미완료·N4-2 미착수·N5 미고정을 유지한다.

## 다음 결정 한 가지

miiz가 **A안 비교 실행에 필요한 시간·실사용 자원·종료/잔여 예산 계측을 다음 최소 개발 범위로 채택할지** 결정한다. 이는 제안이며 새 실행 승인이 아니다. 정상 예제 추가·O1 복원·퍼징·후속 평가를 자동으로 시작하지 않는다.

## 주요 고정 참조

- [measure_normal_boundary_replay.py](../../scripts/measure_normal_boundary_replay.py): `eb6b9ef5182c075f4d7ce42084858e190349f0a16c40eb4057e4888c9c14ba5e`
- [normal_boundary_replay_test.py](../../tests/normal_boundary_replay_test.py): `9ae974f2ed43d2692119d1779a3ad0f85edec8d77508ebcd6e5ea2568eaa938e`
- [input-plan.json](../../runs/n4-1-normal-boundary-replay-2026-10-02/run-v1/input-plan.json): `e3e1a8990019295b38ed0ade1809a24db6918a6131ff5db7f1912e60d98649a2`
- [commands.jsonl](../../runs/n4-1-normal-boundary-replay-2026-10-02/run-v1/commands.jsonl): `193c202278309c4575b70844627c8debe1856db44141ba3cbcf0f8ff041f7084`
- [summary.json](../../runs/n4-1-normal-boundary-replay-2026-10-02/run-v1/summary.json): `73b52da55a9e9ac59ab94871f83568db683382357f60bb7386501f3e0f07d45a`
- [conditions.json](../../runs/n4-1-normal-boundary-replay-2026-10-02/run-v1/conditions.json): `f88f5c2fa6d5b2b0345f8aca34105cb96d8a1b32cd4a1746a7499819aca2a153`
- [evidence.json](evidence.json): `5530c0bc14254a3d30256d6596abcdb34781f931acbac5f3a3fc1f99422fe72e`
- [필수 검사 원문](../../runs/n4-1-normal-boundary-replay-2026-10-02/validation-v1/results.json).

[논문 근거 색인 NB-01](../../docs/paper_evidence_index.md) · [현재 계획](../../docs/plan_revision_2026-10-01.md).

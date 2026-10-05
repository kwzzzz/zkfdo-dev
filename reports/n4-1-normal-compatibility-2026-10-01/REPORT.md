# NC-01 정상 호환성 실행 결과

실행 2026-10-01, 정리 2026-10-02(한국 시각) · 담당 miiz · 버전 `normal-compatibility-v1`. 실행 전에 정한 [SCOPE](SCOPE.md)와 세 대상별 3입력을 그대로 사용했다. [값 없는 근거](evidence.json)의 원본 ledger·파일 해시에서 다음 6조건을 확인할 수 있다.

| 대상 | 옵션 | 컴파일 성공/시도 | 정상 계산 | 제약 검사 | 전체 경계 일치/분모 | leaf 일치/분모 | 준비(초) | 정상 검증(초) | 조건 판정 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| 기존 discovery fixture | O0 | 8/8 | 24/24 | 24/24 | 21/21 | 42/42 | 0.214161 | 10.588127 | 성공 |
| 기존 discovery fixture | O1 | 8/8 | 24/24 | 24/24 | 0/21 | 0/42 | 0.201283 | 9.530163 | 미지원 |
| 반복/상이 파라미터 산술 | O0 | 4/4 | 18/18 | 18/18 | 15/15 | 30/30 | 0.076287 | 8.705817 | 성공 |
| 반복/상이 파라미터 산술 | O1 | 4/4 | 18/18 | 18/18 | 12/15 | 27/30 | 0.079792 | 7.767832 | 미지원 |
| 작은 배열 통제 | O0 | 3/3 | 12/12 | 12/12 | 9/9 | 42/42 | 0.067768 | 5.298036 | 성공 |
| 작은 배열 통제 | O1 | 3/3 | 12/12 | 12/12 | 3/9 | 33/42 | 0.070425 | 5.140930 | 미지원 |

**O0는 세 대상 모두 전체 경계가 일치했다. O1은 세 대상 모두 자동 구성·실제 컴파일·정상 계산·R1CS 검사를 통과했지만 직접 대응할 수 없는 신호가 남아 조건 전체는 미지원이다.** 실제 도구 실행 실패나 확인된 값 불일치는 0건이다. 미지원은 불일치나 탐지 음성이 아니다. 소실 신호를 복원하지 않아 O1의 일반적인 정상 의미 동등성 여부는 이 결과로 결정하지 않는다.

## 분모와 실제 실행

- 3개 작은 정상 fixture × O0/O1 × 사전 입력 3개. 독립 실제 프로젝트·결함 사례 수가 아니다. 기존 discovery fixture의 RSA 등 이름은 단순 항등 산술 placeholder이며 실제 암호 구현을 평가한 것이 아니다.
- 조건당 원본 1개와 자동 discovery의 호출 위치 7/5/3개, wrapper 컴파일 구성 7/3/2개다. 동일 인스턴스 반복과 서로 다른 파라미터를 유지했다. 원본 포함 실제 컴파일은 조건당 8/4/3회, 총 30회다.
- 자동 `targets --no-validate` 6회가 모두 성공했다. 이 옵션은 탐색 중 컴파일 검증을 생략할 뿐이며, 이후 원본과 생성 wrapper를 실제 Circom으로 컴파일했다. 수동 wrapper 대체는 없다.
- 정상 계산·전체 생성 witness의 R1CS 검사·witness export 각 108회: 원본 18회 + 호출 위치별 wrapper 90회. 원본 정상 출력 oracle은 scalar 12개·배열 요소 18개가 모두 일치했다. 출력 oracle 일치가 내부 경계 성공을 대신하지 않는다.
- 경계 단위는 **호출 위치 × 입력**이다. 양쪽 입력·출력의 모든 leaf가 확인되어야 그 경계가 성공한다. 전체 90개 중 60개 확인, 30개 미지원이며 leaf 228개 중 174개 일치, 54개 미지원이다. 3개 입력·옵션 반복을 독립 사례로 합산하지 않는다.

## O1 미지원의 구체적 원인

| 대상 | 직접 확인하지 못한 신호 | 남긴 분모와 판정 |
|---|---|---|
| 기존 fixture | 원본의 7개 호출 경계 입력·출력 모두 `.sym` witness index=-1. 각 wrapper의 입력도 -1 | 21/21 경계 미지원, 42/42 leaf 미지원. wrapper 출력만 존재한다고 성공으로 채우지 않음 |
| 산술 통제 | 원본 `main.a.in` index=-1 | 3/15 경계 미지원, 나머지 12개 일치. leaf 27/30 일치, 3개 미지원 |
| 배열 통제 | 원본 `main.a.in[0]`, `main.a.in[1]`, `main.c.out[2]` index=-1 | 6/9 경계 미지원, `main.b`의 3개 경계만 전체 일치. leaf 33/42 일치, 9개 미지원 |

없는 값에 0을 넣거나 입력식·root 출력 alias로 치환하지 않았다. 원본·wrapper의 모든 정상 계산은 동일한 사전 fixture 입력 어댑터로 계속 실행했지만 그 어댑터를 소실 신호의 관측 근거로 쓰지 않았다. 배열 O0는 길이 2/3의 입력·출력 전체가 일치한다. 배열 O1의 원인은 배열 shape 파싱 실패가 아니라 이 실행에서 최적화로 제거된 직접 대응 신호다. 새로운 최적화 역복원은 구현하지 않았다.

## 구현과 조건

새 [measure_normal_compatibility.py](../../scripts/measure_normal_compatibility.py)가 보존된 v1의 도구 ledger·탐색 그래프 읽기를 사용하고 O0/O1 옵션, 작은 scalar/1차원 배열 입력, 단계별 상태·미지원 이유·분모를 추가한다. [회귀 검사](../../tests/normal_compatibility_test.py)는 소실·결측·범위 밖 index, 선언보다 많은 배열 요소, shape 오류, 비정규 필드 값, 부분 출력 일치, 실제 불일치를 구분한다. 기존 자동 탐색·wrapper 코드, 측정 v1, offline record/aggregate 코드는 수정하지 않았다.

`VecStep(n,k)` 배열 통제는 `(2,2)` 두 호출과 `(3,3)` 한 호출로 제한했다. 요소별 제곱·상수 덧셈을 모두 제약하며 원시 소스는 ignored runs에 보존했다. 지원 인터페이스는 명시된 scalar/1차원 길이 1–8까지다. **실제 확인한 배열 길이는 2/3뿐**이며 길이 1–8 전체 또는 다차원 배열을 실험으로 확인했다는 뜻이 아니다. 정상 입력 어댑터는 이 세 fixture 전용이며 범용 입력 자동 합성 기능이 아니다.

Circom 2.2.3, Node v26.0.0, snarkjs 0.7.6, zkfDO 0.1.0, Python 3.14.7; Darwin arm64. 모든 조건에 `--r1cs --wasm --sym --inspect --prime bn128`와 해당 `--O0`/`--O1`를 사용했다. snarkjs의 `--version`은 버전/help 출력 후 exit 99였으며 그 원본도 보존했다. 컴파일·계산·제약 검사 명령은 모두 exit 0이다. 정확한 실행 바이너리·도구·소스·flags·해시는 [evidence.json](evidence.json)에 있다.

조건 순서는 표 순서로 각 1회다. application compile cache는 조건마다 비우고 같은 조건에서 wrapper 바이트·전체 dependency hash·컴파일러 hash·flags·library 경로·timeout이 같은 구성만 재사용했다. 산술은 조건당 2개, 배열은 1개의 중복 호출 컴파일이 재사용됐다. OS cache는 비우지 않았다. O0/O1 사이의 artifact 재사용은 없다.

## 시간과 작업 상한

준비 wall은 자동 discovery/wrapper 생성, 원본/필요 wrapper 컴파일과 의존성·cache provenance 확인 구간이다. 정상 검증 wall은 입력 파일 준비·정상 계산·R1CS 검사·export·직접 symbol 대응과 출력 oracle 비교 구간이다. 도구/소스 snapshot, 버전 조회, 최종 hash·보고서, cargo·회귀 검사는 제외했다. 별도 subprocess wall과 timeout은 원본 ledger에 보존했다.

6조건 준비 합계 **0.709716초**, 정상 검증 합계 **47.030906초**다. 조건별 소수 1회 측정이므로 성능 우위·열위나 O1 비용 효과를 주장하지 않는다. 이전 NE-01/02 캠페인과 수치나 분모를 합치지 않는다.

실제 6조건 구간은 UTC 14:56:20.312874–14:57:08.058959(한국 시각 23:56:20–23:57:08)이다. 이번 입력 사전 고정 시각과 검사별 실제 wall도 근거에 기록했다. N4-1 상한 12시간은 유지한다. 과거 및 이번 사람의 active-work 사용시간은 계측하지 않아 unknown이며 프로세스 시간이나 문서 작성 구간으로 대체하지 않는다. 잔여 작업시간을 임의로 추정하지 않는다.

## 검증·보존·종료 상태

- `cargo fmt` 통과. 먼저 check로 보호 파일의 예상치 못한 formatting 변경이 없음을 확인한 뒤 실제 fmt 실행.
- `cargo clippy --all-targets --all-features -- -D warnings` 통과.
- `cargo test`: **297 passed, 0 failed, 22 ignored**. Python 정상 회귀 **13 passed**(신규 9 + 기존 4).
- 기존 정상 실행·보고서·측정 v1 등 **1,974개 파일**의 baseline hash가 모두 유지됐다. 기존 두 fixture의 소스 바이트도 이전 실행과 일치한다. record/aggregate 보호 파일도 전후 hash 일치한다. 원본 ledger와 실행 산출물을 사후 수정하지 않았다.
- 6조건을 모두 시도했고 실행 후 구현 수정이 없어 재실행할 영향 조건은 없다. 추가 포괄 검토·O2·새 프로젝트·새 분석 기법으로 확장하지 않는다. 실제 오류 로그 대신 성공을 추정한 조건은 없다.

이번 NC-01의 고정 질문은 완료했다. **N4-1 전체 미완료, N4-2 미착수, N5 미고정**이다. O1 전체 경계 확인에는 별도로 입증된 mapping 경로가 필요하며 이 범위에서는 미지원으로 종료한다. 결함 후보의 통째→컴포넌트 투영, 원인 귀속, wrapper의 일반 의미 보존, abort/입력 전제, A안의 예산·종료·공정성 구현 및 검증은 이 정상 실험으로 해결되지 않는다. 결함 후보 생성·퍼징·평가 실행은 하지 않았다.

## 원문 경로와 주요 해시

- [input-plan.json](../../runs/n4-1-normal-compatibility-2026-10-01/run-v1/input-plan.json): `1814314d555c791ede7544c4ae56b225dec633ad8ecc424fce13776f831b7166`
- [commands.jsonl](../../runs/n4-1-normal-compatibility-2026-10-01/run-v1/commands.jsonl): `030434f21567da0360c9243b607c8624c5f11dccdd5954921b1906dcf535318c`
- [conditions.json](../../runs/n4-1-normal-compatibility-2026-10-01/run-v1/conditions.json): `63e8a7684e1258ba143aada28ff6434c37e1a99af42f888b4c352c1fb8c0734c`
- [summary.json](../../runs/n4-1-normal-compatibility-2026-10-01/run-v1/summary.json): `e2061b6f82fe14017a47e4fd84ef1f5553df1282019073ca344a8c5f4b3fe618`
- [artifact-manifest.json](../../runs/n4-1-normal-compatibility-2026-10-01/run-v1/artifact-manifest.json): `6fdc4a4f14313193367dda967ac4deaacdfdc3194c195f182f0937103664749e`
- [검사·보존 기록](../../runs/n4-1-normal-compatibility-2026-10-01/validation-v1/results.json), [보존 확인](../../runs/n4-1-normal-compatibility-2026-10-01/validation-v1/preservation-result.json).
- [evidence.json](evidence.json): `f1e44ce8435159a98065e80d8215986e5f6eb97c1a1ef9f317cc0ad3dfed8894`

[NC-01 색인](../../docs/paper_evidence_index.md) · [현재 계획](../../docs/plan_revision_2026-10-01.md). commit/push/PR 없이 로컬 산출물만 남겼다.

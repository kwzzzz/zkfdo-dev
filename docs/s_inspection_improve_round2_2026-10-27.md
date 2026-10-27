# S fragment 검사 범위 개선 2차 — 2026-10-27

검사 통과는 aq-024 **187→910→964/975**, aq-017 **191→914→969/979**(원본→1차→2차)다. 기존 적격 산출물 보존은 **2,732개, 차이 0**. 새 통과 대상의 고정 표본은 두 단위 모두 **31/50(62%)**가 실제 래퍼 컴파일에 성공했다. 요구 RQ-C 템플릿의 이번 신규 검사 통과는 **0종**이며, RewardsExtended·ZoneIdInclusionProver는 1차 검사 통과를 유지하지만 컴파일은 실패했다.

**기준과 패치.** HEAD `8065e2b7e165ef3f4c1523f240f5d34ecaefdb22`, 시작 작업 트리는 1차 변경을 포함하므로 clean이 아니다. 변경 전에 [작업 트리 기준 패치](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/base-working-tree.diff)를 저장했다(SHA-256 `edc51ddfd0df22e6748ea1e221b4312acacfbca19331b3a5d042c43f17153230`). 1차 종료 상태와의 차이는 [base-vs-round1.diff](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/base-vs-round1.diff)의 빈 패치(SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`)이며, 1차 패치 재구성과 시작 파일의 일치를 [별도 검증](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/base-round1-verification.json)했다.

이번 코드·새 스크립트의 [implementation.diff](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/implementation.diff) SHA-256은 `635827987e29de0231e82e8f2f879a247deebd6aa6b10de01915e1d3d65be480`. 보고서·계획 상태표까지 포함한 [full.diff](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/full.diff)의 해시는 [full.diff.sha256](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/full.diff.sha256)에 따로 둔다(보고서 자체를 포함하므로 자기참조 방지). 파일별 해시는 [artifact-hashes.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/artifact-hashes.json)에 있다. 기존 동결 기록·원본 입력·기존 scripts는 수정하지 않았다.

**구현·제한.** 정수 나눗셈→함수 문장→RQ-C 잔여 구문 순서로 집중 테스트 후 확장했다.

- [compile_time.rs:463](/Users/miiz/Desktop/kwzzzz_zkfr/src/targets/compile_time.rs:463): `\`, `%`는 양쪽 정수를 bn128의 `[0,p)` 대표값으로 정규화한 후 임의 정밀도 정수 몫·나머지를 계산한다. 0(또는 p의 배수)로 나누면 거부한다. `\=`, `%=`에도 같은 연산을 쓴다. 음수·큰 정수·우선순위·0 나눗셈 검사를 추가했다. 나머지 산술은 기존 checked-i128 부분집합이며 일반 필드 역원 `/`, 비트 연산·overflow는 확장하지 않았다. 의미는 로컬 Circom 소스 [modular_arithmetic.rs:46](/Users/miiz/Desktop/kwzzzz_zkfr/.external/circomspect/circom_algebra/src/modular_arithmetic.rs:46)와 대조했다.
- [compile_time_functions.rs:294](/Users/miiz/Desktop/kwzzzz_zkfr/src/targets/compile_time_functions.rs:294): 실행되는 `assert` 조건을 정확히 확인한다. 거짓이면 소스 파일·줄과 `compile-time assert failed`로 거부한다. 도달하지 않는 `assert(0)`은 실행하지 않는다. `log`는 문자열·평가 가능한 정수 인자만 확인하고 값을 출력하지 않는다. signal/component/constraint 및 미지원 문장은 계속 거부한다. assert의 필드 0·음수·배열, 중첩 호출·로그·부작용 거부를 테스트했다. [함수 블록 처리:511](/Users/miiz/Desktop/kwzzzz_zkfr/src/targets/compile_time_functions.rs:511)는 기존 실행 예산을 불필요하게 소모하지 않도록 유지했고 12,000회 루프 회귀 검사를 통과했다.
- [compile_time.rs:233](/Users/miiz/Desktop/kwzzzz_zkfr/src/targets/compile_time.rs:233): 실제 DataEscrow/TrustProviders/ZSwap 소스에서 막힌 작은 삼항식 확장을 추가했다. 양쪽 분기가 모두 확정 정수여야 하며 조건의 필드 0 여부로 선택한다. 미선택 분기의 불명확한 값도 거부하고 배열·괄호 없는 중첩 삼항식은 받지 않는다. [Circom 문법:507](/Users/miiz/Desktop/kwzzzz_zkfr/.external/circomspect/parser/src/lang.lalrpop:507)에 맞춰 우선순위·중첩·거부 검사를 추가했다.
- [inspection_fallback.rs:200](/Users/miiz/Desktop/kwzzzz_zkfr/src/targets/inspection_fallback.rs:200), [audit:212](/Users/miiz/Desktop/kwzzzz_zkfr/examples/s_inspection_audit.rs:212): 원래 토큰을 변경하지 않고 프로젝트 소스의 정확한 줄을 진단에 보존한다. 새로운 허용 의미를 추측하거나 실행 예산을 늘리지 않았다. 미지원 함수 문장, signal 유래 상수, 누락된 include, 실제 component 슬롯 덮어쓰기는 계속 제한한다.

**검사 수와 사유.** [원본](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-26/baseline/measurement.json), [1차](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-26/after/measurement.json), [2차](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/after/measurement.json)의 모든 상세 행을 [inspection-summary.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/inspection-summary.json)에서 재집계하고 입력 SHA를 대조했다.

| 단위 | 전체 | 원본 검사 | 1차 검사 | 2차 검사 | 2차 증가 | 과거 prepared 적격 |
|---|---:|---:|---:|---:|---:|---:|
| aq-024-6f6781246415 | 975 | 187 | 910 | 964 | +54 | 179 |
| aq-017-9703bbce0c43 | 979 | 191 | 914 | 969 | +55 | 183 |

검사 적격과 전체 준비 적격은 다르다. 과거 비검사 관문까지 재사용하면 조건부로 933/937개지만, 아래 표본 외에는 이번에 재컴파일하지 않았으므로 새 준비 성공 수로 주장하지 않는다.

아래는 주요 사유와 2차의 모든 잔여 사유 **발생 수**다(한 대상에 여러 사유 가능). 전체 문자열별 집계는 위 summary에 있다.

| 사유 | aq-024 원본→1차→2차 | aq-017 원본→1차→2차 |
|---|---:|---:|
| 배열 토큰 `[` | 712→0→0 | 712→0→0 |
| compile-time 변수 배열 | 265→0→0 | 263→0→0 |
| unknown compile-time value 합 | 829→1→4 | 654→1→3 |
| 함수 내부 미지원 문장 | 0→43→0 | 0→44→0 |
| 정수 나눗셈 suffix | 0→18→0 | 0→18→0 |
| 확장 예산 초과 | 0→0→3 | 0→0→3 |
| 함수 검사 예산 초과 | 0→0→3 | 0→0→3 |
| unknown function Active | 0→0→1 | 0→0→1 |

2차 unknown value는 모두 `isZeroExternalAmounts`다. 사유가 바뀐 것은 이전 차단을 지난 뒤 다음 차단에 도달한 결과이며, 예산 초과도 실패로 남겼다.

**RQ-C 및 실제 컴파일.** [원본 매핑](/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json)의 aq-024 직접 매핑 5종(6개 래퍼), aq-017 직접 매핑 2종과 요청된 같은 5종 하위 조각(합계 8개)을 모두 컴파일했다. 아래 수치는 각 단위의 검사/컴파일 성공 개수다. T2051은 `Main component cannot have inputs with tags`, TAC01은 `The template BinaryTag does not exist`다. 각 실패의 전체 컴파일러 문구·정확 경로·줄·로그 SHA는 [compile-summary.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/compile-summary.json)에 있다.

| 템플릿 | aq-024 검사 / 컴파일 | aq-017 검사 / 컴파일 | 남은 검사 사유 / 컴파일 오류 |
|---|---|---|---|
| BabyJubJubSubOrderTag | 2/2 / 2/2 | 2/2 / 2/2 | 없음 |
| RewardsExtended | 1/1 / 0/1 | 1/1 / 0/1 | 검사 통과 / T2051, wrapper `target.circom:5:18` |
| ZoneIdInclusionProver | 1/1 / 0/1 | 1/1 / 0/1 | 검사 통과 / T2051, wrapper `target.circom:5:18` |
| ZAccountBlackListLeafInclusionProver | 0/1 / 0/1 | 0/1 / 0/1 | Active 미정의 / TAC01, 아래 소스 `:42:61` |
| DataEscrowElGamalEncryption | 0/1 / 0/1 | 0/1 / 0/1 | 확장 예산 초과 / T2051, wrapper `target.circom:5:18` |
| TrustProvidersKyt | 직접 매핑 아님 | 0/1 / 0/1 | 함수 검사 예산 초과 / T2051, wrapper `target.circom:5:18` |
| ZSwapV1 | 직접 매핑 아님 | 0/1 / 0/1 | signal alias 값 미확정 / T2051, wrapper `target.circom:5:18` |

요청한 네 템플릿의 정확한 현재 검사 차단 위치는 다음과 같다. 수정 전 차단의 정적 소스 추적은 [rqc-source-reasons.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/rqc-source-reasons.json), 최종 동적 진단은 inspection-summary에 보존했다.

- aq-024 ZAccountBlackListLeafInclusionProver: [zAccountBlackListLeafInclusionProver.circom:39](/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a1b-2026-10-08/units/aq-024-6f6781246415/project/circuits/circuits/templates/zAccountBlackListLeafInclusionProver.circom:39) — `unknown compile-time function Active`.
- aq-024 DataEscrowElGamalEncryption: [escalarmulany.circom:43](/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a1b-2026-10-08/units/aq-024-6f6781246415/project/circuits/node_modules/circomlib/circuits/escalarmulany.circom:43) — `compile-time expansion budget exhausted`.
- aq-017 TrustProvidersKyt: [poseidon.circom:178](/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a1b-2026-10-08/units/aq-017-9703bbce0c43/project/circuits/node_modules/circomlib/circuits/poseidon.circom:178) — `compile-time function inspection budget exhausted`.
- aq-017 ZSwapV1: [zAssetChecker.circom:89](/Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-a1b-2026-10-08/units/aq-017-9703bbce0c43/project/circuits/circuits/templates/zAssetChecker.circom:89) — `unknown compile-time value isZeroExternalAmounts`.

BlackList의 `Active`와 `BinaryTag` 정의는 별도 utils 파일에 있으나 기록된 wrapper 의존 파일에 없다([의존 범위 증거](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/rqc-blacklist-closure.json)). 임의 include 추가는 하지 않았다. ZSwap의 `isZeroExternalAmounts.out`은 signal 입력의 합을 받는 IsZero 출력이다(`zAssetChecker.circom:76–90`). 상수로 추측할 수 없고, 이 signal alias를 안전하게 생략하는 의존 분석은 이번 범위에서 미구현이다. 예산 증액·래퍼 태그 의미 변경까지 확장하지 않은 이유는 작은 정확한 구문 확장 범위와 기존 바이트 보존을 지키기 위해서다.

**50개 표본.** seed **20261027**, 단위별 target_id·label 정렬 후 독립 고정 난수 추출. 대상은 **1차 실패·2차 통과**이며 필수 템플릿은 제외했다. 모집단 54/55개에서 각각 50개를 골랐다([selection.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/compile-check/selection.json), SHA `a21617b74f006795a11fd20edf5e022de4cd858846e351428f5815ba712c723b`).

| 단위 | 표본 성공 / 실패 | 성공률 | 필수 성공 / 전체 | 전체 성공 / 전체 |
|---|---:|---:|---:|---:|
| aq-024 | 31 / 19 | 62% | 2/6 | 33/56 |
| aq-017 | 31 / 19 | 62% | 2/8 | 33/58 |

전체 **66/114 성공, 48 실패, 미실행 0**. 표본의 38개 실패는 모두 T2051이다. 필수 10개 실패까지 합하면 T2051 46개, TAC01 2개다. 실패를 개선 성공으로 계산하지 않았다. Circom SHA `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227`와 원래 준비의 R1CS·bn128·library 인자를 고정했다([compile 코드:161](/Users/miiz/Desktop/kwzzzz_zkfr/scripts/s_inspection_round2_compile_20261027.py:161)). 검사 적격인 선택 대상 108개는 재렌더링·기존·컴파일 입력 wrapper SHA가 모두 같았고, 검사 실패 6개는 기록된 wrapper 자체를 컴파일했다([바이트 대조](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/compile-wrapper-binding.json)). 새 산출물의 R1CS 헤더·SHA만 기록한 후 해당 새 R1CS/sym만 정리하고 로그는 보존했다.

**보존·검증.** [preservation-union.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/preservation-union.json): 원본 prepared 적격 1,270개/16개 단위와 1차 검사 적격 1,824개/두 단위의 합집합 **2,732개**, 적격성·definition·inspection·target_id·fragment spec·기존/재생성 wrapper SHA 차이 **0**. 원본 두 단위 검사 적격 378개도 [별도 비교](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/preservation-original-inspection.json)에서 차이 0이다. 다른 14개 단위의 과거 부적격 대상을 1차에 전수 검사한 기록은 없으므로 그 집합까지 보존됐다고 주장하지 않는다. 하나라도 차이가 나면 실패 종료하는 비교를 사용했다.

최종 fmt, clippy(`--all-targets --all-features -- -D warnings`), cargo test 통과: **411 passed, 0 failed, 24 ignored, 24 filtered**. filtered 24개는 [1차와 동일한 J 호출 제외 목록](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/cargo-command-reference.json)이다. example 테스트 4개, 컴파일 도구 합성 테스트 25개도 통과했다. 단계 집중 검사는 나눗셈 18개→targets 52개→블록 예산 회귀 18개→삼항식 포함 64개 순서로 통과했다. 각 로그는 [timings.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/timings.json)의 명령 기록이 가리킨다.

모든 cargo·컴파일·측정은 nice 19, cargo -j 1/단일 테스트 스레드, Circom 한 개씩 실행했다. fmt는 -j 옵션이 없어 CARGO_BUILD_JOBS=1을 적용했다. **아래는 2026-10-26 UTC(한국 10월 27일 새벽), 모두 CPU contention**이다. 10개 cargo, 2개 probe, 18개 단위 검사, 114개 Circom의 개별 시작/끝을 timings.json에 기록했다.

| 실행 | 시작 UTC | 종료 UTC |
|---|---|---|
| 단계별 cargo·probe | 15:42:29 | 16:04:34 |
| 최종 fmt | 16:06:02 | 16:06:04 |
| 최종 clippy | 16:06:05 | 16:06:17 |
| 최종 cargo test | 16:06:17 | 16:08:47 |
| example test / 최종 build | 16:08:47 / 16:08:49 | 16:08:49 / 16:08:51 |
| aq-024 / aq-017 검사 | 16:09:43 / 16:15:24 | 16:15:23 / 16:21:05 |
| 16개 단위 기존 적격 보존 검사 | 16:23:14 | 16:23:27 |
| 114개 래퍼 컴파일 | 16:24:25.144839 | 16:24:50.397463 |

래퍼 컴파일 wall time 25.252초, 개별 시간 합 24.874초다. 디스크 시작 23.71 GiB, 중간 관측 최저 약 17.44 GiB, 검증 종료 확인 약 26.5 GiB. 실행 도구는 15 GiB 미만에서 중단하도록 감시했다.

**바이너리·명령.** 새 `target/debug/zkfDO` SHA-256 **`df37f457800f9339db50aa285680052cee92fc093c039298590657cc82c42ec3`**, audit example **`d9b443948b9149b7d62a6292f860f219da94b8908c6f998aa9006b7d0e9b7a0a`**([binary-hashes.json](/Users/miiz/Desktop/kwzzzz_zkfr/runs/s-inspection-improve-2026-10-27/binary-hashes.json)). 빌드는 target/에만 두며 **검사/준비 전용, 판정 사용 금지**다. 동결 v2.2 SHA `c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835`는 유지됐다. J·zkFuzz는 실행하지 않았다.

저장소 루트에서 실행한 주요 명령이다. 체크 label과 측정 output은 이미 존재하므로 재측정 때 새 이름을 써야 한다. select도 새 출력 전용이며, 현재 선택 파일에 대한 run은 완료 결과를 재사용한다. 정확한 24개 skip을 포함한 실제 argv는 command.json에 있다.

```sh
nice -n 19 python3 -B scripts/s_inspection_round2_run_20261027.py --label final-fmt -- cargo fmt
nice -n 19 python3 -B scripts/s_inspection_round2_run_20261027.py --label final-clippy -- cargo clippy -j 1 --all-targets --all-features -- -D warnings
nice -n 19 python3 -B scripts/s_inspection_round2_run_20261027.py --label final-cargo-test -- cargo test -j 1
nice -n 19 python3 -B scripts/s_inspection_round2_run_20261027.py --label final-example-test -- cargo test -j 1 --example s_inspection_audit
nice -n 19 python3 -B scripts/s_inspection_round2_run_20261027.py --label final-build -- cargo build -j 1 --bins --example s_inspection_audit
nice -n 19 python3 -B scripts/s_inspection_measure_20261026.py measure --binary target/debug/examples/s_inspection_audit --output runs/s-inspection-improve-2026-10-27/after
nice -n 19 python3 -B scripts/s_inspection_measure_20261026.py preserve-all --binary target/debug/examples/s_inspection_audit --output runs/s-inspection-improve-2026-10-27/preserve-after
nice -n 19 python3 -B scripts/s_inspection_round2_compile_20261027.py self-test
nice -n 19 python3 -B scripts/s_inspection_round2_compile_20261027.py select --before runs/s-inspection-improve-2026-10-26/baseline/measurement.json --round1 runs/s-inspection-improve-2026-10-26/after/measurement.json --after runs/s-inspection-improve-2026-10-27/after/measurement.json
nice -n 19 python3 -B scripts/s_inspection_round2_compile_20261027.py run --max-runtime-seconds 3600
```

**확인한 것**

- 두 단위 검사 증가, 기록된 기존 적격 2,732개의 바이트 보존, 필수 Rust 검사 및 114개 래퍼의 실제 컴파일 성공·실패를 확인했다.
- 활성 aq 폴더·외장 캐시·실행 중 판정 프로세스는 접근/변경하지 않았다. 테스트 제외 목록은 1차 사본을 사용했다. 동결 엔진·규칙·기록 수정, git 쓰기, 설치, runs 재귀 목록 조회는 하지 않았다.

**추정한 것**

- 표본 62%를 전체 신규 대상의 성공률로 확정하지 않는다. 나머지 래퍼, 전체 준비 파이프라인, 다른 단위의 증가량, S 후보·J 결과 변화는 미측정이다.
- signal alias 의존 분석과 누락 의존·태그 wrapper 처리는 후속 후보이며 이번 정확성·보존 검증 범위 밖이다. 시간 차이는 활성 판정과의 CPU 경합 영향을 포함한다.

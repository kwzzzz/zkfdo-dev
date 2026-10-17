# N6-J4b 엔진 v2 구현과 A 회귀 실행 준비

작성일: 2026-10-17 KST. 구현·검사 결과와 미주 터미널 실행 명령을 기록한다. A 765요청 회귀는 수행하지 않았으며, B 판정 허가나 N5 개정을 뜻하지 않는다. 이전 `n6_j4b_implementation_report_2026-10-17.md`는 집계 규칙 보완 전의 착수 대조 이력이다. 현재 기준은 이 보고서와 구현 전 고정 목록이다.

## 1. 승인·시작·목록

지시 SHA-256 `9ca648d966392ca7e353f2d0eacaa1f834f3f7294fa9d62a6b19d1ef46798b14` 일치. 시작 조건은 지정된 `runs/n6-b3-2026-10-12.noindex/mem20-retry.noindex/state.json` 하나를 직접 읽어 `completed`, SHA-256 `70043643377bc489760b092bf96881747fc5bf5a318648ee69c236fd25a9a16a` 일치를 확인했다. runs 재귀 탐색 명령은 사용하지 않았다.

처음 확인한 38건은 술어 배제 부분집합이었다. 사용자의 후속 집계 규칙(완료, l1=false, self_verdicts 비어 있지 않음, self/effective 모두 unknown 없음)에 따라 구현 전에 50건을 확정하고 해시를 대화에 보고했다. 전부 S이며 aq-035 12 + zkemail 두 버전 18 + inference 20이다. inference-original의 자기 배제만 12건은 각 행에 표시해 별도 보고 대상으로 두었다. 나머지 38건은 자기+술어 배제다.

| 목록 | SHA-256 |
|---|---|
| [MD](n6_j4b_regression_lists_2026-10-16.md) | `80f286b970aeb74d09e58c355ed26ba88131c73b52875503d21599c19bcf35d3` |
| [JSON](n6_j4b_regression_lists_2026-10-16.json) | `dd54296714dd1f7114770ad59314d6b7aceef2b091a5c6a71767e71f9ccc4290` |

JSON에는 완료 765요청·v1 L1 650요청·전체 수정판·부분 수정/LOO 목록과 요청·결과 해시·클래스가 있다. 전체 수정판은 zkemail-fixed 9, aq-035 12, inference-all-fixed 0요청이다. all-fixed의 후보 0을 회귀 통과로 세지 않는다. Banyan-fixed·A-Q 수정판 준비 실패는 명시적으로 제외했다. A 후보 값 열람 목록은 `[]`다. B 후보 값·판정 결과도 열지 않았다.

## 2. 변경 파일과 동작

- `src/candidate_review/lifting/synth.rs`: joint cone이 크기 제한을 넘을 때 구조 순서의 작은 branch 모델을 제안한다. 기존 후보 공유 sweep 20초에서 차감한다. 후보로 결정된 값만 고정한 닫힌 cone의 UNSAT만 배제 증명으로 사용하며, 지역 SAT는 재현 제안이다.
- `src/candidate_review/lifting/mod.rs`: 작은 제안도 기존 전체 재현·원본 R1CS 두 검사기·후보 주입·공개 입력·최상위 출력 조건을 거친다. 모델 비교 witness 부재를 별도로 기록하고 빈 외부 override에서 기존 abort 진단으로 연결한다. 제약형 deviated abort를 남은 class repair 슬롯으로 연결한다. 외부 수리 generator가 이미 있으면 이를 버리고 빈 상태에서 다시 수리하지 않는다. sweep 종료는 시간 소진/전체 branch 완료/증명 발견/도구 오류로 기록한다.
- `src/candidate_review/lifting/repair.rs`: 초기 상태를 cycle 집합에 포함하고 실패 제약을 후속 검색에 보존한다. 제어 가능한 기존 제안을 search-only blocking으로 반복하지 않도록 한다. `sat_no_effect`는 기존 with-paths 대안으로 넘어가며 실제 입력/hint 변화 없이 도달로 취급하지 않는다. 오류 종류를 기록한다. class 내 시작점들은 총 6회 iteration 슬롯을 공유하고 독립 술어 작업은 기존 별도 6회다. O0 SYM 대응 검사도 유지한다. 수리 UNSAT·cycle·no_progress·한도·도구 오류는 배제가 아니다.
- `src/candidate_review/lifting/predicate.rs`: 기존 표적 생성 범위와 후보 자체 witness 검사를 유지한다. 후보와 독립적인 base/빈 hint 술어 검색은 별도 attempt 키로 중복을 줄이고 cached unknown은 unknown으로 남긴다. proof v2와 attempt 파일을 분리한다. 증명 키는 O1/O0 R1CS·두 SYM·base input·도구·엔진 실행파일/소스·인스턴스·술어에 결합한다. 저장 schema, 허용 verdict, checker flags, 증거 파일 해시와 저장 record 해시를 검사한다. 기준 입력이 다르면 reach 입력 분류를 공유하지 않는다. 공유 출처와 검증 시각을 보존한다.
- `src/candidate_review/lifting/solver.rs` (신규): 모든 z3 호출의 query 경로·실측 초·명목 timeout·응답·reason-unknown을 `result.json.costs.solver_calls`에 기록한다. solver incomplete와 내부/외부 timeout, 도구 오류를 구분한다. 기존 cost 단계와 중복 합산하지 않는 별도 관측이다.
- `tests/lifting_engine_regression_test.rs`, repair/synth/solver 단위 테스트: 기존 건전성 회귀에 지역 SAT의 전체 witness 실패, search-only UNSAT 비승격, 손상 proof 차단, base 입력 분리, solver unknown/오류 보존 등을 추가했다. 기존 SYM 차단·hint/abort 재현·두 checker 회귀를 유지한다.
- `scripts/n6_j4b_regression.py`, `tests/n6_j4b_regression_test.py` (신규): 기존 J 실행기를 가져와 v2 바이너리/index를 별도로 고정한다. 기존 이어 하기·40 GiB 디스크 가드·리비전별 캐시 정리를 재사용한다. 전체 수정판 또는 배제 50건에서 L1이면 `REGRESSION_STOP.json`을 쓰고 종료 4로 중단하며, marker가 있으면 재개를 거부한다. 개별 결과와 인스턴스 조인 후 실효 도달을 모두 검사한다.
- [설정](n6_j4b_engine_v2_settings_2026-10-17.json), 고정 목록, 이 보고서와 계획 표를 추가/갱신했다. 기존 J 실행기·v1 산출물·프로토콜·설계 원본은 보존했다. 기존 사용자 변경도 보존했다.

프로젝트·템플릿·후보 SHA·W/S를 판정 탐색의 분기 조건으로 쓰지 않는다. 회귀 gate의 요청 목록 식별은 판정 엔진 밖의 검사다. `LessThan` 식별은 기존 오라클 정의만 유지한다. DistanceFromScore 전용 규칙은 없다. 숫자 예산 증액과 요청당 추가 allowance는 없다. 동일 상한에서도 경로·재현·cache 비용은 달라질 수 있으며 실제 A 비용은 미측정이다.

## 3. 검증

검증 결과는 아래 완료 표와 ignored 로그 해시에 기록한다. A 실제 자료 재판정과 fixture 검사는 구분한다. A의 L1 보존·배제 50건 유지·unknown 감소·비용 개선은 아직 결과가 없다. 최초 전체 검사 중 기존 `ordered_scheduler_test::nonzero_exit_does_not_become_success_from_summary_text`가 2초 제한에서 Timeout으로 실패해, 설정·코드를 바꾸지 않고 최종 검사에서 재확인했다.

| 검사 | 결과 |
|---|---|
| `cargo fmt` 및 최종 fmt check | 통과 |
| `cargo clippy --all-targets --all-features -- -D warnings` | 통과 |
| 최종 `cargo test` | 364 통과·0 실패·24 ignored |
| `cargo test --test lifting_engine_regression_test` (search-only UNSAT 추가 후) | 17 통과·0 실패 |
| `python3 -m unittest discover -s tests -p 'n6_j*_test.py'` | 56 통과·0 실패 |
| `cargo build --release --offline` | 통과·의존성 설치 없음 |
| `git diff --check` | 통과 |

최종 전체 검사에는 엔진 회귀 16건이 포함됐으며, 뒤에 추가한 search-only UNSAT 1건은 엔진 회귀 17건 전체를 다시 실행해 확인했다. 최초 스케줄러 timeout은 최종 전체 검사에서 통과했다. 기존 ignored 검사는 실행하지 않았다. cycle의 초기 상태 포함과 탐색 실패가 None/unknown으로 반환되는 경로, 반복 상한은 소스 및 기존 단위 검사로 확인했으며 A에서의 회복 효과는 주장하지 않는다.

| ignored 검증 로그 | SHA-256 |
|---|---|
| `runs/n6-j4b-validation-2026-10-17.noindex/cargo-test.log` | `cb880cb29b969fcf6b978fe7770903f65263ead7de470034efa193e3bf835dab` |
| `runs/n6-j4b-validation-2026-10-17.noindex/clippy.log` | `8d841b8874fe7c505bf056d9c4779ba854287b97768ef7642be2f54d07e4dc83` |
| `runs/n6-j4b-validation-2026-10-17.noindex/engine-regression.log` | `78bdc01d8340fe58962115f6f73d4d55859b42f97addbd168c400bf7dc689f12` |
| `runs/n6-j4b-validation-2026-10-17.noindex/python-tests.log` | `2e665cbcf60bb4d67bb107b4cefe93a185a98182a30813e10e450abe7decfea3` |
| `runs/n6-j4b-validation-2026-10-17.noindex/release-build.log` | `91d1b483c034b304683423ef46ba45050168c5b470e77fb34723ca0a804f3ef5` |
| `runs/n6-j4b-validation-2026-10-17.noindex/initial-timeout.log` | `861a7d0e93b8d4e886d44a0cf58c6a4bde2778eac7a66180f9a12953440574d7` |


## 4. A 회귀 실행 명령 — 미주 터미널에서만

새 index/cache/lock 준비만 수행했다(`prepared_not_executed`). v1 index의 요청 순서·2,926 행을 유지하므로 준비 실패 2,161건은 그대로 건너뛰고 판정 가능 765건만 엔진을 호출한다. 새 cache는 빈 상태로 만들었고, 실행 결과/store는 아직 없다. 준비 단계를 다시 실행하면 기존 경로를 덮어쓰지 않고 거부한다.

저장소 루트에서 다음 명령을 실행한다. 중단 없는 완료 전에는 B 판정에 사용하지 않는다.

```sh
caffeinate -dimsu python3 scripts/n6_j4b_regression.py \
  --engine /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j4b-tools-2026-10-17.noindex/zkfDO \
  --engine-sha256 b12187ce8a3088aaa93d6fe202ec103beea0e786fad500ad6c1bacbf6489574d \
  --action execute
```

디스크 가드 등 일반 중단 후에는 같은 명령으로 이어 한다. 회귀 gate의 `REGRESSION_STOP.json`이 생기면 marker를 지우거나 재실행하지 않고 리드에게 보고한다. 전체 수정판/배제 50건의 L1은 요청·클래스·인스턴스·reach 분류와 원본 결과 경로를 함께 보고한다. 특히 inference-original 자기 배제만 12건을 따로 묶는다. 부분 수정/LOO의 새 L1은 gate 실패로 합치지 않고 남은 결함인지 리드가 검토하도록 별도 목록을 만든다.

완료 후 값 없는 집계 명령:

```sh
python3 scripts/n6_j1_summarize.py --require-complete \
  --index runs/n6-j4-2026-10-15.noindex/request-index-v2.json \
  --run-output runs/n6-j4-2026-10-15.noindex/j-execute.noindex \
  --preparation-units runs/n6-a1-2026-10-07/preparation-units.json \
  --targets docs/n6_targets_a_2026-10-07.json \
  --main-queue runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json \
  --mem20-queue runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json \
  --rq-c-map runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json \
  --output runs/n6-j4-2026-10-15.noindex/j-summary-v2.json
```

그 후 650 L1 요청의 누락을 하나씩 원인과 대조하고, partial/LOO 새 L1, unknown의 상위 원인·내부 종료·클래스/요청/인스턴스 분모, wall 합·최대 요청·단계별 비용·cache hit를 보고한다. 새 solver_calls와 repair error/종료 및 sweep_end를 사용해 시간 소진과 탐색 완료/도구 한계를 구분한다. 상위·하위 종료를 서로 다른 사건으로 더하지 않는다. 자체 발견과 공유 실효 판정, 최초 검증 시각과 후보 시각도 분리한다.

## 5. 고정 값

| 항목 | SHA-256 / 상태 |
|---|---|
| v2 바이너리 `runs/n6-j4b-tools-2026-10-17.noindex/zkfDO` | `b12187ce8a3088aaa93d6fe202ec103beea0e786fad500ad6c1bacbf6489574d` |
| v2 index `runs/n6-j4-2026-10-15.noindex/request-index-v2.json` | `446c064e10a7241c2127339a9acf62816a6d865e16b1e7113b848b1fbb47f513` |
| v2 실행 wrapper | `cabf0d00bdc50251125c4fcb0be66ceb9c1f6463d3bef25a7ca94146abba7972` |
| 설정 JSON | `cc28bf302b993852c1bbf5199c80fa132f646f1e9521c3ae53be7dd67244b3fe` |
| 목록 MD / JSON | §1의 두 SHA-256 |
| v2 커밋 SHA | 미주 커밋 후 기록 대기; 이 작업에서는 커밋하지 않음 |

실행 준비 lock은 바이너리·index·목록·기존 실행기·새 wrapper SHA를 묶는다. 바이너리와 준비 산출물은 ignored runs에 있다. 커밋·push·PR·의존성 설치·B J 실행·B 후보 값/판정 열람은 하지 않았다. v2의 A 회귀 통과와 B 사용 고정은 아직 아니다.

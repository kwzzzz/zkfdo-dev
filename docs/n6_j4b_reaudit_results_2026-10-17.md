# N6-J4b 재검증·보완판 v2.1 결과

작성일: 2026-10-17 KST. 사용자의 재검증 요청에 따라 이전 완료 판단을 다시 대조했다. **이전 v2의 구현·검증에 공백이 있었고, 이를 수정했다. 이전 보고서의 실행 명령 대신 이 문서의 v2.1 명령을 사용한다.** A 실제 회귀는 여전히 미실행이며, 650 L1 보존·배제 50건 유지·unknown 감소·B 사용 가능 여부는 아직 확인하지 않았다.

## 1. 재검증에서 찾은 문제와 수정

| 문제 | 재현/확인 | 보완 |
|---|---|---|
| solver 비정상 종료를 verdict 텍스트만으로 채택 | `unsat` 출력 후 exit 7인 도구를 기존 v2가 받아들여 새 단위 테스트가 실패했다. | 종료 상태와 예상하지 않은 solver 오류를 검사한다. 비정상 종료는 `tool_error`. z3가 unsat/unknown 뒤 요청된 get-value에만 내는 `model is not available`와 exit 1은 정확히 구분해 정상 UNSAT를 보존한다. 실제 z3 반대 대조도 통과했다. |
| 불완전한 SAT 모델 수용 | 요청 wire 집합 일부만 반환한 모델을 기존 v2가 받아들여 새 테스트가 실패했다. | repair와 closed-cone 모두 모델 wire 집합이 요청 집합과 정확히 같아야 한다. |
| 고정 입력·보호 site를 적용 단계에서 재확인하지 않음 | 수리 모델 적용 테스트에서 pinned `x=1`이 `x=9`로 바뀌었다. 실제 A 결과에서 이 현상을 관측했다는 뜻은 아니다. | query 구성뿐 아니라 구체 모델 적용에서도 pinned 입력·보호 site·hub 입력을 차단한다. 보호된 변경만 있는 SAT는 실제 변화 없음으로 돌아가 기존 대안 경로를 사용한다. |
| 회귀 중단 조건의 재개 경로 누락 | 이전 wrapper는 새 run_lift와 새 join만 감쌌다. 기존 결과를 채택하거나 이미 존재하는 join을 읽는 경로가 검사를 우회할 수 있었다. 이전 Python 검사는 순수 gate 두 건뿐이었다. | 새 wrapper는 신규·재개 결과, 기존 join, 새 join, state 저장 직전의 공유 승격을 모두 검사한다. 실제 J 실행기를 모의 엔진과 연결해 재개 L1이면 다음 요청을 실행하지 않는지 확인했다. ID 불일치·빈 클래스 결과도 음성으로 받지 않는다. |
| 실패 attempt의 시간 의존성과 generator 구분 부족 | no_progress로 끝났어도 내부 solve가 timeout/unknown일 수 있었다. 같은 R1CS/SYM 아래 hint generator가 달라도 기존 attempt 키는 같을 수 있었다. | timeout/unknown/tool error가 든 attempt는 memoize하지 않는다. 실제 honest O0 WASM SHA를 job ID와 별도 파일 경로에 결합한다. 전체 값 없는 RepairRecord·원래 요청·record hash를 보존한다. cached unknown은 unknown이고 후보 자체 witness 검사는 계속 수행한다. |

수정은 프로젝트·템플릿·후보 SHA·W/S별 특수 규칙을 추가하지 않았다. 숫자 상한도 증액하지 않았다. class 내 repair 6회 공유와 독립 술어의 기존 6회, 후보 공유 sweep 20초, 모든 기존 크기·solver·도구 상한을 유지한다. L1의 두 검사기·원본 R1CS/SYM 대응·후보 주입·공개 입력·최상위 출력 조건은 유지/강화했으며 완화하지 않았다.

## 2. 검증 범위와 결과

| 검사 | 결과 |
|---|---|
| `cargo fmt`, 최종 `cargo fmt --check` | 통과 |
| `cargo clippy --all-targets --all-features -- -D warnings` | 통과 |
| `cargo test` | **374 통과·0 실패·24 ignored** |
| 전체 검사에 포함된 `lifting_engine_regression_test` | **19 통과** |
| `python3 -m unittest discover -s tests -p 'n6_j*_test.py'` | **62 통과** |
| `cargo build --release --offline` | 통과·설치 없음 |
| 문서/소스 diff 공백 검사 | 통과 |

검사기 불일치에서는 Rust가 0 unsatisfied이고 snarkjs가 not_correct인 경우 실제 CLI가 unknown을 반환했다. R1CS와 SYM 변조 검사는 실제 수리 compile 산출물을 각각 바꾸어 unknown/evidence_invariant로 차단되는지 확인했다. search-only UNSAT 비승격, 작은 SAT의 전체 witness 실패, 구체 sat_no_effect, 초기 상태 cycle·6회 한도, 손상 proof 거부, base 입력 및 generator별 키 분리도 검사했다. cycle/한도는 실제 Search가 사용하는 상태 제어기 단위 검사이고, A 자료의 회복률 검증은 아니다.

새 Python 검사에는 실제 기존 J 실행기와 모의 엔진을 연결한 신규 중단·재개 중단 검사가 포함된다. 중단 marker가 있으면 재개를 거부하며 기존 결과·join 재검사도 적용한다. 도구/실행기/관련 helper 소스 해시도 새 lock에 포함했다.

## 3. 목록·보존·노출 확인

지시 SHA-256 `9ca648d966392ca7e353f2d0eacaa1f834f3f7294fa9d62a6b19d1ef46798b14`와 승인 설계 SHA-256 `3b8c56d211ed5aa63ab10c0ea13b89549167f778b50bf0d7053a7576ae803a3a`를 다시 확인했다. 시작 조건의 completed 및 지정 상태 SHA는 기존 착수 대조를 유지한다. mem20 상태 이외의 B 자료는 읽지 않았다.

고정 요약(915b15c2…)과 사용자 보완 규칙으로 50건을 다시 검산했다. inference-original 자기 배제만 12 + 자기/술어 배제 38이다. 완료 요청 메타데이터 765개를 직접 참조해 각 요청 파일 SHA와 ID도 확인했으며 불일치 0이다. 후보 값이나 기존 개별 result 파일을 열어 디버깅하지 않았다. A 후보 값 열람 목록 `[]`, B 후보 값·판정 열람 0이다. runs 재귀 탐색 명령도 사용하지 않았다.

| 구현 전 고정 목록 | SHA-256 |
|---|---|
| [MD](n6_j4b_regression_lists_2026-10-16.md) | `80f286b970aeb74d09e58c355ed26ba88131c73b52875503d21599c19bcf35d3` |
| [JSON](n6_j4b_regression_lists_2026-10-16.json) | `dd54296714dd1f7114770ad59314d6b7aceef2b091a5c6a71767e71f9ccc4290` |

고정 목록·기존 v1 산출물·프로토콜·설계·이전 보고서/바이너리/준비 lock은 보존했다. 보완 준비는 지정된 회귀 root 아래 새 `reaudit-v2.noindex/`로 구분했다. 기존 사용자 변경은 건드리지 않았다.

## 4. 변경 파일

- `src/candidate_review/lifting/solver.rs`: 종료 상태 검사·허용 protocol 오류 구분·exit_code 계측과 실패 재현/반대 대조 검사.
- `src/candidate_review/lifting/repair.rs`: 정확한 모델 집합 검사, 구체 적용 보호, 실제 Search에서 쓰는 cycle/iteration 제어기와 안전성 검사, attempt 진단 직렬화.
- `src/candidate_review/lifting/synth.rs`: 정확한 closed-cone 모델 집합 검사.
- `src/candidate_review/lifting/predicate.rs`: generator/시작 상태에 결합한 attempt v2.1과 보수적 memoization, 전체 진단·원 요청·해시 유지.
- `src/candidate_review/lifting/mod.rs`: attempt 진단에 필요한 RewriteRecord 역직렬화 지원. 이전 승인 구현은 유지.
- `tests/lifting_engine_regression_test.rs`: 실제 checker 불일치·수리 R1CS/SYM 변경 차단 추가.
- `scripts/n6_j4b_regression_v2.py`, `tests/n6_j4b_reaudit_test.py` (신규): 신규/재개/공유 결과 gate, 요청 결합·출력 범위 검사, helper·runtime 도구 lock.
- [설정 v2](n6_j4b_engine_v2_settings_v2_2026-10-17.json), 이 보고서와 계획 진행 표.

## 5. 미주 터미널 A 실행 명령

준비만 수행했다(`prepared_not_executed`). 새 cache는 비어 있고 결과/store는 아직 생성되지 않았다. 기존 J 실행기의 이어 하기·디스크 가드·리비전별 캐시 정리를 재사용한다. 요청 순서와 2,926 행을 유지하고 준비 실패 2,161건을 건너뛰므로 실제 판정 대상은 765요청이다.

**이전 보고서의 v2 명령 대신 다음 v2.1 명령을 사용한다.**

```sh
caffeinate -dimsu python3 scripts/n6_j4b_regression_v2.py \
  --engine /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j4b-tools-2026-10-17.noindex/zkfDO-v2.1 \
  --engine-sha256 f9a6ba687707aa0b3bb4dafd04d9232c7e0bd4c12802a086f86fd1c5db54296e \
  --action execute
```

일반 중단이면 같은 명령으로 이어 한다. `REGRESSION_STOP.json`이 생기면 marker를 지우거나 재개하지 않고 리드에게 보고한다. 전체 수정판/배제 50건 L1은 즉시 중단하며, inference-original 자기 배제만 12건을 따로 묶어 보고한다. 부분 수정/LOO의 새 L1은 요청·클래스·인스턴스·reach 분류로 따로 검토한다.

완료 후 요약 명령:

```sh
python3 scripts/n6_j1_summarize.py --require-complete \
  --index runs/n6-j4-2026-10-15.noindex/reaudit-v2.noindex/request-index-v2.json \
  --run-output runs/n6-j4-2026-10-15.noindex/reaudit-v2.noindex/j-execute.noindex \
  --preparation-units runs/n6-a1-2026-10-07/preparation-units.json \
  --targets docs/n6_targets_a_2026-10-07.json \
  --main-queue runs/n6-a2b-2026-10-08.noindex/queue-a-v4.json \
  --mem20-queue runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json \
  --rq-c-map runs/n6-j1-2026-10-09.noindex/rq-c-instance-map.json \
  --output runs/n6-j4-2026-10-15.noindex/reaudit-v2.noindex/j-summary-v2.1.json
```

그 뒤 650 L1의 요청별 누락 원인, 부분 수정/LOO 새 L1, unknown 상위·내부 종료와 클래스/요청/인스턴스 분모, wall·최대 요청·단계별 비용·cache hit를 보고해야 한다. 공유 판정과 자체 발견, 원인 상/하위 분류의 중복, 최초 검증과 후보 시간도 구분한다. 아직 이 결과를 얻었다고 주장하지 않는다.

## 6. 해시와 고정 상태

| 항목 | SHA-256 / 상태 |
|---|---|
| v2.1 바이너리 `runs/n6-j4b-tools-2026-10-17.noindex/zkfDO-v2.1` | `f9a6ba687707aa0b3bb4dafd04d9232c7e0bd4c12802a086f86fd1c5db54296e` |
| 새 index | `7e6f0b33cb14cf59809c2b5f5ec69fc2231231a4b374f4cde023ea6567852798` |
| 새 wrapper | `9a738fee71b6a8e873bcccef811e201dfeedc14950c679a8649f070b78370dd0` |
| 새 설정 JSON | `a4867e018a54df656dc1bdd079d7bb4fb6862a984b6e88784e5b30176e5da001` |
| 목록 두 파일 | §3의 고정 SHA 유지 |
| 커밋 SHA | 미주 커밋 후 기록 대기; 커밋하지 않음 |

커밋·push·PR·의존성 설치·A 실제 회귀·B 판정은 하지 않았다. 구현과 명시한 검사 범위는 통과했지만, A 회귀 관문과 B 사용 고정은 남아 있다.

| 보존한 검증 로그 | SHA-256 |
|---|---|
| `runs/n6-j4b-reaudit-validation-2026-10-17.noindex/cargo-test.log` | `ea4c2d6f6e78e864bb6b8ea55730c3a4cc3cb847ffc22d12b342f2da09e06924` |
| `runs/n6-j4b-reaudit-validation-2026-10-17.noindex/clippy.log` | `aaa63828ea5e03a48a01a1263f78177038409fc7c04fd8d835a9fb5b65296064` |
| `runs/n6-j4b-reaudit-validation-2026-10-17.noindex/python-tests.log` | `d6d18c9308c29ec4ba796dffc3d22fcfce4082ea2de186707e2ffeab2bd97b81` |
| `runs/n6-j4b-reaudit-validation-2026-10-17.noindex/engine-regression.log` | `55de08af632d0da5c36bc60b92a9621a22e89a442ca68794a87a090fae16aa81` |
| `runs/n6-j4b-reaudit-validation-2026-10-17.noindex/release-build.log` | `b34daee0383d1308a01201de323873c74ccc9d420409a2f871ef99b2e568cf2f` |
| `runs/n6-j4b-reaudit-validation-2026-10-17.noindex/solver-exit-red.log` | `edfc629bec196cac2dc643acef3e450025ba5dfe1333cde8f58e085f56419507` |
| `runs/n6-j4b-reaudit-validation-2026-10-17.noindex/incomplete-model-red.log` | `3ccae391f511fe5732e2f702b308f3c8a92cddb055ebff1020e187c0a42fde54` |
| `runs/n6-j4b-reaudit-validation-2026-10-17.noindex/protected-controls-red.log` | `09beedf40af4acb196d1d44067e4f6cdbf2d1f602c947c14cd36a2521c5ff2e2` |

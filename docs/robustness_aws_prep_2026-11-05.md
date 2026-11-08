# 실행 안정성·AWS 이식 준비 (2026-11-05)

개발용 실행기와 검증 결과다. 기존 N5 조건을 변경하거나 AWS 실행을 승인하는 문서가 아니다. J v2.4 속도 개선은 이전 작업이며 이번에는 판정 코드·동결 n7 실행기·과거 실행 기록을 바꾸지 않았다. 커밋·푸시·AWS 자원 생성·S3 업로드·held-out 실행은 하지 않는다.

## 변경 범위

| 단계 | 새 파일·주요 함수 | 동작과 확인 범위 |
|---|---|---|
| 1 종료 | `scripts/zkfdo_runtime_v1.py`: `run_command`, `atomic_json`; `scripts/run_policy_a_engine_v5.py`: `Campaign.command/run/checkpoint` | 작업 deadline과 별도 종료 유예를 구분한다. 새 session으로 실행하고 PID 시작 식별자·자손·그룹을 추적하여 TERM→KILL→직접 자식 wait4를 수행한다. 실행 전·중·후 ledger/receipt를 임시 파일→fsync→rename으로 저장한다. 저장 실패도 프로세스 회수를 건너뛰지 않는다. |
| 2 디스크 | runtime `DiskBudget`; `scripts/zkfdo_compile_gate_v1.py`: `create_gate/main`; v5 `Campaign.gate` | 작업 `--max-disk-bytes`, 요청 `--max-request-disk-bytes`, 최저 여유 공간을 검사한다. 복사·명령 시작·실행 중·후를 검사하고, 직접 Circom 및 J의 `--circom-bin` 호출도 별도 gate에서 컴파일 직전에 검사한다. 초과 결과는 보존하며 삭제하지 않는다. |
| 3 플랫폼 | `scripts/zkfdo_platform.py`: `process_snapshot`, `memory_snapshot`, `normalize_ru_maxrss`, `clock_snapshot/clock_delta`, `host_environment` | Linux `/proc`, macOS ps 관계+libproc 실사용/식별자·vm_stat·sysctl. 관측 실패를 0으로 바꾸지 않는다. Linux ru_maxrss KiB와 Darwin bytes를 구분한다. 연속 시계·monotonic·UTC 차이로 절전/시계 변경/모호한 관측을 구분하고 측정을 무효로 한다. |
| 4 도구 | `configs/tools.darwin.json`, `configs/tools.linux.json`; `scripts/zkfdo_tools_v1.py`: `load_manifest/verify_tool` | Mac 11개 도구의 실제 경로·SHA·버전과 확인 가능한 출처를 기록한다. 과거 빌드 명령·커밋을 확인하지 못한 항목은 null과 이유를 남긴다. Linux는 미작성 틀이므로 실행기가 거부한다. |
| 5 실제 설정 | `configs/zkfuzz_defaults_2.2.1_v1.json`; `scripts/zkfdo_zkfuzz_config_v1.py`: `materialize_settings/resolve_configuration/compare_w_s`; v5 설정 관문 | 소스 기본값과 seed를 합친 MutationConfig 29개를 실제 입력 JSON으로 명시하고 SHA·argv·기본 whitelist/정적 검사 설정을 기록한다. 값 자체는 바꾸지 않는다. 비용 비교 모드는 peer spec과 시작 seed/rule을 요구하고 pass별 W/S 선언 설정을 모두 비교한다. 불일치·설정 파악 실패 시 시작하지 않는다. |
| 6 경로 | `zkfdo_tools_v1.py`: `runs_root/output_path`; v5 CLI | `ZKFDO_RUNS`, `ZKFDO_TOOLS_MANIFEST` 및 명시 CLI 경로를 지원한다. 출력은 지정 runs 아래 새 작업 폴더로 제한한다. 도구 코드에 Mac 바이너리 경로나 SHA를 고정하지 않는다. |
| 7 환경 | [env/README.md](../env/README.md), [setup_ubuntu.sh](../env/setup_ubuntu.sh) | 현재 Mac의 측정값과 Ubuntu 설치 초안. 설치 초안은 실행하지 않는다. |
| 8 변경 목록 | [uncommitted_inventory_2026-11-05.md](uncommitted_inventory_2026-11-05.md) | 기존 미커밋 변경과 이번 파일을 구분한다. `.gitignore`의 기존 `__pycache__/` 규칙이 scripts에도 적용되므로 중복 추가하지 않는다. |
| 9 wrapper 옵션 | `scripts/prepare_targets_v2.py`: `classify_target/prepare_plan/analyze_cold`; v5 `validate_wrapper_filter/validate_filtered_configuration` | 기본 꺼짐. 주석·문자열을 구분한 전이 호출 분석과 실제 wrapper main·매개변수·소스 해시·설정 결속을 검사한다. 불확실한 소스는 유지한다. 필터 후 설정이 바뀌거나 비교할 설정 근거가 없으면 재준비를 요구한다. |
| 10 환경·격리 | 플랫폼 `prepare_isolation/scoped_supervisor_affinity`, v5 CLI | 호스트·vCPU·RAM·커널·디스크·선택 IMDS, 작업/요청 RSS 최고치를 기록한다. Linux CPU affinity는 복사·해시를 포함해 적용 후 복원한다. `memory.max`는 command 트리에 적용하고 supervisor는 밖에서 OOM 후 회수한다. 옵션 기본은 꺼짐이고 고정 10GiB 상한은 없다. |
| 11 플랫폼 개정 | [n5_amendment_platform_draft_2026-11-05.md](n5_amendment_platform_draft_2026-11-05.md) | 사람 검토 전 미채택 초안. 기존 프로토콜·개정 문서는 보존한다. |
| 12 AWS 설계 | [aws_execution_plan_2026-11-05.md](aws_execution_plan_2026-11-05.md) | 대량 탐색과 동일 비용 비교를 분리한 설계. 실행·자원 생성은 하지 않는다. |

## 종료·계측의 의미

W-long의 충돌 지점은 `n7_a_w_long_20261029.py:111–125`와 `n7_a_sj_cold_e2e_20261029.py:131–144`다. 내부 예산과 외부 timeout이 겹칠 때 외부 `subprocess.run`이 직접 자식만 종료하고, 별도 session의 zkFuzz 및 마지막 저장을 놓칠 수 있었다. 새 실행기는 작업 중단 후에도 종료 유예를 사용하며 그 시간·CPU를 별도로 기록한다. 따라서 유예를 비용에서 공짜로 제외하지 않는다. 기존 전체 비용 supervisor에도 자손 추적이 있었으므로 모든 구버전에 종료 기능이 없었다는 뜻은 아니다.

디스크 사용량은 해당 작업/요청 폴더만 대상으로 하는 **논리 파일 크기 표본 최고치**다. 하드링크는 한 번 세며 심볼릭 링크는 거부한다. 실행 중 한 번의 큰 쓰기가 표본 사이에서 상한을 넘을 수 있으므로 파일시스템 강제 quota나 정확한 최대 사용량은 아니다. 컴파일 gate는 다음 외부 컴파일 시작을 차단하며, 이미 진행 중인 컴파일은 supervisor가 회수한다. 여유 공간 부족 시 마지막 저장 자체가 실패할 수 있어 실패를 명시한다.

프로세스 RSS는 관측한 command 자손의 합이며 supervisor 자체는 제외한다. wait4 CPU는 직접 자식과 그 자식이 회수한 자손의 범위다. 관측 전에 분리되어 고아가 된 프로세스까지 표본 방식으로 완전히 증명할 수는 없다. Linux cgroup의 별도 누적 사용량은 이 범위를 보완하지만 RSS와 같지 않다. cgroup CPU는 attach 이후 범위이며 그 전 shim CPU는 제외되고 wait4 값은 별도 남긴다. `cpu_seconds_known_sum`은 기록된 범위의 합이며 모든 관측 helper·관측 전 고아 CPU를 완전히 입증하는 총량이 아니다. SIGKILL·전원 상실 때는 최종 영수증 대신 마지막 원자적 checkpoint가 남는다. 일반 timeout/TERM/INT/HUP와 이 경우를 구분한다. 강제 종료된 도구 자체의 최종 J result가 없으면 없는 상태로 남기며 supervisor ledger를 J 판정으로 대체하지 않는다. 절전 관문은 1초 허용폭과 시계 채집 오차를 넘는 차이를 사용하므로 아주 짧은 절전의 부재를 증명하지는 않는다. 차이·허용폭은 영수증에 남긴다.

## zkFuzz 설정 검증

설치된 zkFuzz 2.2.1에는 전체 설정 출력 CLI가 없다. 소스에서 확인한 29개 기본값과 명령줄의 실제 설정을 기록하고, 값이 명시된 JSON을 엔진에 전달한다. 소스 SHA·바이너리 SHA·입력 JSON SHA를 함께 검증한다. 반례에 반환되는 `mutation_test_config`는 실행 도중 적응한 **실행 후 값**으로 별도 보관한다. 반례가 없으면 해당 관측은 unknown이며 초기 설정과 같다고 단정하지 않는다.

자체 합성 회로 하나에 seed 2026110501을 넣은 seed-only 입력과 explicit29 입력을 각각 1회 실행했다. 두 번 모두 정상 종료·자손 회수 완료였고, `5_flag`, `6_target_output`, `7_assignment`, 실행 후 29개 설정이 모두 같았다. 초기 범위·확률 두 값은 엔진이 실행 중 수정했으므로 반환 설정으로 constructor 기본값 전체를 입증했다는 주장은 하지 않는다. 이 검사는 개발용 입력 전달 확인이며 N5 판정 동치나 성능 결과가 아니다.

근거: `runs/robustness-aws-prep-2026-11-05/settings-paired-probe-v1.json` (SHA256 `66018601754e`로 시작; 전체 SHA는 defaults profile에 기록), `config-probe-v1/observation.json`, `config-probe-v2/observation.json`. raw candidate는 ignored runs에만 있다.

비용 비교의 peer 기록은 **해당 pass seed에서 상대 spec이 선언하는 설정**이다. 상대 실행이 그 pass에 실제 도달했다는 뜻이 아니다. discovery 모드는 peer가 필요 없으며 비용 비교 결과와 구분한다. unused-output 검사·LessThan 오라클·IsZero/Num2Bits whitelist 값은 그대로다.

## wrapper 제외와 기존 시간 계산

`--skip-unmutable-wrappers`는 기본 꺼짐이다. 이미 준비된 새 plan을 입력받아 `filtered-plan.json`, `filter-report.json`, 선택적으로 새 campaign spec을 만든다. source-only 검사이며 준비/컴파일/퍼징/J를 실행하지 않는다. 사용자 whitelist·mutator 종류는 실제 설정으로 확인한다. 잠재 hint가 하나 이상이고 전이 호출 안의 모든 hint가 whitelist template에 속할 때만 제외한다. 함수 RHS hint, 미해결 호출, 중복 정의, 불완전 inspection, wrapper main/매개변수·fingerprint 불일치는 유지한다.

세 seed의 준비된 22개 중 공통으로 다음 10개가 조건을 만족했다. 0은 해당 대상이 과거 실행에서 시도되지 않아 절약 가능 시간으로 계산할 관측값이 없다는 뜻이다.

| wrapper | 매개변수 | seed01 S wall(s) | seed02 S wall(s) | seed03 S wall(s) |
|---|---|---:|---:|---:|
| IsZero | 없음 | 0 | 4.100053 | 0 |
| Num2Bits | 41 | 0 | 30.023650 | 0 |
| LessThan | 40 | 0 | 30.023941 | 0 |
| DistanceFromScore | 40 | 0 | 0 | 0 |
| Num2Bits | 81 | 0 | 0 | 0 |
| LessThan | 80 | 0 | 0 | 0 |
| Clamp | 40 | 0 | 0 | 0 |
| CalculatedScoreFraction | 40 | 0 | 0 | 0 |
| Num2Bits | 121 | 0 | 0 | 0 |
| LessThan | 120 | 0 | 0 | 0 |
| **합계** | **seed별 10개 제외 → 12개 유지** | **0** | **64.147643** | **0** |

전체 seed는 2026100601/2026100602/2026100603이다. seed02 세 항목의 CPU는 각각 3.245772/29.949550/29.949011초, 합계 **63.144333초**다. IsZero는 no-candidate, 나머지 둘은 30초 timeout이었다. `actual_attempt_wall_seconds`에 섞인 inline J·정리 시간을 합치지 않고 `process_wall_seconds`와 `resource.cpu_seconds`만 사용했다.

이 값은 **새 규칙이 제외할 대상에 과거에 든 비용**이다. 옵션을 켠 새 실행의 실측 절약이나 동일 후보 보장이 아니다. LessThan 오라클·assert·입력 검사는 hint whitelist와 별개이므로 탐색 범위와 판정 분포가 바뀔 수 있다. 옵션 채택은 별도 실험 계획에서 결정한다. AssertBit 같은 hint가 없는 wrapper는 공집합 논리로 제외하지 않는다.

재현 근거는 `runs/robustness-aws-prep-2026-11-05/wrapper-skip-analysis-v1.json` (SHA256 `a64c5e9121f1bd4d3b9bcf3bec26e5cc07e1c4a918e3790b6aa80b3778dfe242`)이다. 각 target ID·경로·plan/ledger/source hash와 계산 내역이 있다. 강화한 필터로 결과가 같은 것을 재확인했다. `wrapper-filter-plans-v1/<seed>/`에 세 seed의 새 계획·제외 사유·실제 29필드 설정 영수증을 저장했다. 원래 cold spec의 `memory_cap_bytes`는 보존하므로 그대로 v5에서 실행하지 못한다. 물리 footprint 조건을 RSS 조건으로 자동 변경하지 않고 명시적인 새 spec 작성이 필요하다.

## 테스트

단계별 합성 검사를 먼저 수행하고 연결 후 통합 회귀를 수행했다. 실제 Linux cgroup/IMDS·AWS 도구 빌드는 Mac fixture 테스트와 구분한다. 로그는 `runs/robustness-aws-prep-2026-11-05/`에 보존했다.

| 검사 | 결과 |
|---|---|
| runtime timeout·신호·저장 실패·디스크·절전/관측 오류 | 14개 통과. detached 자손을 포함한 관측 대상 0개·최종 ledger/receipt 보존 확인. 동결 W-long 본 실험은 재실행하지 않음 |
| 플랫폼 | 39개 fixture 통과: `/proc`·Darwin 관측·시계·CPU mask 복원·cgroup·디스크 메타데이터. 실제 Linux 실행 아님 |
| 매니페스트·경로 | 6개 테스트 통과, Mac 실제 11개 도구 SHA 확인 |
| 설정 | 15개 parser 테스트 및 두 실제 소형 probe 통과 |
| 컴파일 gate | 2개 통과: 상한 넘은 두 번째 컴파일 차단·기존 출력 보존, deadline/바이너리 교체 거부 |
| v5 캠페인 | 28개 통과: timeout/신호 실기 2개, 설정/peer/필터 결속·부모 affinity 복원·최종 관측 실패 관문 등 |
| wrapper 준비 | 18개 통과: 기본 꺼짐, 불확실 시 유지, 실제 main/매개변수·소스 결속, 중복 ID 거부, manifest 경로 및 후속 plan 검사 |
| Ubuntu 설치 초안 | `bash -n` 및 내장 Python AST 문법 검사 통과. 설치·다운로드·빌드는 실행하지 않음 |
| `cargo fmt` | 통과 (사전 `--check`도 통과) |
| `cargo clippy --all-targets --all-features -- -D warnings` | 통과, 41.39초 |
| `cargo test` | 469 passed / 0 failed / 24 ignored, 208.11초. 기존 ignored 항목을 강제로 실행하지 않음 |

새 Python 테스트는 총 **122개 통과, 실패 0개**다. 최종 변경 모듈 로그는 `python-tests-v3.{json,log}`, 나머지는 `python-tests-v2.{json,log}`와 `python-filter-integration-v1.{json,log}`에 있다. 마지막 독립 검토에서 발견한 설정 unknown 우회는 재필터 요구로 막았고, 최종 관측만 실패한 경우도 다음 작업을 멈추는 회귀를 추가했다.

Cargo는 별도 ignored `cargo-target`, `CARGO_BUILD_JOBS=1`, `CARGO_INCREMENTAL=0`, offline 캐시로 실행했다. 각 무거운 명령 전 다른 터미널의 측정 프로세스와 25GiB 이상 디스크 여유를 확인했고 작업 중 `caffeinate -ims`를 유지했다. 시작 여유 공간은 약103.3GiB였다.

새 실행기 실제 연결 확인은 자체 회로만 사용했다. `v5-smoke-v2/summary.json`의 whole/split 각각 preflight compiler gate와 zkFuzz를 순차 실행하여 29필드·peer 선언 동등성·후보 1개씩·최종 영수증·cleanup 완료를 확인했다. 각 wall은 0.865711/0.956845초로, **운영 smoke 기록이며 성능 비교 자료가 아니다**. cold-v2나 N5 요청은 재실행하지 않았다.

실패 기록도 보존했다. 초기 테스트 묶음 실행 파일의 import 경로 오류는 `python-tests-v1.log`, 수정 후 성공은 v2에 있다. 최초 실제 smoke 회로는 Circom T3001로 preflight에서 차단되어 `v5-smoke-v1/`에 남겼고, 별도 정상 회로로 v2를 실행했다. 이는 설정 전달 probe 두 건의 비교와 구분한다. sandbox의 ps 관측 차단은 macOS 프로세스 관측 권한이 있는 동일 합성 테스트로 다시 확인했다.

작업 시작 전 기록한 동결 실행기·J 관련 28개 SHA는 모두 동일했다. `.gitignore:22`가 `scripts/__pycache__/`를 제외하고 `/runs/`도 제외함을 확인했다. `git diff --check`가 통과했다.

## 남은 운영 검증

Linux 매니페스트는 AWS에서 실제 빌드·SHA·설정 probe를 완료해야 한다. cgroup v2 위임, CPU affinity, `/proc` 관측, IMDS, Linux timeout/신호/디스크 관문과 작은 Mac/Linux 판정 동치를 AWS 한 대에서 먼저 검증해야 한다. Ubuntu 설치 초안은 실행하지 않았다. Mac Python 3.15의 libexpat 연결 문제는 읽기 전용 `plutil` JSON 변환으로 우회했다. 실제 관측은 10 logical CPU·24GiB RAM·APFS SSD·Apple Fabric이며 `host-environment-v2.json`에 원래 오류와 fallback 출처를 보존했다. 양쪽 관측이 실패하면 null과 오류를 남긴다. 당시 메모리 압축·swap이 있어 smoke 시간을 성능 결과로 쓰지 않는다.

이번 변경은 실행·계측 기반을 준비한 것이며 W/S+J 우위나 새 취약점 탐지 성과가 아니다. A cold-v2의 wrapper 분석은 개발 근거다. N5 플랫폼 개정·wrapper 옵션 채택·실험 계획은 사람 검토 후 별도로 결정한다.

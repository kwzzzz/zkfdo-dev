# N6-B1 실행기 v3와 B 1단계 실행 준비

담당: miiz. 상태: **준비 완료, B 실행 미착수**. 기한: 2026-10-07.

## 구현 결과

고정된 v1·v2 파일은 수정하지 않고 [v3 실행기](../scripts/run_policy_a_engine_v3.py)를 새로 만들었다. v1 상태기의 예산·seed pass·후보 조기 반환 뒤 재시작·timeout·시작 실패·프로세스 그룹 정리를 유지하면서 다음을 추가했다.

- W는 첫 시도에 전체 예산을 할당하고 작업공간 생성은 `cp -cR` APFS clone만 허용한다. 실패 시 일반 복사 fallback은 없다.
- S는 plan 순서대로 순환하고 조각마다 별도로 고정한 준비 `sources/` 스냅샷을 쓴다. stage1 plan의 적격 조각 수는 대상별 35–786개이며 21개 제한은 없다.
- 모든 시도에서 50ms 간격으로 프로세스 그룹 RSS 합을 관측한다. 10 GiB 초과 시 그룹을 종료·회수하고 `memory_cap`으로 기록하며 경과 시간은 캠페인 예산에서 빠진다.
- `stderr_report` 모드만 사용한다. `--save_output`은 없고, 조건 문자열을 candidate report와 해시로 연결한다.
- candidate·stdout/stderr·attempt result를 보존한 뒤 각 시도의 workspace 파일 수·바이트·삭제 시간을 기록하고 workspace를 지운다.
- S 조각 커버리지는 600초와 3,600초 이전에 프로세스가 시작된 고유 조각 수를 적격 조각 분모로 기록한다.

[대기열 실행기](../scripts/run_n6_b_queue.py)는 상태 파일로 재개하고 단위 안에서 W→S를 끝낸 뒤 다음 단위를 받는다. 동시 단위는 3개다. 100만 제약 이상인 aadhaar와 Vota 단위는 공통 exclusive lock으로 겹치지 않는다. 10초 host load와 free disk를 남기며, 여유 공간이 35 GiB 미만이면 새 단위를 시작하지 않는다. SIGINT/SIGTERM은 실행 중인 단위를 자르지 않고 새 단위 배정만 멈춘다.

## 고정 spec과 대기열

- 대상 목록: `docs/n6_targets_b_2026-10-06.json`, `853eef3b91698ea4f6c8e9189e0bfb765b697d7f6a505800cb7e42644d07dca6`.
- 최종 spec: `runs/n6-2026-10-06/specs-v5/`의 60개 파일. stage1 10개 × seed 3개 × W/S이며 각 파일 해시는 queue의 해당 단위에 있다.
- 최종 queue: `runs/n6-2026-10-06/queue-v5.json`, `07944ae72355645d8e4672dc4ac69ee72cfcefe7afb3897deeb23df4cc7e7b71`.
- v3 실행기: `45ece40a6edcc5c7b3ae0e5cf9f3172a23707189575ef2a542910c085aa7089e`.
- queue 실행기: `04bca462c29f680b018d2f811e327ae65143027d3fa4b30029758e510e7e28ee`.
- 예산·seed: B 총 3,600초, S 시도 30초, seed `2026100601/02/03`. zkFuzz `ac2d9d16…`, Circom `8991887…`.

대기열은 seed 순서, 각 seed 안에서 고정 stage1 순서다. 첫 두 항목이 aadhaar·Vota이지만 exclusive lock 때문에 동시에 실행되지 않으며, 그동안 다른 normal 단위는 나머지 worker에서 실행될 수 있다. 최종 queue 상태는 `prepared_not_started`이고 B zkFuzz 실행은 0회다.

## 결정적 검사

최종 self-test는 `runs/n6-2026-10-06/state-machine-v3-v5/self-test-v3.json`에 있고 SHA-256은 `69c089990f17b0812332f3fdcf5704ccc25f804550f93d9e53057451900f940e`다. v1의 후보 조기 반환·중복·잔여 예산·timeout 후 descendant 정리·시작 실패·nonzero·취소·순서·pass seed 검사와, v3의 실제 프로세스 그룹 RSS 초과 종료·회수를 모두 통과했다.

Python 회귀는 대상 수 일반화, 21번째 이후 target 검증, 독립 snapshot 강제, APFS clone 실패 시 fallback 금지, `memory_cap`, workspace 삭제, 시작시각 기준 커버리지, queue 변경 감지, 대형 단위 비중첩, 고정 queue 분모를 확인한다.

최종 검사는 Python 23건, `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test` 348건 통과·22건 ignored다. 로그는 `runs/n6-2026-10-06/checks-v5/`에 있다.

## 개발 회로 시험 운전

최종 v5 runner로 A-02 inference 개발 자료를 실행했다. 후보 파일 내용은 열지 않았고 평가 결과에 포함하지 않는다.

| 방식 | spec SHA-256 | preflight | 캠페인 wall | 시도·outcome | 시작 분모 | CPU 합 | 프로세스 트리 RSS 최대 | workspace 잔존 |
|---|---|---|---:|---|---:|---:|---:|---:|
| W | `f1c18a02d96767c7c8c5ab2f5aa573f0fd51fcec0f19480175934e2e43bc6317` | 통과 (`4206f12c…`) | 60.052초 | 1회, timeout 1 | 1/1 | 59.755초 | 1,464,057,856 B | 0 |
| S | `4aef48b3785711fb182fc69832abfec48cceb62944d353aea2a5e99b6fdfd15c` | 21/21 compile 통과 (`bcf001a4…`) | 60.023초 | 8회, candidate signal 1·no-candidate 5·timeout 2 | 8/21 | 59.149초 | 8,699,904 B | 0 |

W ledger는 `7dddc198fb49dee1fd0fdae6e62e77196f16edc42e1f66050f086630d545ec33`, S ledger는 `49a6871eff1c0d8119bf241ac067d8c6d7473c3de138ae283608290e82c5f34c`다. S의 candidate signal 1건은 실행기 연결 확인일 뿐 확인된 결함·고유 원인·의미 판정이 아니다. 파일을 열거나 과거 판정을 복사하지 않았다.

구현 중 발견된 직렬화·validator 연결·커버리지 경계 오류는 B 실행 전에 고쳤다. 실패 실행과 v1–v4 spec은 ignored run root에 보존했고 최종 대기열은 v5만 참조한다.

## 상태와 한계

N6-B1 준비 관문은 통과했다. B 1단계 실행은 검수 후 별도 지시 전까지 시작하지 않는다. 이 작업은 실행·자원 제한·기록 경로를 확인한 것이며 candidate 의미, 탐지 우위, N6 평가 결과를 확인한 것이 아니다.

# N6-A2b v4 실행 준비 결과

- 상태: **준비 완료, campaign 미실행**
- 담당: miiz
- 범위: N6-A2 중단 기록, physical footprint 기반 실행기 v4, 환경 관문·건강 기록 대기열, A/B queue와 preflight 재사용 검증
- 후보 처리: 후보 파일 내용 미개봉, J 및 사람 의미 검토 미수행

## 실행기 v4

`scripts/run_policy_a_engine_v4.py`는 v1~v3를 수정하지 않고 새로 만들었다. 시도 프로세스 그룹을 `ps`로 열거한 뒤 각 프로세스에 macOS `proc_pid_rusage(pid, RUSAGE_INFO_V0)`를 호출해 `ri_phys_footprint`를 합산한다. 1초 표본의 합이 10 GiB를 넘으면 해당 프로세스 그룹을 종료하고 `memory_cap`으로 기록한다. 같은 표본의 `ps` RSS 합도 별도 필드에 남긴다. 프로세스 열거 또는 어떤 프로세스의 `proc_pid_rusage`가 실패하면 감시 없이 계속하지 않고 `resource_monitor_failure`로 종료한다.

시도 ledger에는 다음을 구분해 기록한다.

- `aggregate_process_tree_peak_physical_memory_bytes`
- `aggregate_process_tree_peak_rss_bytes`
- `aggregate_process_tree_peak_rusage_resident_bytes`
- `aggregate_process_tree_peak_process_count`
- physical footprint 기반 cap과 1초 표본 설명

known attempt workspace는 결과 메타데이터를 쓴 뒤 삭제한다. `runs/` 재귀 인벤토리는 만들지 않으며 파일 수와 용량은 `unknown` 및 이유로 남긴다.

| 파일 | SHA-256 |
|---|---|
| `scripts/run_policy_a_engine_v4.py` | `ff36c6db0a7475064c388a9bd0b0a1845863329f1fe2e2b40f06dec641fa9451` |
| `scripts/run_n6_v4_queue.py` | `b0d8912f5395767ddc676e82595e445e6f19c5d572b1a8af936adab7610362c7` |
| `scripts/run_n6_v4_campaigns.py` | `c159004fc288cd68d9c0bf7a2552823b32651e76c7fe157e92d1c70d49ea6cef` |
| `scripts/n6_make_a2b_v4.py` | `42b710d3334b765eba898e5c7da4ca7a0c0afbe241a89f30dbb1e355496a6f26` |

## self-test

실제 macOS self-test 근거는 `runs/n6-a2b-2026-10-08.noindex/self-test-v4-v2/self-test-v4.json`이며 SHA-256은 `7522f92b11feb7c342090601ae8da98373e2a18e77d3369da1bf8f0dd7bd7d91`이다.

| 검사 | 결과 |
|---|---|
| 비영 데이터 64 MiB씩 최대 2 GiB 단계 할당, 시험 cap 1 GiB | `memory_cap`; physical peak 1,283,245,352 bytes에서 종료·reap·process group 비움 |
| `proc_pid_rusage` 대 `footprint -p` | 141,378,040 대 141,557,760 bytes, 차이 0.127%로 5% 이내 |
| 낮은 RSS·cap 초과 physical 값 주입 | `memory_cap` |
| 읽기 실패 주입 | `resource_monitor_failure`, 종료·reap·process group 비움 |
| v1 결정적 상태기 | 통과 |

별도 Python 회귀 검사는 v4 엔진·환경 대기열·독립 supervisor 19건을 통과했다. 시작 관문 실패 fixture는 `run_unit`이 한 번도 호출되지 않고 `state.json`과 `queue-summary.json`에 `start_gate_failed`를 남긴 뒤 코드 2로 종료한다. 디스크 관문으로 멈춘 상태가 종료 정리에서 일반 `stopped_between_units`로 덮이지 않는 회귀 검사와 실행기 pin 검증 실패도 최종 요약에 기록하는 검사도 통과했다.

최종 검사는 `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`, Python v4 회귀 19건이 모두 exit 0이다. 명령·로그 해시 기록은 `runs/n6-a2b-2026-10-08.noindex/checks-final/checks.json`(SHA-256 `bc240550fb92dace29cb2bbcc5f3fa92904b148da4e3085abbf6af5941763439`)에 있다.

## 대기열 v4와 환경 기록

실행 시작 전 60초 동안 AC 전원, low power mode 0, thermal 경고 없음, `kern.memorystatus_level >= 50`, swap 증가 없음이 모두 필요하다. 메모리 상위 10개 프로세스는 `proc_pid_rusage` physical footprint 기준으로 `start-gate.json`에 기록한다. 하나라도 실패하면 W/S campaign을 시작하지 않고 supervisor도 다음 queue로 진행하지 않는다.

실행 중에는 1초마다 memorystatus level·swap 사용량·load average를 `host-health.jsonl`에 남기고 1분마다 thermal 상태를 추가한다. 새 단위는 memorystatus level 40 이상이며 직전 60초 swap 증가가 없을 때만 시작한다. 각 run은 관문 대기시간과 시작 당시 실제 동시 실행 수를 보존한다. 단위 실행 중 swap이 512 MiB 넘게 늘거나 memorystatus level이 15 미만이거나 thermal 경고가 생기거나 건강 기록이 불완전하면 `environment_pressure`로 표시한다. 모든 primary run이 끝난 뒤 표시 단위를 동시 실행 1로 한 번 다시 실행하고 두 기록을 모두 보존한다. 선택 가능한 본 결과는 압력 표시가 없는 run뿐이다.

새 단위 직전 디스크 여유가 A에서 40 GiB, B에서 35 GiB보다 작으면 현재 실행 중인 단위만 마친 뒤 `disk_guard` 상태로 멈춘다. 이 상태는 종료 정리에서도 보존된다.

A queue는 A-D 36단위를 모두 끝낸 뒤 A-Q 45단위를 시작한다. B queue는 million-plus primary 단위를 둘 이상 동시에 시작하지 않는다. A는 총예산 600초, B는 3,600초이며 양쪽 모두 S 시도 상한 30초, seed 3개, physical cap 10 GiB를 유지한다.

| 준비물 | 분모 | SHA-256 |
|---|---:|---|
| A queue v4 | 81단위·162 W/S spec(A-D 36, A-Q 45, `aq-038` 제외) | `2b9d7f1838048a3a776426fd26c38d47dd9363e030299e95519bb5602d612754` |
| B queue v4 | 30단위·60 W/S spec | `d39e821fd65cea1852ad6a20b88ab59e03a7c363be9022224221986716161600` |
| A preflight 재사용 증명 | 162/162 통과 | `3c3cf4918b381d11a2f9f6c91519e854f0bd115bc679296d60a3378c6428a8ce` |
| B preflight 재사용 증명 | 60/60 통과 | `4af095fcd9f7370e01cf0fe48fa32d2164a19b2f98273859355f0c7d284be030` |
| 실행 manifest | A→B 순서, campaign 미실행 | `920fab8d48efd3ae8c208acf6c02e1ec73cb70ea5bda91bcd87d0688fa7a3911` |

preflight 재사용은 각 source ledger의 상태와 해시를 다시 확인하고, source/destination spec이 `campaign_id`와 runner v3→v4 pin을 제외하면 같은지 전수 비교했다. 검증된 원본 snapshot과 로그의 상대 경로를 보존하면서 v4 spec 해시에 연결한 별도 preflight ledger를 162개와 60개 모두 생성했다. v4 변경은 campaign 자원 감시에만 영향을 주므로 재컴파일했다고 기록하지 않는다.

## 독립 터미널 실행

miiz의 별도 실행 지시 뒤 VS Code와 코덱스를 종료하고 터미널에서 다음 한 줄을 그대로 실행한다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu python3 scripts/run_n6_v4_campaigns.py --manifest runs/n6-a2b-2026-10-08.noindex/execution-manifest-v4.json > runs/n6-a2b-2026-10-08.noindex/terminal.log 2>&1
```

이 명령은 코덱스 세션을 사용하지 않고 foreground에서 A 다음 B를 실행한다. 진행 상황은 각 queue의 `state.json`, `unit-gate-waits.jsonl`, `host-health.jsonl`과 공통 `execution-events.jsonl`에만 남고, stdout·stderr는 `runs/n6-a2b-2026-10-08.noindex/terminal.log`에 기록된다. A 또는 B의 시작 관문이 실패하면 해당 queue의 campaign을 하나도 시작하지 않고 즉시 코드 2로 종료하며 다음 queue로 진행하지 않는다.

각 queue는 종료 시 `a-execute.noindex/queue-summary.json` 또는 `b-execute.noindex/queue-summary.json`을 쓴다. supervisor는 정상 종료·관문 실패·실행 실패와 시작 전 pin 검증 실패를 모두 `runs/n6-a2b-2026-10-08.noindex/execution-summary.json`에 단계 상태 또는 오류, 종료 코드, 생성된 queue 요약 경로·해시를 기록한다.

이번 작업에서는 위 명령을 실행하지 않았고 A/B campaign은 0회다. 리드의 v4 직접 시험과 miiz의 VS Code 재시작·앱 정리가 끝난 뒤 별도 지시로 시작한다.

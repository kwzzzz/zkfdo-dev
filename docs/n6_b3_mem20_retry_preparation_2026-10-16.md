# N6-B3 mem20 v4.4 재실행 준비 (2026-10-16)

## 범위와 시작 조건

[지시](../runs/handoff/n6_b3_mem20_retry_fix_instruction_2026-10-16.md)의 SHA-256 `daa2897e43d352e323792f5d0b5d017dbc0d7c4a1ec4bc2d2d41702421a20b89`를 확인했다. 시작 시 [원래 state](../runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json)는 `stopped_between_units`, SHA-256 `5160fda628e9a920d8a0f7717b31fc05ad88326a371780908803d187b2ddfc7c`였다. 기존 실행 입력 61개는 원래 해시 목록과 모두 일치했다. 원래 state·v4.3·고정 입력·실행 산출물은 수정하지 않았다.

이번 작업은 실행기 수정과 실행기 테스트만 수행했다. 실제 사전 관문, 자원 부하 self-test, 재실행·기타 실험, 판정, B 후보 값 열람, 의존성 설치는 수행하지 않았다. 일반 AGENTS.md의 Cargo 검사 요구보다 이번 사용자의 “테스트는 1의 실행기 테스트만” 제한을 적용하여 `cargo fmt`, `cargo clippy`, `cargo test`는 실행하지 않았다. Rust 코드는 수정하지 않았다.

## 변경 내용

- [v4.4 실행기](../scripts/run_n6_v4_4_queue.py)는 v4.3 복사본에 관문·대기 표시·재실행 모드를 추가했다. 관문은 끝에서 첫 `sample_time <= now−60초`까지 읽고, 최신 샘플 나이 `0..3초`를 요구한다. 전체 이력을 복사하거나 삭제하지 않아 `assess_unit`은 원래 단위 구간 전체를 계속 검사한다.
- swap은 v4.3과 동일한 구간의 마지막 값 ≤ 첫 값 기준이다. memorystatus ≥40, AC, 오류 없음 조건을 유지하며 swap 결측은 통과시키지 않는다. 단위 압박의 >512 MiB 증가, memorystatus <15, thermal 및 AC·기록 오류 기준은 그대로다.
- 대기가 1,800초를 넘으면 새 state에 `gate_waiting_since`, `gate_wait_last_reasons`, `gate_wait_unit_id`를 저장하고 사유 변경 시 갱신한다. 통과 시 지운다. 대기 중 중단하면 `stopped_between_units`와 마지막 대기 정보가 함께 남는다.
- `--action retry --from-state ... --units ...`는 중단 상태·queue 해시·지정 단위의 압박 있는 완료 primary 1개·재실행 미착수 여부를 확인한다. 지정 순서대로 run 2 / `pressure_retry` / 동시 1만 수행한다. 추가 primary나 세 번째 실행은 만들지 않는다. 새 출력이 이미 있거나 원본 state 디렉터리 안이면 거부한다.
- 새 state는 `source_state.path/sha256`, 각 단위의 `primary_run_ref.state_path/state_sha256/json_pointer`로 원래 1차 기록을 참조한다. 새 `runs`에는 이 재실행 기록만 들어가므로 새 queue-summary의 분모는 지정한 두 단위다. 원래 여섯 단위 전체 결과와 합산하는 작업은 하지 않았다. 결과 상태는 v4.3의 `completed_unpressured_retry`, `retry_environment_pressure`, `stopped_between_units`, `disk_guard`, `start_gate_failed`를 유지한다.
- 기존 mem20 사전 관문은 검증용 runner와 B2 호스트 관문 모두 v4.3에 묶여 있다. [새 연결 스크립트](../scripts/n6_b3_mem20_retry_prestart_gate.py)는 기존 검증·호스트 검사 절차를 재사용하고 두 연결을 v4.4로 지정한다. 원래 두 관문 스크립트는 보존했다. 검사 출력은 재실행 출력 디렉터리 밖의 새 파일이며 기존 출력은 덮어쓰지 않는다.

## 실행기 테스트

| 범위 | 결과 |
|---|---|
| 기존 v4/v4.1/v4.2/v4.3 queue·supervisor·Policy-A v4 실행기와 새 사전 관문 mock 테스트 | 63/63 통과, 6.933초 |
| 새 v4.4 실행기 테스트 | 15/15 통과, 0.030초 |
| 기존 v4.3 테스트 15개를 v4.4 모듈에 연결한 호환성 검사 | 15/15 통과, 2.347초 |

합계 93회 테스트가 통과했다(서로 다른 테스트 78개 + 새 모듈에 적용한 기존 15개). 간격 1.04초, 다음 샘플 0.01초 전 스냅샷을 연속 120회 구성하면 v4.3은 매번 `swap_window_short`, v4.4는 매번 통과한다. 같은 조건에서 swap 증가 시 차단된다. 최근 꼬리만 읽는지, 과거 구간 압박 기록 보존, 오래된/불완전한 표본, 30분 대기 표시, 원본 state 불변·두 단위 선택·중복/기존 출력 거부·중단/디스크/압박 상태도 검사했다. 캠페인 호출은 mock이며 실제 회로·후보를 사용하지 않았다. 기존 Policy-A 자원 감시 테스트의 자식은 합성 sleep 프로세스다.

검사 명령은 다음과 같다. 마지막 호환성 검사는 `tests.n6_v4_3_queue_test.queue`를 새 모듈로 연결한 뒤 같은 `N6V4QueueTest`를 실행했다.

```sh
python3 -m unittest tests.n6_v4_queue_test tests.n6_v4_1_queue_test tests.n6_v4_2_queue_test tests.n6_v4_3_queue_test tests.n6_v4_supervisor_test tests.policy_a_engine_v4_test tests.n6_b3_mem20_retry_prestart_gate_test -v
python3 -m unittest tests.n6_v4_4_queue_test -v
```

## 실행 입력과 미주용 명령 — 작성만, 미실행

[새 실행 입력 SHA-256 목록](../runs/n6-b3-2026-10-12.noindex/mem20-retry-inputs.sha256)은 68개 파일을 고정한다. 기존 61개에 v4.4·새 관문·원래 mem20 state·간접 엔진/파서 모듈·관문에서 호출하는 실행기 테스트를 추가했다. 목록 SHA-256은 `9deeb5239d8c48df12efd5209999f217eb4d61dac09d281b0e1a6f72f36fd5c5`다. 새 manifest의 68/68 해시를 재확인했다.

남은 단위는 `340107e1f1d8b0a45656cffa-seed-2026100602`, `6079a717f929aaf04a04e329-seed-2026100603`이다. 읽기 전용 metadata 검증에서 두 단위가 조건을 만족함을 확인했다. 각 단위 W 3,600초 + S 3,600초로 예산 합계는 4시간이며 관문 대기·준비 비용은 별도다. 아래는 사람이 실행할 명령이다. 입력 해시와 실제 사전 관문이 통과해야 `caffeinate -dimsu` 재실행으로 이어진다.

```sh
(
  cd /Users/miiz/Desktop/kwzzzz_zkfr || exit 1
  set -C
  mem20_retry_stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  shasum -a 256 -c runs/n6-b3-2026-10-12.noindex/mem20-retry-inputs.sha256 &&
  python3 scripts/n6_b3_mem20_retry_prestart_gate.py \
    --queue runs/n6-b3-2026-10-12.noindex/mem20-prep/queue-b-mem20.json \
    --from-state runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json \
    --units 340107e1f1d8b0a45656cffa-seed-2026100602 6079a717f929aaf04a04e329-seed-2026100603 \
    --output "runs/n6-b3-2026-10-12.noindex/gates/prestart-gate-mem20-retry-${mem20_retry_stamp}.json" &&
  caffeinate -dimsu python3 scripts/run_n6_v4_4_queue.py \
    --action retry \
    --queue runs/n6-b3-2026-10-12.noindex/mem20-prep/queue-b-mem20.json \
    --from-state runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json \
    --units 340107e1f1d8b0a45656cffa-seed-2026100602 6079a717f929aaf04a04e329-seed-2026100603 \
    --output runs/n6-b3-2026-10-12.noindex/mem20-retry.noindex \
    > "runs/n6-b3-2026-10-12.noindex/terminal-mem20-retry-${mem20_retry_stamp}.log" 2>&1
)
mem20_retry_rc=$?
printf 'mem20-retry exit_code=%s\n' "$mem20_retry_rc"
```

## 새 코드·테스트 SHA-256

| 경로 | SHA-256 |
|---|---|
| `scripts/run_n6_v4_4_queue.py` | `f78929ea8328294c38d1e91d108753c2a88b0219b5febd4b1be68811c6bb924e` |
| `scripts/n6_b3_mem20_retry_prestart_gate.py` | `854f83b1b4a9da256f32e107ad0e731c1ab847304d23457c96a82c1d6cd0c276` |
| `tests/n6_v4_4_queue_test.py` | `d7b8c2ad322c2f6901529232f143da0b3dbdc30d69fa01df8079ee1b495fa9c1` |
| `tests/n6_b3_mem20_retry_prestart_gate_test.py` | `97cec7efce300c7c9fa9ed257dcc239dc980cecd5b2efd30436eaa2cc917a1e2` |

이번 작업에서는 mem20 재실행 출력 디렉터리를 생성하지 않았다. 위 명령은 실행 승인이나 관문 통과 기록이 아니며, 후속 판정·결과 집계도 수행하지 않았다.

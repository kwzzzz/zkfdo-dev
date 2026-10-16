# N6-A2 A 실행 시작 기록

- 담당: miiz
- 호스트 시작 기록 시각: 2026-10-07T14:31:18+09:00
- 범위: A-D를 모두 끝낸 뒤 A-Q를 시작하는 W→S campaign execute
- 후보 처리: campaign 신호·파일 경로·해시만 기록하며 후보 파일 내용, 맥락 판정(J), 사람 검토는 열거나 수행하지 않는다.

## 실행 분모와 순서

A1b 고정 queue v3 `runs/n6-a1b-2026-10-08/queue-v3.json`의 SHA-256은 `f84ae9d85bd7eb5289e14e5cafd9cb0234b93fe1ce0dfc5d7805e5305f8b6201`이다. `aq-038-4e5dcd2256b8`의 W·S와 seed 3개를 모두 제외한 실행 목록은 `runs/n6-a2-2026-10-08/execution-list-v1.json`이며 SHA-256은 `deffcdc84845eddd20baac1088e48c3dcc22ac281b57fbc227f70338c5929fec`이다. 고정 A 목록과 70건 배치는 변경하지 않았다.

| 단계 | 단위 | W/S spec | queue SHA-256 |
|---|---:|---:|---|
| A-D | 36 | 72 | `77e5324b8d509ae8caad7b71c337d911247304ab6af393b19eb150e8bffb44d6` |
| A-Q | 45 | 90 | `7e7f913caab295da3a31ad006cc71b4dc8eb1625f3be2b96678ad91f3350130a` |
| 합계 | 81 | 162 | spec manifest `cd39b4aec84917b5e70fc1c1afd3dddcb1756d7920c17f79dc83584f3d0106bd` |

단위 안에서는 W 다음 S를 실행한다. 동시 단위는 3개다. A-Q는 A-D queue가 전부 완료된 뒤에만 시작한다. 방식·seed별 T=600초, S 시도 상한 30초, W 첫 시도 상한 600초, seed `2026100601`·`2026100602`·`2026100603`, 프로세스 트리 RSS 상한 10 GiB를 적용한다. 새 단위를 시작하기 전 여유 공간이 40 GiB 미만이면 queue 상태를 `disk_guard`로 기록하고 더 시작하지 않는다.

## aq-038 제외 근거

A1 leave-one-out 생성기는 계획 범위와 겹친 수정 diff의 hunk `@@ -9,815 +8,0 @@ template EmailAddrWithNameRegex(msg_bytes) {` 전체를 역적용했다. 이 때문에 템플릿 닫는 중괄호 뒤에 815줄이 붙고 `email_addr_with_name_regex.circom:21:2`의 `var`가 템플릿 밖에 놓여 P1012가 발생했다. patch SHA-256은 `5f30c3390b1086d9670594cabbfb1820ca8944832d36d2220c3e32430ce035f5`다. 제외 기록 `runs/n6-a2-2026-10-08/aq-038-exclusion.json`의 SHA-256은 `92b4bcd49361fff034eb83b667c8c0e04d39e4368dca311b9cc3d4dd3913e32d`다.

## 실행기·도구 고정

| 항목 | SHA-256 |
|---|---|
| `scripts/run_policy_a_engine_v3.py` | `7864c823af01be1e8945dedbc28198093087594edadad2367103012cfcff4599` |
| `scripts/run_n6_a2_queue.py` | `fed91e7e5304fb0d0f98577651dd7f3ceb2024330eeccfc08c78c4e9e29387e6` |
| `scripts/run_n6_a2_execute.py` | `709ac2bb63736b25b9a35c220aaa68ef4de171455bb55eed5887e3f9f0b2f723` |
| zkFuzz | `ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd` |
| Circom 2.2.3 | `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227` |

v3는 `ps`가 프로세스 트리 RSS를 읽지 못하면 해당 시도를 즉시 종료해 `resource_monitor_failure`로 남기도록 보정했다. 따라서 A1b spec에서 실행에만 영향을 주는 `campaign_id`와 runner 해시만 바꾼 A2 spec을 만들었다. 소스 snapshot, target, compile command와 compiler는 그대로다. A1b의 통과 preflight를 이 두 필드의 차이만 검증해 새 spec 해시에 연결했으며, 재컴파일했다고 기록하지 않는다. A-D preflight 요약 SHA-256은 `65a96fb9c11e8f26a94502c013b7747c80c9926ebd88e9ead11b0549a8a0fd72`, A-Q는 `b024ed7e3589bfe090456958ebf484f8f6d686e88cd808ebe3e31f3db86e944f`다.

## 실행 전 관문

| 관문 | 결과 | 근거 |
|---|---|---|
| include 출처 | 통과 | 162 spec·4,545 target reference, 미해결 include 0, snapshot 바이트 불일치 0. `include-provenance.json` SHA-256 `097bd2f31548b1b37069edcef9c8c9ba78dd88b6f66138c1a14ede2c7c204a44` |
| 10 GiB 실제 self-test | 통과 | `self-test-v3.json` SHA-256 `1d290aafba15388b715e38e32d9676cb578efeb9f76d242ca8b0f536b58f6b4f` |
| `ps` 실패 fail-closed | 통과 | 결정적 회귀 검사에서 자식 종료·reap·process group 비움을 확인 |
| 운영 | 통과 | `caffeinate -dimsu`와 `pmset -g log` 사용 가능. 실행 전후 pmset 로그 차이로 sleep 횟수를 계산 |
| 동시 무거운 작업 | 통과 | zkFuzz·Circom·Cargo·다른 N6 실행 프로세스 0 |
| 디스크 | 통과 | 182,649,249,792 bytes 여유(40 GiB guard 이상) |
| 시작 직전 load average | 기록 | 1/5/15분 `6.10205078125 / 5.0390625 / 4.21923828125` |

전체 관문 기록 `runs/n6-a2-2026-10-08/gates/prestart-gates.json`의 SHA-256은 `25fdd740e34d115e6d568efc996510f6a0fa06d76a365c0db1a8b883310b3883`이다. 실행 전에 `cargo fmt -- --check`, v3 Python 회귀 검사 7건, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`가 모두 통과했다. 측정 중에는 cargo 검사를 다시 실행하지 않는다.

첫 controller 기동 점검은 macOS `caffeinate`가 Python의 부모 프로세스로 남는다고 잘못 가정해 campaign 생성 전에 거부됐다. 후보 탐색·시도·원시 후보는 0건이었다. controller는 `pmset -g assertions`의 “caffeinate asserting on behalf of python3 PID”를 확인하도록 고쳤고, 실제 `-dimsu` 시험에서 다섯 assertion을 확인한 뒤 위 최종 해시로 다시 고정했다.

# N6-B2 B 본 실행 결과 (2026-10-12)

- 담당: miiz
- 상태: 메타데이터 집계 완료
- 범위: 선택된 W·S ledger, 실행 상태, 시작 관문, 호스트 표본, 관문 대기, `engine_nonzero` stderr만 읽음. 후보 파일 내용은 열지 않았고 재실행·엔진 수정·판정 재분류는 하지 않음.
- 해석: 후보 시도 수는 `ledger.attempts[].candidates`의 비어 있지 않은 항목 수다. 의미 검토나 맥락 판정 결과가 아니다.

## 시작 관문과 완료 상태

| 관문 | 결과 | 확인 내용 | 기록 |
|---|---|---|---|
| `prestart-gate-20261011T031337Z` | failed | `host_start_gate`만 실패: AC 미연결, 배터리 85%. 실행기 시작 전 중단 | `runs/n6-b2-2026-10-09.noindex/gates/prestart-gate-20261011T031337Z.json` |
| `prestart-gate-20261011T032536Z` | passed | 전체 통과: AC 연결, 배터리 85% | `runs/n6-b2-2026-10-09.noindex/gates/prestart-gate-20261011T032536Z.json` |

두 번째 관문 통과 뒤 실행 상태가 생성됐다. 실행기 시작 관문도 `passed`다.
30/30단위 `completed_unpressured`, 선택 run 30개, 재실행 0개, W·S 실행기 종료 코드 0은 60/60건이다.
실행 창(UTC): 2026-10-11T03:27:44.973104+00:00 ~ 2026-10-11T23:42:28.537352+00:00.

## W·S 집계

| 방식 | 종료 사유 | 시도 | outcome_counts | 후보 시도/파일 | 후보 단위 | 최대 동시 물리 메모리 |
|---|---|---:|---|---:|---:|---:|
| W | budget_exhausted 30 | 1167 | deadline_before_spawn 3, engine_nonzero 464, memory_cap 484, no_candidate 190, timeout 26 | 0/0 | 0 | 10.635 GiB |
| S | budget_exhausted 30 | 4867 | candidate 107, engine_nonzero 214, no_candidate 1572, timeout 2974 | 107/107 | 14 | 0.939 GiB |

W의 후보 0/30단위 중 rarimo 3단위는 `engine_nonzero` panic이 모든 정상 시작 시도의 거의 전부를 차지해 표에서 실행 불가로 표시한다. 나머지 27단위는 후보 0으로 표시하며, 그중 Vota·anon-aadhaar 6단위는 W `memory_cap`이 있었다. 이는 원시 outcome이나 종료 사유를 재분류한 값이 아닌 관측 설명이다. S의 후보 단위는 14/30이다.

## 단위별 상태

| 저장소·식별자 | seed | 상태 | W 관측 | W 시도 / memory_cap / panic | S 시도 / 후보 시도 | W/S 최대 물리 메모리 GiB |
|---|---:|---|---|---:|---:|---:|
| anon-aadhaar/anon-aadhaar `6079a717` | 2026100601 | completed_unpressured | 후보 0 (`memory_cap` 관측) | 108 / 107 / 0 | 160 / 3 | 10.635 / 0.035 |
| DoraFactory/Vota-Circuits `340107e1` | 2026100601 | completed_unpressured | 후보 0 (`memory_cap` 관측) | 68 / 67 / 0 | 144 / 0 | 10.172 / 0.019 |
| iden3/circuits `b5b5cf5d` | 2026100601 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 160 / 4 | 0.682 / 0.044 |
| pantherfoundation/panther-core `4c221df7` | 2026100601 | completed_unpressured | 후보 0 | 62 / 0 / 0 | 210 / 4 | 0.566 / 0.032 |
| rarimo/passport-zk-circuits `a8b2aa9c` | 2026100601 | completed_unpressured | 실행 불가 | 159 / 0 / 158 | 194 / 22 | 6.720 / 0.938 |
| selfxyz/self `83cc0060` | 2026100601 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 139 / 0 | 0.523 / 0.033 |
| tanctl/zylith-old `77e0f2db` | 2026100601 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 135 / 0 | 2.208 / 0.034 |
| tangle-network/protocol-solidity `e71f158d` | 2026100601 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 147 / 0 | 1.207 / 0.034 |
| Zellic/zkerc20 `76053f7f` | 2026100601 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 134 / 0 | 1.234 / 0.037 |
| iden3/circuits `60271bae` | 2026100601 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 152 / 0 | 0.621 / 0.035 |
| anon-aadhaar/anon-aadhaar `6079a717` | 2026100602 | completed_unpressured | 후보 0 (`memory_cap` 관측) | 59 / 58 / 0 | 160 / 3 | 10.598 / 0.035 |
| DoraFactory/Vota-Circuits `340107e1` | 2026100602 | completed_unpressured | 후보 0 (`memory_cap` 관측) | 66 / 65 / 0 | 174 / 2 | 10.172 / 0.021 |
| iden3/circuits `b5b5cf5d` | 2026100602 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 160 / 4 | 0.690 / 0.044 |
| pantherfoundation/panther-core `4c221df7` | 2026100602 | completed_unpressured | 후보 0 | 61 / 0 / 0 | 210 / 4 | 0.575 / 0.035 |
| rarimo/passport-zk-circuits `a8b2aa9c` | 2026100602 | completed_unpressured | 실행 불가 | 143 / 0 / 142 | 206 / 24 | 6.714 / 0.939 |
| selfxyz/self `83cc0060` | 2026100602 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 142 / 0 | 0.504 / 0.034 |
| tanctl/zylith-old `77e0f2db` | 2026100602 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 139 / 0 | 2.212 / 0.034 |
| tangle-network/protocol-solidity `e71f158d` | 2026100602 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 165 / 0 | 1.204 / 0.033 |
| Zellic/zkerc20 `76053f7f` | 2026100602 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 138 / 0 | 1.287 / 0.034 |
| iden3/circuits `60271bae` | 2026100602 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 152 / 0 | 0.614 / 0.032 |
| anon-aadhaar/anon-aadhaar `6079a717` | 2026100603 | completed_unpressured | 후보 0 (`memory_cap` 관측) | 121 / 121 / 0 | 160 / 3 | 10.612 / 0.035 |
| DoraFactory/Vota-Circuits `340107e1` | 2026100603 | completed_unpressured | 후보 0 (`memory_cap` 관측) | 67 / 66 / 0 | 174 / 2 | 10.172 / 0.021 |
| iden3/circuits `b5b5cf5d` | 2026100603 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 160 / 4 | 0.683 / 0.044 |
| pantherfoundation/panther-core `4c221df7` | 2026100603 | completed_unpressured | 후보 0 | 70 / 0 / 0 | 210 / 4 | 0.572 / 0.032 |
| rarimo/passport-zk-circuits `a8b2aa9c` | 2026100603 | completed_unpressured | 실행 불가 | 165 / 0 / 164 | 206 / 24 | 6.754 / 0.939 |
| selfxyz/self `83cc0060` | 2026100603 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 142 / 0 | 0.507 / 0.032 |
| tanctl/zylith-old `77e0f2db` | 2026100603 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 139 / 0 | 2.308 / 0.034 |
| tangle-network/protocol-solidity `e71f158d` | 2026100603 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 165 / 0 | 1.211 / 0.033 |
| Zellic/zkerc20 `76053f7f` | 2026100603 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 138 / 0 | 1.233 / 0.034 |
| iden3/circuits `60271bae` | 2026100603 | completed_unpressured | 후보 0 | 1 / 0 / 0 | 152 / 0 | 0.596 / 0.035 |

## panic 분류

`engine_nonzero` stderr 678개를 열어 panic 위치와 메시지로 분류했다. 후보 내용은 읽지 않았다.

| 위치·메시지 | W | S | 범위 |
|---|---:|---:|---|
| `src/mutator/utils.rs:522` — not yet implemented: Support nested-arrays for template parameters | 0 | 197 | 9개 대상 — DoraFactory/Vota-Circuits, Zellic/zkerc20, anon-aadhaar/anon-aadhaar, iden3/circuits, pantherfoundation/panther-core, selfxyz/self, tanctl/zylith-old, tangle-network/protocol-solidity |
| `src/executor/symbolic_execution.rs:2391` — no entry found for key | 464 | 17 | 1개 대상 — rarimo/passport-zk-circuits |

중첩 배열 panic의 9개 대상은 8개 저장소에 속한다. `iden3/circuits`에 서로 다른 식별자 2개가 있다.

rarimo W의 3개 seed별 panic 시도 중앙값은 14.30, 14.31, 13.29초다. 약 14초 뒤 매번 panic이 발생해 유효 탐색 시간이 사실상 0이었다. W의 `timeout` 또는 `deadline_before_spawn` 꼬리 시도까지 의미 있는 탐색 성공으로 해석하지 않는다.

## 관문 대기와 호스트 표본

- 단위 시작 관문 대기 표본 1043개(11단위): `ac_power_absent` 1, `swap_window_short` 1042. 선택 run의 관문 대기 합계 1056.737초, 최대 417.119초.
- 호스트 표본 71873개, memorystatus 수준 49~78. 선택 run 30개 모두 압박 없음으로 판정됐다.
- AC 관측 1199/1199개가 연결 상태, 발열 경고 관측 0/1199개. AC·발열은 모든 표본에 포함되지 않았다.
- 스왑 사용량 첫/끝 2.750/2.695 GiB, 관측 범위 2.695~2.780 GiB. 표본 오류 행 0개.

## 재현 근거

집계 JSON: `runs/n6-b2-2026-10-09.noindex/b-execute-summary.json` (SHA-256 `5f96f0513e15e82aaf020d1e5e240dd4c589b3ed1aa36746e6df3ee9bb314ffb`). 집계 스크립트: `scripts/summarize_n6_b2.py` (SHA-256 `dc364dde467f3d8cd91a14a64631747ef0a86ed743424602f4069683b107d0e4`).

| 입력 | SHA-256 |
|---|---|
| `queue` — `runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json` | `0fbaa62e4437c2f7bf8cfea45391d5375476a1090aaf39cc4433e6eff66e9b19` |
| `state` — `runs/n6-b2-2026-10-09.noindex/b-execute.noindex/state.json` | `a35e4376e95757f5ef8803b4b0e8bd1a0c6c6ee4df276cf09574d0fab50edd09` |
| `host_health` — `runs/n6-b2-2026-10-09.noindex/b-execute.noindex/host-health.jsonl` | `c79e7ae4213b16aa29b25dc43d75422b0b0d537c232133e6e3034a016d0bada2` |
| `unit_gate_waits` — `runs/n6-b2-2026-10-09.noindex/b-execute.noindex/unit-gate-waits.jsonl` | `66ffdf3974d2196a871bc31eeef2d85544723c46e3f3f73144f6d291df290bf9` |
| `execute_start_gate` — `runs/n6-b2-2026-10-09.noindex/b-execute.noindex/start-gate.json` | `ce234a4ed41f6e92b76317ba8827d714559dfb834b8033a6870bf74a7c36794b` |

각 60개 ledger의 경로와 SHA-256은 집계 JSON의 단위별 W·S 행에 있다. 두 시작 관문의 파일 해시는 JSON의 `prestart_gates`에 있다.

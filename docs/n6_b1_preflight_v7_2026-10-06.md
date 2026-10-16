# N6-B1 v7 S 라이브러리 경로 보정과 재점검

담당: miiz. 상태: **v7 spec 생성·B preflight 재점검 완료, B 퍼징 미착수**. 기준일: 2026-10-06.

이 문서는 [v6 사전 점검 기록](n6_b1_preflight_readiness_2026-10-06.md)을 보존하고, 그 검수에서 확인된 S root 단위의 라이브러리 경로 문제와 v7 재점검 결과를 기록한다. 고정 대상·예산·seed·대기열 순서와 W spec은 바꾸지 않았다.

## v7 보정

S target마다 준비 plan의 해당 target `definition.compile_args`에서 원본 절대 `-l` 목록을 다시 읽었다. `command`와 `preflight_compile_command`에서 v6의 workspace `-l` 목록을 순서까지 그대로 접두사로 유지하고, 원본 절대 목록을 기록 순서대로 뒤에 덧붙였다. W spec 30개는 v6 파일과 바이트 단위로 같으며 SHA-256도 모두 같다.

- queue: `runs/n6-2026-10-06/queue-v7.json`, SHA-256 `4033c40a9df75d0b22e281be9f85ad695f08faa24fb6be51f682e3c1e5ca3cef`.
- spec: `runs/n6-2026-10-06/specs-v7/`의 60개. queue가 파일별 SHA-256을 기록한다. W 30/30 v6 동일, S 30/30 기존 목록 접두사와 원본 절대 목록 접미사를 검증했다.
- spec 생성기: `scripts/n6_prepare_b_stage1.py`, SHA-256 `23d3dc69f667ac3a89fc9486bd91463b1ba0164553d7fb6b05dee600d62ed229`.
- queue 실행기: `scripts/run_n6_b_queue.py`, SHA-256 `7382b1fae9a27ece5c4b56912f05b69e4713676141d3ac378bd6eb48f19cb2f2`.
- v3 실행기: SHA-256 `23e94c40efccf44b3f42e8415c6b61491b9d0cc0b6640f8119263536779ced62`; 변경하지 않았다.

W 30건은 v6 완료 summary와 source spec의 해시가 v7 W spec과 정확히 같은 경우에만 별도 v7 ledger로 연결했다. S의 seed 재사용은 끄고 30개를 모두 물리적으로 실행했다.

## `bitify.circom` 조사

세 snapshot에서 `circomlib/circuits/bitify.circom` 파일 자체가 빠진 것은 아니다. 준비 snapshot은 원래 clone 접두사를 제거한 배치로 파일을 담았지만, v6 spec은 기록된 절대 경로의 전체 접두사를 `{workspace}` 아래에 붙였다. 따라서 실제 파일 위치와 `-l` 탐색 루트가 달라졌다.

| 대상 | root index | snapshot 안 실제 파일 | v6에서 필요했던 원본 라이브러리 root |
|---|---:|---|---|
| anon-aadhaar | 389/390 | `node_modules/circomlib/circuits/bitify.circom` | clone의 `node_modules` |
| selfxyz | 415/416 | `node_modules/circomlib/circuits/bitify.circom` | clone의 `node_modules` 등 준비 기록 6개 |
| zylith | 304/305 | `circuits/node_modules/circomlib/circuits/bitify.circom` | clone의 `circuits/node_modules` |

즉, 사본 생성에서 누락된 것은 include 파일이 아니라 **원본 라이브러리 root와 snapshot 배치 사이의 경로 대응**이다. v7은 요청된 spec 수정으로 원본 root를 fallback으로 제공했다. Rust 코드와 snapshot 생성 로직은 수정하지 않았다.

## 30개 S 재점검

원본 summary는 `runs/n6-2026-10-06/stage1-v7/preflight-all.json`, SHA-256 `337687ff1e63fffcd0aa9b9cfd28ca03527aaba5dfbff62e7887601b7715449b`다. 전체 결과는 **60/60 통과**이며, S는 **30/30 실제 실행·통과**, W는 **30/30 v6 바이트 동일 결과 재사용·통과**다.

| 저장소·entrypoint | S 조각 | seed 01 / 02 / 03 preflight wall (초) | 결과 |
|---|---:|---:|---|
| anon-aadhaar · `aadhaar-verifier.circom` | 390 | 494.160 / 488.893 / 524.219 | 3/3 통과 |
| Vota · `tally.circom` | 274 | 292.186 / 293.458 / 295.838 | 3/3 통과 |
| iden3 · `credentialAtomicQueryV3.circom` | 385 | 403.947 / 401.610 / 402.473 | 3/3 통과 |
| panther · `mainZAccountRenewalV1.circom` | 786 | 824.787 / 820.599 / 820.643 | 3/3 통과 |
| rarimo · `m.circom` | 35 | 41.097 / 38.773 / 38.608 | 3/3 통과 |
| selfxyz · `vc_and_disclose_kyc.circom` | 416 | 436.554 / 436.669 / 433.600 | 3/3 통과 |
| zylith · `private_liquidity.circom` | 305 | 320.732 / 323.080 / 321.127 | 3/3 통과 |
| tangle · `poseidon_vanchor_16_2.circom` | 292 | 306.021 / 311.079 / 306.325 | 3/3 통과 |
| zkerc20 · `circuit.circom` | 153 | 162.225 / 163.608 / 162.900 | 3/3 통과 |
| iden3 · `linkedMultiQuery3.circom` | 347 | 362.863 / 363.808 / 362.691 | 3/3 통과 |

v6에서 실패한 세 root target도 seed별 세 번 모두 성공했다. queue invocation wall은 10,967.732초이고 S 실제 preflight wall 합은 10,954.620초다. 통과 S에서 컴파일 산출물 10,149개·4,517,581,776 B를 경로·SHA-256·크기 원장 후 삭제했다. 시작·종료 free disk는 166,714,818,560 B → 133,916,618,752 B였다. snapshot·workspace·JSON·로그는 보존했다.

`stage1-v7`에는 `units/`, `state.json`, `host-load.jsonl`이 없다. 따라서 B zkFuzz campaign은 **0회**이며 후보 파일을 열지 않았다. 이 결과는 preflight 준비 가능성만 확인하며 후보 탐지나 의미 판정 결과가 아니다. B 실행은 별도 검수 후 지시를 기다린다.

## 검사

v7 생성 직후 queue 검증, W 30개 바이트 동일성, S 30개 명령의 기존 경로 접두사·원본 경로 접미사, `command`와 `preflight_compile_command`의 동일 `-l` 순서를 검사했다. v7 관련 Python 9건과 단독 실행기 회귀 16건이 통과했다. 전체 Python 회귀는 프로세스 열람이 허용된 조건에서 386건 통과했다. 샌드박스 안 첫 실행에서는 기존 C-02 검사 두 건이 `/bin/ps` 권한 거부로 실패했고 기존 v1 시간 기반 검사 한 건이 일시 실패했으나, 단독 검사와 권한을 갖춘 전체 재실행에서 모두 통과했다.

`cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`가 모두 통과했다. Rust 검사는 348 passed·22 ignored였고 실패는 없었다.

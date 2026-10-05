# A-02 실제 Policy A 엔진 실행 범위

2026-10-02 · 담당 miiz · `policy-a-engine-scope-v1` · 상태: **실행 전 고정**

이 범위는 기존 개발용 P2 `inference-main` production entrypoint 한 단위와 P2 small-first block 1의 21개 조각에 실제 zkFuzz Policy A 실행기를 적용한다. 기존 [A-01 SCOPE](../n4-1-policy-a-2026-10-02/SCOPE.md)와 [REPORT](../n4-1-policy-a-2026-10-02/REPORT.md)는 가상 예산 모델과 한정 계측 결과로 보존하며 수정하지 않는다. 새 프로젝트, held-out 자료, 추가 후보 선택, 후보 의미 검토, 일반 평가 실행은 포함하지 않는다.

## 고정 대상과 실행 자료

| 항목 | 고정값 |
|---|---|
| 프로젝트 | `inference-labs-inc/subnet-2-circom` |
| 기록된 원본 revision | `d310309c141d36504b3486cebd96ed70ef3a4fdf` |
| production entrypoint | `runs/dev-rq1-pilot-2026-09-29/inference-main/tree/src/circuit.circom` |
| production entrypoint SHA-256 | `f1b6abc4987d25cb53f9da6a72ade48703e99ba9499badb8c3dfee242c3a7464` |
| 통째 분모 | 1 |
| small-first 분모 | 21 |
| P2 pilot config | `reports/dev-rq1-pilot-2026-09-29/pilot-config.json`, SHA-256 `dc8adb794e6d8656ae71b5d778318381899fe3f771891caf37c5c3a415912d9b` |
| P2 project manifest | `reports/dev-rq1-pilot-2026-09-29/inference-main/manifest.json`, SHA-256 `01df2a3c7495d26c574a401bfb42ce9b8b7efd4ea11f8426ff0553ef2eea5804` |
| small-first block-1 plan | `runs/dev-rq1-pilot-2026-09-29/inference-main/campaign/small-first/block-1/plan.json`, SHA-256 `b8843d8b816c6b36934556a98b78d75f711f714212015688e3b0025e76e1cc7f` |
| P2 prepared metadata | `runs/dev-rq1-pilot-2026-09-29/inference-main/prepared/small-first/prepare-099c7c89-5866-43fc-9e72-49beac54420d/prepared.json`, SHA-256 `da6b439618f1250c9d55cf6319dc6a04cc10ae251c87bbe7215cacd31b244122` |
| ranking config | `configs/static-ranking.json`, SHA-256 `8fed87764b001245d600307f7ba7d8453e88e3b977afda656014eac83ea32d26` |
| clean source manifest | [37개 파일 목록](source-manifest-v1.txt), SHA-256 `69574bb41330e20ce1716fb0203688ef965e5dd985f171409d0dc630ca0075e9` |
| 실행기 clean-tree digest | 상대 경로·node kind·파일 hash를 결합한 SHA-256 `adff17f27909f8719fc2883e7a54b9c1e4924df92961878c3f4a257d592bbf5d` |
| 외부 dependency tree digest | `.external/zkbugs/dataset/circom/dependencies`, 실행기 방식 SHA-256 `5641746c77ce4fde88750166331d4bc4d6d32acfaddc9d5f71de947988392abf` |
| zkFuzz | `/Users/miiz/.cargo/bin/zkfuzz`, v2.2.1, SHA-256 `ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd` |
| Circom | `/Users/miiz/.cargo/bin/circom`, v2.2.3, SHA-256 `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227` |
| 공통 실행기 | [run_policy_a_engine.py](../../scripts/run_policy_a_engine.py), SHA-256 `c408ccbad8cc0847bc471b7b38cde0c21d81071157c50b95ab943b16055f874d` |
| 가짜 자식·회귀 검사 | [policy_a_engine_test.py](../../tests/policy_a_engine_test.py), SHA-256 `09413460e37e1bf0174ddbf615e5bf21024b78ac7fbbdeb9945f8138b70db78e` |
| 통째 spec | [whole-spec-v1.json](whole-spec-v1.json), SHA-256 `62c68534d7987c5b284577b9aaf626004bd6659c2aff3a21cc974f2419b11314` |
| small-first spec | [small-first-spec-v1.json](small-first-spec-v1.json), SHA-256 `bc9e8f58ce99f44b13faf27fd339490b75d6e823bb5afa06b04cddaf56f709e6` |

기록된 revision은 P2 provenance다. 로컬 clean `tree`에는 독립 Git metadata가 없으므로 이번 실행의 직접 바이트 고정 근거는 37개 파일 manifest와 실행기 tree digest다. 별도 checkout `runs/dev-projects/inference`의 HEAD가 기록된 revision과 일치하고, wrapper를 제외한 source snapshot과 차이가 없음을 실행 전에 확인했다.

기존 `prepared/.../targets/*/sources`에는 과거 P2의 counterexample JSON 30개가 10개 target에 남아 있다. 이를 삭제하거나 수정하지 않으며 새 실행의 baseline이나 새 후보 판정에 사용하지 않는다. 후보가 없는 clean `tree`를 preflight에 한 번 복제하고, 모든 실제 시도는 그 복제본을 다시 독립 작업공간으로 복제한다. plan의 source/snapshot fingerprint와 clean 파일이 일치하지 않으면 실제 캠페인을 시작하지 않는다.

## small-first 고정 순서

21개 target ID는 다음 순서다. 괄호 안은 plan에 기록된 label이다.

1. `sha256:157e88a9cf6ac84d6cc1b638a5b021dff3874f2cbf9a0cec9592ad8ffad4d030` (`AssertBit()`)
2. `sha256:1830b5991e7c31effb5249dccfc0f125fa1e5cc8099cfcdb5dc7d0e9bde75cb3` (`Subtract()`)
3. `sha256:5bb036e47fc7dba2d94c603cfdf0c75522d0d262938165b648b9884273ef62fc` (`IsZero()`)
4. `sha256:220e4e97e9a5ab14b003259206c40fdd8ccc29d1b6828ec716b0ddd72075cfab` (`RateOfChange()`)
5. `sha256:f217552b8840f9b526f5e6c70243cde863d63452e945eb922fd026e995bfa117` (`Where()`)
6. `sha256:f5040286e8ee5d4ebc0846921a2077922dc714b9d23518c6619e13c6eff6435e` (`FinalNewScore()`)
7. `sha256:40b686f270e27efc1c700d76bb087498afe49de7d1ae2cc0f19105858081125c` (`Num2Bits(41)`)
8. `sha256:f30ce83abfe17fbf52ffe18d617b131a3112f1cb02438e929c45d58dad8409d7` (`LessThan(40)`)
9. `sha256:0afd371f7b994556bc894a5773e85b63e668c56dce8b1dee0dd78e2faffc23a2` (`IntDiv(40)`)
10. `sha256:c390f893f51e513596a07f46194c2c72c4f1a6e5f6ad95b1c416109ffb5cf840` (`DistanceFromScore(40)`)
11. `sha256:7a45cab145dd298430d33839e2eba8aa4d866e55c38c852bf2c0cf12bd45b3e5` (`Num2Bits(81)`)
12. `sha256:a83744762ac16301bda74b28f53092f0adb77aa7a4962c6e081e9bfd4b1d3d51` (`LessThan(80)`)
13. `sha256:96336bc9aa04b9c4eabac2a1f3010067d5b5fcb75e8133b3451a035e8ae58e74` (`IntDiv(80)`)
14. `sha256:d59fef915c37c148f4c3c6bc3e06a901e47fb771af21c13d959c404db12a2a51` (`Clamp(40)`)
15. `sha256:7537bc0ef52b473eaa8aae356d2e04c1c8c749bf17bdb35422e1cf9db729ec67` (`CalculatedScoreFraction(40)`)
16. `sha256:6f244817dabda8262dffe521bdab2f97a607b2dad0d8dd92c195fe4d2d6b8081` (`ResponseTimeNormalized(40)`)
17. `sha256:65c1d9112d196b3bbc6c6f5e33758f5ffe02e2f6b60328878b6a3a9ec2e26904` (`Num2Bits(121)`)
18. `sha256:18954292807a36700ccbeed89b6b53d0588303bee27a2869fb262063950a5c8e` (`LessThan(120)`)
19. `sha256:f3158572394212c4511f169fdd26f2c06f3188b073a0000dee384ae1fc7e4b04` (`IntDiv(120)`)
20. `sha256:cbb4b300f8dba18f55da20646309efcec256acde0ee98eef986adf2bdf02cfec` (`ScoringFunction(40)`)
21. `sha256:82c7b377bf9ef6f552da6a27f68ed5c76f6c38dc81233cce97a64bdcde4338d0` (`ResponseTimeMetric(40)`)

## 실행 순서·예산·seed

실행 순서는 **결정적 가짜 자식 검사 → 통째 preflight → small-first preflight → 통째 캠페인 → small-first 캠페인**이다. 실제 두 캠페인은 동시성 1로 순차 실행하며 같은 `run_campaign` 상태기와 `spawn_and_measure` 프로세스 경로를 사용한다. OS page cache는 비우지 않는다. 통째 선행 효과와 실행 당시의 시스템 부하는 한계로 남기며 P2의 과거 병렬 lane 시간과 합치지 않는다.

| 방식 | 총예산 | 시도 상한 | 순환 |
|---|---:|---:|---|
| 통째 | 600초 | dispatch 시 남은 예산, 최대 600초 | 한 target을 한 pass로 보고 조기 반환 시 같은 target의 다음 pass |
| small-first | 600초 | 조각당 최대 30초와 남은 예산 중 작은 값 | 21개 고정 순서를 돈 뒤 다음 pass |

초기 seed는 `2026092931`이다. 0-based pass `p`의 seed는 `2026092931 + p`다. 통째는 한 시도가 한 pass이고 small-first는 21개 전체가 한 pass다. 같은 small-first pass의 21개는 같은 seed를 사용한다. overflow는 fatal configuration failure다.

후보, 미발견, 조기 정상 종료, target timeout, backend 비영 종료는 순서나 캠페인 종료를 바꾸지 않는다. 잔여 예산이 있으면 다음 고정 시도를 시작하며 target별로 총 600초를 복제하지 않는다. 마지막 시도 할당은 `min(시도 상한, dispatch 시 남은 캠페인 예산)`이다. 통째를 30초마다 재시작하지 않는다.

## 준비·컴파일·캠페인 비용 경계

- preflight는 source/tool/config/tree hash 검증, clean snapshot 복제, plan 순서·fingerprint 검증, 대상별 Circom R1CS compile을 측정한다. preflight compile은 default Circom 최적화 조건, prime `bn128`을 사용한다.
- preflight는 캠페인 예산 밖이다. 이 compile 산출물을 zkFuzz가 재사용한다는 주장은 하지 않는다. 실제 zkFuzz의 내부 compile은 캠페인 wall에 포함되며 compile-only 시간은 분리되지 않으면 `unknown`이다.
- 캠페인 단조시계는 첫 시도 dispatch 직전에 시작한다. 첫 프로세스 start offset을 별도 기록한다.
- 캠페인 wall에는 시도별 clean workspace 복제, seed 설정, spawn, zkFuzz 내부 compile·실행, 후보 저장, 재시작, timeout 종료, process-group 정리, 직접 자식 reap, 시도 result 저장이 포함된다. 최종 campaign ledger 저장 wall은 자기참조를 피하려 캠페인 밖에 별도 기록한다.
- 시도별 pre-spawn 복제·설정, process wall, 종료 후 정리, result 저장과 그 합계를 나누어 기록한다. timeout 정리가 600초를 넘으면 overrun으로 남기고 새 시도를 시작하지 않는다.
- log의 parent 관측 offset과 zkFuzz가 출력한 `Execution Time` 값은 별도 의미다. 후자를 정확한 후보 생성시각이나 캠페인 offset으로 바꾸지 않는다.
- 후보 의미 검토는 이번 범위 밖이다. 검토 시간과 상태는 `unreviewed`로 기록한다.

## 실패·취소·정리 규칙

- timeout, 후보 반환, no-candidate, engine 비영 종료는 process group 정리·직접 자식 reap·result 저장이 성공하면 다음 고정 시도로 진행한다.
- spawn 실패, source/hash 불일치, workspace 구성 실패, 후보/raw 저장 실패, result/ledger 저장 실패, 자식 또는 process group 회수 실패는 무결성 실패다. 해당 캠페인을 즉시 중단하고 현재 상태와 아직 시작하지 않은 분모를 기록한다.
- 공통 실행기의 fatal failure가 통째에서 발생하면 small-first는 `blocked_by_common_runner_failure`로 미시작 처리한다.
- 외부 취소는 현재 process group을 종료·회수하고 불완전 종료로 기록한다. 남은 target/pass와 뒤 캠페인을 시작하지 않는다.
- cleanup·reap 실패를 성공, timeout 또는 음성 결과로 바꾸지 않는다. small-first 21개는 실행 여부와 관계없이 evidence 분모에 남긴다.

## 자원 계측 범위

시도마다 POSIX `wait4`가 반환한 user+system CPU와 `ru_maxrss`를 기록한다. macOS의 `ru_maxrss`는 bytes로 보존한다. 이 값은 직접 기다린 zkFuzz process와 커널이 그 rusage에 누적한 종료 자식의 범위다. timeout 후손이 직접 자식에 누적되지 않았을 가능성과, 동시에 살아 있던 process-group 전체 RSS 합계를 측정하지 못하는 한계를 남긴다. 따라서 전체 process-tree CPU와 peak RSS는 완전 계측으로 주장하지 않으며 aggregate tree peak memory는 `unknown`이다. 측정 한계를 가상 모델 값으로 대체하지 않는다.

## 선행 상태기 검사

실제 zkFuzz 전에 같은 상태기와 실행 함수의 결정적 가짜 자식 및 회귀 검사가 다음을 확인해야 한다.

- 즉시 후보 반환 뒤 고정된 다음 시도, duplicate 보존, no-candidate와 engine 비영 종료
- timeout의 process-group 종료, 직접 자식 reap, 후손 잔존 방지
- spawn failure의 한 번 기록 후 fatal 중단, 외부 취소의 불완전 종료
- 잔여 할당 반환, 21개 고정 순서와 pass별 seed 증가
- source/plan fingerprint, zero-candidate baseline, pinned tool/tree
- compile 성공과 실패 차단, result 저장 실패의 비성공 처리

검사가 실패하면 실제 zkFuzz를 시작하지 않고 1/21 미실행 분모와 차단 단계를 기록한다.

## 원시 자료·판정·종료 기준

원시 로그, mutation settings, 후보, workspace, compile 산출물, 시도 result, campaign ledger와 자원 값은 ignored `runs/n4-1-policy-a-engine-2026-10-02/`에만 둔다. 공유 evidence에는 후보 값을 넣지 않고 경로·SHA-256·상태·시간·크기만 남긴다. 새 후보는 모두 `unreviewed`이며 위치·template 이름·파일 hash는 일반 TCCT, 원인, 고유 원인 수의 판정이 아니다. S-01 또는 S-02 판정을 새 후보에 복사하지 않는다.

결정적 상태기 검사가 통과하고 실제 통째·small-first 캠페인을 각각 한 번 끝내거나, 고정된 fatal 규칙으로 정확한 차단 단계와 미실행 분모를 기록하면 이번 A-02 범위를 종료한다. 결과를 본 뒤 새 seed, 양쪽 30초 민감도 실행, 새 프로젝트, 추가 후보 검토로 확대하지 않는다.

이번 한 쌍은 기존 개발 자료 한 단위의 관측이다. 자동 분해의 일반 탐지 우위, 독립 평가 성과, 의미 동등성, 확인 원인 수, 동일 시도 상한, 전체 process-tree 자원 동등성을 입증하지 않는다. N4-1 전체와 N5를 완료 처리하지 않는다.

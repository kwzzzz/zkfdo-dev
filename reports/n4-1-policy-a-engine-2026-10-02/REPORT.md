# A-02 실제 Policy A 엔진 실행 결과

2026-10-02 · 담당 miiz · `policy-a-engine-report-v1` · 상태: **고정된 개발 실행 완료, 후보 의미 미검토**

## 실행 결과

| 방식 | 사전 분모 / 시작 | 실제 시도 | 총예산 / 캠페인 wall | 실행기 결과 | 새 후보 occurrence | `wait4` CPU 합계 | 시도별 `ru_maxrss` 최대 |
|---|---:|---:|---:|---|---:|---:|---:|
| 통째 production entrypoint | 1 / 1 | 1 | 600초 / 600.040977초 | timeout 1 | 0 | 593.843319초 | 1,446,412,288 bytes |
| small-first | 21 / 21 | 67 | 600초 / 600.004113초 | candidate 31, no-candidate 17, timeout 19 | 31, 모두 `unreviewed` | 596.543063초 | 11,780,096 bytes |

통째와 분할은 새 공통 상태기와 프로세스 실행·계측 함수로 실제 `/Users/miiz/.cargo/bin/zkfuzz`를 실행했다. 통째는 첫 시도에 남은 전체 예산을 주어 30초마다 재시작하지 않았다. 분할은 고정한 21개 순서를 조각당 최대 30초로 순환해 완전한 3 pass와 네 번째 pass의 앞 4개를 실행했다. 21개 모두 첫 pass에서 시작됐으며 미시작 target은 없다.

통째 timeout에서 후보 파일이나 `NOT SAFE` 신호는 없었지만 이를 완결 음성이나 결함 부재로 해석하지 않는다. 분할의 31개 후보 값은 열거나 보고서에 싣지 않았고, 경로·SHA-256·크기와 attempt 수준의 parent 관측·완료 상한만 보존했다. 31개 파일 SHA-256은 서로 달랐으나 이는 31개 고유 원인이나 확인 결함을 뜻하지 않는다. S-01 또는 병렬 S-02의 판정을 새 후보에 복사하지 않았다.

## 사전 고정과 입력 보존

[SCOPE](SCOPE.md)에서 실제 실행 전에 다음을 고정했다.

- P2 `inference-main`, 기록된 revision `d310309c141d36504b3486cebd96ed70ef3a4fdf`
- 통째 1개와 P2 small-first block-1의 21개 ID·순서
- 초기 seed `2026092931`, pass마다 `+1`
- 방식별 총 600초, 통째 시도 최대 남은 600초, 분할 시도 최대 30초
- 가짜 자식 → 두 preflight → 통째 → 분할의 순차 실행, 동시성 1
- 후보 결과와 무관한 순환, fatal infrastructure failure와 외부 취소 규칙
- 준비·캠페인·재시작/정리·자원·검토 비용 경계

과거 prepared target source에는 이전 P2 후보 JSON 30개가 남아 있었다. 이를 수정하거나 새 baseline으로 사용하지 않았다. 후보 0개인 clean P2 tree의 37개 파일 manifest를 고정하고 preflight와 각 시도마다 새 작업공간으로 복제했다. 원본 P2 자료와 기존 A-01 SCOPE/REPORT/run은 변경하지 않았다.

실행기와 spec은 다음 SHA-256으로 고정됐다.

| 자료 | SHA-256 |
|---|---|
| `scripts/run_policy_a_engine.py` | `c408ccbad8cc0847bc471b7b38cde0c21d81071157c50b95ab943b16055f874d` |
| `tests/policy_a_engine_test.py` | `09413460e37e1bf0174ddbf615e5bf21024b78ac7fbbdeb9945f8138b70db78e` |
| `whole-spec-v1.json` | `62c68534d7987c5b284577b9aaf626004bd6659c2aff3a21cc974f2419b11314` |
| `small-first-spec-v1.json` | `bc9e8f58ce99f44b13faf27fd339490b75d6e823bb5afa06b04cddaf56f709e6` |
| `source-manifest-v1.txt` | `69574bb41330e20ce1716fb0203688ef965e5dd985f171409d0dc630ca0075e9` |

## 구현한 공통 경로

[실행기](../../scripts/run_policy_a_engine.py)는 두 방식에 같은 `run_campaign` 상태기와 `spawn_and_measure` 경로를 사용한다.

- clean source, plan 순서·fingerprint, tool/file hash와 dependency tree hash를 preflight에서 확인한다.
- 시도마다 clean workspace와 mutation setting을 새로 만들고 후보 저장도 그 복제본에 한정한다.
- 첫 dispatch 직전에 캠페인 단조시계를 시작하고 성공한 `Popen` 반환 직후의 parent 관측 offset을 따로 남긴다. v1 raw 필드명 `process_start_offset_seconds`는 OS 내부 시작시각을 뜻하지 않는다.
- 조기 후보·no-candidate·timeout·backend 비영 종료 뒤 결과와 무관하게 다음 고정 target/pass로 진행한다.
- spawn, source 복제, 저장, reap, process-group 정리 실패는 무결성 실패로 중단한다.
- timeout과 취소는 독립 process group을 종료하고 직접 자식을 `wait4`로 회수하며 group 잔존을 확인한다.
- 시도별로 dispatch부터 `Popen` 반환 관측까지의 합성 구간, 반환 관측부터 `wait4` 회수 관측까지의 구간, 종료 후 정리, result 저장 시간을 남긴다. 첫 합성 구간에는 source 복제·hash 확인·설정·명령 구성과 spawn 호출 지연이 함께 들어 있어 이들을 서로 분리한 값은 아니다.
- `wait4` CPU와 `ru_maxrss`, 후보 log의 parent 관측 offset, zkFuzz가 출력한 `Execution Time`을 서로 다른 의미로 기록한다.
- 후보는 raw 경로·SHA-256·같은 파일 hash 중복 연결만 기록하며 의미 판정이나 원인 병합을 하지 않는다.

결정적 가짜 자식은 후보 뒤 계속, duplicate 보존, no-candidate, timeout과 후손 정리, spawn fatal, 외부 취소, backend 비영 종료, 잔여 예산, 21개 순서와 pass seed를 같은 상태기에서 확인했다. 단위 회귀는 clean snapshot/plan fingerprint, pinned tool/tree, compile 실패 차단과 result 저장 실패도 확인했다.

## 준비와 컴파일

| preflight | clean 대상 | plan 확인 | compile | 전체 wall | compile wall 합계 | `wait4` CPU 합계 | `ru_maxrss` 최대 |
|---|---:|---|---:|---:|---:|---:|---:|
| 통째 | 1 | split plan은 provenance만 고정 | 1/1 성공 | 1.557341초 | 1.497304초 | 1.512695초 | 425,869,312 bytes |
| small-first | 21 | 21개 순서·62 fingerprint 일치 | 21/21 성공 | 0.626153초 | 0.318839초 | 0.169286초 | 12,615,680 bytes |

두 clean baseline의 기존 후보 수는 0이었다. preflight compile은 Circom v2.2.3, default 최적화, prime `bn128`의 readiness 확인이다. zkFuzz는 캠페인 안에서 다시 컴파일하므로 preflight 산출물이 재사용됐다고 계산하지 않는다. 통째와 조각의 크기가 다르고 한 쌍만 순차 실행했으므로 이 시간 차이를 준비 성능 우위로 쓰지 않는다.

## 예산 순환과 target별 결과

| pass | seed | 시작한 조각 | candidate | no-candidate | timeout | pass 종료 offset |
|---:|---:|---:|---:|---:|---:|---:|
| 0 | 2026092931 | 21 | 10 | 5 | 6 | 198.241618초 |
| 1 | 2026092932 | 21 | 10 | 5 | 6 | 396.262744초 |
| 2 | 2026092933 | 21 | 10 | 5 | 6 | 595.652086초 |
| 3 | 2026092934 | 4 | 1 | 2 | 1 | 600.004045초 |

| 순위 | target | 시도 | candidate | no-candidate | timeout | 후보 occurrence |
|---:|---|---:|---:|---:|---:|---:|
| 1 | `AssertBit()` | 4 | 0 | 4 | 0 | 0 |
| 2 | `Subtract()` | 4 | 4 | 0 | 0 | 4 |
| 3 | `IsZero()` | 4 | 0 | 4 | 0 | 0 |
| 4 | `RateOfChange()` | 4 | 0 | 3 | 1 | 0 |
| 5 | `Where()` | 3 | 0 | 3 | 0 | 0 |
| 6 | `FinalNewScore()` | 3 | 0 | 3 | 0 | 0 |
| 7 | `Num2Bits(41)` | 3 | 0 | 0 | 3 | 0 |
| 8 | `LessThan(40)` | 3 | 0 | 0 | 3 | 0 |
| 9 | `IntDiv(40)` | 3 | 3 | 0 | 0 | 3 |
| 10 | `DistanceFromScore(40)` | 3 | 3 | 0 | 0 | 3 |
| 11 | `Num2Bits(81)` | 3 | 0 | 0 | 3 | 0 |
| 12 | `LessThan(80)` | 3 | 0 | 0 | 3 | 0 |
| 13 | `IntDiv(80)` | 3 | 3 | 0 | 0 | 3 |
| 14 | `Clamp(40)` | 3 | 3 | 0 | 0 | 3 |
| 15 | `CalculatedScoreFraction(40)` | 3 | 3 | 0 | 0 | 3 |
| 16 | `ResponseTimeNormalized(40)` | 3 | 3 | 0 | 0 | 3 |
| 17 | `Num2Bits(121)` | 3 | 0 | 0 | 3 | 0 |
| 18 | `LessThan(120)` | 3 | 0 | 0 | 3 | 0 |
| 19 | `IntDiv(120)` | 3 | 3 | 0 | 0 | 3 |
| 20 | `ScoringFunction(40)` | 3 | 3 | 0 | 0 | 3 |
| 21 | `ResponseTimeMetric(40)` | 3 | 3 | 0 | 0 | 3 |

첫 분할 후보 신호는 rank 2 `Subtract()` 시도의 parent log에서 캠페인 offset 1.108243초에 관측됐다. 해당 시도 완료 offset은 1.117240초이고 zkFuzz가 출력한 실행 시간은 0.002734초였다. 세 값은 각각 parent 관측, 시도 기록 완료, 엔진이 출력한 내부 구간이므로 하나의 정확 생성시각으로 합치지 않는다. 무엇보다 이 occurrence는 이번 작업에서 의미 검토하지 않았으므로 확인된 결함 시간도 아니다.

## wall·재시작·자원 계측

| 계측 | 통째 | small-first |
|---|---:|---:|
| 첫 `Popen` 반환 후 parent 관측 offset | 0.010435초 | 0.010440초 |
| dispatch→`Popen` 반환 관측 합계 | 0.010435초 | 0.684142초 |
| `Popen` 반환 관측→`wait4` 회수 관측 합계 | 600.024083초 | 599.209437초 |
| 종료 후 result 전 정리 합계 | 0.005844초 | 0.070819초 |
| 시도 result 저장 합계 | 0.000268초 | 0.024446초 |
| dispatch→`Popen` 반환·정리·시도 저장 합계 | 0.016546초 | 0.779407초 |
| 캠페인 budget overrun | 0.040977초 | 0.004113초 |
| process-group kill | 1 | 19 |
| 직접 자식 reap / group empty | 1/1 / 1/1 | 67/67 / 67/67 |

두 캠페인의 wall 합계는 1,200.045090초, preflight까지 포함한 이 보고서의 계측 구간 합계는 1,202.228584초다. 가짜 자식·회귀 검사·사후 문서화 시간은 이 합계에 포함하지 않았다. 후보 의미 검토는 수행하지 않았으므로 검토 비용은 unknown이다.

CPU는 `wait4`가 반환한 직접 자식과 커널이 그 자식에 누적한 종료 자식의 범위다. `ru_maxrss`도 시도별 OS rusage 최대이며 동시에 살아 있던 전체 process group RSS의 합이 아니다. 전체 tree CPU·peak memory와 자원 동등성은 입증되지 않았다. 통째와 분할의 `ru_maxrss` 차이는 이 한 쌍에서 관측된 값이며 일반 비용 우위로 해석하지 않는다.

실행 후 기록 감사를 통해 v1 계측 필드의 경계를 더 좁게 해석했다. 고정 [SCOPE](SCOPE.md)의 OS process start와 복제·설정 분리 요구와 달리 실행기는 `Popen` 호출 직전 시각을 보존하지 않았다. 따라서 위 두 parent 관측 구간은 exact process lifetime이나 copy/settings-only 시간이 아니다. 이 보정은 캠페인 시작·종료 단조시계, 결과 수, `wait4` CPU/RSS, 총 wall을 바꾸지 않는다. 원시 ledger와 [v1 evidence](evidence.json)는 사후 수정하지 않았고, [보정 evidence v2](evidence-v2.json)에 필드 의미를 명시했다.

또한 attempt ledger의 stdout/stderr에는 경로만 있고 개별 hash가 없었다. 원시 로그를 수정하지 않고 실행 후 [로그 manifest](raw-log-manifest-v1.txt)에 가짜 자식·preflight·실제 캠페인 로그 246개의 경로·크기·SHA-256을 추가했다. v1 evidence에서 빠졌던 후보 occurrence별 크기, parent `NOT SAFE` 관측 offset, attempt 완료 offset 상한도 v2에 보충했다. 관측 offset과 완료 상한은 후보의 정확 생성시각이 아니다.

## 검증

- `cargo fmt`: 통과
- `cargo clippy --all-targets --all-features -- -D warnings`: 통과
- `cargo test`: 297 통과, 0 실패, 22 ignored
- `python3 -W error::ResourceWarning -m unittest discover -s tests -p '*_test.py'`: 46 통과
- A-02 실행기 전용 회귀: 7 통과
- 결정적 상태기 raw 검사 10개: 모두 통과
- [보정된 값 없는 evidence v2](evidence-v2.json)의 44개 path/hash 참조: 모두 존재하고 일치
- 후보 occurrence 31개: 경로·SHA-256·크기·parent 관측시각·완료 offset 상한 존재, 모두 `unreviewed`
- [원시 로그 manifest](raw-log-manifest-v1.txt): 246개 경로·크기·SHA-256이 실제 파일과 일치

## 해석과 남은 관문

A-02에서 공통 실제 실행 경로, 통째의 600초 단일 시도, small-first의 21개 분모·순환·잔여 예산, timeout 정리와 한정된 실제 자원 계측을 한 개발 단위에서 확인했다. A-01의 가상 모델을 실제 캠페인 결과로 대체해 쓰지 않고 두 기록을 구분한다.

이 결과만으로 분할의 탐지 우위나 고유 원인 수를 비교할 수 없다. 분할 31 occurrence는 모두 미검토이고 통째는 timeout이라 같은 검토 수준의 확인 원인이 양쪽에 없다. 개발에 노출된 한 프로젝트, 다른 시도 상한, 고정된 통째→분할 순서, OS cache, 불완전한 process-tree 자원 범위와 v1 phase 계측 경계가 남는다.

A-02의 이번 고정 실행 범위는 종료했지만 N4-1 전체 관문은 통과하지 않았다. 같은 수준의 후보 의미 검토·원인 귀속, entrypoint 의미, 전체 process-tree 자원과 공정성, 준비+검토 총비용, 독립 실행 단위가 남는다. N4-2는 미착수이고 N5는 미고정이다. 새 seed·민감도 실행·프로젝트·후보 검토로 자동 확장하지 않았다.

## 근거 경로

- [사전 범위](SCOPE.md)
- [통째 spec](whole-spec-v1.json) · [small-first spec](small-first-spec-v1.json)
- [clean source manifest](source-manifest-v1.txt)
- [보정된 값 없는 evidence v2](evidence-v2.json), SHA-256 `41855eae4d04b3426dd71ceff960fe7d925202d56180170a8681d0c85cfacb8e`
- [보존한 v1 evidence](evidence.json), SHA-256 `a8c9142580c110e61dbcb32f185b319c72ad1d6ce3351c0f567713ac1748194a`
- [원시 로그 manifest](raw-log-manifest-v1.txt), SHA-256 `81a7e9e8fda0a15fc21e0981bbaa1da782ac98cf078d50c27da1b2aa169b7b6c`
- raw root: `runs/n4-1-policy-a-engine-2026-10-02/` (ignored)
- raw state-machine summary SHA-256 `57f6837a9d25c47445bb82a28e5c267fcb4017d97687574fbec4ee62bf67e1d0`
- raw whole preflight/campaign ledger SHA-256 `fd2d5698e27e82a01ab8213f3f502755df65b3b9f8f026978ab9123e0e6031a9` / `526ebab395c6fa3aea05cdaf7f680696d62a7fef9a66f7fd26ffb0972f21fadf`
- raw small-first preflight/campaign ledger SHA-256 `284ff020e843e183c886131b92fd2b7c39795b2c7708538e5b4e088f03bc442e` / `8912e24976bc7d7dc414a7eddcda67007fa5aeffff989babf017d09fa0bbcb8e`

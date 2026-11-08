# S 4차 — 2026-10-27

**환경 문제로 차단·미완료.** 합성 제약 동등성과 정책 A/B 계산은 완료했다. 그다음 기존 `target/`과 실제 경로 `/Volumes/X9 Pro/zkfdo-target-moved-20261027/target` 모두 접근을 거부했다. `du -sk target/` 및 실제 경로 측정은 exit 1 / `Operation not permitted`, 디렉터리 열기도 errno 1, 읽기·쓰기 접근 검사 모두 false였다(20:49:32 UTC 및 후속 재확인). UID 501과 소유자는 같지만 이 검사만으로 거부의 OS 내부 원인을 확정할 수 없다. 승인된 권한 확장 실행에서도 같았다. 자동 승인 심사의 거절은 아니었다. [원문](../runs/s-round4-2026-10-27/target-access-check.json) · [분리 진단](../runs/s-round4-2026-10-27/target-access-diagnosis.json)

필수 빌드 전후 용량·15 GiB 증가 제한을 확인할 수 없고 기존 target에 쓸 수도 없다. 권한/OS 설정 변경, 다른 target 생성은 이 작업의 허용 범위 밖이므로 Rust/J 구현에 들어가기 전에 중단했다. **새 바이너리 없음, 바이너리 SHA 없음. Cargo fmt/clippy/test 미실행.** J·zkFuzz·기존 프로세스 조작·git 쓰기·설치 없음. 읽기 전용 사전 점검기는 작성했으며 실제 점검 CLI는 요청대로 실행하지 않았다.

## 0. 기준과 격리

디스크 원인 미확인이라는 [진단 결론](codex_disk_usage_2026-10-27.md)에 따라 **이번 재개는 하위 에이전트 없이 수행**했다. 담당 miiz 승인 범위; 기존 상태표/프로토콜 대신 이 새 보고서에 차단 상태를 기록한다.

HEAD `8065e2b7e165ef3f4c1523f240f5d34ecaefdb22`. 작업 전 소스 diff SHA `6ce4103d4de26cc2e9f165d424a0b7384310a83988c0b0dc282885c09b087fcf`, 전체 추적 파일 기준 diff SHA `a9c1552dd4f8dddb1160ba7e3acc90e35f80ef63b51b0b1f9cbddc3f17d4d959`. 작업 트리는 원래 수정 상태였다. 기준은 [base.json](../runs/s-round4-2026-10-27/base.json). 소스 47파일은 시작 해시와 모두 같고 현재 src diff SHA도 같다. 기존 정책/검사 스크립트 4개 해시와 동결 v2.2 엔진 `c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835`를 재확인했다. [preservation-current.json](../runs/s-round4-2026-10-27/preservation-current.json)

전체 최종 diff는 [full.diff](../runs/s-round4-2026-10-27/full.diff), SHA는 [full.diff.sha256](../runs/s-round4-2026-10-27/full.diff.sha256)에 둔다. 보고서 자체를 포함해 자기참조를 피한 것이다. 기존 변경을 담은 tracked diff와 이번 새 파일 추가를 구분해 보존한다.

## 1. 완료한 검증

- 새 감시기 `scripts/s_round4_monitor_20261027.py:74,121,164`: nice 19, 시작 20 GiB/동작 18 GiB, 10초 df, 자신의 신규 process group만 종료, 같은 명령 재시도 1회, 5분 재확인·3시간 한계, 명령별 time -l/RSS·swap·VM·UTC 기록. 기존 target 측정 불가이면 cargo를 거부한다. 누적 내부 출력 2 GB 제한과 외부 582 GiB 보수적 기준도 둔다.
- 새 합성 검사 `scripts/s_round4_synthetic_20261027.py:166,260,297`: **통과**. 직접 태그 main은 예상한 T2051; 나머지 O0/O1 참조·중간 신호 래퍼 4개 컴파일 성공. O0의 복사 등식 6개를 투영한 뒤 두 다항 제약이 같고, O1도 두 제약이 같다. 참조와 래퍼 모두 비이진 입력 2,3을 만족하므로 binary 의미 제약을 추가하지 않았다. 입력·출력 역할/alias도 비교했다. R1CS 4개 보존, 이번 .sym만 비교 직후 제거. [전체 비교](../runs/s-round4-2026-10-27/synthetic/summary.json)
- **한계:** 합성 예제만 증명했다. 실제 대상 표본의 전체 제약 비교 및 새 J 신호 대응 단위 검사는 미실행이다. 기존 3차의 48/48 컴파일 성공은 [원본 summary](../runs/s-tag-wrapper-2026-10-27/compile/summary.json)의 SHA 연결 receipt를 계산 과정에서 재검증하여 재사용했다. 이것을 제약 동등성으로 세지 않았다. 46개 T2051 대상은 그 48개에 포함되며, 새 래퍼를 바꾸거나 대형 대상을 재컴파일하지 않았다.
- 보존: 이번 src 변경 0. [2차 보고서](s_inspection_improve_round2_2026-10-27.md)의 2,732개 차이 0 및 [3차 무태그 1,870개 바이트 일치](../runs/s-tag-wrapper-2026-10-27/prototype-v2/untagged-preservation.json)는 과거 증거다. **이번 신규 엔진으로 산출물을 재생성한 차등 검사는 아니다.**
- Python **41검사 통과**: 합성 7, 계산 15, 고정 정책 B 9, 감시 안전성 5, 사전 점검 5. 실제 프로세스에 신호를 보내지 않는 소유권 거부 검사를 포함한다. 새 Python 5파일 AST 문법 확인. [명령별 결과](../runs/s-round4-2026-10-27/cpu-contention.json)

## 2. 정책 B 결정과 계산

정책은 3차에 고정한 파일 그대로다. **(템플릿 이름, 정의 파일)** 묶음으로 라운드로빈하며, 각 라운드 자체 소스→node_modules/circomlib, 같은 분류에서는 묶음의 최소 제약 수 순서, 묶음 안에서는 제약 수·target_id·label 순서다. 전체 예산 600초/seed, 시도 상한 30초를 유지한다. 전체 순서를 한 번 돈 뒤 반복한다. 고정 SHA `edfc21d7c82353ce01a0b1a83958a7f885cd55ec4e5cb83815cc45f138319076`. 정확한 전체 문장은 [계산 전 보고서 사본](../runs/s-round4-2026-10-27/policy-before-calculation-report.md), 원래 사전 등록은 coverage 입력에 해시로 연결했다.

**B 채택 기준 통과, 실행기 연결은 아직 없음.** 두 단위의 세 seed 모두 B 묶음 수가 A보다 엄격히 많아야 한다고 보수적으로 해석했다. [결정 파일](../runs/s-round4-2026-10-27/policy-adoption.json)은 **RQ-C 매핑을 읽기 전에 저장**했다(`scripts/s_round4_policy_coverage_20261027.py:422`). 결함 위치는 순서와 채택에 사용하지 않았다.

| 시제품 포함 단위 | seed | A 묶음/대상 | B 묶음/대상 | A 기록시간 사용/30초 가정 | B 기록시간 사용/30초 가정 |
|---|---:|---:|---:|---:|---:|
| aq-024 | 2026100601 | 36/79 | 53/53 | 69/10 | 39/14 |
| aq-024 | 2026100602 | 36/78 | 53/53 | 68/10 | 38/15 |
| aq-024 | 2026100603 | 36/79 | 53/53 | 69/10 | 39/14 |
| aq-017 | 2026100601 | 36/85 | 52/52 | 75/10 | 38/14 |
| aq-017 | 2026100602 | 36/84 | 52/52 | 74/10 | 38/14 |
| aq-017 | 2026100603 | 36/85 | 52/52 | 75/10 | 38/14 |

모든 숫자의 대상·준비·컴파일·ledger 파일 경로/SHA와 첫 시도별 비용: [policy-coverage.json](../runs/s-round4-2026-10-27/policy-coverage.json). 2,302,692 bytes를 파일로 써 기존 2 MB 한도 실패를 해결했다(`새 집계기:440`). 현재 컴파일 증거 집합은 aq-024 **933대상/88묶음**, aq-017 **937/88**; 시제품 포함 **954/107**, **958/105**다. 검사 불완전 대상은 컴파일되어도 제외했고 미컴파일 대상의 제약 수를 추측하지 않았다. 현재 컴파일 기준의 도달 묶음 수도 각각 A36/B53, A36/B52로 같으며 대상별 결과는 JSON에 별도 보존했다.

원래 ledger 시도 수는 aq-024 **113/111/113**, aq-017 **115/113/115**, 시간 중앙값은 약 **3.07초**, 최대 약 **30.03초**였다. 동일 target/seed 기록의 최대 wall time을 쓰고, 기록 없는 경우 남은 예산과 30초 중 작은 값, 30초보다 적게 배정된 과거 기록은 검열된 값으로 보수 처리한다. 관측 overrun을 그대로 비용에 넣어 A의 마지막 종료 예상은 **600.23–621.71초**가 될 수 있으나, 여기서 세는 것은 600초 전에 **시작**한 시도다. 시제품 B는 모두 600초. 새 퍼징 성과/완료율/버그 탐지율을 뜻하지 않는다.

| 보고용 RQ-C 템플릿 | 검사 | 현재→시제품 컴파일 | 시제품 기준 A/B 도달(모든 seed) |
|---|---|---|---|
| aq-024 BabyJubJubSubOrderTag | 통과 | 성공→성공 | 예/예 |
| aq-024 RewardsExtended | 통과 | 실패→성공, 532제약 | 아니오/아니오 |
| aq-024 ZoneIdInclusionProver | 통과 | 실패→성공, 390제약 | 아니오/예 |
| aq-024 DataEscrowElGamalEncryption | 미통과 | 실패→성공, 125,529제약 | 제외/제외 |
| aq-024 ZAccountBlackListLeafInclusionProver | 미통과 | 실패→실패 | 제외/제외 |
| aq-017 TrustProvidersKyt | 미통과 | 실패→성공, 39,337제약 | 제외/제외 |
| aq-017 ZSwapV1 | 미통과 | 실패→성공, 374,372제약 | 제외/제외 |

현재 컴파일 집합에서는 aq-024 BabyJubJubSubOrderTag만 A/B 모두 닿고, aq-017 매핑 템플릿은 둘 다 닿지 않는다. 사후 주석 근거는 같은 JSON의 `rqc_availability_report_only`/`rqc_report_only`다.

## 3. J 연결과 마감 뒤 준비

**명시적 target prefix/view를 받는 새 J v2.3 설계를 권고하되 구현하지 않았다.** 단순 S 이름 변경만으로는 J의 직접 main IO(`lifting/mod.rs:1042`), 원시 후보 만족 검사(`:1063`), 전체 suffix 집합 일치(`:1438`)가 보존되지 않는다. 원시 전체 R1CS/alias를 검증한 뒤 target subtree를 투영하고, 새 입력이 없으면 기존 경로를 유지해야 한다. [별도 개정안 초안](s_round4_j_v23_amendment_draft_2026-10-27.md); 동결 프로토콜 수정 없음.

읽기 전용 `scripts/s_round4_preflight_20261027.py:24,78` 작성: 내장 20 GiB(판정기 자체는 15 GiB), 외부 `ceil(1.2×max(60 GiB,실측 peak))+보존분`, 보수적 582 GiB 바닥, 이미지 mount, 무거운 프로세스, target 할당량, 엔진 SHA를 확인한다. peak/보존분을 모르면 준비 완료를 반환하지 않는다. 원래 기준의 소스는 `scripts/n6_a_remeasure_aq_execute_v3_1.py:61,699–705`. 기존 aq 상태나 캐시 내용은 읽지 않는다. 실제 CLI는 미실행, 순수 단위 검사만 통과했다.

마감 뒤 우선순위: **target 접근 복구→증분 측정 가능 확인→v2.3 구현 및 필수 Rust/보존/실제 제약 검사→기존 완료 요청 v2.2/v2.3 재현→고정 manifest의 S만 실행→새 후보만 새 J로 판정**. W 재실행 없음. 뒤의 재현/S/J 스크립트는 검증된 엔진·요청 계약이 없으므로 미작성이다. 임시 스텁을 완성된 실행기로 제공하지 않았다. 이들은 남은 완료 조건이다.

예상 비용(추정): 사전 점검은 보통 수초~수분, 출력 수십 KiB(du 소요는 target 파일 수에 따라 미확정); S만은 리비전당 3 seed라면 **1,800초=30분**의 퍼징 배정에 준비/종료 비용 추가. 실제 manifest의 리비전 수는 아직 읽지 않았으므로 총시간을 계산하지 않았다. 새 J 시간·peak·보존량과 대형 재컴파일 시간은 미측정이며, 실제 값 없이 디스크 통과를 선언하지 않는다.

## 4. 실행 비용·오류 진단

UTC 기록은 로컬 날짜 10/27의 전날 UTC다. 합성 5컴파일 **2026-10-26 20:47:26.630–20:47:27.276**, time -l 최대 RSS **6,242,304–8,241,152 bytes**. 집계 **20:48:30.905–20:48:31.655**, 최대 RSS **526,385,152 bytes(약 502 MiB)**. 집계 전후 내장 여유 **74,190,782,464→74,188,431,360 bytes**. 이 작은 실행에서는 과거 수십 GiB 급감을 재현하지 못했다. 모든 명령의 전후 swap/VM, 10초 표본, UTC/산출물 크기는 [disk-log.tsv](../runs/s-round4-2026-10-27/disk-log.tsv), [cpu-contention.json](../runs/s-round4-2026-10-27/cpu-contention.json). 10초보다 짧은 실행은 시작 표본과 종료 측정만 있다. 판정과 겹친 실행으로 표시한다.

| 실패/진단 | 원인·조치 | 근거 |
|---|---|---|
| 3차 집계 2 MB 제한 | 새 집계기만 새 폴더에 결과 파일 저장, 정책은 불변 | 새 집계기:440, policy-coverage.json |
| 합성 직접 태그 main T2051 | 예상한 음성 대조, 성공으로 세지 않음 | synthetic/direct-tagged-o1/result.json |
| 최종 diff 해시 첫 검사 실패 | git diff만 사용해 기존 미추적 소스 3개가 누락됨. 파일별 47개 해시 동일을 확인하고 세 파일의 명시적 no-index diff를 추가, 기준 SHA와 일치 | diff-format-diagnosis.json |
| target 접근 거부 | 경로·권한 분리 확인도 errno 1. 설정/위치 우회 없이 구현 중단 | target-access-diagnosis.json |
| 감시기 산출물 지표 | 초기 artifact_bytes가 라운드 누적량이었다. 원본 TSV 보존 후 개별 컴파일 bytes와 round_output_bytes 분리 | disk-log-metric-correction.json, monitor:100 |
| Active/BinaryTag 누락 | BlackList 소스 39·42, utils 315–323/874. include closure/함수 수집 개선 필요; 실제 이진 제약을 태그로 대체하지 않음 | 3차 Jdesign.json, targets.rs:2662, inspection_fallback.rs:637 |
| 유한 확장/함수 예산 초과 | escalarmulany 34/43/95, poseidon 147/148/178. 정확한 캐시/의존 분석 필요, 무제한 증액 안 함 | 3차 Jdesign.json, targets.rs:23, compile_time_functions.rs:15 |
| signal alias 미확정 | zAssetChecker 87–90. signal 값을 추측하지 않는 의존 분석 필요 | 3차 Jdesign.json, inspection_fallback.rs:106 |

숨은 결합: 외장 target의 접근 정책·exFAT 할당량과 cargo 안전 기준, aq와 공유하는 내부/이미지 여유 기준, wrapper 신호 계층과 J의 site/IO 식별, inspection 성공과 실제 compile 성공의 차이, 순서 변경 후 과거 target/seed 시간의 적용 한계. 새 산출물이 작아도 동시 메모리/공간 변화 원인은 별도 계측해야 한다.

## 5. 재현과 해시

이번 결과 경로는 재사용해 덮어쓰지 않는다. 아래 명령은 **새 run label/결과 하위 폴더**를 사용한다. 재실행 전 남은 공간 조건을 지켜야 한다. 마감 뒤 실행용 스크립트는 현재 실행하지 않았다.

```sh
nice -n 19 python3 -B scripts/s_round4_synthetic_20261027.py self-test
nice -n 19 python3 -B scripts/s_round4_policy_coverage_20261027.py self-test
nice -n 19 python3 -B scripts/s_round4_preflight_20261027.py --self-test
nice -n 19 python3 -B scripts/s_round4_monitor_20261027.py --label policy-coverage-recheck --timeout 300 -- python3 -B scripts/s_round4_policy_coverage_20261027.py calculate --input runs/s-tag-wrapper-2026-10-27/coverage-input.json --output runs/s-round4-2026-10-27/recheck/policy-coverage.json
```

마감 뒤 사전 점검의 정확한 안전 기본 명령(peak/보존분 미제공이라 항상 보류, 파일·프로세스 변경 없음):

```sh
nice -n 19 python3 -B scripts/s_round4_preflight_20261027.py --engine runs/n6-j4c-2026-10-17.noindex/zkfDO-v2.2 c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835
```

실제 준비 완료 검사는 측정한 정수 byte 값으로 `--peak-bytes`와 `--retained-bytes`를 추가해야 한다. 모르는 값을 0으로 대체하지 않는다.

| 새 코드 | SHA-256 |
|---|---|
| `scripts/s_round4_monitor_20261027.py` | `ea0e085a055adde1a3dcb8e4d3b2bad81eaec2162cea88ccc1027ba4347823cd` |
| `scripts/s_round4_synthetic_20261027.py` | `af9067f3c7004ff6cda75cafddf92480bff29c4be3d0da2c2c44459400186581` |
| `scripts/s_round4_policy_coverage_20261027.py` | `9a563030b51ac19b2edc6244460dd7facaa7e24c43e28e415068168835c9e1d4` |
| `scripts/s_round4_preflight_20261027.py` | `7c8657a2145e2099701fd325d40d1b5aa50350b4db5f14365e33280b4f7b6707` |
| `scripts/s_round4_monitor_test_20261027.py` | `8deea15c4962cfe67b597a7fb9034e4742000cddf6640e66ff8158f0d73669cc` |

보고서·초안·새 결과 파일까지 전부 [new-files-sha256.json](../runs/s-round4-2026-10-27/new-files-sha256.json)에 기록한다(목록 자신의 해시는 별도 .sha256). 전체 diff의 해시 파일도 포함한다.

**확인한 것:** 합성 제약 동등성, 41개 Python 검사, 6개 seed 비교 모두 정책 B 채택 기준 통과, src/고정 정책/동결 엔진 해시 보존, X9 Pro target 접근 거부. 새 J 구현·실제 회로 동등성·새 바이너리·Rust 필수 검사·2,732개 신규 재생성·재현/S/J 실행기 연결은 완료하지 않았다.

**추정한 것:** 명시적 view를 갖춘 v2.3이 적절한 연결 방법이라는 설계 판단, 정책 계산의 미래 실행 도달 범위와 후속 시간/공간 비용. 디스크 급감 원인과 target 접근 거부의 OS 내부 원인은 아직 확정하지 못했다.

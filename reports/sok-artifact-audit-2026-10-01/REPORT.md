# N1 SoK 공개 자료·노출목록 메타데이터 감사

기록일: 2026-10-01 · 담당: miiz · 상태: **메타데이터 감사 완료, N3 결정 대기**

[현재 계획](../../docs/plan_revision_2026-10-01.md), [평가 설계](../../docs/evaluation_plan_2026-10-01.md), [N1 인계](../../docs/handoff_prompts_2026-10-01.md)를 기준으로 작성했다. 전체 사례별 ID·출처·해시·entrypoint 선언·노출 이력·공개 결과는 [evidence-summary.json](evidence-summary.json)의 `cases` 70행에 있다. 신호값·입력값·witness·후보 본문은 포함하지 않는다.

**핵심 결과:** 공통 56건의 zkFuzz TP 교차표는 10/1/3/42로 재확인됐다. 그러나 전체 Circom 모수는 70건이고, 기존 제외목록에 미등재된 진단 5건·3개 저장소를 미노출 평가 세트라고 부를 수 없다. 공개 original entrypoint 선언 56건은 실행 가능성이나 production 사용의 증거가 아니다. 논문/README의 600초, 공개 JSON의 300초, 현재 집계 코드의 600초 상수는 서로 맞지 않는다. **실행 가능한 독립 평가 세트와 실제 과거 실행 제한은 확보·확정하지 않았다.**

## 1. 수행 범위와 보존

공개 요약·자료 설명·메타데이터 생성/집계 코드의 정적 열람, 기존 zkbugs config 메타데이터, 기존 노출·조사·개발 보고서를 대조했다. 후보 소스 추가 조사, 의존성 설치, 컴파일, 퍼징, 후보 재현, 원시 witness/실행 로그 열람은 하지 않았다. 공개 원시 결과 아카이브도 열지 않았다. 집계 스크립트를 실행하지 않았으며, 아래 수치는 공개 JSON의 재집계다.

고정 제외목록·프로토콜·manifest·계약·실행 기록·판정은 변경하지 않았다. 이번 산출물 두 파일과 계획의 N1 행만 이 작업의 수정 범위다. N2의 병렬 작업과 사용자의 기존 미커밋 변경은 보존했다. N3 이후 작업은 시작하지 않았다.

## 2. 출처·버전·해시

공식 SoK 저장소 main을 조회해 **`d1f198143e2f079b7e8207063de557003305aa70`**에 고정했다(커밋 메타데이터 시각 2026-07-13T12:30:19Z). Git tree의 zkbugs gitlink, 현재 로컬 `.external/zkbugs` HEAD, 기존 T2b 기록은 모두 **`a0eed744ba1a816acaa2fae597f4e79b4fd01aea`**로 일치한다. 현재 `dataset/circom`에 git 변경이 없음을 읽기 전용으로 확인했다. SoK zkhydra gitlink는 `6e8cefe0df6b75da05b30486ac85c7cce751bdc7`이다. 이는 연결된 산출물 revision이지 각 공개 실행의 실제 바이너리 provenance를 추가 입증한 것은 아니다.

아래 자료는 2026-10-01 조회했다. 논문은 arXiv v1의 III-B, V, 그림 2·표 IV 관련 범위만 대조했다. 웹 페이지의 bytes SHA-256은 그 조회 사본을 식별하며 영구적으로 같은 HTTP bytes가 반환된다는 보장은 아니다. 전체 조회시각·크기·로컬 문서 18개 해시는 JSON `sources`, 70개 config의 고정 URL·해시는 각 `cases[].metadata_source`에 있다.

| 자료 | URL | 조회 bytes SHA-256 |
|---|---|---|
| `sok_results` | [고정 원문](https://raw.githubusercontent.com/t-sorger/zkp-security-tools/d1f198143e2f079b7e8207063de557003305aa70/surveys/public/dataset/tools-evaluation.json) | `c312473aba64c86f525e5b31279c51edc2b2c3631670b1791db614a72f51df80` |
| `sok_bugs` | [고정 원문](https://raw.githubusercontent.com/t-sorger/zkp-security-tools/d1f198143e2f079b7e8207063de557003305aa70/surveys/public/dataset/bugs.json) | `06428bbb51b7c76040b9ef19fadb215b904fcd3c4ea937e818a6b0a6e843206f` |
| `sok_readme` | [고정 원문](https://raw.githubusercontent.com/t-sorger/zkp-security-tools/d1f198143e2f079b7e8207063de557003305aa70/README.md) | `9ff28cb36e72b9c30854e0c56826c68dbb1a18d4159dc899972ea3448351be97` |
| `sok_summary_builder` | [고정 원문](https://raw.githubusercontent.com/t-sorger/zkp-security-tools/d1f198143e2f079b7e8207063de557003305aa70/surveys/scripts/build_tools_evaluation.py) | `fdcc1a3a5af295c933300e050c08e343803ed194ce086d72aa7c289166fe1482` |
| `sok_figure_builder` | [고정 원문](https://raw.githubusercontent.com/t-sorger/zkp-security-tools/d1f198143e2f079b7e8207063de557003305aa70/surveys/scripts/generate_rq2_figures.py) | `0240a747418b11a1acc0367b188448c735985acf3f6cbb2404652202456ae951` |
| `sok_paper_html` | [고정 원문](https://arxiv.org/html/2607.23752v1) | `8c5beaec330207c61cb07df85a534ba0279d250adc1d39a450e52ff5743c2a09` |
| `sok_git_tree` | [고정 원문](https://api.github.com/repos/t-sorger/zkp-security-tools/git/trees/d1f198143e2f079b7e8207063de557003305aa70?recursive=1) | `7c635e046841f02c50bd1d44768b6b075de5e5d72788a70690191d3ebaec2cb9` |

로컬 제외목록 [exclusions.development.json](../../datasets/exclusions.development.json)의 SHA-256은 `ae1157e00ca4593d21202a5de275c061e3cf9aaaafe08e376707969c35e359d7`로 [T2b preflight](../heldout-survey-2026-09-26/preflight.json)에 고정된 값과 같다. 공개 bugs와 로컬 config의 허용 메타데이터 12필드(`Project`, `Commit`, `Fix Commit`, `Codebase`, 두 Entrypoint, `Location`, `Executed`, 두 Compiled, `Path`, `DSL`)는 70건 모두 일치했다. 취약 소스·수정 소스나 입력값의 일치를 검증한 것은 아니다.

## 3. 전체 분모와 공개 결과

| 층 | 건수 | 해석 |
|---|---:|---|
| 공개 bugs.json 전체 | 139 | 여러 DSL을 합친 자료 목록 |
| Circom 전체 | 70 | 이번 감사의 사례 모수; 직접 config 및 direct 결과와 1:1 |
| 실제 config 사례 경로 접두 / `Project` URL | 27 / 27 | 독립 프로젝트 계열 수는 unknown |
| direct 결과 | 70 | 6개 도구의 결과 행이 모두 존재 |
| original 결과 | 56 | 23개 저장소; direct의 부분집합 |
| 공통 ID / direct에만 있는 ID / original에만 있는 ID | 56 / 14 / 0 | 부재 행을 미탐으로 채우지 않음 |
| original entrypoint 선언 비어 있지 않음 / 빈 배열 | 56 / 14 | 결과 행 존재 여부와 일치; 부재 원인을 설명하지는 못함 |

DSL별 전체 목록은 Circom 70, Halo2 35, Cairo 8, Plonky3 8, Bellperson 7, Arkworks 5, risc0 3, PIL 2, gnark 1이다. 이 전체 139를 Circom 도구 탐지율 분모로 사용하지 않는다.

공통 56개 `id`를 exact join하고 **`tools.zkfuzz.details.ground_truth_match == "TruePositive"`**인 경우만 탐지로 계산했다. 값이 없거나 다른 라벨이면 이 진단 교차표에서는 비TP이며, 상세 판정과 결측은 별도로 보존했다.

| 공통 56건 | 프로젝트 TP | 프로젝트 비TP | 합계 |
|---|---:|---:|---:|
| 격리 TP | 3 | 10 | 13 |
| 격리 비TP | 1 | 42 | 43 |
| 합계 | 4 | 52 | 56 |

프로젝트만 TP인 1건은 `Unirep/Unirep/veridise_underconstrained_circuit_allows_invalid_comparison`이다. 여기서 TP는 **SoK 공개 정답 일치 라벨**이며, 우리 평가 설계의 같은 원인 검토나 프로젝트 속성 위반 확인을 새로 통과했다는 의미가 아니다.

| zkFuzz 범위 | vulnerable | safe | timeout | error | GT TruePositive | GT FalseNegative | GT 결측 |
|---|---:|---:|---:|---:|---:|---:|---:|
| direct 전체 70 | 25 | 16 | 25 | 4 | 25 | 16 | 29 |
| direct 공통 56 | 13 | 16 | 23 | 4 | 13 | 16 | 27 |
| original 전체=공통 56 | 4 | 12 | 36 | 4 | 4 | 12 | 40 |

42건을 모두 확정 FalseNegative 또는 안전한 회로라고 부르면 안 된다. 이 42건의 `(direct verdict, original verdict)`는 `(timeout,timeout)` 19, `(safe,timeout)` 9, `(safe,safe)` 7, `(timeout,safe)` 3, `(error,error)` 3, `(error,timeout)` 1이다. 오류·시간초과를 제외하지 않았다. direct-only 14건에는 TP 12와 timeout 2가 있으며, original 결과가 없으므로 두 모드 비교에 넣지 않는다.

[그림 집계 코드](https://github.com/t-sorger/zkp-security-tools/blob/d1f198143e2f079b7e8207063de557003305aa70/surveys/scripts/generate_rq2_figures.py#L95-L105)는 `vulnerable` **그리고** `TruePositive`를 요구한다. 이번 고정 JSON에서는 모든 도구의 TP 라벨이 vulnerable verdict와 함께 나타나므로 TP-only와 이 stricter predicate의 양성 집합은 같다. 그렇다고 일반적으로 verdict를 TP로 대체할 수는 없다.

| 도구 | direct vulnerable / TP | original vulnerable / TP |
|---|---:|---:|
| Picus | 10 / 10 | 0 / 0 |
| Civer | 20 / 12 | 4 / 1 |
| Ecne | 30 / 25 | 8 / 7 |
| Circomspect | 10 / 0 | 13 / 1 |
| zkFuzz | 25 / 25 | 4 / 4 |
| ConsCS | 11 / 11 | 1 / 1 |

전체 도구 중 하나라도 TP인 사례는 direct 32/70, original 11/56이다. 공통 56에서 **도구 전체** 교차표는 격리만 14, 프로젝트만 5, 양쪽 6, 양쪽 비TP 31이다. 따라서 14는 zkFuzz 격리 단독 수가 아니다. 도구별 TP 합 83/14는 같은 사례를 중복해서 세는 값이며 고유 사례 32/11과 구분한다. `source.snapshot_summary`의 processed/errors와 tool별 verdict 오류도 서로 다른 층의 통계다.

## 4. ID 매핑·결측·중복

서로 다른 네 식별자를 보존했다: **실제 config 디렉터리의 사례 경로**, 요약 `id`, 요약 `website_bug_id`/bugs `Id`, bugs `Project`. 사례 basename은 요약 `id`와 70/70 일치하고, `website_bug_id → Id`는 exact 1:1이다. 두 모드의 같은 `id`는 같은 website ID로 연결된다. ID/행 중복, join 결측은 없다. 원인 의미상 중복이 없다는 증명은 아니다.

- `website Id`와 실제 사례 경로가 다른 것은 **26건**이다. 공개 `Path`는 **10건 누락**(Self 8, Tangle 1, iden3/circuits 1); 이 중 9건은 original에 존재한다. 누락 시 공개 Id와 로컬 config Id의 exact 일치 및 실제 디렉터리 경로를 근거로 연결하고, public Path 자체는 null로 남겼다.
- MACI `Path`의 `hashcloak_Data...`와 실제 디렉터리/요약 `id`의 `hashcloak_data...`에 대소문자 불일치 **1건**이 있다. 자동 소문자화로 숨기지 않았다.
- Telepathy의 한 `website Id` 접두는 `succinctlabs/telepathy-contracts`지만 `Project`와 실제 사례 경로는 `succinctlabs/telepathy-circuits`다. 이는 이 행의 메타데이터상 별칭 대응이며 두 repo의 모든 코드가 동일하다는 판단이 아니다. `Id` 앞 두 구간만으로 세면 28개 문자열이 나오므로 이를 28개 프로젝트라고 부르거나 그대로 노출목록을 비교하면 오분류할 수 있다.
- Telepathy 두 진단 사례의 website suffix는 `veridise-V-SUC-VUL-001`, `veridise-V-SUC-VUL-002-simplified`, Spartan 진단 사례는 `yacademy-high-03`이다. 실제 사례 경로 suffix와 바꿔 쓰지 않았다.
- `Fix Commit`은 40자리 hash 36, 빈 값 20, 짧은 hash 12, URL 1, 배열 1이다. 자동으로 단일 유효 패치 revision으로 해석하지 않았다. Reclaim XOR는 `Commit == Fix Commit`이라는 메타데이터가 있어 취약·수정 쌍으로 자동 취급할 수 없다.
- zkopru OwnershipProof의 `Codebase`는 `dataset/codebases/circom/tag/audit-v1/...`로 Project 경로와 다른 형식이다. 실제 경로 유효성은 unknown이다.

original 56개 행을 `(Project, Commit, Original Entrypoint)`로만 묶으면 **36개 잠재 단위**(단독 26, 중복 그룹 10)다. 중복 그룹 크기는 2행×4, 3행×4, 4행×1, 6행×1이며 JSON에 구성 ID 전부를 기록했다. 설정·패치·입력 계약의 동일성은 확인하지 않았으므로 36을 확정 실행 단위 수라고 부르지 않는다. 동일 실행에 연결된 여러 정답 사례에 예산을 반복 부여하지 않도록 N3/N5에서 설정까지 포함한 단위를 정해야 한다.

## 5. 프로젝트 목록과 계열의 확인 수준

다음 표의 저장소는 config 경로와 `Project`가 가리키는 단위다. “직접 제외”는 09-24 목록의 사례 행 수이며 후속 노출을 반영한 최신 등급이 아니다. 격리만 TP는 공통 56 내 진단 수다.

| 저장소 | 전체 사례 | original 행 | 기존 repo 제외 | 기존 직접 제외 | 격리만 TP |
|---|---:|---:|---|---:|---:|
| `0xbok/circom-bigint` | 1 | 1 | 예 | 1 | 0 |
| `Arianee/arianee-sdk` | 2 | 2 | 아니오 | 0 | 0 |
| `Moonsong-Labs/zksync-social-login-circuit` | 2 | 2 | 예 | 1 | 0 |
| `Rate-Limiting-Nullifier/circom-rln` | 1 | 1 | 아니오 | 0 | 0 |
| `Unirep/Unirep` | 2 | 2 | 예 | 2 | 0 |
| `aptos-labs/keyless-zk-proofs` | 1 | 1 | 예 | 1 | 1 |
| `banyancomputer/hot-proofs-blake3-circom` | 1 | 1 | 예 | 1 | 0 |
| `darkforest-eth/darkforest-v0.3` | 1 | 1 | 아니오 | 0 | 0 |
| `iden3/circomlib` | 9 | 0 | 예 | 2 | 0 |
| `iden3/circuits` | 1 | 0 | 아니오 | 0 | 0 |
| `inference-labs-inc/subnet-2-circom` | 2 | 2 | 예 | 2 | 0 |
| `pantherfoundation/panther-core` | 12 | 12 | 아니오 | 0 | 2 |
| `personaelabs/spartan-ecdsa` | 3 | 3 | 아니오 | 0 | 1 |
| `privacy-scaling-explorations/maci` | 1 | 0 | 아니오 | 0 | 0 |
| `rarimo/passport-zk-circuits` | 1 | 1 | 예 | 1 | 1 |
| `reclaimprotocol/circom-chacha20` | 3 | 0 | 예 | 3 | 0 |
| `selfxyz/self` | 8 | 8 | 예 | 2 | 1 |
| `semaphore-protocol/semaphore` | 1 | 1 | 아니오 | 0 | 0 |
| `sismo-core/hydra-s2-zkps` | 1 | 1 | 아니오 | 0 | 0 |
| `siv-org/verifiable-private-overrides` | 2 | 2 | 예 | 1 | 0 |
| `succinctlabs/telepathy-circuits` | 6 | 6 | 예 | 2 | 2 |
| `tangle-network/protocol-solidity` | 1 | 1 | 예 | 1 | 0 |
| `worm-privacy/proof-of-burn` | 1 | 1 | 아니오 | 0 | 0 |
| `zkemail/ether-email-auth` | 1 | 1 | 아니오 | 0 | 0 |
| `zkemail/zk-email-verify` | 2 | 2 | 예 | 2 | 0 |
| `zkemail/zk-regex` | 2 | 2 | 아니오 | 0 | 2 |
| `zkopru-network/zkopru` | 2 | 2 | 아니오 | 0 | 0 |

계열 독립성은 **unknown**으로 보존했다. [별도 B 초안](../../datasets/exclusions.injection-eval.draft.json)은 다음의 과거 열람 repo들을 함께 기록하지만, B 초안의 fork/parent·byte 동일성 제외 규칙을 이번 N3 결정으로 자동 상속하지 않는다.

| 관련 이름 | 현재 근거 | 아직 확정하지 않은 것 |
|---|---|---|
| darkforest-v0.3 / darkforest-eth/circuits | 기존 T2b 패치 이력에 후속 저장소가 등장 | 전체 코드 계열·평가 독립성 경계 |
| pantherfoundation / pantherprotocol / vkonst의 panther-core | 기존 조사에서 canonical/대체 repo를 연 기록 | 모든 revision·원인의 동일성, alias와 fork의 정확한 경계 |
| personaelabs / yAudit / zBlock-1의 spartan-ecdsa | 기존 확장 조사에서 패치·fork 경로 검토 | 독립 계열로 셀 수 있는 범위 |
| zkemail의 verify / regex / ether-email-auth | 같은 조직, 별개의 Project URL | 공유 코드·루트 원인 계열 및 노출 전이 |
| iden3의 circomlib / circuits | 같은 조직, 별개의 Project URL | 공유 라이브러리·원인 계열 및 노출 전이 |

같은 조직을 곧 같은 계열로 합치지 않았고, URL이 다르다는 이유로 독립 계열이라고도 선언하지 않았다. 공개 메타데이터만으로 전체 공유 라이브러리·fork 계보를 확정할 수 없다.

## 6. 기존 제외목록과 후속 노출

[09-24 제외목록](../../datasets/exclusions.development.json)은 직접 사례 **22건(executed 8, prepared 8, inspected 6)**, 프로젝트 **14개(development 6, surveyed 8)**다. 이 규칙을 T2b 70건에 적용한 과거 단계 0 제외는 **41건 = 직접 22 + 같은 프로젝트의 다른 원인 19**다. 19건을 모두 직접 소스 열람이라고 분류하지 않았다.

나머지 29건을 미노출이라고 부를 수 없다. [기존 T2b 기록](../heldout-survey-2026-09-26/SURVEY.md)에는 70건 전체의 메타데이터 조사, source/patch 단계 16건, entrypoint 검토 단계 5건, 컴파일·탐색 단계 2건, 별도 확장의 patch 검토 7건이 있다. 단계들은 중첩되므로 합산하지 않는다. Panther의 패치 확보 실패 7건은 프로젝트를 연 이력과 개별 원인 소스를 직접 읽은 사실을 구분해 후자를 unknown으로 두었다. T2b의 0건 통과는 당시 고정한 기준의 결론이며 이번 계획의 적격성 판정을 대신하지 않는다.

[P2](../dev-rq1-pilot-2026-09-29/README.md) 이후 inference Clamp는 inspected→executed, zk-email FpMul은 prepared→executed라는 후속 이력이 생겼다. 기존 제외목록을 고치지 않고 JSON에 별도 열로 기록했다. [T6a](../t6a-compile-reuse-2026-09-26/REPORT.md)의 프로젝트 준비·탐색 이력을 모든 원인의 직접 실행으로 확대 해석하지 않았다.

기존 제외 및 후속 opened/examined 목록에는 27개 저장소 중 **25개**가 등장한다. `sismo-core/hydra-s2-zkps`, `zkemail/ether-email-auth`는 검토한 이력에서 metadata-only로 남지만, 소스 열람 기록을 찾지 못했다는 것이 never-exposed 보장은 아니다. N1에서는 모든 70건의 공개 결과·메타데이터를 보았으므로 결과 지식 노출도 새로 기록했다.

### 격리만 TP인 10건: 진단 하위집합

전체 70/공통 56의 분모를 유지한 채 진단용으로만 아래를 제시한다. 성공 사례만 주 집합으로 택하거나, 회복 가능한 최대치라고 해석하지 않는다.

| 실제 사례 ID | original verdict | 09-24 제외목록 | 후속 노출·확인 수준 |
|---|---|---|---|
| `aptos-labs/keyless-zk-proofs/koukyosyumei_unconstrained_base64_decoded_len` | `error` | 직접 prepared | 기존 제외 유지; 직접 노출과 계열 노출은 별도 |
| `pantherfoundation/panther-core/veridise_fortxreward_abstracted_away_in_reward_calc` | `safe` | 미등재 | 원인 metadata-only; 같은 Panther 프로젝트 opened |
| `pantherfoundation/panther-core/veridise_zone_id_inclusion_prover_bypass` | `safe` | 미등재 | T2b provenance 시도; 개별 소스 열람 unknown |
| `personaelabs/spartan-ecdsa/yacademy_under_constrained_circuits_compromising_the_soundness_of_the_system` | `timeout` | 미등재 | T2b extension01 공개 패치 검토 |
| `rarimo/passport-zk-circuits/koukyosyumei_under_constrained_date_encoder` | `timeout` | 직접 prepared | 기존 제외 유지; 직접 노출과 계열 노출은 별도 |
| `selfxyz/self/zksecurity_the_registration_and_disclosure_circuits_lack_range_checks_for_the_input_indices` | `timeout` | 프로젝트만 제외 | 기존 제외 유지; 직접 노출과 계열 노출은 별도 |
| `succinctlabs/telepathy-circuits/veridise_arrayxor_is_under_constrained` | `timeout` | 직접 prepared | 기존 제외 유지; 직접 노출과 계열 노출은 별도 |
| `succinctlabs/telepathy-circuits/veridise_template_CoreVerifyPubkeyG1_does_not_perform_input_validation_simplified` | `timeout` | 직접 prepared | 기존 제외 유지; 직접 노출과 계열 노출은 별도 |
| `zkemail/zk-regex/matterlabs_email_spoofing_via_manipulated_from_header` | `timeout` | 미등재 | T2b source·entrypoint 검토; production 근거 미확인 |
| `zkemail/zk-regex/matterlabs_fromaddrregex_allows_email_address_spoofing` | `timeout` | 미등재 | T2b source·entrypoint 검토; production 근거 미확인 |

기존 repo 제외목록 미등재는 정확히 **5건·3개 저장소(zk-regex 2, Panther 2, Spartan 1)**다. zk-regex 두 건은 `stage02`·`stage03` 소스/entrypoint 검토, Spartan은 `extension01` 패치 검토가 기록돼 있다. Panther FortxReward는 개별 원인 metadata-only 및 같은 프로젝트 opened, Zone ID는 provenance 시도와 패치 미확보이며 개별 소스 열람은 unknown이다. JSON 각 `exposure.evidence`에 파일·행을 연결했다. 이 다섯 건은 미노출·적격 평가 집합이 아니다.

## 7. Entrypoint·루트·지원 범위

공개 `Direct Entrypoint`는 70건 모두 `circuit.circom`이고, `Original Entrypoint`는 56건에서 각각 경로 하나, 14건에서 빈 배열이다. [README](https://github.com/t-sorger/zkp-security-tools/blob/d1f198143e2f079b7e8207063de557003305aa70/README.md)는 direct를 해당 결함의 격리 wrapper, original을 프로젝트 entrypoint로 설명한다. N1은 그 선언을 기록했으며 각 파일의 실제 main·호출 구조·production 연결을 새로 열어 확인하지 않았다. `generated`, `test`, `main` 같은 이름만으로 production/단일 템플릿 여부를 확정하지 않았다.

`Compiled Direct`와 `Compiled Original`은 **모두 70/70 true**다. original entrypoint가 없는 14건까지 original compiled=true이므로 이 flag를 준비 성공률로 사용하면 안 된다. 동일 revision의 공개 config 선언이며 현재 환경의 성공을 의미하지 않는다. 14건은 circomlib 9, Reclaim 3, MACI 1, iden3/circuits 1이다.

기존 근거는 새 조사와 구분해 재사용했다.

- [T2b stage03](../heldout-survey-2026-09-26/stage03.json)는 Worm의 실제 production 산출물 연결 미확인, zk-regex 두 건의 test-only 호출 경로와 production 연결 미확인을 기록한다. 새 source inspection으로 확인한 사실로 표현하지 않았다.
- 같은 기록은 zkopru의 production impl entrypoint 16개에서 ERC20 사례가 root `ZkTransaction`, OwnershipProof 사례가 child라고 보고한다. **이는 그 16개 entrypoint에 대한 과거 근거**다. 특히 공개 OwnershipProof original은 별도 tester 경로이므로 이 child 판정을 공개 경로에 자동 이전하지 않았다. JSON의 public-original root 상태는 unknown, historical root/child는 별도 필드다.
- [T2b stage04](../heldout-survey-2026-09-26/stage04.json)는 그 16개가 고정 Circom 2.2.3에서 옛 구문으로 컴파일 실패하고 탐색도 incomplete였다고 기록한다. `n_p:null`이며, 타깃이 0개라고 결론 내리지 않는다. SoK의 compiled flag와 로컬 기록은 환경·entrypoint 범위가 달라 직접 모순이라고 단정하지 않는다.

현재 외부 의존성 가용성, 지원 문법, main template, 실제 호출 도달성, 자동 구성 성공, 설정 동일성은 N1에서 새로 검증하지 않았다. JSON은 현재 상태를 unknown으로 둔다. 과거 실패·미지원·production 미확인 기록을 삭제하거나 현재 성공으로 바꾸지 않는다.

## 8. 600초/300초 및 집계 provenance

| 자료 | 확인한 내용 | 해석 |
|---|---|---|
| [SoK v1 III-B](https://arxiv.org/html/2607.23752v1#S3.SS2) | 도구당 600초 설명 | 논문의 방법 기술 |
| [README](https://github.com/t-sorger/zkp-security-tools/blob/d1f198143e2f079b7e8207063de557003305aa70/README.md#L85) | 예시 timeout 600, per-tool seconds 설명 | 재실행 안내이지 보존 run 설정의 증명은 아님 |
| 공개 tools-evaluation.json | `timeout_seconds: 300` | 공개 요약 메타데이터 |
| [동일 revision builder](https://github.com/t-sorger/zkp-security-tools/blob/d1f198143e2f079b7e8207063de557003305aa70/surveys/scripts/build_tools_evaluation.py#L605-L623) | `timeout_seconds`에 **600 상수** 대입 | 실행 설정에서 추출하지 않음; 현재 JSON과 불일치 |

현재 공개 JSON의 생성에 정확히 어떤 builder revision/후처리/실행 설정을 사용했는지 연결할 자료가 확인되지 않았다. **실제 제한이 300초 또는 600초였다고 확정하지 않는다.** 런타임 길이만 보고 어느 값을 사용했다고 추정하지도 않았다. 이를 해결하려면 보존된 실행 invocation/config와 결과·집계 revision의 대응 증거가 필요하며, 이번에는 원시 로그/아카이브를 열지 않았다.

JSON `generated_at=2026-06-10T11:15:45+00:00`, `run_timestamp=2026-06-10T11:15:26+00:00`이다. 현재 builder는 전자를 집계 생성시각, 후자를 `summary.json` **파일 mtime**에서 얻는다. 후자를 실제 실험 시작시각이라고 해석하지 않았다. builder는 `ground_truth_match`를 기존 evaluation status에서, `execution_time_s`를 기존 results execution_time에서 복사한다. 이 값들로 후보 생성시각을 새로 확정하지 않는다.

[README의 집계 설명](https://github.com/t-sorger/zkp-security-tools/blob/d1f198143e2f079b7e8207063de557003305aa70/README.md#L116-L134)은 raw results→summary builder→공개 JSON→figure builder의 흐름을 제시한다. figure builder의 error/timeout/FN 분류와 공개 mode.summary의 verdict 빈도는 별도다. builder는 ground_truth 파일 없는 디렉터리를 건너뛰고 도구 자료가 없으면 missing으로 표시하는 경로도 갖지만, 현재 공개 70/56 행에는 tool verdict missing이 없다. 현재 14개 original 부재 각각의 발생 원인을 이 일반 경로만으로 확정하지 않는다.

추가 불일치도 보존했다. 논문 III-B는 project 미실행 일부를 stale code/dependency로 설명하고 README는 direct와 같은 original의 생략 정책을 설명한다. 실제 메타데이터에는 그 14개의 original entrypoint가 비어 있어 개별 부재 사유는 unknown이다. 논문 V의 Civer isolated TP 20 서술은 공개 JSON TP12·vulnerable20 및 그림2의 TP12와 맞지 않는다. 또한 assigned-but-unconstrained project 결과는 본문 20%와 표 IV의 2/5=40%가 다르다. 어느 것도 원시 실행을 재판정하거나 기존 공개 결과를 수정한 것이 아니다.

## 9. N3에서 결정할 사항

1. **주 분모·포함 규칙:** 70 전체, original 선언이 있는 56, 지원 가능한 부분집합을 어떤 관계로 보고할지 정한다. 격리 TP 여부로 주 집합을 고르지 않고, original 부재·준비 실패·미지원·미판정을 분모에서 숨기지 않는다.
2. **노출 단계와 계열:** 09-24 직접/프로젝트 제외, T2b metadata/source/provenance/compile, P2 실행, 이번 공개 결과 지식을 구분한다. 5건·3repo를 미노출로 복원하지 않는다. Telepathy ID alias와 Darkforest/Panther/Spartan 관련 repo, 조직·공유 라이브러리 관계의 노출 전이 규칙은 새 결정으로 남긴다.
3. **실행 단위와 entrypoint 정책:** `(프로젝트, commit, entrypoint, 설정)`의 중복 제거, 여러 정답 원인에 대한 예산 공유, test/generated/production entrypoint 포함, root 원인과 child 원인의 처리, 패치 없는 사례의 사용 여부를 정한다. 36개 잠재 tuple을 확정 단위로 채택하지 않는다.
4. **최소 개발·지원 범위와 중단 기준:** 기존 옛 문법·의존성·entrypoint 실패의 어떤 부분을 개발 자료에서만 다룰지 N2와 함께 결정한다. 미확인 항목을 풀 추가 source 조사도 새로 범위를 정한 후 수행한다. N1 결과는 추가 소스 개봉·컴파일·퍼징 허가가 아니다.
5. **평가 규모와 주장:** 실제 독립 계열·원인이 부족하면 사례연구·적용성 분석으로 범위를 좁힌다. 기존 “원인 5개·프로젝트 3개” 목표나 seed 반복으로 독립성을 대신하지 않는다. 같은 원인 귀속·동일 검토 수준·컴포넌트/프로젝트 확인 구분은 유지한다.
6. **N5로 넘길 고정 항목:** 시간 설정 provenance 미해결을 명시하고 우리 예산을 독립적으로 정한다. 준비·컴파일·캐시·탐색·맥락 판정·수동 검토의 비용, 대표 순서, seed/동시 실행, 실패·재시도·unknown 처리, 자료·도구 해시를 사전에 고정한다. SoK 과거 수치를 우리 환경의 직접 기준선으로 대체하지 않는다.

## 10. 재계산 절차와 로컬 검증

1. §2의 고정 URL을 받아 SHA-256을 대조한다. `bugs.json`은 `DSL == Circom`만 취하고, 입력·설명·명령 대신 위 허용 필드만 읽는다. 로컬 zkbugs는 지정 revision과 clean metadata인지 확인하고 **config JSON만** 열거한다.
2. config 부모의 `dataset/circom` 상대 경로를 사례 ID로 둔다. 그 basename과 요약 `id`가 유일하게 일치하는지 확인한다. 요약 `website_bug_id`와 공개 bugs `Id`, 로컬 config `Id`를 exact join한다. 공개 `Path` 결측/대소문자 차이는 별도 flag로 남긴다. 이름만으로 수정·alias 확장하지 않는다.
3. direct/original 각각 ID 중복을 확인하고 교집합·차집합을 먼저 계산한다. 각 도구 `verdict`, `details.ground_truth_match` 존재 여부, execution_time 유무를 보존한다. TP 판정은 아래 식이며 부재 행의 탐지값은 **null**로 둔다.

```text
D = {row.id: row for row in modes.direct.bugs}
O = {row.id: row for row in modes.original.bugs}
common = keys(D) intersection keys(O)
TP(row, tool) = row.tools[tool].details.get("ground_truth_match") == "TruePositive"
count[(TP(D[id], zkfuzz), TP(O[id], zkfuzz))] += 1, for id in common
```

4. 전체 도구 교차표는 도구별 `vulnerable AND TP`의 논리합으로 별도 계산한다. `mode.summary`의 vulnerable 개수나 `snapshot_summary.evaluation_counts` 합계를 고유 사례 수로 대체하지 않는다.
5. 노출은 실제 사례 ID를 `exclusions.cases[].zkbugs_case`에 exact join하고 `Project` URL의 GitHub owner/repo를 제외목록 프로젝트와 대조한다. 이번 자료에서는 config 디렉터리의 repo 접두와 `Project`가 모두 일치한다. 직접 제외, 같은 repo만 제외, 후속 단계·개발 노출을 별도 열로 보존한다. unknown을 미노출로 치환하지 않는다.
6. 진단 집합은 common 중 direct TP이고 original 비TP인 경우다. 여기에 기존 repo 제외만 적용한 5/3 수치를 재현하되 이력을 덧붙인다. family는 확정 없는 추론을 하지 않는다. original 경로 목록을 펼쳐 `(Project, Commit, path)`로 잠재 중복만 점검한다.
7. JSON 구문, 70/56/14 분모, 27/23 프로젝트 수, 4칸 교차표 합, 사례별 참조·해시와 집계, 로컬 보고서 링크, 변경 범위를 확인했다. 독립 재집계도 10/1/3/42 및 명목상 5건·3repo와 일치했다. 코드 변경이 없으므로 cargo fmt/clippy/test나 회로 도구는 실행하지 않았다.

이 감사의 완료는 메타데이터·불일치·unknown을 재현 가능한 형태로 남겼다는 뜻이다. N3의 범위 결정, N5 프로토콜 고정, 실행 가능한 독립 평가 세트 확보를 완료했다는 뜻은 아니다.

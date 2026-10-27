# N6-B6c: panther 준비 실패 원인과 동치 관문 결과

작성: 2026-10-20 KST. [지시 전문](../runs/handoff/n6_b6c_instruction_2026-10-19.md)의 SHA-256은 `7ab08c1cb6dc024cabc3f8eed33bde35fbd992461280a5661e60225a4cf8a739`이다. **V1·V2를 입증하지 못했고, 요청된 엄격한 V3 스테이징도 구성할 수 없어 새 B 요청 index·시범 명령·전체 실행 명령을 만들지 않았다.** 기존 출력과 고정 엔진·판정 규칙·형식 검사는 보존했다. B 판정 값·후보 값·witness 값·J 작업 폴더 내용 열람은 0건이며 J 시범·전체 실행도 0건이다.

## 1. 읽은 기록과 범위

경로는 저장소 루트 기준이다. B `result.json`에서는 허용된 `preparation.status/reason/detail`과 실패 단계 이름만 추출했다. 결과 파일의 SHA 계산은 내용을 화면에 출력하지 않는다.

| 기록 | 경로 | SHA-256·허용 관측 |
| --- | --- | --- |
| B6b 새 시범 단계 | `runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/stages/pilot-v2.2/state.json` | `657d26438403b770c1904d27a377b55834b460472658605996a491f3bc1fc4b0`; `failed`, ValueError |
| B6b 새 시범 상태 | `runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/pilot-v2.2.noindex/state.json` | `7ba9188116e4be4a2247da8c6326f7c6e66329bc2581982d2375b4fe280aecfa`; `stopped`, RunnerError |
| queue 9 Vota 결과 | `runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/pilot-v2.2.noindex/requests/00-000009/lift/result.json` | `96a8d4c4e91b41dad07fa60bae52bc4e79d904fa22d6f4939cbd678aa5d150e8`; 형식 검사 통과 |
| queue 25 panther 결과 | `runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/pilot-v2.2.noindex/requests/01-000025/lift/result.json` | `c22c2a420134d4ea4d24ba256ab855a6c5b9ceffea4c03bbfa634736007e1001`; `preparation_failure/template_ambiguous`, `instance main: 95 templates declare its signal names`; 실패 `site_discovery / plan hint rewrites` |
| A 원본 요청 index | `runs/n6-j1-2026-10-09.noindex/request-index.json` | `35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c` |
| A v1 실행 상태 | `runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json` | `6bfeb70743608235bbf9d7125f84c2aadf2fd8d9e95a461de8a9572411cb0e73` |
| A v2.2 요청 index | `runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/request-index-v2.json` | `d1102d837e5d78116cb44a2b67f5a9796f57bbc2a6733d712205eb1d528ceed8` |
| A v2.2 실행 상태 | `runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/j-execute.noindex/state.json` | `fa1da116b317d7833a60bec52826c2119a79f50dbec27616f4cbce2932a8a1f6` |
| A strict 요청 index·실행 상태 | `runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/prepared/strict-request-index.json` 및 `strict-j/state.json` | index `c8f8f1aa9b12a953b78685bafda49d7afe02edf2b0c2c27016dd2d71eee0f362`; state `e62a28db4f994995b3e063dd48daf86cee4ec63cccbbefdc1bb80f5e593072bb` |
| A constructed 요청 index·실행 상태 | `runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/prepared/constructed-request-index.json` 및 `constructed-j/state.json` | index `ebf7fa598fc1ddb4fd9f8e42e7376ab5e99429ccc4ff110c3b83df72151c5fe5`; state `5625b73a5e52b5a9802447089a4faf7e283c40df811f0e9f4cbd9b0fd7c0f55f` |
| B6b 요청 index | `runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/request-index-v1.json` | `1bfcb71d728fe77ccdec0e8897a5a085ea9d286ed658ea160f6cc9fe1fe83b65` |

B6b 시범에서 v2.2 queue 9는 wall `105.940235`초·최대 RSS `11,685,986,304`바이트였고 queue 25는 위 준비 오류에서 멈췄다. v1 새 시범은 시작되지 않았다.

## 2. `template_ambiguous`의 정확한 원인

고정 v2.2 소스 `8065e2b7e165ef3f4c1523f240f5d34ecaefdb22:src/candidate_review/lifting/mod.rs:622-645`, 고정 v1 소스 `cb40e3e06c27bfed2dcb19245f5d6b82d1860404:src/candidate_review/lifting/mod.rs:616-639`는 `source_root` 아래 전체를 템플릿 탐색 대상으로 삼지 않는다. wrapper와 entrypoint 각각에 `targets::discovery_dependency_paths`를 적용한 **include 닫힘의 합집합**만 읽고 `parse_templates`로 선언을 모은다. `targets.rs:989-1035,2923-2967,3015-3043`은 canonical path를 쓰고 include 파일의 부모, 프로젝트 루트, 기존 `-l` 경로 순으로 해석한다. v1·v2.2의 `targets.rs`와 `lifting/source.rs` blob은 같다.

v2.2 `lifting/mod.rs:1120-1200,1261-1374`, v1 `:1104-1184,1226-1339`의 hint 계획은 인스턴스의 선언 신호 이름 집합과 같은 템플릿을 찾는다. `main`이 여러 템플릿과 맞으면 wrapper의 `component main` 템플릿 이름으로 유일성을 다시 검사한다. panther queue 25의 `main`은 `{in, out}`이며 wrapper의 이름은 `Montgomery2Edwards`다. 두 다른 canonical 파일에 같은 이름·내용의 선언이 하나씩 있어 tie-break가 2개를 남긴다. 실제 엔진의 준비 실패 메타데이터에 기록된 95개는 이 신호 집합과 일치하는 **선언 수**다.

| 경로 계통의 파일 | `{in,out}` 선언 수 |
| --- | ---: |
| 원본 clone `circuits/node_modules/circomlib/circuits/montgomery.circom` | 2 |
| 스테이징 `project/circuits/circuits/templates/trustProvidersMerkleTreeLeafIDAndRuleInclusionProver.circom` | 1 |
| 스테이징 `project/circuits/circuits/templates/utils.circom` | 73 |
| 스테이징 `project/circuits/node_modules/circomlib/circuits/binsum.circom` | 1 |
| 스테이징 `project/circuits/node_modules/circomlib/circuits/bitify.circom` | 5 |
| 스테이징 `project/circuits/node_modules/circomlib/circuits/comparators.circom` | 5 |
| 스테이징 `project/circuits/node_modules/circomlib/circuits/gates.circom` | 2 |
| 스테이징 `project/circuits/node_modules/circomlib/circuits/montgomery.circom` | 2 |
| 스테이징 `project/circuits/node_modules/circomlib/circuits/poseidon.circom` | 4 |
| **합계** | **95** |

두 `montgomery.circom` 파일의 SHA-256은 모두 `63692077f57f4467960b172830abbeb4dfafdc3744cde6863433cccea7f0f2bf`다. 원래 B6 queue 25의 닫힘은 wrapper 2파일, entrypoint 34파일, 합집합 35파일이며 `{in,out}` 선언 93개와 `Montgomery2Edwards` 선언 1개였다. B6b에서는 wrapper 2파일, entrypoint 34파일, 합집합 **36파일**·선언 **95개**·같은 이름 선언 **2개**가 됐다. [소스만 읽은 재현 근거](../runs/n6-b6c-2026-10-19.noindex/panther-closure-evidence.json)(SHA-256 `2f1af468c730c59f7b9656c28f0cebf101aec39f0b16f2d75988001535f19d5b`)는 36파일 각각의 경로·SHA, 선언 9파일 분포, 두 중복 경로를 기록한다. [재현기](../runs/n6-b6c-2026-10-19.noindex/panther-source-probe.py)의 SHA-256은 `46c1ad44abeaf25fafbc7d56ec7815978ce83f9a4ef25170dc0d78922565d7ec`이다. 소스 분석으로 얻은 닫힘이며 OS 수준의 Circom 파일 열람 추적은 하지 않았다.

B6b의 **panther 이 요청** 스테이징에는 `.circom`이 183개(프로젝트 181·wrapper 2)다. 지시서의 473개는 B6b의 17쌍 중 다른 쌍의 최대치다. B6b 생성기 `scripts/n6_j3_b_requests.py:44-109,182-194`는 프로젝트·wrapper의 `.circom` 사본을 요청별 root에 둔다. 그러나 엔진은 위 36파일만 템플릿 파서에 넣는다. 따라서 나머지 파일을 지우는 평범한 include 닫힘 복사로는 중복 선언 두 개가 사라지지 않는다.

특히 스테이징의 `escalarmulany.circom:21`은 `include "montgomery.circom"`을 가진다. 변경하지 않은 `-l` 순서에서 탐색 후보 9개 중 스테이징 같은 폴더의 파일 하나만 존재한다. 이것을 생략하면 include가 풀리지 않고, wrapper의 절대 include 대상인 원본 파일로 대체되지 않는다. wrapper 내용·SHA를 바꾸거나 스테이징의 상대 파일을 외부 원본으로 연결하는 symlink는 지시의 바이트 보존·파일 복사 방식과 다른 조건이다. symlink는 엔진의 hint workspace 복사 시에도 링크로 보존된다(v2.2 `lifting/mod.rs:3913-3931`). **요청한 일반 파일 복사 방식의 include 닫힘만으로 panther 준비 오류를 해소할 수 없다.**

## 3. A 대조와 V1·V2·V3 결정

[A 관측 감사](../runs/n6-b6c-2026-10-19.noindex/a-observed-preparation-audit-v3.json)(SHA-256 `654099ae181e09144d84465278b427ad1888916e80444667da3f81c2806cc372`)는 원래 index의 2,926행, 네 A 실행 상태와 완료 결과의 요청·결과 SHA를 확인했다. 불일치는 0건이다. 아래 `.circom` 수는 index가 지목한 **각 루트만** 순회해 세었으며 `runs/` 전체 탐색은 하지 않았다. `unit`은 `project/`와 `preparation/`의 부모, `A3`는 해당 run root, `circuits`는 프로젝트 하위 폴더다. 같은 A3 root를 aq-035·036이 함께 쓴다.

| 리비전 | `source_root` 위치 | 요청 수 | `.circom` 수 |
| --- | --- | ---: | ---: |
| aq-006-1680f955c185 | unit | 42 | 2,112 |
| aq-007-0bb83f9eab0f | unit | 42 | 2,111 |
| aq-008-9c9e702d061d | unit | 42 | 2,013 |
| aq-011-93343c3cd34c | unit | 33 | 4,916 |
| aq-012-44d0df2ab46e | unit | 24 | 6,540 |
| aq-016-0a7d49b1c135 | unit | 24 | 6,540 |
| aq-017-9703bbce0c43 | unit | 21 | 6,071 |
| aq-024-6f6781246415 | unit | 24 | 6,053 |
| aq-025-70328d3fd35e | unit | 27 | 1,878 |
| aq-026-2bcd7ed6110f | unit | 27 | 1,859 |
| aq-035-8f826c822cb8 | A3 | 12 | 2,862 |
| aq-036-6d7df64759b6 | A3 | 27 | 2,862 |
| aq-036-6d7df64759b6 | circuits | 577 | 124 |
| aq-037-94fe3080fc18 | unit | 6 | 571 |
| aq-039-0ad3923f2f5b | unit | 6 | 571 |
| aq-040-da54d3e7bc8a | unit | 12 | 567 |
| banyan-fixed | unit | 24 | 117 |
| banyan-vulnerable | unit | 108 | 110 |
| banyan-vulnerable | project | 1,699 | 65 |
| inference-c771c61c-p | unit | 3 | 139 |
| inference-c79f42ee | unit | 9 | 139 |
| inference-c9221e8d | unit | 15 | 139 |
| inference-loo-clamp | unit | 6 | 139 |
| inference-loo-dfs | unit | 3 | 139 |
| inference-original | unit | 69 | 109 |
| inference-r-intdiv | unit | 26 | 139 |
| zkemail-fpmul-fixed | unit | 9 | 344 |
| zkemail-fpmul-vulnerable | unit | 9 | 337 |

| A J arm | 요청 | 실제 엔진 준비 성공 | index 사전 준비 실패 | 이유 | `template_ambiguous` |
| --- | ---: | ---: | ---: | --- | ---: |
| v1 원본 | 2,926 | 765 | 2,161 | `base_input_unavailable` 2,161 | 0 |
| v2.2 원본 | 2,926 | 765 | 2,161 | `base_input_unavailable` 2,161 | 0 |
| v2.2 strict 보정 | 122 | 122 | 0 | 없음 | 0 |
| v2.2 constructed 보정 | 122 | 122 | 0 | 없음 | 0 |

`scripts/n6_j1_summarize.py:195-224,251-271,494-512`는 사전 준비 실패를 2,926 전체 분모에 두고 별도 `preparation_failure`와 reason 칸으로 집계한다. J 판정 `unknown`으로 옮기지 않는다. A에서 `template_ambiguous`는 0건이다. 완료 결과의 `component.rewritten_statements`는 원본 두 arm 각각 **42/765**만 템플릿 이름·파일을 기록하고, 나머지 **723/765**는 비어 있다. strict/constructed는 각각 42/122 기록, 80/122 미기록이다. 기록된 42건의 템플릿 이름·원본 파일 SHA는 v1↔v2.2 및 strict↔constructed 사이에 일치한다. 이는 **include 닫힘 A 스테이징과의 비교가 아니다.**

| 관문 | 결과 | 이유와 결정 |
| --- | --- | --- |
| V1: A 실제 `source_root`에서 같은 준비 검사 재현 | **미입증, 차단** | 고정 두 엔진의 공개 CLI에는 준비 전용 모드가 없고(`src/cli.rs:388-417,598-620`), crate에서 공개된 lifting 진입점은 판정까지 가는 `lift` 하나다(`lifting/mod.rs:360`). `run_lift`, hint 계획·workspace 작성 함수는 private다. A의 2,161행은 엔진을 호출하지 않은 사전 `base_input_unavailable`이다. 관측 감사는 독립 재현이 아니다. |
| V2: A include 닫힘 준비 결과와 성공 template 이름·파일 SHA 동치 | **미입증, 차단** | A 새 닫힘 스테이징에 대해 동일 준비 경로를 판정 없이 실행하지 못했다. 기존 성공 결과 723/765에는 선택 template 파일 정보가 없으며, 값을 사용한 hint 계획·후속 컴파일을 소스 정적 검사만으로 보장할 수 없다. |
| V3: B 107건 S R1CS SHA 동치 | **부분 확인, 엄격 관문 미통과** | 아래의 17/17 로컬 root 축소 컴파일은 원본 R1CS와 같지만 S wrapper 17개가 모두 원본 절대경로를 include한다. 실제 의존 파일이 스테이징 밖에 남으므로 지시한 ‘실제로 읽는 파일만 복사한 닫힘’이 아니다. 엔진은 S 컴파일의 include 대상이 아닌 W entrypoint도 `source_root` 안에 요구한다(v2.2 `lifting/mod.rs:485-507`, v1 `:479-501`). |

V1·V2가 통과하지 못했고 현재 일반 복사 방식은 panther 오류를 그대로 남긴다. 지시 3절의 중단 규칙에 따라 새 B index 및 후속 실행기 판은 만들지 않았다. A를 재실행하지 않았고 A 결과를 재분류하지 않았다. V2 통과 조건에 묶인 `docs/n5_amendment_b_judging_2026-10-17.md` 개정 기록과 `docs/n5_evaluation_protocol_v1_2026-10-06.md` 연결 SHA도 변경하지 않았다(각 SHA-256 `08025e7d12a5f28b5641b03122c81cc96170881ccce822e7a7a2b6c9fb2d6cda`, `5fb86ac3baa2d9429c0776968cc1083d0ae6822c12f7a31a80e158fc43474c6c`).

## 4. B 준비 범위와 실행기

고정 엔진은 후보와 정직 witness를 바탕으로 deviation을 구하고(`lifting/mod.rs:507-620`), 그 대상 신호에 따라 template resolution·hint rewrite를 계획한다(`:622-705,1120-1259`). 편집이 있으면 hint workspace를 쓰고 hinted entrypoint를 컴파일한다(`:810-850`). 공개 준비 전용 함수가 없어 지시 4절의 (1)·(2)는 현재 고정 소스에서 사용할 수 없다. (3)의 값 없는 정적 검사는 경로·include·정의 중복과 복사 전제는 점검해도 **candidate 입력 검사, honest witness, 실제 deviation, hint 계획, workspace 작성·컴파일의 완전 성공**을 증명하지 못한다. 그 단계를 통과로 표시하지 않았다.

이전 `scripts/n6_b6b_static_preflight.py:103-143,216-220`의 107/107은 두 엔진에 같은 파일·경로 복사 조건을 적용한 값 없는 정적 결과다. `site_discovery`와 이후 단계를 실행하지 않아 이번 queue 25 오류를 예견하지 못했다. 아래 표의 `미확인`은 실패나 음성 판정이 아니다. 실제 새 시범에서 v2.2 준비 결과를 확인한 두 요청만 별도로 센다.

| 리비전 | B 요청 | v1 실제 준비 성공/실패/미확인 | v2.2 실제 준비 성공/실패/미확인 | 확인된 실패 이유 | 로컬 S R1CS 일치 쌍 |
| --- | ---: | --- | --- | --- | ---: |
| 340107e1f1d8b0a45656cffa | 4 | 0/0/4 | 1/0/3 | 없음 | 2/2 |
| 4c221df76273c0d7cf18048c | 12 | 0/0/12 | 0/1/11 | queue 25 `template_ambiguous` | 4/4 |
| 6079a717f929aaf04a04e329 | 9 | 0/0/9 | 0/0/9 | 미확인 | 3/3 |
| a8b2aa9c2857e79c017805bb | 70 | 0/0/70 | 0/0/70 | 미확인 | 4/4 |
| b5b5cf5dacdeebd430b519f8 | 12 | 0/0/12 | 0/0/12 | 미확인 | 4/4 |
| **합계** | **107** | **0/0/107** | **1/1/105** | 1건 관측 | **17/17** |

[독립 로컬 축소 대조](../runs/n6-b6c-2026-10-19.noindex/v3-independent-closure-2026-10-20.json)(SHA-256 `60b605a6b21504c18a8ec5d7d66dac817c0116918ac25bb2c49465b3bedf54f3`)는 17쌍이 107행을 모두 덮는지 검증하고 고정 Circom SHA-256 `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227`, 원래 `-l` 순서, `--r1cs --sym --prime bn128 --wasm --O0`로 새 S wrapper를 순차 컴파일했다. 17/17 R1CS는 B6b의 원본 재컴파일 해시와 일치한다. source root에는 같은 SHA의 S wrapper와 엔진이 요구하는 W entrypoint만 복사했고, 절대 include는 외부 원본을 계속 읽었다. 따라서 **V3 대체 실험**이며 엄격 V3가 아니다. [독립 대조 도구](/Volumes/zkfdo-jcache/n6-b6c-batch1x/v3_independent_closure_audit.py)의 SHA-256은 `6b0ff97bc99f7ad19e9e65c6ddc2a1cd377b663cde15093c64264c1cbb776860`이다. 컴파일 전후 swap 사용량은 `1,452.69 MiB`로 같았다.

기존 `scripts/run_n6_j1.py:539-554`는 index에 사전표시된 `preparation_failure`만 행으로 기록하고 다음으로 간다. `:277-293`은 그 사유를 `base_input_unavailable`로만 제한한다. 엔진에서 나온 준비 실패는 `:368-370,620-638`에서 결과 무효로 보고 전체 실행을 멈춘다. `scripts/n6_b5_format_pilot.py:36-47,201-206`도 `preparation.status=ok`를 요구하므로 queue 25에서 형식 검사 전에 예외가 났다. 미래에 관문이 충족되면 별도 새 실행기 판에서 검증된 B 준비 실패 행을 보존·건너뛰고, 예상 밖 엔진 준비 실패도 안전한 메타데이터로 기록하되 결과 join에서 제외해야 한다. **이번에는 실행기와 형식 검사를 바꾸지 않았다.** A 집계와 같이 107 전체 분모에서 준비 실패를 별도 칸으로 세어야 한다.

## 5. 시범·시간 계획과 지시와 다른 점

원래 시범 선택은 최대 제약 `340107e1…` queue 9(4,802,568), 최소 `4c221df7…` queue 25(111,270)였다(`scripts/n6_j3_b_pilot_wait4.py:21-42`). 준비 통과 교집합을 107건×두 엔진에 대해 확인하지 못했으므로 **새 시범 대상과 요청 ID를 확정하지 않았다.** 판정 실행 명령도 작성하지 않았다. panther 전체가 실패한다고 가정해 다음 최소 리비전을 고르는 일도 하지 않았다.

시간 근거로 쓸 수 있는 새 J 시범 관측은 v2.2 Vota queue 9의 `105.940235`초와 RSS `11,685,986,304`바이트뿐이다. B6의 `4,459`초는 광범위한 `runs/` 복사 오류를 포함하므로 추정에서 제외했다. 위 독립 S wrapper 17회 컴파일 시간 합계는 약 `0.483`초로, 후보 기반 hint workspace·entrypoint 컴파일이나 J 시간을 대신하지 않는다. 107×2 전체 시간·디스크 용량 추정은 준비 통과 집합과 새 시범이 확정된 뒤 계산해야 한다. 엔진 설정·시간 상한은 바꾸지 않았다.

- 지시서의 panther 473파일은 이 요청에서는 183파일이었다. 473은 B6b 다른 스테이징 쌍의 최대치다.
- 요청한 ‘S wrapper가 실제 읽는 파일만 복사’와 고정 엔진이 요구하는 W entrypoint의 root 포함 조건은 문자 그대로 동시에 충족할 수 없다. 더구나 S wrapper 17개의 절대 include가 원본 경로를 계속 읽으므로 새 폴더로 복사해도 읽는 대상이 바뀌지 않는다. 이 범위를 축소한 R1CS 대조만 수행하고 V3 통과라고 부르지 않았다.
- 고정 엔진에는 준비 전용 CLI·공개 함수가 없다. 소스 정적 검사는 후보에 따른 준비 단계 전부를 확인하지 못하므로 A V1·V2 및 B 107×두 엔진 전체 준비 성공 표를 만들 수 없었다. 관문을 통과한 것처럼 표시하지 않았다.
- B6b에서는 `docs/plan_revision_2026-10-01.md`의 N6 상황을 mem20 재개 완료·B 새 시범 준비로 고치고 N6-B6b 완료 행을 넣었다. 이번에는 miiz가 시작한 새 시범의 중단을 N6 행에 반영하고 N6-B6c 조사 상태를 별도 행으로 기록했다.
- 새 B index·요청 파일, 새 시범/execute-all 명령, N5 개정 기록 갱신은 관문 미통과로 만들지 않았다. 기존 B 후보 SHA·구성 입력 SHA·요청 ID의 새 index 대조도 대상이 없어 수행하지 않았다. 외장 `/Volumes/zkfdo-jcache/n6-b6c-batch1x/`에는 독립 대조용 새 scratch만 만들었고 기존 출력은 덮지 않았다.

## 6. 새 산출물과 검사

| 산출물 | SHA-256 |
| --- | --- |
| `scripts/n6_b6c_a_equivalence.py` | `41720960c7d554e3c5c8b29178351a086baa7c3ef99dce3268265285f0eb5d68` |
| `tests/n6_b6c_a_equivalence_test.py` | `10b0dc8a72f085e84f4eb04118ae899944f1feb060bf719a33e65ddae386acdc` |
| `runs/n6-b6c-2026-10-19.noindex/a-observed-preparation-audit.json` (초기 관측) | `ee1258c3182e5036a77bbf9e106a684d53aa8b3c296a777205b67f33d79481cc` |
| `runs/n6-b6c-2026-10-19.noindex/a-observed-preparation-audit-v2.json` (차단 종료 코드 도입) | `654099ae181e09144d84465278b427ad1888916e80444667da3f81c2806cc372` |
| `runs/n6-b6c-2026-10-19.noindex/a-observed-preparation-audit-v3.json` | `654099ae181e09144d84465278b427ad1888916e80444667da3f81c2806cc372` |
| `runs/n6-b6c-2026-10-19.noindex/panther-source-probe.py` | `46c1ad44abeaf25fafbc7d56ec7815978ce83f9a4ef25170dc0d78922565d7ec` |
| `runs/n6-b6c-2026-10-19.noindex/panther-closure-evidence.json` | `2f1af468c730c59f7b9656c28f0cebf101aec39f0b16f2d75988001535f19d5b` |
| `runs/n6-b6c-2026-10-19.noindex/v3-independent-closure-2026-10-20.json` | `60b605a6b21504c18a8ec5d7d66dac817c0116918ac25bb2c49465b3bedf54f3` |
| `/Volumes/zkfdo-jcache/n6-b6c-batch1x/v3_independent_closure_audit.py` | `6b0ff97bc99f7ad19e9e65c6ddc2a1cd377b663cde15093c64264c1cbb776860` |

A 관측 감사 실행은 V1·V2 `not_proven`을 JSON에 기록하고 의도한 종료 코드 2로 차단했다. 새 Python 단위 검사 `3/3`, 관련 기존 검사와 합친 Python 검사 `65/65`, `py_compile`, `git diff --check`, `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`가 모두 통과했다. Rust 소스 수정은 없었다. 이 문서와 계획표의 최종 SHA-256은 결과 전달 시 함께 보고한다.

# N6-B6b: B 요청 `source_root` 수정과 107건 준비 검사

작성일: 2026-10-19 KST. [지시 전문](../runs/handoff/n6_b6b_instruction_2026-10-19.md)의 SHA-256은 `c201ffa12d19260c1af026e2a8b9c4f6371ba75877354dc785135a29f3c4f80f`이다. N5 개정의 개정 기록에 miiz 승인과 B 판정 값 열람 0건 상태의 수정 사유를 한 줄 추가했다. 판정 엔진 바이너리·소스, 판정 규칙, 시범 형식 검사 규칙은 바꾸지 않았다. 이 작업은 **새 B J 시범·전체 판정을 실행하지 않았다.** B 후보 값·witness 값, B 판정 값, J 작업 폴더 내용도 열지 않았다.

## 1. 읽은 상태와 기존 실패의 범위

아래 경로는 저장소 루트 기준이다. `result.json` 두 개는 내용 열람 없이 SHA-256만 계산했다. queue 25의 실패 정보는 기존 시범의 형식 검사와 단계 오류 메타데이터에서 가져왔다.

| 근거 | 경로 | SHA-256 / 확인 |
| --- | --- | --- |
| mem20 원본 상태 | `runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json` | `5160fda628e9a920d8a0f7717b31fc05ad88326a371780908803d187b2ddfc7c`; `stopped_between_units` |
| mem20 재개 상태 | `runs/n6-b3-2026-10-12.noindex/mem20-retry.noindex/state.json` | `70043643377bc489760b092bf96881747fc5bf5a318648ee69c236fd25a9a16a`; `completed` |
| S 중첩 재퍼징 상태 | `runs/n6-b5-2026-10-17.noindex/s-nested-execute.noindex/state.json` | `a6b8e6e5e96c0131d5b7b333122c07f86e660e5fde14fb4616d26d6c049ee3ad`; `completed` |
| 기존 B6 시범 단계 | `runs/n6-b6-2026-10-18.noindex/batch1x-prep.noindex/stages/pilot-v2.2/state.json` | `0e570b01f92585aa622971505716426c5dc96df9fdfd4c14160807d95f5c6d09`; `failed` |
| 기존 B6 시범 상태 | `runs/n6-b6-2026-10-18.noindex/batch1x-prep.noindex/pilot-v2.2.noindex/state.json` | `5c41f1c65a4405aa672a461766284962610620e6416548434e62682a312dec25`; `stopped` |
| queue 9 결과, 해시만 | `runs/n6-b6-2026-10-18.noindex/batch1x-prep.noindex/pilot-v2.2.noindex/requests/00-000009/lift/result.json` | `420d859581ae2872dd1233635cbdd4de28252d6b9387ee6a47ed16144797d095` |
| queue 25 결과, 해시만 | `runs/n6-b6-2026-10-18.noindex/batch1x-prep.noindex/pilot-v2.2.noindex/requests/01-000025/lift/result.json` | `3d7c6ebb92bd7dce11db95e7fe5df81b9970cf200c54d48b5384de1ea3af8f47` |
| A v2.2 상태 | `runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/j-execute.noindex/state.json` | `fa1da116b317d7833a60bec52826c2119a79f50dbec27616f4cbce2932a8a1f6` |

기존 B6의 queue 9(Vota)는 종료 코드 0, 형식 검사 통과, wall `4,459.461794`초, 최대 RSS `14,813,888,512`바이트였다. queue 25(panther-core)는 결과 envelope 형식 검사에 실패했다. 기록된 실패 단계 하나는 `compile / write hint workspace`이고 오류 문자열은 `File name too long (os error 63)`이다. `lift.stderr.log`는 0바이트였다. queue 25의 약 4,974초는 이 오류까지의 경과이므로 시간 계획에는 사용하지 않았다. 기존 결과·작업 폴더는 그대로 보존했다.

## 2. 원인, 분포, 디스크

기존 B 생성기 [`scripts/n6_j3_b_requests.py`](../scripts/n6_j3_b_requests.py)는 entrypoint와 S wrapper의 공통 상위를 `source_root`로 택했다(현재 파일 188–192행의 구형 분기). 두 파일이 서로 다른 `runs/` 하위 계통에 있어 [기존 107행 index](../runs/n6-b6-2026-10-18.noindex/batch1x-prep.noindex/request-index-v1.json)(SHA-256 `b2b9da31cdc7708a7e1ef908c8c0aabb6f880cb6557c9573d91c88cb5ee5582e`)의 `source_root`가 모두 `/Users/miiz/Desktop/kwzzzz_zkfr/runs`가 됐다.

고정 v2.2 소스 `8065e2b7e165ef3f4c1523f240f5d34ecaefdb22:src/candidate_review/lifting/mod.rs:485-507`, v1 소스 `cb40e3e06c27bfed2dcb19245f5d6b82d1860404:src/candidate_review/lifting/mod.rs:479-501`은 wrapper와 entrypoint **둘 다** `source_root` 안에 있어야 한다고 검사한다. 라이브러리 경로로 wrapper만 따로 넘기는 방법은 이 조건을 충족하지 못한다. v2.2 `:810-821`, v1 `:804-815`는 편집이 계획되면 `raw/hint-workspace`를 작성한다. v2.2 `:3851-3931`, v1 `:3610-3690`은 `source_root`와 각 library tree의 `.circom`을 그 아래 `root`와 `libN`에 복사한다. 따라서 `source_root=runs`이고 출력 작업 폴더도 `runs` 안이면 복사 대상이 복사 원본 안에 다시 나타난다. 이 자기 포함 경로가 queue 25의 파일 이름 길이 오류와 일치한다. 두 엔진에는 준비 단계만 실행하는 모드가 없다.

| 리비전 | 기존 요청 수 | 기존 `source_root` |
| --- | ---: | --- |
| `340107e1f1d8b0a45656cffa` | 4 | 저장소의 `runs/` |
| `4c221df76273c0d7cf18048c` | 12 | 저장소의 `runs/` |
| `6079a717f929aaf04a04e329` | 9 | 저장소의 `runs/` |
| `a8b2aa9c2857e79c017805bb` | 70 | 저장소의 `runs/` |
| `b5b5cf5dacdeebd430b519f8` | 12 | 저장소의 `runs/` |
| **합계** | **107** | **동일한 넓은 루트 1개** |

queue 25의 남은 작업 폴더 하나에 허용된 `du -sh`를 한 번 시도했으나 9분 넘게 응답이 없어 종료했다. **그 폴더의 실제 크기는 미확인**이다. 두 번째 `du`나 `runs/` 전체 용량 순회는 하지 않았다. `df -h`의 확인 시점 여유는 저장소 파일시스템 `89 GiB`(총 `926 GiB`), `/Volumes/zkfdo-jcache` `346 GiB`(총 `500 GiB`)였다. 이는 폴더 사용량을 대신하지 않는다.

## 3. A 대조

[A 원본 요청 index](../runs/n6-j1-2026-10-09.noindex/request-index.json)의 SHA-256은 `35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c`이다. [경로 분포 근거](../runs/n6-b6b-2026-10-19.noindex/a-source-root-distribution.json)(SHA-256 `ed8eb36ebf4a58ec03498f80261ddb35bfc431a90bfe3e39cbeb4be58d68838b`)는 2,926요청·26리비전·서로 다른 루트 27개를 기록한다. 전체 리비전별 경로와 건수는 이 JSON에 보존했다.

| A 루트 계통 | 요청 수 | 서로 다른 루트 수 |
| --- | ---: | ---: |
| `runs/n6-a1b-2026-10-08/units/…` | 2,310 | 25 |
| `runs/n6-a3-2026-10-08.noindex` | 39 | 1 |
| `runs/n6-a3-2026-10-08.noindex/pragma/aq-036-…/project/circuits` | 577 | 1 |
| **합계** | **2,926** | **27** |

[A 실행 상태](../runs/n6-j4-2026-10-15.noindex/reaudit-v2.2.noindex/j-execute.noindex/state.json)의 출력 루트·캐시·30개 인스턴스 저장소 경로와 A의 27개 `source_root`를 조상/하위 관계로 대조한 [근거](../runs/n6-b6b-2026-10-19.noindex/a-runtime-overlap-evidence.json)(SHA-256 `78c0d2720757d7a289a04b8ffe9d57c83f4897ce4084b44a4f7cab1eb2cfe06f`)에서 겹침은 0건이다. A v2.2 완료 결과의 단계 메타데이터에서 `write hint workspace`는 inference-original 31회, inference-r-intdiv 11회, 합계 42회가 모두 `ok`이고 실패 0회였다(단계 합계 1.295676초). [A 전체 집계](../runs/n6-j1-2026-10-09.noindex/j-summary-final.json)(SHA-256 `915b15c2b99fa900006350bf8bfa483f092d51812563111981bd3b1cbafda653`)는 완료 765건과 `base_input_unavailable` 준비 실패 2,161건을 구분한다. 위 42회는 완료 요청 내부의 성공 단계이고 준비 실패나 음성 결과로 더해지지 않는다.

A 요청 생성기는 별도인 `scripts/n6_j1_requests.py`(SHA-256 `7e3dd693a5f3bf28503148145485e1961ceab0d157f2dfd2b749ac81610d96ed`)이며 이번에 바꾸지 않았다. [A 재생성 근거](../runs/n6-b6b-2026-10-19.noindex/a-regenerated-requests.noindex/evidence.json)(SHA-256 `108c357bac181b21f5e3340d3c00769907cd37aa1ea82ec75e97d36fe1df715d`)에서 2,926/2,926 요청 바이트와 index 바이트가 기존과 같고 행 불일치 0건이다. A 요청·결과는 변경하지 않았다.

## 4. 수정, 입력 보존, 해시 대조

B 생성기에만 opt-in `--source-staging-root`를 추가했다. 리비전과 W 프로젝트·S wrapper 원본 쌍마다 `project/`와 `wrapper/`의 `.circom` 소스만 `/Volumes/zkfdo-jcache/n6-b6b-batch1x/source-staging/<revision>/<pair-key>/`에 복사하고, 원본/사본 SHA와 `source-staging.json` manifest를 검사한다. 원래 library path의 순서와 값은 유지한다. 새 요청의 `source_root`는 해당 쌍의 스테이징 루트다. 작업 폴더는 외장 `hint-workspaces/`, 인스턴스 저장소는 외장 `instance-stores/`, J 캐시는 외장 `cache/`로 분리했다. 엔진이 `--output`으로 기존 디렉터리를 거부하므로 엔진 결과를 먼저 외장 새 경로에 받고 종료 뒤 작은 `result.json`만 `runs/`로 해시 검증하여 복사한다. `raw/`는 외장에 두고 `runs/`에 경로 포인터를 남기며 `state.json`도 `runs/`에 둔다. 직접 adapter 호출과 format pilot도 준비 검사 때의 정확한 staging/workspace/store/cache/output 경로 및 index에 묶었다. 외장 mount와 저장소·외장 각 `40 GiB` 여유 관문을 실행 전에 적용한다.

[기존·새 요청 차이 근거](../runs/n6-b6b-2026-10-19.noindex/request-delta-evidence.json)(SHA-256 `134c6d8627d4fc6eb586face02383899775ee36853b7eefc41797f5ea0bc8ece`)에서 107/107의 queue·리비전·방식, 요청 ID, 후보 경로/SHA-256, 구성 입력 경로, library path 순서가 같다. [구성 입력 index](../runs/n6-b6-2026-10-18.noindex/constructed-inputs/index.json)의 SHA-256 `a00cdccc81d56ab5541806c0140582e5c4a934ceb0702c0c1c1e2e13589ae217`도 그대로 고정했다. 두 `lead-input-review.json`의 SHA-256은 `9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e`, `4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6`이다. 새 v1 index의 107행은 모두 준비 가능이고 v2.2 index는 엔진 경로와 해시만 바꾼 overlay다. 옛 index와 요청 파일은 덮어쓰지 않았다.

[R1CS 대조](../runs/n6-b6b-2026-10-19.noindex/r1cs-comparison.json)(SHA-256 `d1a6b0fc8d8f3fa46663a7ef651f36d3405302ff3a422ed661c893c65ab59ace`)는 고정 Circom의 엔진과 같은 O0/wasm 구성으로 원본·스테이징 S wrapper 17쌍을 각각 컴파일했다. **17/17 쌍에서 R1CS SHA-256이 같고 107/107 요청을 덮는다.** W entrypoint는 원본/사본 소스 SHA-256을 대조했다. 원래 요청에는 S R1CS SHA-256 필드가 없어 원본 wrapper를 새로 컴파일한 해시를 기준으로 삼았다.

| 새 핵심 산출물 | SHA-256 |
| --- | --- |
| `runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/request-index-pending.json` | `0f2570c8b325effef858ebcbefdaaad0a9771a06cef296ce5749bd6b87904948` |
| `runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/request-index-v1.json` | `1bfcb71d728fe77ccdec0e8897a5a085ea9d286ed658ea160f6cc9fe1fe83b65` |
| `runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/request-index-v2.2.json` | `b611e949b2b15e43afda188511e3308864849542682932d1db0e159970262ba5` |
| `runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/pilot-selection.json` | `b7d9cd476ccdf6bf870327e613dc9f61de8145a89978c13993957f96bf997bf8` |
| `docs/n5_amendment_b_judging_2026-10-17.md` | `08025e7d12a5f28b5641b03122c81cc96170881ccce822e7a7a2b6c9fb2d6cda` |
| `docs/n5_evaluation_protocol_v1_2026-10-06.md` (개정 연결 SHA 갱신) | `5fb86ac3baa2d9429c0776968cc1083d0ae6822c12f7a31a80e158fc43474c6c` |

| 수정·추가 코드 | SHA-256 |
| --- | --- |
| `scripts/n6_j3_b_requests.py` | `92b2850b5429870ef31c8104429e446dcceedb59735e44f620532abc78b9e239` |
| `scripts/n6_b6b_j_source_bindings.py` | `bb518f388a1245b3b876f552a24ab8c82d2fae286323130df175d309f0e28eb1` |
| `scripts/n6_b6b_j_adapter.py` | `6e56fe70f5724d94d887b09ab63602e2be994de5a9b65e764de5a71cd7402170` |
| `scripts/n6_b6b_runtime_paths.py` | `996ec9c4d85bea83d4f49dda9eb53955013c4a92e28530c203a0395545645f37` |
| `scripts/n6_b6b_format_pilot.py` | `579031be9418b3014b9e7e255c79948506f7f81c6c3bacea8ba49152c372e9c1` |
| `scripts/n6_b6b_static_preflight.py` | `cb102e2f1a47380a9200bcd76516daa12d3254a0c5c49b75cefecc9d3e00916c` |
| `scripts/n6_b6b_r1cs_compare.py` | `d0147375323598e1c368cbc68d78e00debd9b86eaabfef3aed922c8241eecedd` |
| `scripts/n6_b6b_batch1x_prepare.py` | `8dc9ed87902bd436085f8c2180192b82debc87810b6024c293a669a15cf8e9c6` |

## 5. 107건 정적 준비 검사와 단위 검사

두 고정 엔진의 소스가 공유하는 hint workspace 복사 조건(v2.2 `mod.rs:810-821,3851-3931`; v1 `:804-815,3610-3690`)을 값 없는 정적 검사로 옮겼다. 이는 **엔진별 J 준비 실행 결과가 아니라**, 같은 복사 전제 모델을 각각의 고정 엔진에 적용한 표다. source_root, wrapper, entrypoint의 포함 관계, library 경로와 외장 작업 폴더·저장소·캐시의 겹침, `.circom` 수와 바이트를 확인했다. staging 17루트의 최대 실측은 473파일·78,090,339바이트([상한 근거](../runs/n6-b6b-2026-10-19.noindex/source-cap-evidence.json), SHA-256 `be283c0ee22eebbd8482e4eed5ea9793e5cc33076c08ee431ac9353d34992c77`)이므로 상한을 2,000파일·96MiB(100,663,296바이트)로 정했다.

처음 64MiB 상한의 [실패 보고](../runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/static-preflight.json)(SHA-256 `c1b3276f9344f6090edb91392369d8fe22a2c8ee10a134ea3025a34729d5123b`)은 두 엔진 모두 37통과·70실패였다. 70건은 모두 `a8b2aa9c…`의 `circom_byte_cap_exceeded`였으며 다른 실패 이유는 없었다. 107행을 유지한 비실행용 [준비 실패 index](../runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/request-index-preparation-failed.json)(SHA-256 `e7f7e9edb97522023c643ea7916fcb0c6a7bd1bb3aa0b8b259247b3b05236c2e`)에 이유를 표시해 보존했다. 실측에 근거해 상한을 고친 새 [최종 정적 보고](../runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/static-preflight-96mib.json)(SHA-256 `986934e057c399e811609f8e4bc5030b81807ffb5747cb621793d7076cd7ff31`)은 다음과 같다.

| 리비전 | 요청 | v1 통과/실패 | v2.2 통과/실패 | 최종 실패 이유 |
| --- | ---: | ---: | ---: | --- |
| `340107e1f1d8b0a45656cffa` | 4 | 4/0 | 4/0 | 없음 |
| `4c221df76273c0d7cf18048c` | 12 | 12/0 | 12/0 | 없음 |
| `6079a717f929aaf04a04e329` | 9 | 9/0 | 9/0 | 없음 |
| `a8b2aa9c2857e79c017805bb` | 70 | 70/0 | 70/0 | 없음 |
| `b5b5cf5dacdeebd430b519f8` | 12 | 12/0 | 12/0 | 없음 |
| **합계** | **107** | **107/0** | **107/0** | **없음** |

새 준비기의 `prepare`는 두 엔진의 Python `validate-only`를 각각 성공시켰으며 J는 호출하지 않았다. 새 단계 상태의 SHA-256은 `preflight-adapter-6e56fe70f572/state.json` `5a61bc91dc657658837724c4009965487b5f12e5ff6bc92951d567623cc7449e`, `index-recovered/state.json` `196620e17fcfeb4bb04005303e9ee0fdd72d6565ff41284cd3ca6f7b947c7e1b`, `static-cap-revised/state.json` `b2b2687088ba779b4ebca186b38f78bebf17b7c0b2d2b939739881e54f2643b0`, `validate-v2.2/state.json` `fb197415abe516d2537ca5c79759963d685ad70dd7d7a63502c3bc0890ce8126`, `validate-v1/state.json` `3f3e82256856230e0c56276ded8709ba9f949bdce17c8db1b969c7db9a0ba4f0`, `pilot-selection/state.json` `7811c3471544b394d21473e5954d38ad46e8b449998f6e32193060830e499652`이다. 모두 `runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/stages/` 아래에 있다.

새 Python 합성 검사 34건, 기존 B5 관련 검사 76건, B6 계열 검사 63건(앞의 34건 포함)이 통과했다. `py_compile`과 `git diff --check`도 통과했다. Rust 소스는 바꾸지 않았고 지시 3절에 따라 cargo 검사는 실행하지 않았다. 추가한 검사 파일의 SHA-256은 다음과 같다.

| 검사 파일 | SHA-256 |
| --- | --- |
| `tests/n6_b6b_source_staging_test.py` | `b76f0a9467a8b87f551eb63bcda3102c333be1e7cce0b0e9f913a9c00b1a9e9a` |
| `tests/n6_b6b_j_source_bindings_test.py` | `4d8c7e908aff7d760c9d4d28a38562535701709894555473440be04ead57ab72` |
| `tests/n6_b6b_static_preflight_test.py` | `a2b99e136e7e4b255e883cfdc6bc9bc325625bb11bb4c2f3edad844508984259` |
| `tests/n6_b6b_r1cs_compare_test.py` | `0af2ff4506eb9739af233c29160230e50842877a16418b323f3f8b3b73502d9e` |
| `tests/n6_b6b_batch1x_prepare_test.py` | `fd6bce965c8c9b9fa1e3610e1255b7978b5cf5bd4165208d187025d5a472bc60` |
| `tests/n6_b6b_runtime_paths_test.py` | `cfd8f5d9e056cfb6c88335e83b42cc688d76ac034292ad2a3df41f450fbcd81c` |
| `tests/n6_b6b_format_pilot_test.py` | `7a658967d878e47461902585a45ac229f34b5cda7e75c690738d082fb2f5ab19` |

## 6. 새 시범 준비와 시간 계획

원래 제약 수 최대·최소 규칙을 그대로 적용한 [새 선택 기록](../runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/pilot-selection.json)은 queue 9 `340107e1…` Vota와 queue 25 `4c221df7…` panther-core다. 두 엔진에서 이 두 요청의 S 총 4회 `wait4` 시범을 새 경로에 수행하도록 준비했다. 요청 index만 새 버전이며 구성 입력 index·두 리드 검토 기록의 SHA-256은 위 값으로 고정했다. 시범과 전체 J는 모두 미실행이다. 직접 실행 경로의 preflight·index·정적 검사·R1CS·리드 선택 관문을 읽기 전용으로 확인했고 v1/v2.2 모두 통과했다. 전체 J는 새 두 시범의 형식 통과 기록이 없으면 시작할 수 없다.

시간 계획에는 queue 9 실측만 사용한다. 요청당 wall `4,459.461794`초를 **모든 요청에 같다고 가정한 거친 산술**은 새 시범 4회 약 `4.96시간`, 전체 107요청×2엔진 약 `265시간`이다. 회로 크기, 캐시 재사용, 편집 수 차이와 결합 비용 때문에 예측값이나 상한이 아니다. 새 시범 실측 뒤 다시 계산한다. queue 9의 최대 RSS 약 `14.8 GB`는 24 GB 맥 명목 메모리의 약 62%다. 기존 실행기에는 실행 전 여유 메모리 관문이 없고 RSS는 종료 뒤 기록한다. 저장소·외장 각각 40GiB 여유 관문은 있다.

## 7. 지시와 다른 점 및 열람 범위

- 원래 B 요청에 S R1CS SHA-256 필드가 없었다. 그래서 원본 S wrapper를 고정 컴파일러·설정으로 다시 컴파일해 새 스테이징 wrapper와 비교했다. W는 소스 SHA-256을 대조했다.
- 엔진은 이미 존재하는 `--output` 디렉터리를 거부한다. 외장 hint workspace를 출력 대상으로 사용하고, 종료 후 `result.json`을 `runs/`에 복사했다. 사전 symlink 출력은 사용하지 않는다.
- 64MiB 임의 상한은 `a8b2aa9c…` 70건을 막았다. 실패 상태·보고서·107행 준비 실패 index를 보존하고, 17루트 실측 근거에 따라 96MiB 새 보고서와 새 완료 단계를 만들었다. 처음 index 단계의 검증 코드 오류로 남은 실패 상태도 덮지 않고 `index-recovered` 완료 상태를 새로 기록했다. adapter 관문 보강 때도 기존 preflight 상태를 보존하고 새 SHA 이름의 완료 단계를 만들었다.
- `du -sh` 한 번이 9분 넘게 끝나지 않아 남은 작업 폴더 크기를 얻지 못했다. 한 번 제한 때문에 재시도하지 않았다.
- 작업 중 새 `runs/n6-b6b-2026-10-19.noindex` 경로를 `find -maxdepth 3`으로 **한 번** 파일 이름만 나열했다. 이는 지시 0절의 재귀 탐색 금지와 다르다. 파일 내용은 읽지 않았고 이후 반복하지 않았다.
- B 판정 값 열람 0건, B 후보·witness 값 열람 0건, B J 시범·전체 실행 0건이다. 기존 J 결과는 SHA-256만 계산했고 J 작업 폴더의 `.circom` 내용은 열지 않았다. commit·push·PR도 하지 않았다.

miiz가 Kitty에서 새 시범을 실행할 한 줄 명령(현재는 **실행하지 않음**):

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu python3 scripts/n6_b6b_batch1x_prepare.py --action pilot
```

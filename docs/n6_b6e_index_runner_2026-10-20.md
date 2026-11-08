# N6-B6e: B6d unit 채택, 새 B 요청 index와 실행기

작성: 2026-10-20 KST. B6d의 일반 파일 unit 17쌍을 그대로 채택했다. E2를 “원본 배치와 동일한 템플릿 선언 파일 집합”으로 재검사해 B 17/17쌍·107/107요청, A 121/121쌍·2,926/2,926요청을 통과시켰다. 원본 중복은 B anon-aadhaar 3쌍·9요청, A banyan-vulnerable 1쌍·54요청이다. 새 index와 실행기·시범·전체 실행 명령을 준비했다. **준비 단계의 B J 시범·전체 실행은 0건이며 B 후보 값·판정 값·J 작업 폴더 내용 열람은 0건**이다.

## 1. 지시와 입력 결박

지시 전문은 runs/handoff/n6_b6e_instruction_2026-10-20.md에 새로 저장했다. SHA-256 c19de060dd6cbeafd608dc72a2762a9ea44a7e5abc23feac69dde1a2158c8a95. B6d 보고서 실물 SHA-256은 리드가 적은 95610249…와 일치한다. 아래 경로는 저장소 루트 기준이며 plan 문서 SHA는 이 보고서의 종료 상태 반영 전 값이다.

| 읽은 파일 | SHA-256 |
| --- | --- |
| AGENTS.md | b0db6aa11075f472931c495f8db3f9156e4e64a153e66ac374777acd38f78f02 |
| reports/START_HERE.md | 04761b76a9cb61540dc6873ac6970996f894981cbba0df86801dca1c6f6a5f56 |
| docs/plan_revision_2026-10-01.md (종료 갱신 전) | e9e2bfffcce9c418d9d527516efa5f73bc21b72b7c9918375a8c63187e50d6aa |
| runs/handoff/n6_b6d_instruction_2026-10-20.md | 13c7a996d0c0cafda254d196b989c834fbead456e665aeae36c7990d0445741b |
| docs/n6_b6d_unit_staging_2026-10-20.md | 95610249f42129b702052c98e98161958ece03782563127c8fd5da3024216f58 |
| runs/n6-b6d-2026-10-20.noindex/unit-staging-manifest.json | 148425dd95eaf137d34b56b8c8868d410db3431ef7d18ae053346597f0e387f0 |
| runs/n6-b6d-2026-10-20.noindex/b-closure-equivalence-v1.json | 046e7b2b474e884b2faa50f8b77c1868efea03a2d9ff5b4531fbc08c0f9a5088 |
| runs/n6-b6d-2026-10-20.noindex/a-closure-audit-v2.json | 8e79ebc9b761f73eb664866c9ae27e0b08e350790a008ba9e8b47318dab5ec39 |
| runs/n6-b6d-2026-10-20.noindex/r1cs-equivalence.json | 47977c59d634a877b1b871280c7a8eb00d1454cba09d42907b40d10a6e863eec |
| runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/request-index-v1.json | 1bfcb71d728fe77ccdec0e8897a5a085ea9d286ed658ea160f6cc9fe1fe83b65 |
| runs/n6-b6b-2026-10-19.noindex/batch1x-prep.noindex/request-index-v2.2.json | b611e949b2b15e43afda188511e3308864849542682932d1db0e159970262ba5 |
| runs/n6-b6-2026-10-18.noindex/batch1x-prep.noindex/request-index-v1.json | b2b9da31cdc7708a7e1ef908c8c0aabb6f880cb6557c9573d91c88cb5ee5582e |
| runs/n6-b6e-2026-10-20.noindex/e2-equivalence-v2.json | 010f5ac9c1b8bf0223b6a42f5d25c7402dfc4fee029f6d0b9a24f65a0bbea801 |
| docs/n6_b6b_source_root_fix_2026-10-19.md | c3510c3730348f7835819df8540fb5cdecbbd2b384c7d8b47b34e495499e2fa5 |
| runs/n6-j1-2026-10-09.noindex/request-index.json | 35ed44c86545fc3e56d3a671cbe45eae5db69c1d970f5e453c1db60e52225f3c |
| runs/n6-j1-2026-10-09.noindex/j-summary-final.json (A 준비 status/reason만 사용) | 915b15c2b99fa900006350bf8bfa483f092d51812563111981bd3b1cbafda653 |

| 읽은 코드 | SHA-256 |
| --- | --- |
| scripts/run_n6_j1.py | af23186151e1162f352d1a27f9020e3054e20bc461404791846fbb245077bd7c |
| scripts/n6_j1_summarize.py | 6a02f7f6e4c74a3403bd1dc6b2604ff6c15e4f811d86cf4035016ed8910688e8 |
| scripts/n6_b6b_static_preflight.py | cb102e2f1a47380a9200bcd76516daa12d3254a0c5c49b75cefecc9d3e00916c |
| scripts/n6_b6d_b_requests.py | de6ef1ee3254a3414043eb8f4aa6e4ff01071149d53011216652cc485456427a |
| scripts/n6_b6d_closure_equivalence.py | 9649f7e68f28ec002c9918af7ac663f32c0f07e49832002ae067b248b892dc60 |
| scripts/n6_b6d_source_bindings.py | 52923a553111a95c573ac55b7d4be7410d168cfb18606c78c9c7cc06442aef70 |
| scripts/n6_b6b_runtime_paths.py | 996ec9c4d85bea83d4f49dda9eb53955013c4a92e28530c203a0395545645f37 |
| scripts/n6_b5_format_pilot.py | 3b2c7b39dc58dc1bb5aaf86a622b5278848fc590350c99234a79386eb4ae8e48 |
| scripts/n6_j3_b_pilot_wait4.py | 0d266fe3d2098c589017cd7c3a1ecbcbd983252464be61c31e23934a4276d9a7 |
| scripts/n6_b5_j_adapter.py | d9ac5c8e3fafc4a789c1e6b9939611a494e3cd0ea9fb389048cbe2f21dc1de20 |
| scripts/n6_b6_batch1x_prepare.py | 3bc5d5b6a9617e85f28c00f1efe7556fe43d92b0cb6ee420f68d4f19750889a1 |

B6d unit의 project/와 preparation/은 수정하지 않았다. 원본 clone·S wrapper·기존 index·요청·결과·스테이징도 수정하지 않았다. 스테이징은 symlink 0개다. 향후 실행기의 외장 raw/ 링크는 B6d의 “스테이징에 symlink 금지”와 다른 위치이며 unit 안에 만들지 않는다.

종료 상태를 반영한 docs/plan_revision_2026-10-01.md의 SHA-256은 7d5c103e25025c87d2c65e7cbc60ad5665a188f2f6d3baf76649ba3a26fc6503이다.

## 2. E2 재검사와 채택 범위

수정 기준은 main 템플릿 선언 파일 수가 2개 이상이어도 제자리 배치와 unit 배치의 canonical 경로가 1:1로 대응하고 각 대응 파일의 내용 SHA-256이 같으면 통과시키고 “원본 템플릿 중복”으로 표시하는 것이다. 두 배치가 다르면 실패한다. 같은 검사기로 B와 A를 새로 감사했고, B6d의 E1 닫힘 17/17, E3 R1CS 17/17, E4 바이트 17/17의 SHA 결박도 재검증했다. B6d unit은 source_root가 unit 부모이며, wrapper·entrypoint가 각각 preparation/·project/ 아래 한 사본이다. E1에서 허용한 clone 밖 -l 경로는 그대로다.

| B 리비전 | 쌍 | 요청 | 수정 E2 통과 | 원본 중복 쌍·요청 |
| --- | ---: | ---: | ---: | ---: |
| 340107e1f1d8b0a45656cffa | 2 | 4 | 2/2 | 0·0 |
| 4c221df76273c0d7cf18048c | 4 | 12 | 4/4 | 0·0 |
| 6079a717f929aaf04a04e329 (anon-aadhaar) | 3 | 9 | 3/3 | 3·9 |
| a8b2aa9c2857e79c017805bb | 4 | 70 | 4/4 | 0·0 |
| b5b5cf5dacdeebd430b519f8 | 4 | 12 | 4/4 | 0·0 |
| **합계** | **17** | **107** | **17/17** | **3·9** |

anon-aadhaar의 GreaterThan 선언은 원본·unit 모두 canonical 파일 2개에 있다. 검사기는 두 파일의 경로 대응·SHA를 확인했다. 이 9요청을 index에서 빼거나 프로젝트 파일을 고치지 않았다. 향후 엔진이 template_ambiguous를 반환하면 107 분모의 preparation_failure로 기록하고 “엔진 한계: 원본 프로젝트의 템플릿 이름 중복” 칸에 따로 센다. 실제 B 준비·판정 결과를 예단하지 않는다.

| A 리비전 | 요청 | 수정 E2 통과 쌍 | 실제 엔진 호출 | 원본 중복 요청 |
| --- | ---: | ---: | ---: | ---: |
| aq-006-1680f955c185 | 42 | 7/7 | 0 | 0 |
| aq-007-0bb83f9eab0f | 42 | 7/7 | 0 | 0 |
| aq-008-9c9e702d061d | 42 | 7/7 | 0 | 0 |
| aq-011-93343c3cd34c | 33 | 11/11 | 0 | 0 |
| aq-012-44d0df2ab46e | 24 | 8/8 | 0 | 0 |
| aq-016-0a7d49b1c135 | 24 | 8/8 | 0 | 0 |
| aq-017-9703bbce0c43 | 21 | 7/7 | 0 | 0 |
| aq-024-6f6781246415 | 24 | 8/8 | 0 | 0 |
| aq-025-70328d3fd35e | 27 | 9/9 | 0 | 0 |
| aq-026-2bcd7ed6110f | 27 | 9/9 | 0 | 0 |
| aq-035-8f826c822cb8 | 12 | 1/1 | 12 | 0 |
| aq-036-6d7df64759b6 | 604 | 2/2 | 604 | 0 |
| aq-037-94fe3080fc18 | 6 | 1/1 | 0 | 0 |
| aq-039-0ad3923f2f5b | 6 | 1/1 | 0 | 0 |
| aq-040-da54d3e7bc8a | 12 | 1/1 | 0 | 0 |
| banyan-fixed | 24 | 1/1 | 0 | 0 |
| banyan-vulnerable | 1807 | 3/3 | 0 | 54 |
| inference-c771c61c-p | 3 | 1/1 | 3 | 0 |
| inference-c79f42ee | 9 | 3/3 | 9 | 0 |
| inference-c9221e8d | 15 | 4/4 | 15 | 0 |
| inference-loo-clamp | 6 | 2/2 | 6 | 0 |
| inference-loo-dfs | 3 | 1/1 | 3 | 0 |
| inference-original | 69 | 10/10 | 69 | 0 |
| inference-r-intdiv | 26 | 7/7 | 26 | 0 |
| zkemail-fpmul-fixed | 9 | 1/1 | 9 | 0 |
| zkemail-fpmul-vulnerable | 9 | 1/1 | 9 | 0 |
| **합계** | **2926** | **121/121** | **765** | **54** |

A 중복 쌍은 banyan-vulnerable의 Blake3NovaTreePath_CheckDepth다. 실제 A 최종 요약의 해당 54요청은 전부 status=preparation_failure, reason=base_input_unavailable, result_path=null, 엔진 호출 0건이다. 따라서 A 관측 template_ambiguous 0건과 모순이 없다. A 엔진이나 판정은 재실행하지 않았다.

## 3. 새 index·정적 준비 검사

새 산출물은 runs/n6-b6e-2026-10-20.noindex/ 아래, B6d unit은 /Volumes/zkfdo-jcache/n6-b6d-batch1x/units/ 아래 그대로다. index 생성기는 기존 B6b 요청 JSON의 ID와 candidate 객체를 메타데이터로만 읽고 후보 파일은 열지 않는다. 독립 합성 검사에서는 후보 파일이 아예 없어도 107요청 생성이 성공했다.

| 산출물 | SHA-256 |
| --- | --- |
| equivalence-gate-v2.json | e7046f4df4794a352832c9ce08e847038a13dd6809210a0fd7b8ab83723fb060 |
| request-index-v1.json | 08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c |
| request-index-v2.2.json | 2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39 |
| request-index-pending.json | b991891f7b28e228f414812e4620e8ed527b35d9fe548b9e77e799dd3aecc3e7 |
| pilot-selection.json | b7d9cd476ccdf6bf870327e613dc9f61de8145a89978c13993957f96bf997bf8 |
| index-change-audit.json | c45053630b87ad0b18a158c5a3a2b002f63b4b3c502635918ad4d92b92e82c4f |
| request-diff-verified-v1.json | fece60afc2f473e63544b218f2eb836879d1887bc0151f85a3b4c1fcd4a89034 |
| static-preflight-96mib-v1.json | eb8241575399399ad46125452ff41bc21949d53df5bc8c5a93cf22ff5b6368cd |
| static-preflight-96mib-v2.2.json | 88c4a92bd627e138d2d77699e6a879e9f5a73729b3a241b6fafff89f966433d5 |
| static-preflight-v1.json (보존한 64MiB 실패) | 3f2440634b9976606d1a0abdf39591f2a384314087e1dc80016bec648345abe5 |
| static-preflight-v2.2.json (보존한 64MiB 실패) | 1ebbcaf6f05ae79c8a5056a254b9e446b39f0eb6958624a714ebd253f5b4ed42 |

107/107 요청 ID, 후보 객체·SHA-256, 구성 입력 경로와 구성 입력 index SHA-256은 기존과 같다. 별도 request-diff-verified-v1.json은 옛·새 요청 107쌍을 다시 열어 집합 차이를 계산했다. 요청 JSON에서 달라진 것은 source_root, entrypoint, component_wrapper, library_paths 네 필드뿐이며 네 필드 모두 107/107에서 새 unit 경로로 바뀌었다. index 기존 행에서 달라진 것은 request 경로·요청 SHA·wrapper 사본 SHA뿐이다. 원본 wrapper SHA도 새 행에 남겼다. v1과 v2.2 index 차이는 고정 engine 경로와 SHA뿐이다. “원본 템플릿 중복” 표시 9개는 index 행에만 있고 엔진 요청 JSON에는 0개다. 시범 선택은 기존 제약 수 규칙의 최대 queue 9, 최소 queue 25다. E3은 원래/사본 wrapper의 R1CS SHA가 17/17 동일함을 보였고 후보 ID·SHA 보존은 별도로 index에서 확인했다. 생성기와 실행기는 SHA 및 source binding을 각각 검사한다. 실제 validate-only는 후보 파일을 해시하므로 이 작업에서는 실행하지 않았다.

B6b 정적 검사기의 기본 64MiB 상한으로 만든 보존 보고 static-preflight-v1.json·static-preflight-v2.2.json은 각각 37통과·70실패였다. 실패는 a8b2aa9c…의 circom_byte_cap_exceeded뿐이다. B6d unit manifest에서 그 리비전의 최대는 227파일·78,022,826바이트다. B6b에서 이미 최종 채택한 상한은 2,000파일·96MiB(100,663,296바이트; docs/n6_b6b_source_root_fix_2026-10-19.md 84–86행)다. 같은 검사기에 그 상한을 명시해 새 이름으로 다시 검사하니 두 index 모두 107/107 통과했다. 겹침·일반 파일·symlink·복사 크기 검사 논리는 바꾸지 않았다. 실행기 관문은 최종 96MiB 보고서와 그 SHA를 요구한다. 실제 v1/v2.2 index에 대해 E1–E4 gate, 허용 필드 차이, 최종 정적 보고서의 읽기 전용 검증도 각각 통과했다.

## 4. 실행기와 분모

새 scripts/n6_b6e_j_runner.py는 고정 v2.2 8065e2b7 및 v1의 src/candidate_review/lifting/mod.rs에서 정의한 preparation reason 29종을 둘로 나눈다. 아래 줄 번호는 고정 v2.2 소스다. 회로·후보에 따른 실패는 status·reason·detail만 state에 기록하고 다음 요청으로 간다. 환경 사유, 자원 부족을 나타내는 detail, 목록에 없는 reason, 깨진 형식은 즉시 중단한다. component_compile_failed 등 혼합 사유라도 detail에 ENOSPC·ENOMEM·disk full·out of memory 등 자원 오류가 있으면 중단한다.

| 처리 | 고정 v2.2 mod.rs:줄 — reason |
| --- | --- |
| 기록 후 계속 (18종) | :517,562 candidate_invalid; :556,1424 candidate_missing_signals; :607 candidate_violates_component_constraints; :531 component_compile_failed; :543 component_inputs_unresolved; :550 component_outputs_unresolved; :1231 deviation_not_hint_assigned; :733,745 entrypoint_compile_failed; :869 hint_changes_constraints; :1189 hint_index_shape; :1163 hint_unsupported; :851 hinted_compile_failed; :781 no_call_site; :1168 reverse_hint_unsupported; :635 source_closure_unresolved; :642 source_parse_failed; :1368 template_ambiguous; :1366 template_unmatched |
| 즉시 중단 (11종) | :515 base_input_invalid; :512 base_input_missing; :536 component_artifacts_invalid; :575 component_witness_failed; :496 component_wrapper_missing; :750,755 entrypoint_artifacts_invalid; :499 entrypoint_missing; :564,587,641,757–759,821,836,852–862,915–925 io; :493 library_missing; :504 source_outside_root; :487 source_root_missing |

전체 실행 state와 값 비열람 결과 관문은 각 엔진의 107요청을 분모로 둔다. preparation_failure는 reason별 별도 칸에 두고, preparation.status=unknown인 두 내재 reason도 J verdict unknown으로 옮기지 않는다. 결과 관문은 두 엔진 완료 후 state의 status/reason/detail과 파일 SHA만 확인하며 verdict-bearing JSON을 파싱하지 않는다. 따라서 verdict_unknown_count는 null이고, 판정 값 분석은 이 관문 밖의 후속 단계다. 원본 중복 표시가 있는 요청의 template_ambiguous는 별도 원본 중복 칸에 센다. 시범은 preparation.status=ok와 형식 검사 통과를 요구한다. 두 시범이 통과해야 전체 실행이 열린다.

| 새 코드·검사 파일 | SHA-256 |
| --- | --- |
| scripts/n6_b6e_e2_equivalence.py | 8f742d57991fd4e5dfcb206186b4fd49eee07b39f621b7c41d8c822a9b6c2874 |
| scripts/n6_b6e_b_requests.py | 51aa2d507df1bb98d87ba44870f96cbee586ff24ee2941d1b5e07b13f6f09016 |
| scripts/n6_b6e_j_runner.py | 3ede8a5d691af29f813d4b7f806fca70429ff8a26d47e6ae678db4b4a3c45d3e |
| scripts/n6_b6e_format_pilot.py | 95089cf30f8698200eda99b51034549db61a1853b5b96056ca1e03e7273953fb |
| scripts/n6_b6e_result_gate.py | 170194bf966d21f05346d7399ca31d747cc830c4dce3c9f9428fd3dc55615983 |
| tests/n6_b6e_e2_equivalence_test.py | 804973d5592f401596a218eb8d8d4d4e6efaf29c9906d38c2f639f2a3a86745e |
| tests/n6_b6e_b_requests_independent_test.py | bf00699e6fc886f759013a143e47a19fb4e3aef65fc1e364ae8929451b1a992e |
| tests/n6_b6e_j_runner_test.py | ee5ebdc1c1fcf7bfd29fcaf54dc6ae3deddee9742a6630ac411dcfc65b4bd1dd |
| tests/n6_b6e_result_gate_test.py | 098410985361ed9f7e5f6d1ac2d5f8a04c26f26004e56cea3336896ff509973f |

Python 합성 단위 검사 30/30 통과: 원본 중복 SHA·경로 대응, 후보 파일 없이 ID/해시 보존, template_ambiguous 기록 후 계속, io·자원 부족·형식 오류 중단, 재시작 시 기록된 요청 미재실행, 값 비열람 결과 관문의 107 분모·reason별 집계를 포함한다. py_compile, git diff --check, cargo fmt, cargo clippy --all-targets --all-features -- -D warnings, cargo test가 통과했다. 고정 엔진·판정 규칙은 고치지 않았다.

## 5. N5 개정 연결

docs/n5_amendment_b_judging_2026-10-17.md의 “개정 기록”에 2026-10-20 KST, 수정·이유·승인자 miiz, “B 판정 값 열람 0건, 판정 엔진·규칙 불변”을 추가했다. E2의 원본 중복 허용을 J 전에 명시했다. 개정 SHA-256은 d89cbe837f48c41664446c17132d6d1464f5f7a01c5c7577f03cf12836d49607이고, 그 뒤 N5 연결 단락에 이 SHA를 기록한 docs/n5_evaluation_protocol_v1_2026-10-06.md SHA-256은 faf5c465584c3f3deeb2afd76db6be601fc361a7b2525092e7ffe6e14af2eb1a다.

## 6. miiz의 Kitty 실행 명령

아래는 준비된 명령이며 준비 단계에서는 실행하지 않았다. 실행 순서는 시범 → 전체 실행 → 결과 관문이다. 각 명령은 한 줄이다. 시범은 두 엔진의 validate-only를 거쳐 queue 9·25를 각 엔진에서 wait4로 실행한다. 전체 실행은 v2.2 다음 v1이며, 두 시범의 형식 통과 상태를 실행기가 확인한다. 결과 관문은 두 전체 실행이 완료된 뒤에만 통과한다.

시범:

~~~sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu zsh -c 'set -e; O="$PWD/runs/n6-b6e-2026-10-20.noindex"; X="/Volumes/zkfdo-jcache/n6-b6e-batch1x"; L1=9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e; L2=4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6; S=b7d9cd476ccdf6bf870327e613dc9f61de8145a89978c13993957f96bf997bf8; for E in v2.2 v1; do if [ "$E" = v2.2 ]; then I=2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39; P=88c4a92bd627e138d2d77699e6a879e9f5a73729b3a241b6fafff89f966433d5; else I=08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c; P=eb8241575399399ad46125452ff41bc21949d53df5bc8c5a93cf22ff5b6368cd; fi; python3 scripts/n6_b6e_j_runner.py --engine "$E" --index "$O/request-index-$E.json" --index-sha256 "$I" --static-preflight "$O/static-preflight-96mib-$E.json" --static-preflight-sha256 "$P" --first-lead-review-sha256 "$L1" --second-lead-review-sha256 "$L2" --cache-root "$X/cache/full-$E" --output "$O/full-$E.noindex" --action validate-only; python3 scripts/n6_b6e_format_pilot.py --engine "$E" --index "$O/request-index-$E.json" --index-sha256 "$I" --static-preflight "$O/static-preflight-96mib-$E.json" --static-preflight-sha256 "$P" --first-lead-review-sha256 "$L1" --second-lead-review-sha256 "$L2" --selection "$O/pilot-selection.json" --selection-sha256 "$S" --cache-root "$X/cache/pilot-$E" --workspace-root "$X/hint-workspaces" --instance-root "$X/instance-stores" --output "$O/pilot-$E.noindex" --action execute; done'
~~~

execute-all:

~~~sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu zsh -c 'set -e; O="$PWD/runs/n6-b6e-2026-10-20.noindex"; X="/Volumes/zkfdo-jcache/n6-b6e-batch1x"; L1=9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e; L2=4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6; for E in v2.2 v1; do if [ "$E" = v2.2 ]; then I=2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39; P=88c4a92bd627e138d2d77699e6a879e9f5a73729b3a241b6fafff89f966433d5; else I=08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c; P=eb8241575399399ad46125452ff41bc21949d53df5bc8c5a93cf22ff5b6368cd; fi; python3 scripts/n6_b6e_j_runner.py --engine "$E" --index "$O/request-index-$E.json" --index-sha256 "$I" --static-preflight "$O/static-preflight-96mib-$E.json" --static-preflight-sha256 "$P" --first-lead-review-sha256 "$L1" --second-lead-review-sha256 "$L2" --cache-root "$X/cache/full-$E" --output "$O/full-$E.noindex" --action execute-all; done'
~~~

결과 관문:

~~~sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu python3 scripts/n6_b6e_result_gate.py --v1-index-sha256 08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c --v2-2-index-sha256 2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39 --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b6e-2026-10-20.noindex/result-gate-v1.json
~~~

## 7. 공간·시간 계획

작업 시작 전 2026-10-20 04:46 KST 여유 공간: 내장 73,029,439,488바이트(68.014GiB), 외장 /Volumes/zkfdo-jcache 367,230,509,056바이트(342.010GiB). B6d unit 17쌍은 361,684KiB(0.345GiB). B6b Vota queue 9 시범의 외장 hint 출력은 288,428KiB(0.275GiB), 외장 cache는 3,541,032KiB(3.377GiB), 내장 요청 metadata는 12KiB였다. 이를 단순 산술로 214개 엔진 요청에 적용하면 hint 약 58.86GiB, 5리비전×2엔진 cache 약 33.77GiB와 unit 0.345GiB를 합쳐 약 92.98GiB에 시범·로그·추가 artifact가 더해진다. 한 요청·한 cache의 크기가 다른 리비전에도 같다는 보장은 없다. 실제 새 시범 뒤에 다시 계산한다.

시간 근거는 B6b Vota **v2.2 정상 시범 105.940235초(약 106초) 한 건뿐**이다. 회로·cache 조건이 다른 214건의 예측값으로 삼지 않고, 새 queue 9·25 두 엔진 시범 뒤 전체 실행 일정을 다시 계산한다. 실행기의 요청 직전 40GiB 여유 관문은 내장 runs 출력과 외장 cache, 외장 workspace·instance store 각각에 적용된다(scripts/n6_b6e_j_runner.py:499–500, scripts/run_n6_j1.py:345–354, scripts/n6_b6b_runtime_paths.py:24–35). 이 관문은 전체 추정 공간을 미리 예약하는 방식은 아니다.

## 8. 지시와 다른 점·열람 경계

- B6d 보고서의 A banyan-vulnerable 중복 쌍 “56요청”은 실제 A index·최종 요약상 54요청이다. 새 E2 감사와 이 보고서는 54를 쓴다.
- B6d 닫힘 감사가 SHA로 묶은 제자리 배치 원본 index는 B6의 request-index-v1.json(b2b9da31…)이고, 새 B6e 요청의 직접 원본은 B6b의 request-index-v1.json(1bfcb71d…)이다. 새 gate는 두 계보를 따로 결박한다.
- B6b 정적 검사기의 코드 기본값 64MiB로는 70건이 실패한다. B6b 보고서에서 실측 후 채택한 96MiB 상한을 같은 검사기의 CLI 옵션으로 지정하고, 실패 보고는 보존했다.
- B6e 결과 관문은 preparation 메타데이터만 집계하므로 J verdict unknown 수는 null이다. B 판정 값을 읽어야 하는 후속 분석에서 별도로 센다.
- 새 index 검증기의 실제 validate-only는 후보 파일과 구성 입력 파일을 해시한다. 준비 단계에서는 이를 실행하지 않고 메타데이터 비교·합성 단위 검사·정적 복사 검사를 수행했다. miiz용 시범 명령에 validate-only를 넣었다.

B 후보 값·판정 값·J 작업 폴더 내용은 열지 않았다. B J 시범·전체 실행, 재퍼징, 의존성 설치, commit·push·PR은 하지 않았다. 기존 B6d unit·대조 파일과 기존 출력은 삭제하거나 덮어쓰지 않았다.

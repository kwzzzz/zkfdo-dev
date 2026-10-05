# C-02 평가 후보 자동 준비 조사

담당: miiz · 기한: 2026-10-10 · 준비 적용성 조사, zkFuzz 미실행.

[선정 절차](c02_corpus_procedure_2026-10-02.md) · [기계 판독 결과](c02_corpus_results_2026-10-02.json)

공유 JSON은 schema 2의 진단 집계 표현이다. [schema 1 확장 원본](../runs/c02-corpus-2026-10-02/summaries/results-expanded-v1.json)을 해시에 연결해 보존하고, 네 종류의 반복 진단 배열만 사유·상태별 발생 수로 축약했다(559,199,412 → 최종 검사 참조를 포함한 58,160,210 bytes). 길이 4 미만 배열과 `null`은 유지하며, 집계 객체는 `representation`·전체 발생 수·원본 JSON pointer를 갖는다. 개별 진단 순서·위치가 필요하면 확장 원본을 읽는다. 저장소·entrypoint·상태·제약 수·시간·수정 이력·측정 참조·전역 통계가 동일함을 [축약 검증](../runs/c02-corpus-2026-10-02/summaries-projection-verification.json)에 남겼다. 진단 발생 수는 독립 실패·후보·원인 수가 아니다.

| 출처 | 고정 쿼리·목록 범위 | 검색·조회 시각 UTC | revision / 근거 |
|---|---|---|---|
| GitHub top200 | `language:Circom; sort=stars; order=desc; per_page=100; page=1` | 2026-10-02T06:00:37.873052+00:00 | [검색 메타데이터](<../runs/c02-corpus-2026-10-02/github-search-page-1-network.meta.json>) |
| GitHub top200 | `language:Circom; sort=stars; order=desc; per_page=100; page=2` | 2026-10-02T06:00:40.982044+00:00 | [검색 메타데이터](<../runs/c02-corpus-2026-10-02/github-search-page-2-network.meta.json>) |
| zkbugs | 전체 DSL 프로젝트 목록 (44 repo; Circom 27) | 2026-10-02T06:00:45.337807+00:00, 2026-10-02T06:01:15.858082+00:00 | `212cc500b7cf1a2221d3e42ff47baff453afd070`; [목록 근거](<../runs/c02-corpus-2026-10-02/catalog_sources.json>) |
| sok_2026 | 전체 DSL 프로젝트 목록 (43 repo; Circom 27) | 2026-10-02T06:00:45.883752+00:00, 2026-10-02T06:01:16.557423+00:00 | `d1f198143e2f079b7e8207063de557003305aa70`; [목록 근거](<../runs/c02-corpus-2026-10-02/catalog_sources.json>) |

출처층은 중복된다. 비율의 분모는 포함 저장소에서 확인한 고유 entrypoint 파일 전부이며, 미시작·실패도 남긴다.

| 층 | 저장소 | 포함/제외/불명 | entrypoint 파일 | 컴파일 성공 | 완전 자동 준비 |
|---|---:|---|---:|---|---|
| 전체 | 239 | 65/168/6 | 3470 | 2296/3470 (66.2%) | 845/3470 (24.4%) |
| github_top200 | 200 | 52/147/1 | 3265 | 2293/3265 (70.2%) | 842/3265 (25.8%) |
| zkbugs | 44 | 16/23/5 | 412 | 68/412 (16.5%) | 25/412 (6.1%) |
| sok_2026 | 43 | 16/22/5 | 412 | 68/412 (16.5%) | 25/412 (6.1%) |
| development_used | 8 | 4/2/2 | 86 | 48/86 (55.8%) | 15/86 (17.4%) |
| known_bug_listed | 36 | 12/21/3 | 326 | 20/326 (6.1%) | 10/326 (3.1%) |
| unexposed_by_lists | 194 | 48/145/1 | 2945 | 2176/2945 (73.9%) | 801/2945 (27.2%) |
| unknown | 1 | 1/0/0 | 113 | 52/113 (46.0%) | 19/113 (16.8%) |

상태: `complete_known_inventory`. 미기록 entrypoint 0개. 구현 오류 후 hash 연결 수정 76개; 원본 컴파일을 재사용하고 탐색 재실행 여부와 v1 기록을 보존한다.

Controller 중단 이력 2개; discovery 재실행 2개. 중단·실패 시도도 all_recorded_stage_attempts에 포함하며, 미측정 중단 wall을 0으로 대체하거나 재실행 이전 비용을 삭제하지 않는다.

저장소별 컴파일 하나 이상: 40/65 (61.5%); 알려진 파일 모두: 19/65 (29.2%). 자동 준비 하나 이상: 24/65 (36.9%); 알려진 파일 모두: 1/65 (1.5%).

| 완전 자동 준비 성공 구분 | entrypoint 파일 수 | 전체 알려진 파일 분모 |
|---|---:|---:|
| root-only: 조각 없음 | 448 | 3470 |
| 하나 이상 자동 조각 있음 | 397 | 3470 |

root-only 성공은 컴포넌트 분해 성공을 입증하지 않는다. 조각 수는 고유 wrapper 컴파일 단위이며 호출 위치 수나 독립 프로젝트 수가 아니다.

| 단계 | 성공 | 부분 | 실패 | timeout | 중단 | 미시작 | 미지원 | 기타·불완전 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 원본 컴파일 | 2296 | 0 | 1168 | 6 | 0 | 0 | 0 | 0 |
| 자동 탐색 | 3470 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| 자동 준비 | 845 | 829 | 1468 | 0 | 0 | 0 | 328 | 0 |
| 계획 생성 | 1674 | 0 | 1468 | 0 | 0 | 328 | 0 | 0 |

자동 탐색의 성공 3,470건은 `targets` 명령이 정상 종료했다는 뜻이다. 탐색 완전성이나 전체 wrapper 컴파일 성공을 뜻하지 않으며, 미지원 진단·호출 위치 실패를 보존한 완전 자동 준비 판정은 별도 행에 있다.

| 원본 제약 수 | entrypoint 파일 수 |
|---|---:|
| 0 | 50 |
| 1–999 | 1305 |
| 1,000–99,999 | 728 |
| ≥100,000 | 213 |
| unknown | 1174 |

관측 2296개에서 최소/중앙/최대: 0/267.000/12,409,130. 컴파일 실패·미시작·수치 결측은 0 제약으로 바꾸지 않는다.

| 단계의 기록된 시도 | 시도 수 | wall 알려짐/불명 | 알려진 wall 합(초) | 전체 시도 wall 합(초) |
|---|---:|---|---:|---:|
| compile | 3470 | 3470/0 | 5,803.506 | 5,803.506 |
| discovery | 3472 | 3470/2 | 9,421.204 | unknown |
| preparation | 3142 | 3142/0 | 21,193.634 | 21,193.634 |
| plan | 3142 | 3142/0 | 427.289 | 427.289 |

시도 wall의 합은 병렬·중첩 실행이 있는 조사 전체 wall이 아니다. 동일 원본 로그를 재사용한 항목은 한 번만 세고, 재실행과 과거 중단 비용은 보존한다. 미측정 비용이 있으면 전체 시도 합은 unknown이다.

| 원본 컴파일 실패 유형 | 보정 후 건수 | 원래 분류 건수 |
|---|---:|---:|
| assertion_or_type | 30 | 43 |
| compiler_or_tool_error | 154 | 1093 |
| compiler_version | 12 | 12 |
| missing_include | 952 | 0 |
| non_quadratic | 20 | 20 |
| timeout | 6 | 6 |

오류 코드 P1014의 missing_include 보정 952건. 원래 분류와 해시 검증된 compiler 로그 참조를 함께 보존한다. 로그·소스 문구는 공유 결과에 복사하지 않는다.

| 미지원·준비 진단 세부 유형 | 탐색 진단 발생 | wrapper 호출 위치 진단 발생 | 준비 진단 발생 |
|---|---:|---:|---:|
| compile_time_variable_array | 80399 | 0 | 20677 |
| component_in_while_loop | 46 | 0 | 46 |
| component_reassignment | 7988 | 0 | 908 |
| definition_include_closure_contains_main | 0 | 2581 | 0 |
| other_or_unclassified | 14670 | 34992 | 35949 |
| target_expansion_limit | 2 | 0 | 2 |
| template_parameter_arity | 1 | 0 | 1 |
| unresolved_compile_time_value | 87585 | 0 | 28039 |
| unresolved_template_definition | 679632 | 0 | 18966 |
| unsupported_compile_time_expression | 24419 | 0 | 2678 |
| unsupported_compile_time_loop | 3789 | 0 | 5659 |
| unsupported_component_array | 2744 | 0 | 4141 |
| unsupported_component_index | 1134 | 0 | 4178 |
| unsupported_template_parameters | 1469 | 0 | 764 |

세부 유형은 저장된 진단 발생 횟수다. 한 entrypoint에 여러 진단이 있거나 탐색·준비 층에 같은 사유가 반복될 수 있으므로 독립 실패 수로 합산하지 않는다. 사유 결측은 unknown으로 보존하며 소스 식·식별자·값을 공유하지 않는다.

| 수동 개입 집계 | 기록된 건수 | 개입 수 미확인 기록 |
|---|---:|---:|
| 저장소 준비 | 0 | 0 |
| entrypoint 측정 | 0 | 0 |

수동 개입 0건은 대상 저장소의 의존성 설치·소스/include 수선을 하지 않았다는 뜻이다. 위의 계측 어댑터 수정과 해시 연결 기록 76건은 별도의 조사 도구 수정 이력이다.

분모 3470개는 알려진 main 파일 경로이며 독립 production 회로 수가 아니다. 확인한 benchmark/dataset 저장소 묶음(ArmanKolozyan/CCC-Check 1126, dangduongminhnhat/Circheck 730, zksecurity/zkbugs 113)의 파일 비중은 1969/3470 (56.7%)다. 이 묶음은 저장소 기준으로, 모든 경로의 용도를 개별 확정한 것은 아니다.

경로 역할: example 53, test 1925, unclassified 1494, vendor_or_dependency 333. 역할 표시는 서로 중복되며 unclassified를 production으로 해석하지 않는다. 포함 저장소 중 inventory 불완전 10개는 추가 main의 수가 unknown이다. 목록상 미노출은 모든 과거 노출 부재의 인증이 아니며, 이번 소스·준비 노출을 되돌리지 않는다.

아래는 축약 경로 추가 후 현재 작업 트리에서 다시 수행한 최종 검사다([명령·소스 해시·로그 해시](../runs/c02-corpus-2026-10-02/checks-final/checks.json)). 최초 집계 JSON의 `checks`는 당시 Rust 315개·Python 45개 검사 이력을 보존한다. 최종 Python 49개는 기존 45개와 축약 회귀 4개를 포함하며 이전 검사 수와 합산하지 않는다. 최종 검사 전후 `src/candidate_review/lifting/`의 파일 해시는 동일하다.

| 검사 | 기록 상태 | 확인된 결과 | 근거 |
|---|---|---|---|
| cargo_fmt | passed | exit 0 | [로그](<../runs/c02-corpus-2026-10-02/checks-final/cargo_fmt.log>) |
| cargo_clippy | passed | exit 0 | [로그](<../runs/c02-corpus-2026-10-02/checks-final/cargo_clippy.log>) |
| cargo_test | passed | 316 passed / 0 failed / 22 ignored | [로그](<../runs/c02-corpus-2026-10-02/checks-final/cargo_test.log>) |
| python_metadata_tests | passed | 49 tests / 1 suites | [로그](<../runs/c02-corpus-2026-10-02/checks-final/python_c02_tests.log>) |

| 저장소 | 출처 | 노출층 | 포함 상태/사유 | entrypoint 파일 | compile | prepare | SHA |
|---|---|---|---|---:|---|---|---|
| 0xbok/circom-bigint | zkbugs, sok_2026 | development_used | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 4f78084327e993136edb2a8f4bd52ffbb437ab78 |
| 0xja-eth/inft-zkp-scheme-starter-kit | github_top200 | unexposed_by_lists | included | 4 | 4/4 (100.0%) | 0/4 (0.0%) | 347d8de1df3a5eb6d0e89811c61ae771562c49bb |
| 0xPolygon/pil-stark | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 51ee688ca1c56efe4c253a2f9f89cb1549a1a2cb |
| 0xPolygonHermez/stark-recurser | github_top200 | unexposed_by_lists | included | 19 | 5/19 (26.3%) | 2/19 (10.5%) | f586bd2cc566a3629567f7707286977aba72b0e5 |
| 0xPolygonHermez/zisk | zkbugs | known_bug_listed | excluded: no_component_main_declaration | 0 | 0/0 (unknown) | 0/0 (unknown) | 306a9c934ba4947b1d586d69b67120f8b4c41466 |
| 0xPolygonHermez/zkevm-proverjs | zkbugs, sok_2026 | known_bug_listed | included | 2 | 0/2 (0.0%) | 0/2 (0.0%) | 5ea957120d3a0361e9f3438562c526e774b2f693 |
| 0xturboblitz/totem | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | db33737b97fdfbfd8289f0f550c2625d59c15483 |
| 2dvorak/zk-jwt-poc | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | db8e58a28bd0b4571f54f4e8cb5ebe4baef1d574 |
| aayush4vedi/ZKWhisper | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | fcf47019f0ec565a54d861150c1b043526e9a555 |
| AB7zz/zk_dapp_multiplier | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | a08f02c89aa66c0b60842347cc5895592c68f89b |
| adompeldorius/springrollup | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 8a01c439fcb8c55907854b417526dc040e57c41f |
| AkshatGada/jpmc0 | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | feed5dfdab7b804064b1f71d900f6b13eaf25fa2 |
| alejandro99so/eerc-backend-converter | github_top200 | unexposed_by_lists | included | 5 | 5/5 (100.0%) | 0/5 (0.0%) | 4e457e0746573795cb58616f149091a40a534113 |
| alexbabits/circom-puzzles | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 167d8bab578338b43c073764cee69078f6bd367c |
| alexcostars/paillier-circom-circuit | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 17e9e426b051e215ef8d9d15d5cb0048bcc455bd |
| alinush/circom-stdlib | github_top200 | unexposed_by_lists | included | 33 | 0/33 (0.0%) | 0/33 (0.0%) | 767e9eb59b7e41aa1bfea467bf40081ddbb43b20 |
| AmirH-A/RLP | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | f558912799827d7e1fa0986ba7534eadab102b4f |
| Apocentre/circom-libs | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 05c0f97a9603790090ff5d2a9d9483cf4c7e8b85 |
| Apocentre/zkin-circuit | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 6b4a811f3f1197b89c163a0f340c6f244a74337c |
| aptos-labs/keyless-zk-proofs | zkbugs, sok_2026 | known_bug_listed | included | 67 | 1/67 (1.5%) | 1/67 (1.5%) | dc10a064d309db23c2459cf318032e095b8c5a8d |
| Arianee/arianee-sdk | zkbugs, sok_2026 | known_bug_listed | included | 3 | 0/3 (0.0%) | 0/3 (0.0%) | 2ea08a45957080a26ffd765356416afa66d9399b |
| arkworks-rs/r1cs-std | zkbugs, sok_2026 | known_bug_listed | excluded: no_circom_files_in_pinned_tree | 0 | 0/0 (unknown) | 0/0 (unknown) | 45e4e2697626a9f9481fe57e70ed29c687194102 |
| ArmanKolozyan/CCC-Check | github_top200 | unexposed_by_lists | included | 1126 | 916/1126 (81.3%) | 367/1126 (32.6%) | 7ed87b8c17d8fc882cd42e86ad784eb68c1442e5 |
| ava-labs/EncryptedERC | github_top200 | unexposed_by_lists | included | 5 | 5/5 (100.0%) | 0/5 (0.0%) | 8dc98cd4d63ad3aa6d86b70b8f4bbcd70f1e8be1 |
| aviggiano/circom-mutator | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | e915f8d819b814541155f1a35a9f53702e41fc9c |
| bankisan/zkShield | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | acb853cef2d2cf659540879c0e2535fc85b91381 |
| banyancomputer/hot-proofs-blake3-circom | zkbugs, sok_2026 | development_used | included | 4 | 0/4 (0.0%) | 0/4 (0.0%) | e37eb56e29b304024055f3d0a1681e6f22132ecc |
| bauti-defi/Zk-MerkleTree | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 47e228b32540a42c70a08d6ecbc9d4cbdd69b7bb |
| BigWhaleLabs/seal-hub-ecdsa-verifier-contract | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | c811039edb27f1000f2bd459a3472111d2a0685a |
| Bitcoin-Wildlife-Sanctuary/circle-plonk-recursive-verifier-circom | github_top200 | unexposed_by_lists | included | 11 | 11/11 (100.0%) | 1/11 (9.1%) | b4c2210d18c62fd399e453a7b51811caea2fbad1 |
| BlocSoc-iitr/Deimos | github_top200 | unexposed_by_lists | included | 118 | 112/118 (94.9%) | 16/118 (13.6%) | d4049fb0734493d738f151ec26265df885a03963 |
| bnzk-labs/Bnzk-circuit | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | add86e787f699a30525571dd1a0908487c499bac |
| Brivan-26/B5GRoam | github_top200 | unexposed_by_lists | excluded: license_absent | 1 | 0/0 (unknown) | 0/0 (unknown) | 3df2fd95b3fdc21f8e6e804cab2255907cf13724 |
| bunsenstraat/chainlink-workshop | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 9ded99d1aa483770cc816d0f0df2c8bd26134421 |
| celo-org/self | github_top200 | unexposed_by_lists | included | 79 | 0/79 (0.0%) | 0/79 (0.0%) | f63ee37118192a07fa7ecfa37d937e02675427f8 |
| chainwayxyz/railgun-proof-of-innocence-circuits | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | ec2b2654329eef2fd05cd00e19dcd86fd51abb5f |
| Consensys/gnark | zkbugs, sok_2026 | known_bug_listed | excluded: no_circom_files_in_pinned_tree | 0 | 0/0 (unknown) | 0/0 (unknown) | 89720c22c66cb33601ba0ed355727f40da8ff811 |
| costa-group/ProgCrypto2023 | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 728d9df2b4e4c2ed1a8601f287ab9881b9be8f0d |
| crema-labs/aes-circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | ec54b9b61c4fa75fcdc7c7a1513fc06b16dd272b |
| crema-labs/ecdsa-p384-circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 1a6c09b469df723d02de7181a153efb937e80838 |
| crema-labs/ecies-circom | github_top200 | unexposed_by_lists | excluded: license_absent | 0 | 0/0 (unknown) | 0/0 (unknown) | 809788667de97de76162858093eb433cbf3bfe8a |
| dangduongminhnhat/Circheck | github_top200 | unexposed_by_lists | included | 730 | 615/730 (84.2%) | 220/730 (30.1%) | 8e7a5d2a87505fd57042c00cebbcbe558f152427 |
| darkforest-eth/darkforest-v0.3 | zkbugs, sok_2026 | known_bug_listed | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | ca1582efc21940132bf1432f3ed85f5c09ed0a56 |
| darth-cy/NFTA-Tornado-Resources | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | e48022c54a2b7cb77e80ab40489039f55ff9d708 |
| didnet/zxDID | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | d2f6b2daf1f15aa6dccf6201ad5ea6e24bcb9f67 |
| distributed-lab/circom-dl | github_top200 | unexposed_by_lists | included | 92 | 90/92 (97.8%) | 46/92 (50.0%) | 472d489acb25769b9aab65e151fc239ae08c87b0 |
| distributed-lab/circom-g4-grammar | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 7cb6d989b49502097c8a294a887bf17e4f1fdcca |
| dl-solarity/circom-lib | github_top200 | unexposed_by_lists | included | 91 | 91/91 (100.0%) | 46/91 (50.5%) | 52582589d667c9102dcd63494464eaa29560558b |
| dl-solarity/zktype | github_top200 | unexposed_by_lists | included | 7 | 6/7 (85.7%) | 5/7 (71.4%) | 12cee03d362c7b9ede415c1ba3abd08170b41b95 |
| dmpierre/eth-private-market | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | fb843c99cb35f83e17e95908039cc3283e455d5d |
| dmpierre/sha1-circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | fe18319cf72b9f3b83d0cea8f49a1f04482c125b |
| DoraFactory/Vota-Circuits | github_top200 | unexposed_by_lists | included | 62 | 0/62 (0.0%) | 0/62 (0.0%) | 916579f6063b69dfd3cc2fce406888024faf7ecf |
| doutv/circom-benchmark | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 58c00beea2be15e526792a42430bec122614c758 |
| ekrembal/halo2-tornado-nova | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 6998e9ca46c202d9a9c95808a6498b193f339708 |
| EkuboProtocol/privacy-pools | github_top200 | unexposed_by_lists | included | 2 | 2/2 (100.0%) | 0/2 (0.0%) | fdaadcf673dfde5e22b173f4ab0a0bd071407682 |
| erhant/circom101 | github_top200 | unexposed_by_lists | included | 43 | 30/43 (69.8%) | 25/43 (58.1%) | 06bab1d67ce464a0f23e1eb094b1957379928bc5 |
| erhant/zkbrainfuck | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 8162cf318ad05842815a80056c1761a0c679920c |
| erhant/zkctf-scalebit | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 3b302b00851083d4f23a799d17108c766fd4588e |
| eryxcoop/cardano-zk-aiken | github_top200 | unexposed_by_lists | excluded: license_absent | 4 | 0/0 (unknown) | 0/0 (unknown) | eb58761593feb582fa3808ce08d2cc0aa349564e |
| filecoin-project/rust-fil-proofs | zkbugs, sok_2026 | known_bug_listed | excluded: no_circom_files_in_pinned_tree | 0 | 0/0 (unknown) | 0/0 (unknown) | d451d23ba6dcabd107e66b2f9c6531887b17fd3d |
| Flamki/setu-stellar-zk | github_top200 | unexposed_by_lists | included | 8 | 5/8 (62.5%) | 0/8 (0.0%) | f3b5d2ed29290a10d7a0e29aee7490136b9ecbdf |
| FlynnSC/zk-hunt | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 3965203107a8aa9e0df9f7d809b0ccc05ce64c6a |
| Galxe/identity-protocol | github_top200 | unexposed_by_lists | included | 55 | 48/55 (87.3%) | 15/55 (27.3%) | ae64be8caa1b0bc116e81f77a555bbbf68668566 |
| Gerson2102/PSE-Core-Program | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | b8e50988deccc1f0c553785ce551afa8997fde29 |
| HerodotusDev/offchain-evm-headers-processor | zkbugs, sok_2026 | known_bug_listed | unknown: main_in_uninitialized_submodules_unknown | 0 | 0/0 (unknown) | 0/0 (unknown) | 5d6093bdd5d689fe0b3f4ae562aee6fbe7d908e8 |
| Hmac512/circom-chacha20 | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 8ec9b9f7496b25165ed4d08b30007d36e2767d94 |
| holyaustin/Filecoin-Forge | github_top200 | unexposed_by_lists | included | 5 | 5/5 (100.0%) | 1/5 (20.0%) | 119abc19195bdcec18b1b11f1c024ed6399d87cc |
| holyaustin/ZeroSecret | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | f7724eca1ccdb41357a36209c37b5d42189b6019 |
| htried/zkp-ldp | github_top200 | unexposed_by_lists | included | 117 | 0/117 (0.0%) | 0/117 (0.0%) | 1e01b123bc99f53062c5408d11f27d4396228c22 |
| hypersign-protocol/zk-kyc-using-ibc | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | bd39b5360e8622034619dceae7ec20c44891020c |
| hyunsooda/zk-practice | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | c5a31847266273b646526231e06d52dba1dd65fe |
| iamnov1ce/simper_mixer | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | ab2b02c7360aba8b708d34be0af46acb834d6282 |
| iden3/circomlib | github_top200, zkbugs, sok_2026 | development_used | included | 48 | 48/48 (100.0%) | 15/48 (31.2%) | 35e54ea21da3e8762557234298dbb553c175ea8d |
| iden3/circuits | zkbugs, sok_2026 | known_bug_listed | included | 48 | 0/48 (0.0%) | 0/48 (0.0%) | 360715607a240041f49eb46c543fc450051c4cb7 |
| inference-labs-inc/subnet-2-circom | github_top200, zkbugs, sok_2026 | development_used | excluded: license_absent | 1 | 0/0 (unknown) | 0/0 (unknown) | 1dc2ee2c423ff8f10bac6b315a21db6678b69750 |
| ingonyama-zk/celer-gnark-circomlib | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 8911213895500cf9aef6f6c9aa318fbc085d7d3f |
| invisibook-lab/invisibook | github_top200 | unexposed_by_lists | included | 6 | 6/6 (100.0%) | 0/6 (0.0%) | 61aa8bd70a7196616b4dbc3c4a3a3440c6506799 |
| IreneBa26/ZK-AnonVoting | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 778007b55c5771c29999cac132b13d345954a274 |
| jatinsahijwani/zk-ava-sdk | github_top200 | unexposed_by_lists | included | 49 | 49/49 (100.0%) | 15/49 (30.6%) | 52dede498dd45e125f5d7fbb8ef1ca6621f85b22 |
| jatinsahijwani/zkArb-sdk | github_top200 | unexposed_by_lists | included | 54 | 50/54 (92.6%) | 17/54 (31.5%) | addc9b6c621de9281119d7c40d79ad2df05432c1 |
| jmagan/poseidon-bls12381-circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | d4f60a7ee906aa2aa06179d6a3d2b7a8dbb2b36e |
| jonas089/circom-keygen-exercise | github_top200 | unexposed_by_lists | excluded: license_absent | 1 | 0/0 (unknown) | 0/0 (unknown) | e9a690f2a8d62ef1fc346da7574094188d1d350f |
| jose-compu/opencircom | github_top200 | unexposed_by_lists | included | 51 | 51/51 (100.0%) | 21/51 (41.2%) | 4e252abf491a3c5715425fed2a30074d43e111c3 |
| Jubzinas/Ouragan | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 475d0046ecf9fb6c07275b6cd436b6e5c758fa7c |
| Koukyosyumei/PwnableProof | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 459bfef6aaeebc367f56df5329d1877054e8c665 |
| kr1983/zklogin-circuit | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | ce9cb1dc223efeab56fd70397bba10973c5f6496 |
| kroma-network/circomlib | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | b040af932308aa7b6e9d034cc43c18bea4ed1ab4 |
| kskhasegawa/circom-rangeproof-for-vc | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | d95fab441f503ff6dfa851575fabc9c2b5cd4526 |
| lakhwani/cscd71 | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 3488ae17a36d41936cc81ff4fe97b08c65fd5978 |
| LBruyne/circom-bench | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | ee25a4420922cfecd75803c19de2977007fc44e9 |
| liyue201/gnark-circomlib | github_top200 | unexposed_by_lists | excluded: no_component_main_declaration | 0 | 0/0 (unknown) | 0/0 (unknown) | a38612a61e22359559b4b007b202860ee64cd414 |
| logos-storage/circom-goldilocks | github_top200 | unexposed_by_lists | included | 1 | 1/1 (100.0%) | 0/1 (0.0%) | 61d68e61e487733e2d307acf6ff5bca4df399449 |
| Lorenz29/anon-ar | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 56ef2b99cc4e1f45c4e4f4f4a56bf6db35e9c19c |
| lurk-lab/lurk-rs | zkbugs, sok_2026 | known_bug_listed | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 399c4f361dd6ded8d08d7ab9f37b273984679fe8 |
| lurk-lab/neptune | zkbugs, sok_2026 | known_bug_listed | excluded: no_circom_files_in_pinned_tree | 0 | 0/0 (unknown) | 0/0 (unknown) | b06f03c5abcb6ff72625349572b21241956d55df |
| lyronctk/zator | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 0c69c8f2305ac4d8601ed171ebb11c0d75d1a39d |
| MatteoMer/onchain-2fa | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | f6eef72cec26d70c97bc8364910b68dd66f7c89b |
| MicrochainLabs/limited-scope-account-circuits | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 4520296565101125d7f95cba77059805e86cf04d |
| microsoft/crescent-credentials | github_top200 | unexposed_by_lists | unknown: main_in_uninitialized_submodules_unknown | 0 | 0/0 (unknown) | 0/0 (unknown) | c211367088ff568309546db088430fd293d9304a |
| Miny-Labs/benzo | github_top200 | unexposed_by_lists | included | 5 | 5/5 (100.0%) | 0/5 (0.0%) | 87c8cecdd677d2fc30f732359ed3cec679f67d39 |
| mohaminemed/zkRoam | github_top200 | unexposed_by_lists | excluded: license_absent | 1 | 0/0 (unknown) | 0/0 (unknown) | 4a7b1511d66b7c7ec5be9c8fb7a7ee6807926112 |
| Moonsong-Labs/zksync-social-login-circuit | zkbugs, sok_2026 | known_bug_listed | included | 4 | 0/4 (0.0%) | 0/4 (0.0%) | 61521a98df28eee817854716c1fee0cdfd3b7bdb |
| mottla/Blind-Schnorr-Signatures | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 33927eeb583207294a4f371417597f59978446d7 |
| motxx/selective-disclosure-sandbox | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 5a8a1755b1d60281f79248b5b9454189a2a42d16 |
| new-biiee/zk-guard | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | e573cfdde24c56c9552377c6d4f8bf49e8e9b3a5 |
| ninjra/aion-cycle | github_top200 | unexposed_by_lists | included | 1 | 0/1 (0.0%) | 0/1 (0.0%) | acc8fba43da897fbd94baac615c64d9c8adce07c |
| nixkitax/circom-schnorr-verify | github_top200 | unexposed_by_lists | included | 2 | 2/2 (100.0%) | 0/2 (0.0%) | 8eb2b9ad104b85c27d06cf830ef637a18723c5cb |
| nobitex/sigmab | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 66704167660b2c7f2a9797cb4c22e5552a3a166f |
| nocturne-xyz/protocol | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | b750bc45a87bb65dfe0a1a3e0ebb0141b63b1138 |
| noir-lang/zk_bench | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 6b1ccb64f548072174ff122588bbd70ce0ccbba4 |
| Notebook-Labs/CashApp-Zephyr | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 33e782e2d51b9552e63e4e83b5358a0bbbf7c1a5 |
| Notebook-Labs/GooglePay-Zephyr | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | d9359783b50768c91e88838a7f52c455e004bc30 |
| NP-Eng/ligero | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 472e7e1af85f9db0bcb44557112ff9d549490ad6 |
| nullity00/batch-ecdsa-secp256r1 | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | c8aefe6c49ac00b5eef83f659a83d3bb45d6d4f2 |
| nullity00/circom-circuits | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | c330d0bf87ff4ec4046aa238b085d5f4d918b6f2 |
| openvm-org/openvm | zkbugs, sok_2026 | known_bug_listed | unknown: main_in_uninitialized_submodules_unknown | 0 | 0/0 (unknown) | 0/0 (unknown) | f08bf2836409f3c0a5f6b6cfe73eb177a8a3e8c8 |
| Orbiter-Finance/stark-snark-recursive-proofs | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 9034341668dae8853bada232e296332c5a69ab30 |
| ouromoros/rlp-circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | dbac3166951e9ff6c172c623b8d852377572f71b |
| oxor-io/circom_workshop | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 6ad6dc84b9e6357d5eafe9b6e0132b896808953a |
| oxor-io/sam-circuits | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 3bacf9b3980bb09917c0415f25390f9923bc84a3 |
| p51lee/zkLeeVM | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | fc12eadbd52014f73c225462485f893573a0931e |
| pantherfoundation/panther-core | zkbugs, sok_2026 | known_bug_listed | included | 23 | 1/23 (4.3%) | 1/23 (4.3%) | 0b078c8398de69a21b77e24405d86bdf3401fc82 |
| penumbra-zone/penumbra | zkbugs, sok_2026 | known_bug_listed | excluded: no_circom_files_in_pinned_tree | 0 | 0/0 (unknown) | 0/0 (unknown) | 36a31c17974c23a7e84cc02c64f0062ae57e79b1 |
| PepperSieve/nope | github_top200 | unexposed_by_lists | included | 41 | 41/41 (100.0%) | 0/41 (0.0%) | 08567b93f83798ce339da591f0ae73937d87db66 |
| personaelabs/spartan-ecdsa | zkbugs, sok_2026 | known_bug_listed | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 4bf236a1a556d450d8daff4451e79757858f6df1 |
| perturbing/plutus-plonk-example | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | b3ac5db7c487b93b261355c25df0e8edb74610c4 |
| philsippl/semaphore-witness-example | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | c83d277c2c71bb68971413bf768c8d7397e5e331 |
| pierpaolodm/Privacy-PreservingProofs4EditedPhotos | github_top200 | unexposed_by_lists | excluded: no_component_main_declaration, license_absent | 0 | 0/0 (unknown) | 0/0 (unknown) | da4d23d70475b48ad134b0cfa40b70d643f65e81 |
| pileum-eu/pileum-connect-circuit | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | ca033f92dc150985911f079dd101324935047968 |
| pisuthd/circom-example | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 7a9cc7ff0b2ded684d5808a30fe12e847849e99a |
| plsdlr/geheimnis | github_top200 | unexposed_by_lists | excluded: no_component_main_declaration | 0 | 0/0 (unknown) | 0/0 (unknown) | f5b9cbf89acc6a40d89ed65a0784212893b51c01 |
| pluto/aes-circuits | github_top200 | unexposed_by_lists | included | 1 | 0/1 (0.0%) | 0/1 (0.0%) | 6539eafbe5a29e22e8851ed5392f31c960c79dbb |
| pluto/circom-correctly-constrained | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | d5cb86b32ffd652a46be1f0427048df87ab2c687 |
| polymerdao/plonky2-circom | github_top200 | unexposed_by_lists | included | 9 | 1/9 (11.1%) | 0/9 (0.0%) | 5cce3c21c5a0555b8c98dcdea312a7c65e4da39e |
| pratham-bhatnagar/zkMeetUp | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 823f7590c3e0083a7627f8c986b45f41c041f5e0 |
| pratham-bhatnagar/zkpVault | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 48491e45e9b4c4fbab76970b113305bb6d60745c |
| prifilabs/zk-toolbox | github_top200 | unexposed_by_lists | included | 12 | 0/12 (0.0%) | 0/12 (0.0%) | 167369587cd6b3ecfb0368759938da429ffc6845 |
| privacy-ethereum/circom-ecdsa-p256 | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 5b916ea5241d07c5b5953dd5724d7fb771ad76d8 |
| privacy-ethereum/webauth-circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 0fb5b4aa1398281c2fd3dbe14db147e05b61f201 |
| privacy-scaling-explorations/maci | zkbugs, sok_2026 | known_bug_listed | excluded: no_component_main_declaration | 0 | 0/0 (unknown) | 0/0 (unknown) | 919c433d09aa776a05ca2d89a0074324d6199e91 |
| ProofOfInnocence/privacy-pools-v1 | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 8ab7132877325e27b22053e974b3310d70b860b5 |
| qatkk/VerifyUTXO | github_top200 | unexposed_by_lists | included | 9 | 2/9 (22.2%) | 1/9 (11.1%) | 69363a9545819365de9d0ee0b19767cebae60d22 |
| Railgun-Privacy/circuits-ppoi | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | ec2b2654329eef2fd05cd00e19dcd86fd51abb5f |
| rarimo/passport-zk-circuits | github_top200, zkbugs, sok_2026 | known_bug_listed | included | 18 | 17/18 (94.4%) | 7/18 (38.9%) | 30b0be2e83062e19f21237c03317c9a26f2dab59 |
| Rate-Limiting-Nullifier/circom-rln | zkbugs, sok_2026 | known_bug_listed | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 17f0fed7d8d19e8b127fd0b3e5295a4831193a0d |
| Raunaque97/BattleShipZK | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 0bafd30b0452a0ca49c4bc5930b9b2d63eaf05b5 |
| reclaimprotocol/circom-chacha20 | zkbugs, sok_2026 | development_used | unknown: clone_failed | 0 | 0/0 (unknown) | 0/0 (unknown) | unknown |
| rejwar/Circom | github_top200 | unexposed_by_lists | included | 3 | 1/3 (33.3%) | 1/3 (33.3%) | 5068a6e324f5d44d0ee6e7ac3521ab6761127063 |
| retrository/zkMSA | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 55422fa9b29c73cfd07443b2bb9837c58100b925 |
| richbm10/zkpol_poc_proof_of_conversion | github_top200 | unexposed_by_lists | excluded: license_absent | 1 | 0/0 (unknown) | 0/0 (unknown) | 9623d6830731ceef398c0d1f15b3563b58f78908 |
| Ricy137/GHOTip-zk | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 53924c753f646678af418fa8b89a35e7656fa136 |
| rigobert9/wesnoth-zkpsi | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 3b8288cfe2b2a91168a67b9146f10d4d6bc8f8e7 |
| risc0/risc0 | zkbugs, sok_2026 | known_bug_listed | included | 1 | 1/1 (100.0%) | 1/1 (100.0%) | 3bbcd44d6459b9ef6ac0df3846dc9215514934e8 |
| rishotics/invert-circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | b7080f415bd0150e7851a720b7741f146384d6f1 |
| ronantakizawa/zksigmoid | github_top200 | unexposed_by_lists | excluded: license_absent | 1 | 0/0 (unknown) | 0/0 (unknown) | 09582b92d633277297fd2cc489f69616d0df90d4 |
| rubydusa/circom-graceful-labeling | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 7c95d1e81b8b865d452ed708a23dc7aa6e0ee554 |
| scroll-tech/mpt-circuit | zkbugs, sok_2026 | known_bug_listed | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | daa3a06e2e96d00337188280ac43fa879e722804 |
| scroll-tech/poseidon-circuit | zkbugs, sok_2026 | known_bug_listed | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | b978cee00aae1e0a1e79e0d74c4683b137f5ea2d |
| scroll-tech/zkevm-circuits | zkbugs, sok_2026 | known_bug_listed | unknown: main_in_uninitialized_submodules_unknown | 0 | 0/0 (unknown) | 0/0 (unknown) | 18f5bc268ca11988690c7cf59fc4615372ce99f2 |
| Se7en-Seas/circom-mangoes | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | bda177cc98ff86737211eec004313474dcda7faf |
| seanpm2001/SNU_2D_ProgrammingTools_IDE_Circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 9893bca0a572d0b0fd340a6747258f1264b31e30 |
| selfxyz/self | github_top200, zkbugs, sok_2026 | known_bug_listed | included | 141 | 0/141 (0.0%) | 0/141 (0.0%) | be761b35e69d85e48dd1c6f3eca7422a4ae43add |
| semaphore-protocol/semaphore | zkbugs, sok_2026 | known_bug_listed | excluded: no_component_main_declaration | 0 | 0/0 (unknown) | 0/0 (unknown) | 38d99081d868acf85e19f217ba427fc3a9eb6111 |
| sfyll/selective-application | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 336c6b5caafe42b337ec8ffc2bd059f1e21171d8 |
| sfyll/shielded_pools | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 507f64ca628dcab4e42779dd7161811f18b460ea |
| shuklaayush/circom-monolith | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 28f24a55d0b0847948fb460680f6353aab92a877 |
| Sindri-Labs/docker-zkp | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 51f7bbcd31f894f663bcca0d7cdb30fbdac2cffd |
| sismo-core/hydra-s2-zkps | zkbugs, sok_2026 | known_bug_listed | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 2b79ab31ebf5547cf73d0441a236446e8ddf501c |
| sisu-network/sisu-bridge | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | a4d8570d12189f12f5edf5168d3604e12312a53a |
| siv-org/verifiable-private-overrides | zkbugs, sok_2026 | known_bug_listed | excluded: no_component_main_declaration | 0 | 0/0 (unknown) | 0/0 (unknown) | 98adc350c4f42375a6415478945e5e607ad47e52 |
| SNAPKITTYWEST/treasury-bridge-zk-proofs | github_top200 | unexposed_by_lists | included | 1 | 0/1 (0.0%) | 0/1 (0.0%) | 9bfb971d95a0cfc8ba5b59388e68e886993e34eb |
| snowolf46/circom_demo | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 38ee2bad70e9a3047349843711c49015110ea4a1 |
| Sofianel5/asn1-der-circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | d2049dde148a57130e90e9eec44217f37e75406c |
| SoraSuegami/circom-uniplonk | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | c9aea758f89a08bf4dc441783ebaeb0898b8e9ac |
| srbakoski/ZKP-kurs | github_top200 | unexposed_by_lists | excluded: license_absent | 5 | 0/0 (unknown) | 0/0 (unknown) | a8c8bc83a6116f0188be4312e49719b8832d0779 |
| starkware-libs/stark-perpetual | zkbugs, sok_2026 | known_bug_listed | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 40f02826f783aa18a7401099c70afb29a8a8bbb1 |
| stealthdrop/stealthdrop | github_top200 | unexposed_by_lists | included | 3 | 0/3 (0.0%) | 0/3 (0.0%) | a8c8dfb2026129217f2a417cd12cb3251f9ff344 |
| stellar/soroban-examples | github_top200 | unexposed_by_lists | included | 6 | 3/6 (50.0%) | 1/6 (16.7%) | 01a9a33dfd4078ea507d6c606906a88370186a6b |
| succinctlabs/sp1 | zkbugs, sok_2026 | known_bug_listed | excluded: no_circom_files_in_pinned_tree | 0 | 0/0 (unknown) | 0/0 (unknown) | 9cb45b2d55569d490346d5cd6b79f12ff786cf90 |
| succinctlabs/telepathy-circuits | github_top200, zkbugs, sok_2026 | known_bug_listed | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 57fc3b9782bc55b34aa61a0cc71949551d796f63 |
| succinctlabs/telepathyx | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 2f6822b504fffd1f13c2cf30abc58364478ad961 |
| Suitec9/Bridge_motel | github_top200 | unexposed_by_lists | excluded: license_absent | 5 | 0/0 (unknown) | 0/0 (unknown) | 1888ea30794a7a25b2ee58a8cea8d201789546b4 |
| summa-dev/summa-solvency | zkbugs, sok_2026 | known_bug_listed | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 23587adcbd4f7c46371d2859a93bc8c5fa71f155 |
| summitto/ProveThis | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 5f59fb505abf20b86b2bd82ac3b6feda91da4d6b |
| SURUJ404/Zero-proof | github_top200 | unexposed_by_lists | included | 2 | 2/2 (100.0%) | 1/2 (50.0%) | b6355a99184dba8056bb82644b0837b366adcc07 |
| TaceoLabs/circom-mpc-utils | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 68e31f59c108948dc769c3c96dc60dcaba4bf773 |
| TaceoLabs/zksummit12_workshop | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | c17a18273ec26988ac3e45f9e0a385df3f1ff794 |
| tamago-labs/zkgpt | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 15c8bb5530a730794464b491f2cc58002c927a23 |
| tanctl/zylith-old | github_top200 | unexposed_by_lists | included | 8 | 0/8 (0.0%) | 0/8 (0.0%) | 44c0eeee4e8a1935c3d8de4ea54f8bcbc7538dd0 |
| tangle-network/protocol-solidity | zkbugs, sok_2026 | development_used | included | 13 | 0/13 (0.0%) | 0/13 (0.0%) | a42b4bc2696b4b812034fd0199d6462ae4fbbb8e |
| TanishaSangwan/dark-pool-amm | github_top200 | unexposed_by_lists | included | 5 | 5/5 (100.0%) | 0/5 (0.0%) | 5e7c29bf8edb774a5c179a646c71107ffd161323 |
| teeolendo/circom_rps | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 4919f1cbf6e58d720b02e6433480afc3272fc88b |
| term-structure/TS-Circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | fdecf81dd95a67a98689015a251c0c3729f04dde |
| thebor1337/zk-research | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 990c26374b6567512206ea8baea7f593e443ae25 |
| TheFrozenFire/circom-circuits | github_top200 | unexposed_by_lists | excluded: license_absent | 2 | 0/0 (unknown) | 0/0 (unknown) | 6619a18fcf9b51bc9c46ee8f094414eb1f833eb6 |
| thomasthechen/zk-ml-applications | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | ce961863e3e0517193829fe5dabed8a4adf63703 |
| tiktok-privacy-innovation/trustless-attestation-verification-circom | github_top200 | unexposed_by_lists | included | 4 | 0/4 (0.0%) | 0/4 (0.0%) | 43f1845d3c3ab495e685847123c02695f7e4ec87 |
| tokamak-network/DEPRECATED-zvm | github_top200 | unexposed_by_lists | included | 2 | 0/2 (0.0%) | 0/2 (0.0%) | 4bae70f83cb672c0b0569becb8b22cd95628a696 |
| tomiet/zkauth | github_top200 | unexposed_by_lists | included | 2 | 2/2 (100.0%) | 0/2 (0.0%) | d7fbbd388a5e5a0d0421f586e9b1483086cff287 |
| TreapGoGo/zk-flex | github_top200 | unexposed_by_lists | included | 1 | 0/1 (0.0%) | 0/1 (0.0%) | 3cc0a0be908c10dbc0c1b6fbcd5b4e88265af2f8 |
| TusimaNetwork/circom-pairing | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 3029cbffac05aae9b43153ce1e1a92448c60d4cd |
| twliu-dorian/ethglobal-sf-hackathon | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 76dd9fac596218a76cf702c7cb10949b101983ba |
| uiuc-kang-lab/zkperf | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 63647f4a08ff000fe1623c50eb208503ede0f635 |
| Unirep/Unirep | zkbugs, sok_2026 | development_used | unknown: main_in_uninitialized_submodules_unknown | 0 | 0/0 (unknown) | 0/0 (unknown) | fe3a863f9613e1992ffd218fd1e38ea665866738 |
| UrsaMajor-t/stark-snark-recursive-proofs | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | ecab014eb30f258348e8e0928e4a8568dfd2f1a2 |
| UVMichael/zkp-fpu | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 35bb66bff2e9cad6aa2007a6ab452a5002525ac3 |
| vacp2p/research | github_top200 | unexposed_by_lists | included | 5 | 1/5 (20.0%) | 0/5 (0.0%) | 93c710b4f706a3489ef0cb3b7fc6e4b91d17b941 |
| vacp2p/zk-explorations | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 6411edb0c9067bbc9dbef57a4dbd323d0f528f4d |
| vault-tron/vault | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 135cbe60134f80941334f9fa799e1786258ff348 |
| veigajoao/compliant-privacy | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 36d0c481c3322bd95bf1a6871e0a597ac5ffff72 |
| victoryeo/circom_zkp | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | b501a8d4902fffd2d470aa8acacf2ee89851f846 |
| vplasencia/merkle-tree-benchmarks | github_top200 | unexposed_by_lists | excluded: license_absent | 2 | 0/0 (unknown) | 0/0 (unknown) | 312d9e30b60c221018bcbdf4397f65981d079c0c |
| wenjin1997/zkshanghai-workshop | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 3240c19fd08689d29f01ce53417d0aa9c240a662 |
| whbjzzwjxq/ZKAP | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | fbd1dddad69a695a7fefeb2b6d824a0805ae9e00 |
| worm-privacy/proof-of-burn | zkbugs, sok_2026 | known_bug_listed | included | 2 | 0/2 (0.0%) | 0/2 (0.0%) | 92a7ecd1c5317ee383cf7b26b2977731ca6ff4fe |
| wyf-ACCEPT/ZK-Decision-Tree-Demo | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 84ef9ae0fcef54672988dd9341d0db728656d28f |
| y-pakorn/shroud | github_top200 | unexposed_by_lists | excluded: license_absent | 1 | 0/0 (unknown) | 0/0 (unknown) | 7aebbf8a92a6e3de2ae7bd3ac437bd9fb7eff09a |
| yagopajarino/zkam | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 946e2fc5468cf89013241f30ddfdca7109ff6226 |
| ymcrcat/soroban-privacy-pools | github_top200 | unexposed_by_lists | included | 5 | 2/5 (40.0%) | 0/5 (0.0%) | 4112bf965e94d826ae0e9f519338b0e491b98d8b |
| Zaira111111/ZK-Identity-Verifier | github_top200 | unexposed_by_lists | excluded: license_absent | 1 | 0/0 (unknown) | 0/0 (unknown) | fc6c4951a5614a26af8ed2e748dfc15156e68898 |
| zero-savvy/zk-remote-attestation | github_top200 | unexposed_by_lists | included | 3 | 2/3 (66.7%) | 0/3 (0.0%) | 4a0416c614061753dcdfe7fc7494a4ba0d020afd |
| zhangdav/zk-tornado | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | e31a50b78f361667575bbcc73981a179bbd602d5 |
| zk-crypto-research/streebog-circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 11cee86465514d8bc38cfce79f20969e603e0d9d |
| zk-kit/zk-kit.circom | github_top200 | unexposed_by_lists | excluded: no_component_main_declaration | 0 | 0/0 (unknown) | 0/0 (unknown) | b61b45701a2c176408e2f77999e7183984bc1a5b |
| ZK-Plus/ICBC24_Tutorial_Compute-Offchain-Verify-Onchain | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 4bd50d2f2c895885f4b32752a885669d902e6206 |
| zkam-labs/zkam | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 4413fe2d179d054d4c9eb37ede81d1452c884c25 |
| ZkBlind/ZkBlindNextJs | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 20eca18fa71bc51c2608d5bb57b0485e57f16b6b |
| zkCloak/zkMapo | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 583338afa544273cf5f397335b684e09f1b1eace |
| zkemail/ether-email-auth | zkbugs, sok_2026 | known_bug_listed | included | 11 | 0/11 (0.0%) | 0/11 (0.0%) | b562fade18b479023265de9c71c31ed924a5a951 |
| zkemail/zk-email-verify | zkbugs, sok_2026 | development_used | included | 21 | 0/21 (0.0%) | 0/21 (0.0%) | 066c8742a5e60519597697e579333b703ffa6ad2 |
| zkemail/zk-regex | zkbugs, sok_2026 | known_bug_listed | included | 6 | 0/6 (0.0%) | 0/6 (0.0%) | 89a4adb990b6288e02385fa63080af31d664bbd9 |
| zkFHE/circomlib-fhe | github_top200 | unexposed_by_lists | included | 42 | 0/42 (0.0%) | 0/42 (0.0%) | e27dd562645bf1062eee94cd457e154ff38239da |
| zkfriendly/zkGitPerks | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 7fb3a181ca8ab8d1d5b65af6016150afbe52fba3 |
| zkmopro/circuit-registry | github_top200 | unexposed_by_lists | excluded: license_absent | 14 | 0/0 (unknown) | 0/0 (unknown) | aab2ee1290ecd5d2b7dff985520bd1f3ce8a9750 |
| zkonduit/rpgf-parsing | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 80f2e0d8a88a76dabcc68a9fe9cd0ee75d915329 |
| zkopru-network/zkopru | zkbugs, sok_2026 | known_bug_listed | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 340d5f3f0b4c5112e767bef122c42cdd6f0ab89c |
| zkpservices/zkpservices | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | 8d884e0a7e722f43aa8ea151de4aff79b453006a |
| zksecurity/zkbugs | github_top200 | unknown | included | 113 | 52/113 (46.0%) | 19/113 (16.8%) | 212cc500b7cf1a2221d3e42ff47baff453afd070 |
| zkwebauthn/webauthn-circom | github_top200 | unexposed_by_lists | excluded: head_committer_date_before_2025_01_01 | 0 | 0/0 (unknown) | 0/0 (unknown) | e93a7ac56656072eeb0b20215f93f28ddbd00d0d |

미지원·불명은 결함 음성이나 일반적인 의미 동등성 근거가 아니다. N4-1 전체와 N5는 이 조사로 완료되지 않는다.

구조적 준비 적용성만 확인했다. wrapper 의미 동등성·후보 타당성·결함 탐지 성과·entrypoint 정확성의 검증은 아니다. 시간은 공유 호스트·초기화하지 않은 OS 캐시·일부 cargo 검사 동시 실행 조건의 관측이며 성능 우위 비교가 아니다. 날짜 등의 조건으로 먼저 제외해 조사하지 않은 라이선스·소스·main 속성은 부재가 아니라 미확인으로 남긴다.

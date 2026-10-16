# N6-A1b A 준비 보충 결과 (2026-10-08)

담당은 miiz다. 고정 A 목록과 70건 배치는 바꾸지 않았고, 이 작업에서 zkFuzz 후보 탐색과 campaign `execute`는 0회다. `src/`도 수정하지 않았다.

## 결과 요약

- 고정 목록: `docs/n6_targets_a_2026-10-07.json`, SHA-256 `6410b49e50b4da6a565955f6b9a6fa3ed1cd996b7923d96710e28ddfa2cf6758`.
- 준비 단위 53개(A-D 12, A-Q 1단계 41) 중 discovery·prepare·plan 성공은 28개, 실패 12개, 미시작 13개다.
- 새 queue는 `runs/n6-a1b-2026-10-08/queue-v3.json`, SHA-256 `f84ae9d85bd7eb5289e14e5cafd9cb0234b93fe1ce0dfc5d7805e5305f8b6201`다. 84개 대상×seed 단위와 168개 W/S spec을 포함한다.
- preflight는 165/168 통과, 3 실패다. 이는 실행 준비 확인이며 zkFuzz 후보 결과가 아니다.
- W/S 양쪽이 모두 준비된 revision 단위는 27개다. `aq-038`은 W 3개가 실패했지만 S 3개는 통과해 S-only 준비 단위 1개로 보존되며, queue 상태기는 W 실패로 S를 버리지 않는다.
- 공식 준비로 Panther full SHA 3개를 직접 fetch했고, 회수 불가 짧은 fix 11개는 `fix_commit_unretrievable`로 남겼다. 허용된 준비 산출물 15,618,115,887바이트는 해시·크기 기록 후 삭제했다.

- 단위별 `materialization.json`에는 공식 script 해시와 적용 결과가 있다. 합계는 상대 symlink 9건, 생성 entrypoint 9건, 호환 편집 6건, 정확 dependency 재사용 3건, iden3 공식 patch 1건이며 모두 성공했다. 기존 실제 dependency directory 재사용 10건은 별도 상태로 남겼다.

- 준비 계측 구간은 2026-10-07T01:15:50.733417+00:00부터 2026-10-07T02:01:58.063931+00:00까지다. 단위 시작·종료에 기록한 load-average 성분 범위는 5.050~12.235이다.

## RQ 포함 단위

- 알려진 결함 쪽 revision 단위(`development`·`vulnerable`·`leave_one_out`)는 27개이며, W/S preflight까지 모두 통과한 단위는 18개다.
- 수정 대조 쪽 revision 단위(`fixed`·`leave_one_out`)는 32개이며, 모두 통과한 단위는 12개다. 이 수는 결함 사례 수와 구분한다.
- A-Q 1단계 RQ1 사례는 24건이며 vulnerable 실행 단위까지 준비된 사례는 18건이다. 짧은 Panther fix 11건도 vulnerable 쪽은 RQ1 분모에 남는다.
- 회수 불가 fix 11건을 제외한 A-Q RQ-C 후보는 13건이다. vulnerable·fixed와 필요한 leave-one-out이 모두 준비된 완전한 쌍은 6건이다.

## 단위별 전후 비교

| 단위 | 층·종류 | 절차 | materialization 전→후 | setup 전→후 | discovery/prepare 전→후 | 적격 조각 | W | S |
|---|---|---|---|---|---|---:|---|---|
| `inference-original` | A-D / development | development_frozen_revision | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 22 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `inference-r-intdiv` | A-D / development | development_frozen_revision | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 25 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `inference-c9221e8d` | A-D / development | development_frozen_revision | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 25 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `inference-c79f42ee` | A-D / development | development_frozen_revision | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 25 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `inference-c771c61c-p` | A-D / development | development_frozen_revision | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 25 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `inference-loo-clamp` | A-D / leave_one_out | development_frozen_revision | ready(recovered) -> ready_for_discovery | success -> success | success -> success | 25 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `inference-loo-dfs` | A-D / leave_one_out | development_frozen_revision | ready(recovered) -> ready_for_discovery | success -> success | success -> success | 25 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `inference-all-fixed` | A-D / fixed | development_frozen_revision | ready(recovered) -> ready_for_discovery | success -> success | success -> success | 25 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `banyan-vulnerable` | A-D / development | development_frozen_revision | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 6 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `banyan-fixed` | A-D / fixed | development_frozen_revision | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 7 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `zkemail-fpmul-vulnerable` | A-D / development | development_frozen_revision | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 11 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `zkemail-fpmul-fixed` | A-D / fixed | development_frozen_revision | ready(recovered) -> ready_for_discovery | success -> success | success -> success | 11 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-000-a6b97aeaa1ae` | A-Q-stage1 / fixed | zkbugs_official | ready(recovered) -> ready_for_discovery | success -> success | failed:manifest_concrete_instance_unavailable -> failed:manifest_concrete_instance_unavailable | — | not_generated | not_generated |
| `aq-001-b32aa7daaea0` | A-Q-stage1 / vulnerable | zkbugs_official | ready(recovered) -> ready_for_discovery | success -> success | failed:compiler_or_tool_error -> failed:compiler_or_tool_error | 0 | not_generated | not_generated |
| `aq-002-923e08e670de` | A-Q-stage1 / fixed | zkbugs_official | ready(recovered) -> ready_for_discovery | setup_failure -> success | not_started:setup_not_success -> failed:manifest_concrete_instance_unavailable | — | not_generated | not_generated |
| `aq-003-626254249e88` | A-Q-stage1 / vulnerable | zkbugs_official | ready(recovered) -> ready_for_discovery | setup_failure -> success | not_started:setup_not_success -> failed:compiler_or_tool_error | 0 | not_generated | not_generated |
| `aq-004-803378d79dea` | A-Q-stage1 / fixed | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | setup_failure -> success | not_started:setup_not_success -> failed:compiler_or_tool_error | 0 | not_generated | not_generated |
| `aq-005-b689893c025f` | A-Q-stage1 / vulnerable | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | setup_failure -> success | not_started:setup_not_success -> failed:compiler_or_tool_error | 0 | not_generated | not_generated |
| `aq-006-1680f955c185` | A-Q-stage1 / fixed | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | setup_failure -> success | not_started:setup_not_success -> success | 78 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-007-0bb83f9eab0f` | A-Q-stage1 / fixed | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | setup_failure -> success | not_started:setup_not_success -> success | 81 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-008-9c9e702d061d` | A-Q-stage1 / vulnerable | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | setup_failure -> success | not_started:setup_not_success -> success | 80 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-009-aefcab68a248` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> not_started:fix_commit_unretrievable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-010-f35ff2e9e262` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> not_started:fix_commit_unretrievable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-011-93343c3cd34c` | A-Q-stage1 / vulnerable | zkbugs_official | not_started:source_commit_unavailable -> ready_for_discovery | not_started -> success | not_started:setup_not_success -> success | 116 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-012-44d0df2ab46e` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> ready_for_discovery | not_started -> success | not_started:setup_not_success -> success | 181 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-013-dd5954ac38b1` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> not_started:fix_commit_unretrievable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-014-5427d7292faa` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> not_started:fix_commit_unretrievable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-015-7bec6b38ea36` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> not_started:fix_commit_unretrievable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-016-0a7d49b1c135` | A-Q-stage1 / vulnerable | zkbugs_official | not_started:source_commit_unavailable -> ready_for_discovery | not_started -> success | not_started:setup_not_success -> success | 181 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-017-9703bbce0c43` | A-Q-stage1 / vulnerable | zkbugs_official | not_started:source_commit_unavailable -> ready_for_discovery | not_started -> success | not_started:setup_not_success -> success | 183 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-018-e39e4e77138c` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> not_started:fix_commit_unretrievable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-019-90637f07f72b` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> not_started:fix_commit_unretrievable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-020-f217a8d648bc` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> not_started:fix_commit_unretrievable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-021-12898764f632` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> not_started:fix_commit_unretrievable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-022-1f2e2842f6ed` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> not_started:fix_commit_unretrievable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-023-e609ecb8edce` | A-Q-stage1 / fixed | zkbugs_official | not_started:source_commit_unavailable -> not_started:fix_commit_unretrievable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-024-6f6781246415` | A-Q-stage1 / vulnerable | zkbugs_official | not_started:source_commit_unavailable -> ready_for_discovery | not_started -> success | not_started:setup_not_success -> success | 179 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-025-70328d3fd35e` | A-Q-stage1 / fixed | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 44 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-026-2bcd7ed6110f` | A-Q-stage1 / vulnerable | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 42 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-027-a847471783dc` | A-Q-stage1 / fixed | zkbugs_official | ready(recovered) -> ready_for_discovery | success -> success | failed:compiler_or_tool_error -> failed:compiler_or_tool_error | 0 | not_generated | not_generated |
| `aq-028-b9b2613fdfa4` | A-Q-stage1 / leave_one_out | zkbugs_official | failed:leave_one_out_patch_unavailable -> not_started:leave_one_out_patch_unavailable | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-029-886c1c02fb66` | A-Q-stage1 / vulnerable | zkbugs_official | ready(recovered) -> ready_for_discovery | success -> success | failed:compiler_or_tool_error -> failed:compiler_or_tool_error | 0 | not_generated | not_generated |
| `aq-030-f6334f2145b4` | A-Q-stage1 / fixed | zkbugs_official | ready(recovered) -> ready_for_discovery | success -> success | failed:compiler_or_tool_error -> failed:compiler_or_tool_error | 0 | not_generated | not_generated |
| `aq-031-2191c2696b01` | A-Q-stage1 / leave_one_out | zkbugs_official | ready(recovered) -> ready_for_discovery | success -> success | failed:compiler_or_tool_error -> failed:compiler_or_tool_error | 0 | not_generated | not_generated |
| `aq-032-01439be37566` | A-Q-stage1 / vulnerable | zkbugs_official | ready(recovered) -> ready_for_discovery | success -> success | failed:compiler_or_tool_error -> failed:compiler_or_tool_error | 0 | not_generated | not_generated |
| `aq-033-f4e0cd04d538` | A-Q-stage1 / fixed | zkbugs_official | failed:original_entrypoint_missing -> failed:original_entrypoint_missing | not_started -> not_started | not_started:setup_not_success -> not_started:setup_not_success | — | not_generated | not_generated |
| `aq-034-8d1c03d49b12` | A-Q-stage1 / vulnerable | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | setup_failure -> success | not_started:setup_not_success -> failed:manifest_concrete_instance_unavailable | — | not_generated | not_generated |
| `aq-035-8f826c822cb8` | A-Q-stage1 / fixed | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 6 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-036-6d7df64759b6` | A-Q-stage1 / vulnerable | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 3 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-037-94fe3080fc18` | A-Q-stage1 / fixed | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 27 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-038-4e5dcd2256b8` | A-Q-stage1 / leave_one_out | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | success -> success | 14 | pass 0/3; fail 3; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-039-0ad3923f2f5b` | A-Q-stage1 / leave_one_out | zkbugs_official | ready(recovered) -> ready_for_discovery | success -> success | success -> success | 27 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |
| `aq-040-da54d3e7bc8a` | A-Q-stage1 / vulnerable | zkbugs_official | ready_for_setup_or_discovery -> ready_for_discovery | success -> success | failed:compiler_or_tool_error -> success | 28 | pass 3/3; fail 0; missing 0 | pass 3/3; fail 0; missing 0 |

## A1 실패 원인 재검산

기존 판정은 바꾸지 않았다. A1의 7개 W 실패 핵심 오류는 다음과 같다.

- `inference-loo-clamp`: `error[P1012]: UnrecognizedToken { token: (2586, Token(22, "--"), 2588), expected: ["\"bus\"", "\"component\"", "\"function\"", "\"template\""] }`; `┌─ "<repo>/runs/n6-a1-2026-10-07/preflight-v2/preflight/inference-loo-clamp-seed-2026100601/W/compile/0000/workspace/src/responseTimeMetric.circom":96:2`
- `inference-loo-dfs`: `error[P1012]: UnrecognizedToken { token: (2586, Token(22, "--"), 2588), expected: ["\"bus\"", "\"component\"", "\"function\"", "\"template\""] }`; `┌─ "<repo>/runs/n6-a1-2026-10-07/preflight-v2/preflight/inference-loo-dfs-seed-2026100601/W/compile/0000/workspace/src/responseTimeMetric.circom":96:2`
- `inference-all-fixed`: `error[P1012]: UnrecognizedToken { token: (2586, Token(22, "--"), 2588), expected: ["\"bus\"", "\"component\"", "\"function\"", "\"template\""] }`; `┌─ "<repo>/runs/n6-a1-2026-10-07/preflight-v2/preflight/inference-all-fixed-seed-2026100601/W/compile/0000/workspace/src/responseTimeMetric.circom":96:2`
- `aq-036-6d7df64759b6`: `error[P1014]:  The file ./utils/padding.circom to be included has not been found`
- `aq-037-94fe3080fc18`: `error[P1014]:  The file @zk-email/zk-regex-circom/circuits/regex_helpers.circom to be included has not been found`
- `aq-038-4e5dcd2256b8`: `error[P1012]: UnrecognizedToken { token: (588, Token(74, "var"), 591), expected: ["\"bus\"", "\"component\"", "\"function\"", "\"template\""] }`; `┌─ "<repo>/runs/n6-a1-2026-10-07/preflight-v2/preflight/aq-038-4e5dcd2256b8-seed-2026100601/W/compile/0000/workspace/packages/circom/circuits/common/email_addr_with_name_regex.circom":21:2`
- `aq-039-0ad3923f2f5b`: `error[P1014]:  The file @zk-email/zk-regex-circom/circuits/regex_helpers.circom to be included has not been found`

A1 discovery/preparation 실패 8개는 원시 분류상 `compiler_or_tool_error` 7개와 `manifest_concrete_instance_unavailable` 1개다. 후자는 `aq-000`의 `concrete root instance key unavailable`이고, 나머지는 plan의 `prepared corpus has no targets eligible for small-first`다. 따라서 8개를 모두 같은 compiler 오류로 재분류하지 않았다.

A1b의 실패·미시작은 다음 원시 기록에 남겼다.

- `aq-000-a6b97aeaa1ae`: `failed` / `manifest_concrete_instance_unavailable` — concrete root instance key unavailable
- `aq-001-b32aa7daaea0`: `failed` / `compiler_or_tool_error` — Error: prepared corpus has no targets eligible for small-first
- `aq-002-923e08e670de`: `failed` / `manifest_concrete_instance_unavailable` — concrete root instance key unavailable
- `aq-003-626254249e88`: `failed` / `compiler_or_tool_error` — Error: prepared corpus has no targets eligible for small-first
- `aq-004-803378d79dea`: `failed` / `compiler_or_tool_error` — Error: prepared corpus has no targets eligible for small-first
- `aq-005-b689893c025f`: `failed` / `compiler_or_tool_error` — Error: prepared corpus has no targets eligible for small-first
- `aq-009-aefcab68a248`: `not_started` / `setup_not_success`
- `aq-010-f35ff2e9e262`: `not_started` / `setup_not_success`
- `aq-013-dd5954ac38b1`: `not_started` / `setup_not_success`
- `aq-014-5427d7292faa`: `not_started` / `setup_not_success`
- `aq-015-7bec6b38ea36`: `not_started` / `setup_not_success`
- `aq-018-e39e4e77138c`: `not_started` / `setup_not_success`
- `aq-019-90637f07f72b`: `not_started` / `setup_not_success`
- `aq-020-f217a8d648bc`: `not_started` / `setup_not_success`
- `aq-021-12898764f632`: `not_started` / `setup_not_success`
- `aq-022-1f2e2842f6ed`: `not_started` / `setup_not_success`
- `aq-023-e609ecb8edce`: `not_started` / `setup_not_success`
- `aq-027-a847471783dc`: `failed` / `compiler_or_tool_error` — Error: prepared corpus has no targets eligible for small-first
- `aq-028-b9b2613fdfa4`: `not_started` / `setup_not_success`
- `aq-029-886c1c02fb66`: `failed` / `compiler_or_tool_error` — Error: prepared corpus has no targets eligible for small-first
- `aq-030-f6334f2145b4`: `failed` / `compiler_or_tool_error` — Error: prepared corpus has no targets eligible for small-first
- `aq-031-2191c2696b01`: `failed` / `compiler_or_tool_error` — Error: prepared corpus has no targets eligible for small-first
- `aq-032-01439be37566`: `failed` / `compiler_or_tool_error` — Error: prepared corpus has no targets eligible for small-first
- `aq-033-f4e0cd04d538`: `not_started` / `setup_not_success`
- `aq-034-8d1c03d49b12`: `failed` / `manifest_concrete_instance_unavailable` — concrete root instance key unavailable

A1b W/S preflight 실패는 다음과 같다.

- `aq-038-4e5dcd2256b8-seed-2026100601:W`: `preflight_status_failed` — `error[P1012]: UnrecognizedToken { token: (588, Token(74, "var"), 591), expected: ["\"bus\"", "\"component\"", "\"function\"", "\"template\""] }`; `┌─ "<repo>/runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-038-4e5dcd2256b8-seed-2026100601/W/compile/0000/workspace/packages/circom/circuits/common/email_addr_with_name_regex.circom":21:2`
- `aq-038-4e5dcd2256b8-seed-2026100602:W`: `reused_preflight_status_failed` — `error[P1012]: UnrecognizedToken { token: (588, Token(74, "var"), 591), expected: ["\"bus\"", "\"component\"", "\"function\"", "\"template\""] }`; `┌─ "<repo>/runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-038-4e5dcd2256b8-seed-2026100601/W/compile/0000/workspace/packages/circom/circuits/common/email_addr_with_name_regex.circom":21:2`
- `aq-038-4e5dcd2256b8-seed-2026100603:W`: `reused_preflight_status_failed` — `error[P1012]: UnrecognizedToken { token: (588, Token(74, "var"), 591), expected: ["\"bus\"", "\"component\"", "\"function\"", "\"template\""] }`; `┌─ "<repo>/runs/n6-a1b-2026-10-08/preflight-v3/preflight/aq-038-4e5dcd2256b8-seed-2026100601/W/compile/0000/workspace/packages/circom/circuits/common/email_addr_with_name_regex.circom":21:2`

## 비용·디스크·남은 실행

- 실제 preflight wall 합은 2479.486초다. queue runner는 seed가 달라도 preflight 입력이 같은 W/S를 검증 후 재사용한다.
- A-D는 W 12·S 12개 method가 준비됐다. 할당 상한 합은 12.0시간, 이상적인 3병렬 하한은 4.00시간이다.
- A-Q는 W 15·S 16개 method가 준비됐다. `aq-038` S-only를 포함한 상한 합은 15.5시간, 이상적인 3병렬 하한은 5.17시간이다. 실제 시간은 시작 실패·조기 반환·정리 비용에 따라 달라진다.
- preflight 전후 여유 공간은 171.7→170.7 GiB다. 이 문서 생성 시점은 170.7 GiB다.
- A1b는 준비 관문만 갱신한다. 후보 값을 열지 않았고 J 판정, RQ1 결과, RQ-C 결과를 완료로 선언하지 않는다.

## 검증

- `python3 -m unittest tests/n6_a1b_test.py tests/n6_prepare_a_stage1_test.py tests/n6_a_specs_test.py tests/n6_targets_a_test.py tests/policy_a_engine_v3_test.py tests/n6_b_queue_test.py`: 29개 통과.
- `cargo fmt`: 통과.
- `cargo clippy --all-targets --all-features -- -D warnings`: 통과.
- `cargo test`: 통과(필요한 gitignored 외부 증거·설치 도구 검사는 기존 선언대로 ignored).

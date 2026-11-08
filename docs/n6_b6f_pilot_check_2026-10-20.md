# N6-B6f: 시범 형식 검사의 미지원 결과 처리

2026-10-20 KST. 이 문서는 B6e 시범이 엔진의 방법별 미지원 결과를 도구 고장으로 취급한 원인과 보정 근거를 기록한다. 판정 엔진, 판정 규칙, A 집계 규칙, B6e 요청 index 및 기존 시범 출력은 수정하지 않았다. B 최종 판정 값과 후보 값 열람은 0건이며 준비 단계의 B J 실행은 0건이다.

## 1. 지시와 읽은 근거

이번 지시 전문: `runs/handoff/n6_b6f_instruction_2026-10-20.md`, SHA-256 `3f6ce67cf5ce345dea40a5b5054b5254945a50b140bbf1aa7408baa8b1811e26`. 앞선 B6e 지시 0절의 로컬 수정·출력 보존·금지 사항을 따른다. 읽은 주요 파일의 SHA-256은 다음과 같다.

| 경로 | SHA-256 |
| --- | --- |
| `AGENTS.md` | `b0db6aa11075f472931c495f8db3f9156e4e64a153e66ac374777acd38f78f02` |
| `reports/START_HERE.md` | `04761b76a9cb61540dc6873ac6970996f894981cbba0df86801dca1c6a5f56` |
| `docs/plan_revision_2026-10-01.md` (종료 상태 반영) | `10a5edcaaa35d391ad9b9250cfe1c6a02014699d5329e596abd00dd09df9bb50` |
| `runs/handoff/n6_b6e_instruction_2026-10-20.md` | `c19de060dd6cbeafd608dc72a2762a9ea44a7e5abc23feac69dde1a2158c8a95` |
| `docs/n6_b6e_index_runner_2026-10-20.md` | `b6d0140de265554bb0723f0a37126db5208bd5eba0bdfa4f38a7eb8211726792` |
| `scripts/n6_b5_format_pilot.py` | `3b2c7b39dc58dc1bb5aaf86a622b5278848fc590350c99234a79386eb4ae8e48` |
| `scripts/n6_b6e_format_pilot.py` | `95089cf30f8698200eda99b51034549db61a1853b5b96056ca1e03e7273953fb` |
| `scripts/n6_b6e_j_runner.py` | `3ede8a5d691af29f813d4b7f806fca70429ff8a26d47e6ae678db4b4a3c45d3e` |
| `scripts/run_n6_j1.py` | `af23186151e1162f352d1a27f9020e3054e20bc461404791846fbb245077bd7c` |
| `scripts/n6_j1_summarize.py` | `6a02f7f6e4c74a3403bd1dc6b2604ff6c15e4f811d86cf4035016ed8910688e8` |
| `scripts/n6_b6_a_calibration.py` | `b6e38733486cd9ae3ac33cdca4e51338c0b37d01131f163def1209ed0d7bb17a` |
| `scripts/n6_b6b_runtime_paths.py` | `996ec9c4d85bea83d4f49dda9eb53955013c4a92e28530c203a0395545645f37` |
| `scripts/n6_j3_b_pilot_wait4.py` | `0d266fe3d2098c589017cd7c3a1ecbcbd983252464be61c31e23934a4276d9a7` |
| `scripts/n6_b5_j_adapter.py` | `d9ac5c8e3fafc4a789c1e6b9939611a494e3cd0ea9fb389048cbe2f21dc1de20` |
| `runs/n6-b6e-2026-10-20.noindex/request-index-v1.json` | `08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c` |
| `runs/n6-b6e-2026-10-20.noindex/request-index-v2.2.json` | `2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39` |
| `runs/n6-b6e-2026-10-20.noindex/pilot-selection.json` | `b7d9cd476ccdf6bf870327e613dc9f61de8145a89978c13993957f96bf997bf8` |
| `runs/n6-b6-2026-10-18.noindex/constructed-inputs/index.json` | `a00cdccc81d56ab5541806c0140582e5c4a934ceb0702c0c1c1e2e13589ae217` |
| `runs/n6-b6-2026-10-18.noindex/lead-input-review.json` | `9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e` |
| `runs/n6-b6-2026-10-18.noindex/lead-input-review-2.json` | `4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6` |
| 고정 v2.2 `src/candidate_review/lifting/repair.rs` | `93e7ddfac28cb3502c2b1e5f787831d5aa50c6cc453507dc7db38401d283ca05` |
| 고정 v2.2 `src/candidate_review/lifting/mod.rs` | `ce89724b7a89031921df38957118f5c5d4a7a1cf3b166746a4e502560daf1d66` |
| 고정 v2.2 `src/candidate_review/lifting/source.rs` | `b96f8afb5fbcd8bdf8947f7809ad8e3f2b6b1fcf10f689f65947c3bb63bd9a2b` |
| 고정 v2.2 `src/candidate_review/lifting/solver.rs` | `11dbe30b64321911cfd1a0efac1e94b84cdd6d5ab27e5909f9d48a791613e102` |
| 고정 v1 `cb40e3e06c27bfed2dcb19245f5d6b82d1860404:src/candidate_review/lifting/repair.rs` | `e2fbc35d4ea6a52377e26e96f992346d475137cae60bf1092ba90ac885d24894` |
| 고정 v1 같은 커밋의 `lifting/mod.rs` | `294d1c297814a6842d1313205e91eced41408a1b014e5c534a1662bfb36df005` |

v2.2 소스는 고정 커밋 `8065e2b7e165ef3f4c1523f240f5d34ecaefdb22`, v1은 위 표의 고정 커밋에서 확인했다. A 결과는 아래 감사 프로그램이 고정 index·state SHA에 맞춰 읽었다. 사람에게 출력한 것은 형식 통과/거부와 repair·injection의 허용 필드 집계뿐이다. B 시범 결과는 전용 재검사 프로그램으로만 읽었고 `preparation`, 단계 이름, repair·injection의 `outcome`·`error_kind`·`note`와 형식 통과/실패만 출력했다.

## 2. 기존 검사기와 두 엔진의 오류 의미

기존 검사기 `scripts/n6_b5_format_pilot.py:36-98`은 준비 `ok`, 결과 구조, 단계 상태, solver 결과를 확인하고 `:84-90`에서 repair 또는 injection의 `outcome=error`를 사유와 무관하게 거부했다. B6e 어댑터 `scripts/n6_b6e_format_pilot.py:79-82`가 이 검사를 그대로 호출한다. 따라서 queue 25의 정상 미지원 6개를 `pilot repair tool failure or invalid structure`로 잘못 멈췄다.

두 고정 엔진에서 injection과 repair는 같은 `repair::search`를 쓴다(v2.2 `lifting/mod.rs:3106-3110,3222-3238`, v1 같은 파일 `:2879-2883,2981-2997`). v1 `repair.rs:680-683,727-733`은 Z3 부재 또는 `run` 오류에서 `outcome=error`와 `note`만 적고 `error_kind`는 없다. v2.2 `repair.rs:723-726,775-795`는 Z3 부재 때 종류 없이 `z3 is not available`, 그 밖의 오류는 아래 여섯 `error_kind` 중 하나와 동적으로 구성한 `note`를 적는다. `format!("{error:#}")`가 하위 오류 사슬을 포함하므로 모든 가능한 note 문자열을 유한한 목록으로 열거할 수 없다. 아래 표는 소스에서 확인한 종류 전부와 허용하는 정확한 note 또는 패턴, 나머지의 처리다.

| 분류 | `error_kind`와 note 종류 | 소스 근거와 처리 |
| --- | --- | --- |
| (가) 방법 전제 불충족 | v2.2 `tool_or_unsupported`, v1 종류 없음; ``deviation_not_hint_assigned: no `<--` statement carries a deviated signal`` | v2.2 `mod.rs:1228-1233`, `repair.rs:913-922`; v1 `mod.rs:1193-1198`, `repair.rs:845-849`. 정확한 문구만 허용. |
| (가) 수리 위치 없음 | v2.2 `tool_or_unsupported`, v1 종류 없음; `the generator aborted in {template} line {number} (...) and no new statement there can be blanked`. 괄호 안은 constraint·assert·unclassified 중 하나 | v2.2 `repair.rs:1123-1163`, v1 `:1079-1085`. 템플릿·줄 번호 외의 문구와 종류는 허용하지 않는다. |
| (가) 진단 복사 한계 | v2.2 `diagnostic_failure`, v1 종류 없음; `the diagnostic copy still aborts after blanking 6 checks` | v2.2 `repair.rs:1120-1165`, v1 `:1087`. 정확한 문구만 허용. |
| (가) 제약 수 한계 | v2.2 `region_limit`, v1 종류 없음; `the predicate instance has too many constraints` | v2.2 `repair.rs:1371-1375`, v1 `:1290-1294`. 정확한 문구만 허용. |
| (가) 제약 수 한계 | v2.2 `region_limit`; `repair region has too many constraints` | v2.2 `repair.rs:1562-1565`에만 있다. v1에서는 거부한다. |
| (나) 외부 도구 부재·입출력·자원 | 종류 없음의 `z3 is not available`, v2.2 `io`, 또는 도구 실행·디스크·메모리 오류가 드러난 note | v1 `repair.rs:680-683`, v2.2 `:723-726,787-790`; Z3 프로토콜·실행은 v2.2 `solver.rs:101-181`. 시범은 멈추고 전체 실행도 환경 오류로 즉시 멈춘다. |
| (나) 시간·증거 불변식 | v2.2 `tool_timeout`, `evidence_invariant`; 임의 하위 오류 문구 | v2.2 `repair.rs:775-795`, `mod.rs:3542-3597,3773-3817`, `repair.rs:963-1016,1090-1097`. 시범은 멈춘다. 전체 실행에서는 환경 자원 문구가 아닌 경우 요청별 검사 실패로 기록한다. |
| (나) 그 밖의 진단·혼합 오류 | v2.2 `diagnostic_failure`의 다른 note, `tool_or_unsupported`의 다른 note, 종류와 note의 불일치, v1의 목록 밖 note | v2.2 `repair.rs:775-795`의 `tool_or_unsupported`는 포괄 분기다. 종류만 보고 허용하지 않는다. 시범은 멈추고 전체 실행은 환경 자원 문구가 아니면 검사 실패로 기록한다. |

새 검사기 `scripts/n6_b6f_format_pilot.py:83-195`는 (가)의 정확한 문구·패턴과 엔진별 종류 짝만 허용한다. `outcome=error`라도 (나), 목록 밖 문구, 종류 불일치, 깨진 구조는 시범에서 거부한다. 단계의 `tool_error`, solver의 도구 오류, synthesis의 도구 오류도 계속 거부한다. 특히 A에서 관측한 `the generator aborted in  line 0 (unclassified) ...`은 위 위치 탐색 실패 패턴에 해당한다. 다만 엔진 `mod.rs:3313-3364`가 abort 로그 읽기 실패를 기본값으로 바꾸므로, 이 note만으로 실제 로그 입출력 이상을 배제할 수는 없다. 이 한계는 엔진을 수정하지 않고 남긴다.

A 요약기 `scripts/n6_j1_summarize.py:195-224,251-271,494-512`는 완료 결과의 repair·injection `error` 자체를 도구 고장으로 거부하지 않는다. A 보정 집계 `scripts/n6_b6_a_calibration.py:345-367`도 A 요약기를 호출한다. B6e execute-all `scripts/n6_b6e_j_runner.py:293-310`은 준비가 `ok`이면 이 method error만으로 멈추지 않았으나, `:388-425`의 양쪽 시범 통과 관문 때문에 본 실행 진입이 막혀 있었다.

## 3. A 전체 대조

새 시범 검사기의 **전체 규칙**을 A의 완료 결과 원본 v1 765건, 원본 v2.2 765건, v2.2 엄격 기준 보정 122건, 구성 기준 보정 122건에 적용했다. 결과 envelope·준비 상태·단계 상태·solver outcome·synthesis outcome·repair/injection error_kind/note·구조를 모두 검사했다. 별도로 28개 revision join envelope도 검사했다. 고정 index·state SHA와 검사기 SHA로 결박한 재현 기록은 `runs/n6-b6f-2026-10-20.noindex/a-full-format-audit-v3.json`(SHA-256 `1bdd69bb0e933eac29edd5cb9b0173ebc9f4e6aa5402da9a3b74d659f2c98308`)이며, 검사 프로그램 `scripts/n6_b6f_a_error_audit.py`의 SHA-256은 `506a3de58037d425d31b515192345c7ca98c3be11abce41a277176a69bf561b1`이다. 감사 기록의 검사기 SHA는 `e0ade9572227059f317623a835195b78afd6219a20aca7324087a7ea582c5dee`다.

| A 구간 | 완료 결과 | injection 오류 | repair 오류 | 전체 형식 거부 |
| --- | ---: | ---: | ---: | ---: |
| 원본 v1 | 765 | 0 | 7 | 0 |
| 원본 v2.2 | 765 | 15 | 7 | 0 |
| v2.2 엄격 기준 보정 | 122 | 10 | 4 | 0 |
| v2.2 구성 기준 보정 | 122 | 37 | 20 | 0 |
| **합계** | **1,774** | **62** | **38** | **0** |

오류 100개는 모두 같은 위치 탐색 실패 note 종류였다. v1 7개는 `error_kind=null`, v2.2 93개는 `error_kind=tool_or_unsupported`다. 보정 결과의 14+57=71개라는 리드 관측도 확인했다. 이 표는 repair·injection만 센다. 별도의 predicate search 오류 28개는 이 method 오류에 섞지 않았다. A가 정상 완료로 받은 결과 1,774건 중 새 시범 검사기가 거부한 결과는 0건, join envelope 거부도 0/28이다. A 엔진을 재실행하지 않았다.

## 4. 기존 B v2.2 시범 결과 읽기 전용 재검사

기존 `runs/n6-b6e-2026-10-20.noindex/pilot-v2.2.noindex`를 변경하거나 두 요청을 다시 실행하지 않았다. 새 검사기는 queue 9 Vota와 queue 25 panther의 기존 `result.json`에 형식 검사만 적용했다. 새 증거 `runs/n6-b6f-2026-10-20.noindex/v2-2-pilot-recheck.json`의 SHA-256은 `202cd8b1d6ef420ef9f3b4918d314d82ab985333902af97d247c7e0a7d29a576`이다.

| queue | 기존 실행 관측 | 새 형식 검사 | 허용된 repair/injection 오류 |
| ---: | --- | --- | ---: |
| 9 Vota | 리드 기록: 통과, wait4 476초·RSS 12.1GB | 통과 | 0 |
| 25 panther | 리드 기록: 준비 `ok`, 엔진 실행 완료 후 기존 검사 중단 | 통과 | repair 6개: `tool_or_unsupported`, ``deviation_not_hint_assigned: no `<--` statement carries a deviated signal`` |

기존 시범은 queue 25의 형식 검사 지점에서 멈췄으므로 v2.2 시범의 revision join은 완료·재검사되지 않았다(`join_rechecked=false`). 새 전체 실행기 관문은 이 사실을 명시한 읽기 전용 재검사 증거와 앞으로 miiz가 실행할 v1 시범의 완료·join을 각각 확인한다(`scripts/n6_b6f_j_runner.py:443-515`). B 최종 판정 필드와 witness를 열지 않았다.

## 5. 새 실행기·결과 관문과 검사

새 실행기 `scripts/n6_b6f_j_runner.py:326-350,381-408,518-676`은 새 형식 검사기를 완료 결과에 적용한다. (가)는 정상 형식으로 계속한다. (나) 또는 목록 밖 note 중 IO·디스크·메모리·도구 부재 등 환경 사유는 즉시 중단한다. 나머지는 해당 요청을 `inspection_failure`로 기록하고 다음 요청으로 진행하며, 같은 엔진의 다섯 번째 검사 실패를 기록한 직후 중단한다. 기록에는 사유·상세와 기존 결과 파일의 경로·SHA만 두고 판정 값을 복사하지 않는다. 재시작 시 기록된 요청을 다시 돌리지 않으며 검사기 SHA 변경도 거부한다. 엔진이 보고한 준비 실패의 기존 회로·후보/환경 분류는 B6e 그대로다.

새 값 비열람 결과 관문 `scripts/n6_b6f_result_gate.py:59-199`은 엔진마다 107 전체를 분모로 `completed`, `preparation_failure`(reason별), `inspection_failure`(reason별)를 분리한다. `inspection_failure`는 unknown 판정으로 옮기지 않으며 5건이면 실행기가 멈추므로 완료 관문은 0~4건만 허용한다. 결과 파일과 join 파일은 경로·SHA를 확인하지만 판정 내용을 집계하지 않는다. v1 시범과 기존 v2.2 재검사 증거가 모두 필요하다.

| 새 파일 | SHA-256 |
| --- | --- |
| `scripts/n6_b6f_format_pilot.py` | `e0ade9572227059f317623a835195b78afd6219a20aca7324087a7ea582c5dee` |
| `scripts/n6_b6f_j_runner.py` | `4dfbff11c73bfc7d1b772bc70892259c431d689eaa84c655eece406d1e236259` |
| `scripts/n6_b6f_result_gate.py` | `603cda37e60c2d69d1e079629a490596a74eb8ae2539f3de590fb51d2b2098ad` |
| `scripts/n6_b6f_a_error_audit.py` | `506a3de58037d425d31b515192345c7ca98c3be11abce41a277176a69bf561b1` |
| `tests/n6_b6f_pilot_runner_test.py` | `e0993cf8bb0cb8fd7e839701ddedb4369de31d865ad157b2ec03131ff978721c` |
| `tests/n6_b6f_result_gate_test.py` | `9f303d0d7ce02711a4df7e1a3cd5b6c337456e253c2702eff3cefeffa7fa27d3` |

Python 단위 검사 19/19 통과: 미지원 note 허용, 도구·환경 오류와 목록 밖 note 거부, 비환경 검사 실패의 요청별 기록·재시작·5건 중단, 107 분모와 별도 집계를 확인했다. `python3 -m py_compile`(위 네 Python 코드), `git diff --check`, `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`가 통과했다. 기본 Rust 검사에서 명시적으로 ignored 처리된 설치 도구·보존 raw 증거 의존 사례는 실행하지 않았다.

## 6. N5 개정 연결

`docs/n5_amendment_b_judging_2026-10-17.md`의 개정 기록에 2026-10-20 KST, 수정·이유·승인자 miiz, “B 최종 판정 값 열람 0건, 판정 엔진·규칙 불변, 진단 중 시범 1건의 repair 단계 오류 문구 열람”을 추가했다. 개정 파일 SHA-256은 `275a6d9ff5db367aa2388394f59d9c70b50f29a90f69f6a765786982064022a6`다. 이후 `docs/n5_evaluation_protocol_v1_2026-10-06.md:244`의 연결 단락을 이 SHA로 갱신했으며 그 파일 SHA-256은 `33d29fd5d8c4f44a352f30933aecbe909dfe008f3253e3d9c121ecb42324b655`다.

## 7. miiz의 Kitty 실행 명령

아래 세 명령은 준비물이다. 준비 단계에서는 실행하지 않았다. v1 시범 → v2.2 다음 v1 전체 실행 → 결과 관문 순서로 실행한다. 각 줄은 단일 명령이며 새 B6f 출력 경로를 쓴다. `validate-only`는 miiz의 전체 실행 명령 안에서 각 엔진 직전에 수행한다.

v1 시범:

~~~sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu zsh -c 'set -e; O="$PWD/runs/n6-b6e-2026-10-20.noindex"; F="$PWD/runs/n6-b6f-2026-10-20.noindex"; X="/Volumes/zkfdo-jcache/n6-b6f-batch1x"; python3 scripts/n6_b6f_format_pilot.py --action execute-v1 --engine v1 --index "$O/request-index-v1.json" --index-sha256 08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c --static-preflight "$O/static-preflight-96mib-v1.json" --static-preflight-sha256 eb8241575399399ad46125452ff41bc21949d53df5bc8c5a93cf22ff5b6368cd --first-lead-review-sha256 9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e --second-lead-review-sha256 4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6 --selection "$O/pilot-selection.json" --selection-sha256 b7d9cd476ccdf6bf870327e613dc9f61de8145a89978c13993957f96bf997bf8 --cache-root "$X/cache/pilot-v1" --workspace-root "$X/hint-workspaces" --instance-root "$X/instance-stores" --output "$F/pilot-v1.noindex"'
~~~

execute-all:

~~~sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu zsh -c 'set -e; O="$PWD/runs/n6-b6e-2026-10-20.noindex"; F="$PWD/runs/n6-b6f-2026-10-20.noindex"; X="/Volumes/zkfdo-jcache/n6-b6f-batch1x"; L1=9de9eb4aaf1626eb9c14bb0437d1b43e3478f983396910623d0df3805a68193e; L2=4bc7f83da1f70c3ab523a38e56ef501f89508ba22e8dab674843d3995a9f60d6; for E in v2.2 v1; do if [ "$E" = v2.2 ]; then I=2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39; P=88c4a92bd627e138d2d77699e6a879e9f5a73729b3a241b6fafff89f966433d5; else I=08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c; P=eb8241575399399ad46125452ff41bc21949d53df5bc8c5a93cf22ff5b6368cd; fi; A=(--engine "$E" --index "$O/request-index-$E.json" --index-sha256 "$I" --static-preflight "$O/static-preflight-96mib-$E.json" --static-preflight-sha256 "$P" --first-lead-review-sha256 "$L1" --second-lead-review-sha256 "$L2" --cache-root "$X/cache/full-$E" --output "$F/full-$E.noindex"); python3 scripts/n6_b6f_j_runner.py "${A[@]}" --action validate-only; python3 scripts/n6_b6f_j_runner.py "${A[@]}" --action execute-all; done'
~~~

결과 관문:

~~~sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && caffeinate -dimsu python3 scripts/n6_b6f_result_gate.py --v1-index-sha256 08421ec900fedbce6f4e55b7fcba64df1c48886030fb094a50b3719e13101f1c --v2-2-index-sha256 2b1825ca2cce94cd08967a5bf16e5a56f9d045c6435a9b03d8625f52af505f39 --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b6f-2026-10-20.noindex/result-gate-v1.json
~~~

## 8. 시간·공간 계획과 지시와 다른 점

리드 기록의 Vota v2.2는 B6b 약 106초, B6e 476초로 약 4.49배 차이다. 두 기록은 source_root·wrapper·library 경로와 cache/출력 위치가 다르고 B6e는 새 cache를 사용했다. 구간별 시간 기록이 없어 차이를 어느 한 요인으로 확정할 수 없다. 476초를 107건에 기계적으로 곱하면 엔진 한 판 약 14.15시간, 두 판 214건 약 28.30시간이다. 이 값은 Vota 한 건을 다른 리비전에 적용한 일정 참고치일 뿐이다. 새 v1 시범 뒤 측정값과 준비 실패 비율을 반영해 다시 계산한다.

작업 시작 시 확인한 여유는 내장 약 71.79GiB, 외장 SSD 약 309.16GiB였다. B6e에서 unit·Vota hint·cache를 바탕으로 어림한 214건 약 92.98GiB는 리비전별 크기 차이를 포함하지 않는다. 실행기의 요청 직전 40GiB 관문은 내장 출력과 외장 cache·workspace·instance store에 적용된다(`scripts/run_n6_j1.py:345-354`, `scripts/n6_b6b_runtime_paths.py:26-35`, 새 실행기 `:608-616`). 전체 용량을 미리 예약하지 않으므로 장기 실행 중 여유를 계속 확인해야 한다.

지시와 다른 점: `outcome=error`의 모든 가능한 note를 소스에서 문자 그대로 열거할 수 없다. 두 판 모두 하위 `anyhow` 오류 사슬을 note로 직렬화한다. 그래서 소스가 직접 만든 (가)의 정확한 문구·제한된 패턴만 허용하고 나머지는 (나) 또는 미목록 검사 실패로 처리했다. 또한 A에서 관측된 빈 template·0행 note에는 엔진이 로그 읽기 실패를 기본값으로 감추는 한계가 있다. 기존 v2.2 시범의 join은 기존 검사 중단 때문에 없으므로 재검사 결과는 요청 2건의 형식에 한정된다. 그 밖에 지시와 다른 구현은 없다. B 최종 판정 값 열람 0건, 후보 값 열람 0건, B J 실행 0건이다.

# N6-B2 B 실행 전 준비 기록

기준: [N5 평가 프로토콜 v1](n5_evaluation_protocol_v1_2026-10-06.md)의 부록, [N6-B2 지시](../runs/handoff/n6_b2_instruction_2026-10-09.md). 기록 범위는 B campaign 시작 전 준비와 검증이다. B campaign과 전체 맥락 판정(J)은 실행하지 않았다. `runs/n6-b2-2026-10-09.noindex/`의 증거는 후보 내용이 아닌 경로, 해시, 상태, 시간 등 메타데이터다. 준비 환경에서 시작 관문은 실패했으며, 터미널의 새 관문 기록이 통과해야만 B campaign을 시작할 수 있다.

## 1) 고정 입력 해시 확인

[고정 입력 검산 JSON](../runs/n6-b2-2026-10-09.noindex/fixed-input-check.json)(SHA-256 `99e3880379773d335fe323b35c0c6753e2743cc57cdb11970c6ba7b5e58999f0`)의 상태는 `passed`다. 원본 B queue의 30단위·60 spec SHA를 확인했고, 대기열 실행기의 `load_preflight_rows`와 같은 조건으로 preflight 재사용 증명 60행을 확인했다. 대상 10개 × seed 3, 각 단위 W·S, 총예산 3,600초, S 시도 30초, 본 실행 10 GiB·동시 3, 백만 제약 이상 단위 6개 조건은 고정 입력 그대로다.

| 입력 | SHA-256 |
| --- | --- |
| [원본 B queue](../runs/n6-a2b-2026-10-08.noindex/queue-b-v4.json) | `d39e821fd65cea1852ad6a20b88ab59e03a7c363be9022224221986716161600` |
| [preflight 재사용 증명](../runs/n6-a2b-2026-10-08.noindex/preflight-reuse-b-v4.json) | `4af095fcd9f7370e01cf0fe48fa32d2164a19b2f98273859355f0c7d284be030` |
| [Policy A 엔진 v4](../scripts/run_policy_a_engine_v4.py) | `ff36c6db0a7475064c388a9bd0b0a1845863329f1fe2e2b40f06dec641fa9451` |
| 고정 zkFuzz `/Users/miiz/.cargo/bin/zkfuzz` | `ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd` |
| 고정 circom `/Users/miiz/.cargo/bin/circom` | `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227` |

## 2) include 출처(미해결·불일치·대체 root 파일 수)

[원본 queue include 출처 v3 JSON](../runs/n6-b2-2026-10-09.noindex/include-provenance-v3.json)(SHA-256 `792af9508592d26c6e67e5f53f38c67bd5ff9a86d33cceccc4424f7d3e63c03d`)은 60 spec, 고유 include closure 3,393개와 spec 대상 참조 10,179개를 검사했다. include는 포함 파일의 디렉터리, 이어서 명령의 `-l` root 순서로 해석했다. 미해결 include 0, 사본 바이트 불일치 0이다. 작업공간 밖에서 해석된 파일 참조 10,992건과 고유 파일 231개 모두 최소 한 준비 snapshot 사본의 SHA-256이 원본과 일치했다. 전체 경로·SHA·사본 대조는 JSON의 `external_unique_files`와 `closures[].outside_workspace`에 있다. [첫 출처 JSON](../runs/n6-b2-2026-10-09.noindex/include-provenance.json)(SHA-256 `8c6b28563f25480e9284118cc4c50bb77b00e432f9bf6bae09ad7b3aa7bd9b80`)과 [v2 JSON](../runs/n6-b2-2026-10-09.noindex/include-provenance-v2.json)(SHA-256 `71106b045d425d404a1f88df060b0974877e14dd7ee59f9014c7e61f49823d18`)은 보존했다. v2에서 사본 대응이 비었던 외부 참조 53건도 v3에서 대조됐다.

`library_root[...]`에서 작업공간 밖으로 해석된 원본 절대 root 파일은 57참조·고유 21개다. 원본 저장소의 `clone/` 뒤 상대경로가 준비된 `workspace/` 바로 아래에 놓이는 구조까지 대응했다. 고유 21파일 각각의 원본 SHA-256과 준비 사본 SHA-256이 일치하며, 57참조 중 사본 누락과 불일치는 모두 0이다. v3의 `library_root_external_files`와 `library_root_external_references`에 원본 경로·SHA, 사본 경로·SHA, snapshot 트리 SHA와 대조 결과를 별도로 적었다. 21파일 목록은 부록 B에 있다. 해당 spec의 `pinned_trees`에는 원본 외부 root pin이 없고, `pinned_files`는 plan·도구만 포함한다. 비교된 준비 사본은 spec의 `source_snapshots[].tree_sha256` 범위 안에 있다. 따라서 원본 외부 파일 자체가 별도로 pin된 것은 아니지만, 실제 해석 파일과 고정 snapshot 사본의 바이트 동등성은 확인했다.

보정 후 [최종 queue include 출처 JSON](../runs/n6-b2-2026-10-09.noindex/include-provenance-final-v3.json)(SHA-256 `833a1910d1afe431d1e3bc749cad6425ce12fcfe5b31c8c398dd48f4ae5e49a6`)은 최종 queue SHA와 60 spec 경로·SHA에 결속된다. 상태 `passed`, 고유 closure 3,393개·spec 대상 참조 10,179개다. 작업공간 밖 include 10,992참조·고유 231파일은 모두 준비 snapshot 사본과 SHA-256이 같고, 미해결·사본 누락·바이트 불일치는 각각 0이다. 대체 library root 57참조·고유 21파일도 사본 누락·불일치 0이다. 최종 [정적 pragma JSON](../runs/n6-b2-2026-10-09.noindex/parser-static-pragma-final.json)(SHA-256 `ba8ce9f80db6ce39e8230d3cd9aeaaf383a3d1a93cec4d20fb3068d2c6559c53`)은 이 출처 JSON의 SHA에 결속되고, 60 spec·3,393 closure에서 내장 파서 2.2.1을 넘는 파일 0개를 확인했다. 첫 두 최종 출처 시도(`include-provenance-final.json`, `include-provenance-final-v2.json`)는 snapshot 대응 경로를 완전히 찾지 못해 별도 보존했고 관문에는 사용하지 않는다.

[include 출처 생성기](../scripts/n6_b2_include_provenance.py) SHA-256은 `b44eff86842a49d4f62147d08c847e46b697be9dd4bcd8220d8e1ff2c2b0ff70`이다. [회귀 테스트](../tests/n6_b2_include_provenance_test.py) 5건은 통과했다.

## 3) 절대경로 include 목록

원본 queue include 출처 v3 JSON의 `absolute_includes`에 전체 목록 3,375참조를 포함했다. 이들은 모두 S entrypoint wrapper의 절대경로 include이고, 서로 다른 include 경로 151개가 모두 준비 작업공간 밖으로 해석된다. 경로, 포함한 wrapper, 줄 번호, 해석된 파일, SHA-256과 closure ID가 각 행에 있다. 경로는 C-03 복구 프로젝트 계열 2,571참조와 E-01 복구 프로젝트 계열 804참조다. W entrypoint의 절대경로 include는 관측되지 않았다. 보정 대상에서 원본 프로젝트를 가리키는 S wrapper 절대 include 304개는 보정 사본의 같은 상대 위치로 다시 연결했고, 원본 프로젝트 절대 include 잔존은 0이다([원본 보존·수정 증거](../runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/source-evidence.json)).

최종 queue에서 실제 해석되는 절대경로 include의 전체 목록은 최종 출처 JSON의 `absolute_includes` 3,375행이다. 이 목록은 보정된 304개 wrapper 경로를 반영하며, 원본 queue 목록과 구분해 보존한다.

## 4) 파서 표와 보정 여부

[정적 pragma 표](../runs/n6-b2-2026-10-09.noindex/parser-static-pragma.json)(SHA-256 `759214d2b626baba3cd6e66a65a6b41f4fa9b4923ab014850e8a4f6e78b84b8c`)은 원본 include closure 3,393개 중 62개에서 내장 파서 2.2.1을 넘는 `pragma circom 2.2.3` 파일을 찾았다(고유 파일 10개, 대상 `77e0f2db173d0c1812de503a`). [첫 seed 동등성 증명](../runs/n6-b2-2026-10-09.noindex/parser-source-equivalence.json)(SHA-256 `7dd081cfd5529895c129e8d39ba9eeb4a39d18c54fc1ad5756befa55412c889`)은 60 spec의 source snapshot, 대상 명령, pinned 파일·트리를 20개 대상·방식 그룹별로 세 seed 사이에서 대조했다.

고정 zkFuzz의 작은 정상 회로에서 파싱과 타입 분석 이후의 표지 `Gathering Trace/Side Constraints...`를 확인했다([표지 근거](../runs/n6-b2-2026-10-09.noindex/parser-marker-control.json), SHA-256 `64ea4a416a2c3d86752d8e0a4e09ebdce7cb8925847c9c06c818e23527fb72b0`). 각 대표 대상을 임시 폴더에서 최대 120초·물리 메모리 10 GiB로 관찰하고 표지 또는 `error[`가 나오면 프로세스 그룹을 정리했다. 후보 내용은 열람하지 않았고 임시 폴더는 모두 삭제했다.

| 대상 구분 | W | S | 파서 결과 |
| --- | ---: | ---: | --- |
| `77e0f2db173d0c1812de503a` | 1 | 305 | W 1·S 61 `P1003`; S 244 수용 |
| 나머지 9대상 | 9 | 3,078 | 전부 수용, P 오류 없음 |
| 전체 | 10 | 3,383 | 3,393/3,393 확인; 수용 3,331, `P1003` 62, 기타 오류 0 |

[동적 수용 요약](../runs/n6-b2-2026-10-09.noindex/parser-acceptance-summary.json)(SHA-256 `00a47218051feab2d0289d75cf214d044a5c6f1d348639ff1892f3c07367f56b`)의 최장 관찰은 19.155405초, 최대 물리 footprint는 7,159,717,064바이트였다. 완료 ledger 4개를 분모로 사용했고, 중단 뒤 정리 오류가 있었던 진단 ledger 1개는 제외한 뒤 해당 대상 36개를 별도 ledger에서 재검사했다. 잔존 프로세스 그룹과 임시 probe 디렉터리는 각각 0이다. `P1003` 조각 61개의 target ID·0부터 시작하는 target index·코드는 부록 A에 전부 적었다.

N5의 파서 버전 보정 규칙에 따라 이 한 대상만 원본과 별개의 사본으로 준비했다. [source evidence](../runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/source-evidence.json)(SHA-256 `ef900f2ac42c74f1fb66f2108077a788ed01170b1edb3c5ab9852c5e36a8ea10`)는 `pragma circom 2.2.3;` 한 줄을 `2.2.1;`로 바꾼 원본 프로젝트 파일 14개·S snapshot 파일 145개, S wrapper 절대 include 경로 수정 304개, 원본과 수정본의 diff를 기록한다. [R1CS 동등성](../runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/r1cs-equivalence.json)(SHA-256 `9d6afaa3d05e4a850f47f56c6d80c50b9af1591e03eb9cee1a081ff6f6675795`)은 고정 circom으로 W 1·S 305쌍 모두 바이트 동일을 확인했다. [대상 ID 대응](../runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/target-id-map.json)은 S 305개, [새 spec 목록](../runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/spec-manifest.json)은 세 seed의 W·S 6개다. 보정 사본의 [정적 pragma](../runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/parser-static-corrected.json)는 2.2.1 초과 파일 0, [파서 재검사](../runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/parser-check-v2.json)(SHA-256 `2c17a7536ed5c6a481a5ec66102171d79ddfcdf93bddc624c000d08d370b1de3`)는 306/306 수용·`parse_unconfirmed` 0이다. 보정 spec 6개는 새 preflight를 통과했고, 최종 queue는 v4.3 `validate-only`를 통과했다(8절).

## 5) v4.3 diff·테스트

[대기열 실행기 v4.3](../scripts/run_n6_v4_3_queue.py)(SHA-256 `7a63986e7a6aa43b445128fdde32b6aeb087049684b07d86481f776e62183b9e`)은 v4.2에서 60초 thermal 표본에 `ac_power`·`ac_power_raw`를 더하고, AC 읽기 실패를 표본 오류로 남긴다. 최근 AC 표본이 연결이 아니면 새 단위를 `ac_power_absent`로 기다리게 하며, 단위 시간 중 미연결 표본이 하나라도 있으면 `ac_power_lost`의 `environment_pressure`로 처리한다. 다른 실행기 동작은 v4.2와의 diff에서 변경되지 않았다. 실제 B 실행에는 v4.3을 사용한다. Python 모의 테스트는 v4.2 12건과 [v4.3 15건](../tests/n6_v4_3_queue_test.py)이 통과했다. v4.3 추가 항목인 AC 미연결 중 실행 압박, 새 단위 대기, 읽기 실패 차단을 포함한다.

## 6) mem20 준비 스크립트·테스트

[B mem20 준비 스크립트](../scripts/n6_b_mem20_prepare.py)(SHA-256 `a44b86b75f72c0a3f291c4913bc7b377f91c55a3864069ab485590a55fee69ac`)는 B 본 실행 뒤에만 본 출력 `state.json`과 압박 없는 마지막 run 기록의 `outcome_counts.memory_cap`으로 대상 단위를 고르도록 작성됐다. 선택 단위의 W·S spec에서는 `memory_cap_bytes`를 20 GiB(`21474836480`)로, `campaign_id` 접두를 `N6-B-mem20-`으로만 바꾸고, 사전 검사의 허용 차이 두 필드와 연결한다. 원본 queue 순서를 유지하며 동시 1, 대상 0이면 queue 없이 요약만 작성한다. 본 실행 데이터로는 실행하지 않았다. [가짜 ledger 테스트](../tests/n6_b_mem20_prepare_test.py) 4건이 통과했다. mem20 본 실행은 B 본 실행 직후, B J 전에 별도로 한다.

## 7) 관문 결과

[B 시작 관문](../scripts/n6_b2_prestart_gate.py)을 최종 queue와 최종 include 출처 JSON으로 실행했다. [관문 기록](../runs/n6-b2-2026-10-09.noindex/gates/prestart-gates.json)(SHA-256 `6f3d774414d0657edf5175cf6f83f22007c1f06051f7215e4553159bd59a83b8`)은 `failed`다. 준비 실행 환경에서 `ps`가 `Operation not permitted`로 막혀 프로세스 목록을 읽지 못했고, 감시 실패 차단 규칙에 따라 무거운 동시 작업 0과 실제 10 GiB self-test·호스트 시작 조건을 통과로 판정하지 않았다. queue·60 spec, include 출처, 디스크, `caffeinate`·`pmset` 사용 가능 여부의 검사는 참이었다. 권한을 높인 재실행도 완료되지 않아 새 관문 기록이나 self-test 출력이 없다. 이 기록은 시작 허가가 아니다.

아래 사용자 터미널 명령은 새 UTC 시각 관문 기록을 만든다. 그 관문이 통과하지 않으면 `&&`에서 멈춰 B campaign을 시작하지 않는다. 관문은 10 GiB 실제 self-test와 감시 실패 차단, AC·저전력·발열·메모리·swap, `caffeinate`·`pmset`, 동시 무거운 프로세스 0, 디스크 여유를 확인한다.

## 8) 최종 queue 해시·`validate-only`

[최종 B queue](../runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json)의 SHA-256은 `0fbaa62e4437c2f7bf8cfea45391d5375476a1090aaf39cc4433e6eff66e9b19`다. [preflight 증명](../runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/preflight-proof.json)(SHA-256 `83cf19c8cd142ad27cd230a2b5a7afb27ed69c369bd57eed67c8ce3a983c4f2b`)은 60행 `passed`이며 원본 54행 재사용과 보정 spec 6행의 새 검사로 구성된다. [queue 준비 메타데이터](../runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/final-queue.json)(SHA-256 `eb0d11f249348e0a7f838186b78796e62bd1ce3320122e18f77d4037fa31ff2a`)는 v4.3 `--action validate-only` 결과 `valid`, 30단위·60 spec을 기록한다. 원본 queue의 대상·예산·seed·순서·10 GiB 조건을 유지하며, 세 seed의 한 대상 W·S 6 spec만 보정 사본으로 교체했다. queue 내부 `queue_runner` 선언은 기존 v4 경로·해시이며, 실제 사용할 실행기는 [v4.3](../scripts/run_n6_v4_3_queue.py)(SHA-256 `7a63986e7a6aa43b445128fdde32b6aeb087049684b07d86481f776e62183b9e`)이다.

필수 Rust 검사는 `cargo fmt -- --check`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`가 모두 종료 코드 0으로 통과했다. Python 모의 테스트는 v4.2 12건, v4.3 15건, 시작 관문 4건, mem20 준비 4건, pragma 보정 7건, 파서 6건, include 생성기 5건이 각각 통과했다. 중복 실행이 있어 이 숫자를 합산된 고유 테스트 수로 쓰지 않는다.

[실행 입력 SHA-256 목록](../runs/n6-b2-2026-10-09.noindex/b-execution-inputs.sha256)(목록 파일 SHA-256 `27b1c98ed1f0ff7d5315b79a7b33303a3f05e932eb9c87d3b3bc622a736d7d0b`)은 엔진 v4, v4.3 실행기, 최종 queue, 시작 관문 스크립트의 네 해시를 고정한다. `shasum -a 256 -c`로 4/4가 통과했다. 시작 관문 스크립트의 SHA-256은 `89bb2563d6f692cafe3204777b86c0824667ea365a2be1ca53570a2b866959fa`다.

## 9) 터미널 명령·예상 시간

사용자가 터미널에서 실행할 B 본 실행 한 줄 명령은 다음과 같다. 여기서는 실행하지 않았다. SHA-256 4개를 먼저 확인한 뒤 새 관문 기록을 만들고, 관문이 통과할 때만 `caffeinate -dimsu` 아래에서 v4.3을 시작한다. 새 관문 파일명에는 UTC 시각을 붙인다.

```sh
shasum -a 256 -c /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b2-2026-10-09.noindex/b-execution-inputs.sha256 && python3 /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_b2_prestart_gate.py --queue /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json --include-provenance /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b2-2026-10-09.noindex/include-provenance-final-v3.json --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b2-2026-10-09.noindex/gates/prestart-gate-$(date -u +%Y%m%dT%H%M%SZ).json && caffeinate -dimsu python3 /Users/miiz/Desktop/kwzzzz_zkfr/scripts/run_n6_v4_3_queue.py --queue /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/queue-b-pragma.json --action execute --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b2-2026-10-09.noindex/b-execute.noindex > /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b2-2026-10-09.noindex/terminal-b.log 2>&1; rc=$?; printf 'exit_code=%s\n' "$rc"
```

계산상 30단위 × (W·S 각 3,600초) ÷ 동시 3 ≈ 20시간에 관문 대기가 더해진다. 백만 제약 이상 단위의 직렬 처리와 환경 대기는 이 단순 계산보다 길게 만들 수 있다. mem20 명령은 B 본 실행 종료 후 대상 선정 결과에 따라 별도로 정한다.

## 부록 A. 원본 파서 `P1003` 조각 목록

대상 `77e0f2db173d0c1812de503a`의 W 1개(`target_id=77e0f2db173d0c1812de503a:whole`, `target_index=0`)와 아래 S 61개가 모두 `P1003`이다. 원본은 [P 오류 메타데이터 JSON](../runs/n6-b2-2026-10-09.noindex/parser-high-version-p-errors.json)(SHA-256 `85a8fd0c067c6ec874e32d5d878eafb726a8bd4957cbde3a4715718352766d15`)이다. 표의 index는 첫 seed의 S spec에서 0부터 센 위치다.

| target_index | target_id | 오류 코드 |
| ---: | --- | --- |
| 0 | `sha256:158a954258bb9ba317fd5e7f55ad53bae3b90ab5838ef2e555a570be5e61d6c9` | `P1003` |
| 2 | `sha256:65c6644dacce004ac53e68f3da845ef893dc15b83470b07afcad800f2a14ceaf` | `P1003` |
| 10 | `sha256:f5b4f9f59a79d265637fcb7a682ed8d11e80c2b0d76bf4b95c6f7c14d6df9ebb` | `P1003` |
| 146 | `sha256:e39ed064e9080dba63fe7fabaeac58c61c988f6bc9edc7b011ce854c44b73c28` | `P1003` |
| 233 | `sha256:d8fa435087e74805f98c0ca8c96a89f4fc43a55262361be7265ab0a6b3dc8923` | `P1003` |
| 236 | `sha256:4be08fd735110ae371c38e0be01634ea50dc72f432a69d43105a77b5d9507a33` | `P1003` |
| 240 | `sha256:70b00efc9529e26b9998e5977f3d8c3f50f29204f1b0a2c6e48565288e536dbc` | `P1003` |
| 241 | `sha256:ba914f02204f4110c573f6d31001ad0b74b3675d7cae6788f04d6e75498ad2cc` | `P1003` |
| 244 | `sha256:22935944c61c715225cf3819ff97994920e863250f96d6695d781892b4979fb8` | `P1003` |
| 245 | `sha256:e478bd35298fa9620d765e917ce5fe0feffe57aab9cf41dd70995397d3c260da` | `P1003` |
| 248 | `sha256:757065bf955dc948dab8c7182a0e012f5408ef9136d2896ac50893f227ae7228` | `P1003` |
| 249 | `sha256:c4eb69c98a68659284f39562af74109bc90911cbf9160d4b83402c988737cf5d` | `P1003` |
| 250 | `sha256:94fb28d69577dac6b8ccda91f749db4590e7192a5931c9262b72761cc66202bf` | `P1003` |
| 251 | `sha256:0fce16a6c27890d62deaa1bb3c5a7f7c65136174f36980d7f04963fe3e80e356` | `P1003` |
| 252 | `sha256:4ca6766b6a831805b4e2e6b877d37a68c8a1eb184ab1066241eddd80beb20263` | `P1003` |
| 253 | `sha256:ed95898f9dc75ab7d6e6a17e8a8a1a91f6372beb3c48ea519e52e385650d0297` | `P1003` |
| 254 | `sha256:42c4c1cf2cd4fedac8514a8f27aa8374efbc419002edaef262a7d744d7a2c794` | `P1003` |
| 255 | `sha256:7a6440e0ae9c0c7beb7263c05ad1cd1d4f13a5b7080f1f437dbe26e04d1b4126` | `P1003` |
| 258 | `sha256:b0b2b4e72bdb717c96ba792a4e08587eb66ad3a63614f2666cfc8105fb801117` | `P1003` |
| 261 | `sha256:fc694c66c98897153398280d9c2dfda945fcfed54704f08d049fc9c18a752916` | `P1003` |
| 262 | `sha256:6bc8b1f732603c41a8c02fc8dbdfc3d09cbc7d52807cbe64cd4d503f5b01956b` | `P1003` |
| 263 | `sha256:04d2447a558cfddf14d1f66d6058f443d1977899981bd87b323fcc6d4e4a1ccf` | `P1003` |
| 264 | `sha256:f442502228dcc3b0c33353b3e40b0db1585c6fe14e4efef138682e3fb9cba95c` | `P1003` |
| 267 | `sha256:7bb567c3e359d55d2fa06bcccf8c217cc070c8d6efcb8d92b829cdca1b9ef9ac` | `P1003` |
| 268 | `sha256:683d0b34c55b70e0731e150bedb48cc28b1eb44f6c83a0445634d04746269c4f` | `P1003` |
| 269 | `sha256:0294c43b0f005e7da24053d3bb3895d41e7aebc22b5ba563e1f2b4061d913009` | `P1003` |
| 270 | `sha256:068c793762fe980f3a9119805cca09eb7110aa362a730bee5fc9ee197291f045` | `P1003` |
| 271 | `sha256:0b886f41571fce122abff1fa748fd13de52c45016a6feaf6af84497a26ca5775` | `P1003` |
| 272 | `sha256:1269e9e093259bdd45fe0f8ebd371d1192f6e71220ebe6ce3c6a23ff3bd64f96` | `P1003` |
| 273 | `sha256:13013560729d4be46e8175046493890502df4af20fc6c797dac3efb14624bf36` | `P1003` |
| 274 | `sha256:13d44fcb9f39b8f680cd7f47b488ed07383960c6caabfc9a113c7af156ba6d3e` | `P1003` |
| 275 | `sha256:174db5f9b9f6fb935eee1a96a20501ecaa0ea1620bf595a1dc73d464c8ddb4f8` | `P1003` |
| 276 | `sha256:1b2ebe166f0170ec6dea877ecea74fa5a191f2ae7f46d086c61d5fe0a5ad3e41` | `P1003` |
| 277 | `sha256:2192f15076e21463b7fdd4b0e9b1d3d4f16f99596cdd8e61fdd4e856e31e34ea` | `P1003` |
| 278 | `sha256:239eae3b6cc551e52fa76d5ee83a926cd567e72023a23058e66b66c754c976d0` | `P1003` |
| 279 | `sha256:4149cae8f1a7869e94e9b655a51b4ea0260550e4de396d55a2ed90b9eff256a6` | `P1003` |
| 280 | `sha256:41eac9010ac0825ea2a507d52e5b1f04d1a286392cfef3b9e14e3d8a4309308a` | `P1003` |
| 281 | `sha256:4c58fa10b30719dc935eddbf07908c20979edf25a9994ba284dda30883f5739d` | `P1003` |
| 282 | `sha256:54da90cf0d7d8e01def90668e95848ccdcf3c914ff5878594a6dee29226aac00` | `P1003` |
| 283 | `sha256:6c9b4e154a52b1ed617e007f61af091f58723c75188b25261cb44ee222e29b58` | `P1003` |
| 284 | `sha256:6cf630edbfe26a1675c9853655ac6d12cc82f1911fae0348cb2167292f5d7085` | `P1003` |
| 285 | `sha256:7e869e40b7984e77d0f1c9ae9ca9f3a469cc64143ff4cb87f0044f3edb231d07` | `P1003` |
| 286 | `sha256:97e156b15725af1870951950e875cd6adcdb1cf872f886d860649f52d55c7d0b` | `P1003` |
| 287 | `sha256:9c75fdd619bf59d5041dd3e7f9b7466cbee2916034a75d1c7434e02d6618a25c` | `P1003` |
| 288 | `sha256:af21bd08ba53e8b1e993e4c9fc4dcce058d51d6f3916becec58f76acbaafebc6` | `P1003` |
| 289 | `sha256:b8c6204064a2a9b94ea0406e02b5c7a05c3480e570427e04ccde7dcdb495c7f4` | `P1003` |
| 290 | `sha256:c1ca46a425afc46e7b2939be8c942b44f104ac5ead77cd571a39d2166cf89aa5` | `P1003` |
| 291 | `sha256:d5513e30b5140dd10460b206ce2d264587f1b80aaf5ee15fe8aa48b95be9aa8e` | `P1003` |
| 292 | `sha256:dba91c2ee441ab0582d031c72f1d695376054ad0b24892b2c57da79f3a1591f6` | `P1003` |
| 293 | `sha256:e2f7dd6588ae6791c0fdade61a5fbdf3ce72c411bcf65aaa2453c143543faa23` | `P1003` |
| 294 | `sha256:e8c864acd0f408a55c9bd828e1e7ce13f5fb13d3d8cdd13fe80d4bafebd7e604` | `P1003` |
| 295 | `sha256:ea76692cc775f6b12880029e24215634d1aaf2b8dddca5f8ece6ab157352735f` | `P1003` |
| 296 | `sha256:fa517d576e6b4e95f7632ca05ebb589d47b2b17b5ac45f447f83bc772900272e` | `P1003` |
| 297 | `sha256:9ff5a8bb703b58f94babc812ddcff268fdddfef6778ab4306c8b2e6b2a81f748` | `P1003` |
| 298 | `sha256:81826f2bc9144f81905409e05c9a3c5dc3318b5393cbb3cd14a4e30cc4978b7e` | `P1003` |
| 299 | `sha256:c83882323d918a7dd139c6f41de66e41866ebea114f455c1af85129687ce7a00` | `P1003` |
| 300 | `sha256:b88c40104e0285e371eee02e0f3d23a021775aad260984073d4ddc6a3a95df44` | `P1003` |
| 301 | `sha256:dc9ee9887d8ddb72c5a0a4240ee4b409e5e06bba37978fff4576e61b1324beff` | `P1003` |
| 302 | `sha256:316ffeb45d44c89dd99f2e63e0cddf384fff132071ea29cb59ea903b81660a80` | `P1003` |
| 303 | `sha256:80216ec7e43ac51ebcba31eea2d479975631e7119596ed7652f452ee49e07710` | `P1003` |
| 304 | `sha256:d931d678872f7d0b9bf72ed710464d0762775ae3f27a682742d54aa1ff29c922` | `P1003` |

## 부록 B. 원본 절대 library root 파일 21개

경로 표기에서 원본은 `원본 접두/clone 이후 경로`, 사본은 `준비 snapshot root/clone 이후 경로`다. 전체 원본·사본 경로와 각각의 SHA-256은 [include 출처 v3 JSON](../runs/n6-b2-2026-10-09.noindex/include-provenance-v3.json)의 `library_root_external_files`에 있다. 아래 SHA-256은 원본과 사본이 같은 값이며, 21/21 대조가 통과했다.

- `A` 원본 접두: `runs/e01-setup-2026-10-03/recovery-v2/repositories/anon-aadhaar__anon-aadhaar/clone`; 준비 snapshot root: `runs/e02-production-mains-2026-10-05/preparation-measurements/6079a717f929aaf04a04e329/cap-900/prepared/prepare-b877c53f-2ffe-4e61-9719-f7eacb6df405/targets/0000/sources`
- `S` 원본 접두: `runs/e01-setup-2026-10-03/recovery-v2/repositories/selfxyz__self/clone`; 준비 snapshot root: `runs/e02-production-mains-2026-10-05/preparation-measurements/83cc00608fdaa7191b839ed6/cap-300/prepared/prepare-5f65c8c4-7628-4d7d-ac88-136af2892725/targets/0000/sources`
- `T` 원본 접두: `runs/c03-corpus-2026-10-02/recovery-v3/repositories/tanctl__zylith-old/clone`; 준비 snapshot root: `runs/f01-2026-10-03/measurements/77e0f2db173d0c1812de503a/prepared/prepare-ba82341e-3047-4b15-aa13-f410847f6924/targets/0000/sources`

| 접두 | clone 이후 경로 | 원본·사본 SHA-256 | 대조 |
| --- | --- | --- | --- |
| T | `circuits/node_modules/circomlib/circuits/bitify.circom` | `688f121303a2dd0154ceeda8d2f53a9d2d26789d10a69a46acd534642725683e` | 일치 |
| T | `circuits/node_modules/circomlib/circuits/comparators.circom` | `fd0c7723ee56e1467df1861131157cbb108e156fe2d9ec64895c8e68de14db20` | 일치 |
| A | `node_modules/@zk-email/circuits/lib/rsa.circom` | `ed5d2d9cc71749caa404951f75ff46eed098c459479e15f9061f7bad186c2ce0` | 일치 |
| A | `node_modules/@zk-email/circuits/lib/sha.circom` | `bc9f6617d9419d62aab75db040ea3b5cafcf865facef822256c808ddba3ee70b` | 일치 |
| A | `node_modules/@zk-email/circuits/utils/array.circom` | `34433ae5b40f12fe49bb9d8fd7172c2b08346dc3061daa8c3a0e7d043c4d6cbd` | 일치 |
| A | `node_modules/@zk-email/circuits/utils/bytes.circom` | `9bb1b8fb982efe8665cd880b392926f32bddc1c0a5e32bde6cb249278058ea0d` | 일치 |
| A | `node_modules/circomlib/circuits/bitify.circom` | `688f121303a2dd0154ceeda8d2f53a9d2d26789d10a69a46acd534642725683e` | 일치 |
| A | `node_modules/circomlib/circuits/comparators.circom` | `fd0c7723ee56e1467df1861131157cbb108e156fe2d9ec64895c8e68de14db20` | 일치 |
| A | `node_modules/circomlib/circuits/gates.circom` | `890e2514ddcbce77e0a5f6867749401fc182664a4b901d6d7bf6856197e0d87c` | 일치 |
| A | `node_modules/circomlib/circuits/poseidon.circom` | `2582464669b69827164bd08ee0337997e1957f2ab4f00cdd86d533ca5e9d9234` | 일치 |
| A | `node_modules/circomlib/circuits/sha256/constants.circom` | `90f910027d360162896b81a4a1654fae16b74d90d43521d172f72c6deb52104e` | 일치 |
| A | `node_modules/circomlib/circuits/sha256/sha256compression.circom` | `aec6674cee5d0b775d7b27279a98b7fbabf5258885d56e01dec9a4a356dbc69c` | 일치 |
| A | `node_modules/circomlib/circuits/sign.circom` | `172255ff7d11d48958d9836f88bb40792009b94be19ba94ed01982a12c276dfb` | 일치 |
| S | `node_modules/@openpassport/zk-email-circuits/utils/array.circom` | `34433ae5b40f12fe49bb9d8fd7172c2b08346dc3061daa8c3a0e7d043c4d6cbd` | 일치 |
| S | `node_modules/@openpassport/zk-email-circuits/utils/bytes.circom` | `9bb1b8fb982efe8665cd880b392926f32bddc1c0a5e32bde6cb249278058ea0d` | 일치 |
| S | `node_modules/@zk-kit/binary-merkle-root.circom/src/binary-merkle-root.circom` | `f8f399fd9b05b5946f9f63287eec1ab8d48174b966b6ebcc4c476a493931ab2c` | 일치 |
| S | `node_modules/circom-bigint/circuits/bigint_func.circom` | `5b2728169951cf380309c9f2ff3e56ea7be20eca0e6f0d2a947d815b2516154c` | 일치 |
| S | `node_modules/circomlib/circuits/bitify.circom` | `688f121303a2dd0154ceeda8d2f53a9d2d26789d10a69a46acd534642725683e` | 일치 |
| S | `node_modules/circomlib/circuits/comparators.circom` | `fd0c7723ee56e1467df1861131157cbb108e156fe2d9ec64895c8e68de14db20` | 일치 |
| S | `node_modules/circomlib/circuits/mux1.circom` | `eaa61d34d40b03a1695212c012f5793c06f6d0db634878a0246249ba12a40922` | 일치 |
| S | `node_modules/circomlib/circuits/poseidon.circom` | `2582464669b69827164bd08ee0337997e1957f2ab4f00cdd86d533ca5e9d9234` | 일치 |

## N5 우선 적용 차이

B2 지시 4절은 각 대상의 첫 seed spec 명령으로 파서를 확인하라고 한다. N5의 B 실행 전 보충은 B 60 spec 전부의 파서 수용 확인을 요구한다. 첫 seed 20개 대상·방식 그룹의 3,393개 entrypoint를 실제 확인했고, [source·명령 동등성 증명](../runs/n6-b2-2026-10-09.noindex/parser-source-equivalence.json)으로 세 seed의 `source_snapshots`, `targets` 명령, `pinned_files`, `pinned_trees`가 각 그룹에서 같음을 확인해 결과를 60 spec 전체에 연결했다. N5의 전체 spec 범위를 기준으로 해석했고, B2의 첫 seed 실행 절차는 이 동등성 근거와 함께 적용했다.

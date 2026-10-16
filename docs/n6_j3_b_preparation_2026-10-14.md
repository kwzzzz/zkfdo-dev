# N6-J3 B 맥락 판정 준비 — 부분 완료 (2026-10-14)

## 범위와 중단 상태

[N6-J3 지시](../runs/handoff/n6_j3_instruction_2026-10-14.md)의 SHA-256 `ad045c202f810e308bec73df2b2dbf90135e7952bd175cc514a46723840aff5a`를 확인했다. 이번 폴더는 **B 본 실행 scope만** 대상으로 한다. 고정 [N5 프로토콜](n5_evaluation_protocol_v1_2026-10-06.md)의 J 기준 입력 순서 (a) zkbugs → (b) 같은 entrypoint의 L 계열 → (c) 커밋 JSON → (d) 수정하지 않은 프로젝트 테스트·입력 도구 → (e) 0 입력과 두 R1CS 검사 규칙을 그대로 적용하도록 새 진입 파일을 준비했다. A의 inventory·기준 입력·요청·J 실행 함수를 재사용하며 A 산출물은 덮어쓰지 않았다.

`runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json`은 마지막 확인 때 `running`이었다(6단위 중 첫 anon-aadhaar 단위 실행). 사용자의 순서 조건 때문에 **기준 입력 수집·컴파일·witness 생성·2건 시범은 아직 실행하지 않았다.** B J 본 실행, mem20 B 실행, 의존성 설치, zkFuzz 실행도 하지 않았다. 아래 107건은 후보 inventory 수이며 호출 가능 수가 아니다. 호출 가능 수·준비 실패 수·시범 결과·전체 B J 시간과 디스크 추정은 mem20 상태가 `completed`가 된 뒤에만 확정할 수 있다.

## 후보 inventory와 요청 계획

B 본 실행의 압박 없는 선택 run 30/30에서 W 후보 0건, S 후보 **107건**을 확인했다. 후보 파일은 경로·SHA-256만 검사했고 JSON 내용이나 후보 값은 열지 않았다. 후보 SHA 107개와 `(unit, method, attempt, candidate_index)` 식별자 107개는 각각 중복이 없었다. 이 고유성은 B 본 실행의 관측이며 후속 mem20 scope에 자동 적용하지 않는다.

| B 리비전 | 저장소 | 제약 수(원본 queue) | W 후보 | S 후보 | 공식 기준 입력·호출 가능 상태 |
| --- | --- | ---: | ---: | ---: | --- |
| `6079a717f929aaf04a04e329` | anon-aadhaar/anon-aadhaar | 1,115,080 | 0 | 9 | 대기 |
| `340107e1f1d8b0a45656cffa` | DoraFactory/Vota-Circuits | 4,802,568 | 0 | 4 | 대기 |
| `b5b5cf5dacdeebd430b519f8` | iden3/circuits | 114,758 | 0 | 12 | 대기 |
| `4c221df76273c0d7cf18048c` | pantherfoundation/panther-core | 111,270 | 0 | 12 | 대기 |
| `a8b2aa9c2857e79c017805bb` | rarimo/passport-zk-circuits | 733,264 | 0 | 70 | 대기 |
| `83cc00608fdaa7191b839ed6` | selfxyz/self | 102,406 | 0 | 0 | 대상, 요청 없음 |
| `77e0f2db173d0c1812de503a` | tanctl/zylith-old | 311,639 | 0 | 0 | 대상, 요청 없음 |
| `e71f158d85178fd29e1ba300` | tangle-network/protocol-solidity | 290,196 | 0 | 0 | 대상, 요청 없음 |
| `76053f7fb015aba5e093d82d` | Zellic/zkerc20 | 331,643 | 0 | 0 | 대상, 요청 없음 |
| `60271bae486ade95f8b72540` | iden3/circuits | 116,498 | 0 | 0 | 대상, 요청 없음 |

[후보 inventory](../runs/n6-j3-2026-10-14.noindex/candidate-inventory.json), [10리비전 manifest](../runs/n6-j3-2026-10-14.noindex/revision-manifest.json), [요청 계획 index](../runs/n6-j3-2026-10-14.noindex/request-index-pending.json)를 새로 썼다. 계획 index에는 107개의 순서·source·wrapper·후보 해시를 연결했지만 `status=awaiting_base_input`이고 `base_input` 또는 실행용 request 파일은 없다. `run_n6_j1.py`에 넘길 수 있는 최종 index가 아니다. B에서 zkbugs 연결 항목이 없으므로 manifest의 (a) 입력 목록은 비어 있으며, (b)~(e)의 결과를 미리 가정하지 않았다.

### B 분할 spec의 라이브러리 경로

S spec의 preflight `-l` 목록 중 후보 요청 기준 **190회, 고유 경로 26개**가 pinned split source snapshot의 `{workspace}` 아래에 실제 존재하지 않았다. 이는 위 후보가 있는 5리비전 모두에서 관측됐다. 빠진 경로는 전부 `{workspace}` 유래였고, 원본 프로젝트를 가리키는 절대 `-l` 경로는 존재했다. 새 요청 계획은 빠진 경로를 각 행의 `unavailable_preflight_library_paths`에 남기고, 존재하는 경로만 원래 순서로 `library_paths`에 둔다. B 전용 [실행 진입 파일](../scripts/run_n6_j3_b.py)은 A 실행기의 검증 중 같은 정규화를 적용한다. 소스 snapshot·고정 spec은 고치지 않았다.

이 정규화는 없는 디렉터리가 import를 해결할 수 없다는 판단에 의존한다. 실제 J의 동일 import 해석과 source tree SHA 검증은 **아직 확인되지 않았다**. mem20 완료 뒤 최종 요청 index의 `validate-only`가 통과해야 하며, 실패하면 J를 시작하지 않고 실패를 기록한다. 결함을 숨기기 위해 패키지를 설치하거나 고정 source를 바꾸지 않는다.

## 입력 고정과 현재 검증

| 산출물 | SHA-256 |
| --- | --- |
| [후보 inventory](../runs/n6-j3-2026-10-14.noindex/candidate-inventory.json) | `7100a14ce308d8a32612fd136efd6ac836d08caf719d63b7dcdba1089ef98e56` |
| [리비전 manifest](../runs/n6-j3-2026-10-14.noindex/revision-manifest.json) | `e648cd6df7d647963a12aae4a1f15aedcacd28029a63fa4bd341a182af810cba` |
| [요청 계획 index](../runs/n6-j3-2026-10-14.noindex/request-index-pending.json) | `732d982745a0b8109e34912c3585db3d326de1d8f33c4d2de1bc4fa48326ac60` |
| [준비 입력 SHA 목록](../runs/n6-j3-2026-10-14.noindex/b-j-preparation-inputs.sha256) | `a6483d8e3ad2f32fabfdba2bd98712068c79c09aaaa0ebb83389301855e82a55` |

| 새 코드 | SHA-256 |
| --- | --- |
| [B inventory](../scripts/n6_j3_b_inventory.py) | `e1ba0f68ac64ad305d454220eebbc540d98ca0b10e68ebd005c21fb095559699` |
| [B 요청 계획·최종화](../scripts/n6_j3_b_requests.py) | `13f2f1947b097f29211b969e8ef195b4c9bc94c3a3699650cf921022fd40222c` |
| [B 기준 입력 선택](../scripts/n6_j3_b_base_inputs.py) | `867ed66072e1c48abd571245346ed028bf537ecad4150ab1e668d377683e8643` |
| [B J 실행 진입](../scripts/run_n6_j3_b.py) | `f67511c5feede08ee5ce8f0cad56757a1d27b71814aee60abcccf07dd0989819` |
| [B 2건 wait4 시범](../scripts/n6_j3_b_pilot_wait4.py) | `0d266fe3d2098c589017cd7c3a1ecbcbd983252464be61c31e23934a4276d9a7` |

준비 입력 SHA 목록은 도구·A와 B의 재사용 스크립트·B queue/state/대상·세 새 index·후보 파일 107개 등 **125개 파일**을 기록하며 `shasum -a 256 -c` 125/125가 통과했다. 후보 내용은 해시 계산 외에는 읽지 않았다. Python 파일 5개의 구문 분석은 통과했다. 사용자 순서 조건에 따라 `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`는 아직 실행하지 않았으며 mem20 완료 뒤 코드 변경 종료 전에 수행해야 한다.

## mem20 완료 뒤에만 수행할 후속 절차

1. mem20 B `state.json`의 `status=completed`를 확인한다. 실패·중단이면 아래 수집과 시범을 시작하지 않는다. 준비 입력 SHA 목록 125/125를 다시 검산한다.
2. `python3 scripts/n6_j3_b_base_inputs.py --scope main`을 실행한다. 이 B 전용 파일은 A 선택 함수를 그대로 호출하되 27행 고정 관문을 B 본 scope 10행으로 바꾸고, mem20 완료 guard를 건다. (d)의 환경 실패는 그대로 기록하고 설치로 재시도하지 않는다. 출력은 `runs/n6-j3-2026-10-14.noindex/base-inputs/`다.
3. `python3 scripts/n6_j3_b_requests.py --scope main --base-index runs/n6-j3-2026-10-14.noindex/base-inputs/index.json`으로 최종 107행 `request-index.json`과 request 파일을 새로 만든다. 이때 리비전×방식별 호출 가능·`base_input_unavailable` 수를 확정한다. 새 index·기준 입력·엔진·circom·실행기·inventory SHA를 `j-execution-inputs.sha256`에 기록하고 검산한다. `python3 scripts/run_n6_j3_b.py --index <절대 경로>/request-index.json --index-sha256 <실제 SHA> --cache-root <기존 빈 디렉터리> --action validate-only`의 source tree/경로 검증을 먼저 통과시킨다.
4. 호출 가능한 리비전 중 제약 수 최대 S 첫 요청과 최소 S 첫 요청만 [B 2건 시범 파일](../scripts/n6_j3_b_pilot_wait4.py)로 `wait4` 측정한다. 둘 이상이면 서로 다른 리비전을 고르고 동률은 리비전 ID 순으로 정한다. 하나뿐이면 그 리비전의 서로 다른 첫 S 요청 2개를 고른다. 호출 가능 S 요청이 총 2건 미만이면 시범 불가를 그대로 보고한다. 중단 조건은 J2 v2와 같고 다른 무거운 작업과 병행하지 않는다. 두 시범의 요청별 벽시계·최대 RSS·캐시/출력 증가를 기록한 뒤, 호출 가능 요청 수에 대한 리비전별 정리 사용 시 전체 B J 시간·디스크 용량 **계획값**을 계산한다. 이 계획값은 상한이나 성능 결과가 아니다.
5. 코드 변경 필수 검사(`cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`)를 수행하고 결과를 기록한다. 그 뒤에만 이 문서에 호출 가능 표·시범 표·추정·최종 입력 SHA를 덧붙여 준비를 완료한다.

아래는 **준비용 B J 본 실행 명령 형태**다. 현재 최종 index와 `j-execution-inputs.sha256`이 없으며 이 작업에서는 실행하지 않는다. mem20 B 완료, 125개 준비 입력 재검산, 기준 입력 수집, 최종 입력 해시 목록 재검산, `validate-only`, 2건 시범, 필수 검사 뒤에만 리드가 사용할 수 있다. `--cleanup-cache-per-revision`과 별도 내장 캐시를 사용한다.

```sh
shasum -a 256 -c /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j3-2026-10-14.noindex/j-execution-inputs.sha256 && mkdir -p /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j3-2026-10-14.noindex/cache-j-execute.noindex && caffeinate -dimsu python3 /Users/miiz/Desktop/kwzzzz_zkfr/scripts/run_n6_j3_b.py --index /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j3-2026-10-14.noindex/request-index.json --index-sha256 "$(shasum -a 256 /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j3-2026-10-14.noindex/request-index.json | awk '{print $1}')" --cache-root /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j3-2026-10-14.noindex/cache-j-execute.noindex --cleanup-cache-per-revision --action execute --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j3-2026-10-14.noindex/j-execute.noindex > /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-j3-2026-10-14.noindex/terminal-j.log 2>&1; rc=$?; printf 'exit_code=%s\n' "$rc"
```

mem20 scope는 이번에 수집하지 않았다. 완료 뒤 같은 `n6_j3_b_inventory.py --scope mem20`, `n6_j3_b_base_inputs.py --scope mem20`, `n6_j3_b_requests.py --scope mem20`을 별도 기본 파일·폴더에 적용할 수 있다. mem20 후보 SHA가 서로 같으면 A 공용 inventory/runner의 후보 SHA 고유성 관문이 거부할 수 있으므로, 이 경우 결과를 합치지 말고 새 버전에서 안정 후보 ID를 사용해야 한다.

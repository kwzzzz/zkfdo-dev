# N6-A3 준비·검증 결과 (2026-10-08)

## 상태와 범위

메모리 민감도 12단위와 pragma 보정 6단위의 spec·preflight·대기열을 새 `runs/n6-a3-2026-10-08.noindex/`에 준비했다. **A·B campaign은 실행하지 않았고, 후보 내용·J·사람 검토도 열람하거나 수행하지 않았다.** 두 대기열은 `validate-only`를 통과했으나, pragma 보정본의 S 두 조각이 짧은 zkFuzz 파서 확인에서 여전히 `P1003`을 내므로 pragma 실행 관문은 **미통과**다. [세부 근거 JSON](n6_a3_preparation_2026-10-08.json)과 [새 파일별 SHA-256 목록](../runs/n6-a3-2026-10-08.noindex/file-sha256-manifest.jsonl)을 함께 둔다.

## 1. 메모리 상한 대상 재계산

A 본 실행 `a-execute-2.noindex`의 81단위에서 선택된 비압력 run의 W/S ledger 종료 사유만 다시 읽었다. 정확히 다음 4개 대상 × seed 3개 = **12단위**에서 W `memory_cap`이 나타났고 S는 **0단위**다. 아래 수치는 각 선택 run에서 `memory_cap`으로 끝난 W 시도 수다. 12단위 중 10개는 `environment_pressure` 뒤의 선택된 재실행, aq-040의 seed 02·03은 첫 실행을 기준으로 했다. 단위별 선택 근거와 ledger SHA-256은 [정규화 증거](../runs/n6-a3-2026-10-08.noindex/mem20/normalization-evidence.json)에 있다.

| 대상 | seed 01 | seed 02 | seed 03 |
|---|---:|---:|---:|
| `aq-006-1680f955c185` | 25 | 26 | 25 |
| `aq-007-0bb83f9eab0f` | 26 | 25 | 25 |
| `aq-008-9c9e702d061d` | 25 | 25 | 25 |
| `aq-040-da54d3e7bc8a` | 22 | 10 | 9 |

새 W/S spec 24개의 JSON 값 차이는 원본 v4 spec 대비 `campaign_id`와 `memory_cap_bytes` (`10737418240` → `21474836480`)뿐이다. 두 필드를 제거한 정규화 JSON SHA-256이 24쌍 모두 일치한다. 기존 v4 preflight를 새 spec 해시에 연결한 [재사용 증명](../runs/n6-a3-2026-10-08.noindex/mem20/preflight-reuse-mem20.json)은 24/24 통과했고, v4 검증기로 연결된 snapshot 813개를 확인했다. 여기서는 새 컴파일을 실행하지 않았다.

## 2. pragma 보정 파일과 R1CS 동등성

원본 A1b 준비 폴더는 보존하고 두 대상의 `project`를 A3로 복사했다. 대상마다 16개 파일에서 정확히 `pragma circom 2.2.2;` 한 줄만 `pragma circom 2.2.1;`로 바꿨다. aq-035의 S snapshot에도 같은 한 줄 변경 2개가 필요했다. 다른 변경은 없다. 34개 파일의 경로·전후 SHA-256·줄 수는 [파일 목록](../runs/n6-a3-2026-10-08.noindex/pragma/source-changes.json)에, 줄 단위 증명은 [diff](../runs/n6-a3-2026-10-08.noindex/pragma/source-diff.patch)에 있다. 새 파일은 모두 versioned 사본이며 원본 project·snapshot·plan은 수정하지 않았다.

고정 circom `/Users/miiz/.cargo/bin/circom` (SHA-256 `8991887889c2a74d6fc704d5689ada4cc76fba004e866c987de6cbf3b3db6227`)으로 W entrypoint를 동일 옵션으로 각각 컴파일했다. 두 대상 모두 원본·보정본 `.r1cs`가 바이트 단위로 같다. [컴파일 근거](../runs/n6-a3-2026-10-08.noindex/pragma/r1cs-equivalence.json)

| 대상 | 원본 R1CS SHA-256 | 보정본 R1CS SHA-256 |
|---|---|---|
| `aq-035-8f826c822cb8` | `823332515398062ef5f10deeaa51e6d9d6542622bfe0acef37b4a6a120c76365` | `823332515398062ef5f10deeaa51e6d9d6542622bfe0acef37b4a6a120c76365` |
| `aq-036-6d7df64759b6` | `3230ec50539173002837dcbe8f5b49b61628a06b45983c03798e6f421aba052a` | `3230ec50539173002837dcbe8f5b49b61628a06b45983c03798e6f421aba052a` |

## 3. 파서 확인과 차단 원인

고정 zkFuzz를 각 W entrypoint와 S 조각에 임시 작업 폴더에서 최대 14초 동안 띄웠다. 각 프로세스 그룹을 종료했고 임시 폴더를 삭제했다. 최종 기록 15건의 실제 최대 경과 시간은 14.096초다. stderr에서 `error[P` 유무와 종료 방식만 확인했으며 출력·후보 내용은 열람하지 않았다. [최종 확인](../runs/n6-a3-2026-10-08.noindex/pragma/parser-check-v2.json)과 [차단 근거](../runs/n6-a3-2026-10-08.noindex/pragma/parser-blocker-v2.json)를 참조한다. 최초 15초 제한 시험은 polling 오차로 최대 15.10초가 걸려 별도 진단 파일로 보존하고, 이 표에는 쓰지 않았다.

| 조건 | 범위 | `error[P` | 종료 방식 |
|---|---|---:|---|
| 보정본 W | aq-035·aq-036 | 0/2 | 시간 상한에서 프로세스 그룹 종료 1, 상한 전 종료 1 |
| 보정본 S | aq-035 6조각·aq-036 3조각 | **2/9** | 문제 2건은 약 0.1초 만에 종료 코드 1; 나머지 7건은 상한 종료 또는 자체 종료 |
| 원본 재현 | W 2개·aq-035 S 문제 조각 2개 | 4/4 (`P1003`) | 모두 약 0.1초 만에 종료 코드 1 |

문제 S target은 `sha256:aa0e65d0…`, `sha256:8e2b67af…`이다. 두 wrapper가 원본 `.../aq-035-8f826c822cb8/project/circuits/utils/assert.circom`을 **절대경로**로 include한다. 따라서 새 snapshot과 `-l` 경로가 있어도 zkFuzz는 원본의 `pragma circom 2.2.2;`를 읽는다. [N6-A3 지시](../runs/handoff/n6_a3_instruction_2026-10-08.md)는 wrapper 유지와 전체 S 파서 수용을 동시에 요구한다. 현재 경로 구조에서는 둘을 함께 만족할 수 없어 wrapper나 원본을 바꾸지 않았다. **현 pragma queue는 실행하지 않아야 한다.**

## 4. spec 차이와 preflight 36건

| 구분 | 원본 v4 spec 대비 허용·필요 차이 | preflight |
|---|---|---|
| 메모리 W/S 24개 | `campaign_id`, `memory_cap_bytes`만 변경. 나머지 JSON 값 정규화 일치 | 기존 v4 결과에 해시 연결 24/24 통과 |
| pragma W/S 12개 | `campaign_id`; `source_snapshots` 경로·변경된 tree SHA-256; 명령의 원본 project `-l` 경로. 새 preflight의 무결성 검사 때문에 W `entrypoint_sha256`과 aq-035 S의 versioned plan pin·plan snapshot 경로 바인딩도 갱신 | v4 `preflight` 새로 실행 12/12 통과, 컴파일 대상 33/33 성공 |

pragma 추가 필드는 지시의 짧은 목록을 넘어가지만 새 소스·plan을 원본 해시로 잘못 선언하지 않기 위해 필요했다. [정확한 327개 JSON 경로별 차이](../runs/n6-a3-2026-10-08.noindex/pragma/spec-difference-audit.json)와 [원본·보정 spec 쌍](../runs/n6-a3-2026-10-08.noindex/pragma/spec-differences.json), [새 preflight 증명](../runs/n6-a3-2026-10-08.noindex/pragma/preflight-proof.json)을 남겼다. 사전 점검 중 sandbox의 `ps` 권한 실패와 aq-036 S의 불필요한 snapshot 경로 바인딩을 제거한 진단도 별도 보존했다. 최종 12개는 모두 새 v4 preflight 통과다. 예산 600초, S 시도 30초, seed, 10 GiB, 조각 목록과 wrapper 바이트는 그대로다.

## 5. 대기열 실행기 v4.2와 두 queue

새 [v4.2 실행기](../scripts/run_n6_v4_2_queue.py)는 v4.1에서 queue `concurrency`를 정수 1 또는 3으로 검사하고 worker 수·동시 시작 상한에 적용하는 부분만 바꿨다(문서 문자열 제외). 나머지 관문·상태·건강 기록·`environment_pressure` 재실행은 그대로다. [새 테스트](../tests/n6_v4_2_queue_test.py)는 1에서 단위 실행이 겹치지 않고 기록된 동시 실행 수가 모두 1임을 확인하며, 1·3 외 값과 bool·문자열·float를 거부한다. v4.1·v4.2 Python 테스트 합계 **22건 통과**했다.

| Queue | 순서·동시 실행 | spec / preflight | SHA-256 | validate-only |
|---|---|---:|---|---|
| [pragma](../runs/n6-a3-2026-10-08.noindex/queue-a3-pragma.json) | seed마다 aq-035 → aq-036, 동시 3 | 12 / 새 12 | `1a8782b4a15bbb8b647bd5b98e34843cc81b9ebea051319f525dca60a7d12df7` | 통과, 6단위 |
| [mem20](../runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json) | 본 실행 queue 순서, 동시 1 | 24 / 재사용 연결 24 | `4096d515672347b51aa6cfe45a54efe1449c2edf1817ef8073c1582d5a564125` | 통과, 12단위 |

출력은 각각 `pragma-execute.noindex`, `mem20-execute.noindex`로 지정했다. v4 엔진 SHA-256은 `ff36c6db0a7475064c388a9bd0b0a1845863329f1fe2e2b40f06dec641fa9451`, v4.2 queue 실행기는 `2d3a16ab6581dffb709dfa1c60dcab67801644b618d3c8dd2616fe701693a0ad`다. 두 queue는 형식 검증만 통과했으며 실행 가능성 판정은 §3의 파서 실패 때문에 보류한다.

## 6. 필수 검사와 실행 명령

`cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`, Python v4.1·v4.2 queue 테스트가 모두 종료 코드 0이었다. `git diff --check`도 통과했다. 캠페인은 0회 실행했다.

아래는 요청된 **터미널 한 줄 명령의 보류본**이다. 맨 앞에서 v4 엔진·v4.2 queue 실행기·두 queue 파일의 SHA-256을 검사하고, 현재 실패 상태인 파서 기록을 검사해 **campaign 전에 종료**한다. 파서 차단을 해결해 새 결과와 queue 해시를 기록하기 전에는 실행하지 않는다. 파서 관문을 통과한 버전으로 갱신되면 pragma 종료 코드와 관계없이 mem20을 이어 실행하고, 로그·종료 코드를 각각 남기도록 구성했다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && printf '%s\n' 'ff36c6db0a7475064c388a9bd0b0a1845863329f1fe2e2b40f06dec641fa9451  scripts/run_policy_a_engine_v4.py' '2d3a16ab6581dffb709dfa1c60dcab67801644b618d3c8dd2616fe701693a0ad  scripts/run_n6_v4_2_queue.py' '1a8782b4a15bbb8b647bd5b98e34843cc81b9ebea051319f525dca60a7d12df7  runs/n6-a3-2026-10-08.noindex/queue-a3-pragma.json' '4096d515672347b51aa6cfe45a54efe1449c2edf1817ef8073c1582d5a564125  runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json' | shasum -a 256 -c && python3 -c 'import json,sys; sys.exit(json.load(open("runs/n6-a3-2026-10-08.noindex/pragma/parser-check-v2.json"))["status"] != "passed")' && caffeinate -dimsu sh -c 'python3 scripts/run_n6_v4_2_queue.py --queue runs/n6-a3-2026-10-08.noindex/queue-a3-pragma.json --output runs/n6-a3-2026-10-08.noindex/pragma-execute.noindex --action execute > runs/n6-a3-2026-10-08.noindex/terminal-a3-pragma.log 2>&1; pragma_rc=$?; printf "pragma exit=%s\n" "$pragma_rc"; python3 scripts/run_n6_v4_2_queue.py --queue runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json --output runs/n6-a3-2026-10-08.noindex/mem20-execute.noindex --action execute > runs/n6-a3-2026-10-08.noindex/terminal-a3-mem20.log 2>&1; mem20_rc=$?; printf "mem20 exit=%s\n" "$mem20_rc"; test "$pragma_rc" -eq 0 && test "$mem20_rc" -eq 0'
```

## N6-A3b: S wrapper 절대경로 보정과 재검증 (2026-10-08)

이 절은 [추가 지시](../runs/handoff/n6_a3b_instruction_2026-10-08.md)에 따른 후속 결과다. 위 §3의 파서 차단과 §6의 보류 명령은 당시 기록으로 남긴다. **현재 실행 준비의 기준은 이 절의 검증 결과와 아래 최종 명령이다.** A·B campaign은 실행하지 않았고 후보 내용·J·사람 검토도 열람하거나 수행하지 않았다. 세부 행별 근거는 [N6-A3b JSON](n6_a3b_preparation_2026-10-08.json)에 있다.

### 보정 줄·절대경로 전수 확인

기존 A3 보정 snapshot의 Circom 파일 304개를 전수 검사하니 A1b 원본 project를 절대경로로 include하는 wrapper가 aq-035의 S 6개와 aq-036의 S 3개, 총 **9개**였다. 두 P1003 조각 외에도 추가 지시 3항에 따라 같은 규칙을 적용했다. 각 새 버전 snapshot의 wrapper에서 `include` 경로가 있는 **3번째 줄 한 줄만** 같은 상대 위치의 A3 보정 project 파일을 가리키도록 바꿨다. 원본 wrapper·A3 snapshot은 그대로다. 새 버전 snapshot에서 남은 A1b 절대경로 include는 **0건**이다. [전후 파일 SHA-256](../runs/n6-a3-2026-10-08.noindex/pragma-b/wrapper-corrections.json)·[줄 diff](../runs/n6-a3-2026-10-08.noindex/pragma-b/source-diff.patch)·[전수 검사](../runs/n6-a3-2026-10-08.noindex/pragma-b/absolute-include-inventory.json)를 보존한다.

고정 circom으로 원본 wrapper+원본 project와 보정 wrapper+보정 project를 preflight와 같은 옵션으로 컴파일한 `.r1cs` SHA-256이 **9/9 바이트 동일**했다. 처음 막힌 두 조각의 전후 해시는 다음과 같고, 나머지 7개 해시는 [전체 R1CS 근거](../runs/n6-a3-2026-10-08.noindex/pragma-b/r1cs-equivalence.json)에 있다.

| 원래 S target → 새 target | 원본·보정 R1CS SHA-256 |
|---|---|
| `sha256:aa0e65d0…` → `sha256:90d3c3ff…` | `eb06c189242c6a37841502bb97fbfa09cc3072ffa9c801e74a1b3f87b0df0902` |
| `sha256:8e2b67af…` → `sha256:e5a05f0b…` | `59153f4e4adef474aacd2076a6b7abbe3da71fcd44db4e3c96338a6f20de5d11` |

조각 식별자는 원본 source fingerprint에 wrapper 해시가 들어가므로 9개 모두 바뀐다. [원래 ID ↔ 새 ID 대응표](../runs/n6-a3-2026-10-08.noindex/pragma-b/target-id-map.json)를 만들고 `stable_target_id` 정의에 따라 9개를 독립 재계산해 [검산](../runs/n6-a3-2026-10-08.noindex/pragma-b/target-id-verification.json)했다. 이 대응으로 후속 J·정답 대조에서는 같은 조각을 추적한다. 이 작업에서 J 자체는 수행하지 않았다.

### 파서·preflight·queue

새 wrapper를 사용하는 보정본 W 2개와 S 9개를 고정 zkFuzz로 다시 확인했다. [parser-check-v3](../runs/n6-a3-2026-10-08.noindex/pragma-b/parser-check-v3.json)는 **11/11 `error[P` 없음**, 최대 경과 13.628초(<14초), 종료 뒤 프로세스 그룹 잔존 0, 임시 작업 폴더 삭제로 `status: passed`다. seed 3개의 target ID·entrypoint 해시가 동일함을 확인하고 seed 01의 고유 11개를 검사했다.

두 versioned plan과 S spec 6개에는 새 snapshot 경로·tree SHA, wrapper의 외부 파일 pin, entrypoint SHA와 새 target ID를 반영했다. [spec·plan 차이 전체](../runs/n6-a3-2026-10-08.noindex/pragma-b/spec-differences.json)에 기록했다. 예산 600초·S 시도 30초·10 GiB·seed·순위/조각 순서·명령·campaign ID는 유지했다. 파서 통과 후 새 v4 preflight에서 S **6/6 spec·27/27 컴파일**이 성공했고, 기존 A3 W 통과 6건과 합친 [12/12 spec·33/33 컴파일 증명](../runs/n6-a3-2026-10-08.noindex/pragma-b/preflight-proof-v2.json)을 남겼다. sandbox의 자원 감시 권한 실패는 [진단](../runs/n6-a3-2026-10-08.noindex/pragma-b/sandbox-preflight-monitor-diagnostic.json)으로 보존하고, 허용된 preflight 전용 재실행으로 최종 결과를 얻었다.

새 [pragma queue](../runs/n6-a3-2026-10-08.noindex/queue-a3b-pragma.json)는 **6단위·12 spec `validate-only` 통과**, SHA-256 `c91e572aaa91582bd46d88b54e9e1bb9a5ce34509af286b65f41aaf22983fc4f`다. 두 대상의 seed별 순서, 동시 3, 관문·건강 기록, v4 엔진 및 v4.2 queue 실행기 pin은 유지했다. [mem20 queue](../runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json)는 수정하지 않았으며 SHA-256 `4096d515672347b51aa6cfe45a54efe1449c2edf1817ef8073c1582d5a564125`로 재확인했다. 새 pragma 출력 경로는 `pragma-b-execute.noindex`다.

Python v4.1·v4.2 queue 테스트 22건과 `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`, `git diff --check`가 모두 통과했다. 새 파일별 해시는 [N6-A3b 목록](../runs/n6-a3-2026-10-08.noindex/file-sha256-manifest-a3b.jsonl)에 기록한다.

### 최종 터미널 명령 — 작성만 하고 실행하지 않음

맨 앞에서 v4 엔진·v4.2 queue 실행기·새 pragma queue·기존 mem20 queue 해시를 확인하고 `parser-check-v3.json`의 `passed`를 확인한다. 그 뒤 pragma와 mem20을 차례로 실행하도록 작성했다. pragma 종료 코드가 0이 아니어도 mem20은 이어 실행하며 로그와 종료 코드를 각각 남긴다. **이 작업에서는 아래 명령을 실행하지 않았다.**

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && printf '%s\n' 'ff36c6db0a7475064c388a9bd0b0a1845863329f1fe2e2b40f06dec641fa9451  scripts/run_policy_a_engine_v4.py' '2d3a16ab6581dffb709dfa1c60dcab67801644b618d3c8dd2616fe701693a0ad  scripts/run_n6_v4_2_queue.py' 'c91e572aaa91582bd46d88b54e9e1bb9a5ce34509af286b65f41aaf22983fc4f  runs/n6-a3-2026-10-08.noindex/queue-a3b-pragma.json' '4096d515672347b51aa6cfe45a54efe1449c2edf1817ef8073c1582d5a564125  runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json' | shasum -a 256 -c && python3 -c 'import json,sys; sys.exit(json.load(open("runs/n6-a3-2026-10-08.noindex/pragma-b/parser-check-v3.json"))["status"] != "passed")' && caffeinate -dimsu sh -c 'python3 scripts/run_n6_v4_2_queue.py --queue runs/n6-a3-2026-10-08.noindex/queue-a3b-pragma.json --output runs/n6-a3-2026-10-08.noindex/pragma-b-execute.noindex --action execute > runs/n6-a3-2026-10-08.noindex/terminal-a3b-pragma.log 2>&1; pragma_rc=$?; printf "pragma exit=%s\n" "$pragma_rc"; python3 scripts/run_n6_v4_2_queue.py --queue runs/n6-a3-2026-10-08.noindex/queue-a3-mem20.json --output runs/n6-a3-2026-10-08.noindex/mem20-execute.noindex --action execute > runs/n6-a3-2026-10-08.noindex/terminal-a3b-mem20.log 2>&1; mem20_rc=$?; printf "mem20 exit=%s\n" "$mem20_rc"; test "$pragma_rc" -eq 0 && test "$mem20_rc" -eq 0'
```

# N6-B6: B 엄격층 1묶음 기록과 탐색층 구성 기준 입력 (2026-10-18)

상태: 준비 중. B 후보 값(입력·witness), B 요청 index의 행, 퍼징 ledger 후보 필드, J 출력과 B 판정 결과를 열지 않는다. 엄격층 본 결과와 구성 입력 탐색층은 분리한다. S 재퍼징과 B 판정은 실행하지 않는다.

## 1. 지시·개정 고정

- 지시서: `runs/handoff/n6_b6_instruction_2026-10-18.md` SHA-256 `577995c26a37302fae407b41f82c2d723060a9774933fc0f9f33f6056e0808bf`.
- N5 개정 8절 추가 뒤 `docs/n5_amendment_b_judging_2026-10-17.md` SHA-256 `751c305aacd5fb63683551efcb8b867597ddc95739e8ab9eac0cc08d18fabb72`.
- 개정 → N5 연결 갱신 뒤 `docs/n5_evaluation_protocol_v1_2026-10-06.md` SHA-256 `71a1fde76db1a8fd311d74173ee241d05d4f7c560c58f1f73a17e6bdb20c47a6`.

## 2. 엄격층 1묶음

## B 엄격층 1묶음: 상태 파일만으로 확인한 범위

읽은 근거는 `runs/n6-b5-2026-10-17.noindex/batch1-prep.noindex/stages/{preflight,base-inputs,entrypoints,index}/state.json` 네 파일뿐이다. B 후보 값·판정 결과·요청 index 행·J 출력은 열지 않았다. 엄격층 출력은 바꾸거나 다시 실행하지 않았다.

| 단계 | 상태 파일의 결과 | 근거 SHA-256 |
|---|---|---|
| preflight | 완료, exit code 0. Docker info·system df 검사 exit code 0. 기준 R1CS 참조 파일의 고정 SHA-256 `b1e3e893ef7163f1918fb9a144bf368b2a0fb20b85cd975366da32352391a79b`. | `cf23c12125ca0c6df002179d0575b5e3a5931c6f239d742559efb22e33703c72` |
| base-inputs | 완료, exit code 0, 리비전 10개. 생성된 기준 입력 index의 기록 SHA-256 `460130af7e74f2a5fe2d103f4b90029eb3a816184e817dae9b143ee1427d53b3`. | `e038908f7379e75fd4f27e03d12a2814cdc9a9db3ddbc88c0c96765601a7cd99` |
| entrypoints | 완료, exit code 0, 행 10개. 분류표의 기록 SHA-256 `126745ca432de49f4ee7bdf901d8f4eb81082b96eb11b4b623c29f61057bd660`. | `e3deeec9f8522d05dd3e1ca48cf2e42ea96c4ed91bcc3b78fd6bab2a4d55ecb7` |
| index | 실패, exit code 1, `RunnerError`. 상태 파일은 구체 실패 이유를 적지 않는다. | `ea332b4941ef90d940604dba7c860e32e457abae333c56276e2071bd736a9d5c` |

상태 파일 자체에는 10개 리비전의 (a)~(e)와 107개 요청의 행별 준비 실패가 없다. 이 부분은 새 `scripts/n6_b6_strict_final_index.py`가 상태 파일에 기록된 기준 입력 index의 SHA-256을 확인하고, 그 index와 기존 v1·v2.2 요청 index를 **프로그램 안에서만** 읽어 검증했다. B 요청 행·하위 템플릿·신호 이름·요청 ID·후보 경로·후보 값은 화면이나 보고서에 내지 않았다. 스크립트가 107행 전부 `preparation_failure=base_input_unavailable`, 요청 있는 5개 리비전의 기준 입력 없음, 두 엔진 index의 요청 행 동일을 확인했다. 원본 v1 index의 바이트를 새 경로 `runs/n6-b6-2026-10-18.noindex/strict-final-index.json`에 그대로 복사했으며, 기존 `batch1-prep.noindex`는 수정하지 않았다.

| 리비전 | B 요청 | 기준 입력 | c: 커밋 JSON | d: 프로젝트 시험·설치 | e: 영 입력 | R1CS |
|---|---:|---|---|---|---|---|
| `340107e1` | 4 | 없음 | 3회, main 입력 키 불일치 | 일치하는 시험·도구 없음 | 정직 witness 실패 | 일치 |
| `4c221df7` | 12 | 없음 | 217회, main 입력 키 불일치 | 원본 시험 실패, 설치 뒤 build 실패 | 정직 witness 실패 | 일치 |
| `60271bae` | 0 | 있음: `e_zero` | 5회, main 입력 키 불일치 | 일치하는 시험·도구 없음 | **통과** | 일치 |
| `6079a717` | 9 | 없음 | 15회, main 입력 키 불일치 | 추적된 설치 산출물에 별도 규칙 필요 | 정직 witness 실패 | 일치 |
| `76053f7f` | 0 | 없음 | 1회, main 입력 키 불일치 | 일치하는 시험·도구 없음 | 정직 witness 실패 | 일치 |
| `77e0f2db` | 0 | 없음 | 30회, main 입력 키 불일치 | 일치하는 시험·도구 없음 | 정직 witness 실패 | 일치 |
| `83cc0060` | 0 | 없음 | 239회, 잘못된 JSON 또는 main 입력 키 불일치 | 추적된 설치 산출물에 별도 규칙 필요 | 정직 witness 실패 | 일치 |
| `a8b2aa9c` | 70 | 없음 | 4회, main 입력 키 불일치 | 일치하는 시험·도구 없음 | 정직 witness 실패 | 일치 |
| `b5b5cf5d` | 12 | 없음 | 5회, main 입력 키 불일치 | 설치 뒤 같은 시험 실패 | 정직 witness 실패 | 일치 |
| `e71f158d` | 0 | 없음 | 36회, 잘못된 JSON 또는 main 입력 키 불일치 | 일치하는 시험·도구 없음 | 정직 witness 실패 | 일치 |

모든 10개 리비전에서 (a) zkbugs 항목은 사용 불가, (b) 대응 L 시리즈 입력은 없음으로 기록됐다. 표의 R1CS `일치`는 수집기에 저장된 컴파일 R1CS SHA-256과 B 퍼징 단위 R1CS SHA-256이 같고 `b_fuzz_r1cs_match=true`인 것을 뜻한다. `60271bae`는 수집 코드의 영 입력 생성 단계 `e_zero`가 선택됐으므로 엄격층 기준 입력이 전부 0이다. 해당 리비전은 B 요청이 없다.

**엄격층 본 결과: B 1묶음 기준 입력 0/107, 판정 불가.** index 단계의 최종 시범 요청 선택은 상태 파일에서 `RunnerError`로 실패했고, `validate-only`와 시범 단계는 실행되지 않았다. `index-plan`과 `index-finalize`에는 `state.json`이 없다. 최종 index SHA-256은 `9d53231056773c4f8ec967c413eaad48dec870bdf3689202474d753342edca06`, 생성·검증 스크립트 SHA-256은 `fa11eada786f20b1885e0b25df0d53a29f32df139c8b2fc4c9250dbc1465e7e1`다. 결과 재실행·S 재퍼징·B 판정은 하지 않았다.

## 3. A 보정 입력을 먼저 만든 방법 (B 생성 시작 전 기록)

A의 엄격 기준 입력이 이미 있는 S 요청 리비전 중 요청 수 상위 세 개를 메타데이터로 골랐다: `inference-original` 69건, `aq-036-6d7df64759b6` 27건, `inference-r-intdiv` 26건. 세 리비전 모두 엄격층에서 통과한 단계가 있는 쉬운 개발 세트에 속하므로, 이 보정은 B의 입력 구성 난도를 대표하지 않는다.

생성 방식은 리비전별 독립 Python 3 표준 라이브러리 스크립트, 고정 seed와 신호·배열 위치별 SHA-256 확장값, 키 순서 고정 JSON 직렬화다. 기존 A 엄격 기준 입력 파일 및 그 원천 경로를 생성 스크립트가 읽지 않는다. `Spend`는 잔액과 양의 출금액을 둔 보통 지출, 두 `IncentiveMechansim` 리비전은 `verified=1`인 256명 검증자의 양의 점수·증명 크기·응답 시간·경쟁 값을 둔 활성 계산을 흉내 냈다. 사용 상태를 끄거나 빈 배열·전부 0인 입력은 만들지 않는다. 서명·키·외부 패키지는 필요 없었다.

같은 seed로 각 생성기를 두 번 돌려 `input.json` SHA-256 동일성을 확인했다. 기존 엄격 입력과는 내용 열람 없이 SHA-256만 비교했고 세 개 모두 달랐다. 고정된 맥 검사 wrapper가 원본 main 컴파일 R1CS 해시, 정직 witness, Rust·snarkjs 원본 R1CS 만족을 확인해 세 개 모두 통과했다. 공개 출력은 전부 0이 아니었다. A에서 생성 방식의 수정은 없었다. B 생성은 이 기록 이후 같은 결정성·비퇴화·원본 검사·시도 기록 규칙으로 시작한다.

## 4. A 보정 입력과 실행 준비

A 공식 기준 입력 index v3의 `status=passed`와 `selected_stage` 메타데이터로 적격을 정하고, 공개된 A J 리비전별 S 요청 수 기록에서 많은 순으로 `inference-original` 69건, `aq-036-6d7df64759b6` 27건, `inference-r-intdiv` 26건을 골랐다. 엄격층은 앞의 두 inference가 (b) `b_l_series`, aq-036이 (a) `a_zkbugs`에서 정직 witness·Rust·snarkjs를 통과했다. 이 선택은 이미 엄격층 기준 입력이 있는 쉬운 성공 사례 쪽으로 편향되므로 B의 기준 입력 부재 리비전 성능을 대표하지 않는다. 기존 A 기준 입력 파일·그 원천 경로와 A 후보 값은 생성기가 읽지 않았다.

방법은 리비전별 독립 Python 표준 라이브러리 스크립트에 고정 seed를 주고 SHA-256 파생 정수로 재현 가능한 정상 입력을 만드는 것이다. inference의 256개 검증자 모두 `verified=1`로 켜고, 점수·경쟁·증명 크기·블록·ID를 0이 아닌 값으로 두며 응답 시간을 각 최소/최대 사이에 둔다. source는 `runs/n6-a1b-2026-10-08/units/inference-original/project/src/circuit.circom:12-33,59-67,140-164`, `src/responseTimeNormalized.circom:7-37`, `src/integerDivision.circom:13-31`이다. `inference-r-intdiv`는 같은 기능의 수리판 `runs/n6-a1b-2026-10-08/units/inference-r-intdiv/project/src/integerDivision.circom:25-34`를 쓴다. aq-036은 프로젝트의 비어 있지 않은 지출 예시(`runs/n6-a3-2026-10-08.noindex/pragma/aq-036-6d7df64759b6/project/circuits/spend.circom:19-51`)처럼 잔액보다 작은 양수를 인출하고 새 시험용 salt를 쓴다. 후보 값, 요청 행, 기존 기준 입력 파일·원천 경로, J 출력은 생성기에 쓰지 않았다. 생성 작업의 지시는 이번 N6-B6 사용자 지시서 3절·3-2절과 회로 소스의 입력 선언·예시뿐이다. 외부 패키지 설치·키·서명은 없으며 Mac에 도구를 새로 설치하지 않았다.

| A 리비전·S 요청 | 엄격 단계 | 생성기 SHA-256 | 구성 입력 SHA-256 | 기존 입력과 SHA 동일? | 2회 생성 동일? | 정직 witness/Rust/snarkjs | R1CS SHA 일치 | 공개 출력 전부 0? | 경과 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: |
| inference-original · 69 | b_l_series | `82bfbb3988eaa630ce43f2619ecf03def1b6d1e1eca5e695e6c2deebc419708d` | `6c08293bedd5e05599859aab948194ab16b5c37186ea81d4ce5f1633bbedaba5` | 아니오 | 예 | 3/3 통과 | 예 (`39022971e46a…`) | 아니오 | 22.51초 |
| aq-036-6d7df64759b6 · 27 | a_zkbugs | `871f1ee0526fb154adda517e774b34434ab9307a3634f69ca437847ec9469522` | `29a5e55d924c0f344d28b8134a53893da0d1a56c4f62f82289ccccd1c1c75dfb` | 아니오 | 예 | 3/3 통과 | 예 (`3230ec505391…`) | 아니오 | 20.72초 |
| inference-r-intdiv · 26 | b_l_series | `7b01d10bc535022f26271af823ba9a159cebd099bbe397942ccddf99b89e892b` | `f7c631f855bc0ae13e6fcc7abf692b80a57fc8eaf17abbdc01057d1e588deca8` | 아니오 | 예 | 3/3 통과 | 예 (`61b6b7c95817…`) | 아니오 | 31.22초 |

생성기는 각각 `scripts/n6_b6_construct_input_inference_original.py`, `scripts/n6_b6_construct_input_aq_036_6d7df64759b6.py`, `scripts/n6_b6_construct_input_inference_r_intdiv.py`; 입력·검사 기록은 `runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/constructed-inputs/<리비전>/` 아래에 새로 만들었다. 검사에는 공유 `scripts/n6_b6_check_constructed_input.py --scope A`를 써서 기존 `n6_b5_docker_base_inputs.py`가 import한 원래 컴파일·입력 키·witness·Rust·snarkjs 함수를 수정하지 않고 호출했다. A R1CS 근거는 공식 index v3 SHA-256 `18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508`이다. `/Volumes/zkfdo-jcache`의 mount 여부를 확인한 뒤 새 `/Volumes/zkfdo-jcache/n6-b6-acal/constructed/` 캐시를 썼다. 2시간/리비전 상한 이내다. 첫 aq-036 호출은 샌드박스가 외장 mount의 새 폴더 쓰기를 거부해 검사 시작 전에 끝났고, 허용된 경로 쓰기 권한으로 재호출해 위 결과를 얻었다. 이 환경 오류는 입력 실패로 세지 않았다.

세 구성 입력 모두 기존 엄격 입력 SHA와 달라 A 보정 비교 대상 3개다. A 보정 J는 아직 실행하지 않았다. v2.2 보존 바이너리는 `runs/n6-j4c-2026-10-17.noindex/zkfDO-v2.2`, 고정 SHA-256은 `c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835`이다. 설정은 `docs/n6_j4b_engine_v2_settings_v2_2026-10-17.json` SHA-256 `a4867e018a54df656dc1bdd079d7bb4fb6862a984b6e88784e5b30176e5da001`와 고정 기록 `docs/n6_j4_freeze_v2_2_2026-10-17.md`를 확인했다. 재실행은 같은 122개 S 요청을 구성/실제 입력 각각 한 번씩 같은 조건으로 처리하며, 캐시는 `/Volumes/zkfdo-jcache/n6-b6-acal/constructed-j`와 `/Volumes/zkfdo-jcache/n6-b6-acal/strict-j`, 인스턴스 저장소는 각 새 결과 폴더에 분리한다. 결과는 `runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/`에 두되 J 실행 전에 index·실행기 검증과 엄격 입력 SHA 재확인이 필요하다. 집계는 요청별 L1/배제/unknown 3×3 표 두 개(실제 재실행 대 구성, 기존 v2.2 대 실제 재실행), 일치율, 구성 쪽 L1·배제 획득/손실 수, 리비전별 주입 버그 확인 여부로 미리 고정한다. A 비교는 탐색층 해석에만 쓰며 B 판정 관문으로 쓰지 않는다.

**지시와 다른 점:** A 식별자 `inference-original`과 `inference-r-intdiv`는 모두 첫 8자가 `inferenc`라 8자 파일명이 충돌한다. 생성기는 전체 구분되는 식별자로 이름 붙였다. aq-036의 첫 외장 캐시 호출은 쓰기 권한 거부로 새 기록을 남기기 전 종료했다.

### A 보정 J 실행 준비 완료, 실행은 안 함

`scripts/n6_b6_a_calibration.py` SHA-256 `c219b4f54b72503f69b6f98e6d2ba01c4d3c66d376df04cb5a8edd16a4028703`는 공식 A 요청 index의 같은 122개 S 요청을 골라 후보 문서의 기준 입력 경로만 새 입력으로 바인딩한 구성 index와 원래 기준 입력을 쓰는 엄격 index를 새로 만들었다. 후보 필드 값은 화면이나 보고서에 출력하지 않았다. 두 index 모두 고정 v2.2 바이너리와 검증된 원본 소스/inventory를 가리킨다. 기존 J 실행기의 `validate_index`를 양쪽에 적용해 통과했다. 출력과 인스턴스 저장소는 `a-calibration.noindex/constructed-j`와 `strict-j`로 분리하고, 실행 시 외장 캐시도 `/Volumes/zkfdo-jcache/n6-b6-acal/constructed-j`, `strict-j`로 새로 만든다. 두 팔의 실제 J는 시작하지 않았으며 실행 통합 상태 경로는 `a-calibration.noindex/state.json`으로 정했다.

- 준비 계획 `runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/prepared/plan.json` SHA-256 `15ea1bf9f812e4d6192ffe2b2103d3cdc097284c8d674dc29b718c0a54d28092`.
- 구성 요청 index SHA-256 `ebf7fa598fc1ddb4fd9f8e42e7376ab5e99429ccc4ff110c3b83df72151c5fe5`; 엄격 재실행 요청 index SHA-256 `c8f8f1aa9b12a953b78685bafda49d7afe02edf2b0c2c27016dd2d71eee0f362`.
- 합성 Python 단위 검사 `tests/n6_b6_a_calibration_test.py` 2/2 통과; 생성기 및 실행기 Python 구문 검사 통과. `prepare`가 두 index를 기존 J 실행기 `validate_index`로 확인했다.
- A 보정용 키티 한 줄은 S 재퍼징 종료 뒤에만 붙인다: `cd /Users/miiz/Desktop/kwzzzz_zkfr && python3 scripts/n6_b6_a_calibration.py --action execute && python3 scripts/n6_b6_a_calibration.py --action aggregate`.

집계 함수는 실행 전에 3×3 행렬의 행/열 방향을 **엄격 재실행→구성**, **기존 v2.2→엄격 재실행**으로 고정했다. L1은 자기 `entrypoint_violation` 또는 조인된 실효 `assumption_violation_reachable`, 배제는 완료·비L1·자기 판정 존재·자기/실효 unknown 없음이며, 나머지는 unknown으로 둔다. 두 일치율과 엄격 재실행 대비 구성 입력에서 L1·배제가 잃고 얻은 건수를 기록한다. aq-036의 알려진 `spend_missing_range_check`에 대해서는 구성 L1 요청 수와 별도로 동일 원인 수동 확인 대기를 표시하며, inference 개발 리비전 둘은 주입 버그 항목이 아니다. 이 비교는 B 관문이 아니다.

### A 준비 코드 안전 보정 (B 생성 시작 뒤, 입력 값 생성 방식 불변)

기존 출력 덮어쓰기 가능성을 없애려고 A 생성기 세 개의 출력 생성만 배타 생성으로 바꿨다. 새 임시 경로 두 곳에서 같은 seed의 input.json SHA-256이 이미 고정한 각 입력과 동일했고, 같은 경로 재호출은 모두 거부됐다. 생성값·입력 해시는 바뀌지 않았다. 최종 생성기 SHA-256은 `inference-original` `b3d62cfd008c477d15345e8b1514b45373bc195d7f0e5042c6cf5aa2c493436f`, `aq-036-6d7df64759b6` `20f2f3192b4ddb194ab8b0e10a6da77a8712b001c36fde569fe209b90008cfb7`, `inference-r-intdiv` `f11492c11f15a7cb6d396652626e0578b776af07e3d018286728a9dcf736c74e`다. 위 A 표의 이전 생성기 SHA 대신 이 값을 쓴다.

A 보정 실행기는 B 탐색층 pilot/full 상태가 `running`일 때 J를 차단한다. 최종 `scripts/n6_b6_a_calibration.py` SHA-256은 `a5943af9ac71369fd41733ba88df4027f2d56bb670f56a09352e3b8a48c148cc`다. 위 초기 실행기 SHA 대신 이 값을 쓴다. 합성 Python 검사 5/5, 구문 검사, 준비된 두 index의 `validate-only`가 통과했다.

보정 비교의 3분류는 세 팔에 동일하게 적용한다. L1 외의 `excluded`는 모든 클래스에 자기 `excluded_in_context` 또는 실효 `assumption_excluded_in_context` 증거가 있을 때만 센다. `assumption_input_reachable`와 `compatible_no_top_violation_observed`를 포함한 그 밖의 비L1은 unknown으로 둔다. 이는 집계만의 사전 보정이며 J 판정 규칙과 기존 A 결과를 바꾸지 않는다. 위 §4 마지막 문단의 더 느슨한 배제 문장은 이 정의로 대체한다.

## 탐색층 1묶음 실행 준비

새 실행기 `scripts/n6_b6_batch1x_prepare.py`는 `constructed-inputs/index.json`의 `layer=constructed`와 10개 리비전·입력 SHA-256을 확인한 뒤 기존 B 요청 생성기·adapter·format-only pilot을 그대로 사용한다. 새 출력은 `runs/n6-b6-2026-10-18.noindex/batch1x-prep.noindex`, J 캐시는 mount 확인된 `/Volumes/zkfdo-jcache/n6-b6-batch1x`다. N5 개정 SHA-256 `751c305aacd5fb63683551efcb8b867597ddc95739e8ab9eac0cc08d18fabb72`, 고정 v1·v2.2 엔진과 circom, mem20 완료 상태를 preflight에서 확인한다. 실제 B index 생성·validate-only·시범·전체 J는 이 작업에서 실행하지 않았다.

`--action pilot`은 새 107행 요청 계획·v1 index·v2.2 overlay를 만들고 두 엔진의 validate-only를 실행한다. 이후 `lead-input-review.json`을 요구해 review-table.md SHA-256, 승인된 8자 리비전 prefix의 유일 대응, 표의 input.json SHA-256과 constructed index 및 실제 파일 SHA-256을 확인한다. 승인되지 않은 구성 입력이 callable이면 J 호출 전에 멈춘다. 승인이 맞을 때만 제약 수 최대·최소 S 요청 두 ID를 `pilot-selection.json`에 미리 기록하고, v2.2→v1 format-only 시범을 실행한다. `--action execute-all`은 두 시범의 통과 상태와 승인·입력 SHA를 재검증한 뒤 v2.2→v1 전체 J를 실행한다. 두 엔진이 완료되기 전에는 판정 값을 출력하지 않는다. 리드 검토 기록 파일은 준비 단계에서 만들지 않았다.

키티용 후속 명령은 S 재퍼징이 끝난 뒤 다음 순서로 사용한다.

```sh
python3 scripts/n6_b6_batch1x_prepare.py --action pilot
python3 scripts/n6_b6_batch1x_prepare.py --action execute-all
```

새 실행기 SHA-256: `756c80e5b633f349a927c41dd2ea5ba6384e2f0775acd2fed1dc68806696cd74`.

합성 임시 폴더의 가짜 검토 기록·표·입력·시범 산출물만 사용한 관문 검사 `python3 -m unittest discover -s tests -p n6_b6_batch1x_prepare_test.py -v`: 5건 통과. 누락된 검토 기록, 표 SHA 변경, 입력 파일 SHA 변경, callable 미승인 리비전을 거부했다. S의 실제 종료 상태 `start_gate_failed`·`disk_guard`는 허용하고 `running`은 거부했다. 시범 결과 파일과 결합 인스턴스 파일의 SHA 변조도 각각 거부했다. `execute-all`은 두 시범의 산출물 SHA를 다시 확인한다. 테스트 파일 SHA-256: `ef2184807887401d08026f243ab57c28b6d18b7efde22d8b5bbdf17beb69f2ac`.

기존 B5 준비 실행기와 다른 점: 기준 입력 수집·entrypoint 재분류를 반복하지 않고 constructed index를 사용한다. N5 개정·캐시 mount·리드 승인 관문을 추가한다. 원본 B5 준비 실행기, B 요청 생성기, 판정 엔진·실행기 판정 규칙은 변경하지 않았다.

### A 보정 준비 최종 코드 고정

A 보정 집계의 방법과 요청별 3분류 기록을 실행 전에 새 `runs/n6-b6-2026-10-18.noindex/a-calibration.noindex/prepared/comparison-method-v2.json`에 고정했다(SHA-256 `8889bd92adb973897a8821d4a1e70166201b5e3b7b38c9a76357eb1315c1b536`). 최종 A 실행기 SHA-256은 `b6e38733486cd9ae3ac33cdca4e51338c0b37d01131f163def1209ed0d7bb17a`이며 앞의 `c219...`·`a594...` 실행기 해시를 대체한다. 이 보정은 집계 방법과 실행 겹침 방지에만 적용했고 J 판정 엔진·A 구성 입력 값·준비된 두 요청 index는 바꾸지 않았다. 최종 생성기 SHA-256은 앞 절의 `b3d62c...`, `20f2f3...`, `f11492...`이고, 첫 A 표의 초기 생성기 해시를 대체한다. Python 단위 검사 5/5, 구문 검사, 122개 요청의 두 `validate-only` 검사가 통과했으며 A J는 실행하지 않았다.

## 5. B 요청 포함 첫 5개 구성 입력 리드 검토표

`review-table.md` SHA-256 `699fcd89f0d8791fbf75c7522eaf1ea16e1e3a993167cb8a53203758ced2aff2`. 다음은 파일 전문이다.

# 탐색층 구성 B 입력: 첫 5개 리드 검토표

이 표는 지정 순서의 B 요청 포함 리비전 다섯 개에 대한 구성 입력만 기록한다. SHA-256은 최종 `input.json`의 바이트 기준이다. 각 행의 근거·시도 시간·검사 인자 차이는 해당 리비전의 `notes.md`와 `attempts.jsonl`에 있다. B 후보 값·요청 행·판정 결과는 열람하지 않았다.

| revision | project | 모사 입력 | 생성 스크립트 SHA-256 | input.json SHA-256 | 스위치류 입력 값 | 공개 출력 전부 0 | 예시 형태 일치·근거 | 정직 witness | Rust | snarkjs | R1CS SHA-256 일치 | 소요 시간(초) | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6079a717 | anon-aadhaar | 새 RSA 시험 키로 서명한 Aadhaar V2 QR | 4a1d6a3b951c3246a58d9d81eb9e72ebe55e55fd5289dde45d14a56f42ec7b35 | 5fb88bdcde81ccd2e5f2b4ed8195e0e0735f34e88299ff9a7c5067b6f18c16f3 | revealAgeAbove18=1, revealGender=1, revealPinCode=1, revealState=1 | 아니오(7개 출력) | 기록 저장소 `aadhaar-verifier.test.ts`의 QR 형태와 `aadhaar-qr-verifier.circom`의 reveal 경로; [notes](6079a717/notes.md) | 통과 | 통과 | 통과 | 예 | 61.981 | 없음 |
| b5b5cf5d | iden3 | 유효한 credential MTP·비철회·EQ 질의 | 87c3ad096d0476936b2d7786bd10dc5677e0ce7310088da86cdfb1e9071882b1 | b7cbca1dca861e7e7a28b6acd06d82fe12197fea091965417142dae74b98fab7 | proofType=2, isRevocationChecked=1, 만료 claim 켬, operator=1 | 아니오(6개 출력) | 기록 저장소 `credentialAtomicQueryV3OffChain.circom`과 `testvectorgen/credentials/v3/v3_test.go`; [notes](b5b5cf5d/notes.md) | 통과 | 통과 | 통과 | 예 | 22.011 | 없음 |
| 340107e1 | Vota-Circuits | 세 참여자의 첫 MACI 투표 집계 배치 | 37c28a21e4b8921168daaef81a182e4eaa3b1bb4871502166cc236b2fe3fa94b | ae1bd7e5d5ad0c8a785ab2ab519f775779874027c8c7e740c20483b36813435f | numSignUps=3, batchNum=0, 비영 투표 3개; 비활성화 스위치 없음 | 해당 없음(공개 출력 0개; 공개 inputHash 비영) | 기록 저장소 `tallyVotes.circom`과 quintary tree/hash 회로; [notes](340107e1/notes.md) | 통과 | 통과 | 통과 | 예 | 166.436 | 없음 |
| 4c221df7 | panther-core | 새 키·KYC 서명·Merkle 경로의 zAccount 갱신 | b0a27e63583643635cfae654626f98c3a4d2bcb201f1117a3b684dd07abf0139 | e4cec6996f56b2c8453664d29d6a5dbb1b88c206ae2b6d60158685682d436c2b | zZoneSealing=1, KYC·forest·salt 검증 관문 켬 | 해당 없음(공개 출력 0개; 공개 입력 비영) | 기록 저장소 `ZAccountRenewalNonZeroInputWitnessGeneration.test.ts`의 갱신 구조와 `zAccountRenewalV1.circom` 검증식; [notes](4c221df7/notes.md) | 통과 | 통과 | 통과 | 예 | 24.191 | 없음 |
| a8b2aa9c | passport-zk-circuits | 새 2048비트 RSA e=3 PSS/SHA-256 서명 | ac53d296be778e03a1f02ab893e09795516242c932a144a3ba0d78c83b27277e | 20181097b0c2cfab1204476fa68230bc9e8f6b49c5c0d030852f729575678190 | 검증 경로 항상 활성; 비활성화 스위치 없음 | 해당 없음(공개 출력 0개) | 기록 저장소 `m.circom`과 `rsaPss.circom`의 limb·salt·MGF1 구조; [notes](a8b2aa9c/notes.md) | 통과 | 통과 | 통과 | 예 | 59.801 | 없음 |


## 6. 최종 리드 검토표

§5의 표에는 행 위치를 뒤에 덧붙이기 전 해시가 들어 있다. 검토에 사용할 최종 `review-table.md` SHA-256은 `ac7d444367e6ec85ada9bf513e68efbded16fb33d43e88691ead80c9e061ff99`이다. 다음은 최종 파일 전문이다.

# 탐색층 구성 B 입력: 첫 5개 리드 검토표

이 표는 지정 순서의 B 요청 포함 리비전 다섯 개에 대한 구성 입력만 기록한다. SHA-256은 최종 `input.json`의 바이트 기준이다. 각 행의 근거·시도 시간·검사 인자 차이는 해당 리비전의 `notes.md`와 `attempts.jsonl`에 있다. B 후보 값·요청 행·판정 결과는 열람하지 않았다.

| revision | project | 모사 입력 | 생성 스크립트 SHA-256 | input.json SHA-256 | 스위치류 입력 값 | 공개 출력 전부 0 | 예시 형태 일치·근거 | 정직 witness | Rust | snarkjs | R1CS SHA-256 일치 | 소요 시간(초) | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6079a717 | anon-aadhaar | 새 RSA 시험 키로 서명한 Aadhaar V2 QR | 4a1d6a3b951c3246a58d9d81eb9e72ebe55e55fd5289dde45d14a56f42ec7b35 | 5fb88bdcde81ccd2e5f2b4ed8195e0e0735f34e88299ff9a7c5067b6f18c16f3 | revealAgeAbove18=1, revealGender=1, revealPinCode=1, revealState=1 | 아니오(7개 출력) | 기록 저장소 `aadhaar-verifier.test.ts`의 QR 형태와 `aadhaar-qr-verifier.circom`의 reveal 경로; [notes](6079a717/notes.md) | 통과 | 통과 | 통과 | 예 | 61.981 | 없음 |
| b5b5cf5d | iden3 | 유효한 credential MTP·비철회·EQ 질의 | 87c3ad096d0476936b2d7786bd10dc5677e0ce7310088da86cdfb1e9071882b1 | b7cbca1dca861e7e7a28b6acd06d82fe12197fea091965417142dae74b98fab7 | proofType=2, isRevocationChecked=1, 만료 claim 켬, operator=1 | 아니오(6개 출력) | 기록 저장소 `credentialAtomicQueryV3OffChain.circom`과 `testvectorgen/credentials/v3/v3_test.go`; [notes](b5b5cf5d/notes.md) | 통과 | 통과 | 통과 | 예 | 22.011 | 없음 |
| 340107e1 | Vota-Circuits | 세 참여자의 첫 MACI 투표 집계 배치 | 37c28a21e4b8921168daaef81a182e4eaa3b1bb4871502166cc236b2fe3fa94b | ae1bd7e5d5ad0c8a785ab2ab519f775779874027c8c7e740c20483b36813435f | numSignUps=3, batchNum=0, 비영 투표 3개; 비활성화 스위치 없음 | 해당 없음(공개 출력 0개; 공개 inputHash 비영) | 기록 저장소 `tallyVotes.circom`과 quintary tree/hash 회로; [notes](340107e1/notes.md) | 통과 | 통과 | 통과 | 예 | 166.436 | 없음 |
| 4c221df7 | panther-core | 새 키·KYC 서명·Merkle 경로의 zAccount 갱신 | b0a27e63583643635cfae654626f98c3a4d2bcb201f1117a3b684dd07abf0139 | e4cec6996f56b2c8453664d29d6a5dbb1b88c206ae2b6d60158685682d436c2b | zZoneSealing=1, KYC·forest·salt 검증 관문 켬 | 해당 없음(공개 출력 0개; 공개 입력 비영) | 기록 저장소 `ZAccountRenewalNonZeroInputWitnessGeneration.test.ts`의 갱신 구조와 `zAccountRenewalV1.circom` 검증식; [notes](4c221df7/notes.md) | 통과 | 통과 | 통과 | 예 | 24.191 | 없음 |
| a8b2aa9c | passport-zk-circuits | 새 2048비트 RSA e=3 PSS/SHA-256 서명 | ac53d296be778e03a1f02ab893e09795516242c932a144a3ba0d78c83b27277e | 20181097b0c2cfab1204476fa68230bc9e8f6b49c5c0d030852f729575678190 | 검증 경로 항상 활성; 비활성화 스위치 없음 | 해당 없음(공개 출력 0개) | 기록 저장소 `m.circom`과 `rsaPss.circom`의 limb·salt·MGF1 구조; [notes](a8b2aa9c/notes.md) | 통과 | 통과 | 통과 | 예 | 59.801 | 없음 |

## 근거 행 위치

- `6079a717`: `runs/e01-setup-2026-10-03/recovery-v2/repositories/anon-aadhaar__anon-aadhaar/clone/packages/circuits/test/aadhaar-verifier.test.ts:43-94`(QR 입력 형태), `runs/e01-setup-2026-10-03/recovery-v2/repositories/anon-aadhaar__anon-aadhaar/clone/packages/circuits/src/aadhaar-qr-verifier.circom:57-100`(서명·reveal 검증).
- `b5b5cf5d`: `runs/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone/testvectorgen/credentials/v3/v3_test.go:429-459`(MTP), `runs/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone/circuits/offchain/credentialAtomicQueryV3OffChain.circom:16-99`(입력 형태).
- `340107e1`: `runs/c03-corpus-2026-10-02/recovery-v3/repositories/DoraFactory__Vota-Circuits/clone/circuits/maci/power/tallyVotes.circom:15-60`(배치·입력), 같은 파일 `:63-168`(상태·투표·결과 검증).
- `4c221df7`: `runs/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone/circuits/test/ZAccountRenewalNonZeroInputWitnessGeneration.test.ts:222-493`(정상 시나리오), `runs/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone/circuits/circuits/zAccountRenewalV1.circom:248-369`(갱신 commitment·nullifier), 같은 파일 `:415-555`(KYC·Merkle·salt).
- `a8b2aa9c`: `runs/c03-corpus-2026-10-02/recovery-v3/repositories/rarimo__passport-zk-circuits/clone/circuits/lib/circuits/signatures/m.circom:11`(정확한 main 인자), `runs/c03-corpus-2026-10-02/recovery-v3/repositories/rarimo__passport-zk-circuits/clone/circuits/lib/circuits/signatures/rsaPss.circom:18-28`(입력), 같은 파일 `:39-217`(PSS 검증).


## 7. Docker 생성 보정 뒤 첫 5개 최종 검토표

§6의 원본 표 4,896바이트/SHA-256 `ac7d444367e6ec85ada9bf513e68efbded16fb33d43e88691ead80c9e061ff99`를 보존했다. npm 자료 의존 생성 세 건을 Docker에서 다시 만든 뒤 같은 파일에 정정본 다섯 행을 덧붙였다. 리드가 검토할 전체 `review-table.md`의 최종 SHA-256은 `f5876f698b5952155b00d2461cd4e81c48892318edcc4f35cc4079e0388ef22d`이다. 다음은 최종 파일 전문이다.

# 탐색층 구성 B 입력: 첫 5개 리드 검토표

이 표는 지정 순서의 B 요청 포함 리비전 다섯 개에 대한 구성 입력만 기록한다. SHA-256은 최종 `input.json`의 바이트 기준이다. 각 행의 근거·시도 시간·검사 인자 차이는 해당 리비전의 `notes.md`와 `attempts.jsonl`에 있다. B 후보 값·요청 행·판정 결과는 열람하지 않았다.

| revision | project | 모사 입력 | 생성 스크립트 SHA-256 | input.json SHA-256 | 스위치류 입력 값 | 공개 출력 전부 0 | 예시 형태 일치·근거 | 정직 witness | Rust | snarkjs | R1CS SHA-256 일치 | 소요 시간(초) | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6079a717 | anon-aadhaar | 새 RSA 시험 키로 서명한 Aadhaar V2 QR | 4a1d6a3b951c3246a58d9d81eb9e72ebe55e55fd5289dde45d14a56f42ec7b35 | 5fb88bdcde81ccd2e5f2b4ed8195e0e0735f34e88299ff9a7c5067b6f18c16f3 | revealAgeAbove18=1, revealGender=1, revealPinCode=1, revealState=1 | 아니오(7개 출력) | 기록 저장소 `aadhaar-verifier.test.ts`의 QR 형태와 `aadhaar-qr-verifier.circom`의 reveal 경로; [notes](6079a717/notes.md) | 통과 | 통과 | 통과 | 예 | 61.981 | 없음 |
| b5b5cf5d | iden3 | 유효한 credential MTP·비철회·EQ 질의 | 87c3ad096d0476936b2d7786bd10dc5677e0ce7310088da86cdfb1e9071882b1 | b7cbca1dca861e7e7a28b6acd06d82fe12197fea091965417142dae74b98fab7 | proofType=2, isRevocationChecked=1, 만료 claim 켬, operator=1 | 아니오(6개 출력) | 기록 저장소 `credentialAtomicQueryV3OffChain.circom`과 `testvectorgen/credentials/v3/v3_test.go`; [notes](b5b5cf5d/notes.md) | 통과 | 통과 | 통과 | 예 | 22.011 | 없음 |
| 340107e1 | Vota-Circuits | 세 참여자의 첫 MACI 투표 집계 배치 | 37c28a21e4b8921168daaef81a182e4eaa3b1bb4871502166cc236b2fe3fa94b | ae1bd7e5d5ad0c8a785ab2ab519f775779874027c8c7e740c20483b36813435f | numSignUps=3, batchNum=0, 비영 투표 3개; 비활성화 스위치 없음 | 해당 없음(공개 출력 0개; 공개 inputHash 비영) | 기록 저장소 `tallyVotes.circom`과 quintary tree/hash 회로; [notes](340107e1/notes.md) | 통과 | 통과 | 통과 | 예 | 166.436 | 없음 |
| 4c221df7 | panther-core | 새 키·KYC 서명·Merkle 경로의 zAccount 갱신 | b0a27e63583643635cfae654626f98c3a4d2bcb201f1117a3b684dd07abf0139 | e4cec6996f56b2c8453664d29d6a5dbb1b88c206ae2b6d60158685682d436c2b | zZoneSealing=1, KYC·forest·salt 검증 관문 켬 | 해당 없음(공개 출력 0개; 공개 입력 비영) | 기록 저장소 `ZAccountRenewalNonZeroInputWitnessGeneration.test.ts`의 갱신 구조와 `zAccountRenewalV1.circom` 검증식; [notes](4c221df7/notes.md) | 통과 | 통과 | 통과 | 예 | 24.191 | 없음 |
| a8b2aa9c | passport-zk-circuits | 새 2048비트 RSA e=3 PSS/SHA-256 서명 | ac53d296be778e03a1f02ab893e09795516242c932a144a3ba0d78c83b27277e | 20181097b0c2cfab1204476fa68230bc9e8f6b49c5c0d030852f729575678190 | 검증 경로 항상 활성; 비활성화 스위치 없음 | 해당 없음(공개 출력 0개) | 기록 저장소 `m.circom`과 `rsaPss.circom`의 limb·salt·MGF1 구조; [notes](a8b2aa9c/notes.md) | 통과 | 통과 | 통과 | 예 | 59.801 | 없음 |

## 근거 행 위치

- `6079a717`: `runs/e01-setup-2026-10-03/recovery-v2/repositories/anon-aadhaar__anon-aadhaar/clone/packages/circuits/test/aadhaar-verifier.test.ts:43-94`(QR 입력 형태), `runs/e01-setup-2026-10-03/recovery-v2/repositories/anon-aadhaar__anon-aadhaar/clone/packages/circuits/src/aadhaar-qr-verifier.circom:57-100`(서명·reveal 검증).
- `b5b5cf5d`: `runs/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone/testvectorgen/credentials/v3/v3_test.go:429-459`(MTP), `runs/c03-corpus-2026-10-02/recovery-v3/repositories/iden3__circuits/clone/circuits/offchain/credentialAtomicQueryV3OffChain.circom:16-99`(입력 형태).
- `340107e1`: `runs/c03-corpus-2026-10-02/recovery-v3/repositories/DoraFactory__Vota-Circuits/clone/circuits/maci/power/tallyVotes.circom:15-60`(배치·입력), 같은 파일 `:63-168`(상태·투표·결과 검증).
- `4c221df7`: `runs/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone/circuits/test/ZAccountRenewalNonZeroInputWitnessGeneration.test.ts:222-493`(정상 시나리오), `runs/c03-corpus-2026-10-02/recovery-v3/repositories/pantherfoundation__panther-core/clone/circuits/circuits/zAccountRenewalV1.circom:248-369`(갱신 commitment·nullifier), 같은 파일 `:415-555`(KYC·Merkle·salt).
- `a8b2aa9c`: `runs/c03-corpus-2026-10-02/recovery-v3/repositories/rarimo__passport-zk-circuits/clone/circuits/lib/circuits/signatures/m.circom:11`(정확한 main 인자), `runs/c03-corpus-2026-10-02/recovery-v3/repositories/rarimo__passport-zk-circuits/clone/circuits/lib/circuits/signatures/rsaPss.circom:18-28`(입력), 같은 파일 `:39-217`(PSS 검증).

## 정정본

원본 검토표는 4896바이트, SHA-256 `ac7d444367e6ec85ada9bf513e68efbded16fb33d43e88691ead80c9e061ff99`로 위에 그대로 보존했다. b5b5cf5d, 340107e1, 4c221df7의 최초 생성은 npm 패키지 데이터·실행에 의존하면서 Mac에서 수행되어 지시서 §3의 Docker `.mjs`/`--network none` 조건을 엄격하게 충족하지 않았다. 세 리비전은 고정 digest Docker에서 독립 2회 다시 생성하고 새 `docker-final/input.json`을 원본 검사로 재확인했다. 생성 입력 SHA는 최초와 같지만 최종 생성기 SHA와 검사 시간은 아래 표를 따른다. 6079a717과 a8b2aa9c는 Python 표준 라이브러리만 썼으며 Docker 생성이 없다. 근거의 전체 경로와 행은 위의 `근거 행 위치` 절 및 각 notes.md에 있다.

| revision | project | 모사 입력 | 생성 스크립트 SHA-256 | input.json SHA-256 | 스위치류 입력 값 | 공개 출력 전부 0 | 예시 형태 일치·근거 | 정직 witness | Rust | snarkjs | R1CS SHA-256 일치 | 소요 시간(초) | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6079a717 | anon-aadhaar | 새 RSA 시험 키로 서명한 Aadhaar V2 QR | 4a1d6a3b951c3246a58d9d81eb9e72ebe55e55fd5289dde45d14a56f42ec7b35 | 5fb88bdcde81ccd2e5f2b4ed8195e0e0735f34e88299ff9a7c5067b6f18c16f3 | revealAgeAbove18=1, revealGender=1, revealPinCode=1, revealState=1 | 아니오(7개 출력) | 기록 저장소 `aadhaar-verifier.test.ts`의 QR 형태와 `aadhaar-qr-verifier.circom`의 reveal 경로; [notes](6079a717/notes.md) | 통과 | 통과 | 통과 | 예 | 61.981 | 없음 |
| b5b5cf5d | iden3 | 유효한 credential MTP·비철회·EQ 질의 | 4b95d574129511ba4176dc73542d3c24aa7b72ed681b740d5a99341927aa35d3 | b7cbca1dca861e7e7a28b6acd06d82fe12197fea091965417142dae74b98fab7 | proofType=2, isRevocationChecked=1, 만료 claim 켬, operator=1 | 아니오(6개 출력) | 기록 저장소 `credentialAtomicQueryV3OffChain.circom:16-99; v3_test.go:429-459`; Docker `--network none` 보정·새 검사; [notes](b5b5cf5d/notes.md) | 통과 | 통과 | 통과 | 예 | 4.334 | 없음 |
| 340107e1 | Vota-Circuits | 세 참여자의 첫 MACI 투표 집계 배치 | bcb4a27423cbe4264d6960ec36d9326c64a6cdfbb6400f67e633e5e5a23eb6ac | ae1bd7e5d5ad0c8a785ab2ab519f775779874027c8c7e740c20483b36813435f | numSignUps=3, batchNum=0, 비영 투표 3개; 비활성화 스위치 없음 | 해당 없음(공개 출력 0개; 공개 inputHash 비영) | 기록 저장소 `tallyVotes.circom:15-168`; Docker `--network none` 보정·새 검사; [notes](340107e1/notes.md) | 통과 | 통과 | 통과 | 예 | 145.941 | 없음 |
| 4c221df7 | panther-core | 새 키·KYC 서명·Merkle 경로의 zAccount 갱신 | 33a73718402bb78c3c21122bdcee7fb1418e91f2f3219fbae4353c0b015fe4fe | e4cec6996f56b2c8453664d29d6a5dbb1b88c206ae2b6d60158685682d436c2b | zZoneSealing=1, KYC·forest·salt 검증 관문 켬 | 해당 없음(공개 출력 0개; 공개 입력 비영) | 기록 저장소 `ZAccountRenewalNonZeroInputWitnessGeneration.test.ts:222-493; zAccountRenewalV1.circom:248-555`; Docker `--network none` 보정·새 검사; [notes](4c221df7/notes.md) | 통과 | 통과 | 통과 | 예 | 6.485 | 없음 |
| a8b2aa9c | passport-zk-circuits | 새 2048비트 RSA e=3 PSS/SHA-256 서명 | ac53d296be778e03a1f02ab893e09795516242c932a144a3ba0d78c83b27277e | 20181097b0c2cfab1204476fa68230bc9e8f6b49c5c0d030852f729575678190 | 검증 경로 항상 활성; 비활성화 스위치 없음 | 해당 없음(공개 출력 0개) | 기록 저장소 `m.circom`과 `rsaPss.circom`의 limb·salt·MGF1 구조; [notes](a8b2aa9c/notes.md) | 통과 | 통과 | 통과 | 예 | 59.801 | 없음 |


## 8. 요청 없는 후속 4개 최종 검토표

기존 `review-table-2.md` 6,945바이트/SHA-256 `af277cd83a415b539007c966be6ca6a2987ba9997d58470e91a517e812b89918`를 보존하고, 77e0f2db의 두 개수 모두 양수인 새 입력을 반영한 정정본 네 행을 덧붙였다. 리드가 검토할 전체 파일 SHA-256은 `b7d1a1f8e7a434f28b7612257001c18582e40deb23dc69cd3b7dacdba29abfb1`이다. 다음은 최종 파일 전문이다.

# N6-B6 후속 4개 구성 입력 검토표

후보 값·B 요청 행·J 출력은 열지 않았다. 표의 SHA-256과 시간은 각 리비전의 최종 입력 및 최종 원본 검사 기록 기준이다. `공개 출력 전부 0`의 `해당 없음`은 공개 출력 wire가 0개라는 뜻이다. 생성 시도의 상세 기록과 이미지 증거는 각 리비전의 `attempts.jsonl`, 방법 설명은 `notes.md`에 있다.

| revision | project | 모사 입력 | 생성 스크립트 SHA-256 | input.json SHA-256 | 스위치류 입력 값 | 공개 출력 전부 0 | 예시 형태 일치·근거 | 정직 witness | Rust | snarkjs | R1CS SHA-256 일치 | 소요 시간(초) | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| 76053f7f | Zellic zkerc20 | Split(30,8): 양수 note 8개, 동일 30층 root의 실제 포함 경로, 양수 출력 2개 | `aa8bd04a55438f5719f9f89d5ddcc58d7f6c3b647fc567965668920e134f1474` | `6310b2188d52edf4da33615b01d4cab696271ac5d62af9717dc586696d414dc5` | note 금액 8/8 양수, salt 8/8 비영, sender 소유, Merkle 검증 활성 | 해당 없음 (0개) | 예. 회로의 Split·commitment·Merkle 규칙과 저장소 Merkle 구현; 아래 근거 1 | 통과 | 통과 | 통과 | 예 | 9.837835 | 최초 Mac Node `.js` 생성은 npm 의존 Docker 조건과 달라 원본을 보존하고 Docker `.mjs` 두 번 재생성·재검사. 첫 캐시 권한 실패는 검사 시작 전 종료. 최종 검사 실패 없음 |
| 77e0f2db | Pragma private liquidity | 커밋 시험 벡터의 한쪽 token0 note를 쓰는 `LIQ_ADD` | `c91e54405a15cf21b25ddd5d28c4910b0f852dbef9197164a7384f887b1c16da` | `c5ebc90ff93101fa80964a65603aab0d125a4645a35d5086c5bac5f44ad5998e` | `LIQ_ADD`, `token0_note_count=1`, `token1_note_count=0`, `liquidity_delta=1`, 활성 note 금액 양수 | 해당 없음 (0개) | 예. 커밋된 `add_liquidity_in_range.json`와 회로·테스트; 아래 근거 2 | 통과 | 통과 | 통과 | 예 | 8.371277 | 첫 inactive slot secret 변형은 정직 witness 실패; 실패 파일 보존. 커밋 시험 벡터 진단 통과 후 최종 경로에 생성·검사 통과 |
| 83cc0060 | Self KYC disclosure | 295바이트 KYC 공개, 실제 credential 포함 경로와 OFAC SMT 증명 2개 | `5140c986e167cd430470f0b677a9c272950508aaeb4a764bf47004992702bc2d` | `25c25eae81db743f82281263bd3b8bbff2c0384fa45d2ff569d24fea62f22e` | `selector_ofac=1`, disclosure 295비트 전부 켬, `leaf_depth=1`, 금지 국가 목록 비어 있지 않음, 날짜·성년 검사 활성 | 아니오 (16개 중 비영) | 예. 커밋 테스트의 KYC·OFAC 입력 형태; 아래 근거 3 | 통과 | 통과 | 통과 | 예 | 24.257069 | 없음 |
| e71f158d | Tangle VAnchor | Transaction(30,16,2): 양수 입력 UTXO 16개, 실제 30층 포함 경로, 양수 출력 2개 | `741a581c253ae7cb238206403a0d1fb547a7fa7a53f1d7c2602b81b2d2e49692` | `b4df967e4c9f987d115aca3a00a7867e067664271bbc61e9d078945d30859bf3` | 금액 16/16 양수, 서로 다른 nullifier, 실제 Merkle 검증, `publicAmount=13`, `extDataHash` 비영, 균형식 성립 | 해당 없음 (0개) | 예. VAnchor 회로·Merkle·테스트 입력 형태; 아래 근거 4 | 통과 | 통과 | 통과 | 예 | 24.895003 | 없음 |

## 근거와 최종 기록

1. **76053f7f.** 기록된 `Zellic__zkerc20` 저장소의 `circuits/circuit.circom:10-40,48-101,124-133`, `circuits/commitment.circom:7-25`, `circuits/merkleroot.circom:4-31`, `circuits/hashtwo.circom:4-14`, `lib/merkleTree.js:75-154`를 따랐다. 저장소 경로는 `runs/c03-corpus-2026-10-02/recovery-v3/repositories/Zellic__zkerc20/clone/`이다. 최종 입력 `76053f7f/docker-final/input.json`, 검사 `76053f7f/docker-final/checks/76053f7fb015aba5e093d82d/check.json`. 생성기 패키지 고정 `scripts/n6_b6_construct_input_76053f7f.lock.json`.
2. **77e0f2db.** 기록된 Pragma 저장소의 `circuits/private_liquidity.circom:169-173,320-327,368-372,388-407,409-425,468-479,494-505`, `circuits/test/private_liquidity.test.js:13-16`, `circuits/test/vectors/private_liquidity/add_liquidity_in_range.json:3,10-16,36-37,58-63,156-166`을 따랐다. 저장소 경로는 `runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/project/`이며, 벡터 SHA-256은 `745a96006d1c479fa837a5b416dd95070f4f066576ec79f9bdd426a0eb2fe02d`이다. 최종 입력 `77e0f2db/final/input.json`, 검사 `77e0f2db/final/checks/77e0f2db173d0c1812de503a/check.json`. Python 표준 라이브러리만 사용해 Docker 생성 대상이 아니다.
3. **83cc0060.** 기록된 `selfxyz__self` 저장소의 `circuits/circuits/disclose/vc_and_disclose_kyc.circom:47-85,92-126,132-164`, `circuits/tests/disclose/vc_and_disclose_kyc.test.ts:23-38,81-95,184-204`, `new-common/src/circuits/inputs/disclose-kyc.ts:30-55,135-215`, `new-common/src/testing/genMockKycData.ts:7-23`을 따랐다. 저장소 경로는 `runs/e01-setup-2026-10-03/recovery-v2/repositories/selfxyz__self/clone/`이며, 테스트가 참조하는 OFAC SMT JSON 두 개의 경로는 `circuits/tests/consts/ofac/nameAndDobKycSMT.json`과 `circuits/tests/consts/ofac/nameAndYobKycSMT.json`이다. 최종 입력 `83cc0060/input.json`, 검사 `83cc0060/checks/83cc00608fdaa7191b839ed6/check.json`. 생성기 패키지 고정 `scripts/n6_b6_construct_input_83cc0060.lock.json`.
4. **e71f158d.** 기록된 `tangle-network__protocol-solidity` 저장소의 `circuits/main/poseidon_vanchor_16_2.circom:3-7`, `circuits/vanchor/transaction.circom:18-41,45-96,100-137`, `circuits/vanchor/keypair.circom:6-24`, `circuits/merkle-tree/manyMerkleProof.circom:11-43`, `packages/utils/src/protocol/merkle-tree.ts:27-82,170-214`, `packages/utils/src/proof/variable-anchor.ts:46-98`, `packages/contracts/test/vanchor/vanchor.test.ts:170-198`을 따랐다. 저장소 경로는 `runs/c03-corpus-2026-10-02/recovery-v3/repositories/tangle-network__protocol-solidity/clone/`이다. 최종 입력 `e71f158d/input.json`, 검사 `e71f158d/checks/e71f158d85178fd29e1ba300/check.json`. 생성기 패키지 고정 `scripts/n6_b6_construct_input_e71f158d.lock.json`.

## 생성 환경과 재현

`76053f7f`, `83cc0060`, `e71f158d`는 각 리비전마다 **동일한** Docker 이미지 `node:22-bookworm-slim` (`node@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392`, Node 22.23.3)에서 두 번 생성했다. 각 실행의 이미지 이름·digest는 해당 `attempts.jsonl`의 Docker generation·attestation 행에 연결되어 있다. `--network none --read-only --tmpfs /tmp`를 사용했고, 기록된 저장소는 읽기 전용, 새 출력 폴더만 쓰기였다. 세 리비전 모두 두 출력의 바이트 SHA-256이 표의 최종 입력 SHA와 같다. `77e0f2db`는 같은 seed와 커밋 벡터 SHA를 검증하는 Python 생성기로 두 번 같은 바이트를 생성했다. 네 최종 검사는 모두 원본 R1CS SHA 일치, 정직 witness·Rust·snarkjs 통과이며 리비전별 3시간 상한 안이다.

## 정정본

기존 표와 네 입력 기록은 보존한다. 아래 표의 77e0f2db 행은 §3의 개수 입력 조건을 반영한 새 최종 입력이다. 탐색층 index는 이 표의 input SHA와 아래 77e0f2db 새 경로를 사용한다. 나머지 세 행은 위 표의 최종 기록과 같다.

| revision | project | 모사 입력 | 생성 스크립트 SHA-256 | input.json SHA-256 | 스위치류 입력 값 | 공개 출력 전부 0 | 예시 형태 일치·근거 | 정직 witness | Rust | snarkjs | R1CS SHA-256 일치 | 소요 시간(초) | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| 76053f7f | Zellic zkerc20 | Split(30,8): 양수 note 8개, 동일 30층 root의 실제 포함 경로, 양수 출력 2개 | `aa8bd04a55438f5719f9f89d5ddcc58d7f6c3b647fc567965668920e134f1474` | `6310b2188d52edf4da33615b01d4cab696271ac5d62af9717dc586696d414dc5` | note 금액 8/8 양수, salt 8/8 비영, sender 소유, Merkle 검증 활성 | 해당 없음 (0개) | 예. 회로의 Split·commitment·Merkle 규칙과 저장소 Merkle 구현; 아래 근거 1 | 통과 | 통과 | 통과 | 예 | 9.837835 | 최초 Mac Node `.js` 생성은 npm 의존 Docker 조건과 달라 원본을 보존하고 Docker `.mjs` 두 번 재생성·재검사. 첫 캐시 권한 실패는 검사 시작 전 종료. 최종 검사 실패 없음 |
| 77e0f2db | Pragma private liquidity | 커밋 LIQ_ADD 시험 벡터의 가격·유동성 계산을 유지하고 양수 token1 note 및 양수 change 추가 | `3ee7b49ac3ec547b9d1bdb6aa0d55cf01498ca80dd0157ff80711e365a182fb8` | `845c0195c7bfbe8d8e674e47c2f980e0061b726cd3985d3951f812689b595607` | `LIQ_ADD`, `token0_note_count=1`, `token1_note_count=1`, 활성 note 금액 각각 1·2, `liquidity_delta=1` | 해당 없음 (0개) | 예. 커밋 벡터에 회로의 token1 Poseidon note·change 관계를 적용; 아래 근거 2-정정 | 통과 | 통과 | 통과 | 예 | 8.218743 | 기존 (1,0) 입력·검사 보존; §3 개수 조건을 위해 새 (1,1) 시도 통과. token1 유동성 소비는 0이고 양수 note가 양수 change로 반환됨 |
| 83cc0060 | Self KYC disclosure | 295바이트 KYC 공개, 실제 credential 포함 경로와 OFAC SMT 증명 2개 | `5140c986e167cd430470f0b677a9c272950508aaeb4a764bf47004992702bc2d` | `25c25eae81db743f82281263bd3b8bbff2c0384fa45d2ff569d24fea62f22e` | `selector_ofac=1`, disclosure 295비트 전부 켬, `leaf_depth=1`, 금지 국가 목록 비어 있지 않음, 날짜·성년 검사 활성 | 아니오 (16개 중 비영) | 예. 커밋 테스트의 KYC·OFAC 입력 형태; 아래 근거 3 | 통과 | 통과 | 통과 | 예 | 24.257069 | 없음 |
| e71f158d | Tangle VAnchor | Transaction(30,16,2): 양수 입력 UTXO 16개, 실제 30층 포함 경로, 양수 출력 2개 | `741a581c253ae7cb238206403a0d1fb547a7fa7a53f1d7c2602b81b2d2e49692` | `b4df967e4c9f987d115aca3a00a7867e067664271bbc61e9d078945d30859bf3` | 금액 16/16 양수, 서로 다른 nullifier, 실제 Merkle 검증, `publicAmount=13`, `extDataHash` 비영, 균형식 성립 | 해당 없음 (0개) | 예. VAnchor 회로·Merkle·테스트 입력 형태; 아래 근거 4 | 통과 | 통과 | 통과 | 예 | 24.895003 | 없음 |

**근거 2-정정.** 기록된 Pragma 저장소 `runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/project/`의 커밋 벡터 `circuits/test/vectors/private_liquidity/add_liquidity_in_range.json:3,8-15,36-37,58-80`(SHA-256 `745a96006d1c479fa837a5b416dd95070f4f066576ec79f9bdd426a0eb2fe02d`)에서 ADD tag·가격·tick·liquidity·몫 입력을 유지했다. 회로 `circuits/private_liquidity.circom:382-407,409-424`는 (1,1)을 허용하고, `:615-678`은 각 활성 token note의 합계와 commitment·nullifier를, `:994-1026,1051-1063`은 token1 change 및 출력 commitment를 검사한다. `circuits/note_commitments.circom:87-143`은 Poseidon nullifier·commitment와 Stark 범위를 정의한다. `rust/client/src/proofs.rs:630-633,683-684`는 두 note 목록을 취급한다. `merkle_root_token1`은 활성 note commitment와 같으며 `circuits/private_liquidity.circom:174-235,438-441`에는 별도 Merkle path 검사가 없고 `rust/client/src/swap.rs:730-745`는 빈 path의 root를 leaf로 계산한다. 이 회로상 제한과 token1 유동성 소비 0은 `77e0f2db/notes.md`에 명시했다. 최종 입력 경로는 `77e0f2db/both-v3/input.json`, 검사 경로는 `77e0f2db/both-v3/checks/77e0f2db173d0c1812de503a/check.json`이다. 생성기는 고정 Docker 이미지 `node:22-bookworm-slim` (`node@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392`)에서 `--network none --read-only`로 두 번 실행했고 같은 SHA가 나왔다. 두 생성 회차의 이미지 이름·digest는 `77e0f2db/attempts.jsonl`에 각각 기록했다.


## 9. 후속 4개 검토표 전사 정정 최종본

§8에 복제한 첫 정정본의 83cc0060 입력 SHA에서 두 자리가 빠진 전사 오류를 발견했다. 원본 표 6,945바이트와 첫 정정본까지 11,749바이트/SHA-256 `b7d1a1f8e7a434f28b7612257001c18582e40deb23dc69cd3b7dacdba29abfb1`는 보존했다. 두 번째 정정본을 덧붙인 리드 검토용 `review-table-2.md` 전체 SHA-256은 `853dcdd211a1bec7c73d273f9209488c3b99690f7aca357899fccab278aeaccf`이다. 다음이 최종 파일 전문이다.

# N6-B6 후속 4개 구성 입력 검토표

후보 값·B 요청 행·J 출력은 열지 않았다. 표의 SHA-256과 시간은 각 리비전의 최종 입력 및 최종 원본 검사 기록 기준이다. `공개 출력 전부 0`의 `해당 없음`은 공개 출력 wire가 0개라는 뜻이다. 생성 시도의 상세 기록과 이미지 증거는 각 리비전의 `attempts.jsonl`, 방법 설명은 `notes.md`에 있다.

| revision | project | 모사 입력 | 생성 스크립트 SHA-256 | input.json SHA-256 | 스위치류 입력 값 | 공개 출력 전부 0 | 예시 형태 일치·근거 | 정직 witness | Rust | snarkjs | R1CS SHA-256 일치 | 소요 시간(초) | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| 76053f7f | Zellic zkerc20 | Split(30,8): 양수 note 8개, 동일 30층 root의 실제 포함 경로, 양수 출력 2개 | `aa8bd04a55438f5719f9f89d5ddcc58d7f6c3b647fc567965668920e134f1474` | `6310b2188d52edf4da33615b01d4cab696271ac5d62af9717dc586696d414dc5` | note 금액 8/8 양수, salt 8/8 비영, sender 소유, Merkle 검증 활성 | 해당 없음 (0개) | 예. 회로의 Split·commitment·Merkle 규칙과 저장소 Merkle 구현; 아래 근거 1 | 통과 | 통과 | 통과 | 예 | 9.837835 | 최초 Mac Node `.js` 생성은 npm 의존 Docker 조건과 달라 원본을 보존하고 Docker `.mjs` 두 번 재생성·재검사. 첫 캐시 권한 실패는 검사 시작 전 종료. 최종 검사 실패 없음 |
| 77e0f2db | Pragma private liquidity | 커밋 시험 벡터의 한쪽 token0 note를 쓰는 `LIQ_ADD` | `c91e54405a15cf21b25ddd5d28c4910b0f852dbef9197164a7384f887b1c16da` | `c5ebc90ff93101fa80964a65603aab0d125a4645a35d5086c5bac5f44ad5998e` | `LIQ_ADD`, `token0_note_count=1`, `token1_note_count=0`, `liquidity_delta=1`, 활성 note 금액 양수 | 해당 없음 (0개) | 예. 커밋된 `add_liquidity_in_range.json`와 회로·테스트; 아래 근거 2 | 통과 | 통과 | 통과 | 예 | 8.371277 | 첫 inactive slot secret 변형은 정직 witness 실패; 실패 파일 보존. 커밋 시험 벡터 진단 통과 후 최종 경로에 생성·검사 통과 |
| 83cc0060 | Self KYC disclosure | 295바이트 KYC 공개, 실제 credential 포함 경로와 OFAC SMT 증명 2개 | `5140c986e167cd430470f0b677a9c272950508aaeb4a764bf47004992702bc2d` | `25c25eae81db743f82281263bd3b8bbff2c0384fa45d2ff569d24fea62f22e` | `selector_ofac=1`, disclosure 295비트 전부 켬, `leaf_depth=1`, 금지 국가 목록 비어 있지 않음, 날짜·성년 검사 활성 | 아니오 (16개 중 비영) | 예. 커밋 테스트의 KYC·OFAC 입력 형태; 아래 근거 3 | 통과 | 통과 | 통과 | 예 | 24.257069 | 없음 |
| e71f158d | Tangle VAnchor | Transaction(30,16,2): 양수 입력 UTXO 16개, 실제 30층 포함 경로, 양수 출력 2개 | `741a581c253ae7cb238206403a0d1fb547a7fa7a53f1d7c2602b81b2d2e49692` | `b4df967e4c9f987d115aca3a00a7867e067664271bbc61e9d078945d30859bf3` | 금액 16/16 양수, 서로 다른 nullifier, 실제 Merkle 검증, `publicAmount=13`, `extDataHash` 비영, 균형식 성립 | 해당 없음 (0개) | 예. VAnchor 회로·Merkle·테스트 입력 형태; 아래 근거 4 | 통과 | 통과 | 통과 | 예 | 24.895003 | 없음 |

## 근거와 최종 기록

1. **76053f7f.** 기록된 `Zellic__zkerc20` 저장소의 `circuits/circuit.circom:10-40,48-101,124-133`, `circuits/commitment.circom:7-25`, `circuits/merkleroot.circom:4-31`, `circuits/hashtwo.circom:4-14`, `lib/merkleTree.js:75-154`를 따랐다. 저장소 경로는 `runs/c03-corpus-2026-10-02/recovery-v3/repositories/Zellic__zkerc20/clone/`이다. 최종 입력 `76053f7f/docker-final/input.json`, 검사 `76053f7f/docker-final/checks/76053f7fb015aba5e093d82d/check.json`. 생성기 패키지 고정 `scripts/n6_b6_construct_input_76053f7f.lock.json`.
2. **77e0f2db.** 기록된 Pragma 저장소의 `circuits/private_liquidity.circom:169-173,320-327,368-372,388-407,409-425,468-479,494-505`, `circuits/test/private_liquidity.test.js:13-16`, `circuits/test/vectors/private_liquidity/add_liquidity_in_range.json:3,10-16,36-37,58-63,156-166`을 따랐다. 저장소 경로는 `runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/project/`이며, 벡터 SHA-256은 `745a96006d1c479fa837a5b416dd95070f4f066576ec79f9bdd426a0eb2fe02d`이다. 최종 입력 `77e0f2db/final/input.json`, 검사 `77e0f2db/final/checks/77e0f2db173d0c1812de503a/check.json`. Python 표준 라이브러리만 사용해 Docker 생성 대상이 아니다.
3. **83cc0060.** 기록된 `selfxyz__self` 저장소의 `circuits/circuits/disclose/vc_and_disclose_kyc.circom:47-85,92-126,132-164`, `circuits/tests/disclose/vc_and_disclose_kyc.test.ts:23-38,81-95,184-204`, `new-common/src/circuits/inputs/disclose-kyc.ts:30-55,135-215`, `new-common/src/testing/genMockKycData.ts:7-23`을 따랐다. 저장소 경로는 `runs/e01-setup-2026-10-03/recovery-v2/repositories/selfxyz__self/clone/`이며, 테스트가 참조하는 OFAC SMT JSON 두 개의 경로는 `circuits/tests/consts/ofac/nameAndDobKycSMT.json`과 `circuits/tests/consts/ofac/nameAndYobKycSMT.json`이다. 최종 입력 `83cc0060/input.json`, 검사 `83cc0060/checks/83cc00608fdaa7191b839ed6/check.json`. 생성기 패키지 고정 `scripts/n6_b6_construct_input_83cc0060.lock.json`.
4. **e71f158d.** 기록된 `tangle-network__protocol-solidity` 저장소의 `circuits/main/poseidon_vanchor_16_2.circom:3-7`, `circuits/vanchor/transaction.circom:18-41,45-96,100-137`, `circuits/vanchor/keypair.circom:6-24`, `circuits/merkle-tree/manyMerkleProof.circom:11-43`, `packages/utils/src/protocol/merkle-tree.ts:27-82,170-214`, `packages/utils/src/proof/variable-anchor.ts:46-98`, `packages/contracts/test/vanchor/vanchor.test.ts:170-198`을 따랐다. 저장소 경로는 `runs/c03-corpus-2026-10-02/recovery-v3/repositories/tangle-network__protocol-solidity/clone/`이다. 최종 입력 `e71f158d/input.json`, 검사 `e71f158d/checks/e71f158d85178fd29e1ba300/check.json`. 생성기 패키지 고정 `scripts/n6_b6_construct_input_e71f158d.lock.json`.

## 생성 환경과 재현

`76053f7f`, `83cc0060`, `e71f158d`는 각 리비전마다 **동일한** Docker 이미지 `node:22-bookworm-slim` (`node@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392`, Node 22.23.3)에서 두 번 생성했다. 각 실행의 이미지 이름·digest는 해당 `attempts.jsonl`의 Docker generation·attestation 행에 연결되어 있다. `--network none --read-only --tmpfs /tmp`를 사용했고, 기록된 저장소는 읽기 전용, 새 출력 폴더만 쓰기였다. 세 리비전 모두 두 출력의 바이트 SHA-256이 표의 최종 입력 SHA와 같다. `77e0f2db`는 같은 seed와 커밋 벡터 SHA를 검증하는 Python 생성기로 두 번 같은 바이트를 생성했다. 네 최종 검사는 모두 원본 R1CS SHA 일치, 정직 witness·Rust·snarkjs 통과이며 리비전별 3시간 상한 안이다.

## 정정본

기존 표와 네 입력 기록은 보존한다. 아래 표의 77e0f2db 행은 §3의 개수 입력 조건을 반영한 새 최종 입력이다. 탐색층 index는 이 표의 input SHA와 아래 77e0f2db 새 경로를 사용한다. 나머지 세 행은 위 표의 최종 기록과 같다.

| revision | project | 모사 입력 | 생성 스크립트 SHA-256 | input.json SHA-256 | 스위치류 입력 값 | 공개 출력 전부 0 | 예시 형태 일치·근거 | 정직 witness | Rust | snarkjs | R1CS SHA-256 일치 | 소요 시간(초) | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| 76053f7f | Zellic zkerc20 | Split(30,8): 양수 note 8개, 동일 30층 root의 실제 포함 경로, 양수 출력 2개 | `aa8bd04a55438f5719f9f89d5ddcc58d7f6c3b647fc567965668920e134f1474` | `6310b2188d52edf4da33615b01d4cab696271ac5d62af9717dc586696d414dc5` | note 금액 8/8 양수, salt 8/8 비영, sender 소유, Merkle 검증 활성 | 해당 없음 (0개) | 예. 회로의 Split·commitment·Merkle 규칙과 저장소 Merkle 구현; 아래 근거 1 | 통과 | 통과 | 통과 | 예 | 9.837835 | 최초 Mac Node `.js` 생성은 npm 의존 Docker 조건과 달라 원본을 보존하고 Docker `.mjs` 두 번 재생성·재검사. 첫 캐시 권한 실패는 검사 시작 전 종료. 최종 검사 실패 없음 |
| 77e0f2db | Pragma private liquidity | 커밋 LIQ_ADD 시험 벡터의 가격·유동성 계산을 유지하고 양수 token1 note 및 양수 change 추가 | `3ee7b49ac3ec547b9d1bdb6aa0d55cf01498ca80dd0157ff80711e365a182fb8` | `845c0195c7bfbe8d8e674e47c2f980e0061b726cd3985d3951f812689b595607` | `LIQ_ADD`, `token0_note_count=1`, `token1_note_count=1`, 활성 note 금액 각각 1·2, `liquidity_delta=1` | 해당 없음 (0개) | 예. 커밋 벡터에 회로의 token1 Poseidon note·change 관계를 적용; 아래 근거 2-정정 | 통과 | 통과 | 통과 | 예 | 8.218743 | 기존 (1,0) 입력·검사 보존; §3 개수 조건을 위해 새 (1,1) 시도 통과. token1 유동성 소비는 0이고 양수 note가 양수 change로 반환됨 |
| 83cc0060 | Self KYC disclosure | 295바이트 KYC 공개, 실제 credential 포함 경로와 OFAC SMT 증명 2개 | `5140c986e167cd430470f0b677a9c272950508aaeb4a764bf47004992702bc2d` | `25c25eae81db743f82281263bd3b8bbff2c0384fa45d2ff569d24fea62f22e` | `selector_ofac=1`, disclosure 295비트 전부 켬, `leaf_depth=1`, 금지 국가 목록 비어 있지 않음, 날짜·성년 검사 활성 | 아니오 (16개 중 비영) | 예. 커밋 테스트의 KYC·OFAC 입력 형태; 아래 근거 3 | 통과 | 통과 | 통과 | 예 | 24.257069 | 없음 |
| e71f158d | Tangle VAnchor | Transaction(30,16,2): 양수 입력 UTXO 16개, 실제 30층 포함 경로, 양수 출력 2개 | `741a581c253ae7cb238206403a0d1fb547a7fa7a53f1d7c2602b81b2d2e49692` | `b4df967e4c9f987d115aca3a00a7867e067664271bbc61e9d078945d30859bf3` | 금액 16/16 양수, 서로 다른 nullifier, 실제 Merkle 검증, `publicAmount=13`, `extDataHash` 비영, 균형식 성립 | 해당 없음 (0개) | 예. VAnchor 회로·Merkle·테스트 입력 형태; 아래 근거 4 | 통과 | 통과 | 통과 | 예 | 24.895003 | 없음 |

**근거 2-정정.** 기록된 Pragma 저장소 `runs/n6-b2-2026-10-09.noindex/pragma-77e0f2db173d0c1812de503a/project/`의 커밋 벡터 `circuits/test/vectors/private_liquidity/add_liquidity_in_range.json:3,8-15,36-37,58-80`(SHA-256 `745a96006d1c479fa837a5b416dd95070f4f066576ec79f9bdd426a0eb2fe02d`)에서 ADD tag·가격·tick·liquidity·몫 입력을 유지했다. 회로 `circuits/private_liquidity.circom:382-407,409-424`는 (1,1)을 허용하고, `:615-678`은 각 활성 token note의 합계와 commitment·nullifier를, `:994-1026,1051-1063`은 token1 change 및 출력 commitment를 검사한다. `circuits/note_commitments.circom:87-143`은 Poseidon nullifier·commitment와 Stark 범위를 정의한다. `rust/client/src/proofs.rs:630-633,683-684`는 두 note 목록을 취급한다. `merkle_root_token1`은 활성 note commitment와 같으며 `circuits/private_liquidity.circom:174-235,438-441`에는 별도 Merkle path 검사가 없고 `rust/client/src/swap.rs:730-745`는 빈 path의 root를 leaf로 계산한다. 이 회로상 제한과 token1 유동성 소비 0은 `77e0f2db/notes.md`에 명시했다. 최종 입력 경로는 `77e0f2db/both-v3/input.json`, 검사 경로는 `77e0f2db/both-v3/checks/77e0f2db173d0c1812de503a/check.json`이다. 생성기는 고정 Docker 이미지 `node:22-bookworm-slim` (`node@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392`)에서 `--network none --read-only`로 두 번 실행했고 같은 SHA가 나왔다. 두 생성 회차의 이미지 이름·digest는 `77e0f2db/attempts.jsonl`에 각각 기록했다.

## 정정본 2

첫 표와 첫 정정본은 바이트 그대로 보존했다. 아래 표는 `83cc0060` 행에서 두 글자 `3d`가 누락된 입력 SHA-256 전사 오류를 바로잡은 최종 4행 표다. 입력 파일·생성기·검사 기록은 바뀌지 않았다. 탐색층 index는 아래 표의 각 SHA-256과 최종 경로를 사용한다.

| revision | project | 모사 입력 | 생성 스크립트 SHA-256 | input.json SHA-256 | 스위치류 입력 값 | 공개 출력 전부 0 | 예시 형태 일치·근거 | 정직 witness | Rust | snarkjs | R1CS SHA-256 일치 | 소요 시간(초) | 실패 사유 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | --- |
| 76053f7f | Zellic zkerc20 | Split(30,8): 양수 note 8개, 동일 30층 root의 실제 포함 경로, 양수 출력 2개 | `aa8bd04a55438f5719f9f89d5ddcc58d7f6c3b647fc567965668920e134f1474` | `6310b2188d52edf4da33615b01d4cab696271ac5d62af9717dc586696d414dc5` | note 금액 8/8 양수, salt 8/8 비영, sender 소유, Merkle 검증 활성 | 해당 없음 (0개) | 예. 회로의 Split·commitment·Merkle 규칙과 저장소 Merkle 구현; 아래 근거 1 | 통과 | 통과 | 통과 | 예 | 9.837835 | 최초 Mac Node `.js` 생성은 npm 의존 Docker 조건과 달라 원본을 보존하고 Docker `.mjs` 두 번 재생성·재검사. 첫 캐시 권한 실패는 검사 시작 전 종료. 최종 검사 실패 없음 |
| 77e0f2db | Pragma private liquidity | 커밋 LIQ_ADD 시험 벡터의 가격·유동성 계산을 유지하고 양수 token1 note 및 양수 change 추가 | `3ee7b49ac3ec547b9d1bdb6aa0d55cf01498ca80dd0157ff80711e365a182fb8` | `845c0195c7bfbe8d8e674e47c2f980e0061b726cd3985d3951f812689b595607` | `LIQ_ADD`, `token0_note_count=1`, `token1_note_count=1`, 활성 note 금액 각각 1·2, `liquidity_delta=1` | 해당 없음 (0개) | 예. 커밋 벡터에 회로의 token1 Poseidon note·change 관계를 적용; 아래 근거 2-정정 | 통과 | 통과 | 통과 | 예 | 8.218743 | 기존 (1,0) 입력·검사 보존; §3 개수 조건을 위해 새 (1,1) 시도 통과. token1 유동성 소비는 0이고 양수 note가 양수 change로 반환됨 |
| 83cc0060 | Self KYC disclosure | 295바이트 KYC 공개, 실제 credential 포함 경로와 OFAC SMT 증명 2개 | `5140c986e167cd430470f0b677a9c272950508aaeb4a764bf47004992702bc2d` | `25c25eae81db743f82281263bd3d3b8bbff2c0384fa45d2ff569d24fea62f22e` | `selector_ofac=1`, disclosure 295비트 전부 켬, `leaf_depth=1`, 금지 국가 목록 비어 있지 않음, 날짜·성년 검사 활성 | 아니오 (16개 중 비영) | 예. 커밋 테스트의 KYC·OFAC 입력 형태; 아래 근거 3 | 통과 | 통과 | 통과 | 예 | 24.257069 | 없음 |
| e71f158d | Tangle VAnchor | Transaction(30,16,2): 양수 입력 UTXO 16개, 실제 30층 포함 경로, 양수 출력 2개 | `741a581c253ae7cb238206403a0d1fb547a7fa7a53f1d7c2602b81b2d2e49692` | `b4df967e4c9f987d115aca3a00a7867e067664271bbc61e9d078945d30859bf3` | 금액 16/16 양수, 서로 다른 nullifier, 실제 Merkle 검증, `publicAmount=13`, `extDataHash` 비영, 균형식 성립 | 해당 없음 (0개) | 예. VAnchor 회로·Merkle·테스트 입력 형태; 아래 근거 4 | 통과 | 통과 | 통과 | 예 | 24.895003 | 없음 |

83cc0060 최종 입력은 `83cc0060/input.json`이며, 그 실제 SHA-256을 파일 바이트에서 다시 계산해 표에 적었다. 이 입력의 원본 검사 `83cc0060/checks/83cc00608fdaa7191b839ed6/check.json`은 기존대로 통과다. 77e0f2db 최종 입력은 첫 정정본에서 정한 `77e0f2db/both-v3/input.json`이다. 각 리비전의 정확한 소스 경로:행과 Docker 이미지 증거는 앞선 근거 절·각 `notes.md`·`attempts.jsonl`을 따른다.

## 10. 구성 입력 색인과 생성 이미지 최종 대조

이 절은 앞의 작업 중간 기록을 마친 뒤 고정한 색인을 기록한다. `runs/n6-b6-2026-10-18.noindex/constructed-inputs/index.json` SHA-256은 `a00cdccc81d56ab5541806c0140582e5c4a934ceb0702c0c1c1e2e13589ae217`이고, 최초 생성 스크립트 `scripts/n6_b6_constructed_input_index.py` SHA-256은 `f7cea10ce8fb98e4d79d655d56848b4dcb6d9c4dc3785b965780dfd6911ed324`다. 색인은 `n6-j1-base-inputs-v1`, `layer=constructed` 형식으로 10개 리비전을 담는다. 새 입력 9개는 `passed`, 60271bae는 새 구성을 시도하지 않은 `base_input_unavailable`이며 경로·해시가 없다. 60271bae의 엄격층 전부 0 입력은 엄격층 기록에 그대로 남긴다. 두 검토표의 마지막 완전한 표 5행·4행과 9개 실제 입력 SHA-256, 각 원본 검사 기록의 R1CS·정직 witness·Rust·snarkjs 통과를 대조했다. B 요청 포함 리비전 다섯 개에서 기존 요청 107건을 보존할 준비가 됐지만 탐색층 요청 index·J 시범·전체 J는 실행하지 않았다.

다음 표의 경로는 `runs/n6-b6-2026-10-18.noindex/constructed-inputs/` 기준이다. Docker 생성 대상 일곱 리비전은 각각 같은 이름·digest의 이미지로 네트워크 없이 독립 2회 생성했고, 두 회차의 SHA-256과 최종 색인의 입력 SHA-256이 일치한다. 각 회차의 이미지 이름·digest·시각·생성 SHA는 해당 리비전 `attempts.jsonl`에 있다. 이미지는 리비전 사이에는 달라도 리비전 안에서는 바뀌지 않았다. Python 표준 라이브러리만 쓴 두 B 입력과 세 A 입력은 Docker 이미지가 없다.

| 리비전 | 최종 input.json 경로 | 생성에 실제 사용한 Docker 이미지 이름 | digest | 2회 동일 SHA |
| --- | --- | --- | --- | --- |
| 6079a717 | `6079a717/input.json` | 해당 없음 (Python 표준 라이브러리) | 해당 없음 | 예 |
| b5b5cf5d | `b5b5cf5d/docker-final/input.json` | `docker.io/library/node` | `sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d` | 예 |
| 340107e1 | `340107e1/docker-final/input.json` | `docker.io/library/node` | `sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d` | 예 |
| 4c221df7 | `4c221df7/docker-final/input.json` | `docker.io/library/node` | `sha256:c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d` | 예 |
| a8b2aa9c | `a8b2aa9c/input.json` | 해당 없음 (Python 표준 라이브러리) | 해당 없음 | 예 |
| 76053f7f | `76053f7f/docker-final/input.json` | `node:22-bookworm-slim` | `sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392` | 예 |
| 77e0f2db | `77e0f2db/both-v3/input.json` | `node:22-bookworm-slim` | `sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392` | 예 |
| 83cc0060 | `83cc0060/input.json` | `node:22-bookworm-slim` | `sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392` | 예 |
| e71f158d | `e71f158d/input.json` | `node:22-bookworm-slim` | `sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392` | 예 |

첫 이미지의 `attempts.jsonl`에는 태그 없이 저장소 이름 `docker.io/library/node`와 고정 digest가 기록돼 있고 실행 전후 image ID도 그 digest와 같았다. `77e0f2db`의 실제 최종 Docker 실행 파일은 `scripts/n6_b6_construct_input_77e0f2db_both.mjs`다. 색인의 `constructed_generator_path`는 같은 바이트(SHA-256 `3ee7b49ac3ec547b9d1bdb6aa0d55cf01498ca80dd0157ff80711e365a182fb8`)인 `scripts/n6_b6_construct_input_77e0f2db.mjs` 별칭을 가리킨다. 실제 실행 경로는 `attempts.jsonl`이 정확히 기록한다. 별칭 자체를 실행한 증거는 없으므로 색인의 경로 필드를 실행 이력의 근거로 해석하지 않는다.

첫 검토표 `review-table.md`의 **최종 전체 파일** SHA-256은 `f5876f698b5952155b00d2461cd4e81c48892318edcc4f35cc4079e0388ef22d`, 후속 검토표 `review-table-2.md`의 **최종 전체 파일** SHA-256은 `853dcdd211a1bec7c73d273f9209488c3b99690f7aca357899fccab278aeaccf`다. 최종 내용은 각각 §7의 `정정본`, §9의 `정정본 2`다. 앞 절들에 보존한 이전 표·SHA는 검토용 최종판이 아니다.

## 11. 리드 검토 관문과 이후 실행 명령

첫 다섯 리비전은 리드가 `review-table.md`의 최종판을 검토·승인한 뒤에만 `lead-input-review.json`을 만든다. 지금 색인의 요청 107건을 모두 호출하려면 다섯 개가 모두 승인돼야 한다. 아래는 **다섯 개 전부 승인됐을 때만** miiz가 사용할 한 줄 형식이다. `open("x")`는 기존 검토 기록을 덮어쓰지 않는다. 준비 단계에서는 이 명령을 실행하지 않았고 실제 리드 기록도 만들지 않았다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && python3 -c 'import json; from datetime import datetime,timezone; from pathlib import Path; p=Path("runs/n6-b6-2026-10-18.noindex/lead-input-review.json"); data={"reviewed_table_sha256":"f5876f698b5952155b00d2461cd4e81c48892318edcc4f35cc4079e0388ef22d","approved_revisions":["6079a717","b5b5cf5d","340107e1","4c221df7","a8b2aa9c"],"reviewer":"lead","time_utc":datetime.now(timezone.utc).isoformat()}; f=p.open("x",encoding="utf-8"); f.write(json.dumps(data,ensure_ascii=False)+"\n"); f.close()'
```

요청 없는 후속 네 리비전도 탐색층 1묶음 **판정 결과를 열기 전** 리드가 `review-table-2.md`를 검토한다. 지금 색인에는 네 입력이 모두 `passed`이므로 결과 열람 관문을 통과하려면 네 개의 승인이 필요하다. **네 개 전부 승인됐을 때만** 다음 형식으로 miiz가 `lead-input-review-2.json`을 만든다. 이 기록은 첫 파일과 별개이며 준비 단계에서 만들지 않았다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && python3 -c 'import json; from datetime import datetime,timezone; from pathlib import Path; p=Path("runs/n6-b6-2026-10-18.noindex/lead-input-review-2.json"); data={"reviewed_table_sha256":"853dcdd211a1bec7c73d273f9209488c3b99690f7aca357899fccab278aeaccf","approved_revisions":["76053f7f","77e0f2db","83cc0060","e71f158d"],"reviewer":"lead","time_utc":datetime.now(timezone.utc).isoformat()}; f=p.open("x",encoding="utf-8"); f.write(json.dumps(data,ensure_ascii=False)+"\n"); f.close()'
```

S 재퍼징이 끝난 뒤 키티에서 사용할 **세 개의 별도 한 줄 명령**은 다음 순서다. A 보정과 B 탐색층은 동시에 돌리지 않는다. 리드 첫 검토 기록이 없으면 두 번째 명령은 J 시범 전에 거부된다.

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr && python3 scripts/n6_b6_a_calibration.py --action execute && python3 scripts/n6_b6_a_calibration.py --action aggregate
cd /Users/miiz/Desktop/kwzzzz_zkfr && python3 scripts/n6_b6_batch1x_prepare.py --action pilot
cd /Users/miiz/Desktop/kwzzzz_zkfr && python3 scripts/n6_b6_batch1x_prepare.py --action execute-all
```

탐색층 전체 J 뒤에도 두 엔진의 완료 상태와 두 리드 검토 기록을 확인하기 전에는 결과를 열지 않는다. `python3 scripts/n6_b6_batch1x_prepare.py --action verify-results-gate`는 그때 사용할 메타데이터 관문 명령이며 결과 값을 읽거나 출력하지 않는다. 기존 B5 `batch1-prep.noindex`·준비 실행기는 변경하지 않았다. 새 실행기는 엄격층의 기준 입력 수집·entrypoint 재분류 대신 구성 색인을 사용하고, 새 출력 `batch1x-prep.noindex`·외장 캐시 `/Volumes/zkfdo-jcache/n6-b6-batch1x`·N5 개정 SHA preflight·두 검토표 관문을 추가했다. 요청 생성기, v1/v2.2 엔진, 판정 규칙은 그대로다. 탐색층의 배제 표시는 추후 층별 보고 집계에서만 `구성 입력 기준 배제`로 쓴다.

제약 수 최대 시범이 340107e1(4,802,568개)이라면, 이 회로의 구성 입력 원본 검사는 145.941~166.436초, 계측된 최대 자식 RSS는 4,022,480 KiB(약 3.84 GiB), swap은 0이었다. 이는 J 시범 측정치가 아니다. 일정 계획값은 **340107e1의 엔진당 적어도 30분, 두 엔진에 1시간 이상**, 가용 메모리 **20 GiB 이상**으로 잡는다. 초기 컴파일·새 캐시·탐색 비용은 아직 실측하지 않아 계획값을 상한으로 쓰지 않는다. 저장소와 외장 캐시는 실행기 각각의 기존 40 GiB 여유 공간 관문을 통과해야 한다.

## 12. 지시와 다른 점 및 남은 관문

- A의 `inference-original`과 `inference-r-intdiv`는 앞 8자가 같아 지시서의 8자 생성기 이름을 구분되는 전체 식별자로 바꿨다. A 생성값을 고정한 뒤 출력의 배타 생성과 집계 분류·동시 실행 방지 코드를 보강했으며, 생성 입력 SHA는 바뀌지 않았다. A 재실행·집계는 아직 하지 않았다.
- `b5b5cf5d`, `340107e1`, `4c221df7`, `76053f7f`의 초기 Mac 생성은 npm 자료 의존 Docker 생성 조건과 달랐다. 초기 파일·시도는 보존하고 고정 이미지의 `.mjs`를 각각 독립 2회 실행해 새 최종 입력을 검사했다. `77e0f2db`의 첫 실패 시도와 (1,0) 개수 입력도 보존하고, (1,1) 활성 note 입력을 새 경로에서 검사했다. 이 회로의 token1 유동성 소비는 0이고 양수 note가 change로 반환되는 한계는 최종 표·notes에 있다.
- `review-table-2.md`의 앞 두 표에 있던 83cc0060 입력 SHA 전사 누락 두 글자를 마지막 `정정본 2`에 바로잡았다. 표의 이전 바이트와 나머지 입력·검사 기록은 보존했다. 최종 표 SHA는 §10에 있다.
- 77e0f2db 색인의 생성기 경로는 실제 실행 경로와 달리 동일 바이트 별칭이다. 색인 최초 생성 전 검사에서 모든 리비전의 Rust checker SHA가 같다고 가정했다가 실제로는 리비전별 빌드 SHA가 달라 실패했고, 색인 파일이 없는 상태에서 검사를 고쳐 최초 한 번 생성했다. §10의 색인에는 각 리비전의 실제 검사 SHA가 들어 있다.
- 한 차례 `rg --files`로 `runs/` 하위의 파일 이름을 재귀 열거해 지시서 0절의 금지 명령 범위를 벗어났다. 파일 이름 목록만 보았고 B 후보 값·요청 행·J 출력·판정 값은 열지 않았다. 외장 캐시 쓰기 권한으로 검사가 시작 전 중단된 시도와 겹친 `cargo test` 한 세션의 즉시 중단도 기록했다. 최종 필수 검사는 별도 완료 세션으로 확인한다.
- 리드 검토 기록 두 개가 아직 없어 실제 탐색층 시범·전체 J·결과 열람 관문은 통과한 상태가 아니다. 엄격층 본 결과는 **B 1묶음 기준 입력 0/107, 판정 불가**로 유지한다. 구성 입력 9/9의 정직 검사 통과는 후속 탐색층의 준비 결과이며 B 판정 수치와 합치지 않는다.

## 13. 최종 검사와 코드 해시

결과 열람 관문은 두 전체 J 완료 단계가 기록한 SHA-256을 현재 각 엔진의 `state.json` 파일 바이트 해시와 다시 대조한다. 파일이 없거나 바뀌면 결과 열람을 거부한다. 이 보강은 J 출력 내용을 읽거나 판정 규칙을 바꾸지 않는다. 임시 폴더의 합성 기록만 쓴 Python 단위 검사에서 리드 파일 누락·표/입력 해시 변경·미승인 호출·둘째 검토 누락·전체 J 상태 변조를 거부했고, A 분류를 포함해 **29/29 통과**했다. 리드 기록 두 개가 없으므로 실제 시범·전체 J·실제 결과 열람 관문은 실행하지 않았다.

| 최종 파일 | SHA-256 |
| --- | --- |
| `scripts/n6_b6_strict_final_index.py` | `fa11eada786f20b1885e0b25df0d53a29f32df139c8b2fc4c9250dbc1465e7e1` |
| `runs/n6-b6-2026-10-18.noindex/strict-final-index.json` | `9d53231056773c4f8ec967c413eaad48dec870bdf3689202474d753342edca06` |
| `scripts/n6_b6_check_constructed_input.py` | `e9523bf03880934a31f4e7354374868e52e71971484110477136e6b680498292` |
| `scripts/n6_b6_constructed_input_index.py` | `f7cea10ce8fb98e4d79d655d56848b4dcb6d9c4dc3785b965780dfd6911ed324` |
| `scripts/n6_b6_a_calibration.py` | `b6e38733486cd9ae3ac33cdca4e51338c0b37d01131f163def1209ed0d7bb17a` |
| `scripts/n6_b6_batch1x_prepare.py` | `3bc5d5b6a9617e85f28c00f1efe7556fe43d92b0cb6ee420f68d4f19750889a1` |
| `tests/n6_b6_a_calibration_test.py` | `75c10a89b77c71de8067417a4685f124bd3795aa1a4dfb7ce4f89e5acdcacd5a` |
| `tests/n6_b6_batch1x_prepare_test.py` | `815c5529be569c6f1f03dcd1ae5ae962cbe27d1a9aedb1cf8a24322b412fbe80` |

최종 B 생성기 아홉 개의 SHA-256은 두 검토표의 마지막 완전한 표에, A 생성기 세 개의 최종 SHA-256은 §4의 안전 보정 기록에 있다. A 실행 계획·두 요청 index·비교법 v2의 SHA-256은 §4와 `A 보정 준비 최종 코드 고정`에 있다. 필수 검사는 마지막 코드 수정 뒤 `cargo fmt` exit 0, `cargo fmt --check` exit 0, `cargo clippy --all-targets --all-features -- -D warnings` exit 0, `cargo test` exit 0이었다. Python `unittest discover -s tests -p 'n6_b6_*test.py' -v`는 29/29, `git diff --check`는 통과했고 두 리드 기록 생성 명령은 실행하지 않고 구문만 확인했다.

최종 상태는 **엄격층 결과 기록 완료·A 보정 입력 준비 완료·B 구성 입력 9개 및 두 검토표·후속 실행 준비 완료**다. A 재실행, B 탐색층 시범과 전체 판정, S 재퍼징, 리드 검토, B 판정 결과 열람은 이 작업에서 하지 않았다.


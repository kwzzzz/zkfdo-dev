# A aq 실행기 v3.1 (2026-10-26)

miiz 승인(2026-10-26)으로 v3를 복사해 한 가지만 바꾼 실행기다.

## 바꾼 점

- 요청 5연속 정지 규칙에서, B 1묶음(구성 입력)이 결과로 센 준비 실패 이유 두 가지를 세지 않는다.
  - `preparation:candidate_missing_signals`
  - `preparation:entrypoint_compile_failed`
- 실행할 때 이 목록을 stderr에 출력한다.
- 다른 준비 실패와 실행 오류는 v3와 똑같이 센다.
- 위 두 이유로 저장된 연속 실패 기록은 가져오지 않는다.
- 그대로인 것: 리비전 2연속 규칙, 마감, 순서, 정리, 디스크 관문, 엔진·요청 index·입력 고정값.
- v3의 설정 결합에 스크립트 SHA가 들어 있어서, 상태 파일을 `aq-exec/state-v3_1.json`으로 분리했다.
- 같은 이유로 고정 기록·로그 이름도 v3_1로 분리했다: `request-order-v3_1.json`, `progress-v3_1.jsonl`, `attempts-v3_1.jsonl`, `disk-waits-v3_1.jsonl`, `workspace-cleanup-v3_1`, `aggregates-v3_1`, `storage-seeds-v3_1`.
  - 첫 시작(22:20)은 v3가 남긴 `request-order-v3.json`과 내용이 달라 판정 0건으로 거부됐다. 그래서 이름을 분리했다.
  - v3와 v2의 상태·출력은 바꾸지 않았다.
  - `state-v3.json`은 v3가 판정 없이 정지한 기록으로 남는다.

## 바꾼 이유

- 20:32에 v2가 aq-024 비위치 요청 5건(2146, 2150, 2152, 2154, 2158)에서 연달아 `candidate_missing_signals`를 받았다.
- 이 준비 실패로 요청 5연속 규칙이 발동해 v2가 정지했다.
- v3는 같은 연속 기록을 가져와 바로 정지했다.
- 이 이유는 판정 엔진이 정상적으로 내린 준비 실패 결과다. B에서도 그대로 결과로 셌다.

## 파일

| 파일 | SHA-256 |
|---|---|
| `scripts/n6_a_remeasure_aq_execute_v3_1.py` | `c93f761361385a574d98a637d193de7edec03c1a1711053d5573c94a450ac943` |
| `tests/n6_a_remeasure_aq_execute_v3_1_test.py` (v3 합성 테스트 + 면제 테스트 3개) | `c67fdc78830361853bf977453d099432653714228ebde8ee7ffe506b8935eb1a` |
| `runs/n6-a-remeasure-2026-10-25.noindex/aq-exec/validation-v3_1-20261026/validate-only-2.json` | `dc4d63932c7d9340d487105d20abb9e5f0f86dddda8ae03c05b9cbd758c88669` |

## 검사

- `py_compile`과 Python 합성 테스트 37개를 nice 19로 돌렸고 모두 통과했다. cargo는 실행하지 않았다.
- 실제 상태로 validate-only를 돌린 결과는 `valid`다.
  - 입력 13개를 확인했다.
  - 엔진별 요청 수: Pass A 123, Pass B 60, 나머지 147
  - 소스 오류 0
- 프로토콜 파일은 바꾸지 않았다.

## 실행 명령

```sh
cd /Users/miiz/Desktop/kwzzzz_zkfr
caffeinate -dimsu python3 -B scripts/n6_a_remeasure_aq_execute_v3_1.py --action execute --no-new-revision-after 2026-10-28T15:00:00Z
```

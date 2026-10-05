# C-01 정상 경계 재사용 준비 점검 결과

2026-10-02 · 담당 miiz · `c01-normal-boundary-readiness-report-v1`

**부분 완료. 기존 NB-01의 지원 범위와 합성 회귀만 확인했고, 요청된 production 전체 호출 위치·신호 매핑 및 정상 경계 재실행은 수행하지 않았다.** 인계에서 상세 매핑은 알려진 결함 후보의 production entrypoint 투영에 연결된다. 이 대상별 연결 구현은 제공할 수 없는 수행 범위라 진행하지 않았다. 이는 자료가 없거나 도구가 실패했다는 뜻이 아니다.

| 요청 대상 | 전체 호출 위치 분모 | 정상 입력·witness 가용성 | production 정상 비교 | 이유 |
|---|---|---|---|---|
| `Subtract()` | unknown | unknown | not_run | 대상별 호출/신호 매핑 미수행; 해당 자료 내용 미조사 |
| `IntDiv(40)` | unknown | unknown | not_run | 대상별 호출/신호 매핑 미수행; 해당 자료 내용 미조사 |

두 template 구성을 호출 위치 2개로 세지 않는다. production 위치별 성공·실패·미지원 수와 성공률은 산출 불가다. 결측이나 최적화 소실을 실제로 관측한 것도 아니므로, 모든 위치가 자료 부족으로 미지원이라고 주장하지 않는다. 전체 위치가 아직 열거되지 않았다는 한계를 그대로 남긴다.

## 이번에 실제 수행한 검증

합성 회귀 실행 전에 [SCOPE](SCOPE.md)를 고정했고 코드·테스트·관련 문서 hash를 [baseline](../../runs/c01-normal-boundary-readiness-2026-10-02/baseline-v1.json)에 남겼다. 해당 범위는 후보·production witness 재실행의 승인이 아니다.

| 기존 회귀 | 통과 / 실패 | 실제 subprocess wall |
|---|---:|---:|
| `tests/normal_boundary_replay_test.py` | 15 / 0 | 0.129890458초 |
| `tests/normal_boundary_replay_label_independence_test.py` | 1 / 0 | 0.128923333초 |
| 합계 | 16 / 0 | 0.258813791초 |

원문 로그·명령·종료코드·해시는 [test-results-v1.json](../../runs/c01-normal-boundary-readiness-2026-10-02/test-results-v1.json)에 있다. 이는 기존 비보안용 합성 metadata 회귀의 재실행이다. 새 회귀나 매핑 코드를 구현하지 않았고, compiler·계산기·실제 회로를 실행하지 않았다. 실제 정상 fixture의 45경계 실행도 반복하지 않았다. 비용은 위 subprocess 구간만이며 문서 확인·소통·보고서 작성과 사람의 실제 작업시간은 측정하지 않았다. production 준비·정상 검증 시간은 미실행이므로 unknown이다.

## 기존 구현에서 확인한 지원 범위

| 항목 | 코드·회귀에서 확인한 사실 | production 적용의 한계 |
|---|---|---|
| 반복 호출과 컴파일 공유 | 각 호출 prefix의 입력을 따로 읽고 경계를 따로 기록하며 동일 구성의 컴파일만 재사용 | 이 구조가 요청 대상의 모든 호출 위치를 실제로 찾았다는 증거는 없음 |
| 입력 공급원 | 원본 calculation·constraint·export가 모두 passed일 때 해당 prefix의 입력만 읽음. 출력은 입력으로 쓰지 않음 | 정상 witness 출처·원본 대응이 별도로 확보돼야 함 |
| 인터페이스 | `in/out`, scalar 또는 연속 1차원 배열 1–8요소 | 임의 포트 이름·다차원·더 큰 배열에 대한 일반 mapping 미구현 |
| 결측·소실·모호성 | 누락, 음수/범위밖 wire, shape 불일치, 중복 symbol을 unsupported로 보존하고 부분 입력 payload를 반환하지 않음 | 최적화로 제거된 신호 복원은 없음; production에서 무엇이 소실됐는지 이번에 조사하지 않음 |
| 출력 비교 | 두 witness 검증 gate가 필요하며 matched·mismatched·unsupported leaf를 따로 유지 | 정상 출력 일치만으로 후보 입력 도달성이나 악의적 할당 투영을 보장하지 않음 |
| fixture 이름·경로표 독립성 | 이름과 선언 경로표를 바꿔도 입력은 discovery prefix/assignment에서 나오며 경로표는 분모 보존에 사용 | production에 대한 새 대응키·중첩 경로표를 제공한 것이 아님 |

출처는 [기존 정상 경계 코드](../../scripts/measure_normal_boundary_replay.py), [경계 회귀](../../tests/normal_boundary_replay_test.py), [독립성 회귀](../../tests/normal_boundary_replay_label_independence_test.py)다. 별도 읽기 전용 코드 점검도 위 지원 범위와 한계를 확인했다.

[NB-01 과거 보고서](../n4-1-normal-boundary-replay-2026-10-02/REPORT.md)는 기존 정상 fixture 세 개에서 고유 호출 위치 **7/5/3개**, wrapper 컴파일 구성 **7/3/2개**, 원본 입력 **9개**, 호출 위치×입력 **45개**의 성공을 기록한다. 이는 과거 O0 정상 fixture 결과이며 이번 production의 분모나 새 실측 성공으로 가져오지 않는다. 기존 원본·도구 hash도 당시 보고서/조건 기록의 provenance로 보존했으며, 이번 production 자료를 재검증한 hash라고 쓰지 않는다.

## 남은 조건과 보존

C-01 전체를 완료하려면 대상별 전체 호출 위치의 독립 열거, source/plan/컴파일 산출물 일치, 호출별 원본 신호와 wrapper 경계 대응, 정상 입력·검증 witness provenance와 정상 실행 결과가 필요하다. 이번에는 이 부분을 수행하지 않았으므로 후보 투영 장애의 실제 위치나 최적화 소실 목록도 unknown이다. 후보 도달성·entrypoint TCCT·프로젝트 결함을 판정하지 않는다.

기존 고정 문서·코드·회귀 12개 파일은 시작 hash와 일치한다. 새 파일은 이 부분 보고서 디렉터리와 ignored 작업 기록이고, 계획은 C-01 행만 갱신했다. S-05 영역과 후보 JSON은 열거나 수정하지 않았다. 코드/테스트 변경이 없어 cargo fmt·clippy·cargo test를 이번 작업에서 새로 수행하지 않았다. 새 퍼징·후보 재현·held-out 실행·commit/push/PR은 없다. N4-1 전체·N5는 완료 처리하지 않는다.

## 값 없는 근거

| 자료 | SHA-256 |
|---|---|
| [SCOPE](SCOPE.md) | `d0c53e1a169b27721357a0c92839c94f19c0505131f5739ee083750bd27c5d7d` |
| [evidence](evidence.json) | `cb4ec28f0c6442880b8782933932d4ca154e5260d82457d2da6044f913df912f` |
| [회귀 실행 기록](../../runs/c01-normal-boundary-readiness-2026-10-02/test-results-v1.json) | `6767fc8219292ad7b68ee8b0db25aeef37f74f90ded067ec0c71556af759a0d5` |

연결된 실행 기록에는 로그 path/hash와 실제 소요 구간을 포함하며 원시 값은 공유 문서에 넣지 않는다.

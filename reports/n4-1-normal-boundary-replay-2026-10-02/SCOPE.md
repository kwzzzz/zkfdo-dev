# NB-01 정상 경계 입력 연결 범위

2026-10-02 · 담당 miiz · `normal-boundary-replay-v1`. [인계](../../docs/next_step_handoff_2026-10-02.md)의 구현 담당 범위만 수행한다. 목적은 NC-01의 fixture별 수동 입력 공식을 검증된 원본 witness의 직접 입력 연결로 대체하는 것이다.

| 기존 대상 | 옵션 | 고정 입력 ID | 원본 입력 조건 | 호출 위치×입력 |
|---|---|---|---:|---:|
| 기존 discovery fixture | O0 | scalar-0, scalar-2, scalar-7 | 3 | 21 |
| 반복/상이 파라미터 산술 통제 | O0 | scalar-0, scalar-2, scalar-7 | 3 | 15 |
| 작은 배열 통제 | O0 | vector-zero, vector-small, vector-mixed | 3 | 9 |
| 합계 | | | 9 | 45 |

원시 입력·기존 소스 해시와 호출 위치 분모는 실행 전에 [input-plan.json](../../runs/n4-1-normal-boundary-replay-2026-10-02/run-v1/input-plan.json)에 기록했다. NC-01의 고정 소스와 입력을 바이트/값 그대로 사용한다. 호출 위치 목록은 빠진 실행을 분모에 남기는 용도이며 입력 값이나 경로별 식을 공급하지 않는다. 도구·새 측정 코드 해시는 실행 전 conditions.json에 기록한다. 이전 소스·보고서·실행·판정·측정 코드는 보존한다.

- 기존 자동 discovery/wrapper 생성과 O0 컴파일을 사용한다. 동일 구성 컴파일만 재사용하며 각 호출 위치의 입력과 wrapper witness는 별도로 생성한다. fixture나 호출 경로별 offset/예외식, 이전 adapter, 원본 출력은 입력 공급원으로 쓰지 않는다.
- 원본 정상 계산·전체 witness 제약 검사·export가 모두 성공해야 입력 연결을 진행한다. 입력 값은 원본 `.sym`의 해당 호출 위치 `in`에서만 읽고, wrapper에 입력 JSON만 전달한다. 새 계산기가 생성한 wrapper witness도 전체 제약을 검사한다.
- 지원은 `in/out` scalar 또는 1차원 배열(1–8 요소)로 한정한다. wrapper `.sym`의 모양과 `snarkjs r1cs info`의 입력/출력 개수를 대조하고 원본 호출 위치의 정확한 이름 집합과 비교한다. 현재 fixture에서 실제 실행하는 배열 길이는 2/3이다. 범용 parser/인터페이스 체계·최적화 역복원은 만들지 않는다.
- 결측·음수/범위 밖 index·shape 불일치·중복 이름/호출 위치·모호한 대응은 미지원 사유로 남긴다. 상위 단계 실패/미완료는 하위 검사를 실행하지 않은 이유로 남기고 9/45 분모에서 제외하지 않는다. 서로 다른 이름이 동일 wire를 가리키는 명확한 alias 자체는 모호성으로 간주하지 않는다.
- 입력 출처 연결과 wrapper witness에서의 입력 재확인은 같은 값의 전달 검증이다. 출력은 wrapper 정상 계산에서 새로 얻고 원본 출력 경계와 별도로 비교한다. 양쪽 전체 witness 제약 검사가 성공하지 않은 출력 일치를 성공으로 세지 않는다.
- 준비(discovery·컴파일·인터페이스 확인), 원본 계산/검사/export, 입력 연결, wrapper 계산/검사/export, 입력 재확인/출력 비교를 각각 계측한다. source/tool snapshot·버전·보고·최종 hash·회귀 검사는 제외한다. 조건별 1회이며 OS cache는 비우지 않는다. 시간 차이로 성능 우위를 주장하지 않는다.

세 fixture의 9/45 사전 조건을 모두 설명하고 필요한 회귀·필수 검사와 최소 변경 영향 조건 확인이 끝나면 종료한다. 원시 값은 ignored `runs/n4-1-normal-boundary-replay-2026-10-02/`에만 저장하며 보고서는 경로·해시·상태·시간만 남긴다. 검토 담당 파일·record/aggregate·원고는 수정하지 않는다. 수동 wrapper·새 예제·O1·후보 생성·퍼징·후속 평가로 확장하지 않는다.

N4-1 전체 미완료·N4-2 미착수·N5 미고정을 유지한다. N4-1 작업 상한 12시간과 과거 담당자 사용시간 unknown을 보존하고, 이번에 관측 가능한 구간/도구 wall만 기록한다. 이를 사람의 active-work 시간이나 잔여 예산으로 바꾸지 않는다.

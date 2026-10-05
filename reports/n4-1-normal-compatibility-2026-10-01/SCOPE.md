# NC-01 정상 호환성 실행 범위

2026-10-01, 담당 miiz, 버전 `normal-compatibility-v1`. [인계](../../docs/next_normal_compatibility_2026-10-01.md)의 한 질문인 O0/scalar 정상 대응의 O1·작은 배열 지원 경계를 확인한다. 기존 정상 실행·코드 v1을 보존하며 새 하네스·출력만 사용한다.

## 실행 전에 정한 6조건

| 조건 | 대상 | 옵션 | 사전 정상 입력 ID |
|---|---|---|---|
| 1 | 기존 정상 discovery fixture | O0 | scalar-0, scalar-2, scalar-7 |
| 2 | 같은 fixture | O1 | 같은 3개 |
| 3 | 기존 반복/상이 파라미터 산술 통제 | O0 | scalar-0, scalar-2, scalar-7 |
| 4 | 같은 통제 | O1 | 같은 3개 |
| 5 | 작은 정상 배열 통제 | O0 | vector-zero, vector-small, vector-mixed |
| 6 | 같은 배열 통제 | O1 | 같은 3개 |

입력 원문과 조건 순서는 실행 전에 생성한 ignored [input-plan.json](../../runs/n4-1-normal-compatibility-2026-10-01/run-v1/input-plan.json)에 고정했다. 하네스가 이 파일의 SHA-256을 검증하고 조건·입력을 변경하지 않는다. 값 없는 근거에도 같은 hash를 기록한다. 기존 두 소스는 이전 실행과 동일한 바이트를 사용한다.

배열 통제는 `VecStep(n,k)`의 길이 n인 `in/out`과 원본 길이 3 입력/출력만 둔다. 원본 main에서 `(2,2)` 두 호출과 `(3,3)` 한 호출을 모두 연결한다. 요소별 제곱과 상수 덧셈만 사용하며 결함을 넣지 않는다. scalar/1차원 배열·길이 1–8까지의 명시된 인터페이스만 처리하고 범용 타입/최적화 역복원은 하지 않는다.

## 실행·판정 규칙

- 각 조건마다 기존 자동 `targets --no-validate`로 탐색·wrapper를 생성한다. 실패/미지원도 조건표에 남기며 수동 wrapper로 바꾸지 않는다.
- 원본과 wrapper는 동일한 해당 `--O0` 또는 `--O1`, `--r1cs --wasm --sym --inspect --prime bn128`로 실제 컴파일한다. 조건 내 동일 컴파일 구성만 재사용하고 조건 간에는 새 디렉터리·빈 application cache다. 순차 1회씩 실행하며 OS cache는 비우지 않는다.
- 원본과 모든 호출 위치의 wrapper는 사전 선언한 정상 입력 어댑터로 계산하고 생성 witness 전체를 `snarkjs wtns check`로 검사한다. 어댑터는 O0/O1에서 같으며 작은 fixture의 연결식을 따르는 테스트 입력일 뿐, 사라진 신호의 값이나 대응을 복원하는 근거로 쓰지 않는다.
- boundary 대응은 discovery의 호출 위치와 `.sym`에서 직접 확인되는 witness index만 쓴다. 입력·출력의 모든 scalar/array 요소가 확인되고 일치해야 전체 경계 성공이다. 소실 index=-1, 없는/범위 밖 신호, 배열 shape 불일치는 이유와 전체 분모를 보존한다. 출력만 일치하면 부분 관측이지 전체 성공이 아니다.
- compile / normal calculation / constraint check / boundary correspondence를 별도로 기록한다. 계산·제약 검사가 성공해도 경계가 미확인이면 조건은 미지원이다. 실제 도구 오류·확인된 불일치는 실패다. 가능한 다른 인스턴스/입력 검사는 계속하며 해당 실패를 숨기지 않는다.
- 준비 wall은 자동 탐색·wrapper와 원본/필요 wrapper 컴파일까지, 정상 검증 wall은 계산·제약 검사·export·경계 비교 구간이다. 소스/도구 snapshot과 버전 조회·최종 hash/보고는 별도다. 이번 목적은 호환성이며 시간 차이를 성능 우위로 해석하지 않는다.

원시 자료와 도구 ledger는 ignored `runs/n4-1-normal-compatibility-2026-10-01/run-v1/`에 둔다. 오프라인 기록/집계 코드는 사용·수정하지 않는다. 기존 v1 파일은 hash로 보존 확인하며 공통 계획은 N4 행만 수정한다. D2·원고 파일은 수정하지 않는다.

6조건의 성공/실패/미지원을 설명하고 최소 변경의 회귀 검사와 필요한 재확인이 끝나면 종료한다. O2·추가 프로젝트·새 분석 기법·결함 후보 생성·퍼징으로 확장하지 않는다. N4-1 전체 미완료·N5 미고정을 유지한다. N4-1 작업 상한은 12시간이며 이전 담당자 작업시간 누계는 계측되지 않았으므로 unknown으로 보존한다. 이번 실행의 시작/종료·실제 도구 시간은 별도로 남기며 사람의 사용 시간으로 환산하지 않는다.

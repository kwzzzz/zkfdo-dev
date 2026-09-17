# Candidate validation evidence

이 디렉터리는 dev3 정적 랭킹 파일럿의 backend 후보를 원본 component 기준으로
사후 검증한 자료를 보존한다. backend 후보 수를 유효 결함 수로 직접 해석하지 않는다.

주 지표의 최소 조건은 다음 세 가지다.

1. component의 입력 전제를 만족한다.
2. 고정한 수정 전 원본 component의 모든 제약을 만족한다.
3. 평가 전에 명시한 기능 또는 보안 속성을 위반한다.

프로젝트 entrypoint와 caller까지 확인된 결함은 별도 지표로 기록한다. 탐색 예산과
사후 검증 비용도 분리한다.

## 보존된 검증

| 자료 | 확인 범위 | 판정 |
|---|---|---|
| [XorWords 독립 검수](xorwords-independent-review-2026-09-15/REVIEW.md) | 기존 후속 검증의 출처·신호 대응·35개 원본 제약 재계산 | 정확한 대입 거부: 35개 중 2개 위반 |
| [Add32Bits 후보 검증](add32bits-component-check-2026-09-15/REPORT.md) | 결정적으로 선택한 후보 1건과 수정 전 원본 component | 정확한 대입 거부: 2개 중 1개 위반 |
| [RotateLeft fixture 충실도](rotateleft-fixture-fidelity-2026-09-15/REPORT.md) | `RotateLeft32Bits(3)` fixture와 고정 원본의 제약 비교 | 대응 범위에서 제약 보존 확인 |
| [RotateLeft 후보 검증](rotateleft-candidate-check-2026-09-17/REPORT.md) | 결정적으로 선택한 후보 1건과 고정 원본 component | 원본 제약은 만족하나 32-bit 입력 전제 실패 |

현재 이 검증들에서 원본 component의 유효 고유 결함으로 집계된 건수는 0이다.
이는 원본 component가 안전하다는 뜻이 아니며, 검사하지 않은 후보 전체나 랭킹 전략의
성능으로 일반화하지 않는다.

컴파일 산출물(`*.r1cs`, `*.sym`)과 독립 검수용 전체 작업 복사본은 저장소에서 제외한다.
보고서에 기록한 고정 소스와 재계산 스크립트로 다시 생성할 수 있다.

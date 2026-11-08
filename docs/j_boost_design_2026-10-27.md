# J 보강 1차 설계 조사 — 2026-10-27

상태: 설계 조사 및 자체 반박 반영 완료(2026-10-27). 담당: miiz. 현재 v2.3 개발 코드 읽기와 선행연구 조사만 수행했다. S4c/4d 추가 작업과 4e는 진행하지 않았다.

이번 요청의 단일 문서 범위를 따라 진행 기록도 이 파일에 둔다. 기존 계획표·코드·실행 기록은 수정하지 않는다.

## 0. 중심 질문과 설계 판단

**판단: J 보강으로 연구의 중심을 옮기는 방향은 타당하다. 다만 최초안의 ‘가정 출처 + core + 부모 제약 추가’만으로는 충분한 기여가 아니다.** 평가 기준은 일정이 아니라 문제의 중요성, 선행과의 기술적 차이, 결론의 건전성, 비용 대비 추가 해결 능력이다. 이번 수정은 **동일한 위반 조건을 보존하는 반례 재합성과 원본 witness 완성**을 중심으로 한다. ScaleCirc와 다르게 보이려고 기능을 더하는 것이 아니라, 계산된 내부 입력에서 구체 반례 전파가 막히는 문제를 해결하려는 설계다.

**같은 호출 위치의 같은 위반 조건을 유지하면서, S 후보의 구체적인 중간값을 다른 값으로 바꾸면 원본에서 검증되는 위반을 찾거나 해당 조건을 배제할 수 있는가?** 이것을 경계 가정 추적·선택적 맥락 확장으로 시험한다. 타원곡선 부품 이름별 예외는 두지 않는다.

출발 수치는 **사용자가 제공한 A 집계이며 이번에 재집계하지 않았다.** aq-024 제외 4리비전·53요청, 2,921클래스 중 제외 2,154(원뿔 1,836·상수 144·구성 입력 기준 국소 반박 174), 미판정 767(예산 소진 703·주입 실패 42·합성 timeout 11·모델 재현 실패 11), L1 0이다. 703/767은 약 91.7%다. 클래스 횟수를 독립 결함 수로 세지 않는다.

설계상 중요한 교정은 세 가지다.

- 현재 닫힌 원뿔은 **후보가 정한 값만 고정**하고 다른 경계는 자유변수로 둔다([mod.rs:2854](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2854), [synth.rs:245](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/synth.rs:245)). 임의 기준값을 고정하는 주된 곳은 경로 역합성과 `repair`다. `synth.rs` 첫 주석의 “off-cone frozen”보다 실제 구현을 기준으로 한다.
- 후보 값은 **정확한 후보 재현 문제에서는 필수 조건**이다. 값을 풀 때는 별도의 ‘위반 술어 탐색’ 문제로 전환하고 원래 후보 판정을 보존해야 한다. 이미 `LessThan`에는 후보 값 없이 탐색하는 경로가 있다([predicate.rs:479](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/predicate.rs:479)). 값 해제 자체를 새 기여로 세지 않는다.
- `budget_exhausted`는 공유된 배제 탐색 예산 소진을 나타낸다. 실패한 계산의 본래 원인은 `cause_before_budget`, `b_outcome`, `injection/repair`에 있다. 작은 제약 묶음도 유한체 비선형식 때문에 어려울 수 있다. 703건이 모두 ‘임시 고정 때문에 실패’했다거나 모두 해결 가능하다는 결론은 아직 없다.

**반례의 값을 바꾸려면 위반 술어가 먼저 정의되어야 한다.** 현재 `repair::Predicate`는 `LessThan` 전용이다([repair.rs:70](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:70)). 일반 TCCT 후보를 받으면 자동으로 후보 독립 술어가 생기지 않는다([mod.rs:724](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:724), [mod.rs:1033](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1033)). aq의 703건에 적용할 수 있는 술어가 없으면, 경계 선택기를 개선해도 그 집단을 해결했다는 결과는 낼 수 없다.

## 1. 값 고정·선택 제한의 현재 위치

아래는 `lifting` 실행 경로의 값 대입·고정·보호·검색 가지 제한을 함께 정리한 목록이다. **원본에서 유도된 사실 / 질의가 정한 조건 / 탐색 선택**을 구분한다. 전역적인 `Assumption` 출처 구조는 현재 없다.

| 위치(file:line) | 고정 또는 제한 | 성격·현재 기록 |
|---|---|---|
| [mod.rs:1585](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1585), [mod.rs:1763](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1763) | 선형 등식의 상수·별칭, 후보와 상수 비교 | 원본 제약 유래. `InputBinding.kind`, O0/O1 근거는 남으나 등가류의 전체 유도 제약·가정 의존 그래프는 없음 |
| [mod.rs:1755](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1755), [mod.rs:1799](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1799), [mod.rs:1995](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1995) | 후보 입력을 직접 main 입력에 대입하거나 중간값 target으로 보관·pin | 정확한 후보 질의의 조건. 원본이 강제한 상수는 아님. 직접/중간 연결 종류만 기록 |
| [mod.rs:1974](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1974), [mod.rs:2816](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2816), [mod.rs:3108](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3108) | 기준 입력 복사 후 일부 leaf만 변경 | 나머지 입력은 탐색 기본값. `input_origin`, 변경 입력명은 있으나 그대로 남긴 값의 이유는 없음 |
| [synth.rs:158](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/synth.rs:158), [mod.rs:2828](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2828) | 경로 밖 신호는 현재 witness 값, 성공한 상위 입력은 다음 경로에서 고정 | 탐색 선택. 새로 푼 값도 그 선택에 조건부. 경로 수·시도 수·변경명만 기록 |
| [mod.rs:2665](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2665), [mod.rs:2786](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2786) | 후보 부품 내부와 pin을 역합성에서 보호 | 정확한 후보 보존을 위한 검색 제한. 값 해제 시 이 보호도 새 목표에 맞춰 바꿔야 함 |
| [mod.rs:2854](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2854), [mod.rs:2872](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2872) | 직접 입력·중간 target·TCCT 부품 입출력 경계값 고정 | 정확한 후보/경계 질의 조건. 배제 제약·고정 신호명은 기록; 일반 위반 배제는 아님 |
| [synth.rs:249](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/synth.rs:249), [synth.rs:526](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/synth.rs:526) | 나머지 wire 자유화, 고차수 wire 확장 중지; 인코더의 누락 fixed는 기본 0 | 고차수 wire를 기준값으로 고정하는 코드는 아님. 누락 0은 정상 cone 불변식상 불필요한 fallback이므로 새 인코더에서는 누락 오류로 처리; wire 0=1은 체 표현의 상수 |
| [mod.rs:2944](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2944) | abort 진단 때 모든 기준 main 입력 고정 | 조건부 진단. 코드도 `abort_instance`로만 기록하며 일반 배제에 사용하지 않음 |
| [mod.rs:1254](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1254), [mod.rs:1477](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1477), [repair.rs:898](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:898) | hint 결과를 후보 상수로 주입, 해당 인스턴스 입력값·배열 인덱스가 같은 경우만 발동 | witness 생성용 선택/후보 재현 장치. 원본 R1CS 사실 아님. 소스 위치·신호·절 수는 기록, 발동 조건별 실제 일치 여부는 없음 |
| [mod.rs:3343](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3343), [repair.rs:1732](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1732), [repair.rs:1761](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1761) | 모델에 없는 hint key는 현재 witness 값; key 변경 시 이전 hint를 제거/재선택 | 검색 상태. key 갱신은 이미 있음. 값별 모델/기준값 출처는 저장하지 않음 |
| [repair.rs:1445](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1445), [repair.rs:589](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:589) | repair unknowns 밖은 assigned 또는 현재 witness 상수 | 임시 경계 고정의 핵심. 질의 파일은 남지만 상수 접기로 출처가 소실됨 |
| [repair.rs:1453](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1453), [repair.rs:1474](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1474), [repair.rs:1508](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1508) | pin·보호 부품·비허용 main 입력·hub를 확장/해제에서 제외 | 검색 정책. 일반 원본 사실 아님. `with_paths`, 크기·결과 정도만 기록 |
| [repair.rs:1574](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1574), [repair.rs:1584](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1584), [repair.rs:1691](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1691) | target 등식, 이미 시도한 control 차단, pin/보호부품 모델 적용 거부 | target은 질의 조건, 나머지는 검색 제한. 반복 차단은 이미 배제 질의에서 분리됨 |
| [mod.rs:3544](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3544), [mod.rs:3571](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3571) | 국소 반박에서 모든 공개·사설 main 입력 및 후보 site 신호 고정 | 기준 입력 조건과 후보 조건 혼합. 설명에 전체 입력 고정 사실은 남으나 개별 의존 추적은 없음 |
| [predicate.rs:165](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/predicate.rs:165), [bitrange.rs:169](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/bitrange.rs:169), [bitrange.rs:268](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/bitrange.rs:268), [refute.rs:124](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/refute.rs:124) | 증명된 상수·범위 전파, 고정값에서 유도한 단일 해, boolean 경우 분기 | 원본 사실 또는 **입력 가정에 의존하는 유도값**. 전자는 일부 제약 ID 보존, 후자는 가정 의존성이 값과 함께 전파되지 않음. 0/1 전체 분기는 임의 샘플링과 다름 |
| [predicate.rs:479](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/predicate.rs:479), [predicate.rs:988](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/predicate.rs:988) | 술어 탐색은 기준 입력에서 시작하나 targets/pin 없음; 술어 배제는 전 wire 자유+유도 범위 | 후보 독립 탐색·배제가 이미 존재. repair 안의 임시 경계 고정은 그대로 적용됨 |

v2.3은 [mod.rs:366](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:366)의 view 진입점이며 위 핵심 엔진을 공유한다. [view_v23.rs:372](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/view_v23.rs:372)의 0 초기화는 모든 raw wire 값이 채워졌는지 확인하는 후보 검증 배열이며, 미지 값을 0으로 탐색하는 정책이 아니다.

## 2. 미판정·국소 반박·주입 실패 경로

| 경로 | 발생 지점과 의미 |
|---|---|
| 역합성이 필요한 입력 | [mod.rs:1800](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1800) → [mod.rs:2006](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2006). 중간 입력을 발견하면 합성으로 넘김 |
| 합성 실패 | [mod.rs:2753](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2753)의 기준 실행 abort 분류, [mod.rs:3080](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3080)의 solver 결과, [mod.rs:3106](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3106)의 SAT 모델 재현·hint 수리, [mod.rs:3277](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3277)의 최종 원인 변환 |
| 예산 소진 | [mod.rs:1021](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1021)에서 요청당 sweep 20초 초기화, [mod.rs:1046](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1046)의 class 반복에서 공유, [mod.rs:3239](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3239)에서 차감, [mod.rs:3320](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3320)에서 앞선 원인을 보존하고 `budget_exhausted` 반환. 전체 J 요청의 20초 제한이라는 뜻은 아님 |
| repair 종료 | [repair.rs:863](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:863)의 진전 없음/순환/반복 상한, [repair.rs:773](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:773)의 도구·크기·불변식 오류. 검색 UNSAT도 일반 배제로 바꾸지 않음 |
| 술어 미판정 | [predicate.rs:454](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/predicate.rs:454)의 실패 검색 재사용, [predicate.rs:520](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/predicate.rs:520)의 미도달, [predicate.rs:558](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/predicate.rs:558)의 원본 검증 실패. class 결론과 별도 필드 |
| 국소 반박 진입 | 생성 abort [mod.rs:2177](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2177), 원본 witness 불만족 [mod.rs:2282](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2282) → `try_refutation` [mod.rs:3443](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3443) → `refute_view` → [refute.rs:44](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/refute.rs:44) |
| 국소 반박의 범위 결정 | [mod.rs:3586](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3586)은 site 입력이 모두 direct/constant이면 `local_constraint_refutation`, 아니면 `reference_input_refuted`로 정함. **다른 main 입력 고정의 불필요성까지 증명하는 검사는 없다.** 해당 증거는 우선 구성 입력 조건부로 보고, 일반 배제에는 그 밖의 임시 고정을 제거한 재질의가 필요 |

### 주입 실패 42건: 맥락 선택과 분리할 J 진단·수정 과제

코드로 확인한 직접 원인은 **관측 가능한 hint wire 값이 후보 값과 다르다**는 것이다([mod.rs:2489](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2489) → [mod.rs:2346](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2346)). 이 코드만으로 42건의 근본 원인을 하나로 확정할 수 없다.

| 원인 후보/진단 공백 | 위치 | 다음 수정 설계 |
|---|---|---|
| 중첩 hint의 입력 key 또는 인덱스 guard가 실제 값과 다름 | `plan_rewrites` [mod.rs:1255](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1255), `instance_key` [mod.rs:1500](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1500) | `InjectionCheck`에 statement ID·인스턴스·guard별 입력 대응·불일치 신호 ID를 남김. exact 모드에서는 해당 guard 재현을 추가 요구하고 실패 시 unknown 유지 |
| O1 관측 실패의 구분 부족 | [mod.rs:2322](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2322)는 `None`만 O0 재확인. `Some(carried=false)`는 바로 실패 | false도 O0에서 진단하되 O0/O1 대응·원본 제약 검사를 모두 요구. 불일치면 `mapping_disagreement`, guard가 꺼졌으면 `guard_not_reached` 등으로 구분; O0만 맞는다고 성공 처리하지 않음 |
| 모델·기준값으로 만든 key가 재실행 중 달라짐 | [mod.rs:3343](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:3343), [repair.rs:1718](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1718) | 이미 있는 key 갱신을 재사용하고 ‘예측 key/실제 key/값 출처’를 대조. predicate 모드에서는 새 입력에 맞춰 hint도 다시 선택 |

고정 guard를 무조건 제거하거나 `injection_not_applied`를 도달로 바꾸는 수정은 하지 않는다. 주입 진단·수정의 이득과 맥락 정제의 이득은 별도 절제 실험으로 분리한다.

## 3. 이미 있는 것과 추가할 것

### 기존 개발과의 연결 및 변경 범위

**현재 시스템을 기반으로 J의 탐색 제어를 보강한다.** S의 후보 생성·래퍼·매핑, 원본 자료 준비, J의 부분 풀이·상위 경로·hint 주입·진단·원본 검증이 전제 자산이다. 재사용 비율을 코드 줄 수나 퍼센트로 산정하지 않았으며, J 내부의 알고리즘 변경을 사소한 패치라고 부르지는 않는다.

| 범위 | 활용 방식 | 필요한 변경 |
|---|---|---|
| S/래퍼·후보·호출 위치 대응 | 기존 산출물을 J 입력으로 사용 | 이번 보강의 재설계 대상 아님 |
| 원본 R1CS·sym·구조 및 상위 경로 | 기존 인덱스·부모 연결·실패 위치 진단 재사용 | 제어기가 필요한 신호·관계를 선택하도록 연결 |
| 작은 부분 풀이·solver | 기존 유한체 인코딩과 실행 기반 재사용 | 경계 고정의 출처와 core 결과 전달 |
| 기존 `repair`와 hint 주입 | 기본 witness 생성·수리 경로로 유지 | 고정 해제, 관계 누적, 재현 실패 분류, 최종 검증 피드백 연결 |
| 후보/술어 구분 및 원본 검증 | 기존 목표와 검사기 재사용 | 목표 범위·의존 가정·새 정책을 결과/캐시에 명시 |
| witness 직접 완성 | 별도 확장안 | 모델 전체 적용·직접 저장·O0/O1 대응 및 검증 연결이 추가로 필요 |

**기본 보강안**은 기존 생성기와 `repair::apply`를 사용하면서, 출처를 추적하고 충돌/원본 실패에 따라 다음 부분 질의를 바꾸는 것이다. **직접 완성 확장안**은 모델을 기존 입력·hint 제어로 적용하는 과정의 손실을 별도로 다룬다. 앞선 설명에서 직접 완성을 전체 보강의 필수 전제처럼 묶은 점을 교정한다. 두 안은 같은 연구 질문 아래 비교하는 구현 변형이며, 후자는 모델 재현 손실에 대한 근거와 추가 해결 능력으로 채택 여부를 판단한다. 일정 때문에 분리하는 것이 아니다.

기본 보강만으로도 계산된 호출 맥락의 선택적 재합성을 시험할 수 있다. 다만 그것만으로 충분한 논문 기여가 되는지, 직접 완성이 더 필요한지는 단순 확장·전체 질의와의 비교로 판단한다. **코드를 많이 바꾸는 것 자체가 신규성의 기준은 아니다.**

| 현재 구현 | 추가할 차이 |
|---|---|
| 닫힌 원뿔·작은 branch 제안·배제 sweep: [synth.rs:216](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/synth.rs:216), [synth.rs:396](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/synth.rs:396) | 크기/깊이 확대만으로 새 방법이라 하지 않음. 어떤 고정에 의존해 막혔는지 기록하고 그 고정만 선택적으로 해제 |
| 실패 인스턴스·부모 입력 연결·상위 hint/main 입력 경로: [repair.rs:359](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:359), [repair.rs:453](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:453) | `alone → with_paths`의 두 단계 대신 가정 의존 충돌과 원본 검증 실패에 따라 경계·호출 관계를 반복 선택 |
| 진단 사본으로 실패 제약 특정·동시 수리: [repair.rs:1046](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1046), [repair.rs:1267](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1267) | 진단/원본 검증 결과를 다음 질의의 명시적 제약 집합과 출처에 연결; 진단 사본은 계속 증거에서 제외 |
| 과거 실패 제약 carry·반복 control 차단: [repair.rs:1553](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1553), [repair.rs:1941](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1941) | 현재 carry는 현재 값에서 만족하고 unknown과 겹치는 것만 선택하며 재시도 때 제거 가능. 보강 경로에서는 필요한 원본 관계를 누적하고, 검색용 차단과 증명용 제약을 별도 보관 |
| 후보와 술어 분리·인스턴스 공유: [predicate.rs:370](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/predicate.rs:370), [predicate.rs:479](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/predicate.rs:479) | `LessThan` 밖으로 같은 의미 조건을 표현할 수 있는 범위와 적용률을 명시; 기존 기능을 새 기여로 중복 계산하지 않음 |

### 자체 반박 후 남기는 연구 주장

| 반박 | 판단과 수정 |
|---|---|
| ScaleCirc도 하위 반례를 부모에 올린다 | 맞다. 분해·캐시·전파는 주 기여에서 제외한다. 비교 대상은 직접 연결 전파와 원래 backend로 돌아가는 경로까지 포함한다 |
| 가정 해제와 CEGAR를 붙인 것 아닌가 | 이 설명만으로는 약하다. 출처 필드·core·양방향 탐색 자체는 새 알고리즘으로 주장하지 않는다. **값을 바꾸어도 유지되는 위반 계약 + 계산된 경계의 공동 합성 + 전체 witness 완성 규칙**을 구현·비교할 단위로 삼는다 |
| `h ≠ RHS`이면 같은 TCCT 버그인가 | 일반적으로 아니다. 출력에 영향 없는 hint 자유도, 분모 0, 다른 피연산자의 변경을 잘못 세기 쉽다. 최초안의 자동 TCCT 술어 추출 제안은 철회한다 |
| 703건은 timeout인데 core가 무슨 도움이 되는가 | core는 UNSAT에만 유효하다. 703건의 효과 근거로 삼지 않는다. 잔차 기반 관계 추가와 core 기반 고정 해제는 서로 다른 실패를 다룬다 |
| 모델이 재현되지 않으면 부모 제약만 더 넣으면 되는가 | 아니다. 기존 수리는 모델 중 main 입력/hint만 적용하고 다시 생성한다([repair.rs:1680](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1680), [repair.rs:835](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:835)). 모델을 적용하다 잃는 실패와 원본 제약 부족을 구분해야 한다. **모델 값을 보존한 전체 witness의 직접 완성 경로**를 별도 확장안으로 설계한다 |
| 전체 SMT 또는 경계를 한꺼번에 풀면 같은 일 아닌가 | 무제한으로 모든 관계를 포함하면 같은 논리 문제다. 차이는 같은 예산에서 필요한 관계·값만 공동으로 다시 풀어 검증된 결론을 얻는 비용이다. 간단한 경계 전부 해제·너비 우선 확장도 필수 비교군이다 |

**주 기여로 발전시킬 주장:** 로컬 반례의 특정 값을 역산하는 데 고정되지 않고, 명시된 위반 조건을 유지한 채 원본 호출 맥락에 맞는 반례를 다시 합성한다. 임시 경계값의 충돌과 원본 제약의 잔차를 서로 다른 피드백으로 사용하여 필요한 신호·관계를 공동으로 풀고, 완성 witness 또는 정확한 범위의 배제를 반환한다. 기존 J의 후보/술어 구분을 출발점으로 삼되, 그것 자체를 새 발명으로 다시 세지 않는다.

**현재 근거의 강도:** ScaleCirc의 검토한 전파 경로와 구별되는 구체적 설계가 있다. 이 방법이 새로운 검증 원리이거나 선행보다 우수하다는 결론은 아직 없다. 좋은 논문으로 발전하려면 일반적인 CEGAR/부분 풀이보다 이 제어 규칙이 왜 필요한지와 실제 추가 해결 능력을 보여야 한다.

## 4. 수정한 삽입 설계

### 4.1 고정해야 할 것은 위반의 의미다

`GoalSpec`을 [mod.rs:1839](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1839)의 맥락과 [repair.rs:85](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:85)의 요구에 연결한다.

- **정확한 후보:** `B_s(w,c)`는 기존 후보의 호출 위치·필요 신호값을 보존한다. 후보 값은 필수 조건이며 해제하지 않는다. 그 밖의 기준 입력·경계 고정만 풀 수 있다.
- **위반 조건:** `V_s(w)`는 같은 실제 호출 위치의 같은 의미 위반이다. 후보 값은 시작 선호값이 된다. 현재 지원은 `LessThan`의 기존 정수 비교 위반이다. 단지 ‘어떤 값이 달라짐’을 같은 의미 위반으로 바꾸지 않는다.
- **일반 TCCT:** S가 사용한 오라클과 일치하는 명시적 위반 관계가 있어야 한다. 계산 의미와 제약 의미를 비교하는 관계는 참조 계산·정의역·관측 출력을 포함해야 하며, `<--` RHS 문자열 추출만으로 만들 수 없다([source.rs:129](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/source.rs:129)). 그런 관계가 없는 후보는 exact 완성만 지원하고, 값 일반화는 `predicate_not_supported`다. 두 R1CS 해의 출력 차이를 사용하면 목표가 underconstraint인지 별도로 명시한다.
- **최상위 영향:** `V_s` 도달과 L1을 분리한다. TCCT L1은 같은 **공개·사설 최상위 입력 전체**에 대한 참조 계산과의 최상위 출력 차이 등 기존 오라클의 조건까지 검증해야 한다. 최상위 영향 T를 정확히 인코딩할 수 있으면 처음부터 `P=V_s∧T`인 별도 목표로 고정할 수 있고, 그렇지 않으면 V 검색 후 T를 검증한다. 참조 실행의 도구 오류/timeout은 의미 위반이 아니다. 위반 위치·다른 이탈 위치를 기록하되 하나의 결과를 독립 버그 여러 개로 세지 않는다.

술어 ID에는 리비전·entrypoint·실제 인스턴스·식/오라클 버전·입력 범위 `H`를 넣는다. 새로운 값을 찾은 결과를 기존 exact 판정에 덮어쓰지 않는다. 술어 확장 자체는 별도 작업이며, 이 설계가 일반 EC 의미를 이미 자동 복원한다고 주장하지 않는다.

### 4.2 세 가지 상태와 보장 범위

`R`은 원본 R1CS 전체, `P`는 위에서 고른 `B_s` 또는 `V_s`다.

- **증명용 질의 `U = C ∧ P ∧ H`:** `C`는 원본 제약의 부분집합과 무조건 정당화된 사실이다. 모든 원본 해의 해당 변수 투영은 `U`를 만족한다. `U`가 UNSAT이면 그 `P,H`에 대한 배제가 가능하다.
- **탐색용 질의 `Q = U ∧ A ∧ N`:** `A`는 기준값 등 임시 등식, `N`은 이미 시도한 제안의 차단이다. 빠진 제약과 임시 고정이 함께 있으므로 **`Q`를 원본의 순수 과대근사나 과소근사라고 부르지 않는다.** Q의 SAT도 UNSAT도 단독으로 원본 결론이 아니다.
- **완성 중인 전체 벡터 `w`:** 시작 witness 또는 진단 벡터에 부분 모델을 반영한 값이다. 원본 검사를 통과하기 전에는 유효 witness가 아니다. 확인된 witness만 원본 해의 증거로 보관한다.

`Assumption`에는 ID·wire/별칭·값·출처·유도 전제·생성 시점을 둔다. 출처는 `OriginalFact / ScopeCondition / CandidateValue / SearchDefault / Derived`다. `Derived`는 전제 가정의 합집합을 이어받고, 전제가 풀리면 재유도한다. 원본 사실과 H는 해제하지 않는다. 현재 [repair.rs:524](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:524)의 상수 접기는 symbolic 경계와 `a_i ⇒ w_i=v_i`로 바꾸어 core에 출처가 남게 한다. wire 0=1, 유한체 정규 범위는 필수다.

`RefinementState`는 `C, A, N, w`, 해제된 wire 집합, 실패 제약 ID, 모델 적용·검증 결과를 보관한다. 같은 wire의 별칭과 여러 호출이 공유하는 입력은 하나의 변수로 푼다. 개별 좌표/자식별 성공값을 서로 독립적인 것처럼 합치지 않는다.

### 4.3 제어 규칙: 충돌은 고정 해제, 잔차는 관계 추가

**두 구현의 공통 제어 규칙**이다. 모델의 적용 방식만 구분한다. 기본 보강은 기존 입력/hint 적용과 재생성을 사용하고, 직접 완성 확장은 모델 전체 벡터를 보존한다. 생성 후 모델과 달라진 값은 `model_reproduction_mismatch`, 원본 제약 불만족은 `failed_constraints`로 별도 피드백한다. 기존 호출자에서 반환된 최종 검증 실패도 총예산 안에서 다음 수리 질의에 연결한다.

1. **시작:** 목표 위치의 원본 부품 제약과 직접 연결을 `C`에 넣는다. 후보값을 바꿀 때는 기존 후보가 부품을 만족한다는 이유로 내부 제약을 생략하는 [synth.rs:237](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/synth.rs:237) 정책을 재사용하지 않는다. 아직 포함하지 않은 경계값은 출처 있는 `A`로 둔다. 기존 생성기·수리는 시작 벡터/제안 공급기로 재사용한다.
2. **Q가 UNSAT:** core 안의 해제 가능한 등식 묶음 하나를 푼다. 별칭 및 그 가정에 의존한 유도값을 함께 무효화한다. 선택 순서는 **새로 자유화할 신호의 인접 원본 제약 수 → 비선형 제약 수 → 안정적 wire ID**로 정하며 부품 이름을 사용하지 않는다. 여러 반복에서 오래 남은 충돌 묶음도 선택하여 싼 경계만 맴돌지 않는다. 최소 core/최적 해제 집합은 보장하지 않는다. `N`이 관여한 실패는 차단을 제거해 재질의하고, 해제할 가정이 없어도 배제 전에는 반드시 `U`를 확인한다.
3. **Q가 SAT:** 기본 보강은 기존 [repair.rs:1680](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1680)의 입력/hint 적용 후 생성된 벡터를 검사한다. 목표값을 재현하지 못하면 그 wire와 생성 관계를 다음 질의의 선택 근거로 남기며, 이를 원본 불가능의 증거로 쓰지 않는다. 직접 완성 확장에서는 **모든 질의 wire 값**을 원본 wire 공간의 전체 벡터 `w`에 반영하고 생성기로 덮어쓰지 않는다. 두 방식 모두 `P,H`와 원본 `R` 전체를 검사해야 한다.
4. **원본 잔차가 있으면:** 실패한 원본 제약 중 새 제약을 `C`에 추가한다. 실패 제약에 등장하는 현재 고정 경계는 일단 출처를 유지하고, 다음 UNSAT의 core가 필요성을 보이면 푼다. 선택은 변경 wire/목표에서 가까운 실패 제약 → 추가 변수 수 → 제약 ID 순이다. 실제 부모 입력 연결과 **형제·하위 소비자가 부과하는 제약도** 따라간다. 출처는 [repair.rs:307](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:307), [repair.rs:359](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:359), 잔차 ID는 [repair.rs:1100](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:1100)의 기존 기반을 활용한다. 소스 대입이 실제 R1CS에 없는 경우 이를 원본 제약처럼 추가해서는 안 된다.
5. **이미 C에 있는 제약이 적용 후 깨졌으면:** 같은 제약을 다시 추가해 해결했다고 하지 않는다. 기본 보강에서는 재생성으로 달라진 wire와 hint guard를 확인하고 기존 수리 경로에 되돌린다. 직접 완성 확장에서는 정확한 모델 반영이라면 발생할 수 없으므로 인코딩·wire 대응·상수 접기 오류로 분류한다. 원본 검사는 통과하지만 목표 오라클이 다르게 평가되는 경우도 목표 인코딩을 점검한다.
6. **timeout/unknown:** core를 만들지 않는다. 실제 잔차가 있으면 위 규칙으로 확장하고, 없으면 독립적인 일반 입력/경계 제안 0·1·`p−1`·증명된 구간 끝값을 제한적으로 사용한다. 이 선택은 검색용이다. 효과를 보장하지 않으며 본질적으로 어려운 유한체 역문제는 unknown으로 남긴다.
7. **진전·재사용:** `C`에 추가한 원본 관계는 누적하고, 풀었던 wire를 새 기준값으로 다시 pin하지 않는다. 부분 모델의 값도 다음 회차의 영구 조건이 아니다. `P,H`를 바꾸면 별도 질의다. 같은 상태 반복·추가 가능한 관계/고정 없음·자원 한도에서 종료한다. 기존 실패 캐시([predicate.rs:425](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/predicate.rs:425))가 새 탐색을 생략하지 않게 목표·정책·새 모듈 hash를 key에 결속한다([mod.rs:1005](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:1005)).

core는 UNSAT 증거에서만 얻고 최소성은 가정하지 않는다([Z3 공식 문서](https://microsoft.github.io/z3guide/programming/Z3%20Python/advanced/)). 이 순서 규칙의 비용 이득은 실험 가설이다. 무제한 확장하면 원본 전체 문제로 수렴하는 구조이지만, 제한된 예산에서 완전성이나 항상 더 빠른 탐색을 주장하지 않는다.

### 4.4 별도 확장안: 생성기와 원본 witness 검증의 역할 분리

이 절의 직접 완성은 기본 보강에 추가할 수 있는 구현 변형이다. 기본 보강의 시작 조건으로 요구하지 않는다.

현재 [repair.rs:846](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/repair.rs:846)은 생성된 witness가 요구를 만족하면 반환하고, [predicate.rs:908](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/predicate.rs:908)은 O1 생성기를 다시 실행한다. 새 완성 경로는 `ConstraintWitness`를 반환하고 **그 벡터 자체**를 검증하도록 별도 연결한다. witness 파일 쓰기는 현재 [wtns.rs:61](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/wtns.rs:61)의 테스트 전용 기반을 정식 경로로 올리는 작업이 필요하다.

- 단일 원본 O0 wire 공간에서 모델을 합치고, 원본 O0 R1CS 전체와 목표를 확인한다. O1로 전달할 때 모든 O1 wire·별칭·입력의 대응을 확인하고 원본 O1도 검사한다. 대응이 불완전하면 0으로 채우지 않고 unknown이다.
- 최종 `.wtns`를 기존 Rust 평가와 snarkjs 원본 검사에 모두 통과시킨다([mod.rs:2250](/Users/miiz/Desktop/kwzzzz_zkfr/src/candidate_review/lifting/mod.rs:2250)). 정상 생성기를 다시 실행하여 악의적 값을 덮어쓰지 않는다. 참조 생성기는 같은 최상위 입력에서 정상 출력/오라클을 얻는 데 사용한다.
- 원본 R1CS를 만족해도 **local V 도달만으로 L1은 아니다.** 최상위 영향 검증이 실패하면 local 도달로만 기록하고, 추가 검색은 별도 검색 차단으로 진행한다. 생성기 오류를 최상위 의미 위반으로 인정하지 않는다.
- 기존 주입 모드의 42건은 §2대로 따로 진단한다. 직접 완성 결과는 `constraint_witness`라는 별도 방법으로 기록하고, 주입이 실행된 것처럼 보고하지 않는다. 기존 판정 계약·동결 프로토콜은 이번 설계로 소급 변경하지 않는다.

이 변경의 이유는 현재 입력·hint 제어로 재생성할 수 있는 witness에 한정된 검색 범위를 넓히기 위해서다. 현재 J도 hint 주입으로 악의적 witness를 만들며, 정상 생성기만 사용하는 것은 아니다. **원본 R1CS가 허용하지 않는 중간값을 정당화하거나 역산 난도를 없애는 방법은 아니다.** ScaleCirc도 반례를 합치는 코드가 있으므로, witness 직접 조립 자체를 최초 기여로 주장하지 않는다. 차이는 값 일반화·경계 충돌·원본 잔차가 하나의 반복 완성 과정으로 이어지는 데 있다.

### 4.5 작은 논리 예시와 반례

다음은 실행하지 않은 설명용 `F₇` 회로다. 원본 관계는 `z=x²`, `q=(z−1)h`, 정상 hint 계산은 `h=0`이며, 같은 국소 위반은 `h≠0`, 최상위 영향은 `q≠0`으로 정한다. 이 예시의 검색 목표 P는 두 조건의 결합으로 처음부터 고정한다.

- 로컬 후보 `(z,h,q)=(3,1,2)`는 로컬 관계를 만족하지만 3은 F₇의 제곱이 아니어서 정확한 후보는 원본에 도달하지 못한다.
- 위반 조건을 보존하고 값을 바꾸면 `(x,z,h,q)=(3,2,1,1)`이 원본 두 관계와 최상위 영향까지 만족한다. 특정 `z=3`의 역산 실패와 같은 위반의 부재는 다르다.
- 기준 `x=1,z=1`을 고정한 검색은 막힐 수 있다. core로 관련 고정을 풀고, 조립 벡터의 `z=x²` 잔차에 따라 상위 관계를 함께 푸는 것이 제안 방법이다.
- 소비자가 추가한 원본 관계가 `h=0`이라면 해당 위반은 실제 배제된다. 정상 생성기의 `h=0` 계산을 원본 제약으로 잘못 추가하면 앞의 유효 반례도 지워진다.

이는 논리적 구별을 보여 주는 예시이며 ScaleCirc의 실제 실패나 aq 개선을 재현한 결과가 아니다.

### 4.6 종료와 논문에서 증명할 의무

**도달 건전성:** 완성 벡터의 원본 R1CS·목표·입력 범위 검사 통과, L1은 추가 최상위 오라클 통과. **배제 건전성:** 임시 고정·반복 차단을 제거한 `U`의 UNSAT와 원본에서의 함의 확인. **목표 보존:** 가정 해제/관계 추가가 `P,H`를 바꾸지 않으며 exact와 predicate 결론을 혼합하지 않음. 이는 설계상 증명 의무이고 현 구현의 새 보장을 이미 검증했다는 뜻은 아니다.

초기 자원 상한안은 정제 6회·일반 seed 8회·부분 질의 4,000제약이다. 상한은 방법의 의미가 아니라 실험 설정이며 A에서 정한 뒤 고정한다. 원본 전체 비교군에는 부분 제약 상한을 적용하지 않는다. 모든 solver·모델 반영·전체 잔차 검사·최종 검증·참조 실행 비용을 총예산에 포함한다.

## 5. 비교 설계 — 개발 A / 평가는 B와 새 대상

**이번에는 B를 열지 않았다.** A(aq·banyan·inference)는 진단·시제품 개발·회귀에만 사용한다. RQ-C 버그 위치 결과 개선을 J 보강의 효과로 주장하지 않는다. 최종 비교는 방법·설정·선택 규칙을 고정한 뒤 B와 새 대상에서 한다. B의 과거 집계 노출은 기록하고, 완전히 미노출인 새 대상으로 오해시키지 않는다.

| 비교군 | 같은 질의에서의 역할 |
|---|---|
| ① 현재 J(v2.3 개발 기준) | 현재 exact 판정과 지원되는 술어 탐색을 그대로 측정. 엔진 hash 고정 |
| ② 원본 전체 직접 질의 | 모든 원본 제약 `R ∧ P ∧ H`, 같은 solver/인코딩·목표·입력 범위. 임시 후보값은 고정하지 않음. 완전한 모델을 원본 witness로 검증 |
| ③ J 보강 | 같은 `P,H`로 가정 선택 해제·원본 실패 기반 관계 확장. **기존 생성/수리 경로를 쓰는 기본 보강**과 **직접 완성 확장**을 각각 측정. 준비·core·모든 검증 비용 포함 |

**ScaleCirc도 실제 비교에 포함한다.** 검토 리비전의 반례 전파와 원래 backend fallback을 끝까지 포함하고, 최종 witness는 공통 검증기로 검사한다. 같은 속성을 지원하는 층에서만 성능·해결 수를 직접 비교한다. UNDER와 `LessThan` 의미 위반은 같은 속성이 아니므로 한 표에서 우열로 합치지 않는다. 공통 술어 어댑터가 필요한 실험은 ‘수정한 ScaleCirc/backend’로 명시하고 동일 어댑터를 다른 비교군에도 준다. 지원하지 않는 속성은 지원 범위 차이로 보고하며 알고리즘 성능 패배로 세지 않는다.

현재 J가 지원하지 않는 일반 TCCT 술어에서는 ①의 exact 결과와 ②/③의 predicate 결과를 같은 결론인 것처럼 직접 비교하지 않는다. **공통 술어층(현재 `LessThan`)에서 3군을 우선 비교**하고, 신규 술어층에는 ①의 지원 여부·exact 결과를 별도로 보고한다. 신규 술어 어댑터를 붙인 기존 검색기와 ③의 추가 절제 비교로 ‘술어 지원 확대’와 ‘맥락 정제’의 효과도 나눈다.

- 단위: `(revision, entrypoint, 실제 instance, predicate ID, H)`로 중복 제거. 같은 인스턴스에 여러 후보/seed가 붙어도 고유 결론은 한 번 센다. exact 후보 비교는 candidate hash를 추가한 별도 표다.
- 크기: 원본 R1CS 기준 작은 회로 **≤1,000**, 중간 회로 **1,001–100,000제약**을 미리 층화한다(설계안). A의 banyan과 inference의 재현 가능한 개발 entrypoint/래퍼를 규모 확인 후 배치하고, 큰 aq 원본을 작은 조각 크기 때문에 ‘작은 원본’으로 표시하지 않는다. 적격 중간 개발 자료가 없으면 빈 층으로 남긴다. 최종 B·새 대상도 같은 크기 기준을 적용한다.
- 예산안: 공통 준비 산출물에서 시작하는 질의당 **작은 것 60초/중간 것 300초, 메모리 10 GiB**, 반복 3개·공통 seed·순서 교차. 클래스별 새 예산과 현재 J의 요청 단위 공유 sweep를 구분하고, 요청 총예산도 동일하게 제한한다. 냉/온 캐시를 섞지 않는다. 원본 준비 포함 총비용과 검색 비용을 모두 보고한다. 이 수치는 아직 평가 프로토콜이 아니다.
- 주 지표: 원본에서 검증된 **고유 L1 수**, 공통 predicate 단위 **unknown→검증 도달/정당한 배제 전환 및 역전 수**, 범위별 배제 수, 전체 wall time·프로세스 트리 peak RSS. 디스크·준비 실패·미지원·timeout도 분모와 함께 기록한다. L1은 공통 독립 검증층으로 확인하며 RQ-C 위치 일치를 성공으로 쓰지 않는다.
- 보장 범위는 `exact_candidate`, `predicate_under_H`, `predicate_all_allowed_inputs`, `reference_input_only`로 분리한다. 단순 상태 문자열 변경·조건부 배제의 재분류는 unknown 해결 실적으로 세지 않는다.
- 필수 절제/단순 경쟁안: **같은 P에서 경계를 전부 풀기**, 같은 예산의 **너비 우선 원본 관계 확장**, 기존 repair에 **직접 witness 조립만 추가**, core 선택 제거, 잔차 선택 제거, 주입 진단/수정만, 일반 seed만. 반복 횟수·총예산·목표 지원을 맞춰야 선택 정책의 이득을 주장할 수 있다.
- 추가 관찰: 임시 고정 UNSAT / 제약 누락 / 모델 적용 손실 / 진짜 solver 난도별 전환 수, 원본 대비 사용 제약 비율, 호출 경계를 넘은 수, core·전체 검사 비용. 동일한 원본 제약 검사 두 개는 건전성 확인 기반이지 별도 주요 발명으로 세지 않는다.

**연구 가설을 반박하는 결과도 미리 정한다.** (가) 정확한 후보 실패 후 같은 V의 검증된 다른 witness를 추가로 찾지 못하면 값 일반화의 효용은 지지되지 않는다. (나) 직접 완성만으로 동일 효과가 나면 core/맥락 선택을 주요 기여로 주장하지 않는다. (다) 전체 질의나 단순 확장이 같은 예산에서 우세하면 선택적 정제의 비용 우위를 주장하지 않는다. (라) 기존 `LessThan` 사례만 처리하면 일반 TCCT/EC 문제를 해결했다고 하지 않는다. 연구 방향의 타당성과 이 가설들의 실증 성공은 구분한다.

## 6. 제공될 개발 사례의 코드 대응

조사 시 `runs/j-dev-2026-10-27/classes-v1.json`과 `runs/j-dev-2026-10-27/cases/`가 없었다. 개별 사례 분석란은 비워 둔다. 다른 aq 판정 폴더·J 캐시·B에서 대체 자료를 찾지 않았다.

| 사례 ID | 현재 중단 지점(file:line) | 실패 전 원인·활성 가정 | 설계 반영 |
|---|---|---|---|

후속 자료가 제공되면 `cause_before_budget`, `b_outcome`, 마지막 solver/repair 결과, guard 불일치, predicate 복원 가능성부터 대응한다. 현재 703건의 개별 실패 유형·42건의 근본 원인·중간 크기 개발 사례 선정은 미확정이다.

## 7. 선행연구와 ScaleCirc 대비 위치

| 연구·확인 범위 | 겹치는 부분 | 구별할 부분·한계 |
|---|---|---|
| **Picus/QED², PLDI 2023**, [논문](https://veridise.com/wp-content/uploads/2025/01/Automated-Detection-of-Underconstrained-Circuits-for-Zero-Knowledge-Proofs.pdf), [공개 분할 안내](https://github.com/Veridise/Picus#mitigation) | 유한체 추론과 SMT, 수동 분할·출력 범위 추상화, 국소 반례와 전체 결함의 구별 | 우리 대상은 호출 위치에 고정된 명시적 위반의 맥락 내 재합성이다. 두 해의 비유일성만 사용하면 목표도 Picus와 겹친다. 새로운 일반 검증 원리로 포장하지 않음 |
| **ScaleCirc, ASE 2025**, [공식 초록](https://research.polyu.edu.hk/en/publications/scalecirc-scaling-the-analysis-over-circom-circuits/), [고정 리비전 코드](https://github.com/jinan789/ScaleCirc/blob/3d05d0f3e82816135419dba37dde91d48cb65068/ScaleCirc/utils_One_Template_Analysis.py#L1820-L2030) | 분해·재사용·constrainedness 전파와 실제 부모 반례 생성/조립. 소스 의미 활용·ZKAP 연결도 존재 | 검토한 전파는 저장된 자식 반례 쌍과 직접 부모 입력 대응을 사용한다. 제안 방법은 같은 V 아래 값을 다시 선택하고 계산된 연결·다른 소비자 제약까지 함께 풀며, 전체 잔차를 다음 완성 질의에 돌린다. 본문 전문 미확보이므로 논문 전체에 특정 기능이 없다는 단정은 유보 |
| **SMASH, POPL 2010**, [저자 공개 논문](https://patricegodefroid.github.io/public_psfiles/popl2010.pdf) | 호출 경계에서 도달/배제 정보를 필요에 따라 생성·재사용하고, 동적 탐색과 정적 분석을 교대한다. 양쪽 피드백 결합은 이미 선행 범위 | 우리의 Q는 may/must 요약 자체가 아니다. ZK의 원본 제약이 허용하는 악의적 witness를 보존하며 경계값·누락 관계를 다루는 구체적 알고리즘이 필요하다. ‘양방향’이나 ‘검증+퍼징’이라는 표현만으로 신규성을 주장하지 않음 |

기반인 [CEGAR, CAV 2000](https://www.cs.cmu.edu/~emc/papers/Conference%20Papers/Counterexample-guided%20Abstraction%20Refinement.pdf)의 가짜 반례 검증·정제 역시 선행이다. 이 문서의 새 설계는 그 원리를 ZK에 적용했다는 사실만으로 기여가 되지 않는다.

**ScaleCirc 코드 재대조:** 이전에 확보한 공개 소스의 SHA-256을 기존 검토 기록과 맞춘 뒤 다시 읽었다. `utils_One_Template_Analysis.py:1820`의 `check_UNDER_case`, `:1833`의 직접 연결 목록, `:1908`의 최대 20회 시도, `:1941`의 부모 출력 비교, `:2090`의 실제 호출, `:2093` 이후 fallback, `:4207`의 직접 입력 대응 기록을 확인했다. 공개 소스는 `/private/tmp/scalecirc-review-20261027/`에 있고 실행하지 않았다. 이 경로와 **반례의 값을 바꾸면서 원본 잔차/충돌에 따라 관계를 공동 합성하는 제안**은 구별된다. backend fallback이 같은 문제를 풀 수 있으므로 표현력 독점이나 탐지 우위는 여기서 결론 내리지 않는다.

**논문 중심 문장 초안:** “계산된 호출 입력 때문에 로컬 반례를 원본에 연결하기 어려운 ZK 회로에서, 위반 조건을 유지하며 반례 값을 재합성하고 원본 witness를 점진적으로 완성하는 방법을 제안한다. 임시 경계값 충돌과 원본 제약 위반을 구분하여 필요한 값과 관계를 공동으로 다시 풀고, 검증된 도달과 범위가 명시된 배제를 반환한다.” 이는 제안할 방법의 문장이고, 성능·신규성 입증이 끝났다는 문장이 아니다.

## 다음 단계: 시제품 범위와 작업량

일정을 설계의 채택 기준으로 삼지 않는다. 기본 시제품은 기존 생성/수리 경로 위에 목표·출처·선택적 정제·검증 피드백을 연결한다. 아래 작업량 표는 **직접 완성 확장까지 포함한 전체안**이다. 직접 완성을 시작의 선행 조건으로 삼거나 기본 보강의 효과와 합쳐 보고하지 않는다.

| 단계 | 범위·산출물 | 작업량 추정 |
|---|---|---:|
| 목표/원본 대응 | 기존 exact 및 `LessThan` P, H, 원본 wire/별칭 계약, 반례·배제 범위 확인 | 0.5–1일 |
| 직접 완성 | 모델 전체 반영, 원본 O0/O1 대응, witness 저장·두 검사기 검증, 참조 오라클 분리 | 1–2일 |
| 선택적 정제 | 출처 보존 인코딩, core 해제, 잔차 제약 누적, 진전·예산·캐시 | 1.5–2.5일 |
| 의미 회귀/비교 경로 | 생성기 재현 실패와 R1CS 불만족 구별, 단순 확장/전체 질의/기존 J 비교 준비, A 개발 점검 | 1–1.5일 |

합계 **약 4–7 작업일**은 집중 작업 1일 6시간을 가정한 공학적 추정이다. 일반 TCCT 오라클 변환·ScaleCirc 어댑터·최종 B/새 대상 평가는 별도이며 아직 견적을 확정할 수 없다. 최초 16–25시간 추정은 모델 직접 완성·대응 검증의 작업을 빠뜨렸으므로 철회한다. 개발 사례 부재는 설계 채택의 시간 제한이 아니라 703건에 대한 적용률·효과를 아직 판단할 수 없는 이유다.

필수 회귀는 (a) 임시 고정 UNSAT 후 해제 SAT, (b) 진짜 원본 제약에 의한 P 배제, (c) exact 후보 배제와 같은 V 도달 공존, (d) 부모뿐 아니라 공유 입력·다른 소비자의 잔차, (e) 모델 반영 손실/별칭 불일치, (f) 원본을 만족하지만 최상위 영향 없는 witness, (g) 검색 seed·반복 차단의 증명 혼입 방지다. 오늘은 설계만 작성했으며 다음에 코드 변경이 허용될 때 저장소의 fmt·Clippy·test 관문을 적용한다.

## 확인한 것

- v2.3가 공유하는 J의 고정·미판정·국소 반박·수리·술어 경로와 삽입 위치를 정적 코드로 대조했다. 작은 부분 풀이·상위 경로·carry·후보 독립 `LessThan` 탐색은 이미 있다.
- 요청의 출발 집계는 제공값으로만 인용했고, 지정 개발 파일 부재를 확인했다. 금지된 aq 폴더·외장 J 캐시·B 원자료는 열지 않았다.
- Picus 논문/공개 안내, CEGAR 논문, ScaleCirc 공식 초록/README를 확인했고, 자체 반박 과정에서 SMASH 논문을 추가로 확인했다. ScaleCirc의 확보된 공개 코드를 해시 확인 후 재대조했다. ScaleCirc 본문 전문 대조는 미완료다.
- 현재 repair는 모델을 입력/hint 제어로 투영하고 생성기를 재실행한다. 전체 모델 벡터를 원본 witness로 직접 완성하는 제어 과정은 검토한 현재 실행 경로에 없다. 테스트 전용 witness 쓰기 함수는 존재한다.
- 코드 수정·판정·퍼징·컴파일·설치·하위 에이전트·git 쓰기를 하지 않았다. 작성·수정 파일은 이 문서 하나다.

참조 시점 핵심 소스 SHA-256: `mod.rs=0a5f59c265c72c664f89f67193372fb35d0c337b0651e397d84bf845fc19b780`, `repair.rs=93e7ddfac28cb3502c2b1e5f787831d5aa50c6cc453507dc7db38401d283ca05`, `synth.rs=b36da125e6147996ffeb33e645e769727acfe37aaf867caecfe6f0e547233a01`, `predicate.rs=19cbf00493345219545979432b3f4edbc2051ba2b86512b93ce1dfe583bef532`. 행 번호는 이 작업 트리 시점의 것이다.

## 추정한 것

가정 선택의 비용 이득, 직접 witness 완성의 추가 해결 능력, 일반 TCCT 술어의 지원률, aq 703건의 개선 가능 수, 주입 실패 42건의 근본 원인, 작업량은 미검증이다. F₇ 예시는 논리 설명이며 실행 결과가 아니다.

**최종 판단:** J 보강은 ScaleCirc와 겹치는 분해·반례 전파 위에서 더 필요한 연구 문제를 겨냥한다. 최초안 그대로는 기능 추가 수준으로 평가될 위험이 컸다. 수정안은 기존 합성·수리·검증 기반에 목표 보존·선택적 정제를 연결하고, 직접 witness 완성을 별도 확장으로 비교하는 구체적 검증 대상을 갖추었으므로 연구로 발전시킬 근거가 있다. 선택 정책이 단순 방법보다 낫지 않거나 지원 술어가 지나치게 좁으면 주요 기여 주장은 약해진다. 자료 부재나 미실험을 근거로 효과를 확정하지 않되, 설계의 가치를 기한으로 판단하지 않는다.

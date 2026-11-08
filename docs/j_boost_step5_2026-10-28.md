A는 개발 세트다. 이 결과는 J 보강의 성과가 아니다.

# J 보강 5차: aq-026/2200 진단

**결론:** 고정 대표 071·073·079·080에서 확인된 원본 도달 또는 배제는 0건이다. Q1·Q3·Q2 12질의 모두 Z3 `unknown(timeout)`이다. 지정된 범위의 forward existence probe도 상위 DateDecoder 입력 힌트를 바꿀 수 없어 완성되지 않았다. 따라서 이번 측정은 J 성능 개선이나 버그 존재의 증거가 아니다.

## 범위와 실행 한도

- 원본 O0: **89,089개 제약**, 89,719 wire, 최상위 출력 9개. O1: 54,442개 제약. O0 R1CS SHA-256 `7ad78e34fa0110050eb9051b63813ebd21ad206da9c7ebc326e74ace8b18cf95`; O1 `2274acf37ad5421d6a85d4436850b8bb7753075f5e00d007f5c2ab7937c37f45`. 두 R1CS는 4차 원본 해시와 일치한다.
- 질의 순서: Q1 `F ∧ S의 13개 신호값 고정`(나머지 wire 자유), Q3 `F ∧ V ∧ C`, 남은 시간에 Q2 `F ∧ V`. `F`는 O0 전체 89,089개 제약이다. `C`는 아래 842개 최상위 입력의 4차 기준값 고정이다. `V`는 별도 정직 계산 변수 `z=10t+u, 0≤u<10`으로 산출한 부품 출력 `H`와 실제 `E`의 필드 불일치다. 원래 DateEncoder의 q/r에 새 자릿수 범위를 덧붙이지 않았다. 정확 치환: alias 34,048, 일반 필드식 53,035, 단일 선형 598, 불리언 1,408.
- solver 누적 **7141.027초 / 7,200초**, 질의별 모두 600초 미만, seed 0, `nice -n 19`. 실험 시작부터 마지막 질의까지 **130.6분 / 240분**(2026-10-27 16:32:39–18:43:14 UTC). 한 번에 한 질의만 실행. 원본 이미지·aq 캐시 사용 없음.
- 도구: Circom 2.2.3, Z3 5.1.0, Node 26.0.0, snarkjs 0.7.6. 실행 파일 해시는 `runs/j-boost-2026-10-27/step5/preparation.json`에 기록했다.
- 마지막 실험 후 검토 도구가 약 24,753초 멈춰 보고가 지연됐다. 그 동안 새 실험은 실행되지 않았다. Q1/079는 부모 세션 중단 뒤 Z3 자체가 timeout으로 끝났고, 원래 영수증을 `recovery-audit/`에 보존한 후 종료 시각과 heartbeat로 594.425초를 복구했다.
- 보고서 작성 뒤 구문 확인에 `python3 -m py_compile`을 사용해 허용 경로 밖 `scripts/__pycache__/j_boost_step5_diag_20261028.cpython-315.pyc`가 생성됐다. 경로 제한을 어긴 작업이며, 삭제 금지 지시에 따라 이 파일을 그대로 두었다. 이후 검사에서는 이 명령을 다시 쓰지 않았다.
- Rust·기존 실행기는 수정하지 않았다. `AGENTS.md`의 계획표 갱신과 Cargo 관문은 이번 작업의 허용 쓰기 경로·실험 상한과 충돌해 실행하지 않았다.

## 대표별 결과

| 대표 | 존재 probe | Q1 | Q3 | Q2 | solver 초(Q1/Q3/Q2) | probe의 첫 실패 O0 제약(0부터) |
|---|---|---|---|---|---|---|
| 071 | 미완성: child `===` 중단; 진단 벡터 O0/O1/snarkjs 거부 | unknown(timeout) | unknown(timeout) | unknown(timeout) | 594.7/595.4/594.8 | 1829 |
| 073 | 미완성: child `===` 중단; 진단 벡터 O0/O1/snarkjs 거부 | unknown(timeout) | unknown(timeout) | unknown(timeout) | 594.8/595.4/594.8 | 1947 |
| 079 | 미완성: child `===` 중단; 진단 벡터 O0/O1/snarkjs 거부 | unknown(timeout) | unknown(timeout) | unknown(timeout) | 594.4/595.8/594.9 | 8127 |
| 080 | 미완성: child `===` 중단; 진단 벡터 O0/O1/snarkjs 거부 | unknown(timeout) | unknown(timeout) | unknown(timeout) | 595.4/595.5/594.9 | 8138 |

대체 날짜는 각각 071=`2/1/80`, 073=`2/1/90`, 079=`2/1/30`, 080=`2/1/35`이며 모두 날짜 범위 안이다. 주입 대상은 각 DateEncoder의 q/r 힌트 6개뿐이다. 상위 DateDecoder의 `day/month/year`는 `<--`로 계산되는 별도 힌트여서 실제 child 입력은 모두 기존 `day=1`이었다. 이 상태에서 대체 `day=2`를 위한 q/r을 넣으면 `day − 10·dayDecimals − dayRest = −1 (mod p)`가 되어 생성기가 child의 `===`에서 중단했다. 정상 downstream 재계산은 이루어지지 않았다.

첫 실패 위치를 확인하려고 별도로 만든 **대수적 거부 진단 벡터**는 완성된 forward probe나 SAT witness가 아니다. 대상 child의 q/r과 encoded를 갱신하고 나머지는 기준 witness로 둔 뒤 전체 O0·O1와 양쪽 snarkjs를 검사했다. 네 벡터 모두 입력 계약은 유지했지만 O0 제약 1개 및 O1 제약 1개가 실패했고 snarkjs 두 검사도 실패했다. 실제 날짜의 `V=false`, `aligned=unknown`, 검증된 도달=0이다. 네 첫 O0 식의 A·B는 공집합, C는 아래와 같다(잔차 1):

| 대표 | 인스턴스 | 제약 | C의 wire:계수 |
|---|---|---:|---|
| 071 | `main.birthDateLowerboundCompare.firstDateNormalization.firstDateDecoder.dateEncoder` | 1829 | `1039:1 + 1042:-10 + 1043:-1` (`day−10·dayDecimals−dayRest`) |
| 073 | `main.birthDateLowerboundCompare.secondDateNormalization.firstDateDecoder.dateEncoder` | 1947 | `1171:1 + 1174:-10 + 1175:-1` (`day−10·dayDecimals−dayRest`) |
| 079 | `main.expirationDateLowerboundCompare.firstDateDecoder.dateEncoder` | 8127 | `8633:1 + 8636:-10 + 8637:-1` (`day−10·dayDecimals−dayRest`) |
| 080 | `main.expirationDateLowerboundCompare.secondDateDecoder.dateEncoder` | 8138 | `8650:1 + 8653:-10 + 8654:-1` (`day−10·dayDecimals−dayRest`) |

## 명시적 입력 계약 C

`C`는 이 실험의 **기준 입력 등식**이지 회로의 일반 유효입력 규격이 아니다. 842개 pin = 스칼라 18개 + `dg1[0..743]` 744비트 + `idStateSiblings[0..79]` 80개. 기준 입력 JSON SHA-256 `c88e50147ebb3ee221c240aca3fe68d4795b1898874a7b4b45980a56e4fc9162`. 비트열은 `dg1[0]`을 최상위 비트로 해석한 186자리 16진수로 아래에 전부 지정했다. 따라서 모든 개별 비트값이 복원된다.

| 스칼라 입력 | 값 |
|---|---:|
| `main.birthDateLowerbound` | `61779618115633` |
| `main.birthDateUpperbound` | `52983525093425` |
| `main.citizenshipMask` | `0` |
| `main.currentDate` | `55208334864949` |
| `main.eventData` | `237827176111428467964829360686859070113858978917836674772780347917507574374` |
| `main.eventID` | `386965417269815948541023196534788283782247624637184722509250345650194089994` |
| `main.expirationDateLowerbound` | `56282059976753` |
| `main.expirationDateUpperbound` | `57381571604529` |
| `main.idStateRoot` | `16461076936932554575602044675013316891669823867734147857021253623830729638376` |
| `main.identityCounter` | `1` |
| `main.identityCounterLowerbound` | `0` |
| `main.identityCounterUpperbound` | `2` |
| `main.pkPassportHash` | `356957525147781608598424661205482416885691890477330880589061281400922574251` |
| `main.selector` | `65535` |
| `main.skIdentity` | `420381841470549164013134905480206700327737619514477901427686558342425519890` |
| `main.timestamp` | `1760000000` |
| `main.timestampLowerbound` | `1750000000` |
| `main.timestampUpperbound` | `1770000000` |

- `dg1[0..743]`, index 0→743 순서의 비트열 = `0x615b5f1f58503c5553414558414d504c453c3c53594e5448455449433c544553543c3c3c3c3c3c3c3c3c3c3c3c3c3c3c3c545354303030303031375553413930303130313146333530313031343c3c3c3c3c3c3c3c3c3c3c3c3c3c3032` (앞의 0도 포함해 정확히 744비트).
- `idStateSiblings[0..79] = 0` (80개 전부). 개별 wire 번호와 값은 `step5/contract.json`에 보존했다.

## 질의 파일 SHA-256

| 대표 | Q1 | Q3 | Q2 |
|---|---|---|---|
| 071 | `5f11f33e47d242bdc547abd8451ddb469a6d791bbd7859ebddcef9a48024df02` | `e926d93a688298d598756746e398a30603f1153d421db305447f5067425cdbe4` | `e08fddb026f99fb1332bd3c94b1ca07c1bf4b0b10edd78f3a732c1aebbd00aec` |
| 073 | `a4d7c0aad532b735e7bc701b3ea7ca772902f0ec7eb847f0858091cda94e83f1` | `3d8383fdb204e144daac9ca8b2642282f728942bdf93f7f3f6333acf90b6230c` | `d141bc7a7820c7f4400398cbaf3da11b969a7c26562ba4f9c46ddfcf26bb874a` |
| 079 | `1aa6d4bf0568e4e3b9fe3bd1ebb430e044c34343d841f44b3f07ee0db54d60ec` | `d19c423a6caa6c7133d2f0c006396f66aa03302551ebffb51d401db99d27c7fa` | `ec12f7ead687e8f39899bde539ff0a4013c7201050f0917d215e530dfb064e99` |
| 080 | `e9235ec05efdefdb367a1dffd9ce910ed20cd398efedc381ce9f515307037c36` | `b82361b5af385540e77e67284cf0f75fa3c8e5fcfcc5ecf6a3c661f6e10db1ba` | `68658cc49b140468d72f0bedd1ea1267ad5f580033e5817e0bbe80b4831c6b3b` |

12개 `query.smt2` 파일의 현재 SHA를 다시 계산해 모두 위 기록과 일치함을 확인했다. 각 파일·scope·solver stdout/stderr·영수증은 `runs/j-boost-2026-10-27/step5/queries/<대표>/<Q1|Q3|Q2>/`에 있다. `unknown(timeout)`에는 모델이 없어 원본 O0/O1/snarkjs 및 aligned 규칙으로 승인할 SAT가 없었다. `unknown`을 UNSAT이나 배제로 읽지 않는다.

## Step 0과 자기 반박

- 4차 원장 SHA-256 `57aeca594cd18906a2e8044e57440a47f772514c7b3cf5e9cfc5366848fb373c`에서 **264회 시도**(closed_cone 12, repair_region 252)와 실패 제약 번호·공통 부품 경로는 회수했다. 대표별 시도는 071=27, 073=7, 079=31, 080=7이다. 당시의 원시 query/시작·모델 벡터가 보존되지 않아 264회의 wire별 출처, 서로 다른 모델 수, 잔차값, query 소속은 회수할 수 없다.
- Circom `\`와 `%`는 고정된 witness 생성기에서 9, 10, 19, 20, `p−1`을 시험했고 각각 `(q,r)=(0,9),(1,0),(1,9),(2,0),((p−1)//10,6)`으로 정수 나눗셈과 일치했다. 대규모 정수식의 의미를 조용히 바꾸지 않았다.
- Q3는 842개 계약을 고정했고 Q2만 계약을 제거했다. **SAT가 하나도 없어 계약 위반에 의존한 SAT도 없다.** 반대로 계약 아래 위반이 불가능하다는 뜻도 아니다.
- 대체 날짜 네 개는 모두 범위 안이지만 probe는 하나도 통과하지 못했다. 계산된 q/r 중 일부가 통상 0–9 자릿수 범위 밖이다. 원래 DateEncoder q/r에는 그런 추가 제한이 없으며, 이 값들로 성공을 주장하지 않는다.
- Q1/Q3/Q2의 600초 시간 초과는 SMT-LIB의 대규모 비선형 정수·mod 인코딩이 풀리지 않은 것이다. 가설을 입증하거나 반증하지 못했다. 특히 Q1의 고정 S 입력 자체가 원본에서 불가능한지, 또는 다른 입력으로 같은 위반이 가능한지 여전히 미정이다.

## 확인한 것

- O0/O1 원본 해시 및 기준 witness의 O0/O1·snarkjs 검증, 12개 질의의 해시·시간·`unknown(timeout)`, 4개 probe의 child 제약 충돌과 첫 실패 식, 842개 계약, 경계값 나눗셈 의미, 실행 상한 준수.

## 추정한 것

- DateDecoder의 parent 힌트와 child 힌트를 함께 바꿀 수 있는 **별도 탐색 설계**라면 forward 존재 후보를 만들 수 있을지 모른다. 이번 범위에서는 실행·검증하지 않았으므로 방법이나 논문 기여로 세지 않는다. 재검토 우선순위는 parent/child 입력 대응을 명시하고 작은 원본 부분문제에서 검증된 모델을 찾는 것이다.
- 후속 검토에서 기존 `repair.rs`가 이미 상류 힌트 탐색과 generator 재실행을 한다는 점, `boost.rs`의 값 덮어쓰기가 264개 직접 완성 시도 모두에 적용된다는 점을 코드로 대조했다. 제안된 “경계 올리기·하류 재계산”만으로 기존 J와 다른 새 규칙은 확인되지 않았다. 대화의 근거와 다음 진단 범위는 `runs/j-boost-2026-10-27/step5/claude_debate_20261028.md`에 남겼다.

**요약:** 원본 검증 도달·배제 0건. probe 범위 충돌 4건, SMT 시간 초과 12건. 이 개발 결과로 J의 효과나 선행 연구 대비 우위를 주장할 수 없다.

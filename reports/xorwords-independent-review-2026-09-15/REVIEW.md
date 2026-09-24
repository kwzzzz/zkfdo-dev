# XorWords 기존 후속 검증 독립 검수

검수일: 2026-09-15. 대상: `zkfDO_검수자료` 최신 v2 묶음의 보존 소스·반례·제약·검증 절차.

## 결론

**기존의 정확한 신호 대입은 확보한 수정 직전 원본 `XorWords(1,32)`에서 35개 제약 중 2개를 위반한다. 핵심 계산과 이 반례를 원본의 유효한 반례로 집계하지 않는 판단은 타당하다.**

이 결론은 기존 검증 스크립트의 출력만 재인용한 것이 아니다. 별도 코드로 보존 R1CS를 읽고 모든 계수를 소스에서 도출한 다항식과 대조했으며, 기존 반례를 대입해 재계산했다. 원래 검증 스크립트도 별도 복사본에서 실제로 재실행했다.

`wrapper-only`는 이 증거로 확인된 범위를 나타내는 용어로 읽으면 타당하다. 원본 안전성, 다른 내부 대입의 부재, 프로젝트 입력 도달 불가능성을 뜻하지 않는다.

## 1. 자료로 확인된 사실

### 출처와 파일 동일성

- 묶음 `SHA256SUMS`의 56개 항목과 `FILE_MANIFEST.json`의 51개 파일 항목이 실제 바이트·크기와 일치했다. 최상위 편의 사본 8개도 `files/`의 대응 파일과 동일했다. 해시 일치는 아래 수학 검증과 별도로 수행했다.
- 보존된 [수정 commit 응답](/Users/miiz/Desktop/zkfDO_검수자료/files/runs/xorwords-original-followup-2026-09-15/fix-commit.json:1)은 `ef9f5a5ad899d852740a26b30eabe5765673c71f`의 직접 부모를 `4551ca64c9fe536b7b9b7498a1feb1ecdc847474`로 기록한다. [부모 commit 응답](/Users/miiz/Desktop/zkfDO_검수자료/files/runs/xorwords-original-followup-2026-09-15/parent-commit.json:1)과도 일치한다.
- 출처 기록의 소스 7개에 대해 저장된 content 응답의 Base64를 해독했다. 실제 소스 바이트, Git blob SHA-1, SHA-256, 길이를 대조했다. 부모 소스 6개는 부모 tree의 경로별 blob과, 수정본 1개는 수정 commit의 해당 파일 blob과 일치한다.
- 부모의 재귀 tree 목록을 Git tree 형식으로 다시 인코딩·해싱한 결과는 `d39bd2375a4bf277a0f65b7d511f5a6191a86c2b`로, 부모 commit이 가리키는 tree와 일치한다. 주의할 점은 `parent-tree.json` 최상위 `sha`에는 tree hash 대신 조회에 사용된 부모 commit hash가 들어 있다는 것이다. 그 필드를 tree hash로 간주하지 않고 실제 항목으로 재계산했다.
- 실제 검사에 복사된 `generics.circom`과 원래 테스트 `xor32bits.circom`은 확보 원본과 바이트 단위로 같다. [원래 테스트 5행](/Users/miiz/Desktop/zkfDO_검수자료/files/runs/xorwords-original-followup-2026-09-15/parent-xor32bits.circom:5)은 `XorWords(1,32)`를 main으로 사용한다.
- 원본과 수정본의 실제 차이는 Boolean 제약 활성화, `ain * a[i] === 0` / `bin * b[i] === 0`을 각각 무조건적인 잔여값 0 검사로 변경한 것이다. 이는 기록된 수정 목적과 일치한다.

출처 검수는 **보존 API 응답과 실제 파일 사이의 일관성**을 확인했다. 이번에 원격 서버에서 다시 내려받거나 Git commit object 자체의 hash를 복원한 것은 아니다.

### 입력·내부 신호·출력 대응

[fixture 19–35행](/Users/miiz/Desktop/zkfDO_검수자료/files/experiments/evidence/xorwords-2026-09-15/fixture/xor.circom:19)은 가중치 `2^k` 순서로 비트를 저장한다. [원본 67–85행](/Users/miiz/Desktop/zkfDO_검수자료/files/runs/xorwords-original-followup-2026-09-15/parent-generics.circom:67)은 `2^31`부터 내려간다. 따라서 다음 대응이 맞다.

| fixture | 원본 | 확인 내용 |
|---|---|---|
| `main.a`, `main.xor.a` | `main.a[0]` | 두 alias 모두 6 |
| `main.b`, `main.xor.b` | `main.b[0]` | 두 alias 모두 1 |
| `main.out`, `main.xor.out` | `main.out[0]` | 실제 출력 `p - 17,179,770,361` 유지 |
| `a_bits[k]`, `b_bits[k]`, `xor_bits[k]` | `abits[31-k]`, `bbits[31-k]`, `xors[31-k]` | 비트 가중치 보존 |

총 99개 신호를 대응하고 상수 wire 0에는 1을 넣었다. 누락 신호, 임의의 0 대입, 값 변환은 없다. 기대 출력 7로 실제 출력을 교체하지 않았다. `ain`, `bin`, `out2`는 소스의 계산용 변수이며 추가 witness 신호가 아니다.

### 유한체 계산과 모든 제약

소스와 컴파일 결과의 필드는 다음과 같다.

`p = 21888242871839275222246405745257275088548364400416034343698204186575808495617`

보존 반례를 대입해 직접 얻은 값은 다음과 같다.

- `Σ abits[j] · 2^(31-j) = p - 17,179,869,178`
- `Σ bbits[j] · 2^(31-j) = 98,817`
- `Σ xors[j] · 2^(31-j) = out = p - 17,179,770,361`
- 정상 정수 XOR는 `6 XOR 1 = 7`이다. 실제 출력은 이 값과 다르다.

별도 R1CS 판독 코드로 이진 파일의 헤더, prime, 35개 제약의 모든 계수, wire label을 읽었다. `R1CS_READABLE.json` 및 `.sym`과 일치했다. 또한 모든 제약을 다항식으로 전개해서 소스로부터 도출한 32개 XOR 식, 2개 재구성 식, 1개 출력 식과 각각 대조했다.

| 0부터 시작하는 제약 번호 | 식 | `mod p` 잔여값 | 판정 |
|---|---|---|---|
| 0–31 | 각 비트의 `xors = abits + bbits - 2·abits·bbits` | 모두 0 | 32개 만족 |
| 32 | `(a - Σ abits·가중치) · a` | `17,179,869,184 × 6 = 103,079,215,104` | 위반 |
| 33 | `(b - Σ bbits·가중치) · b` | `p - 98,816` | 위반 |
| 34 | `out - Σ xors·가중치` | 0 | 만족 |

실패 계수의 직접 근거는 [R1CS_READABLE.json 667행](/Users/miiz/Desktop/zkfDO_검수자료/R1CS_READABLE.json:667)과 [709행](/Users/miiz/Desktop/zkfDO_검수자료/R1CS_READABLE.json:709), 원본 식은 [generics.circom 83행](/Users/miiz/Desktop/zkfDO_검수자료/files/runs/xorwords-original-followup-2026-09-15/parent-generics.circom:83)이다.

### 실제 재실행과 정적 검토의 구분

| 검수 작업 | 이번 수행 방식 | 결과 |
|---|---|---|
| 보존 fixture 검증 `verify.py` | 정확한 복사본에서 실제 실행 | 종료 0, 16개 내부 checksum 및 원본/보존 재현의 주요 필드 일치 |
| 소스·신호 대응·판정 문구 | 정적 검토 | 대응 및 범위 제한 타당 |
| 보존 R1CS 계산 | 기존 스크립트를 import하지 않은 별도 코드로 실제 재계산 | 33개 만족, 2개 위반 |
| 원본 component 검사 `check_r1cs.py` | 정확한 복사본에서 실제 실행·컴파일 | Circom 2.2.3, 종료 0, 보존 결과 JSON과 필드별 차이 없음 |
| 새 컴파일 산출물 | 보존본과 바이트 해시 비교 | R1CS 및 `.sym` 해시 일치 |
| 감사 PDF | 10쪽 전체 텍스트·링크 추출, 8–9쪽 이미지 확인 | 관련 발췌 일치, 감사 대상 프로젝트 hash 확인되지 않음 |

이번에 퍼징을 재실행하지 않았다. fixture의 재현 주장에 대해서는 보존된 두 반례의 assignment·flag·설정·seed·generation 일치와 제약 만족을 확인했다. 종료 코드 0은 검사 완료이며 반례 통과를 뜻하지 않는다.

## 2. 오류나 수정할 주장

**핵심 산술·신호 대응·33/2 판정에서 수정해야 할 오류는 발견하지 못했다.** 다음은 읽는 사람이 현재 상태나 보존 범위를 오해하지 않도록 보완할 사항이다. 기존 원문과 코드는 수정하지 않았다.

1. **과거의 미확보 상태에 시점을 표시할 필요가 있다.** 사례 문서의 [76행부터인 ‘확인하지 못한 사실’](/Users/miiz/Desktop/zkfDO_검수자료/xorwords-case-study-2026-09-15.md:76)은 후속 절에서 확보한 정보까지 미확인으로 열거한다. [145행 후속 절](/Users/miiz/Desktop/zkfDO_검수자료/xorwords-case-study-2026-09-15.md:145)이 갱신을 명시하므로 전체 결론의 모순으로 판단하지는 않는다. 앞 제목을 ‘초기 분석 당시 미확인 사항 — 후속 절에서 일부 갱신’으로 표시하면 혼동을 줄일 수 있다.
2. **fixture 검증기 마지막 출력은 해당 검증기의 범위로 한정해야 한다.** [verify.py 57행](/Users/miiz/Desktop/zkfDO_검수자료/files/experiments/evidence/xorwords-2026-09-15/verify.py:57)의 `Original-project source ... unverified`는 이 스크립트가 원본을 검사하지 않는다는 뜻으로는 맞다. 하지만 전체 연구의 최신 상태로 인용하면 이미 수행한 원본 출처·component 검사가 빠진다. 원본이 아직 전혀 확보되지 않았다는 근거로 사용하면 안 된다.
3. **재실행 안내에서 컴파일 파일의 덮어쓰기를 구분해야 한다.** [check_r1cs.py 117–126행](/Users/miiz/Desktop/zkfDO_검수자료/files/experiments/evidence/xorwords-original-followup-2026-09-15/check_r1cs.py:117)은 고정 경로의 소스 사본·R1CS·신호표·컴파일 로그를 다시 쓴다. 문서의 `--output` 보호 설명은 결과 JSON에 대해서만 맞다. 따라서 증거 보존을 위한 재실행은 별도 복사본에서 해야 한다. 이번에는 그렇게 실행했다.

`wrapper-only`라는 표현 자체를 오류로 판단하지 않았다. [사례 문서 255–260행](/Users/miiz/Desktop/zkfDO_검수자료/xorwords-case-study-2026-09-15.md:255)은 정확한 전체 대입의 거부와 일반적인 원본 안전성·프로젝트 공격 가능성을 명확히 구분한다. 이 제한을 생략하고 ‘원본은 안전함’, ‘프로젝트에서 도달 불가’, ‘wrapper가 결함을 만들었음’으로 요약하는 것은 자료가 뒷받침하지 않는다.

## 3. 남은 미확인 사항

- 감사 당시의 정확한 전체 revision. 확보한 부모는 XOR 수정 직전 구현이며, 감사 PDF 8쪽 관련 발췌와 일치한다. PDF의 10쪽 전체 텍스트와 링크에서 프로젝트 commit hash를 확인하지 못했다. 따라서 이것만으로 감사 전체 snapshot을 확정하지 않는다.
- 실제 프로젝트 입력으로 XOR 호출부의 `a=6, b=1`에 도달하는지, 다른 내부 대입으로 성립하는 반례가 있는지, 전체 witness/proof가 유효한지. [원래 main 5행](/Users/miiz/Desktop/zkfDO_검수자료/files/runs/xorwords-original-followup-2026-09-15/parent-circuit.circom:5)과 [caller 29–32행](/Users/miiz/Desktop/zkfDO_검수자료/files/runs/xorwords-original-followup-2026-09-15/parent-chacha20.circom:29)의 정적 연결은 확인했다. 이 연결 확인만으로 실제 입력 도달성을 증명하지 않는다.
- 2023년 컴파일러 및 배포 proof artifact와의 동일성. 이번 재컴파일은 기록과 같은 Circom 2.2.3의 `--O0 --prime bn128`을 사용했다.
- 출처 기록의 [Hmac512 교차 확인 요약](/Users/miiz/Desktop/zkfDO_검수자료/source-provenance.json:44)은 있으나 그 서버의 별도 원시 commit 응답은 이 묶음에 없다. 그 교차 조회와 과거 404 응답 자체는 이번 검수에서 독립 재확인하지 않았다. reclaim-1 보존 응답·소스·tree의 일관성은 위에서 확인했다.
- dev3 전체 49회 파일럿의 원시 실행 검증과 유효 결함 수. 최신 [preparation 132행 부근](/Users/miiz/Desktop/zkfDO_검수자료/dev10-preparation-2026-09-15.json:132)은 완료 상태이며 오래된 `not_run`과 혼동하지 않았다. 49회 전략 실행·147회 타깃 시도·119건 후보는 보고된 파일럿 수치이며, 이 검수로 고유한 프로젝트 결함 수나 랭킹 우위를 입증한 것이 아니다.

## 4. 연구의 다음 질문 하나

**다음 비교 실험에서 ‘유효한 발견 1건’으로 세기 위해 요구할 최소 증거는 무엇인가?**

이 질문이 필요한 이유: 후보 도착 속도만 빨라져도 현재의 파일럿 지표는 좋아질 수 있다. 그러나 이번 사례처럼 원본에서 거부되는 후보라면, 그 개선을 zkFuzz의 유효한 결함 탐지 효율 개선으로 해석할 수 없다. 먼저 측정할 성공의 뜻을 정해야 한다.

이 단계의 종료 조건: fixture 반례, 원본 component에서 성립한 반례, 프로젝트 문맥까지 확인한 결함의 집계 여부와 반복 발견의 중복 처리 기준을 짧은 표로 합의한다. 기존 XorWords 증거를 그 표에 적용했을 때 해당 원본의 유효한 발견으로 세지 않는 이유가 명확하면 된다. 이 기준은 ‘대상 수가 많음’과 ‘개별 대상의 분석 비용이 큼’을 어느 쪽도 정적 랭킹이 해결했다고 전제하지 않아야 한다.

추가 연구 작업은 이 검수 결과를 논의한 뒤 결정한다.

## 검수 산출물과 보존

- [독립 재계산 결과](/Users/miiz/Desktop/kwzzzz_zkfr/reports/xorwords-independent-review-2026-09-15/independent-results.json): 출처 대조, 35개 제약별 잔여값, 재실행 비교.
- [원본 component 재실행 결과](/Users/miiz/Desktop/kwzzzz_zkfr/reports/xorwords-independent-review-2026-09-15/component-rerun.stdout.txt): 기존 결과 JSON과 필드별 동일.
- 검수자료 65개 파일의 실행 전후 해시가 모두 동일했다. 원본 저장소의 기존 사례 문서 및 후속 증거도 변경하지 않았다. 신규 파일은 이 검수 디렉터리에만 생성했다.

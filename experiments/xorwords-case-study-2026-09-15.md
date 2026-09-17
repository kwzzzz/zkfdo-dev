# `XorWords` direct 반례 사례 분석 — 2026-09-15

이 분석은 기존 dev3 connection smoke에서 `reclaim XorWords direct` 한 건만 추적한다.
랭킹 구현·corpus·전략 반복 실험은 변경하지 않았다. 아래에 기록한 최소 재현은 동일
설정으로 실행해 보존한 재현 한 건이다. 별도 검토자의 임시 디렉터리 재실행은 이 자료의
실험 횟수나 성능 통계에 포함하지 않는다.

## 선정

이 타깃은 manifest → 준비 snapshot과 해시 → 원본 실행 로그 → 보존 반례 → 기존 수동
검토와 확인 → zkbugs 메타데이터·fixture → 감사 보고서까지 한 경로로 추적할 수 있어서
선정했다. `risk_score=0`, `warning_count=0`인 타깃이므로 위험 점수나 랭킹상 유리함을
선정 기준으로 사용하지 않았다.

- target: `sha256:ad316368e69f548873127453f56e34ad4e732a310b8ec19380476d1241031e6d`
- 기존 run: `a96a4865-2ea1-4e59-a9d4-02bc8197c23f`, zkFuzz seed `424242`
- 선언된 revision: project `ef9f5a5ad899d852740a26b30eabe5765673c71f`, zkbugs
  snapshot `a0eed744ba1a816acaa2fae597f4e79b4fd01aea`

## 검증된 사실

준비된 타깃은 BN254(`bn128`) direct mode의 인자 없는 `XorWords()`이며, 내부에서
`XorBits(32)`를 사용한다. 준비 snapshot과 zkbugs fixture는 byte 단위로 같다.

- `circuit.circom`: `3b598d718d95008b1d0bc08ad42687779d3ae6369216fec6183d8efa09616fbb`
- `xor.circom`: `c4e2d54a4c99b4f8fefd1fd5ce20ecf43196e71d5b4a30bfc1bc143be728e3a4`

감사 보고서의 대상 `XorWords`는 고정된 배열 크기와 `M`에 대해 두 `M`-bit 값 배열을
처리한다. 보고서에 실린 감사 당시 코드는 bit Boolean 제약이 빠졌고, 분해 뒤 남은 값에
`ain * a[i] === 0`을 적용하는 재구성 검사도 `a[i]=0`일 때 무력화됐다. 반면 현재 direct
fixture는 두 scalar field 입력을 그대로 노출하고, `XorBits(32)` 안에서 `sum_a`와
`sum_b`를 계산만 할 뿐 입력 `a`, `b`와 잇는 제약이 전혀 없다. 따라서 양쪽의 함수
모양과 제약식은 동일하지 않다.

기존 반례는 `a=6`, `b=1`에 대해 정상 scalar XOR인 `7`을 expected output으로
기록하지만 다음 field 값을 실제 출력으로 만든다. 여기서
`p=21888242871839275222246405745257275088548364400416034343698204186575808495617`이다.

```text
out = p - 17,179,770,361
    = 21888242871839275222246405745257275088548364400416034343698204186558628725256
```

반례의 `a_bits[28]=p-64`, `b_bits[14]=6`은 Boolean 값이 아니다. bit 배열의 가중합도
각각 `a`와 `b`를 재구성하지 못한다.

```text
sum(a_bits[i] * 2^i) mod p = p - 17,179,869,178 != 6
sum(b_bits[i] * 2^i) mod p = 98,817               != 1
```

동시에 각 위치의 `xor_bits[i] = a_bits[i] + b_bits[i] - 2*a_bits[i]*b_bits[i]`와
output packing 제약은 모두 만족하며, 그 packing 결과가 위의 저장된 `out`과 정확히
같다. 즉 이 반례가 보여 주는 불일치는 **direct fixture가 허용하는 비Boolean·비재구성
bit witness로 올바른 `6 XOR 1`과 다른 출력을 만든 것**이다. `a`와 `b`가 모두 0이
아니므로 이 witness는 감사 보고서에 실린 원래의 잔여값 검사까지 만족하지는 않는다.

동일한 준비 snapshot, prime, zkFuzz revision, seed와 mutation settings로 한 번 다시
실행했다. exit code 0, generation 0에서 반례가 다시 나왔고, 기존 반례와 새 반례의
assignment, flag, seed, generation이 모두 같았다. 파일 전체 해시는 경로와 실행시간
메타데이터가 달라 서로 다르다.

## 해석과 판정

판정은 **`wrapper-only`**다. 현재 증거는 격리된 direct fixture의 under-constraint와
그 반례 재현을 확인한다. 이 판정은 원 프로젝트가 안전하다는 뜻이 아니며, 원 프로젝트
결함이나 실제 호출 경로의 도달성을 확인한 결과도 아니다.

`project`로 판정하려면 선언된 project revision의 실제 소스·entrypoint·호출자 제약에서
동일 witness 또는 같은 원인으로 프로젝트 속성이 깨지는지 확인해야 한다. 현재는 fixture와
감사 대상의 제약 구조부터 다르므로, source equivalence를 전제로 하는
`reachability-unknown`보다 `wrapper-only`가 확인 가능한 범위를 더 정확히 나타낸다.
기존 [`confirmations.json`](../runs/dev10-smoke/confirmations.json)의 같은 판정은 변경하지
않았다.

## 확인하지 못한 사실

- project revision `ef9f5a5...`의 실제 `XorWords` 정의, template 파라미터, 배열 크기와
  호출 위치
- 원래 caller가 두 피연산자에 적용한 bit/range 제약과 입력 도달 조건
- 해당 revision이 감사 전/후 어느 구현인지와 감사 보고서의 client fix가 반영됐는지
- 이 witness가 원 프로젝트 R1CS·proof에서 성립하는지, public/output 사용에 실제 영향을
  주는지

로컬 zkbugs의 선언된 project codebase와 `input.json`은 없고, 메타데이터의
`Original Entrypoint`도 비어 있다. `zkbugs_vars.sh`는 original entrypoint를 direct
fixture와 같은 파일로 지정한다. 따라서 `Compiled Original=true` 메타데이터만으로 실제
프로젝트 문맥이 검증됐다고 볼 수 없다. 로컬 zkbugs checkout은 1-commit shallow
checkout이므로 fixture가 언제 처음 추가됐는지도 이 checkout만으로 판단하지 않았다.

## 근거 파일

- [공유용 최소 근거 묶음](evidence/xorwords-2026-09-15/README.md): 아래 원본·재현 반례,
  stdout/stderr, seed 설정, direct fixture와 MIT 고지, 메타데이터를 byte 단위로 보존했다.
  파일별 해시와 원래 경로는 묶음 안에 기록했다. raw JSON의 절대 경로는 당시 실행
  환경의 기록이며 다른 컴퓨터에서 유효한 경로가 아니다.
- [dev10 manifest](../datasets/manifest.dev10.json): 실행 전 고정한 메타데이터다.
  `Not reproduced by this work` 등의 문구는 준비 당시 상태이며, 이번 사례 판정으로
  덮어쓰지 않았다.
- [준비 결과](../runs/dev10-preparation/prepare-e11d82dd-e508-4b69-ab93-38dbed5345f8/prepared.json)
- [zkbugs metadata](../.external/zkbugs/dataset/circom/reclaimprotocol/circom-chacha20/zksecurity_Unsound_XOR_gadget/zkbugs_config.json),
  [direct fixture](../.external/zkbugs/dataset/circom/reclaimprotocol/circom-chacha20/zksecurity_Unsound_XOR_gadget/xor.circom),
  [entrypoint 설정](../.external/zkbugs/dataset/circom/reclaimprotocol/circom-chacha20/zksecurity_Unsound_XOR_gadget/zkbugs_vars.sh)
- [감사 보고서](../.external/zkbugs/reports/documents/zksecurity-reclaimprotocol.pdf), pp. 8–9
- [기존 반례](../runs/dev10-smoke/execution-ebf486be-c22f-4a60-962e-c0c594738137/counterexample-candidates/0002/circuit.circom_wjkTGSo5J8_counterexample.json),
  [stdout](../runs/dev10-smoke/execution-ebf486be-c22f-4a60-962e-c0c594738137/ef4000c1-46fc-4e34-a269-3bf971c5a21e/runs/a96a4865-2ea1-4e59-a9d4-02bc8197c23f/stdout.log),
  [기존 검토](../runs/dev10-smoke/review.md)
- [최소 재현 디렉터리](../runs/xorwords-case-study-2026-09-15/reproduction)

기존 반례 SHA-256은
`6dbcbffe3b707ddb75f763aec08aead29c76639d096d6b1def8a8e0de6bb78a8`, 재현 반례
SHA-256은 `dd354ebe796709665f4b79984c2b7c81751e00c62b7a523acd24416b5fefdf3a`다.

## 실행·검증 명령

아래 명령은 저장소 root에서 실행했다. 소스나 조건을 수정하지 않았다.

```sh
.external/zkFuzz/target/release/zkfuzz \
  runs/xorwords-case-study-2026-09-15/reproduction/circuit.circom \
  --prime bn128 \
  --search_mode ga \
  --save_output \
  --path_to_mutation_setting \
  runs/xorwords-case-study-2026-09-15/reproduction/mutation-settings.json \
  > runs/xorwords-case-study-2026-09-15/reproduction/stdout.log \
  2> runs/xorwords-case-study-2026-09-15/reproduction/stderr.log

shasum -a 256 \
  runs/xorwords-case-study-2026-09-15/reproduction/circuit.circom \
  runs/xorwords-case-study-2026-09-15/reproduction/xor.circom \
  runs/xorwords-case-study-2026-09-15/reproduction/mutation-settings.json
```

비교는 JSON의 `7_assignment`, `5_flag`,
`8_auxiliary_result.mutation_test_log.random_seed`, `generation` 필드에 대해 수행했다.

공유용 묶음은 ignored `runs/` 없이 해시·반례 동일성·위의 산술을 검산할 수 있다.
이 명령은 퍼징을 재실행하거나 원 프로젝트의 proof를 검증하지 않는다.

```sh
python3 experiments/evidence/xorwords-2026-09-15/verify.py
```

## 후속: 원본 revision 대응과 제약 검사 — 2026-09-15

**기존 반례는 확보한 XOR 수정 직전 원본 component에서 거부됐다.** 원본 소스와 테스트를
변경하지 않고 컴파일한 35개 제약 중 33개를 만족하고, 입력 재구성 검사 2개를 위반한다.
새 취약점 발견이나 프로젝트 전체 재현 결과가 아니다. 위의 fixture 재현·반례·확인서는
그대로 유지하며, 이 절은 앞 절의 원본 자료 미확보 상태를 갱신한다.

### 출처와 revision

| 구분 | 확인한 revision과 의미 |
|---|---|
| zkbugs snapshot | `a0eed744ba1a816acaa2fae597f4e79b4fd01aea`: fixture와 메타데이터의 버전 |
| 메타데이터의 project Commit / Fix Commit | 둘 다 `ef9f5a5ad899d852740a26b30eabe5765673c71f`로 기록됨 |
| 확보한 XOR 수정 commit | `ef9f5a5...`, 2023-08-04, `fix: xor circuit security`; Boolean 제약 활성화 및 무조건적인 잔여값 0 검사로 변경 |
| 확보한 XOR 수정 직전 commit | `4551ca64c9fe536b7b9b7498a1feb1ecdc847474`; 위 수정 commit의 직접 부모이며 관련 `XorWords` 코드가 감사 보고서 발췌와 일치 |

원래 `reclaimprotocol/circom-chacha20` 주소의 고정 소스와 commit API는 404를 반환했다.
이는 그 코드가 존재한 적 없다는 증거가 아니다. 공개 fork `reclaim-1/circom-chacha20`에서
동일 `ef9f5a5...`와 부모 소스를 확보했다. GitHub API가 이 fork의 parent/source로 안내한
`Hmac512/circom-chacha20`에서도 같은 수정 commit·tree·부모 hash를 확인했다. 확보한
부모 revision의 README는 설치 저장소로 원래 `reclaimprotocol/circom-chacha20`을 가리킨다.
저장소 이름 변경의 전체 이력까지 확인한 것은 아니다.

감사 PDF에는 정확한 project hash가 없고, p.8 코드는 일부 생략된 발췌다. 따라서
`4551ca64...`를 **XOR 수정 직전의 원본 구현**으로 검증했으며, 감사에 쓰인 전체 snapshot의
정확한 hash라고 단정하지 않는다. PDF p.9의 최종 bit 기반 refactor도 `ef9f5a5...`와 동일한
버전으로 취급하지 않는다. 최신 코드는 사용하지 않았다.

출처·획득 실패·commit 관계·파일별 Git blob/SHA-256은
[후속 출처 기록](evidence/xorwords-original-followup-2026-09-15/source-provenance.json)에 남겼다.
획득한 파일의 Git blob hash를 계산하고 부모 commit의 tree 항목과 대조했다.
[XOR 수정 diff](https://github.com/reclaim-1/circom-chacha20/commit/ef9f5a5ad899d852740a26b30eabe5765673c71f)와
[수정 직전 원본](https://github.com/reclaim-1/circom-chacha20/blob/4551ca64c9fe536b7b9b7498a1feb1ecdc847474/circuits/generics.circom#L47)을 구분해 참조한다.

### 원본 입력·신호·출력 대응

확보한 upstream 자체의 `circuits/tests/xor32bits.circom`가 `XorWords(1,32)`를 main으로
선언한다. 새 harness나 입력 조건을 만들지 않고 이 테스트와 `generics.circom`을 원래
상대 경로로 복사했다. 두 파일은 다운로드한 원본과 byte 단위로 같다.

| 기존 fixture 신호 | 원본 테스트 신호 | 적용한 대응 |
|---|---|---|
| `main.a`, `main.xor.a` | `main.a[0]` | 값 `6` 유지; 두 alias의 동일성 확인 |
| `main.b`, `main.xor.b` | `main.b[0]` | 값 `1` 유지; 두 alias의 동일성 확인 |
| `main.out`, `main.xor.out` | `main.out[0]` | 실제 출력 `p-17,179,770,361` 유지; expected `7`로 바꾸지 않음 |
| `main.xor.a_bits[k]` | `main.abits[31-k]` | 원본이 높은 자리부터 순회하므로 인덱스 반전 |
| `main.xor.b_bits[k]` | `main.bbits[31-k]` | 같은 인덱스 반전 |
| `main.xor.xor_bits[k]` | `main.xors[31-k]` | 같은 인덱스 반전 |

대응 후 비영 bit 값은 `abits[30]=1`, `abits[29]=1`, `abits[3]=p-64`,
`bbits[31]=1`, `bbits[22]=1`, `bbits[17]=6`이다. `xors`는 이 서로 겹치지 않는
위치에서 같은 값을 가진다. 전체 비영 신호는 아래 결과 JSON에도 기록했다.
원본의 `ain`, `bin`, `out2`는 계산용 `var`이며 추가 witness 신호가 아니다.
필드 값의 변환, 새 입력 전제, 추가 연결 제약은 없다.

### 변경 없는 원본 제약에서의 결과

로컬 `circom 2.2.3`으로 원본 테스트를 `--r1cs --sym --O0 --prime bn128` 설정으로
컴파일했다. 당시의 2023년 컴파일러나 배포 proof artifact를 복원한 것은 아니다.
검증 스크립트는 `.sym`으로 99개 신호를 모두 대응하고 상수 wire 0을 1로 지정한 뒤,
R1CS의 모든 `A(w) × B(w) - C(w)`를 필드에서 평가한다. 누락 신호를 0으로 채우지
않으며, witness 생성기로 기존 내부 값을 교체하지 않는다.

32개 XOR 식과 출력 packing 식은 만족한다. 다음 두 식만 거부되며, 스크립트에서
원본 83–84행의 식과 컴파일된 제약의 계수가 정확히 같은 것도 확인했다.

| R1CS 번호(0부터) | 원본 제약 | 기존 반례 대입 결과 (mod p) |
|---|---|---|
| 32 | `(a[0] - Σ abits[j]·2^(31-j)) * a[0] === 0` | `17,179,869,184 × 6 = 103,079,215,104`, 0이 아님 |
| 33 | `(b[0] - Σ bbits[j]·2^(31-j)) * b[0] === 0` | `(1 - 98,817) × 1 = p-98,816`, 0이 아님 |

검사 결과는 [component-check.json](evidence/xorwords-original-followup-2026-09-15/component-check.json),
검사 코드는 [check_r1cs.py](evidence/xorwords-original-followup-2026-09-15/check_r1cs.py)다.
원본을 이미 확보한 현재 작업 공간에서는 아래 명령으로 확인할 수 있다. 기본 출력은
stdout이며, `--output`을 지정해도 기존 결과 파일 덮어쓰기를 거부한다. 종료 코드 0은
검사 완료를 뜻하고, 반례 통과 여부는 `candidate_satisfies_original_component=false`로 구분한다.

```sh
python3 experiments/evidence/xorwords-original-followup-2026-09-15/check_r1cs.py
```

다른 checkout에서는 먼저 아래 두 고정 소스를 받아야 한다. 스크립트가 내용 해시를
확인하므로 다른 revision의 파일로 대체할 수 없다. 다른 caller 소스의 주소와 해시는
후속 출처 기록에 있으며, 원본 소스·컴파일 결과는 ignored `runs/`에만 보관했다.

```sh
mkdir -p runs/xorwords-original-followup-2026-09-15
gh api 'repos/reclaim-1/circom-chacha20/contents/circuits/generics.circom?ref=4551ca64c9fe536b7b9b7498a1feb1ecdc847474' --jq .content \
  | python3 -c 'import base64,sys; sys.stdout.buffer.write(base64.b64decode(sys.stdin.read()))' \
  > runs/xorwords-original-followup-2026-09-15/parent-generics.circom
gh api 'repos/reclaim-1/circom-chacha20/contents/circuits/tests/xor32bits.circom?ref=4551ca64c9fe536b7b9b7498a1feb1ecdc847474' --jq .content \
  | python3 -c 'import base64,sys; sys.stdout.buffer.write(base64.b64decode(sys.stdin.read()))' \
  > runs/xorwords-original-followup-2026-09-15/parent-xor32bits.circom
```

### Component와 프로젝트 도달성의 경계

원본 entrypoint/caller는 이번에 확보했다. [원래 main](https://github.com/reclaim-1/circom-chacha20/blob/4551ca64c9fe536b7b9b7498a1feb1ecdc847474/circuits/circuit.circom#L5)은
`main{public [in]} = ChaCha20(16)`이다. [최종 word XOR](https://github.com/reclaim-1/circom-chacha20/blob/4551ca64c9fe536b7b9b7498a1feb1ecdc847474/circuits/chacha20.circom#L29)은
`a[0]`를 입력 word에, `b[0]`를 ChaCha20 block 출력에 연결한다. Quarter round 내부에도
`XorWords(1,32)` 호출이 있다. 따라서 앞 절의 미확보는 **당시 로컬에 원본이 없었고
확인한 보고서에도 완전한 caller가 제시되지 않았다는 뜻**이며, upstream에 없다는 뜻은 아니다.

| 확인 범위 | 이번 결론 |
|---|---|
| fixture 반례 | 기존 재현과 산술 확인을 재사용; 성립 |
| 확보한 수정 직전 원본 component | 같은 입력·내부 값·출력의 대응 확정; 원본 재구성 제약 2개 위반 |
| 프로젝트 entrypoint/caller | 정적 호출 구조는 확보; 실제 입력으로 `a=6,b=1`에 도달하는지와 전체 witness/proof는 미검증 |
| 감사 당시의 정확한 전체 revision | 보고서에 hash가 없어 미확정; 수정 직전 구현과 관련 발췌의 일치까지 확인 |

이 **정확한 전체 신호 대입**은 원본 component에서 거부되므로 그 상태로 프로젝트 witness로
확장할 수 없다. 입력 `6,1`만을 쓰는 다른 내부 대입의 가능성이나 다른 입력의 결함은
이번 검사의 대상이 아니다. `wrapper-only`는 기존 증거의 적용 범위이며, wrapper가 문제를
만들었다는 인과 판단이 아니다. 원본에도 감사에서 보고된 결함 구조가 있었고 fixture와
원본의 제약은 다르다. 원본의 일반적 안전성이나 실제 프로젝트 공격 가능성은 이 결과로
판정하지 않는다. 이 후속 질문의 조사·검증은 여기서 종료한다.

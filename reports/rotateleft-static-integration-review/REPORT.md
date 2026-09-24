# RotateLeft32Bits static integration review

검토일: 2026-09-19

## 범위와 버전

이번 검토는 이전 [fixture 충실도 보고서](../rotateleft-fixture-fidelity-2026-09-15/REPORT.md)와 [구조화 결과](../rotateleft-fixture-fidelity-2026-09-15/comparison.json)의 판정을 유지하면서, 실제 프로젝트의 정적 인스턴스화 경로와 32-bit 입력 전제만 확인했다.

검토한 upstream 소스는 `reclaim-1/circom-chacha20`의 고정 revision **`ef9f5a5ad899d852740a26b30eabe5765673c71f`**이다. RotateLeft 수정 `e5e756375fc1fc8dc48667b00cdf38c79a0fdf50`의 직접 부모라는 기존 provenance를 재사용했다. 고정 commit archive의 SHA-256은 `8b81d8fe5d70ae7fb4fb8cb683449bf06b303b9799ad589b95b6a55cff2f399f`이다. 각 파일의 Git blob과 SHA-256은 [evidence.json](evidence.json)에 기록했다.

현재 zkfDO 작업 트리는 commit `020ef5bde018f8562a0476e16c5ce58bda36d23e`이며 upstream 원본으로 사용하지 않았다. `.external`의 현재 동명 파일도 근거로 사용하지 않았다. 감사 보고서에 전체 프로젝트 commit이 없으므로 `ef9f5a…`과 감사 당시 전체 snapshot의 동일성은 계속 미확인이다.

요청된 이전 보고서와 `comparison.json` 외에 RotateLeft 반례·witness·실험 실행 산출물은 열거나 평가하지 않았다. 컴파일·witness 생성·퍼징도 수행하지 않았고 기존 소스와 실험 파일은 변경하지 않았다.

## 판정

| 질문 | 판정 |
|---|---|
| 고정 원본의 설정된 배포 빌드가 RotateLeft에 도달하는가 | **확인.** `ChaCha20(16) → ChaCha20Block → QR → RotateLeft32Bits` 경로가 존재한다. |
| 실제 QR 안의 회전 입력이 32-bit로 제한되는가 | **확인. 회로 제약에 의한 보장.** 네 회전 모두 바로 앞 `XorWords(1,32)`의 32-bit 출력에 연결된다. |
| `RotateLeft32Bits` 자체가 입력 범위를 강제하는가 | **아니오.** 주석으로 전제하며 `<--` witness 계산은 범위 제약이 아니다. |
| 라이브러리 외부 입력 검증이 완전한가 | **아니오.** key·IV·ciphertext는 unsigned 32-bit word로 변환되지만 `startCounter`에는 runtime 정수·범위 검사가 없다. |
| dev3의 `L=3`이 실제 프로젝트 빌드에 사용되는가 | **고정 snapshot에서 인스턴스화가 발견되지 않음.** 실제 값은 `16, 12, 8, 7`이다. |
| 포함된 WASM·zkey가 정확히 이 source로 빌드됐는가 | **미확인.** 설정 경로는 확인했지만 source-to-artifact provenance는 없다. |

이 결과는 실제 caller가 회전 입력 전제를 충족한다는 정적 판정이다. RotateLeft 구현 전체의 정확성, 안전성, 기존 후보의 유효성은 판정하지 않는다.

## 실제 빌드 및 사용 경로

아래 줄 번호는 모두 고정 revision `ef9f5a…`의 repository-relative 경로다.

1. `package.json:6-12`의 `build:circuit`가 `scripts/build-circuit.sh`를 실행한다.
2. `scripts/build-circuit.sh:1-5`는 `circom circuits/circuit.circom --r1cs --wasm --O2 --inspect -o resources`를 실행한다.
3. `circuits/circuit.circom:1-5`는 `chacha20.circom`을 include하고 `component main{public [in]} = ChaCha20(16)`을 만든다.
4. `circuits/chacha20.circom:18-35`에서 `N/16`개의 `ChaCha20Block`을 만들므로 `N=16`인 실제 main에는 block이 1개다.
5. `circuits/chacha20.circom:39-132`에서 block 하나는 10회 반복마다 column QR 4개와 diagonal QR 4개, 총 QR 80개를 만든다.
6. 각 QR은 `circuits/chacha20.circom:152-218`에서 `RotateLeft32Bits(16)`, `(12)`, `(8)`, `(7)`을 각각 한 번 사용한다.

따라서 설정된 전체 빌드에는 parameter별 80개, 총 **320개**의 RotateLeft 인스턴스가 있다.

배포 artifact 연결도 정적으로 존재한다. `scripts/build-circuit.sh:7-14`는 생성한 R1CS로 `resources/circuit_final.zkey`를 만들고, `src/operator.ts:10-22`는 `resources/circuit.wasm`과 그 zkey를 기본 operator에 연결한다. `src/zk.ts:26-55`의 `generateProof`가 입력을 operator에 전달하고 `src/operator.ts:28-45`가 `snarkjs.groth16.fullProve`를 호출한다.

다만 build command에는 `--prime`과 Circom 버전 pin이 없다. `readme.md:90-107`은 현재 BN-128을 쓴다고 설명하지만 이는 문서 기록이다. 커밋에 들어 있는 WASM·zkey를 이번에 재빌드하거나 source hash와 연결하지 않았으므로, 저장된 artifact가 정확히 `ef9f5a…`에서 생성됐다고 승격하지 않는다.

## 정의·테스트·실제 사용의 구분

| 위치 | 분류 | 의미 |
|---|---|---|
| `circuits/generics.circom:35-46` | 정의 | `RotateLeft32Bits(L)` template 정의. 이것만으로 인스턴스화되지 않는다. |
| `circuits/chacha20.circom:1-3` | import | `generics.circom` include. 실제 사용 근거는 별도의 QR call site다. |
| `circuits/chacha20.circom:152-218` | **실제 빌드 경로** | QR에서 `L=16,12,8,7`을 인스턴스화하고 출력이 다음 상태로 이어진다. |
| `circuits/tests/rotateLeft32bits.circom:9-30` | 직접 component 테스트 | 같은 네 parameter를 한 번씩 시험하지만 배포 entrypoint가 아니다. |
| `src/tests/circuits.test.ts:79-105,267-269` | 테스트 driver | `circuits/tests/rotateLeft32bits.circom`을 별도로 불러 선택된 입력으로 검사한다. |

직접 RotateLeft 테스트 wrapper에는 `in`을 32-bit로 분해하거나 범위를 확인하는 제약이 없다. 테스트 코드가 32-bit 값만 넣는 것은 테스트 데이터의 가정이지 모든 가능한 witness를 제한하는 회로 제약이 아니다.

## 실제 회전 입력의 32-bit 보장

네 경로는 다음과 같다.

| parameter | 회전 직전 producer | 연결 위치 | 판정 |
|---:|---|---|---|
| 16 | `xor1.out[0]` | `circuits/chacha20.circom:158-167` | 회로 제약으로 unsigned 32-bit |
| 12 | `xor2.out[0]` | `circuits/chacha20.circom:175-184` | 회로 제약으로 unsigned 32-bit |
| 8 | `xor3.out[0]` | `circuits/chacha20.circom:192-201` | 회로 제약으로 unsigned 32-bit |
| 7 | `xor4.out[0]` | `circuits/chacha20.circom:209-218` | 회로 제약으로 unsigned 32-bit |

근거는 고정 revision의 `XorWords(1,32)`이다.

- `circuits/generics.circom:72-73`의 `abits`와 `bbits` 계산은 `<--` witness 대입이므로 그 자체는 보장이 아니다.
- `circuits/generics.circom:76-77`이 각 bit를 Boolean으로 제약한다.
- `circuits/generics.circom:78`이 `xors[l]`을 Boolean 입력의 XOR 다항식에 연결한다.
- `circuits/generics.circom:80-82,89`가 32개 XOR bit의 가중합을 `out[i]`에 제약한다. 문서화된 BN128에서는 이 합이 `0..2^32-1` 안에 있다.
- `circuits/generics.circom:87-88`은 XorWords의 두 입력도 각각 32-bit bit 분해와 같도록 제약한다.

각 `rot*.in <== xor*.out[0]` 연결은 실제 제약이다. 따라서 RotateLeft component 내부의 주석 전제에 의존하는 직접 wrapper와 달리, 확인한 QR caller 네 경로는 입력 전제를 회로 안에서 충족한다.

## 외부 입력 처리와 회로 제약의 구분

| 입력 | 외부 라이브러리 처리 | 분류 |
|---|---|---|
| key | `src/zk.ts:35-46`에서 32-byte 길이를 검사하고 `src/utils.ts:3-9`에서 `readUInt32LE`로 변환 | runtime 검증·변환 |
| IV/nonce | `src/zk.ts:38-46`에서 12-byte 길이를 검사하고 동일하게 변환 | runtime 검증·변환 |
| ciphertext | `src/zk.ts:117-136`에서 `Uint32Array`로 변환·padding하고 16 word 길이를 검사 | runtime 검증·변환 |
| `startCounter` | `src/zk.ts:48-54`에서 JavaScript number를 그대로 전달 | runtime 범위 검사 없음 |

`src/types.ts:60-69`의 `@minimum 1`은 주석이며 runtime 검사가 아니다. key·nonce·ciphertext를 `Uint32Array`로 만드는 외부 경로는 정상 API 사용을 보조하지만, 실제 회전 입력의 강한 근거는 위 `XorWords` 회로 제약이다. 라이브러리를 통하지 않고 회로를 직접 호출하는 사용자는 외부 변환의 보호를 받지 않는다.

## 기존 L=3 결과의 적용 범위

이전 검토는 direct wrapper의 `RotateLeft32Bits(3)`, 명시적 `bn128`, `O0` 조건에서 fixture와 고정 원본의 R1CS 동일성을 확인했다. 이번 고정 snapshot 전체에서 `RotateLeft32Bits` 인스턴스화를 검색한 결과 실제 빌드와 직접 테스트 모두 `16,12,8,7`만 사용한다.

따라서 기존 `L=3` 결과는 다음에는 사용할 수 있다.

- dev3 direct fixture가 고정 원본의 `RotateLeft32Bits(3)` 제약계를 보존했다는 주장
- `L=3` direct component 후보를 원본 component 수준에서 사후 검증할 때의 provenance

다음에는 직접 적용할 수 없다.

- 프로젝트 entrypoint에서 `L=3`이 도달 가능하다는 주장
- `L=16,12,8,7` 각각의 R1CS가 fixture와 동일하다는 주장
- `O2` 전체 `ChaCha20(16)` 빌드나 배포 WASM·zkey의 exact equivalence

## 미확인 사항과 보완 조치

미확인 사항은 감사 당시 전체 snapshot, 고정 source와 배포 artifact의 exact provenance, repository 밖 downstream caller, 실제 parameter 네 개와 전체 O2 entrypoint의 R1CS 대응이다.

프로젝트 문맥 결함을 집계하려면 다음 보완이 필요하다.

1. `L=16,12,8,7` 또는 전체 `ChaCha20(16)`을 대상으로 고정 source와 평가 target의 대응을 별도로 확인한다.
2. Circom 버전과 prime을 pin하고 source·R1CS·WASM·zkey hash를 한 provenance record로 묶는다.
3. direct component 후보는 32-bit 입력 전제를 별도로 강제하거나 검증한 뒤에만 유효 결함으로 센다.
4. API 경계까지 보안 주장에 포함한다면 `startCounter`의 정수·uint32 runtime 검사를 추가 검토한다.

이번 정적 검토만으로 RotateLeft 전체의 정확성이나 안전성을 확정하지 않는다.

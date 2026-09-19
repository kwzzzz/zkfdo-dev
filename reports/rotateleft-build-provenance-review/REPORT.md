# RotateLeft build and artifact provenance review

검토일: 2026-09-19

## 범위와 결론

고정 원본은 `reclaim-1/circom-chacha20@ef9f5a5ad899d852740a26b30eabe5765673c71f`이다. 이전 [정적 통합 검토](../rotateleft-static-integration-review/REPORT.md)와 [fixture 충실도 검토](../rotateleft-fixture-fidelity-2026-09-15/REPORT.md)의 판정은 변경하지 않았다.

| 항목 | 상태 | 결론 |
|---|---|---|
| 설정된 entrypoint와 O2 옵션 | **확인 완료** | `circuits/circuit.circom`, `ChaCha20(16)`, `--O2 --inspect`가 source에 명시돼 있다. |
| 과거 Circom compiler 버전 | **미확인** | 외부 prerequisite이며 version pin·container·build log가 없다. |
| build command의 prime 고정 | **부재 확인** | `--prime`/`-p`가 없다. 문서는 BN128을 설명하고 보존 zkey도 BN128이지만 과거 compiler/default 기록은 없다. |
| JavaScript 의존성 버전 | **확인 완료** | lockfile에서 `snarkjs 0.7.0`, `circom_tester 0.0.19` 등을 확인했다. |
| repository/공개 GitHub CI 기록 | **부재 확인** | 고정 tree에 CI 설정·manifest·build log가 없고 해당 commit의 status/check/action run도 0건이다. 외부 비공개 빌드는 배제하지 않는다. |
| `L=16,12,8,7` direct 대응 | **확인 완료** | 현재 비교 환경에서 각 parameter의 fixture와 고정 원본 R1CS·심볼이 바이트 단위로 같다. |
| 전체 `ChaCha20(16)/O2` 대응 | **미확인** | 고정 원본 baseline은 생성했지만 비교할 fixture/full-circuit artifact와 과거 R1CS가 없다. |
| 보존 WASM·zkey의 파일 정체성 | **확인 완료** | Git blob, 크기, SHA-256과 정적 metadata를 기록했다. |
| 보존 WASM·zkey가 `ef9f5a…` source에서 생성됐는가 | **미확인** | source hash와 artifact를 연결하는 검증 가능한 build provenance가 없다. |
| witness·proof·trusted setup·정확성/안전성 판정 | **범위 밖** | 수행하거나 판정하지 않았다. |

구조화된 명령·해시·API 응답 해시는 [evidence.json](evidence.json)에 있다.

## 빌드 환경 근거

아래 줄 번호는 모두 고정 revision `ef9f5a…` 기준이다.

- `package.json:6-12`의 `build:circuit`는 `scripts/build-circuit.sh`를 실행한다.
- `scripts/build-circuit.sh:1-5`의 실제 명령은 `circom circuits/circuit.circom --r1cs --wasm --O2 --inspect -o resources`다.
- `circuits/circuit.circom:1-5`의 main은 `ChaCha20(16)`이다.
- `scripts/build-circuit.sh:7-17`은 R1CS와 ptau로 zkey를 만들지만 zkey 검증 명령은 주석 처리돼 있다.

### 과거 설정과 현재 비교 설정의 분리

| 설정 | repository에 남은 근거 | 판정 |
|---|---|---|
| 최적화 | build script에 `--O2` | **확인 완료** |
| prime | build command에는 없음. `readme.md:95-107`은 현재 BN-128이라고 설명하고 보존 zkey metadata는 `bn128` | 명시적 pin은 **부재 확인**, 과거 command 환경은 **미확인** |
| Circom 버전 | `readme.md:80-100`이 설치를 요구할 뿐 버전을 고정하지 않음 | **미확인** |
| Node/npm 버전 | `.nvmrc`, container, engines 기반 build pin 없음 | **미확인** |
| snarkjs | `package-lock.json:3975-3990`에 `0.7.0` | **확인 완료** |
| circom_tester | `package-lock.json:1711-1723`에 `0.0.19`; 이것은 build compiler pin이 아님 | **확인 완료** |
| Jest/TypeScript | `package-lock.json:2664-2676,4273-4288,4413-4424`에 각각 Jest `29.5.0`, ts-jest `29.1.0`, TypeScript `5.1.3` | **확인 완료** |

`package-lock.json:1-29`는 lockfile version 3과 root dependency 범위를 기록한다. 반면 Circom compiler는 npm dependency가 아니며 build script가 PATH의 `circom`을 직접 호출한다.

현재 설치된 Circom 2.2.3과 snarkjs 0.7.6은 이번 재현 비교·metadata 열람 도구로만 기록했다. 과거 배포 도구 버전으로 취급하지 않았다.

### ptau와 빌드 기록

`scripts/download-ptau.sh:1-3`은 BN128용 ptau URL을 제공하지만 expected hash를 확인하지 않는다. `scripts/generate-ptau.sh:1-17`에는 별도의 BLS12-381 생성 경로가 있고 검증 명령은 주석 처리돼 있다. 고정 tree의 `pot/`에는 빈 `.gitadd`만 있으며 실제 `pot18_final.ptau`는 없다.

고정 tree에서 `.github`/CircleCI 설정, Dockerfile, build manifest, build log를 찾지 못했다. GitHub API에서도 `ef9f5a…`의 commit status, check run, Actions run은 각각 0건이었다. 따라서 repository에서 확인 가능한 과거 build record의 부재는 확인했지만, repository 밖 기록이 존재하지 않는다고 일반화하지 않는다.

## 실제 parameter의 대응 확인

비교 양쪽은 다음과 같이 고정했다.

| 구분 | source | wrapper |
|---|---|---|
| fixture | 이전 검토가 보존한 `generics.circom`, SHA-256 `cdd4afc861b5b07de22aa90fe81f0d9142882964586e8531185ca3422c745bae` | parameter별 `component main {public [in]} = RotateLeft32Bits(L);` |
| 원본 | `ef9f5a…:circuits/generics.circom`, SHA-256 `4dca4517b1804c8d3a6c9fa0699bb31633a117ca1f0e6df7a45d352beb94d366` | fixture와 바이트가 같은 parameter별 wrapper |

재현 설정은 **현재 Circom 2.2.3, `--O2 --inspect --prime bn128`, R1CS와 `.sym`만 생성**이다. 이는 실제 source의 O2와 문서·zkey의 BN128에 맞춘 비교 설정이며 과거 compiler 환경 증거가 아니다.

| L | wrapper SHA-256 | R1CS SHA-256 | `.sym` SHA-256 | fixture ↔ 원본 |
|---:|---|---|---|---|
| 16 | `0c35231d5a2be3dfba317b55de301ab7e9a4377e4cb9925ec0cb6c7e0e63fde3` | `729ff97ef99dbf75cef5781ecef0d42107568191b4aa35359492222c19b61a5f` | `6ee1dc69b2bc33d24769352d74a029cb36cde8328f18ee9ecf8213fe2930e1d7` | **바이트 동일** |
| 12 | `3fd1b1cfb3474cb464780c443fb2b03cf80671ad680d2f4a7c9e1a951d50eb6a` | 동일 | 동일 | **바이트 동일** |
| 8 | `5760e02e38393dde5164b4107e76c0955dea0a933769e55da6340ca6fd10e6dc` | 동일 | 동일 | **바이트 동일** |
| 7 | `a28b98749aab8fa13956b44f3f116813d8f90bd10ad869c81b10296309aece65` | 동일 | 동일 | **바이트 동일** |

각 결과는 wires 3, labels 5, public output 1, public input 1, constraints 0이다. O2가 `part1`과 `part2`를 `.sym`의 wire `-1`로 최적화한 결과도 양쪽에서 같다. 이 표는 명시한 환경에서 생성물의 정확한 동일성만 뜻한다. 0 constraint의 의미, O0/O2 의미 동등성, 구현 안전성은 이번 결과로 판정하지 않는다.

기존 `L=3/O0/bn128` 결과와 이번 결과를 합치면 direct fixture와 고정 원본의 대응 범위는 넓어지지만, `L=3`의 프로젝트 도달성을 만들지는 않는다.

## 전체 ChaCha20(16)/O2

고정 원본 전체 entrypoint를 현재 비교 환경에서 `--O2 --inspect --prime bn128`로 한 번 컴파일했다. 새 WASM은 만들지 않았다.

| 항목 | 현재 baseline |
|---|---:|
| wires | 32,269 |
| public outputs / inputs / private inputs | 16 / 16 / 12 |
| labels | 36,605 |
| constraints | 32,592 |
| R1CS SHA-256 | `3c4c4596ecfb37b249b94ab437124c660f0f8427696e830a46428d96fd2d9cb3` |
| `.sym` SHA-256 | `e38c608435a78b56f501cdf3d913d40386a383f163840c6c9f300f4b04dc8541` |

대응하는 dev3 fixture, historical R1CS, compiler 기록이 없으므로 전체 회로 동일성은 **미확인**이다. 이 새 baseline을 과거 배포물의 provenance 증거로 사용하지 않았다.

## 배포 WASM·zkey

기본 operator는 `src/operator.ts:10-22`에서 아래 두 파일을 참조한다.

| 파일 | 크기 | Git blob | SHA-256 | 정적 metadata |
|---|---:|---|---|---|
| `resources/circuit.wasm` | 180,868 B | `0751087eeb00c0ca579290d4e3b2190ac71f17b9` | `832a40dee8dc64f2a1bd5e56caed83a42e939846d8bd477c4983e99d5bf94456` | WebAssembly version 1; 실행하지 않음 |
| `resources/circuit_final.zkey` | 13,647,982 B | `0c928b96317f9e0c4794d0bcdf9014f85a56a541` | `783acd4aceb66baa24bb253b426f6eab3bfd935facee9564d30678ef439b2bfe` | Groth16, BN128, `nPublic=32` |

zkey metadata는 현재 snarkjs 0.7.6으로 verification key만 임시 export해 읽었다. zkey를 재생성하거나 trusted setup을 수행하지 않았다. 새 full baseline도 public output 16개와 public input 16개로 합계 32개이므로 coarse metadata는 일치한다. 이것은 많은 회로가 공유할 수 있는 값이며 source provenance가 아니다.

### 파일 이력

- WASM은 `e37b573bfcd3c4923e7dc328f45ba0229458c1fb`(2023-06-25)에서 마지막으로 변경됐다.
- zkey는 `9f98e3aaa95e629515883e0cc6e6cfe6aef6d622`(2023-06-25)에서 마지막으로 변경됐다.
- 이후 `4551ca64c9fe536b7b9b7498a1feb1ecdc847474`(2023-08-04)가 Add 제약 source를, `ef9f5a…`(2023-08-04)가 XOR 제약 source를 변경했지만 두 artifact blob은 갱신되지 않았다.

따라서 “artifact 파일이 고정 source와 같은 commit tree에 있다”는 사실을 source 연결 증거로 사용할 수 없다. repository history와 공개 GitHub metadata에는 `ef9f5a…` source hash, compiler, 명령, R1CS, WASM, zkey를 묶는 manifest나 build attestation이 **없음**을 확인했다. 다만 과거 artifact가 어떤 외부 source로 만들어졌는지까지 이 이력만으로 확정할 수 없으므로 exact provenance 판정은 **미확인**이다.

## 실제 수행 및 미수행

실제로 수행했다.

- 고정 source·build script·lockfile·ptau script·GitHub-visible CI metadata 정적 검토
- WASM·zkey의 SHA-256, Git blob, 크기와 변경 이력 확인
- 기존 WASM은 실행하지 않고 header만 정적 확인
- 기존 zkey에서 protocol·curve·공개 신호 수 metadata만 읽음
- `L=16,12,8,7` fixture/원본 direct R1CS·심볼 비교
- 고정 원본 전체 `ChaCha20(16)`의 현재-tool R1CS·심볼 baseline 생성

수행하지 않았거나 판정하지 않았다.

- witness·반례·proof 생성 또는 평가 — **범위 밖**
- 기존 WASM 실행 — **범위 밖**
- zkey 재생성, 기여, beacon, trusted setup — **범위 밖**
- zkey와 새 R1CS의 검증 — exact ptau가 없어 **미확인**
- 과거 compiler 재현, O0/O2 의미 동등성, 전체 RotateLeft 정확성·안전성, 후보 유효성 — **범위 밖**

exact provenance 결론을 내려면 과거 Circom 실행 파일 또는 정확한 버전·container, 실제 사용한 `pot18_final.ptau`와 신뢰 가능한 hash, historical `circuit.r1cs`, 그리고 source commit부터 R1CS·WASM·zkey hash까지 연결하는 build log 또는 서명된 manifest가 필요하다.

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

# H1 탐색 사냥 퍼징 준비와 실행 (2026-10-25)

상태: 실행 중. 담당: miiz.

- 성격: N5 고정 목록 밖의 탐색용 사냥이다. 결과는 평가 표와 합치지 않는다.
- 후보: 후보 값은 열지 않는다. 후보는 결함 판정이 아니며, J 판정과 사람 검토가 필요하다.
- 제보: 후보가 확인되면 4절 4항처럼 비공개로 제보하고, 그 전에는 발표·공유 자료에 대상 이름과 재현 값을 쓰지 않는다.

## 대상과 예산

| 대상 | main | S로 쪼갠 단위 |
|---|---|---:|
| HoomanBuilds/moros `06b9bf35` | `contracts/shielded-collateral-vault/circuits/batch.circom` | 72 |
| | `contracts/shielded-collateral-vault/circuits/exit_match.circom` | 76 |
| | `contracts/payment-circuits/transfer_four.circom` | 77 |
| ethstorage/zk-decoder `0c2db000` | `circom/circuits/blob_poseidon_2.circom` | 75 |
| | `circom/circuits/blob_poseidon.circom` | 74 |

- main마다 S 2 seed(2026102501, 2026102502)와 W 1 seed(2026102501)를 돌린다. 한 실행은 30분이고, S의 시도 상한은 30초다.
- 모두 15단위이고, 동시에 2개씩 큰 대상부터 돌린다. 맥 메모리가 24 GiB라 단위당 메모리 상한을 10 GiB로 두었다.
- zkFuzz는 N6-B5에서 중첩 배열을 고친 바이너리다(SHA-256 `f4d992e707c4227de99467adf38bae3ad98573ec5ababe09e391429d7c2542f0`). 단위 실행기는 `scripts/run_policy_a_engine_v4.py`다.

## 방법

`scripts/h1_hunt_prepare.py`는 기존 코드를 재사용한다. 대상 탐색·준비·실행 계획은 E-02의 `prepare_one`, spec 생성은 N6-B의 `create_specs`를 쓴다. 동작은 prepare, specs, preflight, run 네 가지다. 산출물은 `runs/h1-hunt-2026-10-25.noindex/`에 있다.

준비 중에 보정한 것:

1. **circomlib 경로:** circomlib 2.0.5는 로컬 사본을 썼다. EthStorage는 링크가 프로젝트 밖이라 준비가 막혀서, 클론 안에 사본을 복사했다.
2. **디스크 관문:** 이 스크립트에서만 E-02의 내장 디스크 관문을 35 GiB에서 22 GiB로 낮췄다. 실행 중에는 15 GiB 아래에서 새 단위를 시작하지 않는다.
3. **출력 위치:** 사전 검사와 실행 출력은 내장 디스크에 둔다. 실행기가 스냅샷을 clonefile로 복사하는데, 디스크가 다르면 실패하기 때문이다.
4. **W 라이브러리 경로:** W 명령 끝에 기록된 원래 라이브러리 절대 경로를 덧붙였다. S는 원래 이렇게 하고 있었고, B 생성기는 프로젝트 밖 라이브러리를 스냅샷 경로로 잘못 바꾼다.
5. **moros pragma:** zkFuzz에 내장된 circom 파서는 2.2.1까지만 받는다. 첫 실행에서 moros 시도가 모두 즉시 실패했다(후보 0, 기록 보존).
   - 퍼징용 클론에서 `pragma circom 2.2.2/2.2.3;` 35줄만 `2.2.1`로 바꿨다(`runs/h1-candidates-2026-10-25/moros-pragma-2.2.1.patch`, SHA-256 `7f4f2a2a0eefe0b1414647659afb23edc23f4155ed645b599e137c3ef9475078`).
   - 바꾼 소스를 circom 2.2.3으로 다시 컴파일했더니 세 main의 R1CS가 배포 manifest SHA와 같았다.
   - bus와 tag 문법은 쓰지 않는다.

실패한 시도의 파일은 지우지 않고 `/Volumes/zkfdo-jcache/moved-from-internal-2026-10-25/h1-hunt/`로 옮겼다.

## spec (15개, `runs/h1-hunt-2026-10-25.noindex/specs/`)

`units.json` SHA-256 `c523f8a71c478ba5fdf845c5581f0cc9c007bd54c5c959c76ecb44989aed2699`

| 단위 | spec SHA-256 |
|---|---|
| moros-batch S 01 / W 01 / S 02 | `c28bab83…` / `44445008…` / `9acd06d2…` |
| moros-exit-match S 01 / W 01 / S 02 | `c41e2d71…` / `9d52c1f4…` / `80d5e02e…` |
| moros-transfer-four S 01 / W 01 / S 02 | `ef1db859…` / `748b7b11…` / `8acb92b0…` |
| edec-blob-poseidon-2 S 01 / W 01 / S 02 | `f30fb9f5…` / `af1b8ba6…` / `48d11358…` |
| edec-blob-poseidon S 01 / W 01 / S 02 | `11d6ebd9…` / `65640c4d…` / `0a3d58dd…` |

사전 검사는 15/15 통과했다.

## 실행

- EthStorage 5단위: 22:42 KST에 시작했다. 명령은 `python3 scripts/h1_hunt_prepare.py --action run --only edec`다.
- moros 9단위: EthStorage가 끝나면 `--only moros`로 자동으로 이어서 시작한다.
- 결과는 단위별 ledger(`outputs/runs/<unit>/out/`)의 결과 개수로만 보고한다.

# H1 사냥 후보 사전 조사: clone·컴파일 (2026-10-25)

상태: 조사 기록. 목록 고정 전. 담당: miiz. 퍼징·판정은 하지 않았다. 대상 선택은 miiz가 이 기록을 보고 한다.

## 방법

- 대상: 웹 조사(`runs/h1-candidates-2026-10-25/codex-web-candidates.md`)에서 배포 근거가 가장 강하고 회로 감사 흔적이 없는 6개를 골랐다. moros, TONresistor, zul, EthStorage zk-decoder, b402-solana, vocdoni franchise.
- clone: `runs/h1-candidates-2026-10-25/clones/`에 `--depth 1`로 받았다.
- 컴파일: circom 2.2.3으로 한 번씩만 했다. 의존성은 설치하지 않았다. circomlib 2.0.5는 기존 로컬 사본(`runs/c03-corpus-2026-10-02/.../0xbow-io__privacy-pools-core/clone/node_modules/circomlib`)을 연결했다. 6개 repo 모두 package.json에서 circomlib 2.0.5를 쓴다.
- 옵션: 각 repo의 빌드 스크립트에 있는 prime과 최적화 옵션을 그대로 썼다.
- 스크립트: `runs/h1-candidates-2026-10-25/compile_h1.py` SHA-256 `201bc357beed8ec9f7f5a588e784de06a5f1cb2d3dfc88f7643eca1437a40a49`
- 결과: `runs/h1-candidates-2026-10-25/compile-results.json` SHA-256 `54418757650715054f4b1ce8a46c2cc31945cd13e7ecba5a89c3d0c8822754e5`

## 결과

| repo · commit | 배포 main | 배포 근거 (repo 안에서 확인) | 감사 | 컴파일 | 제약 수 (비선형 + 선형) | 비고 |
|---|---|---|---|---|---|---|
| HoomanBuilds/moros `06b9bf35` (2026-08-25) | payment 7개(`contracts/payment-circuits/*.circom`), prediction 15개(`contracts/shielded-collateral-vault/circuits/*.circom`) | `deployments/payments-mainnet-proving.json:28`부터, `deployments/private-mainnet-proving.json:31`부터: 회로별 source와 r1cs SHA-256. **우리가 컴파일한 R1CS 22개가 배포 manifest의 r1cs SHA-256과 22/22 일치.** README.md:69-85 Stellar 메인넷 계약표 | README.md:881 "No independent external security audit has been completed" | 22/22 성공(각 2초 이하) | 34,938+32,858(payment deposit) ~ 122,974+110,336(prediction batch) | bn254. 배포 근거가 가장 강함 |
| TONresistor/zk-resistor-contracts `43e61b89` (2026-07-17) | `circuits/insert.circom`, `circuits/withdraw.circom` | `circuits/package.json:9-10` 컴파일 스크립트, README.md:128-136 TON 메인넷 계약표(TON Verifier 소스 연결) | repo 안에 감사 언급 없음 | **실패**: 의존 패키지 `poseidon-bls12381-circom` 1.0.0이 로컬에 없음(설치 안 함) | – | **prime이 bls12381**. 우리 도구(zkFuzz·J)가 bn128 외 prime을 지원하는지 먼저 확인해야 함 |
| zuldotso/zul `30222e2d` (2026-06-29) | `circuits/transfer.circom`, `circuits/unshield.circom` | `circuits/scripts/common.mjs:14`(컴파일 대상 목록), `circuits/artifacts/CEREMONY-TRANSCRIPT.md:3` "mainnet shielded pool" ceremony(2026-06-16), README.md:27·62 mainnet 설정 | repo 안에 감사 언급 없음 | 2/2 성공 | transfer 16,046+17,800, unshield 8,083+8,901 | 회로가 작음. 배포 R1CS 해시는 repo에 없음(vk.bin만 있음) |
| ethstorage/zk-decoder `0c2db000` (2025-08-26) | `circom/circuits/blob_poseidon.circom`, `blob_poseidon_2.circom` | `circom/scripts/build/build.sh:17`(`--O2`, 기본 bn128). 메인넷 연결은 외부 문서뿐(repo 안에서는 미확인) | repo 안에 감사 언급 없음 | 2/2 성공(18초·37초) | 499,709+0, 999,418+0 | O2라 선형 제약 0. 반복 구조(blob 다항식 계산)가 큼 |
| mmchougule/b402-solana `8afeca96` (2026-05-27) | `circuits/transact.circom`, `circuits/adapt.circom` | `circuits/scripts/compile.sh:13`, `compile-adapt.sh:13`, ceremony zkey와 vkey 커밋됨(`circuits/build/ceremony/`) | README.md:379 "External audits scoped"(아직 없음) | 2/2 성공 | 17,259+0, 17,581+1 (README의 17,259·17,582와 일치) | **README.md:20 "live mainnet deployment is a test playground, not production"** |
| vocdoni/zk-franchise-proof-circuit `dc665879` (2023-12-05) | `circuit/census.circom`(래퍼로 nLevels 160) | `circuit/circuit-compiler.sh:84-91`(main 래퍼 생성·컴파일). prod 사용은 외부(go.vocdoni.io 설정)라 repo 안에서는 미확인 | repo 안에 감사 언급 없음 | 성공(래퍼, nLevels 160) | 84,761+93,305 | 마지막 커밋 2023년 |

## anon-aadhaar(B 6079a717) 재컴파일과 template_ambiguous 점검

- 판정 엔진과 같은 명령으로 다시 컴파일했다. `circom <entry> --r1cs --sym --prime bn128 -o … -l <source_root> -l <request library_paths…>`에 O1은 `--wasm`, O0은 `--O0`을 붙였다(고정 v2.2 `lifting/mod.rs:3542-3575`, 제한 600초 `mod.rs:40`). O1과 O0 모두 0.1초 만에 실패했다.
- 원인: `error[T2008]: Duplicated callable symbol` 16건(CompConstant, Num2Bits 계열, AliasCheck, 비교기, BinSum).
  - 요청의 `library_paths`에 E-02 준비 사본의 circomlib(`runs/e02-production-mains-2026-10-05/…/clone/node_modules`)과 B 스테이징 unit의 circomlib(`/Volumes/zkfdo-jcache/n6-b6d-batch1x/units/…/project/node_modules`)이 함께 들어 있다.
  - 그래서 같은 circomlib가 두 경로로 두 번 읽힌다.
  - 즉 우리 스테이징·요청 생성 쪽 문제이고, 회로 문제가 아니다.
- 확인: 라이브러리 경로를 unit 안의 경로(`unit`, `unit/project`, `unit/project/node_modules`, `unit/project/packages/circuits/src`)만으로 줄이면 O1은 23.5초, O0은 12.6초에 성공했다.
  - O1: 비선형 1,040,272 + 선형 74,808
  - O0: 비선형 1,057,382 + 선형 4,313,309
- template_ambiguous 정적 점검: anon-aadhaar 9건의 S wrapper는 모두 circomlib `GreaterThan`이 대상이고, unit 안의 `comparators.circom` 하나만 include한다.
  - 엔진의 템플릿 찾기(`mod.rs:1330-1375`)는 신호 이름이 같은 템플릿(LessThan·GreaterThan 등)이 여럿이면 `main` 템플릿 이름으로 고른다.
  - unit 경로만 쓰면 `template GreaterThan(`이 unit 안에 한 곳뿐이어서 이름으로 하나가 정해진다. 그래서 template_ambiguous는 나지 않을 것으로 본다.
  - 반대로 E-02 경로가 함께 있으면 같은 이름이 두 파일에 생겨 ambiguous가 될 수 있다. 확신은 중간이다. 실제 엔진 실행으로 확인하지 않았다.
- 고치려면 B 요청의 `library_paths` 생성 규칙을 바꿔야 한다. 이건 개정이 필요한 실행기·요청 변경이라 하지 않았다.
- 기록: 스크립트 `runs/h1-candidates-2026-10-25/anon_recompile.py` SHA-256 `10a3c5d580e9a6a87a280817abf083ce3590d55e5fa583c26da0f6a23ada6fe3`. 로그는 `/Volumes/zkfdo-jcache/h1-anon-aadhaar-recompile-2026-10-25/`(`o1`·`o0`는 원래 경로, `unit-only/`는 줄인 경로)에 있다.

## 한계

- 의존성을 설치하지 않았다. 그래서 TONresistor는 컴파일하지 못했다.
- 외부 링크(탐색기의 계약 주소, 외부 문서의 prod 설정)는 다시 열어 보지 않았다. 표의 배포 근거는 repo 안의 파일만이다.
- 감사 칸은 repo 안의 언급만 본 것이다.
- zkFuzz 논문의 평가 대상과 겹치는지는 여전히 미확인이다.

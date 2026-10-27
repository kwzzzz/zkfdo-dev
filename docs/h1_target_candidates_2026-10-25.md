# H1 사냥 후보 표 (2026-10-25, 고정 전 초안)

상태: 초안. 담당: miiz. 목록 고정은 miiz 검토 뒤에 한다. 이 문서는 대상 목록을 고정하지 않으며, 여기 있는 어떤 repo에도 zkFuzz·J·컴파일·clone을 새로 실행하지 않았다.

## 자료와 방법

- 읽은 기록: `docs/c02_corpus_results_2026-10-02.json`(239 repo), `docs/c03_corpus_results_2026-10-02.json`(80 repo). 겹치는 repo는 C-03의 설치 후(after) 기록을 우선했다.
- 로컬 clone은 기록된 commit에서 `git grep`·`git ls-tree`·`git show`로만 읽었다. 경로는 C-02 `clone_path`, C-03 `runs/c03-corpus-2026-10-02/recovery-v3/repositories/<owner__name>/clone`이다. runs/ 아래 재귀 목록은 만들지 않았다.
- 제외:
  - B·A에 쓴 repo: entrypoint 분류표의 10개 리비전 repo(anon-aadhaar, Vota-Circuits, iden3/circuits, panther-core, passport-zk-circuits, selfxyz/self, zylith-old, protocol-solidity, zkerc20)와 A 개발 세트.
  - C-02 `development_used`·`known_bug_listed`·`prior_exposure_listed`, C-03 `development_used_direct_or_alias`·`known_bug_listed_direct_or_alias`·`catalog_matches` 중 하나라도 있는 repo.
  - 출처에 `zkbugs`가 있는 repo.
  - fork 표시 repo, 그리고 역할이 education_example·tool_benchmark·library인 repo.
- zkFuzz 평가 목록은 로컬에 대조할 목록이 없다. 그래서 모든 행을 **미확인**으로 둔다.
- main 선택: 원본 컴파일이 성공하고 제약 수가 기록된 entrypoint를 제약 수가 큰 순서로 본다. test·mock·example·bench 경로를 뺀 뒤, 배포 근거가 있는 첫 main을 고른다.
- 배포 근거: N5 개정 4절 1항 규칙을 따른다. 빌드·배포 스크립트, verifier 생성 설정, README가 main 파일을 직접 가리키는 줄이어야 한다. 파일 이름이 들어간 줄만 자동으로 찾았고, 각 줄은 직접 열어 확인했다. test·fixture·benchmark 스크립트나 주석, 폴더 목록만 있는 경우는 배포 근거로 세지 않았다(칸 비움, 비고에 적음).
- 감사 흔적: 경로에 `audit`(auditor 제외)가 있는 파일과 README의 audit 언급을 찾고, 그 줄을 직접 읽었다.
- 정렬: 배포 근거 있음 → 감사 흔적 없거나 적음 → 제약 수 큼 → 컴파일 됨.
- 통째 퍼징 가능 여부: C-02·C-03 기록은 `zkfuzz_executions` 0이라 근거가 없다. 칸을 비웠다.

## 상위 10개

| 순위 | repo | commit | 배포 main 후보 | 배포 근거 | 감사 흔적 | 원본 컴파일 | 제약 수 | 마지막 커밋 | 통째 퍼징 | zkbugs / zkFuzz 목록 | 비고 |
|---:|---|---|---|---|---|---|---:|---|---|---|---|
| 1 | PepperSieve/nope | `08567b…` | `circuits/src/app/ecdsa-rsa.circom` | `circuits/export.sh:7` (빌드 스크립트의 NAMES 목록) | 없음 (`README.md:9`: 감사 안 됨, 더미 trusted setup) | success (C-03 설치 후) | 1,313,436 | 2025-04-06 |  | 없음 / 미확인 | export.sh는 witness 계산기 빌드와 시험 증명을 함께 함. 연구 프로토타입 성격 |
| 2 | Railgun-Privacy/circuits-ppoi | `ec2b26…` | `circuits/poi-transaction.circom` | `scripts/buildCircuit.sh:8` (circom 빌드 명령) | 없음 | success (C-03 설치 후) | 174,664 | 2023-09-26 |  | 없음 / 미확인 | team_curated 출처 포함 |
| 3 | Miny-Labs/benzo | `87c8ce…` | `contracts/circuits/transfer.circom` | `contracts/scripts/ceremony/ceremony-marker.json:14` (verifier 생성 ceremony 설정) | 자체 감사 없음 (`README.md:174`: unaudited) | success (C-03 설치 후) | 51,519 | 2026-07-11 |  | 없음 / 미확인 | `README.md:153`: Avalanche 메인넷 배포 표기. 회로가 감사된 ava-labs EncryptedERC와 거의 같음(제약 51,522) |
| 4 | EkuboProtocol/privacy-pools | `fdaadc…` | `circuits/pool.circom` | `README.md:49` (circom 빌드 명령) | 없음 | success (C-03 설치 후) | 29,092 | 2025-02-03 |  | 없음 / 미확인 | 역할 production |
| 5 | Flamki/setu-stellar-zk | `f3b5d2…` | `circuits/disclosure.circom` | `README.md:91` (main 파일 직접 언급) | 적음 (`README.md:22`: 감사 안 됨, `README.md:170`: "Security Fix From Audit" 절) | success (C-03 설치 후) | 3,272 | 2026-10-01 |  | 없음 / 미확인 | Stellar testnet 프로토타입 |
| 6 | Galactica-corp/galactica-monorepo | `08dad6…` | `packages/zk-certificates/circuits/mains/mimcEnDecrypt.main.circom` | `packages/zk-certificates/hardhat.config.ts:187` (circom 빌드 설정) | 없음 | success (C-03 설치 후) | 2,200 | 2025-10-31 |  | 없음 / 미확인 | E-01·E-02 컴파일 측정에 쓰임(판정·퍼징은 안 함). 더 큰 main은 배포 근거를 자동으로 못 찾음 |
| 7 | 0xbow-io/privacy-pools-core | `d494b6…` | `packages/circuits/circuits/commitment.circom` | `packages/circuits/circomkit.json` (circomkit 빌드 설정의 `commitment`) | 있음 (`audit/circuits_audit_oxorio.md` 외) | success (C-03 설치 후) | 1,537 | 2026-09-23 |  | 없음 / 미확인 | 감사 있음, 회로 작음 |
| 8 | Bitcoin-Wildlife-Sanctuary/circle-plonk-recursive-verifier-circom | `b4c221…` | `integration/integration.circom` |  | 없음 | success (C-03 설치 후) | 4,960,109 | 2025-01-16 |  | 없음 / 미확인 | 배포 근거 아님: `integration/test.sh:4`(시험 스크립트) |
| 9 | 0xja-eth/inft-zkp-scheme-starter-kit | `347d8d…` | `circuits/dual_key_verifier.circom` |  | 없음 | success (C-03 설치 후) | 398,358 | 2025-09-04 |  | 없음 / 미확인 | 배포 근거 아님: `README.md:266`(폴더 목록). starter kit |
| 10 | zero-savvy/zk-remote-attestation | `4a0416…` | `circom/zRA.circom` |  | 없음 (`README.md:115`는 tornado-core 인용) | success (C-03 설치 후) | 21,405 | 2025-06-27 |  | 없음 / 미확인 | 배포 근거 아님: `benchmarking/script.sh:15` |

commit 칸의 짧은 값은 아래 근거 JSON의 전체 commit을 줄인 것이다.

## 10위 밖(조건은 맞음)

- invisibook-lab/invisibook `lib/zk/templates/settle_cozk.circom` 6,944: 근거가 `chain/cfg/core.toml:10` 주석뿐이라 배포 근거로 세지 않음.
- tomiet/zkauth `circuits/allowlist_gate.circom` 3,896: fixture 설정만 있음.
- logos-storage/circom-goldilocks `circuit/testmain.circom` 300: 시험 main.

## 한계

- C-02·C-03 출처(GitHub 별 상위 200, zkbugs, SoK 2026, 팀 선정)에 없는 repo는 빠져 있다. 덜 알려진 회로를 넓게 찾으려면 새 수집이 필요하다.
- 배포 근거는 파일 이름이 들어간 줄만 자동으로 찾았다. 그래서 근거가 있는데도 못 찾은 큰 main이 있을 수 있다(예: Galactica, 0xbow의 다른 main).
- 감사 흔적은 repo 안의 파일만 봤다. 외부에서 공개한 감사 보고서는 확인하지 않았다.
- 원본 컴파일과 제약 수는 C-02·C-03 측정값(O1, 기록된 commit)이다. 지금 최신 commit과 다를 수 있다.
- "통째 퍼징 가능"은 기록이 없다. 제약 수가 수십만을 넘는 main(1, 2, 8, 9위)은 B의 rarimo처럼 판정·퍼징 비용이 클 수 있다.

## 기록

- 생성 스크립트: `runs/h1-candidates-2026-10-25/h1_candidates.py` SHA-256 `ceced5e20c15c3fe9e45d64ffa5f4f66c755166acea970bd7c7187d86316c659`
- 근거 JSON(전체 commit 포함): `runs/h1-candidates-2026-10-25/h1_rows.json` SHA-256 `1ac253f434c8aa02a31e7ce5b581c4445a480e06c373ed2588ca692ff2a52163`
- 고정할 때 스크립트를 `scripts/`로 옮긴다.
- 이 문서의 SHA-256은 문서 밖(보고 메시지와 계획 표)에 기록한다.

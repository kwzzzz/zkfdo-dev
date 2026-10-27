# N6-B5 준비 결과 (2026-10-17 작업, 2026-10-18 KST 확인)

이 작업은 B 판정 전에 J v2.2와 N5 개정을 기록하고, B의 중첩 배열 중단 원인을 계수해 S 퍼저와 후속 실행을 준비한 것이다. **이 세션에서 B 기준 입력 수집·B 의존성 설치·B 판정·B 재퍼징은 실행하지 않았다.** B 후보 입력·witness 값과 B 판정 결과도 열지 않았다. 원본 J 소스, 고정 기록, B 실행 기록은 수정하지 않았다.

## 1. 고정·개정과 상한 범위

| 기록 | SHA-256 | 상태 |
|---|---|---|
| `runs/handoff/n6_b5_instruction_2026-10-17.md` | `7dc02bd79f47a820a5608a26a6f81a8b34109710abfb501e03206da64188d0ff` | 원래 지시 전문 |
| `runs/handoff/n6_limit_scope_lead_check_2026-10-17.md` | `db44d8ba0958d0d86aae064d20a753094ccaba1a549346f9d31e146fb8022597` | 추가 리드 확인표 |
| [J v2.2 고정 기록](n6_j4_freeze_v2_2_2026-10-17.md) | `9ee4126d6036c5f67b8df2d851348028b6764d2b295214b2cef4b9c5d5ba8b88` | 수정 없음 |
| [v1·v2.2 상한 범위 기록](n6_j4_v2_2_limit_scope_2026-10-17.md) | `4106dd34a962490b89fb6f9e621e4213c2721d2944a9b0f24323a52c9ac7bdc6` | 리드 확인표 W1–W4 넓힘 4개, N1–N3 좁힘 3개를 코드에서 재확인해 보강 |
| [N5 개정](n5_amendment_b_judging_2026-10-17.md) | `88107b35ed98a0ea366fe616cd48b941d08ef9b44f2ddac2bf7b204e6514cae8` | 2절 1항 한 문장 교체와 범위 기록 SHA 갱신 |
| [N5 원본과 연결 단락](n5_evaluation_protocol_v1_2026-10-06.md) | `27940cc6f3b62578cb973ef9b0a8a438a76ce6948a73ca8288c8343fef79b053` | 원래 본문 보존, 끝의 개정 SHA만 갱신 |

이전 N5 개정 초안(SHA-256 `4e377b81e70b0b280a943b8e242e1574fda20e97ef31bb5366c219e3148d7342`)은 `runs/handoff/n5_amendment_draft1_2026-10-17.md`로 옮겨 보존했다. 범위 기록은 수치 상수 자체의 변경 0개와 실제 호출 범위 차이를 구분한다. 특히 새 작은 cone 모델·중단된 witness 수리·지역 Z3 재시도·비교 witness 없는 모델 수리는 탐색을 넓히고, 클래스 공유 6회·가정 술어 실패 캐시·지역 4,000제약 오류는 좁힌다. 작은 cone 제안이 기존 sweep의 20초를 먼저 쓰는 효과와 시작 상태 순환 조기 종료도 기록했다. 이 차이는 중단 관문이 아니라 B 판정 전 방법 기록이다.

시작 확인은 `runs/n6-b5-2026-10-17.noindex/startup-checks.json`에 남겼다. 완료된 v2.2 A 회귀 state SHA-256은 `fa1da116b317d7833a60bec52826c2119a79f50dbec27616f4cbce2932a8a1f6`, v2.2 바이너리와 `target/release/zkfDO`는 모두 `c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835`였다. v2.3 경로·J 소스 변경·동시 무거운 작업은 없었고 Docker 정보 확인은 성공했다.

## 2. 중첩 배열 panic 전수 집계

`runs/n6-b5-2026-10-17.noindex/panic-counts.json`(SHA-256 `0d47cd17e80b2f3a002742f44edd634fc9eeec2d59dfe2f8391ccb9e20a6123b`)에 state·queue SHA와 대상·단위·방법·모든 run별 302개 ledger 확인 결과를 보존했다. `utils.rs:522` 중첩 배열 panic은 B 본 실행 S 197회, W 0회다. 따라서 개정 5절 2항의 W 재퍼징 단위는 없다.

| 실행층 | 단위 / run (방법별) | W 중첩 panic | S 중첩 panic | 다른 비정상 종료 메타데이터 |
|---|---:|---:|---:|---|
| B 본 10 GiB | 30 / 30 | 0 | 197 | W `symbolic_execution.rs:2391` panic 464·memory cap 484·시작 전 기한 3; S 같은 symbolic panic 17 |
| B mem20 첫 기록 | 6 / 9 | 0 | 43 | W memory cap 519·시작 전 기한 2 |
| B mem20 재시도 | 2 / 2 | 0 | 9 | W memory cap 113·시작 전 기한 1 |
| A 본 10 GiB | 81 / 92 | 0 | 0 | W engine exit 1 미분류 1,042·memory cap 474·시작 전 기한 19; S engine exit 1 미분류 39 |
| A pragma 보정 | 6 / 6 | 0 | 0 | W 시작 전 기한 1 |
| A mem20 | 12 / 12 | 0 | 0 | W memory cap 73 |

집계에 쓴 state는 B 본 `runs/n6-b2-2026-10-09.noindex/b-execute.noindex/state.json`(`a35e4376e95757f5ef8803b4b0e8bd1a0c6c6ee4df276cf09574d0fab50edd09`), B mem20 첫 기록 `runs/n6-b3-2026-10-12.noindex/mem20-execute.noindex/state.json`(`5160fda628e9a920d8a0f7717b31fc05ad88326a371780908803d187b2ddfc7c`), 완료 재시도 `runs/n6-b3-2026-10-12.noindex/mem20-retry.noindex/state.json`(`70043643377bc489760b092bf96881747fc5bf5a318648ee69c236fd25a9a16a`), A 본 `runs/n6-a2b-2026-10-08.noindex/a-execute-2.noindex/state.json`(`864d714d32b6ce4201bd6ca8151531d6929570e880edbfcedb380b8ddb42e744`), A pragma `runs/n6-a3-2026-10-08.noindex/pragma-b-execute-2.noindex/state.json`(`feb98923232336f79684d5773c1c1b80d4f685b88b13a7ad5c6ee776d258dd32`), A mem20 `runs/n6-a3-2026-10-08.noindex/mem20-execute-2.noindex/state.json`(`370e744d96634cd03d603b6f1c7c5e7ea814ec133b3777e26b6d2e7d985cd644`)이다. 방법별·대상별·단위별 완전 표는 집계 JSON에 있다.

## 3. S 퍼저 수정과 재퍼징 준비

수정 전 zkFuzz 커밋은 `072bf1fbbd1c9ecad58d4f6d2204c3b96e7fec17`; 기존 `/Users/miiz/.cargo/bin/zkfuzz` SHA-256은 `ac2d9d16fd97ff803b121b7994aef804b4e191636f3f78660ff6ecd6c9ae4edd`로 빌드 뒤에도 같았다. `.external/zkFuzz/src/mutator/utils.rs`의 중첩 배열 미구현 분기와 합성 테스트만 바꿨다. 패치 `runs/n6-b5-2026-10-17.noindex/zkfuzz-nested.patch` SHA-256은 `abba61105393a799814067d15ece883cfd3b03850bf7ad7bcc41e2218c93672b`, 격리 release 바이너리 `runs/n6-b5-2026-10-17.noindex/zkfuzz-nested-target/release/zkfuzz`는 `f4d992e707c4227de99467adf38bae3ad98573ec5ababe09e391429d7c2542f0`다. `CARGO_HOME=runs/n6-b5-2026-10-17.noindex/zkfuzz-cargo-home CARGO_TARGET_DIR=runs/n6-b5-2026-10-17.noindex/zkfuzz-nested-target cargo build --offline --release --bin zkfuzz`로 빌드했고 cargo/rustc는 1.94.1이다.

zkFuzz 테스트 77개와 중첩 합성 CLI 검사가 통과했다. 비중첩 합성 템플릿 3개를 seed `20261017`, `max_generations=3`으로 기존·수정 바이너리에 동일 적용해 출력이 일치했다. ANSI 색상, 진행 표시의 carriage return, `Execution Time`만 비교에서 제외했다. 비교 JSON은 `runs/n6-b5-2026-10-17.noindex/zkfuzz-differential/comparison.json`(SHA-256 `7dc22b02b4b755d59cf74e0ef50e678cb8af2fa8677d12ea27c5b6149b8e7988`)이다. 수정한 두 파일의 형식은 맞췄다. 외부 zkFuzz 저장소 전체의 fmt와 엄격한 Clippy는 수정 밖의 기존 형식 및 `build.rs:5` 경고 때문에 실패했고 이 사실을 판정 결과와 무관한 검사 한계로 보존한다.

비중첩 경로가 바뀌지 않았다는 주 근거는 패치 diff(미구현 분기만 수정)이고, 비중첩 합성 템플릿 차등 검사는 보조 근거다.

S 전용 새 큐 `runs/n6-b5-2026-10-17.noindex/s-nested-prep/queue-b-s-nested.json` SHA-256은 `9cfd92aacff47a831e6a63d1ab37759336b3cf5c1f806e8620de0428e287db7c`다. 원본의 10대상×3 seed·순서·단위당 3,600초·10 GiB를 유지한 30개 S spec이며 바이너리만 바꿨다. preflight 재사용 증명 `d00a36412c6c117c05bf7fecbd9df653bd0fc4242dcc3ae37626577f6df30a03`, 준비 기록 `8cd417d0a98098ca1323af7f0901c898f4b01900166fe21cb8770fd58f412f3f`이고 validate-only와 관련 Python 25건이 통과했다. 재실행기는 환경 압박 또는 실행기 중단 시 같은 설정을 한 번만 재시도한다.

시작 전 관문 `runs/n6-b5-2026-10-17.noindex/s-nested-prep/gates/prestart-gate-s-nested.json`(SHA-256 `6cc8c6e887da629ead42d2c0c9d941beb2a4137b6583b8e0bcb42cab9ccaef6e`)은 **실패**했다. 호스트 `memorystatus` 최저 36이 기준 50 미만이었고, 2 GiB 자체 시험·다른 무거운 프로세스 부재·디스크·전원·swap·열 상태는 통과했다. `s-nested-execute.noindex`는 생성하지 않았다. 호스트 상태가 회복되면 실행 직전에 관문을 새로 통과시켜야 한다.

관문을 새로 통과한 뒤 별도 재퍼징 단계에서 쓸 명령은 다음과 같다. 이 세션에서는 실행하지 않았다.

```sh
caffeinate -dimsu python3 /Users/miiz/Desktop/kwzzzz_zkfr/scripts/run_n6_b5_s_nested_queue.py --queue /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b5-2026-10-17.noindex/s-nested-prep/queue-b-s-nested.json --output /Users/miiz/Desktop/kwzzzz_zkfr/runs/n6-b5-2026-10-17.noindex/s-nested-execute.noindex --action execute
```

## 4. Docker 기준 입력 규칙과 A 시험

새 수집기 [n6_b5_docker_base_inputs.py](../scripts/n6_b5_docker_base_inputs.py)(SHA-256 `ebcfa8189b75fc5694dbfcbe01e38c994bc37e688e4770996c20b233ac4fb31c`)와 B 퍼징 R1CS 근거 추적기 [n6_b5_r1cs_reference.py](../scripts/n6_b5_r1cs_reference.py)(SHA-256 `8b03da272a1aec0e4466700ea6ca264e303a24c21bb024e068ae0ae6d26fe9fb`)를 만들었다. 후자는 원래 preflight 증명·컴파일 호출·산출물 삭제 계획의 SHA를 연결해 B 10리비전×3 seed의 원본 R1CS 해시가 모두 같음을 확인했다. 근거 map `runs/n6-b5-2026-10-17.noindex/b-r1cs-reference-v2.json` SHA-256은 `b1e3e893ef7163f1918fb9a144bf368b2a0fb20b85cd975366da32352391a79b`다. 앞서 만든 1/10만 확인된 map은 이 근거로 대체했고 B 수집에는 쓰지 않는다.

`runs/n6-b5-2026-10-17.noindex/install-tools.json`(SHA-256 `a0b82574afd6823d0a77ca6c0ace4459b4586b06b4f8dce2da43728355f0737b`)은 공식 `docker.io/library/node@sha256:c3de60bf2f9dd0ac6370e6117950ff62d6e339527e7472301c9c78a017978392`의 `linux/amd64` 판, Node 22.23.3, npm 10.9.9, corepack 0.36.0, 기본 Yarn 1.22.22/4.10.3, pnpm 9.15.9를 고정한다. 같은 버전의 Linux circom 2.2.1 공식 릴리스는 `runs/n6-b5-2026-10-17.noindex/circom-linux-amd64-v2.2.1`(SHA-256 `217c99792b0cdf7806f923d0afd88dafae06a14d82001fd3bda34407e6073317`)로 보존했다. 컨테이너에 연결하는 호스트 폴더는 해당 리비전 프로젝트의 임시 복사본 하나뿐이다. `.git` 사본을 제외하고 Mac 비밀 환경변수·SSH agent·토큰을 넘기지 않는다. 설치·허용 build·원본 (d) 테스트는 컨테이너에서, 후보 기준 입력의 정직 witness와 Rust·snarkjs·R1CS SHA 검사는 고정된 Mac 도구로 한다. lock은 기록된 커밋에 있어야 하며 정해진 명령 하나만 설치에 쓴다. build가 다른 이름의 스크립트를 호출하면 실행 전에 (d) 실패로 둔다. 컨테이너/레지스트리 차단은 환경 차단으로 분리한다. 리비전당 60분을 넘기지 않는다.

고정 이미지 실행 1회와 `npm ping` 1회가 성공했다(`a-connectivity-check.json`, SHA-256 `ecec3198a60fd542787b2599ffd34ae392fb9e264463e1636d0ec500322b3f7d`). 네트워크 없는 합성 정책 테스트 6건과 프로젝트 사본 하나만 연결한 실제 Docker 합성 Node·circom 시험이 통과했다(시험 로그 SHA-256 `d70db05327500208c83f9fd129bbcb1738ab496e370de81ffec3a975d8616c99`). B에서는 이 기록이 끝난 뒤에만 첫 설치를 시작한다.

첫 A 직접 시험 `aq-025-70328d3fd35e`는 Linux circom 고정 전 8.36초에 `pinned_linux_circom_unavailable`로 끝났다. 도구를 고정한 뒤 별도 경로에서 재시험하니 Node·circom 검증과 원본 테스트까지 실행됐으나 기록된 커밋 `bbbe14c…`에 `package-lock.json`이 없어서 설치 전에 (d) 실패로 끝났다(12.75초). 준비 사본에 있는 lock은 커밋되지 않았으므로 허용된 lock으로 대체하지 않았다. 이 두 시도 모두 J와 A 공식 기준 입력 index를 변경하지 않았다.

수집기 최종판으로 열 개를 다시 시험한 메타데이터 요약은 `runs/n6-b5-2026-10-17.noindex/a-dryrun/final-audit/summary.json`(SHA-256 `7a980319236220767b44228ecfe9154d5bb09b463153723cd54a32aac6d6f034`)이다. 수집기 SHA와 각 state·index SHA, 단계별 실패 사유·시간을 묶었다. 열 개 모두 기준 입력 미확보이고 합계 281.28초였다. 모든 행에서 (a)는 `zkbugs_input_missing`, (b)는 `matching_l_series_input_missing`, (c)는 `main_input_keys_mismatch`, (e)는 `honest_witness_failed`였다. 표의 `중첩 build`는 허용된 이름의 build 스크립트가 다른 이름의 스크립트를 호출해 원문 규칙상 실행하지 않은 것이고, `커밋 lock 없음`은 복사본에는 lock이 있어도 기록된 커밋에는 없다는 뜻이다.

| A 리비전 | (a) | (b) | (c) | (d) | (e) | 최종판 경과 |
|---|---|---|---|---|---|---:|
| aq-025-70328d3fd35e | 실패 | 실패 | 실패 | 커밋 lock 없음 | 실패 | 33.35초 |
| aq-011-93343c3cd34c | 실패 | 실패 | 실패 | 중첩 build | 실패 | 27.99초 |
| aq-012-44d0df2ab46e | 실패 | 실패 | 실패 | 중첩 build | 실패 | 28.27초 |
| aq-016-0a7d49b1c135 | 실패 | 실패 | 실패 | 중첩 build | 실패 | 28.56초 |
| aq-017-9703bbce0c43 | 실패 | 실패 | 실패 | 중첩 build | 실패 | 28.78초 |
| aq-024-6f6781246415 | 실패 | 실패 | 실패 | 중첩 build | 실패 | 29.55초 |
| aq-026-2bcd7ed6110f | 실패 | 실패 | 실패 | 커밋 lock 없음 | 실패 | 12.74초 |
| aq-037-94fe3080fc18 | 실패 | 실패 | 실패 | 커밋 lock 없음 | 실패 | 29.69초 |
| aq-039-0ad3923f2f5b | 실패 | 실패 | 실패 | 커밋 lock 없음 | 실패 | 28.50초 |
| aq-040-da54d3e7bc8a | 실패 | 실패 | 실패 | 커밋 lock 없음 | 실패 | 33.83초 |

최초 직접 시험과 나머지 9개 백그라운드 시험은 원형 상태 그대로 `a-dryrun/`에 보존했다. 최종판 재시험도 첫 시험 시각부터 3시간 안에 끝났으며 어느 시험도 A 공식 준비 실패 2,161건을 바꾸지 않았다. 2026-10-17 UTC의 시험 중 Linux circom 버전 고정, 컨테이너 사본의 `.git` 제거, 전체 Docker 로그의 환경 차단 분리, Panther 동일 main 검사 복원, 테스트 안의 build 중복 호출 방지를 수집기 구현에 반영했다. lock·테스트·도구·입력 무수정, 컨테이너 실행, 60분, R1CS 일치 규칙은 바꾸지 않았다. 특히 네트워크/권한 차단은 (d) 실패나 음성 결과로 취급하지 않고 해당 리비전 단계에서 멈춘다.

A 후보 입력·witness 값 파일은 열지 않았다(연 파일 목록 `[]`). 확인에 읽은 A 자료는 기준 입력 index의 실패 메타데이터, revision manifest, `aq-011/012/016/017/024` 프로젝트의 `package.json`·`circuits/package.json`·`crypto/package.json` 스크립트 필드, 열 개 리비전의 정해진 root/circuits lock 존재 여부와 해당 커밋의 lock 보유 여부뿐이다. 프로젝트 소스·기준 입력은 수정하지 않았다.

## 5. B 1묶음 명령 준비

키티에서 다음 **한 명령**을 실행한다. 시작할 때 `J cache parent (existing absolute directory): `라고 묻고, 이미 존재하는 폴더의 절대 경로를 입력받는다. 이 폴더는 저장소·B 출력과 다른 외장 볼륨에 있어야 하며 저장소 볼륨과 장치 번호도 달라야 한다. 명령은 장치 번호 차이를 검사하므로 물리적으로 외장 볼륨인지는 경로를 넣기 전에 사람이 확인한다. 첫 preflight에서 저장소와 이 캐시 폴더의 여유 공간을 각각 40 GiB 이상 검사한다. B 기준 입력 수집 직전에는 저장소를, J 시범 직전에는 저장소와 캐시 폴더를 다시 검사한다. 이 세션에서는 명령을 실행하지 않았고 B 기준 입력·의존성 설치·J 판정·시범도 전혀 실행하지 않았다.

질문에 넣을 값은 `/Volumes/zkfdo-jcache/n6-b5-batch1`이다. 2026-10-18 확인 때 `test -d`가 성공했고, 해당 볼륨의 남은 공간은 523,922,748 KiB(약 499.65 GiB)였다. 이는 입력 경로 확인일 뿐 위 명령이나 B 단계를 실행한 것은 아니다.

```sh
caffeinate -dimsu python3 /Users/miiz/Desktop/kwzzzz_zkfr/scripts/n6_b5_batch1_prepare.py
```

[준비 실행기](../scripts/n6_b5_batch1_prepare.py)(SHA-256 `6e5392455b8fc2a1d85f1cbbd9f1c2d63ef342d67d6e9c5c7b1009a7d97eb64f`)는 첫 단계에서 저장소·외장 캐시 양쪽 40 GiB, Docker 정보·사용량, 고정 수집기·도구·R1CS map, v1 바이너리 `e5cb01845422c1dd59c0bb2822d8652c1bafc583d8c111814dfbd9127a96e1ed`와 v2.2 바이너리 `c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835`, 원래 mem20 state(`stopped_between_units`)와 완료된 retry state(SHA-256 `70043643377bc489760b092bf96881747fc5bf5a318648ee69c236fd25a9a16a`)를 검사한다. 원래 state가 `completed`가 아닌 것은 기록 연결 문제로 판정 변경이 없으며, [J adapter](../scripts/n6_b5_j_adapter.py)(SHA-256 `d9ac5c8e3fafc4a789c1e6b9939611a494e3cd0ea9fb389048cbe2f21dc1de20`)가 두 state의 내용·SHA를 확인하고 완료 재시도 경로를 기존 실행기에 넘긴다. 원래 J 소스·v1 바이너리·판정 규칙은 수정하지 않았다.

앞 단계가 성공해야 다음으로 진행한다. B 10리비전 기준 입력 수집은 리비전별 (d) 실패를 `판정 불가`로 보존하며, Docker/네트워크 자체가 차단되면 멈춘다. 이어 기록된 Git 리비전의 README·빌드·배포·verifier 근거로 entrypoint 분류표를 만들고 파일·줄·SHA를 묶는다. 직접 근거가 없거나 알 수 없으면 하네스로 둔다. B manifest의 10개 main 중 9개는 기록 커밋과 사본이 바이트 동일하다. `77e0f2db173d0c1812de503a`는 1,129줄 중 pragma 한 줄만 `2.2.3 → 2.2.1`이고 main 정의·호출은 같다. 양쪽 SHA와 `pragma_only` 관계를 분류표에 보존한다. 이 차이는 배포/하네스 분류를 바꾸지 않는 기록 문제다. 분류표의 실제 SHA는 B 단계 실행 후 생성되며 여기서 미리 만들지 않았다.

그 뒤 기존 [B 요청 생성기](../scripts/n6_j3_b_requests.py)(SHA-256 `13f2f1947b097f29211b969e8ef195b4c9bc94c3a3699650cf921022fd40222c`)로 원래 첫 B 퍼징의 S 107건·W 0건을 모두 담은 최종 index를 만든다. 기준 입력이 없는 요청은 준비 실패로 표시하며 삭제하지 않는다. v1 index에서 요청 행을 한 글자도 바꾸지 않고 v2.2 엔진 경로·SHA만 바꾼 index를 따로 만든 뒤 두 index에 `validate-only`를 실행한다. 기준 입력이 있는 S 요청에서 제약 수 최대·최소 두 요청을 고르고 **시범 전에 ID를 파일로 기록**한다. [형식 전용 시범 실행기](../scripts/n6_b5_format_pilot.py)(SHA-256 `3b2c7b39dc58dc1bb5aaf86a622b5278848fc590350c99234a79386eb4ae8e48`)는 v2.2부터, 이어 v1로 두 건씩 실행해 exit code·형식·도구 오류 메타데이터만 확인하고 화면에는 단계별 exit code와 형식 통과 여부만 낸다. 판정 필드의 존재와 형식은 검사하되 판정 값·집계 수치는 확인하거나 출력하지 않는다. 실패한 시범의 출력·캐시는 보존하고 다음 시도는 새 경로를 쓴다. 완료 단계 재개 시 입력·산출물 SHA를 다시 확인한다. 이 명령은 두 엔진 시범 뒤 끝나며 107건 전체 판정은 시작하지 않는다.

v1 형식에는 v2.2의 `solver_calls` 배열이 없어 시범은 v1 비용 단계와 class의 오류 메타데이터만 검사한다. v1의 `aborted` witness 상태는 정직한 제약 중단과 일부 도구 중단을 완전히 분리하지 못하므로, v1 시범에서 명시적 오류가 없다는 검사는 이 기록 형식의 한계 안에서만 해석한다. 실제 v1이 새 index나 저장소 형식을 읽지 못하면 바이너리를 고치지 않고 해당 오류를 기록한다. 최종 107 index의 validate-only와 실제 시범 통과 여부는 B 기준 입력 수집 전이라 아직 확인할 수 없다. 합성 index의 기준 입력 있음/없음 행과 새 준비 실행기의 Python 14건 검사는 통과했다. 이후 순서는 1묶음 전체 v2.2→v1, S 30단위 재퍼징, 2묶음 판정이며 각각 별도 지시에서 실행한다.

## 6. 디스크와 검사

| 위치·시점 | 남은 용량 또는 Docker 사용량 | 해석 |
|---|---:|---|
| 저장소 볼륨 시작 | 130,476,144 KiB(약 124.43 GiB) | `startup-checks.json` 기록 |
| 저장소 볼륨 A 최종판 종료 후 | 120,965,464 KiB(약 115.36 GiB) | 여러 A 시험과 도구 빌드 뒤 약 9.07 GiB 감소; B 소요량으로 환산하지 않음 |
| J 외장 캐시 볼륨 | 2026-10-17 당시 경로 미확인; 2026-10-18 확인 시 523,922,748 KiB | 기존 state/index에 별도 외장 경로가 없었다. 이번에는 5절의 경로 존재와 여유 공간만 확인했고 B 명령은 실행하지 않았다. |
| Docker 시작 | 이미지 23.02 GB, 컨테이너 3.41 GB, 볼륨 471.8 MB, 빌드 캐시 17.72 GB | `startup-checks.json` |
| Docker A 종료 후 | 이미지 23.7 GB, 컨테이너 3.41 GB, 볼륨 471.8 MB, 빌드 캐시 17.72 GB | 약 0.68 GB 이미지 증가; `docker system df` 재확인 |

용량 계획은 기존 실행 기록의 관측과 미래 소요량을 구분한다. B 기준 입력은 고정 Node 이미지 증가분이 A에서 약 0.68 GB였으나 열 리비전의 임시 사본·`node_modules` 크기는 아직 실측하지 못했다. 기준 입력 수집 직전 저장소에 **40 GiB 이상** 없으면 멈춘다. 이전 A J 실행은 765요청에서 출력 11.597 GiB, 리비전별 삭제된 캐시의 합 54.428 GiB, 최대 한 리비전 19.251 GiB였다. B는 107요청에 큰 회로도 포함하므로 A의 요청당 크기를 곱하지 않는다. B 1묶음은 기존 J 실행기의 저장소 출력·외장 캐시 각각 **40 GiB 가드**를 그대로 쓰고, 두 시범의 실측 뒤 다시 계획한다. 기존 S 여섯 단위의 W·S 출력은 154 MiB였으므로 30단위 단순 배율은 약 770 MiB이지만 중첩 수정 뒤 재시도·산출물 증가는 알 수 없다. S 시작 전 관문의 **35 GiB** 여유 검사를 유지한다. 세 무거운 단계는 순서대로 실행하며 요구량을 합산해 확정치로 쓰지 않는다. 용량이 부족하면 기존 ignored 실행 캐시나 사용하지 않는 Docker 이미지·빌드 캐시를 사람이 검토하도록 안내하고 자동 삭제는 하지 않는다.

저장소 본체는 `cargo fmt`, `cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`를 모두 exit 0으로 마쳤다. 새 Python 실행기·수집기와 기존 기준 입력 준비의 합성 검사 39건, Python 구문 검사, `git diff --check`도 통과했다. 외부 zkFuzz는 77개 테스트·중첩 합성 CLI·비중첩 세 템플릿 차등 검사를 통과했다. 외부 저장소 전체 fmt/엄격 Clippy의 기존 실패는 3절에 한정해 적었다. 실제 B 107 index의 validate-only와 두 엔진 시범은 B 기준 입력 수집 전이므로 미실행이며 성공으로 세지 않는다. S 관문도 앞 절에 적은 호스트 압박 때문에 실패 상태 그대로다.

이 작업에서 바뀐 파일은 `docs/n6_j4_v2_2_limit_scope_2026-10-17.md`, `docs/n5_amendment_b_judging_2026-10-17.md`, `docs/n5_evaluation_protocol_v1_2026-10-06.md`, `docs/n6_b5_preparation_2026-10-17.md`, `docs/plan_revision_2026-10-01.md`, `runs/handoff/lead_session_notes.md`와 4·5절의 새 준비 스크립트·검사 파일이다. 구체적으로 `scripts/n6_b5_docker_base_inputs.py`, `n6_b5_r1cs_reference.py`, `n6_b5_a_dryrun_remaining_v1.py`, `n6_b5_batch1_prepare.py`, `n6_b5_j_adapter.py`, `n6_b5_format_pilot.py`, `n6_b5_s_nested_prepare.py`, `n6_b5_s_nested_prestart_gate.py`, `run_n6_b5_s_nested_queue.py`, `tests/n6_b5_a_dryrun_remaining_v1_test.py`, `tests/n6_b5_batch1_prepare_test.py`, `tests/n6_b5_docker_base_inputs_test.py`, `tests/n6_b5_s_nested_queue_test.py`, `.external/zkFuzz/src/mutator/utils.rs`, `.external/zkFuzz/tests/nested_template_parameter_emulation_test.rs`다. 새 고정 기록 `docs/n6_j4_freeze_v2_2_2026-10-17.md`는 SHA 기록 뒤 수정하지 않았다. 기존의 무관한 `.vscode/settings.json` 변경과 `docs/c02_corpus_results_2026-10-02.json`, `docs/c03_corpus_results_2026-10-02.json` 미추적 파일은 건드리지 않았다. commit·push·PR은 하지 않았다.

## 7. 개정 2판과 A 재시험

miiz의 2026-10-17 UTC 승인에 따라 N5 개정 3절 3항의 빌드 사슬 문장만 교체하고 문서 끝에 개정 기록을 붙였다. N5 원본은 연결 단락의 개정 SHA만 새 값으로 바꿨다. 1절의 J 고정 기록(9ee4126d6036c5f67b8df2d851348028b6764d2b295214b2cef4b9c5d5ba8b88)과 상한 범위 기록(4106dd34a962490b89fb6f9e621e4213c2721d2944a9b0f24323a52c9ac7bdc6)은 수정하지 않았다. 4절은 1판 규칙과 당시 수집기 SHA·A 시험 결과를 적은 역사적 기록이다. 6절의 Python 검사 39건과 변경 파일 목록도 1판 당시 기록이며, 이번 최종 값은 아래에 적었다.

| 파일 | SHA-256 |
|---|---|
| runs/handoff/n6_b5b_instruction_2026-10-17.md (새 지시 전문) | 0e4790020d75d2f49dadfe7291d08494b24ee458624820a52838c77def553765 |
| docs/n5_amendment_b_judging_2026-10-17.md (개정 2판) | bf7308ee7226522ecf7a36de276b859fdccff089d562654e30a9362429762291 |
| docs/n5_evaluation_protocol_v1_2026-10-06.md (개정 연결) | 438f58c409ea876f61cd6226164408bf2c726ab03d4e81f4d8d8bb748ba5ab91 |
| scripts/n6_b5_docker_base_inputs.py (최종 수집기) | defe70373f818ce0db203d73a6833785ee6e308c90a908388d78461dae76fb42 |
| scripts/n6_b5_batch1_prepare.py (새 수집기 SHA 고정) | 12bf226545fa74c9f187525f3c85d7ccc70a54dcda556476a21175778daa48b2 |
| scripts/n6_b5b_a_dryrun.py (A 순차 실행기) | 94e11255c9a3490a94420d72d92fd5484bc28ecd92e328e2b4b0ebbaca1a97fb |

수집기는 같은 package.json 및 workspace 하위 package.json의 중첩 호출과 pre·post 호출을 정적으로 따라가고, 알 수 없는 호출은 동적으로 표시한다. 순환은 무한 반복 없이 기록한 뒤 (d) 실패로 둔다. 실제 실행 사슬은 정적 계획과 별도로 기록한다. 최초 회차에서 설치가 먼저 실패하면 계산한 정적 사슬이 결과에 남지 않는 수집기 기록 버그를 발견했다. 설치·테스트·빌드보다 먼저 각 테스트의 script-chain-plan-N.json을 저장하고, 경로·SHA를 단계 및 실패 기록에 연결하도록 고쳤다. 설치 실패와 환경 차단에도 계획 파일이 보존된다. 이 수정은 설치 명령이나 판정 규칙을 바꾸지 않았다. 고정 이미지·기록된 커밋 lock·설치 플래그·테스트와 입력 무수정·컨테이너·60분·R1CS 해시 검사는 유지했다.

같은 package.json의 중첩 호출, workspace 호출, 순환, 동적 호출과 설치 실패 전 계획 보존을 포함한 Python 합성 검사 59건이 통과했다. Python 구문 검사, git diff --check, cargo fmt, cargo clippy --all-targets --all-features -- -D warnings, cargo test도 모두 종료 코드 0이었다.

처음 다섯 건은 runs/n6-b5-2026-10-17.noindex/a-dryrun-v2/의 각 리비전 경로에 보존했다(수집기 SHA 1f09f3c5a1c09c7735dee261d8be08dec4ea7387f3f006997f7974e3f99ccc55, 합계 504.89초). 기록 버그 수정 뒤 같은 다섯 건만 final/ 하위에서 한 리비전씩 재확인했다(합계 497.28초). 첫 회차 시작부터 최종 종료까지 1,321.36초로 다섯 건 합계 90분 제한 이내이며, 각 리비전도 60분 미만이다. 최종 index SHA-256은 19c339bdb27f09daa40a1e5226e1e3ad8868c65d8eb0aad630cb21a5ccd9b3dc, 메타데이터만 담은 final/metadata-summary.json SHA-256은 512efab295cfcbbf85027686b23fb8273ae4346426e6ce49775069b6c5270613이다.

| A 리비전 | (a)/(b)/(c)/(d)/(e) | 실제 실행된 package.json 사슬 | 설치 exit code/초 | 빌드 exit code/초 | 테스트 exit code/초 | 기준 입력 | R1CS 해시 일치 | 실패 사유 | 총초 |
|---|---|---|---|---|---|---|---|---|---:|
| aq-011-93343c3cd34c | 실패/실패/실패/실패/실패 | 없음 | 1/34.06, 1/29.12 | 미실행 | 미실행 | 미확보 | 예 | lock_install_failed; 컨테이너에 Git 실행 파일 없음 | 90.09 |
| aq-012-44d0df2ab46e | 실패/실패/실패/실패/실패 | 없음 | 1/33.71, 1/31.03 | 미실행 | 미실행 | 미확보 | 예 | lock_install_failed; 컨테이너에 Git 실행 파일 없음 | 77.36 |
| aq-016-0a7d49b1c135 | 실패/실패/실패/실패/실패 | 없음 | 1/32.73, 1/31.24 | 미실행 | 미실행 | 미확보 | 예 | lock_install_failed; 컨테이너에 Git 실행 파일 없음 | 76.29 |
| aq-017-9703bbce0c43 | 실패/실패/실패/실패/실패 | 없음 | 1/29.82 | 미실행 | 미실행 | 미확보 | 예 | lock_install_failed; 컨테이너에 Git 실행 파일 없음 | 43.48 |
| aq-024-6f6781246415 | 실패/실패/실패/실패/실패 | 없음 | 1/29.08, 1/27.99, 1/27.89, 1/28.37, 1/27.54, 1/29.33, 1/27.94 | 미실행 | 미실행 | 미확보 | 예 | lock_install_failed; 컨테이너에 Git 실행 파일 없음 | 210.06 |

다섯 건의 단계별 세부 사유는 공통으로 (a) zkbugs_input_missing, (b) matching_l_series_input_missing, (c) main_input_keys_mismatch, (d) lock_install_failed, (e) honest_witness_failed이다. 설치 14회 모두 개정 표의 Yarn 1 명령(corepack yarn@1.22.22 install --frozen-lockfile --ignore-scripts)을 그대로 사용했고, 설치 로그 오류는 모두 “Couldn't find the binary git”이었다. 당시 수집기는 네트워크·권한 차단 표시가 없다는 이유로 (d) 실패로 기록했다. 계획 파일에는 circuits/package.json의 build → build:types → 동적 외부 호출 → build:ts가 남지만 설치 단계에서 멈춰 실제 package.json 스크립트 실행은 0건이다. 따라서 이번 실프로젝트 결과는 중첩 빌드 사슬의 실행 성공을 입증하지 않는다.

2026-10-18 재분류: 위 표의 (d) 실패 표기는 당시 수집기의 상태값이며, 설치 컨테이너에 Git 실행 파일이 없었던 5/5는 모두 **도구 차단**이다. (d) 판정 실패 5건으로 세지 않는다. 최종 `aq-024`의 설치 7회는 각각 다른 lock·폴더 설치가 아니라 모두 동일한 `circuits/yarn.lock`과 `circuits` 폴더의 재시도였다. `aq-011`·`aq-012`·`aq-016`의 각 2회도 동일 lock·폴더 재시도였고 `aq-017`은 한 번 설치했다. 이번 도구 보정판은 같은 lock·폴더를 다시 설치하지 않는다.

A 공식 준비 실패 2,161건과 공식 기준 입력 index는 바꾸지 않았다. index SHA-256은 18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508로 유지된다. A 후보 입력·witness 값은 열지 않았다(연 파일 목록 []). B 기준 입력 수집·B 의존성 설치·B 판정·S 재퍼징은 0건이고, B 후보 값과 B 판정 결과는 열지 않았다. 기존 a-dryrun/과 원본 실행 기록은 그대로 두었다. commit·push·PR은 하지 않았다.

## 8. 도구 보정과 A 재시험 2

2026-10-18 UTC 지시 전문을 `runs/handoff/n6_b5c_instruction_2026-10-18.md`에 저장했다. 지난 `a-dryrun-v2/final`의 0/5는 설치 컨테이너에 Git 실행 파일이 없었던 **도구 차단**으로 재분류한다. 7절의 당시 `lock_install_failed` 표시는 역사적 수집기 상태값이며 (d) 실패 집계로 쓰지 않는다. 개정 기록에 공식 전체 Node 이미지, 공개 GitHub SSH lock 주소의 컨테이너 내부 HTTPS 받기, 컨테이너 도구 누락 시 도구 차단, 동일 lock·폴더 1회 설치를 적고 N5 연결 SHA를 갱신했다. 고정 기록과 상한 범위 기록은 수정하지 않았다.

| 파일·기록 | SHA-256 또는 digest |
|---|---|
| 새 지시서 `runs/handoff/n6_b5c_instruction_2026-10-18.md` | `d0fd6bb8648ac2f3eb4e5e1d3a2e993825f47b116dd0dd63f0b589b59fa90ae2` |
| 개정 `docs/n5_amendment_b_judging_2026-10-17.md` | `d9e535234e868fd6826e8f0e622993158b256fa2d702556ce643ebe2cb0799d9` |
| N5 연결 `docs/n5_evaluation_protocol_v1_2026-10-06.md` | `5afa5f00579bd3011e264b186367f5310390cae28aa48a4cb89a3aff1188f644` |
| `install-tools.json` | `0daf78af39e06dddb1776cf1f4b1ffd875a26054e2cd4d5c39c8f52560de4688` |
| 수집기 `scripts/n6_b5_docker_base_inputs.py` | `dd1a51bee722f7ca4868f3e9ec42982a12bf6e00c362c87cdb8175fbe55a440b` |
| 준비 실행기 `scripts/n6_b5_batch1_prepare.py` | `6e5392455b8fc2a1d85f1cbbd9f1c2d63ef342d67d6e9c5c7b1009a7d97eb64f` |
| A 순차 실행기 `scripts/n6_b5c_a_dryrun.py` | `f3d4aef271a2eb173ac014bb25bf1d4ac4cd467f048013d00fa043472509029a` |
| 이미지 확인 기록 `install-tools-b5c-image-check.json` | `50309f1bdf2b3ae7d48d1921c87bde7a8080b639fcf0a1acc031c2e57fcb8f3b` |
| 공식 전체 이미지 `node:22.23.3-bookworm`, `linux/amd64` manifest SHA-256 | `c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d` |

새 이미지에서 한 번 확인한 버전은 Node `22.23.3`, npm `10.9.9`, corepack `0.36.0`, Git `2.39.5`, Python `3.11.2`, Make `4.3`, g++ `12.2.0`이다. Yarn Classic `1.22.22`, Yarn Modern `4.10.3`, pnpm `9.15.9`는 기존 도구 기록의 값 그대로다. Git 설정은 lock에 공개 GitHub `git+ssh://git@github.com/` 또는 `ssh://git@github.com/`가 있을 때만 설치 컨테이너 환경의 `url."https://github.com/".insteadOf`로 적용하고 설정을 설치 메타데이터에 기록한다. lock의 커밋은 바꾸지 않으며 비밀 값·SSH 키·토큰은 넣지 않았다. Git 의존성 lock, 두 SSH 주소의 네트워크 없는 Git 재작성, 도구 차단, 동일 lock·폴더 1회 설치를 합성 검사했다.

첫 라운드는 `a-dryrun-v3/`에 보존했다. 일반 샌드박스의 Docker 소켓 권한 거부로 첫 리비전의 (d) 컨테이너 시작이 환경 차단되었고, 뒤 네 건은 시작하지 않았다. 컨테이너 접근을 확인한 뒤 같은 다섯 건을 `a-dryrun-v3/round-2/`에서 한 번에 한 리비전씩 실행했다. 첫 실행 2026-10-18 03:12:37 UTC부터 마지막 종료 03:21:03 UTC까지 505.79초로 공유 2시간 한도 안이다. 1라운드 리비전 시간 합계 27.44초, 2라운드 합계 456.45초이며 각 리비전은 60분 미만이다. 규칙 변경이나 새 수집기 결함이 확인되지 않아 3라운드는 실행하지 않았다. 아래 `실패`는 각 단계가 기준 입력을 제공하지 못했다는 뜻이며 B 판정이나 음성 결과가 아니다.

| 1라운드 A 리비전 | (a)/(b)/(c)/(d)/(e) | 실제 스크립트 사슬 | 설치 exit/초 | 빌드 exit/초 | 테스트 exit/초 | 기준 입력 | R1CS 해시 일치 | 실패·중단 사유 |
|---|---|---|---|---|---|---|---|---|
| aq-011-93343c3cd34c | 미기록/미기록/미기록/환경 차단/미실행 | 없음 | 미실행 | 미실행 | 미실행 | 미확보 | 확인 불가 | Docker 소켓 접근 권한 거부; 27.44초 |
| aq-012-44d0df2ab46e | 미실행/미실행/미실행/미실행/미실행 | 없음 | 미실행 | 미실행 | 미실행 | 미확보 | 확인 불가 | 앞 리비전 환경 차단 뒤 미실행 |
| aq-016-0a7d49b1c135 | 미실행/미실행/미실행/미실행/미실행 | 없음 | 미실행 | 미실행 | 미실행 | 미확보 | 확인 불가 | 앞 리비전 환경 차단 뒤 미실행 |
| aq-017-9703bbce0c43 | 미실행/미실행/미실행/미실행/미실행 | 없음 | 미실행 | 미실행 | 미실행 | 미확보 | 확인 불가 | 앞 리비전 환경 차단 뒤 미실행 |
| aq-024-6f6781246415 | 미실행/미실행/미실행/미실행/미실행 | 없음 | 미실행 | 미실행 | 미실행 | 미확보 | 확인 불가 | 앞 리비전 환경 차단 뒤 미실행 |

2라운드의 실제 스크립트 사슬은 정적 예상 목록이 아니라 package manager 로그 발표로 확인한 `script_chain_executed`다. 경로는 모두 `circuits/package.json`이며 `build → build:types → build:ts` 순서다. 정적 계획의 동적 호출은 실제 실행이 확인되지 않아 사슬에 넣지 않았다. exit/초의 `재사용` 행은 설치 프로세스를 새로 실행하지 않았고 0.00초로 기록한 결정이다.

| 2라운드 A 리비전 | (a)/(b)/(c)/(d)/(e) | 실제 스크립트 사슬 | 설치 exit/초 | 빌드 exit/초 | 테스트 exit/초 | 기준 입력 | R1CS 해시 일치 | 실패 사유 |
|---|---|---|---|---|---|---|---|---|
| aq-011-93343c3cd34c | 실패/실패/실패/실패/실패 | build → build:types → build:ts (1회) | 0/62.99 | 2/23.99 | 1/2.49 | 미확보 | 예 | 빌드 TypeScript 오류; 다른 테스트는 설치 유발 조건 없이 실패 |
| aq-012-44d0df2ab46e | 실패/실패/실패/실패/실패 | 없음 | 1/34.04, 재사용 1/0.00 | 미실행 | 미실행 | 미확보 | 예 | lock 설치의 Yarn registry 요청 404; 동일 lock 재설치 없음 |
| aq-016-0a7d49b1c135 | 실패/실패/실패/실패/실패 | 없음 | 1/36.20, 재사용 1/0.00 | 미실행 | 미실행 | 미확보 | 예 | lock 설치의 Yarn registry 요청 404; 동일 lock 재설치 없음 |
| aq-017-9703bbce0c43 | 실패/실패/실패/실패/실패 | build → build:types → build:ts (1회) | 0/59.33 | 2/24.39 | 미실행 | 미확보 | 예 | 빌드 TypeScript 오류 |
| aq-024-6f6781246415 | 실패/실패/실패/실패/실패 | build → build:types → build:ts (5회) | 0/62.01, 재사용 0/0.00 ×4 | 2/23.19, 2/5.18, 2/5.59, 2/5.10, 2/5.72 | 1/2.25, 1/2.16, 1/2.54, 1/1.32, 1/2.12, 1/1.80 | 미확보 | 예 | 다섯 빌드의 TypeScript 오류; 두 테스트는 설치 유발 조건 없이 실패 |

2라운드에서 `aq-011`·`aq-017`은 각각 `circuits/yarn.lock`과 `circuits` 폴더를 실제 1회 설치해 성공했고 빌드에서 실패했다. `aq-012`·`aq-016`은 같은 lock·폴더를 1회 설치해 실패한 뒤 각각 한 번의 후속 설치 결정을 실패 재사용으로 기록했다. `aq-024`의 설치 결정 다섯 번도 모두 같은 `circuits/yarn.lock`·`circuits` 폴더이며 실제 설치 1회와 결과 재사용 4회다. 다른 lock·폴더 설치나 같은 lock 재시도는 없었다. 2라운드 결과는 기준 입력 0/5이고 컴파일한 R1CS 해시는 다섯 건 모두 해당 A 참조 해시와 일치했다. 1라운드 `round.json` SHA-256은 `58ba1ce4800cac3a192ad20adfce185807f7f6933ee7d8eb427f28d524a1850f`, 2라운드 index SHA-256은 `db40cb6b85f950010b1c34ce1e6fcdbb03fd0d3972d8c49cd3b03eac9538cc66`이다.

**B 첫 설치 전 확정판:** `install-tools.json` SHA-256 `0daf78af39e06dddb1776cf1f4b1ffd875a26054e2cd4d5c39c8f52560de4688`, 수집기 SHA-256 `dd1a51bee722f7ca4868f3e9ec42982a12bf6e00c362c87cdb8175fbe55a440b`, 준비 실행기 SHA-256 `6e5392455b8fc2a1d85f1cbbd9f1c2d63ef342d67d6e9c5c7b1009a7d97eb64f`, 이미지 `linux/amd64` manifest SHA-256 `c4d5523090a817b7aa86d2111241fdd4f66d1e27782b44160e6aa63b357ecb2d`. B 설치가 시작되면 이 도구들을 바꾸지 않는다. B 1묶음 명령의 캐시 질문에는 `/Volumes/zkfdo-jcache/n6-b5-batch1`을 넣는다. 폴더 존재 확인은 성공했고 남은 용량은 523,922,748 KiB(약 499.65 GiB)였다. 이 세션에서 B 명령은 실행하지 않았다.

고친 도구 결함은 네 가지다: (1) Git이 빠진 slim 이미지를 같은 Node 버전의 공식 전체 이미지로 교체, (2) 공개 GitHub SSH lock 주소를 컨테이너 Git 설정으로 HTTPS에 연결, (3) Git·circom 등 컨테이너 실행 파일 누락을 (d) 실패 대신 도구 차단으로 분류, (4) 같은 lock·폴더의 반복 설치를 1회 실제 설치와 후속 결과 재사용으로 변경. 1라운드 Docker 소켓 권한 거부는 실행 환경 차단이라 코드 보정 목록에 넣지 않았다. 실 A 2라운드에서 추가 코드 결함은 발견하지 않았다.

Python 합성 검사 76건, Python 구문 검사, `cargo fmt`와 `cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`가 모두 통과했다. Git 의존성 lock과 SSH 재작성은 실제 네트워크 없이 합성 저장소에서 확인했다. A 공식 준비 실패 2,161건과 공식 기준 입력 index SHA-256 `18ad0bee4278fd77f94b11c354e531a31a4a5d2c0f96c9bd87d7e17c850d1508`는 불변이다. 기존 `a-dryrun/`과 `a-dryrun-v2/`도 보존했다. A 후보 입력·witness 값, B 후보 값·판정 결과는 열지 않았고 B 기준 입력 수집·B 의존성 설치·B 판정·S 재퍼징은 0건이다. commit·push·PR은 하지 않았다.


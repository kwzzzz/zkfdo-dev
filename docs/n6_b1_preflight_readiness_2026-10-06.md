# N6-B1 검수 보정과 B 사전 점검

담당: miiz. 상태: **검수 보정·B `preflight-all` 완료, B 퍼징 미착수**. 기준일: 2026-10-06.

이 문서는 [초기 B1 준비 기록](n6_b1_readiness_2026-10-06.md)을 보존하고, B 실행 전 검수 보정과 새 v6 산출물을 기록한다. v1·v2 실행기, 고정 대상, 예산, seed와 대상 순서는 바꾸지 않았다.

## 보정 결과

- [v3 실행기](../scripts/run_policy_a_engine_v3.py)의 프로세스 그룹 RSS 합 관측 간격을 1.0초로 바꿨다. 각 시도와 캠페인 ledger도 1초 표본의 최대 동시 RSS 합이라는 측정 의미를 기록한다. 10 GiB 초과 종료·회수 self-test를 실제 `ps` 접근 조건에서 다시 통과했다.
- [대기열 실행기](../scripts/run_n6_b_queue.py)는 `preflight-all`과 `execute`를 분리한다. `execute`는 같은 queue 해시의 60개 preflight 결과가 모두 기록되기 전에는 거부하며, 실행 중 preflight나 컴파일을 호출하지 않는다.
- W preflight 실패는 같은 단위의 S를 막지 않는다. 각 방식은 `preflight_failed` 또는 캠페인 결과를 따로 남긴다.
- `million_plus` 단위가 실행 중이면 다음 `million_plus` worker를 잠금에서 대기시키지 않고, 고정 대기열에서 뒤의 첫 일반 단위를 시작한다. 실제 단위 시작 순서와 sequence는 `state.json`에 기록한다.
- 통과한 preflight의 `compile/*/artifacts/` 아래 `.r1cs`, `.wasm`, `.cpp`, `.dat`, `.o`만 경로·SHA-256·크기 원장을 먼저 쓴 뒤 크기와 해시를 재확인해 삭제한다. snapshot, compile workspace, JSON, 로그와 실패 preflight의 진단 산출물은 보존한다.

결정적 검사는 W preflight 실패 뒤 S 실행, 전체 preflight 관문, 큰 회로를 건너뛴 일반 단위 선택, 실제 시작 순서, 삭제 범위와 원장, seed 독립 preflight 재사용의 동등성 조건을 확인한다. `campaign_id`와 `initial_seed` 외 필드가 하나라도 다르면 재사용을 거부한다.

## v6 고정 산출물

- 대상 목록: `docs/n6_targets_b_2026-10-06.json`, SHA-256 `853eef3b91698ea4f6c8e9189e0bfb765b697d7f6a505800cb7e42644d07dca6`.
- spec: `runs/n6-2026-10-06/specs-v6/`의 60개. stage1 10개 × seed `2026100601/02/03` × W/S다.
- queue: `runs/n6-2026-10-06/queue-v6.json`, SHA-256 `105809365b2e011743a057640bc36a851861a25d568edfdf9d364d71ad3a4522`.
- v3 실행기: SHA-256 `23e94c40efccf44b3f42e8415c6b61491b9d0cc0b6640f8119263536779ced62`.
- queue 실행기: SHA-256 `aecf63c55785c30dfef9238c48576f5b2fb1e7f5d2514d08d6bc7cf85cd5845e`.
- self-test: `runs/n6-2026-10-06/state-machine-v3-v6-real-2/self-test-v3.json`, SHA-256 `79cf282fb529da677f02d75bfcf473d76ed6696824e01f2064da96e2e9ab385f`.

queue의 60개 spec 해시와 각 spec의 v3 pin을 현재 파일에 다시 대조했다. queue runner pin도 현재 파일과 일치한다. B 예산은 방식별 3,600초, S 시도 상한은 30초이며 기존 seed·순서를 유지한다.

## 개발 회로 재시험

A-02 inference 개발 회로에서 W와 S preflight를 모두 끝내고 산출물을 원장화·정리한 뒤 각 60초 캠페인을 실행했다. 평가 대상 결과가 아니며 후보 파일 내용은 열지 않았다.

| 방식 | spec SHA-256 | preflight | 캠페인 wall | outcome | 시작 분모 | 프로세스 트리 RSS 최대 |
|---|---|---|---:|---|---:|---:|
| W | `d15a700f0aed8445a795156128ade0cf225503fd8dfbf2ae31412a973fc2e17d` | 1/1 성공, 산출물 1개·31,003,840 B 삭제 | 60.072초 | timeout 1 | 1/1 | 1,457,864,704 B |
| S | `c9a8104308ff348d91b8a07085c9527a8191cf9161b2c3e1b9a3452937ce0b53` | 21/21 성공, 산출물 21개·290,524 B 삭제 | 60.029초 | candidate signal 1·no-candidate 5·timeout 2 | 8/21 | 8,503,296 B |

W ledger SHA-256은 `868b660986280406ac385806aff4671be1be3f6e78d3898771b6af6444fd3581`, S는 `2aad622b7f6aa97921f4326a453430cbd1129f20997c2b9c3ac275fe67bc0efa`다. candidate signal은 실행 경로 확인이며 결함·원인·의미 판정이 아니다.

## B `preflight-all` 결과

원본 요약은 `runs/n6-2026-10-06/stage1-v6/preflight-all.json`이고 SHA-256은 `e4164c2b5857c375432ff44f06f655e5ac6ac07af27d967688b224475cc04bec`다. 60/60 spec에 결과가 있으며, **통과 51·실패 9**다. W는 30/30 통과했고 S는 21/30 통과했다.

seed는 preflight의 source·plan·compile command에 관여하지 않는다. 각 대상·방식의 첫 seed 20개는 실제 컴파일했고, 나머지 40개는 `campaign_id`와 `initial_seed`만 제외한 전체 spec 동등성을 확인해 첫 ledger·snapshot·해시를 참조하는 별도 ledger를 만들었다. 따라서 물리적 preflight 실행은 20개, 명시적 seed 독립 재사용은 40개다. 재사용 ledger는 실제 컴파일 시간을 0으로 기록하고 원본 preflight 시간과 해시를 별도 필드에 보존한다.

| 저장소·entrypoint | 제약 | W 실제 preflight | S 실제 preflight |
|---|---:|---|---|
| anon-aadhaar/anon-aadhaar · `aadhaar-verifier.circom` | 1,115,080 | 통과, 74.997초 | 실패, 389/390 성공, 1,029.064초¹ |
| DoraFactory/Vota-Circuits · `tally.circom` | 4,802,568 | 통과, 63.493초 | 통과, 274/274, 299.750초 |
| iden3/circuits · `credentialAtomicQueryV3.circom` | 114,758 | 통과, 11.355초 | 통과, 385/385, 413.513초 |
| pantherfoundation/panther-core · `mainZAccountRenewalV1.circom` | 111,270 | 통과, 92.280초 | 통과, 786/786, 839.857초 |
| rarimo/passport-zk-circuits · `m.circom` | 733,264 | 통과, 80.753초 | 통과, 35/35, 40.225초 |
| selfxyz/self · `vc_and_disclose_kyc.circom` | 102,406 | 통과, 273.779초 | 실패, 415/416, 443.010초 |
| tanctl/zylith-old · `private_liquidity.circom` | 311,639 | 통과, 9.203초 | 실패, 304/305, 323.746초 |
| tangle-network/protocol-solidity · `poseidon_vanchor_16_2.circom` | 290,196 | 통과, 47.019초 | 통과, 292/292, 311.333초 |
| Zellic/zkerc20 · `circuit.circom` | 331,643 | 통과, 22.913초 | 통과, 153/153, 166.361초 |
| iden3/circuits · `linkedMultiQuery3.circom` | 116,498 | 통과, 11.071초 | 통과, 347/347, 371.221초 |

¹ 배터리 부족으로 queue와 runner를 `SIGSTOP`한 구간이 이 wall에 포함된다. 정지 구간을 runner가 별도 계측하지 않았으므로 1,029.064초를 활성 준비 비용으로 쓰지 않는다.

세 S 실패는 각각 마지막 조각 한 개가 Circom `P1014`로 종료된 결과다. 모두 `circomlib/circuits/bitify.circom` include를 찾지 못했으며 stderr SHA-256은 `2c86b18d1cad322292bfe8cf24c881ad9678b54087f107baa24d61580663fb4c`다. 실패 target은 aadhaar `sha256:2bb0a6c0…`, selfxyz `sha256:9b832124…`, zylith `sha256:d931d678…`이고, seed 2·3은 동일 spec 조건의 실패를 재사용 ledger에 보존했다.

전체 관측 wall 합은 4,921.975초이고 queue invocation wall은 4,927.049초다. 둘 다 위 정지 구간을 포함한다. 시작·종료 free disk는 181,369,491,456 B → 165,835,567,104 B로 15,533,924,352 B 감소했다. 통과 preflight에서 2,282개·1,831,694,156 B의 컴파일 산출물을 원장 후 삭제했다. 전체 실패인 세 S preflight는 진단 보존 때문에 성공 조각의 `.r1cs` 1,108개·792,014,168 B를 남겼다.

## 실행 관문과 검사

`runs/n6-2026-10-06/stage1-v6/`에는 `units/`, `state.json`, `host-load.jsonl`, campaign ledger가 없다. 따라서 B zkFuzz 캠페인은 **0회**다. 이후 `execute`를 지시받으면 W preflight 실패는 `preflight_failed`로 남기고 S를 계속하며, S preflight 실패는 W만 실행하고 S를 `preflight_failed`로 남긴다.

관련 Python 단위 검사 13건과 전체 Python 회귀 384건이 통과했다. `cargo fmt`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test`도 통과했고 Rust 결과는 348 passed·22 ignored다. 이 준비 결과는 후보 탐지·의미 판정·평가 성과가 아니다.

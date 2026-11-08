A는 개발 세트다. 이 결과는 J 보강의 성과가 아니다.

# J 보강 4차 — 판정 의미와 두 시범

**완료(2026-10-28 KST).** 두 요청×세 군 모두 결과 검증·군별 정리까지 완료했다. **2055는 예산 증가로 미판정 1개가 배제로 바뀌었다. 2200은 직접 완성 264시도 모두 원본 제약을 깨서 추가 도달·L1이 0개다.** 나머지 13요청은 실행하지 않았다.

## 1. 반박·판정 범위

- 릴리스로 맞춰도 v2.2와 현재 v2.3 코드는 다르다. 효과는 같은 새 release의 세 군 사이에서 보고, v2.2는 판정 대조와 계획용 과거 시간으로 사용했다. ①′는 ①보다 총 예산이 커진다.
- `aligned`는 별도 `{reason, violation, detail}` 칸이다. 실제 Circom assert 메시지와 template·line 증거가 있을 때 `honest_aborted`, 정상 계산의 출력 차이면 `output_differs`, 같으면 `outputs_equal`이다. 도구·시간·입력 오류나 불명확한 중단은 `unknown`이다. 기존 `l1`·`influence`·result 계약은 유지했다.
- 직접 완성 시간은 배제 예산에서 차감하지 않았다. 별도 시간과 군 전체 비율을 기록한다. 거부된 264개 벡터로 보장하는 것은 **그 벡터들의 원본 불만족**까지다.
- 실패 위치는 0부터 시작하는 제약 번호와 관련 wire 별칭의 **공통 상위 부품 경로**다. R1CS/SYM에 없는 정확한 소스 제약 소유자를 주장하지 않는다. 모델 유무는 제공된 S 후보의 유무가 아니라 **J 역방향·수리 solver 모델**의 유무다.

## 2. 시작 조건·공간·정리

처음(15:02:47Z), 시범 직전(15:18:28Z), 종료 감사(15:54:34Z)에 프로세스 목록과 state를 직접 읽었다. aq `stopped / interrupted / signal 15; request saved`, 진행 요청 0, 차단 프로세스 0. 정지 시각은 13:22:00Z이며 state SHA는 끝까지 `d06cdb38c614e9e56ec4b7be601d2e87bc966bf354836da31cb05d6ae091f52d`였다. plan-v6_1 작성 중 자체 J harness가 감지된 기록은 남아 있지만, harness가 끝난 뒤 별도 시범 직전 관문을 통과했다.

이전 **851 GiB 계산은 폐기**했다. 아래 최대는 요청·history의 `max(0, disk_before.external_free_bytes − judging_free_bytes_at_finish)`다. 새 캐시는 해당 리비전의 `deferred_cache_store_bytes` 전체 최대를 보수적 대용 추정으로 사용했다(요청별 새 캐시 크기의 보장된 상한은 아님). 단위 GiB.

| 리비전 | 기록 수 | 최대 차이 | 새 캐시 추정 | 필요량 2×최대+캐시 |
|---|---:|---:|---:|---:|
| aq-011 | 21 | 12.246 | 41.388 | 65.879 |
| aq-016 | 15 | 48.162 | 53.040 | 149.365 |
| aq-017 | 15 | 28.146 | 37.573 | 93.865 |
| aq-026 | 3 | 236.241 | 64.367 | 536.848 |

기록 없으면 399.7 GiB를 사용한다. 매 군 시작에는 image 여유가 필요량 이상이어야 하고, 시작·매분 검사에서 image와 X9 실제 여유가 각각 100 GiB 이상이어야 한다. 아래는 **J 실행 시작→종료(정리 전)** 여유다. X9 연결은 `hdiutil info`로 확인했다.

| 요청·군 | image 시작→끝 GiB | X9 시작→끝 GiB |
|---|---:|---:|
| 2055 ① 기본 | 607.198→606.733 | 651.484→651.484 |
| 2055 ①′ 공정 | 607.008→606.733 | 651.484→651.484 |
| 2055 ③a 직접 | 607.008→606.732 | 651.484→651.484 |
| 2200 ① 기본 | 606.853→601.366 | 651.484→648.115 |
| 2200 ①′ 공정 | 601.686→601.385 | 648.115→648.115 |
| 2200 ③a 직접 | 601.687→599.755 | 648.115→648.115 |

6군 모두 기존 `cleanup_v2_1.cleanup_tree`로 자기 작업 폴더만 정리했고 마지막에 6개 폴더 부재를 직접 확인했다. 결과·작은 증거·공유 캐시는 보존했다. 유효 직접 witness는 0개다. 최종 image 601.687 GiB, X9 648.115 GiB, 전용 cargo target 1.120 GiB. aq 판정·캐시 변경, compact, 설치, git 쓰기, 하위 에이전트, B/RQ-C 자료 사용 없음.

## 3. 변경·합성·회귀

- `boost.rs:95,133,163,298,450`: 실패 제약 위치, 의미 정렬, 클래스 진단, 단계 시간. `lifting/mod.rs:1097`은 옵션이 켜졌을 때 클래스 진단만 덧붙인다. `src/bin/zkfdo-j-v23.rs:37`의 `--aligned-diagnostics`는 `--constraint-witness`를 요구하며 기본 꺼짐이다. view 경로 변경 없음.
- `repair.rs:2005`는 합성 helper만 수정했다. 명시적 입력 모델을 시험하면서 helper가 모든 입력을 0으로 다시 고정해 UNSAT였던 시험 오류를 고쳤다. 운영 수리 알고리즘은 유지했다.
- `j_boost_measure_20261027.py:196,254,640,680,767,917,1010,1077,1135`: 공간·결과·정리·예상·실행·재확인. J 출력은 존재하지 않는 `judgment/`로 분리했다. 상대 include 원문을 보존해 익명 인스턴스 offset을 유지했다. 초기 상태 기록 오류 때도 자식 프로세스를 회수한다.
- frozen plan-v5와 미실행 plan-v6를 보존했다. plan-v6에서 필요량을 X9에도 적용하던 과도한 관문을 수정한 **plan-v6_1**을 사용했다. 새 계획은 2055·2200만 허용한다.

| 합성 경우 | 확인 결과 |
|---|---|
| 출력 차이 | 원본 두 검사기 통과, `aligned=output_differs` |
| 출력 같음 | 원본 두 검사기 통과, `outputs_equal` |
| 최상위 출력 0개 | `outputs_equal`, `output_differs` 불가 |
| 진짜 정상 assert 중단 | `honest_aborted`; 기존 `l1=null`, `influence=honest_comparator_aborted` 유지 |
| 불명확한 중단·도구/입력 오류 모양 | `unknown` |
| 원본 제약 위반 / 매핑 누락 | 거부와 첫 실패 번호·경로 / unknown |

최종 `cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test` **426 통과·0 실패·24 ignored**. 분리한 J 24개는 요청한 4d harness를 격리해 **release 바이너리로 24/24 통과**(fixture 최대 31제약). 새 직접 완성 합성은 1–3제약. 실행기 합성 **18/18**(물리 여유 중단·벽시계 상한·수집 후 정리·재시작·국소 재질의 포함). 모든 빌드는 전용 target, `-j 1`, nice 19, 4c 30/20/18 GiB·target 8 GiB 감시 아래 순차 수행했다. 새 harness의 잠금 파일 갱신 요구는 설치 없이 `--offline`으로 해결했다.

| 바이너리 | SHA-256 (종료 때 직접 재계산) |
|---|---|
| 세 군 공통 새 release | `3fcf4c1ff5db62606f570ff25d786035a025bf91910ed2184f32a08736930eda` |
| aq v2.2 — 전후 동일 | `c78166319c0e12a62d89697ec0b248ef916e236961db9f890ec992f53c59a835` |
| 4d v2.3 — 전후 동일 | `05649971dc0fb9ece435324d3c779e2c6f148f4dc6efd74ff9fecf5a9690e700` |

이전 debug `a82d6542…`는 `step4/backup/bin/zkfdo-j-v23-debug-step3`에 따로 보존했고 debug target을 삭제하지 않았다. 아래 모든 기록 경로의 기준은 `runs/j-boost-2026-10-27/step4/`다.

## 4. 두 시범 결과

세 군 seed=0. ① 요청 공유 배제 예산 20초, ①′·③a 클래스당 20초. 요청 상한은 2055 각 군 1,934초, 2200 각 군 4,859초로 동일하다. 시간은 **J 실행 wall(준비 포함, 정리 제외)**. RSS는 1초 표본, 작업 공간은 60초 표본+종료 시점 최대이며 짧은 순간의 실제 peak를 보장하지 않는다.

| 요청(출력 수)·군 | 배제 / 미판정 | wall 초 | 실제 sweep 초 | compile 초 / hit | RSS GiB | 작업 공간 GiB |
|---|---:|---:|---:|---|---:|---:|
| 2055(0) ① 기본 | 29 / 7 | 249.913 | 22.911 | 16.079 / 0 | 2.640 | 0.279 |
| 2055(0) ①′ 공정 | 30 / 6 | 340.889 | 134.556 | 0.020 / 4 | 0.837 | 0.279 |
| 2055(0) ③a 직접 | 30 / 6 | 341.698 | 134.542 | 0.020 / 4 | 0.808 | 0.280 |
| 2200(9) ① 기본 | 0 / 16 | 524.131 | 20.142 | 290.205 / 71 | 1.019 | 1.703 |
| 2200(9) ①′ 공정 | 0 / 16 | 255.900 | 44.134 | 0.019 / 318 | 1.017 | 0.306 |
| 2200(9) ③a 직접 | 0 / 16 | 275.629 | 44.007 | 0.019 / 318 | 1.249 | 1.936 |

**2055 운영 시범:** ①의 36클래스 판정·사유 모두 v2.2와 동일. ①′에서 `main.zAccountRenewalV1.zAccountUtxoInSpendPubKeyDeriver.drv.segments[0].e2m`만 `budget_exhausted`→`closed_cone_unsat`. ③a는 ①′와 동일하며 직접 완성 모델 snapshot이 0개다. 직접 완성 시간·추가 도달·L1 모두 0. 미판정→배제 **1**, 반대 방향 **0**은 예산 증가가 포함된 관측이다.

**준비 공유:** 2055의 원본 O0/O1·hinted 컴파일 12.250초는 뒤 군에서 cache hit로 0초, 이후 클래스 수리 컴파일까지 합친 총 compile은 16.079→0.020→0.020초다. 각 군의 부품 compile은 약 0.013초, 부품 honest witness는 0.045/0.049/0.050초로 다시 실행했다. 2200 총 compile은 290.205→0.019→0.019초다. witness 생성은 공유하지 않았다. 따라서 2200 wall 감소를 옵션의 탐색 속도 개선으로 읽지 않는다. cache key는 `lifting/mod.rs:3857`의 compiler SHA·O0 여부·entry/root/library 경로·전체 closure 파일 SHA이며 세 군이 같은 cache를 쓰고 instance-store는 군별이다.

**국소 반박 2건:** `126-local_refutation`, `127-local_refutation`은 이전과 같은 O0 SHA `5cead78c7ce55c41c6c48c85df6ca8ab70c8af85da7fb41860db8d6c0c90ebec`를 확인했다. 원본 **190,532개 전체 제약**과 정확한 후보 입출력만 고정하고 다른 main 입력을 모두 풀어 재질의: 각각 **UNSAT**, 14.097초·15.004초. 범위는 이 정확한 후보다. 기존 판정 기록은 바꾸지 않았다.

**2200 효과 시범:** 세 군 모두 16 미판정. 미판정→도달·배제 **0**, 반대 방향 **0**. 기본 ①은 v2.2와 결론 16/16 동일하나 `main.birthDateUpperboundCompare.firstDateDecoder.dateEncoder`의 사유가 `synthesis_timeout`→`budget_exhausted`로 달랐다. ①′·③a는 사유까지 동일하다.

아래 모든 결론은 unknown이다. T=`synthesis_timeout`, M=`synthesis_model_not_reproduced`, B=`budget_exhausted`. 경로 약어: BL=`main.birthDateLowerboundCompare`, BU=`main.birthDateUpperboundCompare`, EL=`main.expirationDateLowerboundCompare`, EU=`main.expirationDateUpperboundCompare`. 실패 위치는 **각 클래스 첫 시도의 첫 실패**이며 264시도 전부의 번호·경로는 직접 군 `j-boost.json`에 있다.

| 클래스 | ① | ①′ | ③a | aligned | 직접 시도 / 초 | 진단: 첫 제약 @공통 부품 |
|---|---|---|---|---|---:|---|
| `BL.firstDateDecoder.dateEncoder` | T | T | T | 미시도 | 0 / 0.000 | solver 모델 없음 (timeout) |
| `BL.firstDateNormalization.firstDateDecoder.dateEncoder` | M | M | M | unknown | 27 / 1.624 | 1736 @BL.firstDateDecoder.dateEncoder (O0 거부) |
| `BL.firstDateNormalization.secondDateDecoder.dateEncoder` | M | M | M | unknown | 36 / 2.162 | 1754 @BL.firstDateNormalization.dateIsLess (O0 거부) |
| `BL.secondDateDecoder.dateEncoder` | T | T | T | 미시도 | 0 / 0.000 | solver 모델 없음 (timeout) |
| `BL.secondDateNormalization.firstDateDecoder.dateEncoder` | M | M | M | unknown | 7 / 0.417 | 0 @main (O0 거부) |
| `BL.secondDateNormalization.secondDateDecoder.dateEncoder` | M | M | M | unknown | 31 / 1.851 | 1846 @BL.firstDateNormalization.secondDateDecoder.dateEncoder (O0 거부) |
| `BU.firstDateDecoder.dateEncoder` | B | T | T | 미시도 | 0 / 0.000 | solver 모델 없음 (timeout) |
| `BU.firstDateNormalization.firstDateDecoder.dateEncoder` | B | M | M | unknown | 12 / 0.728 | 0 @main (O0 거부) |
| `BU.firstDateNormalization.secondDateDecoder.dateEncoder` | B | M | M | unknown | 21 / 1.280 | 1741 @BL.firstDateNormalization (O0 거부) |
| `BU.secondDateDecoder.dateEncoder` | B | T | T | 미시도 | 0 / 0.000 | solver 모델 없음 (timeout) |
| `BU.secondDateNormalization.firstDateDecoder.dateEncoder` | B | M | M | unknown | 32 / 1.941 | 2180 @BU.secondDateDecoder.dateEncoder (O0 거부) |
| `BU.secondDateNormalization.secondDateDecoder.dateEncoder` | B | M | M | unknown | 28 / 1.698 | 1741 @BL.firstDateNormalization (O0 거부) |
| `EL.firstDateDecoder.dateEncoder` | B | M | M | unknown | 31 / 1.890 | 8049 @EL.dateIsLess (O0 거부) |
| `EL.secondDateDecoder.dateEncoder` | B | M | M | unknown | 7 / 0.421 | 563 @main (O0 거부) |
| `EU.firstDateDecoder.dateEncoder` | B | M | M | unknown | 7 / 0.421 | 563 @main (O0 거부) |
| `EU.secondDateDecoder.dateEncoder` | B | M | M | unknown | 25 / 1.511 | 8168 @EU.dateIsLess (O0 거부) |

**직접 완성 진단:** 모델 없음 4클래스, 모델이 있으나 기존 hint 재현 실패 12클래스. 그 12클래스의 **264시도 전부 O0 제약 위반**. 목표·O1 사상·snarkjs·정상 계산까지 도달한 시도는 0이다. `aligned`: unknown 264시도(12클래스), 미시도 4클래스; honest_aborted/output_differs/outputs_equal은 각각 0. 원본 검증 도구 실패도 0이지만 도구 단계까지 간 시도 자체가 없다.

**직접 완성 시간:** 15.944882초, 군 wall 275.628606초의 **5.785%**. 벡터 완성 0.255659초, O0 검사 11.160756초, query 기록 등 나머지 4.528467초. O1·snarkjs·정상 계산은 미도달. ①′→③a wall 차이는 19.729초이며 capture 시간과 구분한다. 클래스별 시간은 위 표와 원장에 보존했다.

**원인별:** 2200의 M 원인 12클래스는 모두 미판정 유지, T 4클래스도 미판정 유지. 2055 기본 군의 미판정 7개는 `cause_before_budget=synthesis_timeout`이고 그중 1개가 예산 증대로 배제됐다(①′·③a에는 같은 원인의 미판정 6개). 두 요청에서 `cone_refuted_by_propagation_only`와 `injection_not_applied`는 관측 0이다. 최종 사유의 B→M/T 변화만으로 미판정 감소라고 세지 않는다.

## 5. 남은 13요청 예상 — 실행하지 않음

두 시범으로 재계산한 세 군 합계 **17.64시간**, 계획용 2배 **35.27시간**. 실제 요청 상한들의 합계는 별도 63.60시간이다. 예측식은 `3×과거시간×1.01213 + 클래스수×(2×2.97319+1.23307)`초. 옵션 차이는 compile 시간을 빼고 두 시범에서 큰 클래스당 증가량을 적용했다. 적은 시범의 선형 추정이므로 보장 상한이 아니다.

| 요청 | 세 군 예상 분 | 계획용 2배 분 | 공식 필요 GiB(100 하한 별도) |
|---|---:|---:|---:|
| aq-011 / 2044 | 17.2 | 34.3 | 65.879 |
| aq-011 / 2045 | 25.3 | 50.6 | 65.879 |
| aq-011 / 2047 | 17.1 | 34.1 | 65.879 |
| aq-011 / 2056 | 29.1 | 58.3 | 65.879 |
| aq-011 / 2067 | 27.4 | 54.8 | 65.879 |
| aq-016 / 2101 | 98.6 | 197.2 | 149.365 |
| aq-016 / 2109 | 92.6 | 185.2 | 149.365 |
| aq-016 / 2117 | 82.8 | 165.6 | 149.365 |
| aq-017 / 2125 | 97.6 | 195.1 | 93.865 |
| aq-017 / 2132 | 98.9 | 197.8 | 93.865 |
| aq-017 / 2139 | 99.1 | 198.1 | 93.865 |
| aq-026 / 2209 | 179.3 | 358.6 | 536.848 |
| aq-026 / 2218 | 193.3 | 386.5 | 536.848 |

새 시범에서 최대 image 할당 증가 5.486 GiB, 작업 공간 표본 최대 1.936 GiB를 관측했다. 새 캐시·증거 등 보존량은 2055 0.346 GiB, 2200 5.166 GiB다. 이를 과거 리비전별 최대·캐시 대용값과 대조해도 과거 값이 더 커서 위 공간 요구량은 유지된다. 다른 후보의 작업 공간이 이 시범 수준이라고 가정해 관문을 낮추지 않았다. 13요청 예측은 J 세 군 기준이며 추가 국소 재확인 시간은 포함하지 않았다.

## 6. 기록·상태·남은 문제

실행 계획: `step4/plan-v6_1.json`, SHA `a36862740b7da9ebe0da81e460d7465b8de2c813a266a53229e2a31c5d80a78c`. 종료 상태 `completed`, 마지막 갱신 15:52:33Z. 6군 모두 validated/cleaned, 무거운 실행 잔존 0. 요약 `summary-final-v1.json`, 종료 감사 `final-audit-v1.json`, 전체 전후 파일 SHA `final-sha256-v1.json`. 아래 명령은 저장소 루트 기준이다.

```sh
python3 -B scripts/j_boost_measure_20261027.py status --plan runs/j-boost-2026-10-27/step4/plan-v6_1.json
python3 -B scripts/j_boost_measure_20261027.py summary --plan runs/j-boost-2026-10-27/step4/plan-v6_1.json
```

중단됐을 때의 재개 명령(이번 실행은 완료했으므로 재실행 불필요):

```sh
nohup nice -n 19 python3 -B scripts/j_boost_measure_20261027.py pilots --plan runs/j-boost-2026-10-27/step4/plan-v6_1.json --local-refutation-recheck > runs/j-boost-2026-10-27/step4/resume-v6_1.log 2>&1 < /dev/null &
```

완료 군은 건너뛰고 상태·분당 heartbeat·잠금으로 이어간다. 실패 군을 명시적으로 다시 할 때만 `--retry-failed`를 더한다. 전체 실행 명령은 제공하지 않는다.

남은 문제: 264개 부분 모델을 원본 전체 해로 잇는 기능은 아직 없다. 실패 제약을 반영하는 잔차 확장, 임시 고정 해제, 위반 술어에 의한 다른 후보 탐색은 이번에 구현하지 않았다. **직접 완성만으로 이 요청을 해결하지 못했다는 근거**는 확보했지만, 각 확장이 해결할지와 다른 입력에 유효 위반이 존재할지는 미확정이다. 실제 A에서 aligned의 양성 결과는 없고 합성으로만 확인했다.

### 변경 전후 SHA-256

모든 기존 변경 파일은 수정 전 `step4/backup/`에 복사했다. 실행 중 source/runner/binary를 바꾸지 않았다. 새 보고서는 변경 전 파일이 없다.

| 파일 | 전 | 후 |
|---|---|---|
| `docs/plan_revision_2026-10-01.md` | `38b9cd8d13c2d9e1410a5a2ffc3263e580ad1f80225451b67841f60a2f8e0dc4` | `fe3eae1b5557bf1fc91eafa93ed91c218aaaf38d28e3eb9a60dcf16d4b1a7562` |
| `src/candidate_review/lifting/boost.rs` | `86c436ffd84bad5dac89ec6d7e23bf5ac9ae05f850e65be6f7b772d67b20c7dc` | `637118116b817dda2af6d342a05b5fa6f4826f9baa00cb6f2ccacf038aa65cb4` |
| `src/candidate_review/lifting/mod.rs` | `9f93a5a6b9ef290a786cbfeabd9a99296abfba6bc2282c8cc80456a7569e2d58` | `337b4803766d1f6a06a532df2d6d65a5d26891756de06f1e3372a36bfb665d2f` |
| `src/bin/zkfdo-j-v23.rs` | `2b0783f360f117ead9d83f76fe6bb2cc96dee1c1ac5cd04ac3a39bbd79cdb151` | `f01b6144edded67a3c33e18624a4bfd2dbf8911c9d0674a0a7a5dd54d1d2e0f1` |
| `scripts/j_boost_measure_20261027.py` | `696548ecf9a184013484551cb536c38b868961974dd292e96933ad6a8e394eda` | `c4452dc7ed9331dbb3beb7faf761d6ef07e17a8e7d60e5c4519900aedb4aaeb1` |
| `scripts/j_boost_measure_20261027_test.py` | `72af7d52ce8f04c0f653d9534e7c656109033ea781478ee676eb6fdfd5edb16e` | `f0b3ba71396c7b5f849ed80cfa614cb75579dad0643fab4294f32195e70e6662` |
| `src/candidate_review/lifting/repair.rs` | `4d35f2caa36d869c8e24a8ba6f5fc5dd96c67561b3fe7fd2701a38ae7c2d6729` | `eefb396457afb2dec437e3249eeb97bf5a77e6fdfb6a142264ed8ba292381bec` |

## 확인한 것 / 추정한 것

**확인한 것:** 보호된 두 바이너리와 aq state SHA 유지, 동일 release의 6군 완료·검증·정리, 2055의 미판정 1→배제와 국소 재확인 2 UNSAT, 2200의 264개 원본 제약 위반·추가 도달/L1 0, 단계 시간·자원 표본, 합성·저장소·릴리스 24개 관문 통과.

**추정한 것:** 남은 13요청 17.64시간과 2배 계획값, 새 캐시 대용 크기, 미실행 회로의 공간 요구량. 실패 wire의 공통 상위 경로는 구조상 위치 근거이며 정확한 소스 소유권이나 근본 결함 원인 귀속이 아니다. 다음 정제 방법의 효과와 독립 평가 성과는 아직 확인하지 않았다.

**요약:** 운영 시범은 통과했다. 예산 보강은 2055에서 배제 1개를 더 만들었고, 직접 완성은 2200의 264시도에서 추가 도달을 만들지 못했다. 원본 제약 위반 위치와 비용을 확보했으며 전체 13요청 실행은 하지 않았다.

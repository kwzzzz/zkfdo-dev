# 개발 매핑 보조 분석: J1 "S+J에서만 L1" 5쌍의 위치 (2026-10-26)

상태: 보조 분석. 승인·담당: miiz.

- 공식 RQ-C 표(고정 18개 버그·26행 매핑)에 넣지 않는다.
- 고정 매핑을 넓혀 공식 점수를 바꾸지 않는다.
- inference는 개발 세트(L-03·L-06에 씀)라서 독립 평가가 아니다.
- 읽기와 계산만 했다. 엔진, 퍼징, 판정은 실행하지 않았다.

## 자료

- **판정 기록:** 공식 J1 index `runs/n6-j1-2026-10-09.noindex/request-index.json`, state `runs/n6-j1-2026-10-09.noindex/j-execute.noindex/state.json`(v1 엔진)과 그 result 파일들.
- **대상 버그:** 이 프로젝트의 zkbugs 항목 2개다(`docs/n6_targets_a_2026-10-07.json`). 둘 다 고정 J 매핑에는 선택되지 않았다.
  - `koukyosyumei_clamp_comparator_overflow`: `src/clampTensor.circom:38-67` `Clamp`. 내부 `LessThan(b)` 입력이 범위를 벗어나면 비교가 틀린다.
  - `koukyosyumei_subtract_unconstrained_multiplier`: `src/subtractTensor.circom:3-10` `Subtract`. `d <-- 1`이 제약되지 않는다.
- **인스턴스 이름:** 리비전 `d310309`의 소스에서 가져왔다.
  - `calculatedScoreFraction.circom:16`: `clamp = Clamp(b)`
  - `responseTimeNormalized.circom:23,27`: `subtract1`, `subtract2 = Subtract()`
- **스크립트:** `scripts/n6_dev_mapping_inference_20261026.py`, SHA-256 `44f6dc7487b1b01005d0468d302960df6a33714e301d6d9a108269bff73d2395`
- **출력:** `docs/n6_dev_mapping_inference_2026-10-26.json`, SHA-256 `715b433682a15d61ba9a7b88cbfc543daf793bd10ab348b1302e21639cf7b173`

## 위치 대응 규칙

- **Subtract 항목:** 자기 판정이 TCCT 위반(`entrypoint_violation`)이고, 대표 사이트가 Subtract 인스턴스(`…subtract1`, `…subtract2`)인 클래스.
- **Clamp 항목:** 실효 가정 술어가 도달(`assumption_violation_reachable`)이고, 술어 인스턴스가 Clamp 안의 `LessThan`(`…clamp.LessThan[i]`)인 클래스.
- **그 밖:** 두 항목 어느 쪽에도 귀속하지 않는다. 부모 템플릿의 L1을 자식 버그로 귀속하지 않는다.

## 결과

| 쌍 (리비전·seed) | Clamp 항목 위치의 L1 | Subtract 항목 위치의 L1 | 그 밖의 L1 |
|---|---|---|---|
| inference-original · 01 | 있음 | 없음 | 있음 |
| inference-original · 02 | 있음 | 있음 | 있음 |
| inference-original · 03 | 있음 | 있음 | 있음 |
| inference-r-intdiv · 01 | 없음 | 없음 | 있음 |
| inference-r-intdiv · 03 | 없음 | 있음 | 있음 |

클래스 수:

- **Clamp:** inference-original에서 `main.calculated_score_fraction_comp[i].clamp.LessThan[j]` 술어 도달 9.
- **Subtract:** inference-original에서 `…response_time_normalized_fn[i].subtract1` 2·`subtract2` 2, inference-r-intdiv에서 각 1(TCCT).
- **그 밖:**
  - TCCT: `int_div`, `int_div_2`, `int_div_3`, `response_time_normalized_fn[i].division`, `response_time_reward_metric_fn[i].scoring_function`
  - 술어: `distance_from_score_fn[i].positive`, `response_time_normalized_fn[i].LessThan`, `response_time_reward_metric_fn[i].scoring_function.lt`

## 해석과 한계

- 5쌍 중 4쌍에서 L1의 일부가 알려진 버그 위치(Clamp 또는 Subtract)와 맞는다. 맞지 않는 1쌍(r-intdiv · 01)의 L1은 `scoring_function`의 TCCT뿐이다.
- 같은 리비전의 W는 후보가 0이었다(J1 결과). 그래서 이 버그 위치를 판정 재료로 가진 쪽은 S+J뿐이다.
- 그 밖의 L1은 이 두 항목과 무관하다.
  - IntDiv는 L-06에서 원인으로 확인된 결함이지만 zkbugs 70항목에는 없다.
  - DistanceFromScore 도달은 수정 커밋 이후 코드에서는 사라지는 문제로 기록돼 있다(L-06).
- L-06에 따르면 Clamp 결함은 IntDiv에 이어진 연쇄 결함이다. 그래서 Clamp 위치의 도달을 Clamp의 독립 원인으로 셀 수는 없다. 원인 귀속(L2)은 이 분석 범위 밖이다.
- 고정 매핑 밖의 대응이므로, 공식 RQ-C 점수나 독립 평가 결과로 쓰지 않는다.

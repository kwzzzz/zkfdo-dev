1번 결과: **문제 있음 — 자동 RQ-C 프로토콜 해시 불일치(별도 래퍼 검증 완료)**. [docs/n6_a_rqc_input_audit_2026-10-26.md](../docs/n6_a_rqc_input_audit_2026-10-26.md)

# B 사람 검토 자료 — N5 개정 4절 3항 (2026-10-26)

담당: miiz·리드. 구성 입력 탐색층 B 1묶음의 공간 중단 시점 중간 결과다. 사람 검토 칸은 판정·서명 없이 비워 두었다.

기준은 `docs/n5_amendment_b_judging_2026-10-17.md:34`, `:70`, `:111`, `:135`다. 집계 근거는 `/private/tmp/n6_b_human_review_counts_20261026.json` (`scope_4_3`, `engines`, 전체 원본 SHA 목록 `input_sources`); 저장된 쌍 관문 `runs/n6-b6h-2026-10-24.noindex/deadline-result-gate-v1.json:2`, 상태 `runs/n6-b6g-2026-10-23.noindex/full-v2.2.noindex/state.json:10` · `runs/n6-b6g-2026-10-23.noindex/full-v1.noindex/state.json:9`와 연결된 결과·공유 판정의 해시를 다시 확인했다.

| 재집계 범위 | 수 | 근거 |
|---|---:|---|
| B의 모든 L1 합집합 | 0요청 / 0클래스 | `/private/tmp/n6_b_human_review_counts_20261026.json` (`scope_4_3`, `engines`, 전체 원본 SHA 목록 `input_sources`); `runs/n6-b6g-2026-10-23.noindex/full-v2.2.noindex/state.json:10` · `runs/n6-b6g-2026-10-23.noindex/full-v1.noindex/state.json:9` |
| 2절 4항 (다): 한 엔진 배제·다른 엔진 L1 | 0요청 | `runs/n6-b6h-2026-10-24.noindex/deadline-result-gate-v1.json:2`; `/private/tmp/n6_b_human_review_counts_20261026.json` (`scope_4_3`, `engines`, 전체 원본 SHA 목록 `input_sources`) |
| v2.2에서만 나온 배제 | 1요청 / 1클래스 | 아래 결과 파일; `/private/tmp/n6_b_human_review_counts_20261026.json` (`scope_4_3`, `engines`, 전체 원본 SHA 목록 `input_sources`) |

- v2.2: 계획 107건 중 완료 결과 27건·준비 실패 17건·미완료 63건, 완료 결과의 클래스 461개. 근거: `runs/n6-b6e-2026-10-20.noindex/request-index-v2.2.json:17`, `runs/n6-b6g-2026-10-23.noindex/full-v2.2.noindex/state.json:10`, `/private/tmp/n6_b_human_review_counts_20261026.json` (`scope_4_3`, `engines`, 전체 원본 SHA 목록 `input_sources`).
- v1: 계획 107건 중 완료 결과 27건·준비 실패 17건·미완료 63건, 완료 결과의 클래스 461개. 근거: `runs/n6-b6e-2026-10-20.noindex/request-index-v1.json:17`, `runs/n6-b6g-2026-10-23.noindex/full-v1.noindex/state.json:9`, `/private/tmp/n6_b_human_review_counts_20261026.json` (`scope_4_3`, `engines`, 전체 원본 SHA 목록 `input_sources`).

보수적 선택: 미완료·준비 실패를 음성 판정으로 세지 않고, 두 엔진의 완료 요청·클래스 대응과 저장된 공유 판정 범위가 정확히 같을 때만 비교했다. 엔진이나 집계 실행기는 재실행하지 않았다. 분류 규칙 근거는 `scripts/n6_b6h_result_gate.py:122`–`:137`이며, 저장된 유효 판정을 재사용했다.

| 항목 | 근거 파일·줄 | 기계 판정 | 독립 확인 결과 | 사람 검토 |
|---|---|---|---|---|
| 모든 L1 | `runs/n6-b6g-2026-10-23.noindex/full-v2.2.noindex/state.json:10` · `runs/n6-b6g-2026-10-23.noindex/full-v1.noindex/state.json:9`; `/private/tmp/n6_b_human_review_counts_20261026.json` (`scope_4_3`, `engines`, 전체 원본 SHA 목록 `input_sources`) | 해당 없음 | 원본 결과·저장된 공유 판정 재집계 일치 | |
| 2절 4항 (다) | `runs/n6-b6h-2026-10-24.noindex/deadline-result-gate-v1.json:2`; `/private/tmp/n6_b_human_review_counts_20261026.json` (`scope_4_3`, `engines`, 전체 원본 SHA 목록 `input_sources`) | 해당 없음 | 원본 재집계와 저장된 관문 일치 | |
| 리비전 `4c221df76273c0d7cf18048c` · 요청 25 · 클래스 6 | `runs/n6-b6g-2026-10-23.noindex/full-v2.2.noindex/main/0004/requests/000025/attempt-0001/result.json:402`; `runs/n6-b6g-2026-10-23.noindex/full-v1.noindex/main/0004/requests/000025/attempt-0001/result.json:390`; `docs/n6_b6h_review_v22_only_exclusion_2026-10-25.md:9` | v2.2 `excluded_in_context` (`closed_cone_unsat`); v1 `unknown` (`budget_exhausted`) | 미실행(z3 없음) · `/private/tmp/n6_b_cone_independent_check_20261026.json` | |

현재 독립 확인: `미실행(z3 없음)`, 원뿔 파일 존재 `False`, 부모 경로 존재 `False`. 명시 경로는 `/Volumes/zkfdo-jcache/n6-b6g-batch1x/hint-workspaces/full-v2.2.noindex/main/0004/requests/000025/attempt-0001/raw/site-006/synthesis/cone.smt2`이며 근거는 `/private/tmp/n6_b_cone_independent_check_20261026.json`다. 독립 솔버: 미실행; 시간 —.

기존 독립 z3 재실행 완료 기록은 docs의 `n6_b*`·`n6_light*`·`n5*` 문서 검색에서 찾지 못했다. 이는 해당 문서 범위의 확인이며 다른 위치의 기록 존재까지 부정하지 않는다.

독립 확인 범위: 기존 검토 문서 `docs/n6_b6h_review_v22_only_exclusion_2026-10-25.md:19`의 62제약·69미지 원뿔, `:21`의 고정 사이트 신호 4개다. `:23`은 원래 SMT2 삭제를 기록한다. 이번 확인은 남은 명시 경로와 설치된 Python z3만 대상으로 하며, J 재실행·재컴파일·설치를 하지 않았다. 값은 출력하지 않았다.

다시 실행(저장소 루트):

```sh
nice -n 19 python3 -B scripts/n6_b_cone_independent_check_20261026.py --output /private/tmp/n6_b_cone_independent_check_20261026.json
nice -n 19 python3 -B scripts/n6_b_human_review_counts_20261026.py \
  --gate runs/n6-b6h-2026-10-24.noindex/deadline-result-gate-v1.json \
  --v1-index runs/n6-b6e-2026-10-20.noindex/request-index-v1.json \
  --v22-index runs/n6-b6e-2026-10-20.noindex/request-index-v2.2.json \
  --v1-state runs/n6-b6g-2026-10-23.noindex/full-v1.noindex/state.json \
  --v22-state runs/n6-b6g-2026-10-23.noindex/full-v2.2.noindex/state.json \
  --independent-check /private/tmp/n6_b_cone_independent_check_20261026.json \
  --output /private/tmp/n6_b_human_review_counts_20261026.json \
  --report docs/n6_b_human_review_4_3_2026-10-26.md
```

새 파일 SHA-256(이 보고서 자체 해시는 최종 전달문에서 별도 제시):

| 파일 | SHA-256 |
|---|---|
| `scripts/n6_b_human_review_counts_20261026.py` | `8d187feaa2bb5a333ad2f17a22cbe67ed76602ce20b341065f7077182b8304e7` |
| `scripts/n6_b_cone_independent_check_20261026.py` | `8fd41cb48c7393f63c995b9e614d33347340900d8649601ed045984ca6a6a91a` |
| `/private/tmp/n6_b_human_review_counts_20261026.json` | `8a7d85f06d256e8a93cb3e56b0e399a14b659e1b63f1a69347bcb072be498f84` |
| `/private/tmp/n6_b_cone_independent_check_20261026.json` | `5c33f935c6a79e05b268c5fd703e28a53cc7f2aea7d4b4f61174d649a2525711` |

**확인한 것**: 위 범위의 기계 판정과 경로·SHA 연결을 기존 결과로 다시 확인했다. 후보·witness 파일, 실행 중 aq, 전환 스크립트와 B 원본은 수정하지 않았다.

**추정한 것**: 독립 풀이가 실행되지 않았으므로 저장된 UNSAT을 독립 확인으로 대체하지 않았다. 원뿔의 원래 O1 적용과 실제 배포 공격 가능성은 사람 검토에 남긴다. 미완료 요청에 대한 결과는 추정하지 않았다.

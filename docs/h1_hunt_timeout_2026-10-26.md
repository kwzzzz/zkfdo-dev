# H1 사냥 퍼징 결과와 timeout 표 (2026-10-26)

탐색 사냥(N5 목록 밖)이다. 후보 내용은 열지 않았고, ledger의 결과 수만 셌다. 퍼징은 2026-10-25 22:42에 시작해 10-26 02:43 KST에 끝났다(15/15 단위 완료).

- **결과:** 15단위 모두에서 후보는 **0**건이다.
- **timeout의 뜻:** 시도 상한까지 탐색했지만 후보가 없었다는 뜻이다. 버린 결과가 아니다.
- **시도 상한:** S는 30초, W는 1,800초(시도 하나로 예산 전체를 쓴다). 단위당 총 예산은 1,800초다.
- **출처:** 원자료는 `runs/h1-hunt-2026-10-25.noindex/report/timeout-by-target.tsv`(SHA-256 `93f3396c872854b43baa19655ba4d24b9625fba9b8c7466c3ddac56aababa26e`)이고, 단위·하위 단위별 시도·timeout·후보 없음·후보 수를 담았다.

## 단위별

| 단위 | 방식 | 시도 | 후보 없음 | timeout | 후보 | 하위 단위 시도 범위 |
|---|---|---:|---:|---:|---:|---|
| moros-batch seed 01 / 02 | S | 116 / 117 | 110 / 111 | 6 / 6 | 0 | 72/72 |
| moros-exit-match seed 01 / 02 | S | 112 / 112 | 102 / 102 | 10 / 10 | 0 | 76/76 |
| moros-transfer-four seed 01 / 02 | S | 112 / 118 | 102 / 107 | 10 / 11 | 0 | 77/77 |
| edec-blob-poseidon-2 seed 01 / 02 | S | 69 / 70 | 13 / 14 | 56 / 56 | 0 | 대부분 시도, 일부 예산 소진 |
| edec-blob-poseidon seed 01 / 02 | S | 70 / 70 | 14 / 14 | 56 / 56 | 0 | 70/74 (4개 예산 소진) |
| moros 3개 main, EthStorage 2개 main | W | 각 1 | 0 | 각 1 | 0 | 전체 회로 |

## timeout이 몰린 하위 단위 (템플릿 기준, seed 합계)

| 대상 | 템플릿 | timeout / 시도 | 시도 상한 |
|---|---|---:|---:|
| edec-blob-poseidon | MixS | 112 / 112 | 30초 |
| edec-blob-poseidon-2 | MixS | 111 / 111 | 30초 |
| moros-transfer-four | Poseidon2Sponge | 18 / 18 | 30초 |
| moros-exit-match | Poseidon2Sponge | 16 / 16 | 30초 |
| moros-batch | Poseidon2Sponge | 8 / 8 | 30초 |
| moros 3개 | Permutation | 각 2 / 2 | 30초 |
| moros-batch / exit-match / transfer-four | InternalRound | 2/197, 2/182, 1/95 | 30초 |
| edec-blob-poseidon-2 | Ark | 1 / 8 | 30초 |

## 해석

- EthStorage의 S 예산은 대부분 Poseidon 내부 `MixS` 인스턴스(약 110개)에서 30초씩 timeout으로 쓰였다. 예산 소진으로 4개 하위 단위는 시작하지 못했다.
- moros는 모든 하위 단위를 한 번 이상 시도했다. timeout은 Poseidon2 해시 계열(Poseidon2Sponge·Permutation)에만 몰렸다.
- 재실행 여부는 aq 판정이 끝난 뒤 miiz가 정한다. 다음 두 방향은 그때 판단할 근거다.
  - 해시 계열 하위 단위의 시도 상한을 늘리는 것
  - 해시 하위 단위를 빼고 응용 로직 하위 단위에 예산을 주는 것

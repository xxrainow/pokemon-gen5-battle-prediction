# 첫 경기의 타입 구성 계산 예시

경기 ID: `gen5ubers-2293926818` / 포맷: `gen5ubers`

전체 경기 적용 전, 기본 데이터의 첫 경기 한 판만 계산했다. 타입별 팀원 수 17개 × (A팀·B팀·두 팀 차이) = 51개다. 관리 정보·정답 5개를 함께 저장해 결과표는 1행 × 56열이다.

## 실제 입력 팀

| 팀 | 슬롯 | 포켓몬 | 타입 1 | 타입 2 |
|---|---|---|---|---|
| p1 | 1 | hooh | Fire | Flying |
| p1 | 2 | umbreon | Dark | 없음 |
| p1 | 3 | entei | Fire | 없음 |
| p1 | 4 | regirock | Rock | 없음 |
| p1 | 5 | shiftry | Grass | Dark |
| p1 | 6 | alakazam | Psychic | 없음 |
| p2 | 1 | castform | Normal | 없음 |
| p2 | 2 | vaporeon | Water | 없음 |
| p2 | 3 | blastoise | Water | 없음 |
| p2 | 4 | magneton | Electric | Steel |
| p2 | 5 | charizard | Fire | Flying |
| p2 | 6 | giratina | Ghost | Dragon |

## 계산한 팀원 수

| 타입 | A팀(p1) | B팀(p2) | A − B |
|---|---|---|---|
| Normal | 0 | 1 | -1 |
| Fire | 2 | 1 | 1 |
| Water | 0 | 2 | -2 |
| Electric | 0 | 1 | -1 |
| Grass | 1 | 0 | 1 |
| Ice | 0 | 0 | 0 |
| Fighting | 0 | 0 | 0 |
| Poison | 0 | 0 | 0 |
| Ground | 0 | 0 | 0 |
| Flying | 1 | 1 | 0 |
| Psychic | 1 | 0 | 1 |
| Bug | 0 | 0 | 0 |
| Rock | 1 | 0 | 1 |
| Ghost | 0 | 1 | -1 |
| Dragon | 0 | 1 | -1 |
| Dark | 2 | 0 | 2 |
| Steel | 0 | 1 | -1 |

## 세는 방법

불꽃/비행 포켓몬 한 마리는 불꽃에 1, 비행에 1을 더한다. 단일 타입 포켓몬은 한 번만 센다. 복수 타입 때문에 타입 수의 합은 6보다 클 수 있다.

이 경기의 타입 수 합계는 A팀 8, B팀 9다. 팀원은 각각 6마리다.

## 파일과 범위

- [결과 CSV](../data/type_sample.csv) / [결과 Parquet](../data/type_sample.parquet)
- [51개 피처의 정의](type_definitions.json)
- [검증 결과](type_checks.json)

5세대의 17개 타입만 사용한다. 이 수는 팀의 타입 구성이며 공격 기술·방어 상성·승률은 아니다. 기존 능력치 피처와 결합하거나 전체 경기에 적용하지 않았다. winner와 y는 결과표에 보존하지만 피처 계산에는 사용하지 않는다.

## 검사

- independent_type_counts: passed
- dual_type_totals: passed
- count_and_difference_ranges: passed
- single_type_null_and_empty_handling: passed
- slot_order_invariance: passed
- team_swap_sign_check: passed
- metadata_and_target_not_used: passed
- parquet_and_csv_roundtrip: passed
- source_file_unchanged: passed

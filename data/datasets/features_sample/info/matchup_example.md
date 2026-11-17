# 첫 경기의 방어 상성 계산 예시

경기 ID: `gen5ubers-2293926818` / 포맷: `gen5ubers`

기본 데이터의 첫 경기 한 판만 계산했다. 공격 타입 17개 × (약점·저항·무효) × (A팀·B팀·차이) = 153개 피처다. 관리 정보·정답 5개를 함께 저장해 결과표는 1행 × 158열이다. 특성·아이템 효과는 제외했다.

## 계산 순서

1. 각 포켓몬의 타입을 읽는다.
2. `gen5_typechart.csv`에서 공격 타입(행) × 방어 타입(열)의 배율을 찾는다. 복수 타입이면 두 값을 곱한다.
3. **곱한 뒤의 최종 배율**로 분류한다: 2·4배 = 약점, 0.5·0.25배 = 저항, 0배 = 무효, 1배 = 어느 쪽에도 세지 않음.
4. 팀별로 분류마다 포켓몬 수를 세고, 차이는 A팀 − B팀이다.

상성표 SHA-256: `8a53c8287b0fe05ca1e454640dd2ae50a78a4853feab2e54f086ee212dcba6c9`

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

## 예: 바위 공격을 받을 때

| 팀 | 포켓몬 | 타입 | 타입 1 배율 | 타입 2 배율 | 최종 배율 | 분류 |
|---|---|---|---|---|---|---|
| p1 | hooh | Fire/Flying | 2 | 2 | **4** | 약점 |
| p1 | umbreon | Dark | 1 | — | **1** | 보통 |
| p1 | entei | Fire | 2 | — | **2** | 약점 |
| p1 | regirock | Rock | 1 | — | **1** | 보통 |
| p1 | shiftry | Grass/Dark | 1 | 1 | **1** | 보통 |
| p1 | alakazam | Psychic | 1 | — | **1** | 보통 |
| p2 | castform | Normal | 1 | — | **1** | 보통 |
| p2 | vaporeon | Water | 1 | — | **1** | 보통 |
| p2 | blastoise | Water | 1 | — | **1** | 보통 |
| p2 | magneton | Electric/Steel | 1 | 0.5 | **0.5** | 저항 |
| p2 | charizard | Fire/Flying | 2 | 2 | **4** | 약점 |
| p2 | giratina | Ghost/Dragon | 1 | 1 | **1** | 보통 |

약점 A 2·B 1·차이 +1 / 저항 A 0·B 1·차이 -1 / 무효 A 0·B 0·차이 +0

## 두 배율이 상쇄되어 1배가 된 경우

한 타입은 약점, 다른 타입은 저항이라 최종 1배가 되어 어느 쪽에도 세지 않은 경우다.

| 팀 | 포켓몬 | 공격 타입 | 계산 |
|---|---|---|---|
| p1 | hooh | Ice | 0.5 × 2 = 1 |
| p2 | charizard | Ice | 0.5 × 2 = 1 |

4배·0.25배(두 타입 모두 같은 방향)는 각각 약점·저항으로 한 번만 센다. 이 경기에서 4배 4건, 0.25배 6건이다. 한 타입이라도 0배면 최종 0배(무효)다.

## 포켓몬별 최종 배율 (행: 포켓몬, 열: 공격 타입)

| 팀 | 포켓몬 | Nor | Fir | Wat | Ele | Gra | Ice | Fig | Poi | Gro | Fly | Psy | Bug | Roc | Gho | Dra | Dar | Ste |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| p1 | hooh | 1 | 0.5 | 2 | 2 | 0.25 | 1 | 0.5 | 1 | 0 | 1 | 1 | 0.25 | 4 | 1 | 1 | 1 | 0.5 |
| p1 | umbreon | 1 | 1 | 1 | 1 | 1 | 1 | 2 | 1 | 1 | 1 | 0 | 2 | 1 | 0.5 | 1 | 0.5 | 1 |
| p1 | entei | 1 | 0.5 | 2 | 1 | 0.5 | 0.5 | 1 | 1 | 2 | 1 | 1 | 0.5 | 2 | 1 | 1 | 1 | 0.5 |
| p1 | regirock | 0.5 | 0.5 | 2 | 1 | 2 | 1 | 2 | 0.5 | 2 | 0.5 | 1 | 1 | 1 | 1 | 1 | 1 | 2 |
| p1 | shiftry | 1 | 2 | 0.5 | 0.5 | 0.5 | 2 | 2 | 2 | 0.5 | 2 | 0 | 4 | 1 | 0.5 | 1 | 0.5 | 1 |
| p1 | alakazam | 1 | 1 | 1 | 1 | 1 | 1 | 0.5 | 1 | 1 | 1 | 0.5 | 2 | 1 | 2 | 1 | 2 | 1 |
| p2 | castform | 1 | 1 | 1 | 1 | 1 | 1 | 2 | 1 | 1 | 1 | 1 | 1 | 1 | 0 | 1 | 1 | 1 |
| p2 | vaporeon | 1 | 0.5 | 0.5 | 2 | 2 | 0.5 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0.5 |
| p2 | blastoise | 1 | 0.5 | 0.5 | 2 | 2 | 0.5 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 1 | 0.5 |
| p2 | magneton | 0.5 | 2 | 1 | 0.5 | 0.5 | 0.5 | 2 | 0 | 4 | 0.25 | 0.5 | 0.5 | 0.5 | 0.5 | 0.5 | 0.5 | 0.25 |
| p2 | charizard | 1 | 0.5 | 2 | 2 | 0.25 | 1 | 0.5 | 1 | 0 | 1 | 1 | 0.25 | 4 | 1 | 1 | 1 | 0.5 |
| p2 | giratina | 0 | 0.5 | 0.5 | 0.5 | 0.5 | 2 | 0 | 0.5 | 1 | 1 | 1 | 0.5 | 1 | 2 | 2 | 2 | 1 |

열 이름은 공격 타입의 앞 세 글자다. 2 이상은 약점, 1 미만·0 초과는 저항, 0은 무효다.

## 집계 결과 153개

| 공격 타입 | A 약점 | A 저항 | A 무효 | B 약점 | B 저항 | B 무효 | 차이 약점 | 차이 저항 | 차이 무효 |
|---|---|---|---|---|---|---|---|---|---|
| Normal | 0 | 1 | 0 | 0 | 1 | 1 | +0 | +0 | -1 |
| Fire | 1 | 3 | 0 | 1 | 4 | 0 | +0 | -1 | +0 |
| Water | 3 | 1 | 0 | 1 | 3 | 0 | +2 | -2 | +0 |
| Electric | 1 | 1 | 0 | 3 | 2 | 0 | -2 | -1 | +0 |
| Grass | 1 | 3 | 0 | 2 | 3 | 0 | -1 | +0 | +0 |
| Ice | 1 | 1 | 0 | 1 | 3 | 0 | +0 | -2 | +0 |
| Fighting | 3 | 2 | 0 | 2 | 1 | 1 | +1 | +1 | -1 |
| Poison | 1 | 1 | 0 | 0 | 1 | 1 | +1 | +0 | -1 |
| Ground | 2 | 1 | 1 | 1 | 0 | 1 | +1 | +1 | +0 |
| Flying | 1 | 1 | 0 | 0 | 1 | 0 | +1 | +0 | +0 |
| Psychic | 0 | 1 | 2 | 0 | 1 | 0 | +0 | +0 | +2 |
| Bug | 3 | 2 | 0 | 0 | 3 | 0 | +3 | -1 | +0 |
| Rock | 2 | 0 | 0 | 1 | 1 | 0 | +1 | -1 | +0 |
| Ghost | 1 | 2 | 0 | 1 | 1 | 1 | +0 | +1 | -1 |
| Dragon | 0 | 0 | 0 | 1 | 1 | 0 | -1 | -1 | +0 |
| Dark | 1 | 2 | 0 | 1 | 1 | 0 | +0 | +1 | +0 |
| Steel | 1 | 2 | 0 | 0 | 4 | 0 | +1 | -2 | +0 |

## 파일과 범위

- [결과 CSV](../data/matchup_sample.csv) / [결과 Parquet](../data/matchup_sample.parquet)
- [153개 피처의 정의](matchup_definitions.json)
- [포켓몬 × 공격 타입 204건의 배율 상세](matchup_members.json)
- [검증 결과](matchup_checks.json)

타입 상성만 사용한다. 특성(예: 부유)·아이템(예: 풍선)·기술 고유 효과·날씨는 반영하지 않으며 실제 피해량·공격 기술 범위도 아니다. 기존 피처와 결합하거나 전체 경기에 적용하지 않았다. winner와 y는 결과표에 보존하지만 계산에는 사용하지 않는다.

## 검사

- chart_sha256_matches_info: passed
- chart_examples_and_multiply_before_classify: passed
- all_type_combinations_independent_classification: passed
- independent_team_counts: passed
- count_and_difference_ranges: passed
- slot_order_invariance: passed
- team_swap_sign_check: passed
- single_type_null_and_empty_handling: passed
- metadata_and_target_not_used: passed
- parquet_and_csv_roundtrip: passed
- source_file_unchanged: passed

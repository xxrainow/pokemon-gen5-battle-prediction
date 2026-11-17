# 조합 피처 정의

분할 후 사용할 입력 컬럼과 종·타입·포맷의 변환 규칙은 [모델 입력과 인코딩 정의](../encoding/encoding_spec.md)에 정리한다. 이 문서의 피처 계산과 인코딩은 별도 단계다.

## 1. 이번에 계산하는 능력치 요약

입력은 기본 표에 있는 각 팀 6마리의 HP·공격·방어·특수공격·특수방어·스피드 종족값이다. 기술·아이템·특성·레이팅·승패 정답은 피처 계산에 사용하지 않는다.

한 능력치의 팀원 6개 값을 `x1, …, x6`라고 할 때 다음 세 가지를 계산한다.

| 이름 규칙 | 계산식 | 의미 |
|---|---|---|
| `p1_{stat}_mean`, `p2_{stat}_mean` | `(x1 + … + x6) / 6` | 해당 능력치의 팀 평균 |
| `p1_{stat}_max`, `p2_{stat}_max` | `max(x1, …, x6)` | 해당 능력치가 가장 높은 팀원의 값 |
| `p1_{stat}_std`, `p2_{stat}_std` | `sqrt(sum((xi − mean)²) / 6)` | 능력치가 일부 팀원에 몰려 있는 정도 |
| `diff_{stat}_{summary}` | `p1_{stat}_{summary} − p2_{stat}_{summary}` | 두 팀 요약값의 상대적인 차이 |

`stat`은 `hp`, `atk`, `def`, `spa`, `spd`, `spe`이고, `summary`는 `mean`, `max`, `std`다. 한 팀 18개, 양 팀 36개, 차이 18개로 **총 54개 피처**다. 표준편차는 팀 전체 6마리를 대상으로 하는 모집단 표준편차(`ddof=0`)로 정한다. 합계는 평균의 6배여서 이번에는 따로 추가하지 않는다.

예를 들어 `p1_spe_mean`은 A팀 평균 스피드 종족값, `diff_atk_max`는 양 팀의 최대 공격 종족값 차이다. 표준편차가 높다고 반드시 유리한 것은 아니며, 차이 피처도 원래 두 팀 요약값에서 유도된 정보다.

슬롯 순서를 바꿔도 결과가 같아야 한다. A와 B를 바꾸면 팀별 피처가 서로 바뀌고 차이 피처의 부호가 반대가 되어야 한다. 메타데이터·정답을 바꿔도 피처 값은 변하지 않아야 한다.

## 2. 타입 구성과 다음 후보

타입 구성은 5세대의 17개 타입별로 해당 타입을 가진 팀원을 센다. 단일 타입은 한 번, 복수 타입은 각각의 타입에 한 번씩 집계한다. 따라서 한 팀의 타입 수 합계는 6~12가 될 수 있다. 같은 포켓몬 종이라도 서로 다른 슬롯이면 각 팀원으로 센다.

- `p1_type_{type}_count`, `p2_type_{type}_count`: 팀별 해당 타입을 가진 팀원 수(0~6)
- `diff_type_{type}_count`: A팀 수 − B팀 수(−6~6)
- 예: `p1_type_fire_count`, `diff_type_water_count`

17개 타입 × (A팀·B팀·차이) = **51개 피처**다. 첫 경기 샘플은 관리 정보·정답 5개를 함께 저장해 1행 × 56열이다. 같은 정의를 전체 경기에도 적용했다. 두 번째 타입이 비어 있거나 null인 경우는 단일 타입으로 처리한다. 첫 번째 타입 누락, 5세대 외 타입, 같은 타입의 중복 입력은 오류로 처리한다.

| 묶음 | 후보 정의 | 상태 |
|---|---|---|
| 타입 구성 | 17개 타입별 팀원 수. 복수 타입은 각 타입에 한 번씩 집계 | 샘플 검증 및 전체 822,419경기 적용 완료 |
| 방어 상성 | 공격 타입별로 타입 배율이 2 이상인 팀원 수, 0 초과 1 미만인 팀원 수, 0인 팀원 수 | 샘플 검증 및 전체 822,419경기 적용 완료 |
| 양 팀 차이 | 각 팀의 동일 피처를 A − B로 비교 | 능력치·타입 구성·방어 상성 전체 데이터에 포함 |

평균 스피드가 높다고 실제로 먼저 행동한다고 단정하지 않는다. 타입 구성은 방어 상성이나 공격 기술 범위를 의미하지 않는다. 방어 상성도 특성·아이템 효과는 제외하며 실제 피해량은 계산하지 않는다. 능력치 54개, 타입 구성 51개, 방어 상성 153개는 모두 전체 경기에 적용했다.

## 3. 파일 구성

- `preprocessing/features/build_stat_sample.py`: 기본 표 첫 경기에서 능력치 피처 54개를 계산하고 검증하는 코드
- `data/datasets/features_sample/data/stat_sample.parquet`, `data/datasets/features_sample/data/stat_sample.csv`: 첫 경기의 피처와 관리 정보·정답. 1행 × 59열
- `data/datasets/features_sample/info/stat_definitions.json`: 실제 54개 피처 이름과 계산식
- `data/datasets/features_sample/info/example.md`: 입력 팀원과 결과를 사람이 읽기 좋게 펼친 예시
- `data/datasets/features_sample/info/checks.json`: 별도 계산·슬롯 순서·팀 교환·저장값 검사 결과
- `preprocessing/features/build_type_sample.py`: 같은 첫 경기에서 타입 구성 피처 51개 계산·검증
- `data/datasets/features_sample/data/type_sample.csv`, `type_sample.parquet`: 타입 구성 결과표
- `data/datasets/features_sample/info/type_definitions.json`: 실제 51개 타입 피처 정의
- `data/datasets/features_sample/info/type_example.md`: 입력 포켓몬 타입과 실제 집계 설명
- `data/datasets/features_sample/info/type_checks.json`: 타입 구성 샘플 검사 결과

샘플의 관리 정보·정답은 `battle_id`, `formatid`, `uploadtime`, `winner`, `y`다. `winner`와 `y`를 모델 입력으로 사용하지 않는다. 기본 데이터 표는 수정하지 않는다.

## 4. 전체 경기 적용

- `preprocessing/features/build_stat_features.py`: 기본 데이터 전체에 능력치 피처 54개 추가
- `data/datasets/stat_features/data/`: `all_stat_features.parquet`, `all_stat_features.csv`
- `data/datasets/stat_features/info/`: 데이터 설명, 입력 목록, 검증 결과. 피처 정의는 샘플의 `features_sample/info/stat_definitions.json`을 참조

전체 결과는 822,419행 × 167열이다. 기존 113열의 값·순서는 그대로 두고 새 54열을 뒤에 붙인다. 입력 후보는 기본 108개 + 새 54개 = 162개이며, 관리 정보 4개와 정답 1개는 별도로 구분한다. 샘플과 전체 계산은 `build_stat_sample.py`의 피처 정의를 공유한다.

모든 경기에서 기존 컬럼 보존, 새 피처의 결측·무한값 없음, CSV·Parquet 저장값 일치를 확인한다. 첫·마지막 경기와 고정 난수 표본은 별도 계산과 대조하고 슬롯 순서·팀 교환·관리 정보 및 정답 변경도 검사한다. 세부 결과는 `stat_features/info/quality_report.json`에 저장한다. 이 단계에서는 데이터 분할과 모델 학습·평가는 하지 않는다.

### 타입 구성 추가

- `preprocessing/features/build_type_features.py`: 능력치 데이터 전체에 타입 구성 51개 추가
- `data/datasets/stat_type_features/data/`: `all_stat_type_features.parquet`, `all_stat_type_features.csv`
- `data/datasets/stat_type_features/info/`: 설명, 입력 목록, 검증 결과. 타입 정의는 샘플의 `type_definitions.json`을 참조

결과는 822,419행 × 218열이다. 기존 167열의 값·순서를 유지하고 타입 구성 51열을 뒤에 붙였다. 입력 후보는 기본 108개 + 능력치 54개 + 타입 구성 51개 = 213개이며 관리 정보 4개와 정답 1개는 제외한다. `columns.json`에서 각 입력 묶음을 별도로 고를 수 있다.

모든 경기에서 기존 값 보존, 타입 수·차이의 범위, 단일·복수 타입 합계, CSV·Parquet 저장값 일치를 확인한다. 고정 표본은 샘플 코드의 독립 집계와 대조하고 슬롯 순서·팀 교환·정답 독립성도 검사한다. 기존 데이터셋과 피처 정의 파일은 수정하지 않는다.

## 5. 방어 상성 계산 전의 참조 표

- `initial_preparation/code/export_gen5_typechart.cjs`: 공식 Showdown 로더의 `Dex.mod('gen5')`로 생성
- `data/external/gen5_typechart.csv`: 행은 공격 타입, 열은 방어 측 단일 타입인 17 × 17 배율 표
- `data/external/gen5_typechart_info.json`: 패키지 버전·무결성·상속 경로·로더 해시·검증 결과

무효는 `getImmunity`로 먼저 확인하고, 그 외에는 `2 ** getEffectiveness`로 배율을 얻는다. 복수 타입은 두 배율을 곱한다. 특성·아이템·기술 고유 효과·경기 상태는 제외한다. 바위 → 불꽃/비행은 4배이며, 5세대에서는 강철이 고스트·악을 각각 0.5배로 받는다.

모든 단일 타입 289개와 공격 타입별 단일·복수 방어 조합 2,601개를 공식 로더와 대조했다. 참조 표를 이용한 방어 상성 샘플은 6절에 정리한다.

## 6. 방어 상성 샘플

공격 타입 `a`마다 각 팀원이 받는 최종 배율 `m = chart[a][type1] × chart[a][type2]`를 구한다. 단일 타입이면 `chart[a][type1]`만 쓴다. **곱한 뒤에** 분류한다.

| 최종 배율 | 분류 | 피처 |
|---|---|---|
| 2, 4 | 약점 | `{side}_def_{attack}_weak_count` |
| 0.5, 0.25 | 저항 | `{side}_def_{attack}_resist_count` |
| 0 | 무효 | `{side}_def_{attack}_immune_count` |
| 1 | 세지 않음 | — |

`side`는 `p1`, `p2`, `diff`(A − B)이고 `attack`은 17개 공격 타입의 소문자 영어 이름이다. 예: `p1_def_rock_weak_count`, `diff_def_ground_immune_count`. 팀별 값은 0~6, 차이는 −6~6이며 한 공격 타입에서 약점·저항·무효 수의 합은 6 이하다. 17 × 3 × 3 = **153개 피처**다.

- `preprocessing/features/build_matchup_sample.py`: 첫 경기에서 153개 계산·검증
- `data/datasets/features_sample/data/matchup_sample.csv`, `matchup_sample.parquet`: 관리 정보·정답 포함 1행 × 158열
- `data/datasets/features_sample/info/matchup_definitions.json`: 153개 피처 이름·계산식
- `data/datasets/features_sample/info/matchup_members.json`: 12마리 × 17개 공격 타입 = 204건의 타입별 배율·최종 배율·분류
- `data/datasets/features_sample/info/matchup_example.md`: 바위 공격 예시, 상쇄 사례, 포켓몬별 배율표, 집계표
- `data/datasets/features_sample/info/matchup_checks.json`: 검증 결과

상성표 SHA-256을 `gen5_typechart_info.json`과 대조하고, 곱셈 대신 무효 여부와 log2 지수 합으로 분류하는 별도 계산을 모든 단일·복수 타입 조합과 샘플 팀원에 대조한다. 슬롯 순서·팀 교환·단일 타입 null/빈 문자열·관리 정보 및 정답 독립성·저장값 일치도 검사한다. 특성(부유 등)·아이템(풍선 등)·기술 고유 효과·날씨는 제외한다.

### 방어 상성 전체 적용

- `preprocessing/features/build_matchup_features.py`: 능력치·타입 구성 데이터 전체에 방어 상성 153개 추가
- `data/datasets/stat_type_matchup_features/data/`: `all_stat_type_matchup_features.parquet`, `all_stat_type_matchup_features.csv`
- `data/datasets/stat_type_matchup_features/info/`: 설명, 입력 목록, 검증 결과·공격 타입별 평균 수. 정의는 샘플의 `matchup_definitions.json`을 참조

결과는 822,419행 × 371열이다. 기존 218열의 값·순서를 유지하고 방어 상성 153열을 뒤에 붙였다. 입력 후보는 기본 108개 + 능력치 54개 + 타입 구성 51개 + 방어 상성 153개 = 366개이며 관리 정보 4개와 정답 1개는 제외한다. 전체 계산은 (첫 타입, 두 번째 타입) 조합별 분류를 미리 만든 표로 찾되, 그 표도 샘플 코드의 `classify`(곱한 뒤 분류)로 만든다.

모든 경기에서 범위·차이·분류 합계와 저장값 일치를 확인하고, 무효 수를 해당 무효 타입의 타입 구성 수와 대조한다(노말·격투 → 고스트, 고스트 → 노말, 전기 → 땅, 땅 → 비행, 독 → 강철, 에스퍼 → 악; 그 외 공격 타입은 항상 0). 고정 표본 102경기는 샘플 코드의 행 단위 계산·독립 분류와 대조하고 슬롯 순서·팀 교환·정답 독립성도 검사한다. 기존 데이터셋과 피처 정의 파일은 수정하지 않는다.

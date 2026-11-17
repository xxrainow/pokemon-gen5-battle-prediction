# 조합 피처 정의

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
| 방어 상성 | 공격 타입별로 타입 배율이 2 이상인 팀원 수, 0 초과 1 미만인 팀원 수, 0인 팀원 수 | 5세대 상성표 준비 후 계산 |
| 양 팀 차이 | 각 팀의 동일 피처를 A − B로 비교 | 능력치·타입 구성 전체 데이터에 포함, 방어 상성은 구현 전 |

평균 스피드가 높다고 실제로 먼저 행동한다고 단정하지 않는다. 타입 구성은 방어 상성이나 공격 기술 범위를 의미하지 않는다. 방어 상성을 추가할 때도 특성·아이템 효과는 제외하며 실제 피해량은 계산하지 않는다. 능력치 54개와 타입 구성 51개는 모두 전체 경기에 적용했다.

## 3. 파일 구성

- `preprocessing/build_stat_sample.py`: 기본 표 첫 경기에서 능력치 피처 54개를 계산하고 검증하는 코드
- `data/datasets/features_sample/data/stat_sample.parquet`, `data/datasets/features_sample/data/stat_sample.csv`: 첫 경기의 피처와 관리 정보·정답. 1행 × 59열
- `data/datasets/features_sample/info/stat_definitions.json`: 실제 54개 피처 이름과 계산식
- `data/datasets/features_sample/info/example.md`: 입력 팀원과 결과를 사람이 읽기 좋게 펼친 예시
- `data/datasets/features_sample/info/checks.json`: 별도 계산·슬롯 순서·팀 교환·저장값 검사 결과
- `preprocessing/build_type_sample.py`: 같은 첫 경기에서 타입 구성 피처 51개 계산·검증
- `data/datasets/features_sample/data/type_sample.csv`, `type_sample.parquet`: 타입 구성 결과표
- `data/datasets/features_sample/info/type_definitions.json`: 실제 51개 타입 피처 정의
- `data/datasets/features_sample/info/type_example.md`: 입력 포켓몬 타입과 실제 집계 설명
- `data/datasets/features_sample/info/type_checks.json`: 타입 구성 샘플 검사 결과

샘플의 관리 정보·정답은 `battle_id`, `formatid`, `uploadtime`, `winner`, `y`다. `winner`와 `y`를 모델 입력으로 사용하지 않는다. 기본 데이터 표는 수정하지 않는다.

## 4. 전체 경기 적용

- `preprocessing/build_stat_features.py`: 기본 데이터 전체에 능력치 피처 54개 추가
- `data/datasets/stat_features/data/`: `all_stat_features.parquet`, `all_stat_features.csv`
- `data/datasets/stat_features/info/`: 데이터 설명, 입력 목록, 검증 결과. 피처 정의는 샘플의 `features_sample/info/stat_definitions.json`을 참조

전체 결과는 822,419행 × 167열이다. 기존 113열의 값·순서는 그대로 두고 새 54열을 뒤에 붙인다. 입력 후보는 기본 108개 + 새 54개 = 162개이며, 관리 정보 4개와 정답 1개는 별도로 구분한다. 샘플과 전체 계산은 `build_stat_sample.py`의 피처 정의를 공유한다.

모든 경기에서 기존 컬럼 보존, 새 피처의 결측·무한값 없음, CSV·Parquet 저장값 일치를 확인한다. 첫·마지막 경기와 고정 난수 표본은 별도 계산과 대조하고 슬롯 순서·팀 교환·관리 정보 및 정답 변경도 검사한다. 세부 결과는 `stat_features/info/quality_report.json`에 저장한다. 이 단계에서는 데이터 분할과 모델 학습·평가는 하지 않는다.

### 타입 구성 추가

- `preprocessing/build_type_features.py`: 능력치 데이터 전체에 타입 구성 51개 추가
- `data/datasets/stat_type_features/data/`: `all_stat_type_features.parquet`, `all_stat_type_features.csv`
- `data/datasets/stat_type_features/info/`: 설명, 입력 목록, 검증 결과. 타입 정의는 샘플의 `type_definitions.json`을 참조

결과는 822,419행 × 218열이다. 기존 167열의 값·순서를 유지하고 타입 구성 51열을 뒤에 붙였다. 입력 후보는 기본 108개 + 능력치 54개 + 타입 구성 51개 = 213개이며 관리 정보 4개와 정답 1개는 제외한다. `columns.json`에서 각 입력 묶음을 별도로 고를 수 있다.

모든 경기에서 기존 값 보존, 타입 수·차이의 범위, 단일·복수 타입 합계, CSV·Parquet 저장값 일치를 확인한다. 고정 표본은 샘플 코드의 독립 집계와 대조하고 슬롯 순서·팀 교환·정답 독립성도 검사한다. 기존 데이터셋과 피처 정의 파일은 수정하지 않는다.

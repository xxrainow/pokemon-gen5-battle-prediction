# pokemon-gen5-battle-prediction

포켓몬 쇼다운의 공개 경기 기록을 활용해, **경기 시작 전 양 팀의 구성으로 5세대 포켓몬 배틀의 승패를 예측하는 ML 프로젝트**입니다.

## 프로젝트 목표

각 팀의 포켓몬 종, 종족값, 타입과 이들로 계산한 팀 조합 피처를 바탕으로 첫 번째 팀의 승리 확률을 예측합니다. 개별 포켓몬의 기본 특성과 팀 구성의 관계가 경기 결과에 어떤 예측 정보를 제공하는지 살펴봅니다.

## 데이터

- **경기 기록:** [HolidayOugi/pokemon-showdown-replays](https://huggingface.co/datasets/HolidayOugi/pokemon-showdown-replays)
- **도감 및 타입 상성:** [Pokémon Showdown](https://github.com/smogon/pokemon-showdown)의 5세대 기준 데이터
- **대상 포맷:** Gen 5 Ubers, OU, UU, RU, NU, PU, ZU

경기 시작 전 팀 미리보기에서 양 팀의 포켓몬 명단을 추출하고, 실제 승패를 정답으로 사용합니다. 포켓몬의 종 ID에 도감 정보를 연결해 종족값과 타입을 구성합니다.

## 예측에 사용하는 정보

| 구분 | 정보 |
|---|---|
| 포켓몬 기본 정보 | 양 팀 각 6마리의 종, 종족값 6개, 타입 |
| 조합 피처 | 팀 능력치 요약, 타입 구성, 방어 상성, 양 팀의 차이 |
| 예측 대상 | 첫 번째 팀이 승리할 확률 |

기술, 아이템, 특성, 플레이어 레이팅은 입력에서 제외합니다. 경기 중 체력 변화나 사용 기술 등 진행 정보도 경기 전 예측의 입력으로 사용하지 않습니다. 방어 상성은 타입만 기준으로 계산하며, 실제 기술의 공격 범위나 피해량을 의미하지 않습니다.

## 진행 상황

- 7개 포맷을 같은 기준으로 정리한 **822,419경기의 기본 데이터셋** 구축
- 포켓몬 기본 정보 108개에 경기 ID, 포맷, 업로드 시각, 승자와 정답을 포함한 113개 컬럼으로 구성

능력치 요약 피처 54개를 샘플 경기에서 검증한 뒤 전체 822,419경기에 추가했습니다. 기존 113열을 유지한 167열 데이터셋을 별도로 저장하며, 입력 후보는 기본 피처 108개와 조합 피처 54개로 총 162개입니다. 타입 구성·방어 상성 피처는 아직 구현 전이며, 모델 학습과 성능 평가도 아직 수행하지 않았습니다.

## 디렉토리 구조

```text
pokemon-gen5-battle-prediction/
├── README.md
├── .gitignore
├── requirements.txt
├── initial_preparation/              # 초기 데이터 수집·가공 작업
│   ├── code/
│   │   ├── log_download_gen5.sh      # 원본 경기 로그 다운로드
│   │   ├── parse_logs.py             # 경기 로그 파싱
│   │   ├── merge_external.py         # 도감·기술 정보 결합
│   │   ├── verify_merge.py           # 결합 결과 검증
│   │   └── combine_parts.py          # 분할 결과 파일 통합
│   └── reports/
│       ├── download.log              # 다운로드 실행 기록
│       └── *_summary.json            # 포맷·부분 파일별 파싱 요약 9개
├── preprocessing/                    # 기본 데이터 정리·조합 피처 생성
│   ├── prepare_basic.py
│   ├── build_stat_sample.py
│   ├── build_stat_features.py         # 전체 경기의 능력치 피처 생성·검증
│   └── feature_definitions.md
└── data/
    ├── raw/                          # 원본 경기 로그 Parquet 9개
    ├── external/
    │   ├── pokedex.csv                # 포켓몬 종족값·타입
    │   └── moves.csv                  # 기술 정보
    ├── initial_dataset/              # 초기 가공 데이터 CSV·Parquet 18개 보존
    └── datasets/
        ├── basic/
        │   ├── data/                 # 통합·포맷별 기본 데이터 표 9개
        │   └── info/                 # 설명·검증 자료
        │       ├── README.md         # 기본 데이터셋 설명
        │       ├── columns.json      # 입력 피처·관리 정보·정답 목록
        │       ├── quality_report.json # 데이터 생성·품질 검증 결과
        │       └── excluded_rows.csv # 제외한 경기와 이유
        ├── features_sample/
        │   ├── data/                 # 한 경기의 계산 결과표
        │   │   ├── stat_sample.csv
        │   │   └── stat_sample.parquet
        │   └── info/                 # 샘플 설명·검증 자료
        │       ├── stat_definitions.json
        │       ├── example.md
        │       └── checks.json
        └── stat_features/            # 전체 경기 + 능력치 조합 피처 54개
            ├── data/
            │   ├── all_stat_features.csv
            │   └── all_stat_features.parquet
            └── info/
                ├── README.md
                ├── columns.json
                └── quality_report.json
```

`initial_preparation/`에는 초기 작업의 코드와 실행 기록을, `preprocessing/`에는 이후 전처리와 조합 피처 생성 코드를 둡니다. 두 단계에서 사용하는 데이터는 공통 `data/` 아래에 역할별로 보관합니다.

`data/initial_dataset/`은 기존 초기 가공 결과를 보존하는 폴더입니다. 이후 생성하는 데이터셋은 `data/datasets/` 아래에 구분해서 저장합니다. `basic/data/`에는 데이터 표를, `basic/info/`에는 설명·컬럼 정의·검증 결과·제외 목록을 모읍니다. `features_sample/`은 전체 경기의 피처 데이터셋이 아닌, 첫 경기 한 건의 계산·검증 예시입니다.

위 구조는 로컬 데이터 파일을 포함합니다. `.gitignore`는 원본 로그, 초기 데이터셋, 전체 데이터셋의 CSV·Parquet를 제외하며, 참조 데이터와 설명·검증 자료, 작은 피처 샘플은 추적할 수 있도록 설정되어 있습니다. 새로 저장소를 받으면 제외된 데이터는 별도로 준비해야 합니다.

## 실행 방법

Python 3.13에서 실행을 확인했습니다. 아래 명령은 저장소 루트 기준입니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

초기 보존본 `data/initial_dataset/`의 Parquet 9개가 준비되어 있다면 다음 명령으로 기본 데이터와 능력치 피처 샘플을 생성합니다.

```bash
python preprocessing/prepare_basic.py
python preprocessing/build_stat_sample.py
```

기본 데이터 표는 `data/datasets/basic/data/`, 설명·컬럼 정의·품질 보고서·제외 목록은 `data/datasets/basic/info/`에 저장됩니다. 피처 샘플의 결과표는 `data/datasets/features_sample/data/`, 설명·검증 자료는 `data/datasets/features_sample/info/`에 저장됩니다. 각 명령은 같은 위치에 있는 기존 출력 파일을 덮어씁니다. 별도 결과를 만들려면 출력 경로를 지정합니다.

```bash
python preprocessing/prepare_basic.py --output data/datasets/basic_new
python preprocessing/build_stat_sample.py --output data/datasets/features_sample_new
```

첫 명령의 데이터 표는 `data/datasets/basic_new/data/`, 설명·검증 자료는 `data/datasets/basic_new/info/`에 저장됩니다. 다른 위치를 원하면 `--info-output`을 지정합니다. 두 번째 명령은 기본적으로 기존 `basic/data/all_basic.parquet`를 읽으며, 새 기본 표를 사용하려면 `--source data/datasets/basic_new/data/all_basic.parquet`를 함께 지정합니다.

전체 경기의 능력치 조합 피처는 다음 명령으로 생성합니다.

```bash
python preprocessing/build_stat_features.py
```

`basic/data/all_basic.parquet`의 기존 113열과 경기 순서를 유지하고, 샘플과 같은 계산으로 새 피처 54개를 뒤에 붙입니다. 통합 CSV·Parquet는 `stat_features/data/`, 설명·컬럼 정의·검증 결과는 `stat_features/info/`에 저장합니다. 기존 출력이 있으면 덮어쓰지 않고 중단하므로, 다시 만들 때는 `--output data/datasets/stat_features_new`처럼 새 폴더를 지정합니다.

모든 경기의 기존 값과 새 피처의 결측·무한값 여부, CSV·Parquet 저장값을 검사합니다. 별도 계산과 슬롯 순서·팀 교환·관리 정보 및 정답 변경 검사는 고정 난수 표본과 첫·마지막 경기에서 수행합니다. `columns.json`에는 기본 입력 108개, 새 입력 54개, 합친 입력 162개의 목록을 구분해 기록하며 정답과 관리 정보는 입력 목록에 넣지 않습니다.

원본 로그부터 다시 처리하는 경우의 ZU 예시입니다. 다운로드 명령은 전체 로그 9개를 받습니다.

```bash
bash initial_preparation/code/log_download_gen5.sh
python initial_preparation/code/parse_logs.py 'data/raw/[Gen 5] ZU.parquet' --out data/datasets/parsed/zu
python initial_preparation/code/merge_external.py zu
python initial_preparation/code/verify_merge.py zu
```

파싱 표는 `data/datasets/parsed/`, 외부 정보 결합 표는 `data/datasets/enriched/`에 저장됩니다. 두 폴더는 위 명령을 실행할 때 생성됩니다. 파싱 요약은 `initial_preparation/reports/zu_summary.json`에 저장되며, 기존 기록을 보존하려면 `--report-dir`로 별도 위치를 지정합니다. 도감·기술 정보는 `data/external/`에서 읽습니다. `data/initial_dataset/`은 기본 출력 경로로 사용하지 않습니다.

전체 로그에서 기본 표를 다시 만들려면 9개 파일을 각각 `ubers`, `ou_part1`, `ou_part2`, `ou_part3`, `uu`, `ru`, `nu`, `pu`, `zu`라는 출력 이름으로 파싱하고 결합한 뒤, `prepare_basic.py --source data/datasets/enriched`를 실행합니다. 분할 처리 결과를 합치는 `combine_parts.py`는 기존처럼 대상 폴더와 이름을 인자로 받습니다.

Python 코드의 기본 경로는 스크립트 위치를 기준으로 계산합니다. 사용자가 직접 넘기는 상대 경로는 명령을 실행한 위치를 기준으로 합니다.

## 참고 프로젝트

[FutureSightML](https://github.com/HotHams/FutureSightML)의 팀 구성 기반 승률 예측 접근과 피처 설계를 참고합니다.

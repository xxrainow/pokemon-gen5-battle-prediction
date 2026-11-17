# 데이터 경로

| 경로 | 내용 | Git 포함 |
|---|---|---|
| `external/` | 기존 `pokemon/external/`의 도감·기술 CSV | 예 |
| `raw/` | 다운로드한 Showdown 로그 Parquet 9개 | 아니요 |
| `initial_dataset/` | 기존 `pokemon/data/original/`의 초기 보존본 | 아니요 |
| `processed/parsed/` | 파서를 재실행한 결과 | 아니요 |
| `processed/enriched/` | 재파싱 결과에 외부 정보를 결합한 결과 | 아니요 |
| `processed/basic/` | 113열 기본 데이터 | 아니요 |
| `processed/features/` | 향후 전체 조합 피처 | 아니요 |
| `archive/pokemon/` | 현재 중간 표와 구분해 보존하는 과거 파싱 요약 | 아니요 |
| `archive/pokemon_2/` | 원본 폴더의 중복 README | 아니요 |

기존 `pokemon/data/original/`의 현재 Parquet는 이미 외부 정보가 결합된 파일입니다. 이를 사용할 경우 `initial_dataset/`에 복사합니다. 기존 `pokemon_2/data/basic_all/`의 전체 표는 `processed/basic/`에 대응합니다. 원본 폴더는 그대로 보존합니다. `initial_dataset/`도 초기 상태를 보존하는 폴더로 사용하며, 파싱·결합 코드의 기본 출력은 `processed/parsed/`와 `processed/enriched/`로 분리했습니다.

## 로컬 파일 배치

이 컴퓨터에서는 아래 경로에 원본을 복사해 두었습니다. 이 경로들은 `.gitignore`에 등록되어 있으며, GitHub에서 저장소를 새로 받으면 데이터는 별도로 준비해야 합니다.

| 기존 로컬 파일 | 저장소 내 로컬 보관 경로 |
|---|---|
| `pokemon/log/*.parquet` | `data/raw/` |
| `pokemon/log/download.log` | `data/raw/download.log` |
| `pokemon/data/original/*.parquet`, `*.csv` | `data/initial_dataset/` |
| `pokemon/data/original/*_summary.json` | `data/archive/pokemon/parsing_summaries/` |
| `pokemon_2/data/basic_all/*.parquet`, `*.csv` | `data/processed/basic/` |
| `pokemon_2/README.md` | `data/archive/pokemon_2/README.md` |

`data/processed/parsed/`와 `data/processed/enriched/`는 재실행 결과용 빈 폴더입니다. 과거 `*_summary.json`은 현재 결합 표와 처리 단계·일부 행 수가 다르므로 여기에 두지 않습니다. `data/processed/features/`도 앞으로 전체 피처를 생성할 때 사용할 빈 폴더로 준비했습니다.

`.DS_Store`, `.vscode/`, `__pycache__/`는 실행에 불필요하므로 복사하지 않고 Git에서도 무시합니다. 원본 폴더를 실수로 저장소 바로 아래에 복사하는 경우에도 `/pokemon/`, `/pokemon_2/`를 무시합니다.

초기 보존본에서 기본 표를 다시 만들 때는 `python scripts/prepare_basic.py`를 실행합니다. 출력은 `data/processed/basic/`에 저장됩니다.

기존 기본 표에서 피처 샘플을 확인하려면 저장소 루트에서 다음 명령을 실행합니다. 출력은 추적 중인 샘플을 덮어쓰지 않는 로컬 전용 경로에 저장합니다.

```bash
.venv/bin/python scripts/build_stat_sample.py --output data/processed/features/stat_sample
```

기본 표 생성은 기본적으로 `initial_dataset/`을 읽습니다. 재파싱부터 다시 만들려면 다음 절차를 사용합니다. 필요한 파일명은 `ubers.parquet`, `ou_part1.parquet`, `ou_part2.parquet`, `ou_part3.parquet`, `uu.parquet`, `ru.parquet`, `nu.parquet`, `pu.parquet`, `zu.parquet`입니다. 각각 `scripts/parse_logs.py`의 `--out data/processed/parsed/<이름>`으로 파싱한 뒤 다음과 같이 결합합니다.

```bash
python scripts/merge_external.py ubers ou_part1 ou_part2 ou_part3 uu ru nu pu zu
python scripts/verify_merge.py ubers ou_part1 ou_part2 ou_part3 uu ru nu pu zu
python scripts/prepare_basic.py --source data/processed/enriched
python scripts/build_stat_sample.py
```

`merge_external.py`는 Parquet와 CSV를 모두 생성하며 검사 코드도 두 형식을 사용합니다. 기존 출력이 있는 폴더에서 재실행하면 파일을 덮어쓰므로 비교 실행은 `--out` 또는 `--output`으로 별도 경로를 지정합니다.

`../reports/basic/`에는 기존 실행의 보고서·컬럼 정의·설명을 보존했습니다. 보고서의 입력 경로와 샘플 검사 결과의 입력 경로는 새 저장소 구조에 맞게 바꿨으며 해시와 수치는 원본 그대로입니다. `excluded_rows.csv`는 전체 데이터와 함께 로컬에 보존합니다.

`external/` CSV는 기존 파일의 스냅샷입니다. 생성 스크립트와 Showdown 소스 버전은 확보되지 않았고, 타입 상성표는 아직 포함되어 있지 않습니다. 5세대 전체 데이터의 정확성을 새로 검증한 것은 아닙니다.

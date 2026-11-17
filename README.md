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

현재 능력치 요약 피처를 정의하고 샘플 경기에서 계산을 검증했으며, 타입 구성·방어 상성 피처와 전체 데이터 적용을 진행할 예정입니다. 모델 학습과 성능 평가는 아직 수행하지 않았습니다.

## 참고 프로젝트

[FutureSightML](https://github.com/HotHams/FutureSightML)의 팀 구성 기반 승률 예측 접근과 피처 설계를 참고합니다.

## 저장소 구성

- `scripts/`: 로그 다운로드·파싱·외부 정보 결합·기본 데이터 생성 코드
- `data/external/`: 도감 및 기술 정보 CSV 스냅샷
- `reports/basic/`: 기본 데이터 품질 보고서와 컬럼 목록
- `examples/stat_sample/`: 첫 경기의 능력치 피처 54개와 검증 결과
- `docs/feature_definitions.md`: 피처 계산식과 다음 구현 후보

전체 로그와 전처리 데이터는 Git에 포함하지 않습니다. 데이터 경로와 보관 기준은 [데이터 안내](data/README.md)에 정리했습니다.

## 실행

Python 3.13에서 확인했으며, 모든 명령은 저장소 루트에서 실행합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
bash scripts/log_download_gen5.sh
```

작은 ZU 포맷의 파싱·결합·검사 예시입니다. 다운로드 스크립트는 전체 7개 포맷의 파일 9개를 받습니다.

```bash
python scripts/parse_logs.py 'data/raw/[Gen 5] ZU.parquet' --out data/interim/parsed/zu
python scripts/merge_external.py zu
python scripts/verify_merge.py zu
```

기본 데이터 생성에는 9개 부분 파일 모두의 결합 결과가 필요합니다. 전체 준비 후 실행합니다.

```bash
python scripts/prepare_basic.py
python scripts/build_stat_sample.py
```

기존 기본 데이터가 있다면 `data/processed/basic/all_basic.parquet`에 두고 마지막 명령만 실행해도 됩니다. 로컬 파일을 가져온 이번 작업에서는 ZU 파싱·결합 검사와 기존 기본 표를 사용한 피처 샘플 재실행을 확인했습니다. 전체 822,419경기 재생성은 수행하지 않았습니다. 과거 중간 데이터와 현재 코드의 행 수 차이 등 재현상의 한계는 [통합 조사 기록](docs/import-plan.md)에 정리했습니다.

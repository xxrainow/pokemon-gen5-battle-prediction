# 전처리 작업 구성

| 폴더 | 목적 | 파일 |
|---|---|---|
| `basic/` | 초기 가공 표에서 기술 관련 정보를 제외한 기본 표 생성 | `prepare_basic.py` |
| `features/` | 능력치·타입 구성·방어 상성 피처 계산 및 검증 | `build_*_sample.py`는 한 경기 예시, `build_*_features.py`는 전체 적용 |
| `split/` | 대진 그룹 기준 학습·검증·테스트 분할 | `split_dataset.py` |
| `encoding/` | 모델 입력 선택과 문자 인코딩 | `encoding_spec.md` 정의표, `encode_dataset.py` 변환·검증 코드 |

[조합 피처 정의](features/feature_definitions.md) · [입력·인코딩 정의](encoding/encoding_spec.md)

## 실행 순서

저장소 루트에서 가상환경을 활성화하고 `python -m`으로 실행한다. 파일 간 참조가 있으므로 파일 경로로 직접 실행하는 대신 아래 모듈 명령을 사용한다.

```bash
python -m preprocessing.basic.prepare_basic
python -m preprocessing.features.build_stat_sample
python -m preprocessing.features.build_stat_features
python -m preprocessing.features.build_type_sample
python -m preprocessing.features.build_type_features
python -m preprocessing.features.build_matchup_sample
python -m preprocessing.features.build_matchup_features
python -m preprocessing.split.split_dataset --strategy matchup
python -m preprocessing.encoding.encode_dataset
```

방어 상성 계산에는 `data/external/gen5_typechart.csv`가 필요하다. 원본 다운로드·파싱·외부 정보 결합·공식 상성표 생성은 `initial_preparation/code/`에서 관리한다.

출력 데이터 위치는 기존과 같이 `data/datasets/` 아래다. 코드 분류를 위해 이미 만든 데이터 표를 재생성할 필요는 없다. 기본 표·능력치 샘플은 기존 출력에 덮어쓸 수 있으므로, 실행 전 확인하거나 `--output`으로 새 폴더를 지정한다. 나머지 명령은 기존 출력이 있으면 중단한다. 옵션은 각 명령 뒤에 `--help`를 붙여 확인한다.

인코딩 결과는 `data/datasets/encoded/data/`에 분할별 `X_*.npz`(희소 입력 행렬), `y_*.npy`(정답), `*_rows.parquet`(행 번호·경기 ID·포맷)로 저장한다. `info/`에는 범주 목록·피처 순서·참조 해시와 전체 행 검증 보고서를 보관한다. 숫자는 표준화 없이 float32로 저장한다.

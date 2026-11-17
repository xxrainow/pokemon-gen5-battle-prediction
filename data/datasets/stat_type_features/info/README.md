# 능력치·타입 구성 조합 피처 데이터셋

입력: `data/datasets/stat_features/data/all_stat_features.parquet`

822,419경기 × 218열. 기존 167열의 값·순서를 유지하고 타입 구성 51열을 뒤에 추가했다.

`../data/all_stat_type_features.csv`와 `../data/all_stat_type_features.parquet`는 같은 표다.

## 컬럼 구분

- 기본 정보 108개 + 능력치 54개 + 타입 구성 51개 = 입력 후보 213개
- 관리 정보 4개: battle_id, formatid, uploadtime, winner
- 정답 1개: y (1은 p1 승리, 0은 p2 승리)

winner와 y는 입력에 넣지 않는다. 관리 정보도 자동으로 학습에 포함하지 않는다. columns.json에서 basic_features, stat_features, type_features, features로 입력을 선택할 수 있다.

## 타입 집계

5세대 17개 타입 × (A팀 수·B팀 수·A − B) = 51개다. 불꽃/비행 팀원은 불꽃과 비행에 각각 1을 더하고 단일 타입은 한 번만 센다. 각 타입의 팀원 수는 0~6, 차이는 −6~6, 팀의 타입 수 합계는 6~12다. 이 수는 방어 상성·공격 기술 범위·승률을 나타내지 않는다.

[타입 피처 정의](../../features_sample/info/type_definitions.json)와 [능력치 피처 정의](../../features_sample/info/stat_definitions.json)는 샘플의 정의 파일을 공유한다. 중복 정의 파일은 만들지 않는다.

## 검증

전체 경기의 기존 167열·순서, 타입 수 범위·차이·복수 타입 합계와 CSV·Parquet 전체 값 일치를 확인했다. 첫·마지막 경기와 고정 난수 표본 등 102경기는 독립 집계와 대조했다. 표본에서 슬롯 순서·팀 교환·관리 정보 및 정답 변경 검사도 통과했다. 원본 해시와 검사 결과는 quality_report.json에 있다.

## 다시 생성

```bash
python -m preprocessing.features.build_type_features
```

기존 출력이 있으면 중단한다. --output으로 새 폴더를 지정할 수 있다. 데이터 분할·모델 학습·평가는 아직 진행하지 않았다.

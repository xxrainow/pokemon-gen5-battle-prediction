# 능력치·타입 구성·방어 상성 조합 피처 데이터셋

입력: `data/datasets/stat_type_features/data/all_stat_type_features.parquet`

822,419경기 × 371열. 기존 218열의 값·순서를 유지하고 방어 상성 153열을 뒤에 추가했다.

`../data/all_stat_type_matchup_features.csv`와 `../data/all_stat_type_matchup_features.parquet`는 같은 표다.

## 컬럼 구분

- 기본 정보 108개 + 능력치 54개 + 타입 구성 51개 + 방어 상성 153개 = 입력 후보 366개
- 관리 정보 4개: battle_id, formatid, uploadtime, winner
- 정답 1개: y (1은 p1 승리, 0은 p2 승리)

winner와 y는 입력에 넣지 않는다. 관리 정보도 자동으로 학습에 포함하지 않는다. columns.json에서 basic_features, stat_features, type_features, matchup_features, features로 입력을 선택할 수 있다.

## 방어 상성 집계

팀원마다 공격 타입 17개에 대해 받는 배율을 `data/external/gen5_typechart.csv`에서 찾는다. 복수 타입은 두 배율을 먼저 곱한 뒤 분류한다. 2·4배는 약점, 0.5·0.25배는 저항, 0배는 무효이고 1배는 세지 않는다. 17개 공격 타입 × (약점·저항·무효) × (A팀·B팀·A − B) = 153개다. 팀별 값은 0~6, 차이는 −6~6이다. 특성·아이템·기술 고유 효과·날씨는 반영하지 않는다.

계산 과정은 [첫 경기 예시](../../features_sample/info/matchup_example.md)에서 볼 수 있다. [방어 상성 정의](../../features_sample/info/matchup_definitions.json), [타입 구성 정의](../../features_sample/info/type_definitions.json), [능력치 정의](../../features_sample/info/stat_definitions.json)는 샘플의 정의 파일을 공유한다.

## 검증

상성표 해시, 전체 경기의 기존 218열·순서, 방어 상성 수 범위·차이·분류 합계(6 이하)와 CSV·Parquet 전체 값 일치를 확인했다. 모든 경기에서 무효 수가 해당 무효 타입(예: 땅 공격 → 비행)의 타입 구성 수와 같은지도 대조했다. 첫·마지막 경기와 고정 난수 표본 등 102경기는 샘플 코드의 행 단위 계산과 대조했다. 표본에서 슬롯 순서·팀 교환·관리 정보 및 정답 변경 검사도 통과했다. 원본 해시, 공격 타입별 평균 수, 검사 결과는 quality_report.json에 있다.

## 다시 생성

```bash
python -m preprocessing.features.build_matchup_features
```

기존 출력이 있으면 중단한다. --output으로 새 폴더를 지정할 수 있다. 데이터 분할·모델 학습·평가는 아직 진행하지 않았다.

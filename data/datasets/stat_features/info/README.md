# 전체 경기의 능력치 조합 피처 데이터셋

입력: `data/datasets/basic/data/all_basic.parquet`

822,419경기 × 167열. 기존 113열을 그대로 두고 능력치 피처 54열을 뒤에 추가했다.


## 컬럼 구분

- 입력 후보 162개: 기존 종·종족값·타입 108개 + 능력치 조합 피처 54개
- 관리 정보 4개: battle_id, formatid, uploadtime, winner
- 정답 1개: y (1은 p1 승리, 0은 p2 승리)

winner와 y는 입력 피처가 아니다. 관리 정보도 자동으로 학습에 포함하지 않는다. columns.json의 basic_features, stat_features, features를 사용해 입력 구성을 구분할 수 있다.

## 추가한 계산

HP·공격·방어·특수공격·특수방어·스피드마다 팀 평균·최댓값·모집단 표준편차를 계산한다. 양 팀의 값 36개와 p1 − p2 차이 18개로 총 54개다.

[샘플의 피처 정의](../../features_sample/info/stat_definitions.json)와 동일한 54개 계산을 사용한다.

## 검증

모든 경기의 기존 113열·순서 보존, 새 피처의 결측·무한값 없음, CSV·Parquet 전체 값 일치를 확인했다. 첫·마지막 경기와 고정 난수 표본 등 102경기는 별도 계산과 대조했다. 표본에서 슬롯 순서·팀 교환·관리 정보 및 정답 변경 검사도 통과했다. 세부 결과와 원본 해시는 quality_report.json에 있다.

## 다시 생성

```bash
python -m preprocessing.features.build_stat_features
```

기존 출력이 있으면 중단한다. 다른 결과를 만들려면 --output으로 새 폴더를 지정한다. 데이터 분할·학습·평가는 아직 하지 않았다.

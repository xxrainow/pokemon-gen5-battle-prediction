# 원핫 인코딩 데이터

종·타입·포맷을 고정 사전으로 원핫 인코딩했다. 숫자 330개는 표준화 없이 float32로 저장하므로 소수점에 반올림 오차가 있을 수 있다.

`data/X_{split}.npz`: CSR 입력 행렬, `data/y_{split}.npy`: 정답(0=p2 승리, 1=p1 승리), `data/{split}_rows.parquet`: 행 번호·경기 ID·포맷 대응표. 경로는 encoded 폴더 기준이다.

`encoding_manifest.json`에 열별 범주·출력 위치·피처 이름·참조 해시가 있고 `quality_report.json`에 분할별 크기·UNKNOWN·전체 저장값 검사가 있다.

```python
from scipy.sparse import load_npz
import numpy as np
X = load_npz('data/datasets/encoded/data/X_train.npz')
y = np.load('data/datasets/encoded/data/y_train.npy', allow_pickle=False)
```

실행: `python -m preprocessing.encoding.encode_dataset`. 기존 출력이 있으면 중단한다. 재생성은 `--output`으로 새 폴더를 지정한다. 모델 학습·평가는 수행하지 않았다.

"""고정 사전으로 종·타입·포맷을 원핫 인코딩한다. 표준화·모델 학습은 하지 않는다.

실행: python -m preprocessing.encoding.encode_dataset
"""

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import platform

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import scipy
from scipy import sparse

ROOT = Path(__file__).resolve().parents[2]
SPLITS = ("train", "validation", "test")
FORMATS = sorted(("gen5nu", "gen5ou", "gen5pu", "gen5ru", "gen5ubers", "gen5uu", "gen5zu"))
UNKNOWN, NONE = "__UNKNOWN__", "__NONE__"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_plan(columns_path, pokedex_path, chart_path):
    columns = json.loads(columns_path.read_text())
    inputs = columns["features"] + ["formatid"]
    if len(inputs) != 367 or len(set(inputs)) != len(inputs):
        raise ValueError("입력 명세는 중복 없는 367개 컬럼이어야 합니다.")
    if set(inputs) & {"battle_id", "uploadtime", "winner", "y"}:
        raise ValueError("정답·제외 컬럼이 입력에 포함됐습니다.")
    with pokedex_path.open(newline="") as stream:
        species = [r["species"] for r in csv.DictReader(stream)]
    with chart_path.open(newline="") as stream:
        types = [r["attack_type"].strip().lower() for r in csv.DictReader(stream)]
    if len(set(species)) != len(species) or any(not x for x in species):
        raise ValueError("도감 종 목록의 중복·결측")
    if len(set(types)) != 17 or len(types) != 17:
        raise ValueError("상성표 타입 목록은 중복 없는 17개여야 합니다.")
    if set(species + types) & {UNKNOWN, NONE}:
        raise ValueError("참조 목록에 예약 항목이 있습니다.")
    categories, numeric, blocks, names = {}, [], {}, []
    for col in inputs:
        if col.endswith("_species"):
            values = sorted(species) + [UNKNOWN]
        elif col.endswith("_type1"):
            values = sorted(types) + [UNKNOWN]
        elif col.endswith("_type2"):
            values = sorted(types) + [NONE, UNKNOWN]
        elif col == "formatid":
            values = FORMATS
        else:
            values = None
        start = len(names)
        if values is None:
            numeric.append(col)
            names.append(col)
        else:
            categories[col] = values
            names.extend(f"{col}={value}" for value in values)
        blocks[col] = {"start": start, "stop": len(names)}
    if len(numeric) != 330 or len(categories) != 37:
        raise ValueError("숫자 330개·범주 37개의 정의와 일치하지 않습니다.")
    return {"version": 1, "input_columns": inputs, "numeric_columns": numeric,
            "categories": categories, "blocks": blocks, "feature_names": names,
            "shape_columns": len(names), "dtype": "float32", "format": "CSR",
            "target": "y", "excluded": ["battle_id", "uploadtime", "winner"],
            "standardization": "none", "numeric_precision": "float32 변환에 따른 반올림 오차 있음",
            "references": {str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p): sha256(p)
                           for p in (columns_path, pokedex_path, chart_path)}}


def normalized_values(col, values, categories):
    """각 원래 값에 대응하는 범주와 미등록 원래 값을 돌려준다."""
    known = set(categories) - {UNKNOWN, NONE}
    normalized, unknown = [], Counter()
    for value in values:
        if col.endswith(("_type1", "_type2")) and isinstance(value, str):
            value = value.strip().lower()
        missing = value is None or value == ""
        if col.endswith("_type2") and missing:
            normalized.append(NONE)
            continue
        if missing or not isinstance(value, str):
            raise ValueError(f"{col}: 필수 범주 결측 또는 문자열이 아닌 값 {value!r}")
        if value not in known:
            if col == "formatid":
                raise ValueError(f"대상 밖 포맷: {value}")
            unknown[value] += 1
            normalized.append(UNKNOWN)
        else:
            normalized.append(value)
    return normalized, unknown


def numeric_values(table, plan):
    values = np.column_stack([table[c].to_numpy(zero_copy_only=False)
                              for c in plan["numeric_columns"]]).astype(np.float32)
    if not np.isfinite(values).all():
        raise ValueError("숫자 입력에 결측·무한값 또는 float32 범위 초과")
    return values


def encode_batch(table, plan, unknown_counts):
    n = len(table)
    values = numeric_values(table, plan)
    r, c = np.nonzero(values)
    positions = np.array([plan["blocks"][col]["start"] for col in plan["numeric_columns"]])
    row_parts, col_parts, data_parts = [r], [positions[c]], [values[r, c]]
    for col, categories in plan["categories"].items():
        mapped, unknown = normalized_values(col, table[col].to_pylist(), categories)
        unknown_counts[col].update(unknown)
        lookup = {value: i for i, value in enumerate(categories)}
        row_parts.append(np.arange(n))
        col_parts.append(np.array([lookup[v] for v in mapped]) + plan["blocks"][col]["start"])
        data_parts.append(np.ones(n, dtype=np.float32))
    return sparse.csr_matrix((np.concatenate(data_parts),
                              (np.concatenate(row_parts), np.concatenate(col_parts))),
                             shape=(n, plan["shape_columns"]), dtype=np.float32)


def verify_saved(matrix, y, ids_path, source_path, plan, batch_size):
    """저장 행렬을 열별로 해석해서 모든 원본 행과 대조한다."""
    ids = pq.read_table(ids_path).to_pydict()
    offset = 0
    numeric_positions = [plan["blocks"][col]["start"] for col in plan["numeric_columns"]]
    for batch in pq.ParquetFile(source_path).iter_batches(batch_size=batch_size):
        table = pa.Table.from_batches([batch])
        end = offset + len(table)
        selected = matrix[offset:end]
        np.testing.assert_array_equal(selected[:, numeric_positions].toarray(), numeric_values(table, plan))
        for col, categories in plan["categories"].items():
            block = plan["blocks"][col]
            hot = selected[:, block["start"]:block["stop"]]
            assert hot.nnz == len(table) and np.all(hot.data == 1)
            np.testing.assert_array_equal(np.diff(hot.indptr), np.ones(len(table)))
            decoded = [categories[i] for i in hot.indices]
            assert decoded == normalized_values(col, table[col].to_pylist(), categories)[0]
        np.testing.assert_array_equal(y[offset:end], table["y"].to_numpy())
        assert ids["battle_id"][offset:end] == table["battle_id"].to_pylist()
        assert ids["formatid"][offset:end] == table["formatid"].to_pylist()
        assert ids["row_index"][offset:end] == list(range(offset, end))
        offset = end
    assert offset == len(y) == matrix.shape[0] == len(ids["battle_id"])
    assert matrix.shape[1] == plan["shape_columns"] and matrix.dtype == np.float32
    assert np.isfinite(matrix.data).all()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=ROOT / "data/datasets/splits/data")
    ap.add_argument("--output", type=Path, default=ROOT / "data/datasets/encoded")
    ap.add_argument("--columns", type=Path, default=ROOT / "data/datasets/stat_type_matchup_features/info/columns.json")
    ap.add_argument("--pokedex", type=Path, default=ROOT / "data/external/pokedex.csv")
    ap.add_argument("--typechart", type=Path, default=ROOT / "data/external/gen5_typechart.csv")
    ap.add_argument("--batch-size", type=int, default=10000)
    args = ap.parse_args()
    if args.batch_size <= 0:
        ap.error("batch-size는 양수여야 합니다.")
    if args.output.exists() and any(args.output.iterdir()):
        ap.error("출력이 이미 있습니다. --output으로 새 폴더를 지정하세요.")
    plan = make_plan(args.columns, args.pokedex, args.typechart)
    sources = {name: args.source / f"{name}.parquet" for name in SPLITS}
    hashes = {name: sha256(path) for name, path in sources.items()}
    required = set(plan["input_columns"] + ["battle_id", "y"])
    for path in sources.values():
        if required - set(pq.ParquetFile(path).schema_arrow.names):
            ap.error(f"필수 컬럼 누락: {path}")
    data_dir, info_dir = args.output / "data", args.output / "info"
    data_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    report = {"versions": {"python": platform.python_version(), "numpy": np.__version__,
                           "scipy": scipy.__version__, "pyarrow": pa.__version__},
              "script_sha256": sha256(Path(__file__)), "outputs": {}}
    for name, path in sources.items():
        print(f"{name}: 인코딩 시작", flush=True)
        chunks, targets, id_tables = [], [], []
        unknown = {col: Counter() for col in plan["categories"]}
        offset = 0
        for batch in pq.ParquetFile(path).iter_batches(batch_size=args.batch_size):
            table = pa.Table.from_batches([batch])
            labels = table["y"].to_numpy(zero_copy_only=False)
            if not np.isin(labels, [0, 1]).all():
                raise ValueError("정답은 0 또는 1이어야 합니다.")
            ids = table["battle_id"].to_pylist()
            if any(not value for value in ids):
                raise ValueError("빈 경기 ID")
            chunks.append(encode_batch(table, plan, unknown))
            targets.append(labels.astype(np.uint8))
            id_tables.append(pa.table({"row_index": np.arange(offset, offset + len(table), dtype=np.int64),
                                       "battle_id": table["battle_id"], "formatid": table["formatid"]}))
            offset += len(table)
        if not offset:
            raise ValueError(f"빈 분할: {name}")
        matrix, y = sparse.vstack(chunks, format="csr"), np.concatenate(targets)
        del chunks, targets
        sparse.save_npz(data_dir / f"X_{name}.npz", matrix)
        np.save(data_dir / f"y_{name}.npy", y, allow_pickle=False)
        pq.write_table(pa.concat_tables(id_tables), data_dir / f"{name}_rows.parquet")
        del matrix, y, id_tables
        matrix = sparse.load_npz(data_dir / f"X_{name}.npz")
        y = np.load(data_dir / f"y_{name}.npy", allow_pickle=False)
        verify_saved(matrix, y, data_dir / f"{name}_rows.parquet", path, plan, args.batch_size)
        assert sha256(path) == hashes[name]
        report["outputs"][name] = {
            "source": str(path.resolve()), "source_sha256": hashes[name], "rows": matrix.shape[0],
            "columns": matrix.shape[1], "nnz": matrix.nnz, "dtype": str(matrix.dtype),
            "y0": int((y == 0).sum()), "y1": int((y == 1).sum()),
            "unknown_counts": {c: dict(counts) for c, counts in unknown.items()},
            "unknown_total": sum(sum(counts.values()) for counts in unknown.values()),
            "files": {p.name: sha256(p) for p in (data_dir / f"X_{name}.npz", data_dir / f"y_{name}.npy",
                                                   data_dir / f"{name}_rows.parquet")},
            "checks": "전체 행 숫자·범주 복원·정답·ID·순서·저장값·입력 불변 확인"}
        del matrix, y
        print(f"{name}: {offset:,}경기 × {plan['shape_columns']:,}열 저장·검증 완료", flush=True)
    write_json(info_dir / "encoding_manifest.json", plan)
    write_json(info_dir / "quality_report.json", report)
    (info_dir / "README.md").write_text(
        "# 원핫 인코딩 데이터\n\n종·타입·포맷을 고정 사전으로 원핫 인코딩했다. 숫자 330개는 "
        "표준화 없이 float32로 저장하므로 소수점에 반올림 오차가 있을 수 있다.\n\n"
        "`data/X_{split}.npz`: CSR 입력 행렬, `data/y_{split}.npy`: 정답(0=p2 승리, 1=p1 승리), "
        "`data/{split}_rows.parquet`: 행 번호·경기 ID·포맷 대응표. 경로는 encoded 폴더 기준이다.\n\n"
        "`encoding_manifest.json`에 열별 범주·출력 위치·피처 이름·참조 해시가 있고 "
        "`quality_report.json`에 분할별 크기·UNKNOWN·전체 저장값 검사가 있다.\n\n"
        "```python\nfrom scipy.sparse import load_npz\nimport numpy as np\n"
        "X = load_npz('data/datasets/encoded/data/X_train.npz')\n"
        "y = np.load('data/datasets/encoded/data/y_train.npy', allow_pickle=False)\n```\n\n"
        "실행: `python -m preprocessing.encoding.encode_dataset`. 기존 출력이 있으면 중단한다. "
        "재생성은 `--output`으로 새 폴더를 지정한다. 모델 학습·평가는 수행하지 않았다.\n", encoding="utf-8")


if __name__ == "__main__":
    main()

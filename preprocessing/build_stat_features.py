"""기본 데이터의 전체 경기에 능력치 조합 피처 54개를 추가한다.

실행: python preprocessing/build_stat_features.py
기존 basic은 읽기만 한다. stat_features/data와 info에 결과를 저장한다.
"""

import argparse
import hashlib
import json
import math
import random
from collections import Counter
from os.path import relpath
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from build_stat_sample import STATS, SUMMARY, compute_features, feature_definitions, verify
from prepare_basic import COLUMNS, FEATURES, META, SCHEMA


STAT_FEATURES = [d["name"] for d in feature_definitions()]
ROOT = Path(__file__).resolve().parent.parent


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def display_path(path):
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_all(values):
    total = values[0]
    for value in values[1:]:
        total = pc.add(total, value)
    return total


def calculate_features(table):
    """한 번에 여러 경기 계산. 정답·관리 정보와 타입은 계산에 사용하지 않는다."""
    result = {}
    for side in ("p1", "p2"):
        for stat in STATS:
            values = [pc.cast(table[f"{side}_slot{k}_{stat}"], pa.float64())
                      for k in range(1, 7)]
            for value in values:
                if (value.null_count or not pc.all(pc.is_finite(value)).as_py()
                        or not pc.all(pc.and_(pc.greater(value, 0),
                                             pc.less_equal(value, 255))).as_py()):
                    raise ValueError(f"잘못된 종족값: {side}/{stat}")
            mean = pc.divide(add_all(values), 6.0)
            squared = [pc.multiply(pc.subtract(value, mean), pc.subtract(value, mean))
                       for value in values]
            result[f"{side}_{stat}_mean"] = mean
            result[f"{side}_{stat}_max"] = pc.max_element_wise(*values)
            result[f"{side}_{stat}_std"] = pc.sqrt(pc.divide(add_all(squared), 6.0))
    for stat in STATS:
        for summary in SUMMARY:
            result[f"diff_{stat}_{summary}"] = pc.subtract(
                result[f"p1_{stat}_{summary}"], result[f"p2_{stat}_{summary}"])
    return result


def check_symmetry(table):
    """전체 계산 코드도 슬롯 순서·팀 교환·정답 변경에 일관되게 동작하는지 검사."""
    original = calculate_features(table)
    reversed_table = table
    swapped_table = table
    for side, opposite in (("p1", "p2"), ("p2", "p1")):
        for k in range(1, 7):
            for stat in STATS:
                name = f"{side}_slot{k}_{stat}"
                i = table.schema.get_field_index(name)
                reversed_table = reversed_table.set_column(
                    i, name, table[f"{side}_slot{7-k}_{stat}"])
                swapped_table = swapped_table.set_column(
                    i, name, table[f"{opposite}_slot{k}_{stat}"])
    reversed_features = calculate_features(reversed_table)
    swapped_features = calculate_features(swapped_table)
    for name, value in original.items():
        if not pc.all(pc.less_equal(pc.abs(pc.subtract(value, reversed_features[name])), 1e-10)).as_py():
            raise ValueError(f"슬롯 순서 검사 실패: {name}")
        if name.startswith("diff_"):
            other = pc.negate(swapped_features[name])
        else:
            opposite = "p2_" + name[3:] if name.startswith("p1_") else "p1_" + name[3:]
            other = swapped_features[opposite]
        if not pc.all(pc.less_equal(pc.abs(pc.subtract(value, other)), 1e-10)).as_py():
            raise ValueError(f"팀 교환 검사 실패: {name}")
    changed = table
    for name in META + ["y"]:
        i = changed.schema.get_field_index(name)
        changed = changed.set_column(i, name, pa.nulls(len(table), type=table[name].type))
    changed_features = calculate_features(changed)
    if any(not original[name].equals(changed_features[name]) for name in STAT_FEATURES):
        raise ValueError("관리 정보·정답이 피처 계산에 영향을 줌")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=ROOT / "data/datasets/basic/data/all_basic.parquet")
    parser.add_argument("--output", type=Path, default=ROOT / "data/datasets/stat_features")
    parser.add_argument("--batch-size", type=int, default=10000)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size는 양수여야 합니다.")
    source = pq.ParquetFile(args.source)
    if not source.schema_arrow.equals(SCHEMA, check_metadata=False):
        parser.error("입력은 basic의 113열 스키마여야 합니다.")
    rows = source.metadata.num_rows
    if not rows:
        parser.error("입력 데이터에 경기가 없습니다.")
    data_dir, info_dir = args.output / "data", args.output / "info"
    parquet_path = data_dir / "all_stat_features.parquet"
    csv_path = data_dir / "all_stat_features.csv"
    output_paths = [parquet_path, csv_path] + [info_dir / n for n in
                    ("README.md", "columns.json", "quality_report.json")]
    if any(path.exists() for path in output_paths):
        parser.error("출력 파일이 이미 있습니다. --output으로 다른 폴더를 지정하세요.")
    source_hash = sha256(args.source)
    data_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    schema = source.schema_arrow
    for name in STAT_FEATURES:
        schema = schema.append(pa.field(name, pa.float64()))
    expected_digest = hashlib.sha256()
    formats = Counter()
    written = 0
    with pq.ParquetWriter(parquet_path, schema, compression="snappy") as writer, \
            pacsv.CSVWriter(csv_path, schema) as csv_writer:
        for batch in source.iter_batches(batch_size=args.batch_size):
            table = pa.Table.from_batches([batch])
            features = calculate_features(table)
            for name in STAT_FEATURES:
                table = table.append_column(name, features[name])
            writer.write_table(table)
            csv_writer.write_table(table)
            sink = pa.BufferOutputStream()
            pacsv.write_csv(table, sink, write_options=pacsv.WriteOptions(include_header=False))
            expected_digest.update(sink.getvalue().to_pybytes())
            formats.update(table["formatid"].to_pylist())
            written += len(table)
            if written == len(table) or written % 100000 == 0 or written == rows:
                print(f"계산·저장: {written:,}/{rows:,}경기", flush=True)

    # 원본 113열은 모든 경기에서 보존됐는지 검사하고 새 피처를 독립 계산과 대조한다.
    saved = pq.ParquetFile(parquet_path)
    if written != rows or saved.metadata.num_rows != rows or not saved.schema_arrow.equals(schema):
        raise ValueError("저장 행 수·스키마 불일치")
    sample_indices = {0, rows - 1} | set(random.Random(0).sample(range(rows), min(100, rows)))
    sampled_inputs = []
    offset, checked = 0, 0
    parquet_csv_digest = hashlib.sha256()
    for original_batch, saved_batch in zip(source.iter_batches(batch_size=args.batch_size),
                                           saved.iter_batches(batch_size=args.batch_size)):
        original = pa.Table.from_batches([original_batch])
        output = pa.Table.from_batches([saved_batch])
        if not original.equals(output.select(COLUMNS)):
            raise ValueError("기존 컬럼 값·경기 순서가 변경됨")
        for name in STAT_FEATURES:
            if output[name].null_count or not pc.all(pc.is_finite(output[name])).as_py():
                raise ValueError(f"비어 있거나 유한하지 않은 피처: {name}")
        local = [i - offset for i in sorted(sample_indices) if offset <= i < offset + len(output)]
        if local:
            inputs = original.take(local)
            sampled_inputs.append(inputs)
            for row, observed in zip(inputs.to_pylist(), output.take(local).to_pylist()):
                reference = compute_features(row)
                verify(row, reference)
                for name in STAT_FEATURES:
                    if not math.isclose(observed[name], reference[name], rel_tol=1e-12, abs_tol=1e-10):
                        raise ValueError(f"독립 계산 불일치: {row['battle_id']}/{name}")
                checked += 1
        sink = pa.BufferOutputStream()
        pacsv.write_csv(output, sink, write_options=pacsv.WriteOptions(include_header=False))
        parquet_csv_digest.update(sink.getvalue().to_pybytes())
        offset += len(output)
    if offset != rows or checked != len(sample_indices):
        raise ValueError("검사 행 수 불일치")
    check_symmetry(pa.concat_tables(sampled_inputs))
    with csv_path.open("rb") as stream:
        header = stream.readline().decode("utf-8").strip()
        if header != ",".join(f'"{name}"' for name in schema.names):
            raise ValueError("CSV 컬럼 순서 불일치")
        csv_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if csv_hash != expected_digest.hexdigest() or csv_hash != parquet_csv_digest.hexdigest():
        raise ValueError("CSV·Parquet 전체 저장값 불일치")
    if sha256(args.source) != source_hash:
        raise ValueError("입력 파일이 변경됨")

    write_json(info_dir / "columns.json", {
        "features": FEATURES + STAT_FEATURES, "basic_features": FEATURES,
        "stat_features": STAT_FEATURES, "metadata": META, "target": "y",
        "columns_in_order": schema.names,
    })
    checks = {name: "passed" for name in (
        "all_original_values_and_row_order_preserved", "all_stat_features_finite_and_non_null",
        "independent_sample_calculation", "slot_order_invariance", "team_swap_sign_check",
        "metadata_and_target_not_used", "full_csv_parquet_roundtrip", "source_file_unchanged")}
    write_json(info_dir / "quality_report.json", {
        "source": display_path(args.source), "source_sha256": source_hash,
        "output_rows": rows, "input_columns": len(COLUMNS), "output_columns": len(schema),
        "basic_feature_count": len(FEATURES), "added_feature_count": len(STAT_FEATURES),
        "feature_count": len(FEATURES) + len(STAT_FEATURES), "metadata_count": len(META),
        "target": "y", "standard_deviation_ddof": 0, "formats": dict(formats),
        "independently_checked_rows": checked, "sample_seed": 0,
        "calculation_tolerance": {"relative": 1e-12, "absolute": 1e-10},
        "csv_body_sha256": csv_hash, "checks": checks,
        "limitations": ["입력 데이터의 파싱·도감 정확성을 새로 검증하지 않음",
                        "타입 조합·방어 상성 피처 미포함", "데이터 분할·모델 학습·평가 미실시"],
    })
    definitions_link = Path(relpath(
        ROOT / "data/datasets/features_sample/info/stat_definitions.json", info_dir)).as_posix()
    (info_dir / "README.md").write_text(
        f"# 전체 경기의 능력치 조합 피처 데이터셋\n\n"
        f"입력: `{display_path(args.source)}`\n\n"
        f"{rows:,}경기 × {len(schema)}열. 기존 113열을 그대로 두고 능력치 피처 54열을 뒤에 추가했다.\n\n"
        "`../data/all_stat_features.parquet`와 `../data/all_stat_features.csv`는 같은 표다. "
        "전체 표를 한 번에 메모리에 올리지 않고 나눠 읽고 저장한다.\n\n"
        "## 컬럼 구분\n\n"
        "- 입력 후보 162개: 기존 종·종족값·타입 108개 + 능력치 조합 피처 54개\n"
        "- 관리 정보 4개: battle_id, formatid, uploadtime, winner\n"
        "- 정답 1개: y (1은 p1 승리, 0은 p2 승리)\n\n"
        "winner와 y는 입력 피처가 아니다. 관리 정보도 자동으로 학습에 포함하지 않는다. "
        "columns.json의 basic_features, stat_features, features를 사용해 입력 구성을 구분할 수 있다.\n\n"
        "## 추가한 계산\n\n"
        "HP·공격·방어·특수공격·특수방어·스피드마다 팀 평균·최댓값·모집단 표준편차를 계산한다. "
        "양 팀의 값 36개와 p1 − p2 차이 18개로 총 54개다. "
        f"[샘플의 피처 정의]({definitions_link})와 동일한 54개 계산을 사용한다.\n\n"
        "## 검증\n\n"
        "모든 경기의 기존 113열·순서 보존, 새 피처의 결측·무한값 없음, CSV·Parquet 전체 값 일치를 확인했다. "
        f"첫·마지막 경기와 고정 난수 표본 등 {checked}경기는 별도 계산과 대조했다. "
        "표본에서 슬롯 순서·팀 교환·관리 정보 및 정답 변경 검사도 통과했다. "
        "세부 결과와 원본 해시는 quality_report.json에 있다.\n\n"
        "## 다시 생성\n\n"
        "```bash\npython preprocessing/build_stat_features.py\n```\n\n"
        "기존 출력이 있으면 중단한다. 다른 결과를 만들려면 --output으로 새 폴더를 지정한다. "
        "데이터 분할·학습·평가는 아직 하지 않았다.\n", encoding="utf-8")
    print(f"완료: {rows:,}경기 × {len(schema)}열; 검증 {len(checks)}개 통과", flush=True)
    print(f"결과표: {data_dir}\n설명·검증 자료: {info_dir}", flush=True)


if __name__ == "__main__":
    main()

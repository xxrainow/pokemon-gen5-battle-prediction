"""전체 경기의 능력치 데이터에 타입 구성 피처 51개를 추가한다.

실행: python preprocessing/build_type_features.py
stat_features를 읽고 stat_type_features/data와 info에 새 결과를 저장한다.
"""

import argparse
import hashlib
import random
from collections import Counter
from os.path import relpath
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq

from build_stat_features import ROOT, STAT_FEATURES, display_path, sha256, write_json
from build_type_sample import TYPES, compute_features, feature_definitions, feature_name, verify
from prepare_basic import COLUMNS, FEATURES, META, SCHEMA


TYPE_FEATURES = [d["name"] for d in feature_definitions()]
INPUT_COLUMNS = COLUMNS + STAT_FEATURES


def add_all(values):
    total = values[0]
    for value in values[1:]:
        total = pc.add(total, value)
    return total


def has_secondary(column):
    return pc.fill_null(pc.not_equal(column, ""), False)


def calculate_features(table):
    """복수 타입은 각 타입에 한 번씩 집계한다. 입력 오류는 누락시키지 않고 중단한다."""
    result = {}
    valid_types = pa.array(TYPES)
    for side in ("p1", "p2"):
        slots = []
        for k in range(1, 7):
            primary, secondary = (table[f"{side}_slot{k}_{f}"] for f in ("type1", "type2"))
            if primary.null_count or not pc.all(pc.is_in(primary, value_set=valid_types)).as_py():
                raise ValueError(f"{side}/slot{k}: 잘못되거나 누락된 첫 번째 타입")
            invalid_secondary = pc.and_(has_secondary(secondary),
                                        pc.invert(pc.is_in(secondary, value_set=valid_types)))
            if pc.any(invalid_secondary).as_py():
                raise ValueError(f"{side}/slot{k}: 잘못된 두 번째 타입")
            if pc.any(pc.fill_null(pc.equal(primary, secondary), False)).as_py():
                raise ValueError(f"{side}/slot{k}: 두 타입이 중복됨")
            slots.append((primary, secondary))
        for t in TYPES:
            indicators = [pc.cast(pc.or_(pc.equal(primary, t),
                                         pc.fill_null(pc.equal(secondary, t), False)), pa.int8())
                          for primary, secondary in slots]
            result[feature_name(side, t)] = add_all(indicators)
    for t in TYPES:
        result[feature_name("diff", t)] = pc.subtract(
            result[feature_name("p1", t)], result[feature_name("p2", t)])
    return result


def check_counts(table):
    """모든 저장 행에서 수 범위, 차이, 단일·복수 타입 합계를 검사한다."""
    for side in ("p1", "p2"):
        values = [table[feature_name(side, t)] for t in TYPES]
        for value in values:
            if value.null_count or not pc.all(pc.and_(pc.greater_equal(value, 0),
                                                      pc.less_equal(value, 6))).as_py():
                raise ValueError("타입 수가 비어 있거나 0~6 범위를 벗어남")
        duals = [pc.cast(has_secondary(table[f"{side}_slot{k}_type2"]), pa.int8())
                 for k in range(1, 7)]
        expected_total = pc.add(add_all(duals), pa.scalar(6, type=pa.int8()))
        if not pc.all(pc.equal(add_all(values), expected_total)).as_py():
            raise ValueError("단일·복수 타입 집계 합계 불일치")
    for t in TYPES:
        difference = table[feature_name("diff", t)]
        expected = pc.subtract(table[feature_name("p1", t)], table[feature_name("p2", t)])
        if difference.null_count or not difference.equals(expected):
            raise ValueError(f"타입 수 차이 불일치: {t}")


def check_symmetry(table):
    original = calculate_features(table)
    reversed_table, swapped_table = table, table
    for side, opposite in (("p1", "p2"), ("p2", "p1")):
        for k in range(1, 7):
            for field in ("type1", "type2"):
                name = f"{side}_slot{k}_{field}"
                i = table.schema.get_field_index(name)
                reversed_table = reversed_table.set_column(
                    i, name, table[f"{side}_slot{7-k}_{field}"])
                swapped_table = swapped_table.set_column(
                    i, name, table[f"{opposite}_slot{k}_{field}"])
    reversed_features, swapped_features = (calculate_features(t) for t in
                                          (reversed_table, swapped_table))
    for t in TYPES:
        for side in ("p1", "p2", "diff"):
            name = feature_name(side, t)
            if not original[name].equals(reversed_features[name]):
                raise ValueError(f"슬롯 순서 검사 실패: {name}")
            if side == "diff":
                other = pc.negate(swapped_features[name])
            else:
                opposite = "p2" if side == "p1" else "p1"
                other = swapped_features[feature_name(opposite, t)]
            if not original[name].equals(other):
                raise ValueError(f"팀 교환 검사 실패: {name}")
    changed = table
    for name in META + ["y"]:
        i = changed.schema.get_field_index(name)
        changed = changed.set_column(i, name, pa.nulls(len(table), type=table[name].type))
    changed_features = calculate_features(changed)
    if any(not original[name].equals(changed_features[name]) for name in TYPE_FEATURES):
        raise ValueError("관리 정보·정답이 타입 피처 계산에 영향을 줌")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=ROOT / "data/datasets/stat_features/data/all_stat_features.parquet")
    parser.add_argument("--output", type=Path, default=ROOT / "data/datasets/stat_type_features")
    parser.add_argument("--batch-size", type=int, default=10000)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size는 양수여야 합니다.")
    expected_schema = SCHEMA
    for name in STAT_FEATURES:
        expected_schema = expected_schema.append(pa.field(name, pa.float64()))
    source = pq.ParquetFile(args.source)
    if not source.schema_arrow.equals(expected_schema, check_metadata=False):
        parser.error("입력은 stat_features의 167열 스키마여야 합니다.")
    rows = source.metadata.num_rows
    if not rows:
        parser.error("입력 데이터에 경기가 없습니다.")
    data_dir, info_dir = args.output / "data", args.output / "info"
    parquet_path = data_dir / "all_stat_type_features.parquet"
    csv_path = data_dir / "all_stat_type_features.csv"
    output_paths = [parquet_path, csv_path] + [info_dir / n for n in
                                            ("README.md", "columns.json", "quality_report.json")]
    if any(p.exists() for p in output_paths):
        parser.error("출력 파일이 이미 있습니다. --output으로 다른 폴더를 지정하세요.")
    source_hash = sha256(args.source)
    data_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    schema = source.schema_arrow
    for name in TYPE_FEATURES:
        schema = schema.append(pa.field(name, pa.int8()))
    expected_digest = hashlib.sha256()
    formats = Counter()
    written = 0
    with pq.ParquetWriter(parquet_path, schema, compression="snappy") as writer, \
            pacsv.CSVWriter(csv_path, schema) as csv_writer:
        for batch in source.iter_batches(batch_size=args.batch_size):
            table = pa.Table.from_batches([batch])
            result = calculate_features(table)
            for name in TYPE_FEATURES:
                table = table.append_column(name, result[name])
            check_counts(table)
            writer.write_table(table)
            csv_writer.write_table(table)
            sink = pa.BufferOutputStream()
            pacsv.write_csv(table, sink, write_options=pacsv.WriteOptions(include_header=False))
            expected_digest.update(sink.getvalue().to_pybytes())
            formats.update(table["formatid"].to_pylist())
            written += len(table)
            if written == len(table) or written % 100000 == 0 or written == rows:
                print(f"계산·저장: {written:,}/{rows:,}경기", flush=True)

    saved = pq.ParquetFile(parquet_path)
    if written != rows or saved.metadata.num_rows != rows or not saved.schema_arrow.equals(schema):
        raise ValueError("저장 행 수·스키마 불일치")
    sample_indices = {0, rows - 1} | set(random.Random(0).sample(range(rows), min(100, rows)))
    sampled_inputs = []
    offset, checked = 0, 0
    parquet_csv_digest = hashlib.sha256()
    for original_batch, saved_batch in zip(source.iter_batches(batch_size=args.batch_size),
                                           saved.iter_batches(batch_size=args.batch_size)):
        original, output = (pa.Table.from_batches([b]) for b in (original_batch, saved_batch))
        if not original.equals(output.select(INPUT_COLUMNS)):
            raise ValueError("기존 167열의 값·경기 순서가 변경됨")
        check_counts(output)
        local = [i - offset for i in sorted(sample_indices) if offset <= i < offset + len(output)]
        if local:
            inputs = original.take(local)
            sampled_inputs.append(inputs)
            for row, observed in zip(inputs.to_pylist(), output.take(local).to_pylist()):
                reference = compute_features(row)
                verify(row, reference)
                if any(observed[name] != reference[name] for name in TYPE_FEATURES):
                    raise ValueError(f"독립 타입 집계 불일치: {row['battle_id']}")
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
        "features": FEATURES + STAT_FEATURES + TYPE_FEATURES, "basic_features": FEATURES,
        "stat_features": STAT_FEATURES, "type_features": TYPE_FEATURES,
        "metadata": META, "target": "y", "columns_in_order": schema.names,
    })
    checks = {name: "passed" for name in (
        "all_original_167_columns_and_row_order_preserved", "all_type_count_ranges_and_differences",
        "all_single_and_dual_type_totals", "independent_sample_calculation",
        "slot_order_invariance", "team_swap_sign_check", "metadata_and_target_not_used",
        "full_csv_parquet_roundtrip", "source_file_unchanged")}
    write_json(info_dir / "quality_report.json", {
        "source": display_path(args.source), "source_sha256": source_hash,
        "output_rows": rows, "input_columns": len(INPUT_COLUMNS), "output_columns": len(schema),
        "basic_feature_count": len(FEATURES), "stat_feature_count": len(STAT_FEATURES),
        "type_feature_count": len(TYPE_FEATURES), "feature_count": len(FEATURES + STAT_FEATURES + TYPE_FEATURES),
        "metadata_count": len(META), "target": "y", "types": list(TYPES),
        "formats": dict(formats), "independently_checked_rows": checked, "sample_seed": 0,
        "csv_body_sha256": csv_hash, "checks": checks,
        "limitations": ["입력 데이터의 파싱·도감 정확성을 새로 검증하지 않음",
                        "방어 상성 피처 미포함", "데이터 분할·모델 학습·평가 미실시"],
    })
    links = {name: Path(relpath(ROOT / f"data/datasets/features_sample/info/{name}_definitions.json",
                               info_dir)).as_posix() for name in ("stat", "type")}
    (info_dir / "README.md").write_text(
        f"# 능력치·타입 구성 조합 피처 데이터셋\n\n입력: `{display_path(args.source)}`\n\n"
        f"{rows:,}경기 × {len(schema)}열. 기존 167열의 값·순서를 유지하고 타입 구성 51열을 뒤에 추가했다.\n\n"
        "`../data/all_stat_type_features.csv`와 `../data/all_stat_type_features.parquet`는 같은 표다.\n\n"
        "## 컬럼 구분\n\n"
        "- 기본 정보 108개 + 능력치 54개 + 타입 구성 51개 = 입력 후보 213개\n"
        "- 관리 정보 4개: battle_id, formatid, uploadtime, winner\n"
        "- 정답 1개: y (1은 p1 승리, 0은 p2 승리)\n\n"
        "winner와 y는 입력에 넣지 않는다. 관리 정보도 자동으로 학습에 포함하지 않는다. "
        "columns.json에서 basic_features, stat_features, type_features, features로 입력을 선택할 수 있다.\n\n"
        "## 타입 집계\n\n"
        "5세대 17개 타입 × (A팀 수·B팀 수·A − B) = 51개다. "
        "불꽃/비행 팀원은 불꽃과 비행에 각각 1을 더하고 단일 타입은 한 번만 센다. "
        "각 타입의 팀원 수는 0~6, 차이는 −6~6, 팀의 타입 수 합계는 6~12다. "
        "이 수는 방어 상성·공격 기술 범위·승률을 나타내지 않는다.\n\n"
        f"[타입 피처 정의]({links['type']})와 [능력치 피처 정의]({links['stat']})는 "
        "샘플의 정의 파일을 공유한다. 중복 정의 파일은 만들지 않는다.\n\n"
        "## 검증\n\n"
        "전체 경기의 기존 167열·순서, 타입 수 범위·차이·복수 타입 합계와 CSV·Parquet 전체 값 일치를 확인했다. "
        f"첫·마지막 경기와 고정 난수 표본 등 {checked}경기는 독립 집계와 대조했다. "
        "표본에서 슬롯 순서·팀 교환·관리 정보 및 정답 변경 검사도 통과했다. "
        "원본 해시와 검사 결과는 quality_report.json에 있다.\n\n"
        "## 다시 생성\n\n```bash\npython preprocessing/build_type_features.py\n```\n\n"
        "기존 출력이 있으면 중단한다. --output으로 새 폴더를 지정할 수 있다. "
        "데이터 분할·모델 학습·평가는 아직 진행하지 않았다.\n", encoding="utf-8")
    print(f"완료: {rows:,}경기 × {len(schema)}열; 검증 {len(checks)}개 통과", flush=True)
    print(f"결과표: {data_dir}\n설명·검증 자료: {info_dir}", flush=True)


if __name__ == "__main__":
    main()

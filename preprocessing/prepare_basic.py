"""7개 포맷의 종·종족값·타입 기본 표를 만든다.

설치: python -m pip install pyarrow
실행: python pokemon_2/prepare_basic.py

원본은 읽기만 한다. 출력: 통합 CSV/Parquet, 포맷별 Parquet,
제외 행 목록, 품질 보고서, 컬럼 설명. 인코딩·분할·조합 피처는 수행하지 않는다.
"""

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq


SOURCES = {
    "ubers": ["ubers"],
    "ou": ["ou_part1", "ou_part2", "ou_part3"],
    "uu": ["uu"], "ru": ["ru"], "nu": ["nu"], "pu": ["pu"], "zu": ["zu"],
}
FIELDS = ("species", "hp", "atk", "def", "spa", "spd", "spe", "type1", "type2")
FEATURES = [f"{side}_slot{k}_{field}"
            for side in ("p1", "p2") for k in range(1, 7) for field in FIELDS]
META = ["battle_id", "formatid", "uploadtime", "winner"]
COLUMNS = META + FEATURES + ["y"]
STAT_COLS = [name for name in FEATURES if name.rsplit("_", 1)[1] in FIELDS[1:7]]
SPECIES_COLS = [name for name in FEATURES if name.endswith("_species")]
TYPE1_COLS = [name for name in FEATURES if name.endswith("_type1")]
TYPE2_COLS = [name for name in FEATURES if name.endswith("_type2")]
TYPES = pa.array(["Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting",
                  "Poison", "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost",
                  "Dragon", "Dark", "Steel"])
SCHEMA = pa.schema([
    pa.field(name, pa.int64() if name in ("winner", "uploadtime") or name in STAT_COLS
             else pa.int8() if name == "y" else pa.string()) for name in COLUMNS
])


def blank(column):
    return pc.or_(pc.is_null(column), pc.fill_null(pc.equal(column, ""), False))


def any_of(conditions, length):
    result = pa.array([False] * length)
    for condition in conditions:
        result = pc.or_(result, condition)
    return result


def total(mask):
    return pc.sum(pc.cast(mask, pa.int64())).as_py() or 0


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=Path(__file__).resolve().parent.parent / "pokemon/data/original")
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).resolve().parent / "data/basic_all")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    # 1. 승자 조건을 만족하는 경기의 ID를 모든 파일에 걸쳐 확인한다.
    # 중복 ID는 한쪽을 임의로 선택하지 않고 모든 해당 행을 별도 보관한다.
    ids = Counter()
    manifests = []
    for group, names in SOURCES.items():
        for name in names:
            path = args.source / f"{name}.parquet"
            pf = pq.ParquetFile(path)
            missing_columns = set(META + FEATURES) - set(pf.schema_arrow.names)
            if missing_columns:
                raise ValueError(f"{path}: 필요한 컬럼 없음: {missing_columns}")
            for batch in pf.iter_batches(batch_size=20000, columns=["battle_id", "winner"]):
                t = pa.Table.from_batches([batch])
                valid = pc.fill_null(pc.is_in(t["winner"], value_set=pa.array([1, 2])), False)
                ids.update(t.filter(valid)["battle_id"].to_pylist())
            with path.open("rb") as source_file:
                digest = hashlib.file_digest(source_file, "sha256").hexdigest()
            manifests.append({"path": str(path.resolve()), "sha256": digest,
                              "rows": pf.metadata.num_rows,
                              "columns": len(pf.schema_arrow.names)})
    duplicate_ids = {key for key, count in ids.items() if count > 1}
    duplicate_values = pa.array(sorted(key for key in duplicate_ids if key is not None),
                                type=pa.string())
    del ids

    reports = []
    quarantine = []
    global_reasons = Counter()
    combined_path = args.output / "all_basic.parquet"
    csv_path = args.output / "all_basic.csv"
    csv_digest = hashlib.sha256()
    kept_ids = set()

    # 2. 필요한 컬럼만 나눠 읽고 모든 포맷에 같은 조건을 적용한다.
    with pq.ParquetWriter(combined_path, SCHEMA, compression="snappy") as combined, \
            pacsv.CSVWriter(csv_path, SCHEMA) as csv_writer:
        for group, names in SOURCES.items():
            report = {"formatid": f"gen5{group}", "source_rows": 0,
                      "winner_valid_rows": 0, "output_rows": 0,
                      "y_counts": Counter(), "exclusion_reasons": Counter(),
                      "missing_required_by_column": Counter(), "single_type_slots": 0,
                      "uploadtime_null_rows": 0}
            with pq.ParquetWriter(args.output / f"{group}_basic.parquet", SCHEMA,
                                  compression="snappy") as output:
                for name in names:
                    pf = pq.ParquetFile(args.source / f"{name}.parquet")
                    row_offset = 0
                    for batch in pf.iter_batches(batch_size=10000, columns=META + FEATURES):
                        t = pa.Table.from_batches([batch])
                        n = len(t)
                        report["source_rows"] += n
                        valid_winner = pc.fill_null(
                            pc.is_in(t["winner"], value_set=pa.array([1, 2])), False)
                        report["winner_valid_rows"] += total(valid_winner)
                        required_missing = {}
                        for column in SPECIES_COLS + TYPE1_COLS:
                            required_missing[column] = blank(t[column])
                        for column in STAT_COLS:
                            required_missing[column] = pc.is_null(t[column])
                        for column, mask in required_missing.items():
                            count = total(pc.and_(valid_winner, mask))
                            if count:
                                report["missing_required_by_column"][column] += count

                        invalid_stats = any_of([
                            pc.fill_null(pc.or_(pc.less_equal(t[column], 0),
                                                pc.or_(pc.greater(t[column], 255),
                                                       pc.invert(pc.is_finite(t[column])))), False)
                            for column in STAT_COLS], n)
                        invalid_types = any_of([
                            pc.and_(pc.invert(blank(t[column])),
                                    pc.invert(pc.is_in(t[column], value_set=TYPES)))
                            for column in TYPE1_COLS + TYPE2_COLS], n)
                        reasons = {
                            "winner_not_1_or_2": pc.invert(valid_winner),
                            "missing_battle_id": blank(t["battle_id"]),
                            "formatid_missing_or_unexpected": pc.invert(pc.fill_null(
                                pc.equal(t["formatid"], report["formatid"]), False)),
                            "duplicate_battle_id": pc.is_in(t["battle_id"],
                                                             value_set=duplicate_values),
                            "missing_required_feature": any_of(required_missing.values(), n),
                            "invalid_stat": invalid_stats,
                            "invalid_type": invalid_types,
                        }
                        # 제외 사유는 우선순위대로 하나만 기록해 건수 중복을 막는다.
                        remaining = pa.array([True] * n)
                        reason_for_row = {}
                        for reason, mask in reasons.items():
                            selected = pc.and_(remaining, mask)
                            count = total(selected)
                            if count:
                                report["exclusion_reasons"][reason] += count
                                global_reasons[reason] += count
                                for index in pc.indices_nonzero(selected).to_pylist():
                                    reason_for_row[index] = reason
                            remaining = pc.and_(remaining, pc.invert(mask))
                        for index, reason in sorted(reason_for_row.items()):
                            quarantine.append({"source_file": f"{name}.parquet",
                                               "source_row_zero_based": row_offset + index,
                                               "battle_id": t["battle_id"][index].as_py(),
                                               "formatid": t["formatid"][index].as_py(),
                                               "winner": t["winner"][index].as_py(),
                                               "reason": reason})
                        row_offset += n
                        clean = t.filter(remaining)
                        if not len(clean):
                            continue
                        y = pc.cast(pc.equal(clean["winner"], 1), pa.int8())
                        clean = clean.append_column("y", y).select(COLUMNS).cast(SCHEMA)
                        report["output_rows"] += len(clean)
                        report["uploadtime_null_rows"] += clean["uploadtime"].null_count
                        ones = total(pc.equal(y, 1))
                        report["y_counts"]["1"] += ones
                        report["y_counts"]["0"] += len(clean) - ones
                        report["single_type_slots"] += sum(total(blank(clean[c])) for c in TYPE2_COLS)
                        clean_ids = clean["battle_id"].to_pylist()
                        assert len(set(clean_ids)) == len(clean_ids)
                        assert not kept_ids.intersection(clean_ids)
                        kept_ids.update(clean_ids)
                        output.write_table(clean)
                        combined.write_table(clean)
                        csv_writer.write_table(clean)
                        sink = pa.BufferOutputStream()
                        pacsv.write_csv(clean, sink,
                                        write_options=pacsv.WriteOptions(include_header=False))
                        csv_digest.update(sink.getvalue().to_pybytes())
            reports.append(report)
            print(json.dumps(report, ensure_ascii=False), flush=True)

    # 3. Parquet를 다시 읽어 CSV 전체 값 및 행 수와 대조한다.
    expected_rows = sum(report["output_rows"] for report in reports)
    saved = pq.ParquetFile(combined_path)
    assert saved.metadata.num_rows == expected_rows
    assert saved.schema_arrow.equals(SCHEMA)
    assert len(kept_ids) == expected_rows
    expected_digest = csv_digest.hexdigest()
    with csv_path.open("rb") as f:
        f.readline()  # 헤더를 제외한 본문을 비교한다.
        assert hashlib.file_digest(f, "sha256").hexdigest() == expected_digest
    actual_digest = hashlib.sha256()
    for batch in saved.iter_batches(batch_size=10000):
        sink = pa.BufferOutputStream()
        pacsv.write_csv(batch, sink, write_options=pacsv.WriteOptions(include_header=False))
        actual_digest.update(sink.getvalue().to_pybytes())
    assert actual_digest.hexdigest() == expected_digest
    for group, report in zip(SOURCES, reports):
        part = pq.ParquetFile(args.output / f"{group}_basic.parquet")
        assert part.metadata.num_rows == report["output_rows"]
        assert part.schema_arrow.equals(SCHEMA)
    assert len(FEATURES) == 108 and len(COLUMNS) == 113
    assert not any("_move" in c or c.endswith(("_item", "_ability"))
                   or c.startswith("rating") for c in COLUMNS)

    with (args.output / "excluded_rows.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["source_file", "source_row_zero_based",
                                               "battle_id", "formatid", "winner", "reason"])
        writer.writeheader()
        writer.writerows(quarantine)
    report = {"sources": manifests, "source_rows": sum(r["source_rows"] for r in reports),
              "output_rows": expected_rows, "output_columns": len(COLUMNS),
              "feature_count": len(FEATURES), "feature_columns": FEATURES,
              "metadata_columns": META, "target": "y=1: p1 승리, y=0: p2 승리",
              "uploadtime_definition": "원본의 업로드 Unix 시각을 그대로 보존한 관리 정보. 자동으로 모델 입력에 포함하지 않음.",
              "exclusion_reasons": dict(global_reasons),
              "duplicate_ids_among_winner_valid_rows": sorted(duplicate_ids),
              "formats": reports, "roundtrip_verification": "passed",
              "csv_body_sha256": expected_digest,
              "limitations": ["type2 빈칸 유지", "범주형 인코딩 및 데이터 분할 미실시",
                              "조합 피처 미생성", "원본 파싱·도감 세대 정확성을 다시 검증한 작업은 아님"]}
    assert report["source_rows"] == expected_rows + len(quarantine)
    write_json(args.output / "quality_report.json", report)
    write_json(args.output / "columns.json", {"features": FEATURES, "metadata": META,
                                              "target": "y", "columns_in_order": COLUMNS})
    lines = ["# 7개 포맷 기본 데이터\n",
             "종·종족값·타입 108개와 경기 ID·포맷·업로드 시각·승자·정답을 담은 113열 표다.\n",
             f"총 {report['source_rows']:,}행 중 {expected_rows:,}행을 저장했다.\n",
             "| 포맷 | 원본 행 | 저장 행 | p1 승리 | p2 승리 |\n",
             "|---|---|---|---|---|\n"]
    for r in reports:
        lines.append(f"| {r['formatid']} | {r['source_rows']:,} | {r['output_rows']:,} | "
                     f"{r['y_counts'].get('1',0):,} | {r['y_counts'].get('0',0):,} |\n")
    lines += ["\n통합 파일은 `all_basic.parquet`, `all_basic.csv`다. 포맷별 파일은 "
              "`ubers_basic.parquet` 등이며, OU 3개 부분은 `ou_basic.parquet`로 합쳤다.\n",
              "\n`battle_id`, `formatid`, `uploadtime`, `winner`는 관리 정보이고 `y`는 정답이다. "
              "`winner`와 `y`를 모델 입력에 넣으면 안 된다. 포맷의 입력 사용 여부는 별도 결정한다.\n",
              "\n`uploadtime`은 원본의 업로드 Unix 시각을 그대로 보존했다. 시간순 분할·시기별 분포 확인에 "
              "사용할 수 있지만 경기 발생 시각과 동일하다고 가정하지 않는다. 모델 입력에는 자동으로 포함하지 않는다.\n",
              "\n`type2` 빈칸은 단일 타입일 수 있어 유지했다. 기술·아이템·특성·레이팅은 제거했다. "
              "숫자 인코딩·표준화·분할·조합 피처 생성은 아직 하지 않았다.\n",
              "\n## 제외 내역\n\n"]
    lines += [f"- `{reason}`: {count:,}행\n" for reason, count in global_reasons.items()]
    lines += ["\n제외 행의 원본 파일·행 위치·ID·이유는 `excluded_rows.csv`에 있다. "
              "원본 파일은 수정하지 않았다. 상세 집계와 원본 해시는 `quality_report.json`, "
              "컬럼 목록은 `columns.json`에 있다. 저장 후 통합 Parquet와 CSV의 전체 값을 "
              "직렬화 해시로 대조했고, 포맷별 행 수와 스키마도 확인했다.\n"]
    (args.output / "README.md").write_text("".join(lines), encoding="utf-8")
    print(f"완료: {expected_rows:,}행 × {len(COLUMNS)}열 / {args.output}", flush=True)


if __name__ == "__main__":
    main()

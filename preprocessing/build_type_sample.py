"""첫 경기의 타입별 팀원 수와 두 팀의 차이 51개를 계산하고 검증한다.

실행: python preprocessing/build_type_sample.py
기본 데이터와 기존 능력치 샘플은 수정하지 않는다. 전체 경기 적용은 하지 않는다.
"""

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from prepare_basic import META as BASIC_META, TYPES as BASIC_TYPES


TYPES = tuple(BASIC_TYPES.to_pylist())
META = (*BASIC_META, "y")
ROOT = Path(__file__).resolve().parent.parent


def feature_name(side, type_name):
    return f"{side}_type_{type_name.lower()}_count"


def feature_definitions():
    return [{"name": feature_name(side, type_name), "type": type_name,
             "formula": f"{side}에서 {type_name} 타입을 가진 팀원 수" if side != "diff" else
             f"{feature_name('p1', type_name)} - {feature_name('p2', type_name)}"}
            for side in ("p1", "p2", "diff") for type_name in TYPES]


def compute_features(row):
    """단일 타입은 한 번, 복수 타입은 각각의 타입에 한 번씩 집계한다."""
    result = {}
    for side in ("p1", "p2"):
        counts = Counter()
        for slot in range(1, 7):
            primary = row[f"{side}_slot{slot}_type1"]
            secondary = row[f"{side}_slot{slot}_type2"]
            if primary not in TYPES:
                raise ValueError(f"{side}/slot{slot}: 잘못된 첫 번째 타입 {primary!r}")
            if secondary not in (None, "") and secondary not in TYPES:
                raise ValueError(f"{side}/slot{slot}: 잘못된 두 번째 타입 {secondary!r}")
            if primary == secondary:
                raise ValueError(f"{side}/slot{slot}: 두 타입이 중복됨")
            counts[primary] += 1
            if secondary not in (None, ""):
                counts[secondary] += 1
        result.update({feature_name(side, t): counts[t] for t in TYPES})
    result.update({feature_name("diff", t): result[feature_name("p1", t)]
                   - result[feature_name("p2", t)] for t in TYPES})
    return result


def verify(row, result):
    for side in ("p1", "p2"):
        # Counter를 쓰지 않고 타입별로 6개 슬롯의 포함 여부를 독립 계산한다.
        for t in TYPES:
            expected = sum(t in {row[f"{side}_slot{k}_type1"],
                                 row[f"{side}_slot{k}_type2"]} for k in range(1, 7))
            assert result[feature_name(side, t)] == expected
            assert 0 <= result[feature_name(side, t)] <= 6
        expected_total = 6 + sum(row[f"{side}_slot{k}_type2"] not in (None, "")
                                 for k in range(1, 7))
        assert sum(result[feature_name(side, t)] for t in TYPES) == expected_total
    for t in TYPES:
        assert result[feature_name("diff", t)] == (
            result[feature_name("p1", t)] - result[feature_name("p2", t)])
        assert -6 <= result[feature_name("diff", t)] <= 6

    reversed_row, swapped_row = dict(row), dict(row)
    single_row, blank_row = dict(row), dict(row)
    for side, opposite in (("p1", "p2"), ("p2", "p1")):
        for k in range(1, 7):
            for field in ("type1", "type2"):
                key = f"{side}_slot{k}_{field}"
                reversed_row[key] = row[f"{side}_slot{7-k}_{field}"]
                swapped_row[key] = row[f"{opposite}_slot{k}_{field}"]
            single_row[f"{side}_slot{k}_type2"] = None
            blank_row[f"{side}_slot{k}_type2"] = ""
    assert compute_features(reversed_row) == result
    swapped = compute_features(swapped_row)
    for t in TYPES:
        assert swapped[feature_name("p1", t)] == result[feature_name("p2", t)]
        assert swapped[feature_name("p2", t)] == result[feature_name("p1", t)]
        assert swapped[feature_name("diff", t)] == -result[feature_name("diff", t)]
    single = compute_features(single_row)
    assert single == compute_features(blank_row)
    for side in ("p1", "p2"):
        assert sum(single[feature_name(side, t)] for t in TYPES) == 6
        for t in TYPES:
            assert single[feature_name(side, t)] == sum(
                row[f"{side}_slot{k}_type1"] == t for k in range(1, 7))
    changed = dict(row)
    for name in META:
        changed[name] = None
    assert compute_features(changed) == result
    return {name: "passed" for name in (
        "independent_type_counts", "dual_type_totals", "count_and_difference_ranges",
        "single_type_null_and_empty_handling", "slot_order_invariance",
        "team_swap_sign_check", "metadata_and_target_not_used")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path,
                        default=ROOT / "data/datasets/basic/data/all_basic.parquet")
    parser.add_argument("--output", type=Path, default=ROOT / "data/datasets/features_sample",
                        help="결과표는 data/, 설명·검증 자료는 info/에 저장")
    args = parser.parse_args()
    source = pq.ParquetFile(args.source)
    if not source.metadata.num_rows:
        parser.error("입력 데이터에 경기가 없습니다.")
    data_dir, info_dir = args.output / "data", args.output / "info"
    paths = [data_dir / "type_sample.csv", data_dir / "type_sample.parquet"] + [
        info_dir / n for n in ("type_definitions.json", "type_example.md", "type_checks.json")]
    if any(p.exists() for p in paths):
        parser.error("타입 샘플 출력이 이미 있습니다. --output으로 다른 폴더를 지정하세요.")
    with args.source.open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    row = next(source.iter_batches(batch_size=1)).to_pylist()[0]
    result = compute_features(row)
    definitions = feature_definitions()
    assert len(TYPES) == 17 and len(result) == 51
    checks = verify(row, result)
    output = {name: row[name] for name in META} | result
    schema = pa.schema([
        pa.field(name, pa.string() if name in ("battle_id", "formatid") else pa.int64())
        for name in META] + [pa.field(d["name"], pa.int8()) for d in definitions])
    table = pa.Table.from_pylist([output], schema=schema)
    data_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, data_dir / "type_sample.parquet")
    with (data_dir / "type_sample.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output))
        writer.writeheader()
        writer.writerow(output)
    assert pq.read_table(data_dir / "type_sample.parquet").equals(table)
    with (data_dir / "type_sample.csv").open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == list(output)
        exported = list(reader)
    assert len(exported) == 1 and all(exported[0][k] == str(v) for k, v in output.items())
    checks["parquet_and_csv_roundtrip"] = "passed"
    with args.source.open("rb") as stream:
        assert hashlib.file_digest(stream, "sha256").hexdigest() == source_hash
    checks["source_file_unchanged"] = "passed"
    try:
        source_path = args.source.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        source_path = str(args.source.resolve())
    report = {"source": source_path, "source_sha256": source_hash,
              "battle_id": row["battle_id"], "sample_rows": 1, "types": list(TYPES),
              "feature_count": 51, "metadata_and_target_count": 5, "output_columns": 56,
              "team_type_totals": {s: sum(result[feature_name(s, t)] for t in TYPES)
                                   for s in ("p1", "p2")}, "checks": checks}
    for name, value in [("type_definitions.json", definitions), ("type_checks.json", report)]:
        (info_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    lines = ["# 첫 경기의 타입 구성 계산 예시\n\n",
             f"경기 ID: `{row['battle_id']}` / 포맷: `{row['formatid']}`\n\n",
             "전체 경기 적용 전, 기본 데이터의 첫 경기 한 판만 계산했다. "
             "타입별 팀원 수 17개 × (A팀·B팀·두 팀 차이) = 51개다. "
             "관리 정보·정답 5개를 함께 저장해 결과표는 1행 × 56열이다.\n\n",
             "## 실제 입력 팀\n\n",
             "| 팀 | 슬롯 | 포켓몬 | 타입 1 | 타입 2 |\n",
             "|---|---|---|---|---|\n"]
    for side in ("p1", "p2"):
        for k in range(1, 7):
            lines.append(f"| {side} | {k} | {row[f'{side}_slot{k}_species']} | "
                         f"{row[f'{side}_slot{k}_type1']} | "
                         f"{row[f'{side}_slot{k}_type2'] or '없음'} |\n")
    lines += ["\n## 계산한 팀원 수\n\n",
              "| 타입 | A팀(p1) | B팀(p2) | A − B |\n",
              "|---|---|---|---|\n"]
    for t in TYPES:
        lines.append(f"| {t} | {result[feature_name('p1', t)]} | "
                     f"{result[feature_name('p2', t)]} | {result[feature_name('diff', t)]} |\n")
    lines += ["\n## 세는 방법\n\n",
              "불꽃/비행 포켓몬 한 마리는 불꽃에 1, 비행에 1을 더한다. "
              "단일 타입 포켓몬은 한 번만 센다. 복수 타입 때문에 타입 수의 합은 6보다 클 수 있다.\n\n",
              f"이 경기의 타입 수 합계는 A팀 {report['team_type_totals']['p1']}, "
              f"B팀 {report['team_type_totals']['p2']}다. 팀원은 각각 6마리다.\n\n",
              "## 파일과 범위\n\n",
              "- [결과 CSV](../data/type_sample.csv) / [결과 Parquet](../data/type_sample.parquet)\n",
              "- [51개 피처의 정의](type_definitions.json)\n",
              "- [검증 결과](type_checks.json)\n\n",
              "5세대의 17개 타입만 사용한다. 이 수는 팀의 타입 구성이며 공격 기술·방어 상성·승률은 아니다. "
              "기존 능력치 피처와 결합하거나 전체 경기에 적용하지 않았다. "
              "winner와 y는 결과표에 보존하지만 피처 계산에는 사용하지 않는다.\n\n",
              "## 검사\n\n"]
    lines += [f"- {name}: {value}\n" for name, value in checks.items()]
    (info_dir / "type_example.md").write_text("".join(lines), encoding="utf-8")
    print(f"완료: 첫 경기 1행 × 56열 (타입 구성 피처 51개)")
    print(f"결과표: {data_dir}/type_sample.*\n설명·검증 자료: {info_dir}/type_*")


if __name__ == "__main__":
    main()

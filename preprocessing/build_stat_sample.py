"""기본 표의 첫 경기에서 능력치 요약 피처 54개를 계산한다.

준비: python -m pip install pyarrow
실행: python preprocessing/build_stat_sample.py
원본 기본 표는 수정하지 않는다. 전체 경기 적용 코드는 build_stat_features.py다.
"""

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq


STATS = ("hp", "atk", "def", "spa", "spd", "spe")
SUMMARY = ("mean", "max", "std")
META = ("battle_id", "formatid", "uploadtime", "winner", "y")


def feature_definitions():
    """샘플과 전체 데이터에서 사용하는 동일한 54개 피처 정의."""
    formulas = {"mean": "sum(x1..x6) / 6", "max": "max(x1..x6)",
                "std": "sqrt(sum((xi - mean)^2) / 6)"}
    return [{"name": f"{side}_{stat}_{summary}", "stat": stat, "summary": summary,
             "formula": formulas[summary] if side != "diff" else
             f"p1_{stat}_{summary} - p2_{stat}_{summary}"}
            for side in ("p1", "p2", "diff") for stat in STATS for summary in SUMMARY]


def compute_features(row):
    """입력의 종족값만 사용한다. std는 모집단 표준편차이며 분모는 6이다."""
    result = {}
    for side in ("p1", "p2"):
        for stat in STATS:
            values = [row[f"{side}_slot{k}_{stat}"] for k in range(1, 7)]
            if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0
                   for v in values):
                raise ValueError(f"{row.get('battle_id')}: {side}/{stat}에 잘못된 값")
            mean = math.fsum(values) / 6
            result[f"{side}_{stat}_mean"] = mean
            result[f"{side}_{stat}_max"] = float(max(values))
            result[f"{side}_{stat}_std"] = math.sqrt(
                math.fsum((v - mean) ** 2 for v in values) / 6)
    for stat in STATS:
        for summary in SUMMARY:
            result[f"diff_{stat}_{summary}"] = (
                result[f"p1_{stat}_{summary}"] - result[f"p2_{stat}_{summary}"])
    return result


def verify(row, result):
    """별도 계산과 팀원 순서·팀 교환 검사를 수행한다."""
    for side in ("p1", "p2"):
        for stat in STATS:
            values = [row[f"{side}_slot{k}_{stat}"] for k in range(1, 7)]
            expected = {"mean": statistics.mean(values), "max": max(values),
                        "std": statistics.pstdev(values)}
            for summary, value in expected.items():
                assert math.isclose(result[f"{side}_{stat}_{summary}"], value,
                                    rel_tol=1e-12, abs_tol=1e-12)
    reversed_row = dict(row)
    swapped_row = dict(row)
    for side, opposite in (("p1", "p2"), ("p2", "p1")):
        for k in range(1, 7):
            for stat in STATS:
                reversed_row[f"{side}_slot{k}_{stat}"] = row[f"{side}_slot{7-k}_{stat}"]
                swapped_row[f"{side}_slot{k}_{stat}"] = row[f"{opposite}_slot{k}_{stat}"]
    reversed_result = compute_features(reversed_row)
    swapped = compute_features(swapped_row)
    for name, value in result.items():
        assert math.isclose(reversed_result[name], value, abs_tol=1e-12)
        if name.startswith("diff_"):
            assert math.isclose(swapped[name], -value, abs_tol=1e-12)
        elif name.startswith("p1_"):
            assert math.isclose(swapped[name.replace("p1_", "p2_", 1)], value, abs_tol=1e-12)
    changed_meta = dict(row, y=1-row["y"], winner=3-row["winner"], uploadtime=0)
    assert compute_features(changed_meta) == result
    return {"independent_statistics_check": "passed", "slot_order_invariance": "passed",
            "team_swap_sign_check": "passed", "metadata_not_used_as_features": "passed"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent.parent
    parser.add_argument("--source", type=Path, default=root / "data/datasets/basic/data/all_basic.parquet")
    parser.add_argument("--output", type=Path, default=root / "data/datasets/features_sample",
                        help="샘플 저장 폴더. 결과표는 data/, 설명·검증 자료는 info/에 저장")
    args = parser.parse_args()
    row = next(pq.ParquetFile(args.source).iter_batches(batch_size=1)).to_pylist()[0]
    features = compute_features(row)
    assert len(features) == 54
    checks = verify(row, features)
    output_row = {name: row[name] for name in META} | features
    output_schema = pa.schema([
        pa.field(name, pa.string() if name in ("battle_id", "formatid") else pa.int64())
        for name in META] + [pa.field(name, pa.float64()) for name in features])
    data_dir = args.output / "data"
    info_dir = args.output / "info"
    data_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([output_row], schema=output_schema)
    pq.write_table(table, data_dir / "stat_sample.parquet")
    with (data_dir / "stat_sample.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(output_row))
        writer.writeheader()
        writer.writerow(output_row)
    assert pq.read_table(data_dir / "stat_sample.parquet").equals(table)
    with (data_dir / "stat_sample.csv").open(encoding="utf-8-sig", newline="") as f:
        exported = next(csv.DictReader(f))
    assert all(exported[k] == str(v) for k, v in output_row.items())
    checks["parquet_and_csv_roundtrip"] = "passed"

    definitions = feature_definitions()
    (info_dir / "stat_definitions.json").write_text(
        json.dumps(definitions, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    (info_dir / "checks.json").write_text(json.dumps({
        "source": str(args.source.resolve()), "battle_id": row["battle_id"],
        "sample_rows": 1, "feature_count": 54, "metadata_and_target_count": 5,
        "output_columns": 59, "standard_deviation_ddof": 0, "checks": checks,
    }, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    lines = ["# 능력치 요약 피처의 첫 경기 계산 예시\n\n",
             f"경기 ID: `{row['battle_id']}` / 포맷: `{row['formatid']}`\n\n",
             "전체 822,419경기에 적용한 결과가 아니라 첫 경기 한 판의 샘플이다. "
             "54개 피처와 관리 정보·정답 5개를 담은 59열 표를 저장했다.\n\n",
             "## 입력 종족값\n\n",
             "| 팀 | 슬롯 | 종 | HP | Atk | Def | SpA | SpD | Spe |\n",
             "|---|---|---|---|---|---|---|---|---|\n"]
    for side in ("p1", "p2"):
        for k in range(1, 7):
            values = [side, k, row[f"{side}_slot{k}_species"]] + [row[f"{side}_slot{k}_{stat}"] for stat in STATS]
            lines.append("| " + " | ".join(str(v) for v in values)+" |\n")
    lines.extend(["\n## 계산 결과\n\n",
                  "표시값만 소수점 넷째 자리로 반올림했다. CSV·Parquet에는 반올림 전 값을 저장했다.\n\n",
                  "| 능력치 | 요약 | p1 | p2 | 차이 p1 − p2 |\n",
                  "|---|---|---|---|---|\n"])
    for stat in STATS:
        for summary in SUMMARY:
            values = [features[f"{side}_{stat}_{summary}"] for side in ("p1", "p2", "diff")]
            lines.append(f"| {stat} | {summary} | "+" | ".join(f"{v:.4f}" for v in values)+" |\n")
    speeds = [row[f"p1_slot{k}_spe"] for k in range(1, 7)]
    lines.extend(["\n## 스피드 평균을 직접 확인하기\n\n",
                  f"p1 스피드 종족값은 `{speeds}`다. 합계 {sum(speeds)}를 6으로 나누면 "
                  f"`p1_spe_mean = {features['p1_spe_mean']}`이 된다.\n\n",
                  "표준편차는 한 팀의 6마리 전체를 대상으로 계산하므로 분모를 6으로 둔다. "
                  "입력 스케일을 바꾸는 표준화와는 다른 계산이다. 실제 능력치·행동 순서·피해량을 뜻하지 않는다.\n\n",
                  "## 검사\n\n"])
    lines += [f"- {key}: {value}\n" for key, value in checks.items()]
    (info_dir / "example.md").write_text("".join(lines), encoding="utf-8")
    print(json.dumps({"battle_id": row["battle_id"], "p1_spe_mean": features["p1_spe_mean"],
                      "p2_spe_mean": features["p2_spe_mean"], "diff_spe_mean": features["diff_spe_mean"],
                      "features": len(features), "checks": checks}, ensure_ascii=False, indent=2))
    print("결과표:", data_dir)
    print("설명·검증 자료:", info_dir)


if __name__ == "__main__":
    main()

"""첫 경기의 방어 상성 피처 153개(공격 타입 17 × 약점·저항·무효 × A·B·차이)를 계산하고 검증한다.

실행: python -m preprocessing.features.build_matchup_sample
포켓몬마다 공격 타입별로 받는 배율을 상성표에서 찾고, 복수 타입이면 두 배율을 먼저 곱한 뒤 분류한다.
특성·아이템·기술 고유 효과·경기 상태는 제외한다. 기본 데이터와 기존 샘플은 수정하지 않으며
전체 경기 적용은 하지 않는다.
"""

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from preprocessing.features.build_type_sample import META, ROOT, TYPES


CHART_PATH = ROOT / "data/external/gen5_typechart.csv"
CHART_INFO_PATH = ROOT / "data/external/gen5_typechart_info.json"
CATEGORIES = ("weak", "resist", "immune")
CATEGORY_KO = {"weak": "약점", "resist": "저항", "immune": "무효", "neutral": "보통"}
SIDES = ("p1", "p2", "diff")


def load_chart(path=CHART_PATH, info_path=CHART_INFO_PATH):
    """상성표를 읽고 해시·축·값 범위를 확인한다. chart[공격][방어] = 배율."""
    info = json.loads(info_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != info["csv_sha256"]:
        raise ValueError(f"상성표 해시 불일치: {digest} != {info['csv_sha256']}")
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["attack_type", *TYPES]:
            raise ValueError(f"상성표 열 순서가 다름: {reader.fieldnames}")
        chart = {r["attack_type"]: {d: float(r[d]) for d in TYPES} for r in reader}
    if list(chart) != list(TYPES):
        raise ValueError(f"상성표 행 순서가 다름: {list(chart)}")
    allowed = set(info["allowed_single_type_multipliers"])
    if any(v not in allowed for row in chart.values() for v in row.values()):
        raise ValueError("상성표에 허용되지 않은 배율이 있음")
    return chart, digest, info


def feature_name(side, attack, category):
    return f"{side}_def_{attack.lower()}_{category}_count"


def feature_definitions():
    rule = {"weak": "최종 배율 2 또는 4", "resist": "최종 배율 0.5 또는 0.25",
            "immune": "최종 배율 0"}
    return [{"name": feature_name(side, attack, c), "attack_type": attack, "category": c,
             "formula": (f"{feature_name('p1', attack, c)} - {feature_name('p2', attack, c)}"
                         if side == "diff" else
                         f"{side} 팀원 중 {attack} 공격을 받을 때 {rule[c]}인 수 "
                         "(복수 타입은 두 배율을 곱한 뒤 분류)")}
            for side in SIDES for attack in TYPES for c in CATEGORIES]


def team_types(row, side):
    """슬롯별 (첫 타입, 두 번째 타입 또는 None)을 검증해 돌려준다."""
    result = []
    for slot in range(1, 7):
        primary = row[f"{side}_slot{slot}_type1"]
        secondary = row[f"{side}_slot{slot}_type2"] or None
        if primary not in TYPES:
            raise ValueError(f"{side}/slot{slot}: 잘못된 첫 번째 타입 {primary!r}")
        if secondary is not None and secondary not in TYPES:
            raise ValueError(f"{side}/slot{slot}: 잘못된 두 번째 타입 {secondary!r}")
        if primary == secondary:
            raise ValueError(f"{side}/slot{slot}: 두 타입이 중복됨")
        result.append((primary, secondary))
    return result


def multiplier(chart, attack, types):
    value = 1.0
    for t in types:
        if t is not None:
            value *= chart[attack][t]
    return value


def classify(value):
    if value == 0:
        return "immune"
    if value >= 2:
        return "weak"
    if value < 1:
        return "resist"
    if value == 1:
        return "neutral"
    raise ValueError(f"분류할 수 없는 배율: {value}")


def compute_features(row, chart):
    result = {}
    for side in ("p1", "p2"):
        members = team_types(row, side)
        for attack in TYPES:
            labels = [classify(multiplier(chart, attack, m)) for m in members]
            result.update({feature_name(side, attack, c): labels.count(c) for c in CATEGORIES})
    for attack in TYPES:
        for c in CATEGORIES:
            result[feature_name("diff", attack, c)] = (
                result[feature_name("p1", attack, c)] - result[feature_name("p2", attack, c)])
    return result


def independent_label(chart, attack, primary, secondary):
    """곱셈 대신 무효 여부와 log2 지수의 합으로 분류해 본 계산과 대조한다."""
    values = [chart[attack][t] for t in (primary, secondary) if t]
    if any(v == 0 for v in values):
        return "immune"
    exponent = sum(round(math.log2(v)) for v in values)
    return "weak" if exponent > 0 else "resist" if exponent < 0 else "neutral"


def verify(row, result, chart, info):
    checks = {}
    for ex in info["examples"]:
        defense = (ex["defense"] + [None])[:2]
        assert multiplier(chart, ex["attack"], defense) == ex["expected"], ex
    assert multiplier(chart, "Fire", ("Water", "Grass")) == 1  # 0.5 × 2
    assert classify(multiplier(chart, "Fire", ("Water", "Grass"))) == "neutral"
    assert classify(multiplier(chart, "Electric", ("Water", "Ground"))) == "immune"  # 2 × 0
    assert classify(multiplier(chart, "Rock", ("Fire", "Flying"))) == "weak"  # 4배
    assert classify(multiplier(chart, "Water", ("Water", "Dragon"))) == "resist"  # 0.25배
    checks["chart_examples_and_multiply_before_classify"] = "passed"

    # 모든 단일·복수 방어 조합에서 곱셈 분류와 지수 분류가 일치하는지 확인
    for attack in TYPES:
        for i, a in enumerate(TYPES):
            for b in (None, *TYPES[i + 1:]):
                assert classify(multiplier(chart, attack, (a, b))) == \
                    independent_label(chart, attack, a, b)
    checks["all_type_combinations_independent_classification"] = "passed"

    for side in ("p1", "p2"):
        members = team_types(row, side)
        for attack in TYPES:
            labels = [independent_label(chart, attack, *m) for m in members]
            for c in CATEGORIES:
                assert result[feature_name(side, attack, c)] == labels.count(c)
            assert sum(result[feature_name(side, attack, c)] for c in CATEGORIES) \
                + labels.count("neutral") == 6
    checks["independent_team_counts"] = "passed"
    for attack in TYPES:
        for c in CATEGORIES:
            a, b = result[feature_name("p1", attack, c)], result[feature_name("p2", attack, c)]
            assert 0 <= a <= 6 and 0 <= b <= 6
            assert result[feature_name("diff", attack, c)] == a - b
    checks["count_and_difference_ranges"] = "passed"

    reversed_row, swapped_row, single_row, blank_row = (dict(row) for _ in range(4))
    for side, opposite in (("p1", "p2"), ("p2", "p1")):
        for k in range(1, 7):
            for field in ("type1", "type2"):
                key = f"{side}_slot{k}_{field}"
                reversed_row[key] = row[f"{side}_slot{7-k}_{field}"]
                swapped_row[key] = row[f"{opposite}_slot{k}_{field}"]
            single_row[f"{side}_slot{k}_type2"] = None
            blank_row[f"{side}_slot{k}_type2"] = ""
    assert compute_features(reversed_row, chart) == result
    checks["slot_order_invariance"] = "passed"
    swapped = compute_features(swapped_row, chart)
    for attack in TYPES:
        for c in CATEGORIES:
            assert swapped[feature_name("p1", attack, c)] == result[feature_name("p2", attack, c)]
            assert swapped[feature_name("diff", attack, c)] == \
                -result[feature_name("diff", attack, c)]
    checks["team_swap_sign_check"] = "passed"
    single = compute_features(single_row, chart)
    assert single == compute_features(blank_row, chart)
    for side in ("p1", "p2"):
        for attack in TYPES:
            labels = [classify(chart[attack][row[f"{side}_slot{k}_type1"]]) for k in range(1, 7)]
            for c in CATEGORIES:
                assert single[feature_name(side, attack, c)] == labels.count(c)
    checks["single_type_null_and_empty_handling"] = "passed"
    changed = dict(row)
    for name in META:
        changed[name] = None
    assert compute_features(changed, chart) == result
    checks["metadata_and_target_not_used"] = "passed"
    return checks


def member_rows(row, chart):
    """포켓몬 × 공격 타입별 배율 상세. 예시 문서와 검증 자료에 쓴다."""
    details = []
    for side in ("p1", "p2"):
        for slot, (primary, secondary) in enumerate(team_types(row, side), start=1):
            for attack in TYPES:
                first = chart[attack][primary]
                second = chart[attack][secondary] if secondary else None
                final = multiplier(chart, attack, (primary, secondary))
                details.append({"side": side, "slot": slot,
                                "species": row[f"{side}_slot{slot}_species"],
                                "type1": primary, "type2": secondary, "attack_type": attack,
                                "type1_multiplier": first, "type2_multiplier": second,
                                "final_multiplier": final, "category": classify(final)})
    return details


def fmt(value):
    if value is None:
        return "—"
    return f"{value:g}"


def write_example(path, row, result, details, checks, chart_digest):
    lines = ["# 첫 경기의 방어 상성 계산 예시\n\n",
             f"경기 ID: `{row['battle_id']}` / 포맷: `{row['formatid']}`\n\n",
             "기본 데이터의 첫 경기 한 판만 계산했다. 공격 타입 17개 × (약점·저항·무효) × "
             "(A팀·B팀·차이) = 153개 피처다. 관리 정보·정답 5개를 함께 저장해 결과표는 1행 × 158열이다. "
             "특성·아이템 효과는 제외했다.\n\n",
             "## 계산 순서\n\n",
             "1. 각 포켓몬의 타입을 읽는다.\n",
             "2. `gen5_typechart.csv`에서 공격 타입(행) × 방어 타입(열)의 배율을 찾는다. "
             "복수 타입이면 두 값을 곱한다.\n",
             "3. **곱한 뒤의 최종 배율**로 분류한다: 2·4배 = 약점, 0.5·0.25배 = 저항, 0배 = 무효, "
             "1배 = 어느 쪽에도 세지 않음.\n",
             "4. 팀별로 분류마다 포켓몬 수를 세고, 차이는 A팀 − B팀이다.\n\n",
             f"상성표 SHA-256: `{chart_digest}`\n\n",
             "## 실제 입력 팀\n\n",
             "| 팀 | 슬롯 | 포켓몬 | 타입 1 | 타입 2 |\n|---|---|---|---|---|\n"]
    seen = set()
    for d in details:
        if (d["side"], d["slot"]) not in seen:
            seen.add((d["side"], d["slot"]))
            lines.append(f"| {d['side']} | {d['slot']} | {d['species']} | {d['type1']} | "
                         f"{d['type2'] or '없음'} |\n")

    lines += ["\n## 예: 바위 공격을 받을 때\n\n",
              "| 팀 | 포켓몬 | 타입 | 타입 1 배율 | 타입 2 배율 | 최종 배율 | 분류 |\n",
              "|---|---|---|---|---|---|---|\n"]
    for d in details:
        if d["attack_type"] == "Rock":
            types = d["type1"] + (f"/{d['type2']}" if d["type2"] else "")
            lines.append(f"| {d['side']} | {d['species']} | {types} | {fmt(d['type1_multiplier'])} | "
                         f"{fmt(d['type2_multiplier'])} | **{fmt(d['final_multiplier'])}** | "
                         f"{CATEGORY_KO[d['category']]} |\n")
    rock = {c: (result[feature_name('p1', 'Rock', c)], result[feature_name('p2', 'Rock', c)],
                result[feature_name('diff', 'Rock', c)]) for c in CATEGORIES}
    lines.append("\n" + " / ".join(
        f"{CATEGORY_KO[c]} A {a}·B {b}·차이 {d:+d}" for c, (a, b, d) in rock.items()) + "\n\n")

    cancel = [d for d in details if d["type2"] and d["final_multiplier"] == 1
              and d["type1_multiplier"] != 1]
    lines += ["## 두 배율이 상쇄되어 1배가 된 경우\n\n"]
    if cancel:
        lines += ["한 타입은 약점, 다른 타입은 저항이라 최종 1배가 되어 어느 쪽에도 세지 않은 경우다.\n\n",
                  "| 팀 | 포켓몬 | 공격 타입 | 계산 |\n|---|---|---|---|\n"]
        lines += [f"| {d['side']} | {d['species']} | {d['attack_type']} | "
                  f"{fmt(d['type1_multiplier'])} × {fmt(d['type2_multiplier'])} = 1 |\n"
                  for d in cancel]
    else:
        lines.append("이 경기에는 해당 사례가 없다.\n")
    four = [d for d in details if d["final_multiplier"] in (4, 0.25)]
    lines +=["\n4배·0.25배(두 타입 모두 같은 방향)는 각각 약점·저항으로 한 번만 센다. "
              f"이 경기에서 4배 {sum(d['final_multiplier'] == 4 for d in four)}건, "
              f"0.25배 {sum(d['final_multiplier'] == 0.25 for d in four)}건이다. "
              "한 타입이라도 0배면 최종 0배(무효)다.\n\n"]

    lines += ["## 포켓몬별 최종 배율 (행: 포켓몬, 열: 공격 타입)\n\n",
              "| 팀 | 포켓몬 | " + " | ".join(t[:3] for t in TYPES) + " |\n",
              "|---|---|" + "---|" * len(TYPES) + "\n"]
    for side, slot in sorted(seen):
        cells = {d["attack_type"]: d for d in details if (d["side"], d["slot"]) == (side, slot)}
        species = cells[TYPES[0]]["species"]
        lines.append(f"| {side} | {species} | " + " | ".join(
            fmt(cells[t]["final_multiplier"]) for t in TYPES) + " |\n")
    lines.append("\n열 이름은 공격 타입의 앞 세 글자다. 2 이상은 약점, 1 미만·0 초과는 저항, 0은 무효다.\n\n")

    lines += ["## 집계 결과 153개\n\n",
              "| 공격 타입 | A 약점 | A 저항 | A 무효 | B 약점 | B 저항 | B 무효 | "
              "차이 약점 | 차이 저항 | 차이 무효 |\n",
              "|---|---|---|---|---|---|---|---|---|---|\n"]
    for attack in TYPES:
        values = [result[feature_name(s, attack, c)] for s in SIDES for c in CATEGORIES]
        lines.append(f"| {attack} | " + " | ".join(
            f"{v:+d}" if i >= 6 else str(v) for i, v in enumerate(values)) + " |\n")
    lines += ["\n## 파일과 범위\n\n",
              "- [결과 CSV](../data/matchup_sample.csv) / [결과 Parquet](../data/matchup_sample.parquet)\n",
              "- [153개 피처의 정의](matchup_definitions.json)\n",
              "- [포켓몬 × 공격 타입 204건의 배율 상세](matchup_members.json)\n",
              "- [검증 결과](matchup_checks.json)\n\n",
              "타입 상성만 사용한다. 특성(예: 부유)·아이템(예: 풍선)·기술 고유 효과·날씨는 반영하지 않으며 "
              "실제 피해량·공격 기술 범위도 아니다. 기존 피처와 결합하거나 전체 경기에 적용하지 않았다. "
              "winner와 y는 결과표에 보존하지만 계산에는 사용하지 않는다.\n\n",
              "## 검사\n\n"]
    lines += [f"- {name}: {value}\n" for name, value in checks.items()]
    path.write_text("".join(lines), encoding="utf-8")


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
    paths = [data_dir / "matchup_sample.csv", data_dir / "matchup_sample.parquet"] + [
        info_dir / n for n in ("matchup_definitions.json", "matchup_members.json",
                               "matchup_example.md", "matchup_checks.json")]
    if any(p.exists() for p in paths):
        parser.error("방어 상성 샘플 출력이 이미 있습니다. --output으로 다른 폴더를 지정하세요.")
    chart, chart_digest, chart_info = load_chart()
    with args.source.open("rb") as stream:
        source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    row = next(source.iter_batches(batch_size=1)).to_pylist()[0]
    result = compute_features(row, chart)
    definitions = feature_definitions()
    assert len(TYPES) == 17 and len(result) == len(definitions) == 153
    assert set(result) == {d["name"] for d in definitions}
    result = {d["name"]: result[d["name"]] for d in definitions}
    checks = {"chart_sha256_matches_info": "passed"} | verify(row, result, chart, chart_info)
    details = member_rows(row, chart)
    assert len(details) == 12 * 17

    output = {name: row[name] for name in META} | result
    schema = pa.schema([
        pa.field(name, pa.string() if name in ("battle_id", "formatid") else pa.int64())
        for name in META] + [pa.field(d["name"], pa.int8()) for d in definitions])
    table = pa.Table.from_pylist([output], schema=schema)
    data_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, data_dir / "matchup_sample.parquet")
    with (data_dir / "matchup_sample.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output))
        writer.writeheader()
        writer.writerow(output)
    assert pq.read_table(data_dir / "matchup_sample.parquet").equals(table)
    with (data_dir / "matchup_sample.csv").open(encoding="utf-8-sig", newline="") as stream:
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
              "typechart": CHART_PATH.relative_to(ROOT).as_posix(),
              "typechart_sha256": chart_digest, "battle_id": row["battle_id"],
              "sample_rows": 1, "attack_types": list(TYPES),
              "categories": {"weak": "최종 배율 2·4", "resist": "최종 배율 0.5·0.25",
                             "immune": "최종 배율 0", "neutral(세지 않음)": "최종 배율 1"},
              "feature_count": 153, "metadata_and_target_count": 5, "output_columns": 158,
              "member_attack_pairs": len(details),
              "category_totals": {side: {c: sum(d["category"] == c for d in details
                                                if d["side"] == side)
                                         for c in (*CATEGORIES, "neutral")}
                                  for side in ("p1", "p2")},
              "excludes": chart_info["excludes"], "checks": checks}
    for name, value in [("matchup_definitions.json", definitions),
                        ("matchup_members.json", details), ("matchup_checks.json", report)]:
        (info_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    write_example(info_dir / "matchup_example.md", row, result, details, checks, chart_digest)
    print("완료: 첫 경기 1행 × 158열 (방어 상성 피처 153개)")
    print(f"결과표: {data_dir}/matchup_sample.*\n설명·검증 자료: {info_dir}/matchup_*")


if __name__ == "__main__":
    main()

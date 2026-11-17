"""전체 경기의 능력치·타입 구성 데이터에 방어 상성 피처 153개를 추가한다.

실행: python preprocessing/build_matchup_features.py
stat_type_features를 읽고 stat_type_matchup_features/data와 info에 새 결과를 저장한다.
계산 규칙과 피처 이름은 build_matchup_sample.py와 공유한다.
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

from build_matchup_sample import (CATEGORIES, CHART_PATH, classify, compute_features,
                                  feature_definitions, feature_name, load_chart, verify)
from build_stat_features import ROOT, STAT_FEATURES, display_path, sha256, write_json
from build_type_features import INPUT_COLUMNS as STAT_INPUT_COLUMNS, TYPE_FEATURES
from build_type_features import add_all, has_secondary
from build_type_sample import TYPES, feature_name as type_feature_name
from prepare_basic import FEATURES, META, SCHEMA


MATCHUP_FEATURES = [d["name"] for d in feature_definitions()]
INPUT_COLUMNS = STAT_INPUT_COLUMNS + TYPE_FEATURES
CATEGORY_CODES = {name: code for code, name in enumerate(("neutral", *CATEGORIES))}
NONE = len(TYPES)  # 두 번째 타입이 없을 때의 인덱스
# 5세대 타입 상성의 무효 관계: 공격 타입 -> 이를 무효로 받는 방어 타입
IMMUNITIES = {"Normal": "Ghost", "Fighting": "Ghost", "Ghost": "Normal", "Electric": "Ground",
              "Ground": "Flying", "Poison": "Steel", "Psychic": "Dark"}


def build_lookup(chart):
    """공격 타입별로 (첫 타입 × 18 + 두 번째 타입) → 분류 코드 표를 만든다."""
    lookup = {}
    for attack in TYPES:
        codes = []
        for primary in TYPES:
            for secondary in (*TYPES, None):
                value = chart[attack][primary] * (chart[attack][secondary] if secondary else 1)
                codes.append(CATEGORY_CODES[classify(value)])
        lookup[attack] = pa.array(codes, type=pa.int8())
    return lookup


def calculate_features(table, lookup):
    """두 배율을 곱한 뒤의 분류를 미리 만든 표에서 찾아 팀별로 센다. 입력 오류는 중단한다."""
    valid_types = pa.array(TYPES)
    result = {}
    for side in ("p1", "p2"):
        slot_codes = []
        for k in range(1, 7):
            primary, secondary = (table[f"{side}_slot{k}_{f}"] for f in ("type1", "type2"))
            first = pc.index_in(primary, value_set=valid_types)
            if first.null_count:
                raise ValueError(f"{side}/slot{k}: 잘못되거나 누락된 첫 번째 타입")
            present = has_secondary(secondary)
            second_raw = pc.index_in(secondary, value_set=valid_types)
            if pc.any(pc.and_(present, pc.is_null(second_raw))).as_py():
                raise ValueError(f"{side}/slot{k}: 잘못된 두 번째 타입")
            second = pc.if_else(present, second_raw, pa.scalar(NONE, type=pa.int32()))
            if pc.any(pc.equal(first, second)).as_py():
                raise ValueError(f"{side}/slot{k}: 두 타입이 중복됨")
            slot_codes.append(pc.add(pc.multiply(first, NONE + 1), second))
        for attack in TYPES:
            labels = [pc.take(lookup[attack], code) for code in slot_codes]
            for category in CATEGORIES:
                code = CATEGORY_CODES[category]
                result[feature_name(side, attack, category)] = add_all(
                    [pc.cast(pc.equal(label, code), pa.int8()) for label in labels])
    for attack in TYPES:
        for category in CATEGORIES:
            result[feature_name("diff", attack, category)] = pc.subtract(
                result[feature_name("p1", attack, category)],
                result[feature_name("p2", attack, category)])
    return result


def all_true(mask):
    return mask.null_count == 0 and pc.all(mask).as_py()


def check_counts(table):
    """모든 행에서 범위·차이·분류 합계·무효 관계를 검사한다."""
    for attack in TYPES:
        for side in ("p1", "p2"):
            values = [table[feature_name(side, attack, c)] for c in CATEGORIES]
            for value in values:
                if not all_true(pc.and_(pc.greater_equal(value, 0), pc.less_equal(value, 6))):
                    raise ValueError(f"방어 상성 수가 비어 있거나 0~6 범위를 벗어남: {attack}")
            if not all_true(pc.less_equal(add_all(values), 6)):
                raise ValueError(f"약점·저항·무효 합계가 6을 넘음: {side}/{attack}")
            # 타입만 기준이면 무효 수 = 그 공격을 무효로 받는 타입을 가진 팀원 수(타입 구성 피처)
            immune = table[feature_name(side, attack, "immune")]
            expected = (table[type_feature_name(side, IMMUNITIES[attack])]
                        if attack in IMMUNITIES else pa.scalar(0, type=pa.int8()))
            if not all_true(pc.equal(immune, expected)):
                raise ValueError(f"무효 수와 타입 구성 불일치: {side}/{attack}")
        for category in CATEGORIES:
            difference = table[feature_name("diff", attack, category)]
            expected = pc.subtract(table[feature_name("p1", attack, category)],
                                   table[feature_name("p2", attack, category)])
            if difference.null_count or not difference.equals(expected):
                raise ValueError(f"방어 상성 차이 불일치: {attack}/{category}")


def check_symmetry(table, lookup):
    original = calculate_features(table, lookup)
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
    reversed_features, swapped_features = (calculate_features(t, lookup) for t in
                                          (reversed_table, swapped_table))
    for attack in TYPES:
        for category in CATEGORIES:
            for side in ("p1", "p2", "diff"):
                name = feature_name(side, attack, category)
                if not original[name].equals(reversed_features[name]):
                    raise ValueError(f"슬롯 순서 검사 실패: {name}")
                if side == "diff":
                    other = pc.negate(swapped_features[name])
                else:
                    opposite = "p2" if side == "p1" else "p1"
                    other = swapped_features[feature_name(opposite, attack, category)]
                if not original[name].equals(other):
                    raise ValueError(f"팀 교환 검사 실패: {name}")
    changed = table
    for name in META + ["y"]:
        i = changed.schema.get_field_index(name)
        changed = changed.set_column(i, name, pa.nulls(len(table), type=table[name].type))
    changed_features = calculate_features(changed, lookup)
    if any(not original[name].equals(changed_features[name]) for name in MATCHUP_FEATURES):
        raise ValueError("관리 정보·정답이 방어 상성 계산에 영향을 줌")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT /
                        "data/datasets/stat_type_features/data/all_stat_type_features.parquet")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "data/datasets/stat_type_matchup_features")
    parser.add_argument("--batch-size", type=int, default=10000)
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error("--batch-size는 양수여야 합니다.")
    expected_schema = SCHEMA
    for name in STAT_FEATURES:
        expected_schema = expected_schema.append(pa.field(name, pa.float64()))
    for name in TYPE_FEATURES:
        expected_schema = expected_schema.append(pa.field(name, pa.int8()))
    source = pq.ParquetFile(args.source)
    if not source.schema_arrow.equals(expected_schema, check_metadata=False):
        parser.error("입력은 stat_type_features의 218열 스키마여야 합니다.")
    rows = source.metadata.num_rows
    if not rows:
        parser.error("입력 데이터에 경기가 없습니다.")
    data_dir, info_dir = args.output / "data", args.output / "info"
    parquet_path = data_dir / "all_stat_type_matchup_features.parquet"
    csv_path = data_dir / "all_stat_type_matchup_features.csv"
    output_paths = [parquet_path, csv_path] + [info_dir / n for n in
                                            ("README.md", "columns.json", "quality_report.json")]
    if any(p.exists() for p in output_paths):
        parser.error("출력 파일이 이미 있습니다. --output으로 다른 폴더를 지정하세요.")
    chart, chart_digest, chart_info = load_chart()
    lookup = build_lookup(chart)
    source_hash = sha256(args.source)
    data_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    schema = source.schema_arrow
    for name in MATCHUP_FEATURES:
        schema = schema.append(pa.field(name, pa.int8()))
    expected_digest = hashlib.sha256()
    formats = Counter()
    sums = Counter()
    written = 0
    with pq.ParquetWriter(parquet_path, schema, compression="snappy") as writer, \
            pacsv.CSVWriter(csv_path, schema) as csv_writer:
        for batch in source.iter_batches(batch_size=args.batch_size):
            table = pa.Table.from_batches([batch])
            result = calculate_features(table, lookup)
            for name in MATCHUP_FEATURES:
                table = table.append_column(name, result[name])
            check_counts(table)
            writer.write_table(table)
            csv_writer.write_table(table)
            sink = pa.BufferOutputStream()
            pacsv.write_csv(table, sink, write_options=pacsv.WriteOptions(include_header=False))
            expected_digest.update(sink.getvalue().to_pybytes())
            formats.update(table["formatid"].to_pylist())
            for name in MATCHUP_FEATURES:
                if not name.startswith("diff_"):
                    sums[name] += pc.sum(pc.cast(table[name], pa.int64())).as_py()
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
            raise ValueError("기존 218열의 값·경기 순서가 변경됨")
        check_counts(output)
        local = [i - offset for i in sorted(sample_indices) if offset <= i < offset + len(output)]
        if local:
            inputs = original.take(local)
            sampled_inputs.append(inputs)
            for row, observed in zip(inputs.to_pylist(), output.take(local).to_pylist()):
                # 샘플 코드의 행 단위 곱셈 계산과, 그 안의 log2 지수 기반 독립 분류로 대조
                reference = compute_features(row, chart)
                verify(row, reference, chart, chart_info)
                if any(observed[name] != reference[name] for name in MATCHUP_FEATURES):
                    raise ValueError(f"독립 방어 상성 계산 불일치: {row['battle_id']}")
                checked += 1
        sink = pa.BufferOutputStream()
        pacsv.write_csv(output, sink, write_options=pacsv.WriteOptions(include_header=False))
        parquet_csv_digest.update(sink.getvalue().to_pybytes())
        offset += len(output)
    if offset != rows or checked != len(sample_indices):
        raise ValueError("검사 행 수 불일치")
    check_symmetry(pa.concat_tables(sampled_inputs), lookup)
    with csv_path.open("rb") as stream:
        header = stream.readline().decode("utf-8").strip()
        if header != ",".join(f'"{name}"' for name in schema.names):
            raise ValueError("CSV 컬럼 순서 불일치")
        csv_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    if csv_hash != expected_digest.hexdigest() or csv_hash != parquet_csv_digest.hexdigest():
        raise ValueError("CSV·Parquet 전체 저장값 불일치")
    if sha256(args.source) != source_hash:
        raise ValueError("입력 파일이 변경됨")

    features = FEATURES + STAT_FEATURES + TYPE_FEATURES + MATCHUP_FEATURES
    write_json(info_dir / "columns.json", {
        "features": features, "basic_features": FEATURES, "stat_features": STAT_FEATURES,
        "type_features": TYPE_FEATURES, "matchup_features": MATCHUP_FEATURES,
        "metadata": META, "target": "y", "columns_in_order": schema.names,
    })
    checks = {name: "passed" for name in (
        "typechart_sha256_matches_info", "all_original_218_columns_and_row_order_preserved",
        "all_matchup_count_ranges_and_differences", "all_category_totals_at_most_6",
        "all_immune_counts_match_type_composition", "independent_sample_calculation",
        "slot_order_invariance", "team_swap_sign_check", "metadata_and_target_not_used",
        "full_csv_parquet_roundtrip", "source_file_unchanged")}
    mean_counts = {attack: {f"{side}_{c}": round(sums[feature_name(side, attack, c)] / rows, 4)
                            for side in ("p1", "p2") for c in CATEGORIES} for attack in TYPES}
    write_json(info_dir / "quality_report.json", {
        "source": display_path(args.source), "source_sha256": source_hash,
        "typechart": display_path(CHART_PATH), "typechart_sha256": chart_digest,
        "output_rows": rows, "input_columns": len(INPUT_COLUMNS), "output_columns": len(schema),
        "basic_feature_count": len(FEATURES), "stat_feature_count": len(STAT_FEATURES),
        "type_feature_count": len(TYPE_FEATURES), "matchup_feature_count": len(MATCHUP_FEATURES),
        "feature_count": len(features), "metadata_count": len(META), "target": "y",
        "attack_types": list(TYPES), "categories": {
            "weak": "최종 배율 2·4", "resist": "최종 배율 0.5·0.25", "immune": "최종 배율 0",
            "neutral(세지 않음)": "최종 배율 1"},
        "formats": dict(formats), "mean_team_counts_by_attack_type": mean_counts,
        "independently_checked_rows": checked, "sample_seed": 0,
        "csv_body_sha256": csv_hash, "checks": checks,
        "limitations": ["입력 데이터의 파싱·도감 정확성을 새로 검증하지 않음",
                        "특성·아이템·기술 고유 효과·경기 상태 미반영",
                        "실제 피해량·공격 기술 범위 아님",
                        "데이터 분할·모델 학습·평가 미실시"],
    })
    links = {name: Path(relpath(ROOT / f"data/datasets/features_sample/info/{name}",
                               info_dir)).as_posix()
             for name in ("stat_definitions.json", "type_definitions.json",
                          "matchup_definitions.json", "matchup_example.md")}
    (info_dir / "README.md").write_text(
        f"# 능력치·타입 구성·방어 상성 조합 피처 데이터셋\n\n입력: `{display_path(args.source)}`\n\n"
        f"{rows:,}경기 × {len(schema)}열. 기존 218열의 값·순서를 유지하고 방어 상성 153열을 뒤에 추가했다.\n\n"
        "`../data/all_stat_type_matchup_features.csv`와 `../data/all_stat_type_matchup_features.parquet`는 같은 표다.\n\n"
        "## 컬럼 구분\n\n"
        f"- 기본 정보 108개 + 능력치 54개 + 타입 구성 51개 + 방어 상성 153개 = 입력 후보 {len(features)}개\n"
        "- 관리 정보 4개: battle_id, formatid, uploadtime, winner\n"
        "- 정답 1개: y (1은 p1 승리, 0은 p2 승리)\n\n"
        "winner와 y는 입력에 넣지 않는다. 관리 정보도 자동으로 학습에 포함하지 않는다. "
        "columns.json에서 basic_features, stat_features, type_features, matchup_features, "
        "features로 입력을 선택할 수 있다.\n\n"
        "## 방어 상성 집계\n\n"
        "팀원마다 공격 타입 17개에 대해 받는 배율을 `data/external/gen5_typechart.csv`에서 찾는다. "
        "복수 타입은 두 배율을 먼저 곱한 뒤 분류한다. 2·4배는 약점, 0.5·0.25배는 저항, 0배는 무효이고 "
        "1배는 세지 않는다. 17개 공격 타입 × (약점·저항·무효) × (A팀·B팀·A − B) = 153개다. "
        "팀별 값은 0~6, 차이는 −6~6이다. 특성·아이템·기술 고유 효과·날씨는 반영하지 않는다.\n\n"
        f"계산 과정은 [첫 경기 예시]({links['matchup_example.md']})에서 볼 수 있다. "
        f"[방어 상성 정의]({links['matchup_definitions.json']}), "
        f"[타입 구성 정의]({links['type_definitions.json']}), "
        f"[능력치 정의]({links['stat_definitions.json']})는 샘플의 정의 파일을 공유한다.\n\n"
        "## 검증\n\n"
        "상성표 해시, 전체 경기의 기존 218열·순서, 방어 상성 수 범위·차이·분류 합계(6 이하)와 "
        "CSV·Parquet 전체 값 일치를 확인했다. 모든 경기에서 무효 수가 해당 무효 타입(예: 땅 공격 → 비행)의 "
        "타입 구성 수와 같은지도 대조했다. "
        f"첫·마지막 경기와 고정 난수 표본 등 {checked}경기는 샘플 코드의 행 단위 계산과 대조했다. "
        "표본에서 슬롯 순서·팀 교환·관리 정보 및 정답 변경 검사도 통과했다. "
        "원본 해시, 공격 타입별 평균 수, 검사 결과는 quality_report.json에 있다.\n\n"
        "## 다시 생성\n\n```bash\npython preprocessing/build_matchup_features.py\n```\n\n"
        "기존 출력이 있으면 중단한다. --output으로 새 폴더를 지정할 수 있다. "
        "데이터 분할·모델 학습·평가는 아직 진행하지 않았다.\n", encoding="utf-8")
    print(f"완료: {rows:,}경기 × {len(schema)}열; 검증 {len(checks)}개 통과", flush=True)
    print(f"결과표: {data_dir}\n설명·검증 자료: {info_dir}", flush=True)


if __name__ == "__main__":
    main()

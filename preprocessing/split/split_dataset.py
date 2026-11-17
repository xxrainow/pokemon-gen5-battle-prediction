"""최종 피처 표를 포맷·승패를 고려해 Train/Validation/Test로 나눈다.

--strategy matchup: 같은 포맷의 같은 양 팀 종 구성(팀 순서 무관)을 함께 배정.
--strategy team-components: 같은 포맷에서 한쪽 팀이라도 공유하는 경기를 연결해 함께 배정.
팀 구성은 슬롯 순서를 무시한 종 목록이다. 기술·아이템까지 같은 팀이라는 뜻은 아니다.
인코딩·표준화·모델 학습은 수행하지 않는다.
"""

import argparse
from array import array
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import random

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[2]
SPLITS = ("train", "validation", "test")
SPECIES = [f"{side}_slot{k}_species" for side in ("p1", "p2") for k in range(1, 7)]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def assign_groups(groups, ratios, seed):
    """큰 그룹부터 포맷별 경기 수와 승패 비율의 오차를 줄이도록 배정한다."""
    rng = random.Random(seed)
    buckets = defaultdict(list)
    for group, (fmt, n0, n1) in groups.items():
        buckets[fmt].append((group, n0, n1))
    assignments = {}
    for fmt, items in sorted(buckets.items()):
        total = [sum(item[c + 1] for item in items) for c in (0, 1)]
        targets = [[ratio * value for value in total] for ratio in ratios]
        used = [[0, 0] for _ in SPLITS]
        rng.shuffle(items)
        items.sort(key=lambda item: item[1] + item[2], reverse=True)
        for group, n0, n1 in items:
            counts = (n0, n1)
            choices = list(range(3))
            rng.shuffle(choices)
            def cost(i):
                return sum(((used[i][c] + counts[c] - targets[i][c]) ** 2
                            - (used[i][c] - targets[i][c]) ** 2)
                           / max(targets[i][c], 1.0) for c in (0, 1))
            chosen = min(choices, key=cost)
            assignments[group] = chosen
            used[chosen][0] += n0
            used[chosen][1] += n1
        if any(count == 0 for counts in used for count in counts):
            raise ValueError(f"{fmt}: 각 분할에 양쪽 승패를 배정하지 못했습니다. 비율이나 전략을 확인하세요.")
    return assignments


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=ROOT /
                    "data/datasets/stat_type_matchup_features/data/all_stat_type_matchup_features.parquet")
    ap.add_argument("--output", type=Path, default=ROOT / "data/datasets/splits")
    ap.add_argument("--strategy", required=True, choices=("matchup", "team-components"))
    ap.add_argument("--ratios", nargs=3, type=float, default=(0.70, 0.15, 0.15))
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if any(not math.isfinite(r) or r <= 0 for r in args.ratios) or not math.isclose(sum(args.ratios), 1):
        ap.error("분할 비율은 양수 3개이며 합계가 1이어야 합니다.")
    source = pq.ParquetFile(args.source)
    needed = {"battle_id", "formatid", "y", *SPECIES}
    if needed - set(source.schema_arrow.names):
        ap.error("필수 컬럼이 없습니다.")
    data_dir, info_dir = args.output / "data", args.output / "info"
    paths = [data_dir / f"{name}.{ext}" for name in SPLITS for ext in ("csv", "parquet")]
    paths += [info_dir / name for name in ("assignments.parquet", "split_report.json", "README.md")]
    if any(path.exists() for path in paths):
        ap.error("출력이 이미 있습니다. --output으로 새 폴더를 지정하세요.")
    source_hash = sha256(args.source)

    # 종 구성과 경기 연결을 먼저 조사한다. 이 과정은 인코딩 변환을 학습하지 않는다.
    team_lookup = {}
    team_hashes, parent, size = [], array("I"), array("I")
    row_a, row_b = array("I"), array("I")
    row_formats, row_y = [], bytearray()
    pair_counts = Counter()
    def team_id(fmt, names):
        if any(not isinstance(name, str) or not name for name in names):
            raise ValueError("종 이름에 빈 값이 있습니다.")
        key = (fmt, *sorted(names))
        if key not in team_lookup:
            i = len(parent)
            team_lookup[key] = i
            parent.append(i)
            size.append(1)
            team_hashes.append(digest(key))
        return team_lookup[key]
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for batch in source.iter_batches(batch_size=10000, columns=["formatid", "y"] + SPECIES):
        for row in batch.to_pylist():
            fmt, y = row["formatid"], row["y"]
            if not fmt or y not in (0, 1):
                raise ValueError("포맷 또는 정답이 잘못되었습니다.")
            a = team_id(fmt, [row[f"p1_slot{k}_species"] for k in range(1, 7)])
            b = team_id(fmt, [row[f"p2_slot{k}_species"] for k in range(1, 7)])
            row_a.append(a); row_b.append(b); row_formats.append(fmt); row_y.append(y)
            pair_counts[(fmt, min(a, b), max(a, b))] += 1
            ra, rb = find(a), find(b)
            if ra != rb:
                if size[ra] < size[rb]: ra, rb = rb, ra
                parent[rb] = ra; size[ra] += size[rb]
    component_keys = {}
    for i, key in enumerate(team_hashes):
        root = find(i)
        component_keys[root] = min(component_keys.get(root, key), key)
    groups, row_groups = {}, []
    component_rows, format_rows = defaultdict(Counter), Counter(row_formats)
    for fmt, a, b, y in zip(row_formats, row_a, row_b, row_y):
        root = find(a)
        component_rows[fmt][root] += 1
        key = (digest([fmt, *sorted((team_hashes[a], team_hashes[b]))])
               if args.strategy == "matchup" else component_keys[root])
        if key not in groups: groups[key] = [fmt, 0, 0]
        groups[key][y + 1] += 1
        row_groups.append(key)
    audit = {fmt: {"battles": count, "components": len(component_rows[fmt]),
                   "largest_component_battles": max(component_rows[fmt].values()),
                   "largest_component_fraction": max(component_rows[fmt].values()) / count}
             for fmt, count in sorted(format_rows.items())}
    if args.strategy == "team-components":
        for fmt, stats in audit.items():
            if stats["largest_component_fraction"] > max(args.ratios):
                ap.error(f"{fmt}: 연결 그룹이 {stats['largest_component_fraction']:.1%}이므로 "
                         "요청 비율을 맞출 수 없습니다. 학습 비율을 높이거나 matchup을 사용하세요.")
    assignments = assign_groups(groups, args.ratios, args.seed)
    row_split = bytearray(assignments[key] for key in row_groups)
    del team_lookup, groups, assignments

    # 기존 컬럼과 값을 유지해 각 행을 지정된 분할로 보낸다.
    data_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    writers = [pq.ParquetWriter(data_dir / f"{name}.parquet", source.schema_arrow,
                                compression="snappy") for name in SPLITS]
    csv_writers = [pacsv.CSVWriter(data_dir / f"{name}.csv", source.schema_arrow) for name in SPLITS]
    manifest_schema = pa.schema([("source_row", pa.int64()), ("battle_id", pa.string()),
                                ("formatid", pa.string()), ("split", pa.string()),
                                ("group_id", pa.string())])
    manifest = pq.ParquetWriter(info_dir / "assignments.parquet", manifest_schema,
                                compression="snappy")
    counts = [Counter() for _ in SPLITS]
    team_sets, pair_sets, id_sets = [set() for _ in SPLITS], [set() for _ in SPLITS], [set() for _ in SPLITS]
    expected = [hashlib.sha256() for _ in SPLITS]
    offset = 0
    try:
        for batch in source.iter_batches(batch_size=10000):
            table = pa.Table.from_batches([batch])
            n = len(table)
            ids = table["battle_id"].to_pylist()
            if any(not ident for ident in ids): raise ValueError("빈 경기 ID")
            for i, name in enumerate(SPLITS):
                indices = [k for k in range(n) if row_split[offset+k] == i]
                selected = table.take(indices)
                if not indices: continue
                for k in indices:
                    pos = offset + k
                    ident = ids[k]
                    if ident in id_sets[i]: raise ValueError(f"중복 경기 ID: {ident}")
                    id_sets[i].add(ident)
                    counts[i][(row_formats[pos], int(row_y[pos]))] += 1
                    team_sets[i].update((row_a[pos], row_b[pos]))
                    pair_sets[i].add((min(row_a[pos], row_b[pos]), max(row_a[pos], row_b[pos])))
                writers[i].write_table(selected)
                csv_writers[i].write_table(selected)
                sink = pa.BufferOutputStream()
                pacsv.write_csv(selected, sink, write_options=pacsv.WriteOptions(include_header=False))
                expected[i].update(sink.getvalue().to_pybytes())
            records = [{"source_row": offset+k, "battle_id": ids[k],
                        "formatid": row_formats[offset+k], "split": SPLITS[row_split[offset+k]],
                        "group_id": row_groups[offset+k]} for k in range(n)]
            manifest.write_table(pa.Table.from_pylist(records, schema=manifest_schema))
            offset += n
    finally:
        for writer in writers + csv_writers: writer.close()
        manifest.close()
    assert offset == source.metadata.num_rows
    overlaps = {}
    for i in range(3):
        for j in range(i+1, 3):
            key = f"{SPLITS[i]}__{SPLITS[j]}"
            assert not id_sets[i].intersection(id_sets[j])
            pair_overlap = len(pair_sets[i].intersection(pair_sets[j]))
            team_overlap = len(team_sets[i].intersection(team_sets[j]))
            assert pair_overlap == 0
            if args.strategy == "team-components": assert team_overlap == 0
            overlaps[key] = {"battle_id": 0, "matchup_pairs": pair_overlap,
                             "observed_team_compositions": team_overlap}
    outputs = {}
    for i, name in enumerate(SPLITS):
        saved = pq.ParquetFile(data_dir / f"{name}.parquet")
        assert saved.schema_arrow.equals(source.schema_arrow)
        assert saved.metadata.num_rows == sum(counts[i].values())
        checked_digest = hashlib.sha256()
        for batch in saved.iter_batches(batch_size=10000):
            sink = pa.BufferOutputStream()
            pacsv.write_csv(batch, sink, write_options=pacsv.WriteOptions(include_header=False))
            checked_digest.update(sink.getvalue().to_pybytes())
        assert checked_digest.hexdigest() == expected[i].hexdigest()
        with (data_dir / f"{name}.csv").open("rb") as stream:
            stream.readline()
            assert hashlib.file_digest(stream, "sha256").hexdigest() == expected[i].hexdigest()
        by_format = {fmt: {"y0": counts[i][(fmt,0)], "y1": counts[i][(fmt,1)],
                           "rows": counts[i][(fmt,0)]+counts[i][(fmt,1)]}
                     for fmt in sorted(format_rows)}
        outputs[name] = {"rows": saved.metadata.num_rows,
                         "fraction": saved.metadata.num_rows / offset,
                         "by_format": by_format, "csv_body_sha256": expected[i].hexdigest()}
    assert sha256(args.source) == source_hash
    assert sum(result["rows"] for result in outputs.values()) == offset
    report = {"source": str(args.source.resolve()), "source_sha256": source_hash,
              "rows": offset, "columns": len(source.schema_arrow.names),
              "strategy": args.strategy, "seed": args.seed,
              "requested_ratios": dict(zip(SPLITS,args.ratios)),
              "group_definition": ("formatid + 슬롯 순서를 무시한 양 팀 종 구성. 팀 순서도 무시."
                                   if args.strategy == "matchup" else
                                   "같은 포맷에서 한쪽 팀의 종 구성이라도 공유하는 경기를 연결한 묶음."),
              "same_team_means": "입력에서 관측 가능한 종 구성. 기술·아이템·특성 동일성을 뜻하지 않음.",
              "group_count": len(set(row_groups)), "repeated_pair_extra_rows": sum(n-1 for n in pair_counts.values()),
              "connected_component_audit": audit, "outputs": outputs, "cross_split_overlaps": overlaps,
              "checks": {"every_row_assigned_once": "passed", "id_and_pair_groups_disjoint": "passed",
                         "saved_values_equal_source_selected_rows": "passed", "csv_parquet_agree": "passed",
                         "source_file_unchanged": "passed"},
              "limitations": ["학습·평가 및 인코딩·표준화는 아직 수행하지 않음",
                              "matchup 전략은 개별 팀이 분할 간 반복될 수 있어 새 팀 구성 일반화 평가가 아님",
                              "그룹 제약으로 요청 비율·승패 비율은 근사치", "업로드 시각 기준 시간 분할은 아님"]}
    write_json(info_dir / "split_report.json", report)
    lines = ["# 학습 검증 테스트 분할\n\n", f"전략: `{args.strategy}`, seed: {args.seed}. "
             "기존 입력 컬럼과 값은 유지하고 경기 행만 나눴다.\n\n",
             "| 분할 | 경기 수 | 비율 |\n|---|---|---|\n"]
    for name,value in outputs.items():
        lines.append(f"| {name} | {value['rows']:,} | {value['fraction']:.2%} |\n")
    lines += ["\n같은 포맷의 같은 대진은 팀 순서를 바꿔도 하나의 그룹이다. "
              "matchup 전략에서는 한쪽 팀이 다른 상대와 싸운 경기가 다른 분할에 존재할 수 있다. "
              "team-components 전략은 같은 포맷의 팀 구성까지 서로 겹치지 않게 한다.\n\n",
              "데이터는 `../data/train.parquet` 등으로 저장했다. `assignments.parquet`에는 원본 행·경기 ID·" 
              "포맷·배정 분할·그룹 ID가 있다. `split_report.json`에는 포맷별 승패·비율·중복 검사가 있다.\n\n",
              "이 파일 전체를 그대로 모델 입력에 넣지 않는다. 관리 정보와 winner·y를 구분하고, "
              "변환 규칙을 학습할 때는 train만 사용한다. validation은 설정 선택, test는 최종 평가에 사용한다.\n"]
    (info_dir / "README.md").write_text("".join(lines), encoding="utf-8")
    print(json.dumps({name: {k:v for k,v in value.items() if k != "csv_body_sha256"}
                      for name,value in outputs.items()}, ensure_ascii=False, indent=2), flush=True)
    print("저장 완료:",args.output)


if __name__ == "__main__":
    main()

"""Verify merged files produced by merge_external.py (independent of the merge code).

Checks per file:
  1. same row count and same battle_id order as the source file
  2. column count = source + 12*8 + 48*22, every source column kept with identical values
  3. value check against external CSVs read with the csv module (strings), for all rows
     (or a random sample of --sample rows for large files):
       species -> 8 stat/type columns, moveN -> 22 attribute columns,
       missing move -> all 22 attribute columns missing
  4. null consistency on ALL rows: missing move <-> missing basePower/category/type/...;
     species present -> hp..type1 present
  5. CSV: header equals parquet columns, row count equals parquet rows,
     first 2000 CSV rows equal parquet values
"""
import argparse, csv, random, math
import pyarrow.parquet as pq
import pyarrow.compute as pc
import pandas as pd

def load(path, key):
    with open(path, encoding="utf-8") as f:
        r = csv.DictReader(f)
        rows = {row[key]: row for row in r}
        return rows, [c for c in r.fieldnames if c != key]

def same(v, e):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return e == ""
    if e == "":
        return False
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, (int, float)):
        try: return abs(float(e) - float(v)) < 1e-9
        except ValueError: return False
    return str(v) == e

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--src", default="data/processed/parsed")
    ap.add_argument("--merged", default="data/processed/enriched")
    ap.add_argument("--ext", default="data/external")
    ap.add_argument("--sample", type=int, default=5000)
    a = ap.parse_args()
    dex, dex_f = load(f"{a.ext}/pokedex.csv", "species")
    mv, mv_f = load(f"{a.ext}/moves.csv", "move")
    sides, slots, moves = ("p1", "p2"), range(1, 7), range(1, 5)
    all_ok = True
    for name in a.names:
        errs = []
        src = pq.read_table(f"{a.src}/{name}.parquet")
        mpf = pq.ParquetFile(f"{a.merged}/{name}.parquet")
        n = mpf.metadata.num_rows
        cols = mpf.schema_arrow.names
        # 1-2
        if n != src.num_rows: errs.append(f"rows {n} != {src.num_rows}")
        exp_cols = len(src.column_names) + 12 * len(dex_f) + 48 * len(mv_f)
        if len(cols) != exp_cols: errs.append(f"columns {len(cols)} != {exp_cols}")
        for c in src.column_names:
            m = pq.read_table(f"{a.merged}/{name}.parquet", columns=[c]).column(0)
            if not m.equals(src.column(c)): errs.append(f"source column changed: {c}")
        # 4 null consistency on all rows
        always = [f for f in mv_f if f in ("basePower","category","type","accuracy","priority","contact","hazard","priority_move","pivot","setup","recovery","drain","recoil","sound","phazing")]
        for s in sides:
            for k in slots:
                base = f"{s}_slot{k}"
                t = pq.read_table(f"{a.merged}/{name}.parquet", columns=[f"{base}_species"] + [f"{base}_{f}" for f in dex_f if f != "type2"])
                sp_null = pc.is_null(t.column(0))
                for f in t.column_names[1:]:
                    if not pc.all(pc.equal(sp_null, pc.is_null(t[f]))).as_py(): errs.append(f"null mismatch {f}")
                for j in moves:
                    mc = f"{base}_move{j}"
                    t = pq.read_table(f"{a.merged}/{name}.parquet", columns=[mc] + [f"{mc}_{f}" for f in mv_f])
                    mnull = pc.is_null(t.column(0))
                    for f in mv_f:
                        an = pc.is_null(t[f"{mc}_{f}"])
                        if f in always:
                            if not pc.all(pc.equal(mnull, an)).as_py(): errs.append(f"null mismatch {mc}_{f}")
                        else:  # missing move must give missing attribute
                            if not pc.all(pc.or_(pc.invert(mnull), an)).as_py(): errs.append(f"attr present for missing move {mc}_{f}")
        # 3 value check
        idx = list(range(n)) if n <= a.sample else sorted(random.Random(0).sample(range(n), a.sample))
        need = [c for c in cols if "_slot" in c]
        sub = pq.read_table(f"{a.merged}/{name}.parquet", columns=need).take(idx).to_pylist()
        checked = 0
        for row in sub:
            for s in sides:
                for k in slots:
                    base = f"{s}_slot{k}"
                    sp = row[f"{base}_species"]
                    for f in dex_f:
                        v = row[f"{base}_{f}"]
                        e = dex[sp][f] if sp is not None else ""
                        checked += 1
                        if not same(v, e): errs.append(f"value {base}_{f} sp={sp} got={v!r} exp={e!r}")
                    for j in moves:
                        m = row[f"{base}_move{j}"]
                        for f in mv_f:
                            v = row[f"{base}_move{j}_{f}"]
                            e = mv[m][f] if m is not None else ""
                            checked += 1
                            if not same(v, e): errs.append(f"value {base}_move{j}_{f} move={m} got={v!r} exp={e!r}")
        # 5 csv
        with open(f"{a.merged}/{name}.csv", encoding="utf-8") as f:
            header = next(csv.reader(f))
        if header != cols: errs.append("csv header != parquet columns")
        import pyarrow as pa
        int_idx = [i for i, fld in enumerate(mpf.schema_arrow) if pa.types.is_integer(fld.type)]
        csv_rows, bad_int = -1, 0
        for rec in csv.reader(open(f"{a.merged}/{name}.csv", encoding="utf-8")):
            csv_rows += 1
            if csv_rows == 0: continue
            for i in int_idx:
                x = rec[i]
                if x and not x.lstrip("-").isdigit(): bad_int += 1
        if csv_rows != n: errs.append(f"csv rows {csv_rows} != {n}")
        if bad_int: errs.append(f"csv integer cells not written as integers: {bad_int}")
        head_csv = pd.read_csv(f"{a.merged}/{name}.csv", nrows=2000, keep_default_na=False, dtype=str)
        head_pq = pq.ParquetFile(f"{a.merged}/{name}.parquet").read_row_group(0).slice(0, 2000).to_pylist()
        bad_csv = 0
        for i, row in enumerate(head_pq[:len(head_csv)]):
            for c in cols:
                e = head_csv.iat[i, head_csv.columns.get_loc(c)]
                ok_cell = (e == str(row[c])) if isinstance(row[c], int) and not isinstance(row[c], bool) else same(row[c], e)
                if not ok_cell: bad_csv += 1
        if bad_csv: errs.append(f"csv/parquet value mismatches in first rows: {bad_csv}")
        ok = not errs
        all_ok &= ok
        print(f"{name}: rows={n} cols={len(cols)} value_cells_checked={checked} rows_checked={len(idx)} -> {'OK' if ok else 'FAIL'}")
        for e in errs[:10]: print("   ", e)
    print("ALL OK" if all_ok else "SOME FAILED")

if __name__ == "__main__":
    main()

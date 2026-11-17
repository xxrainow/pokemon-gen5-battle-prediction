"""Merge external tables (pokedex.csv, moves.csv) into the parsed battle files.

For every battle row and every slot ({p1,p2} x slot1..6):
  species        -> + hp, atk, def, spa, spd, spe, type1, type2        (data/external/pokedex.csv)
  move1..move4   -> + 22 move attributes per move                       (data/external/moves.csv)
A missing move (not revealed in the log) gives missing values for its 22 attributes.
Existing columns are kept unchanged and in place; new columns are inserted right after
the species / move column they belong to:
  {side}_slot{k}_{stat}            e.g. p1_slot1_hp
  {side}_slot{k}_move{j}_{attr}    e.g. p1_slot1_move1_basePower

Usage:
  python3 scripts/merge_external.py --src data/processed/parsed --out data/processed/enriched zu pu ...
"""
import argparse
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

SIDES = ("p1", "p2")
SLOTS = range(1, 7)
MOVES = range(1, 5)


def load_tables(ext_dir):
    dex = pd.read_csv(f"{ext_dir}/pokedex.csv", keep_default_na=False, na_values=[""])
    mv = pd.read_csv(f"{ext_dir}/moves.csv", keep_default_na=False, na_values=[""])
    assert dex.species.is_unique and mv.move.is_unique
    dex = dex.set_index("species")
    mv = mv.set_index("move")
    return dex, mv


def arrow_type(series):
    """Arrow type for an external column: int64 / float64 / string (mixed values -> string)."""
    s = series.dropna()
    if pd.api.types.is_integer_dtype(series) or (pd.api.types.is_float_dtype(series) and len(s) and (s == s.round()).all() and series.name not in ("흡수", "반동")):
        return pa.int64()
    if pd.api.types.is_float_dtype(series):
        return pa.float64()
    return pa.string()


def build_layout(src_columns, dex, mv):
    """Ordered output columns and, for new columns, (source column, table, field)."""
    stat_fields = list(dex.columns)              # hp..spe, type1, type2
    move_fields = list(mv.columns)               # 22 attributes
    order, new = [], {}
    for c in src_columns:
        order.append(c)
        for s in SIDES:
            for k in SLOTS:
                if c == f"{s}_slot{k}_species":
                    for f in stat_fields:
                        name = f"{s}_slot{k}_{f}"
                        order.append(name); new[name] = (c, "dex", f)
                for j in MOVES:
                    if c == f"{s}_slot{k}_move{j}":
                        for f in move_fields:
                            name = f"{s}_slot{k}_move{j}_{f}"
                            order.append(name); new[name] = (c, "mv", f)
    return order, new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="+")
    ap.add_argument("--src", default="data/processed/parsed")
    ap.add_argument("--out", default="data/processed/enriched")
    ap.add_argument("--ext", default="data/external")
    ap.add_argument("--batch-size", type=int, default=10000)
    ap.add_argument("--row-start", type=int, default=0, help="first source row to process")
    ap.add_argument("--row-stop", type=int, default=None, help="stop before this source row")
    ap.add_argument("--out-suffix", default="", help="e.g. .part0 -> writes <name>.part0.parquet/.csv")
    args = ap.parse_args()

    dex, mv = load_tables(args.ext)
    types = {("dex", f): arrow_type(dex[f]) for f in dex.columns}
    types.update({("mv", f): arrow_type(mv[f]) for f in mv.columns})
    lookup = {"dex": dex, "mv": mv}
    Path(args.out).mkdir(parents=True, exist_ok=True)

    for name in args.names:
        src = pq.ParquetFile(f"{args.src}/{name}.parquet")
        src_schema = src.schema_arrow
        order, new = build_layout(src_schema.names, dex, mv)
        fields = []
        for c in order:
            if c in new:
                _, tbl, f = new[c]
                fields.append(pa.field(c, types[(tbl, f)]))
            else:
                fields.append(src_schema.field(c))
        schema = pa.schema(fields, metadata=src_schema.metadata)

        writer = None
        first = True
        n = 0
        pos = 0
        stop = args.row_stop if args.row_stop is not None else src.metadata.num_rows
        for batch in src.iter_batches(batch_size=args.batch_size):
            b0, pos = pos, pos + batch.num_rows
            lo, hi = max(args.row_start, b0), min(stop, pos)
            if hi <= lo:
                if b0 >= stop: break
                continue
            batch = batch.slice(lo - b0, hi - lo)
            df = batch.to_pandas()
            cols = {}
            for c in order:
                if c in new:
                    key_col, tbl, f = new[c]
                    cols[c] = df[key_col].map(lookup[tbl][f])
                else:
                    cols[c] = df[c]
            out = pd.DataFrame(cols, columns=order)
            arrays = []
            for fld in schema:
                col = out[fld.name]
                if fld.name in new:
                    if pa.types.is_integer(fld.type):
                        col = col.astype("Int64")
                    elif pa.types.is_floating(fld.type):
                        col = col.astype("float64")
                    else:
                        col = col.astype("object").where(col.notna(), None).map(lambda v: v if v is None else str(v))
                    arrays.append(pa.array(col, type=fld.type, from_pandas=True))
                else:
                    arrays.append(batch.column(batch.schema.get_field_index(fld.name)))
            table = pa.Table.from_arrays(arrays, schema=schema)
            if writer is None:
                writer = pq.ParquetWriter(f"{args.out}/{name}{args.out_suffix}.parquet", schema)
            writer.write_table(table)
            table.to_pandas(integer_object_nulls=True).to_csv(f"{args.out}/{name}{args.out_suffix}.csv", mode="w" if first else "a", header=first, index=False)
            first = False
            n += len(df)
        writer.close()
        print(f"{name}{args.out_suffix}: rows {args.row_start}..{args.row_start + n} = {n} rows, {len(order)} columns ({len(new)} added)", flush=True)


if __name__ == "__main__":
    main()

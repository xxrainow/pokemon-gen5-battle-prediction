"""Concatenate <name>.partK.parquet/.csv (K = 0,1,...) into <name>.parquet/.csv, in order."""
import sys, glob, re
import pyarrow.parquet as pq

out_dir, name = sys.argv[1], sys.argv[2]
parts = sorted(glob.glob(f"{out_dir}/{name}.part*.parquet"), key=lambda p: int(re.search(r"\.part(\d+)\.parquet$", p).group(1)))
assert parts, "no parts found"
writer, total = None, 0
for p in parts:
    pf = pq.ParquetFile(p)
    if writer is None:
        writer = pq.ParquetWriter(f"{out_dir}/{name}.parquet", pf.schema_arrow)
    assert pf.schema_arrow.equals(writer.schema, check_metadata=False), p
    for g in range(pf.num_row_groups):
        t = pf.read_row_group(g); writer.write_table(t); total += t.num_rows
writer.close()
with open(f"{out_dir}/{name}.csv", "wb") as out:
    for i, p in enumerate(parts):
        with open(p.replace(".parquet", ".csv"), "rb") as f:
            header = f.readline()
            if i == 0: out.write(header)
            while True:
                chunk = f.read(1 << 24)
                if not chunk: break
                out.write(chunk)
print(f"{name}: combined {len(parts)} parts, {total} rows")

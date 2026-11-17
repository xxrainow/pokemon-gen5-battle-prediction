"""Pokemon Showdown replay log parser (Gen 5 singles).

Reads a HolidayOugi/pokemon-showdown-replays parquet file and writes ONE table,
one row per battle: <out>.{parquet,csv} plus <out>_summary.json.

Columns
  battle_id, formatid, tier, uploadtime, rating1, rating2, winner (1/2, 0 = dropped)
  then for each side p1/p2 and slot 1..6 (team-preview order):
    {side}_slot{k}_species       |poke|      start-time
    {side}_slot{k}_move1..4      |move|      IN-BATTLE (revealed during play)
    {side}_slot{k}_item          |-item|, |-enditem|, "[from] item:"   IN-BATTLE
    {side}_slot{k}_ability       |-ability|, "[from] ability:"         IN-BATTLE

IN-BATTLE columns depend on how the battle went. Do not use them as inputs of a
start-time win predictor. START_TIME_COLUMNS / IN_BATTLE_COLUMNS below list them.

parse_pre_start() reads only lines before |start| (plus |win|/|tie| for the label);
parse_in_battle() reads the rest.

Usage:
  python3 scripts/parse_logs.py "data/raw/[Gen 5] ZU.parquet" --out data/processed/parsed/zu
  python3 scripts/parse_logs.py "data/raw/[Gen 5] OU_part1.parquet" "data/raw/[Gen 5] OU_part2.parquet" "data/raw/[Gen 5] OU_part3.parquet" --out data/processed/parsed/ou
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


# ---------------------------------------------------------------- helpers

def to_id(name: str) -> str:
    """Showdown-style id: lowercase alphanumerics only. 'Rotom-Wash' -> 'rotomwash'."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def species_id(details: str) -> str:
    """'Garchomp, M, L50' -> 'garchomp'. Hidden formes ('Arceus-*') keep a '*'
    so they become a separate token: 'arceus*'."""
    name = details.split(",")[0].strip()
    if name.endswith("-*"):
        return to_id(name[:-2]) + "*"
    return to_id(name)


def base_id(details: str) -> str:
    """Species id without forme suffix: 'Rotom-Wash' -> 'rotom'."""
    return to_id(details.split(",")[0].strip().split("-")[0])


def parse_ident(ident: str):
    """'p1a: Nick' -> ('p1', 'Nick'). Returns (None, None) if not a pokemon ident."""
    m = re.match(r"^(p[12])[a-z]?: ?(.*)$", ident.strip())
    if not m:
        return None, None
    return m.group(1), m.group(2).strip()


def tag_value(parts, tag):
    """Find '[tag] value' among line parts; return value or None."""
    for p in parts:
        p = p.strip()
        if p.startswith(f"[{tag}]"):
            return p[len(tag) + 2:].strip()
    return None


# ---------------------------------------------------------------- part 1: pre-start

def parse_pre_start(lines):
    """Read ONLY lines before |start|, plus |win|/|tie| for the label."""
    out = {
        "tier": None,
        "p1_name": None, "p2_name": None,
        "rating1": None, "rating2": None,
        "p1_preview": [], "p2_preview": [],   # raw details strings, preview order
        "has_start": False,
        "winner_name": None, "tie": False,
        "start_index": None,
    }
    for i, line in enumerate(lines):
        parts = line.split("|")
        if len(parts) < 2:
            continue
        cmd = parts[1]
        if cmd == "start":
            out["has_start"] = True
            out["start_index"] = i
            break
        if cmd == "tier" and len(parts) >= 3:
            out["tier"] = parts[2].strip()
        elif cmd == "player" and len(parts) >= 4 and parts[2] in ("p1", "p2"):
            side, name = parts[2], parts[3].strip()
            if name:
                out[f"{side}_name"] = name
                if len(parts) >= 6 and parts[5].strip():
                    try:
                        out["rating1" if side == "p1" else "rating2"] = int(parts[5].strip())
                    except ValueError:
                        pass
        elif cmd == "clearpoke":
            out["p1_preview"], out["p2_preview"] = [], []
        elif cmd == "poke" and len(parts) >= 4 and parts[2] in ("p1", "p2"):
            side = parts[2]
            out[f"{side}_preview"].append(parts[3].strip())

    # Label only: scan for |win| / |tie| (nothing else after |start| is read here)
    for line in reversed(lines):
        if line.startswith("|win|"):
            out["winner_name"] = line.split("|", 2)[2].strip()
            break
        if line.startswith("|tie"):
            out["tie"] = True
            break
    return out


# ---------------------------------------------------------------- part 2: in-battle

# Abilities whose owner is the line's main pokemon even when an [of] tag is present
# (the [of] there is the attacker that triggered it).
MAIN_OWNER_ABILITIES = {
    "waterabsorb", "voltabsorb", "dryskin", "stormdrain", "lightningrod",
    "motordrive", "sapsipper", "flashfire", "pickpocket", "magician",
    "harvest", "colorchange", "justified", "rattled", "weakarmor",
    "angerpoint",
}
ITEM_GAIN_MOVES = {"trick", "switcheroo", "thief", "covet", "bestow"}
ITEM_GAIN_ABILITIES = {"pickpocket", "magician"}
ABILITY_CHANGE_MOVES = {"skillswap", "roleplay", "entrainment", "worryseed",
                        "simplebeam", "gastroacid"}


class Slot:
    __slots__ = ("moves", "item", "ability", "item_changed", "ability_changed")

    def __init__(self):
        self.moves = []
        self.item = None
        self.ability = None
        self.item_changed = False
        self.ability_changed = False


def parse_in_battle(lines, start_index, previews):
    """Read lines after |start| and collect revealed moves / items / abilities.

    previews: {'p1': [details...], 'p2': [details...]} from team preview.
    Returns ({'p1': [Slot]*n, 'p2': [Slot]*n}, stats Counter).
    """
    stats = Counter()
    slots = {s: [Slot() for _ in previews[s]] for s in ("p1", "p2")}
    pre_ids = {s: [species_id(d) for d in previews[s]] for s in ("p1", "p2")}
    pre_base = {s: [base_id(d) for d in previews[s]] for s in ("p1", "p2")}
    nick2slot = {}                 # (side, nick) -> slot index
    transformed = set()            # (side, nick) currently transformed
    stint = {"p1": None, "p2": None}   # active (key, [(slot_idx, move)]) for Illusion fixes

    def match_slot(side, details):
        sid, bid = species_id(details), base_id(details)
        taken = set(nick2slot[k] for k in nick2slot if k[0] == side)
        cands = [i for i, p in enumerate(pre_ids[side]) if p == sid]
        if not cands:
            cands = [i for i, p in enumerate(pre_ids[side])
                     if p.endswith("*") and sid.startswith(p[:-1])]
        if not cands:
            cands = [i for i, b in enumerate(pre_base[side]) if b == bid]
        free = [i for i in cands if i not in taken]
        return (free or cands or [None])[0]

    def slot_of(ident):
        side, nick = parse_ident(ident)
        if side is None:
            return None, None, None
        idx = nick2slot.get((side, nick))
        if idx is None:
            stats["unresolved_ident"] += 1
            return side, nick, None
        return side, nick, idx

    def set_item(side, idx, item, force=False):
        if idx is None:
            return
        sl = slots[side][idx]
        if sl.item is None and (force or not sl.item_changed):
            sl.item = to_id(item)

    def set_ability(side, idx, ability, force=False):
        if idx is None:
            return
        sl = slots[side][idx]
        if sl.ability is None and (force or not sl.ability_changed):
            sl.ability = to_id(ability)

    for line in lines[start_index + 1:]:
        parts = line.split("|")
        if len(parts) < 3:
            continue
        cmd = parts[1]

        # --- identity tracking
        if cmd in ("switch", "drag") and len(parts) >= 4:
            side, nick = parse_ident(parts[2])
            if side is None:
                continue
            key = (side, nick)
            if key not in nick2slot:
                idx = match_slot(side, parts[3])
                if idx is None:
                    stats["unmatched_switch"] += 1
                    continue
                nick2slot[key] = idx
            transformed.discard(key)
            stint[side] = (key, [])
            continue
        if cmd == "replace" and len(parts) >= 4:
            # Illusion broken: moves used during this stint belong to the real pokemon
            side, nick = parse_ident(parts[2])
            if side is None:
                continue
            key = (side, nick)
            if key not in nick2slot:
                idx = match_slot(side, parts[3])
                if idx is not None:
                    nick2slot[key] = idx
            real = nick2slot.get(key)
            if stint[side] and real is not None:
                for wrong_idx, mv in stint[side][1]:
                    if mv in slots[side][wrong_idx].moves:
                        slots[side][wrong_idx].moves.remove(mv)
                    if mv not in slots[side][real].moves and len(slots[side][real].moves) < 4:
                        slots[side][real].moves.append(mv)
                stats["illusion_fix"] += 1
            stint[side] = (key, [])
            continue
        if cmd == "-transform":
            side, nick = parse_ident(parts[2])
            if side:
                transformed.add((side, nick))
            continue

        # --- moves
        if cmd == "move" and len(parts) >= 4:
            if tag_value(parts[4:], "from") is not None:   # called by another move/ability, or lockedmove repeat
                continue
            side, nick, idx = slot_of(parts[2])
            if idx is None or (side, nick) in transformed:
                continue
            mv = to_id(parts[3])
            if mv == "struggle":
                continue
            sl = slots[side][idx]
            if mv not in sl.moves and len(sl.moves) < 4:
                sl.moves.append(mv)
                if stint[side] and stint[side][0] == (side, nick):
                    stint[side][1].append((idx, mv))
            continue

        # --- items
        if cmd == "-enditem" and len(parts) >= 4:
            side, _, idx = slot_of(parts[2])
            if idx is not None:
                set_item(side, idx, parts[3])           # item lost: it was the current item
                slots[side][idx].item_changed = True
            continue
        if cmd == "-item" and len(parts) >= 4:
            side, _, idx = slot_of(parts[2])
            if idx is None:
                continue
            frm = tag_value(parts[4:], "from") or ""
            frm_id = to_id(frm.split(":", 1)[1]) if ":" in frm else to_id(frm)
            if frm.startswith("move:") and frm_id in ITEM_GAIN_MOVES:
                slots[side][idx].item_changed = True      # received someone else's item
            elif frm.startswith("ability:") and frm_id in ITEM_GAIN_ABILITIES:
                slots[side][idx].item_changed = True
                set_ability(side, idx, frm_id)
            elif frm_id in ("recycle", "harvest"):
                set_item(side, idx, parts[3], force=True)
            else:
                set_item(side, idx, parts[3])           # Air Balloon, Frisk reveal, ...
            # Frisk: the ability belongs to the [of] pokemon (handled below)
        # "[from] item: X" on any line (Leftovers heal, Life Orb recoil, Rocky Helmet, ...)
        frm = tag_value(parts[3:], "from")
        if frm and frm.startswith("item:") and cmd not in ("-item", "-enditem"):
            of = tag_value(parts[3:], "of")
            owner = of if of else parts[2]
            side, _, idx = slot_of(owner)
            set_item(side, idx, frm[5:])

        # --- abilities
        if cmd == "-ability" and len(parts) >= 4:
            side, _, idx = slot_of(parts[2])
            frm = tag_value(parts[4:], "from") or ""
            of = tag_value(parts[4:], "of")
            if frm.startswith("ability:"):
                src = to_id(frm[8:])
                if src == "trace" and idx is not None:
                    set_ability(side, idx, "trace")       # tracer's own ability
                    slots[side][idx].ability_changed = True
                    if of:
                        s2, _, i2 = slot_of(of)
                        set_ability(s2, i2, parts[3])     # traced target's ability
                    continue
                if src == "mummy" and idx is not None:
                    # |-ability|target|Mummy|OldAbility|[from] ability: Mummy|[of] mummy-user
                    if len(parts) >= 5 and not parts[4].startswith("["):
                        set_ability(side, idx, parts[4])
                    slots[side][idx].ability_changed = True
                    if of:
                        s2, _, i2 = slot_of(of)
                        set_ability(s2, i2, "mummy")
                    continue
            if frm.startswith("move:") and to_id(frm[5:]) in ABILITY_CHANGE_MOVES:
                if idx is not None:
                    slots[side][idx].ability_changed = True
                continue
            set_ability(side, idx, parts[3])
            continue
        if cmd == "-activate" and len(parts) >= 4 and parts[3].strip().startswith("ability:"):
            side, _, idx = slot_of(parts[2])
            set_ability(side, idx, parts[3].strip()[8:])
            continue
        if frm and frm.startswith("ability:"):
            ab = to_id(frm[8:])
            of = tag_value(parts[3:], "of")
            owner = parts[2] if (ab in MAIN_OWNER_ABILITIES or not of) else of
            side, _, idx = slot_of(owner)
            set_ability(side, idx, frm[8:])

    return slots, stats


# ---------------------------------------------------------------- per battle

SIDES = ("p1", "p2")
SLOTS = range(1, 7)
META_COLUMNS = ["battle_id", "formatid", "tier", "uploadtime", "p1_name", "p2_name",
                "rating1", "rating2", "winner", "drop_reason"]
START_TIME_COLUMNS = ["tier", "rating1", "rating2"] + [
    f"{s}_slot{k}_{f}" for s in SIDES for k in SLOTS for f in ("species",)]
IN_BATTLE_COLUMNS = [
    f"{s}_slot{k}_{f}" for s in SIDES for k in SLOTS
    for f in ("move1", "move2", "move3", "move4", "item", "ability")]
SLOT_FIELDS = ("species", "move1", "move2", "move3", "move4", "item", "ability")
ALL_COLUMNS = META_COLUMNS + [f"{s}_slot{k}_{f}" for s in SIDES for k in SLOTS for f in SLOT_FIELDS]
EXCLUDED_FROM_OUTPUT = ["p1_name", "p2_name", "drop_reason"]   # used internally only
OUTPUT_COLUMNS = [c for c in ALL_COLUMNS if c not in EXCLUDED_FROM_OUTPUT]


def parse_battle(row):
    """Return (one dict = one output row, parser stats)."""
    lines = row["log"].split("\n")
    pre = parse_pre_start(lines)

    p1n = pre["p1_name"] or (row["players"][0] if len(row["players"]) > 0 else None)
    p2n = pre["p2_name"] or (row["players"][1] if len(row["players"]) > 1 else None)

    winner, drop = 0, ""
    if pre["tie"]:
        drop = "tie"
    elif pre["winner_name"] is None:
        drop = "no_winner"
    else:
        w = to_id(pre["winner_name"])
        if p1n and w == to_id(p1n) and not (p2n and w == to_id(p2n)):
            winner = 1
        elif p2n and w == to_id(p2n) and not (p1n and w == to_id(p1n)):
            winner = 2
        else:
            drop = "unknown_winner"
    if not drop and not pre["has_start"]:
        drop = "no_start"
    if not drop and (len(pre["p1_preview"]) != 6 or len(pre["p2_preview"]) != 6):
        drop = "not_6v6_preview"
    if drop:
        winner = 0

    rec = dict.fromkeys(ALL_COLUMNS)
    rec.update({
        "battle_id": row["id"],
        "formatid": row["formatid"],
        "tier": pre["tier"],
        "uploadtime": int(row["uploadtime"]),
        "p1_name": p1n, "p2_name": p2n,
        "rating1": pre["rating1"], "rating2": pre["rating2"],
        "winner": winner,
        "drop_reason": drop,
    })

    previews = {s: pre[f"{s}_preview"] for s in SIDES}
    for s in SIDES:
        for k, details in enumerate(previews[s][:6], start=1):
            rec[f"{s}_slot{k}_species"] = species_id(details)

    stats = Counter()
    if pre["has_start"] and previews["p1"] and previews["p2"]:
        slots, stats = parse_in_battle(lines, pre["start_index"], previews)
        for s in SIDES:
            for k, sl in enumerate(slots[s][:6], start=1):
                for m in range(4):
                    rec[f"{s}_slot{k}_move{m+1}"] = sl.moves[m] if m < len(sl.moves) else None
                rec[f"{s}_slot{k}_item"] = sl.item
                rec[f"{s}_slot{k}_ability"] = sl.ability
    return rec, stats


# ---------------------------------------------------------------- main

def output_schema():
    import pyarrow as pa
    fields = []
    for c in OUTPUT_COLUMNS:
        if c in ("uploadtime", "winner", "rating1", "rating2"):
            fields.append(pa.field(c, pa.int64()))
        else:
            fields.append(pa.field(c, pa.string()))
    return pa.schema(fields)


def main(argv=None):
    import pyarrow as pa
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="parquet file(s) from the HF dataset")
    ap.add_argument("--out", required=True, help="output prefix, e.g. data/zu")
    ap.add_argument("--no-csv", action="store_true", help="write parquet only")
    ap.add_argument("--batch-size", type=int, default=20000)
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    schema = output_schema()
    writer = None
    first_csv = True

    move_cols = [c for c in ALL_COLUMNS if "_move" in c]
    item_cols = [c for c in ALL_COLUMNS if c.endswith("_item")]
    abil_cols = [c for c in ALL_COLUMNS if c.endswith("_ability")]
    stats = Counter()
    agg = Counter()
    drops = Counter()

    for path in args.inputs:
        pf = pq.ParquetFile(path)
        n_file = 0
        for batch in pf.iter_batches(batch_size=args.batch_size,
                                     columns=["id", "players", "log", "uploadtime", "formatid"]):
            rows = []
            for row in batch.to_pylist():
                rec, s = parse_battle(row)
                rows.append(rec)
                stats.update(s)
            df = pd.DataFrame(rows, columns=ALL_COLUMNS)
            for c in ("rating1", "rating2"):
                df[c] = df[c].astype("Int64")
            n_file += len(df)

            # summary counters
            agg["total"] += len(df)
            drops.update(v for v in df.drop_reason if v)
            valid = df[df.drop_reason == ""]
            agg["valid"] += len(valid)
            agg["p1_win"] += int((valid.winner == 1).sum())
            agg["rating_both"] += int((valid.rating1.notna() & valid.rating2.notna()).sum())
            agg["rating_none"] += int((valid.rating1.isna() & valid.rating2.isna()).sum())
            agg["moves"] += int(valid[move_cols].notna().sum().sum())
            agg["items"] += int(valid[item_cols].notna().sum().sum())
            agg["abils"] += int(valid[abil_cols].notna().sum().sum())

            out_df = df[OUTPUT_COLUMNS]
            table = pa.Table.from_pandas(out_df, preserve_index=False)
            if writer is None:
                # keep pandas metadata so nullable ints (rating) read back as Int64
                schema = schema.with_metadata(table.schema.metadata)
                writer = pq.ParquetWriter(f"{out}.parquet", schema)
            table = table.cast(schema)
            writer.write_table(table)
            if not args.no_csv:
                out_df.to_csv(f"{out}.csv", mode="w" if first_csv else "a", header=first_csv, index=False)
                first_csv = False
        print(f"read {n_file:,} battles from {path}", file=sys.stderr)
    if writer is not None:
        writer.close()

    n_mons = agg["valid"] * 12
    summary = {
        "inputs": args.inputs,
        "battles_total": agg["total"],
        "battles_valid": agg["valid"],
        "drop_reasons": dict(drops),
        "valid_p1_win_rate": round(agg["p1_win"] / agg["valid"], 4) if agg["valid"] else None,
        "valid_rating_both": agg["rating_both"],
        "valid_rating_none": agg["rating_none"],
        "avg_moves_revealed_per_pokemon": round(agg["moves"] / n_mons, 3) if n_mons else None,
        "item_revealed_rate": round(agg["items"] / n_mons, 4) if n_mons else None,
        "ability_revealed_rate": round(agg["abils"] / n_mons, 4) if n_mons else None,
        "n_columns": len(OUTPUT_COLUMNS),
        "parser_stats": dict(stats),
    }
    with open(f"{out}_summary.json", "w") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

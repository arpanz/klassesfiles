"""
compare_5th_sem_timetables.py
─────────────────────────────
Compare timetable_5th.json      (zero-padded section names: CSE-01 …)
with    timetable_5th_filled.json (non-padded section names: CSE-1 …)

It normalises every section key so that “CSE-01”, “CSE-1”,
“IT-05”, “IT-5”, … are considered the *same* section.

For every triple (SECTION, DAY, SLOT) it reports
  • slots missing in one file
  • subject mismatches
  • room mismatches

Run
    python compare_5th_sem_timetables.py timetable_5th.json timetable_5th_filled.json
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from collections import defaultdict

DAYS = {"Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"}

# ───────────────────────── normalisation helpers ────────────────────────────
SECTION_REGEX = re.compile(r"^([A-Z]+)(?:-?)(\d+)$", re.I)

def norm_section(raw: str) -> str:
    """
    Turn  'CSE-01' -> 'CSE-1'
          'IT01'   -> 'IT-1'
          'csce-3' -> 'CSCE-3'
    """
    m = SECTION_REGEX.match(raw.replace(" ", ""))
    if not m:
        return raw.strip()                        # unknown pattern, leave as is
    prefix, num = m.groups()
    return f"{prefix.upper()}-{int(num)}"         # int() removes leading zeros

def is_day_dict(d: dict) -> bool:
    return d and all(k in DAYS for k in d)

# ───────────────────────── flatten timetable ────────────────────────────────
def flatten(data: dict) -> dict[tuple[str,str,str], dict]:
    """
    (section, day, slot)  ->  {"subject": …, "room": …}
    """
    flat = {}
    for sec_raw, day_map in data.items():
        sec = norm_section(sec_raw)
        for day, slots in day_map.items():
            for slot, entry in slots.items():
                flat[(sec, day, slot)] = entry
    return flat

# ───────────────────────── comparison & reporting ───────────────────────────
def compare(a: dict, b: dict) -> None:
    only_a, only_b, sub_diff, room_diff = [], [], [], []

    for key in set(a)|set(b):
        if key not in a:
            only_b.append(key); continue
        if key not in b:
            only_a.append(key); continue

        sa, sb = a[key].get("subject"), b[key].get("subject")
        ra, rb = a[key].get("room"),    b[key].get("room")

        if sa != sb:
            sub_diff.append((key, sa, sb))
        elif ra != rb:
            room_diff.append((key, ra, rb))

    def show(title: str, seq):
        print(f"\n{title}: {len(seq)}")
        for item in seq:
            print(item)

    show("Missing in FILE-B", only_a)
    show("Missing in FILE-A", only_b)
    show("Subject mismatches", sub_diff)
    show("Room mismatches",    room_diff)

# ───────────────────────── main ─────────────────────────────────────────────
def main(p1: str, p2: str):
    a = json.loads(Path(p1).read_text(encoding="utf-8"))
    b = json.loads(Path(p2).read_text(encoding="utf-8"))

    flat_a, flat_b = flatten(a), flatten(b)
    print(f"Entries in A: {len(flat_a):>4}")
    print(f"Entries in B: {len(flat_b):>4}")

    compare(flat_a, flat_b)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Usage: python compare_5th_sem_timetables.py <fileA.json> <fileB.json>")
    main(sys.argv[1], sys.argv[2])

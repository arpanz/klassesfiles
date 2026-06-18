#!/usr/bin/env python3
"""
Timetable_3rd_sem_roll.csv  ➜  roll_to_section.json
Structure: { "2429001": "CSCE-01", ... }
"""

import csv, json
from pathlib import Path

SRC  = Path("Timetable_3rd_sem_roll.csv")
DEST = Path("roll_to_section.json")

mapping = {}

with SRC.open(encoding="utf-8-sig") as f:        # 1️⃣ strips the BOM automatically
    reader = csv.reader(f)
    header = next(reader)

    # 2️⃣ locate the two useful columns irrespective of spacing / case
    cols   = {name.strip().lower(): idx for idx, name in enumerate(header)}
    roll_i = cols.get("roll number")
    sect_i = cols.get("section")

    if roll_i is None or sect_i is None:
        raise ValueError("Unable to locate 'Roll Number' or 'Section' columns")

    # 3️⃣ build the dictionary
    for row in reader:
        if not row:                  # skip completely blank lines
            continue
        roll    = row[roll_i].strip()
        section = row[sect_i].strip()
        if roll and section:         # ignore records missing either field
            mapping[roll] = section

with DEST.open("w", encoding="utf-8") as f:
    json.dump(mapping, f, indent=4, ensure_ascii=False)

print(f"✓ {DEST.name} written with {len(mapping):,} entries")

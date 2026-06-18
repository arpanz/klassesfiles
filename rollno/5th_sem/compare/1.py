import json
import sys
from pathlib import Path

DAYS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}

def is_section_dict(d: dict) -> bool:
    """True when *all* keys look like days of week (=> dict represents one section)."""
    return d and all(k in DAYS for k in d)

def flatten(data: dict) -> dict[tuple[str, str, str], dict]:
    """
    Turn the nested structure into
    {(section, day, slot): {"subject": s, "room": r?}}
    """
    flat: dict[tuple[str, str, str], dict] = {}

    # level-0: could already be sections or groups (E1 / E2 / …)
    for k0, v0 in data.items():

        # Case 1: immediately a SECTION → v0 = {DAY: {...}}
        if is_section_dict(v0):
            sections = {k0: v0}

        # Case 2: k0 is a GROUP (E1 / E2) → descend one level
        else:
            sections = v0  # keys here are real section names

        # Go through each section
        for section, day_map in sections.items():
            for day, slots in day_map.items():
                for slot, entry in slots.items():
                    if not isinstance(entry, dict):
                        continue          # defensive; shouldn't happen
                    flat[(section, day, slot)] = entry

    return flat

def compare(a: dict, b: dict) -> None:
    """
    Print differences between two flattened dicts.
    """
    only_in_a = []
    only_in_b = []
    subject_diff = []
    room_diff = []

    # union of keys from both files
    for key in set(a) | set(b):
        if key not in a:
            only_in_b.append(key)
            continue
        if key not in b:
            only_in_a.append(key)
            continue

        a_sub, b_sub = a[key].get("subject"), b[key].get("subject")
        a_room, b_room = a[key].get("room"), b[key].get("room")

        if a_sub != b_sub:
            subject_diff.append((key, a_sub, b_sub))
        elif a_room != b_room:
            room_diff.append((key, a_room, b_room))

    # print report
    def p(title: str, seq):
        if not seq:
            print(f"\n{title}: None")
            return
        print(f"\n{title}  ({len(seq)})")
        print("-" * len(title))
        for item in seq:
            print(item)

    p("Missing in FILE-A", only_in_b)
    p("Missing in FILE-B", only_in_a)
    p("Subject mismatch", subject_diff)
    p("Room mismatch", room_diff)

def main(path_a: str, path_b: str) -> None:
    a_data = json.loads(Path(path_a).read_text(encoding="utf-8"))
    b_data = json.loads(Path(path_b).read_text(encoding="utf-8"))

    flat_a = flatten(a_data)
    flat_b = flatten(b_data)

    print(f"📑  Entries in A : {len(flat_a):>4}")
    print(f"📑  Entries in B : {len(flat_b):>4}")

    compare(flat_a, flat_b)

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Usage: python compare_elective_timetables.py <fileA.json> <fileB.json>")
    main(sys.argv[1], sys.argv[2])

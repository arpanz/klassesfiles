"""
Tests for tt_parser.py — covers:
  • deep_merge (fix #6: partial uploads must not wipe untouched days)
  • classify_change (fix #7: slot-level BIG/SMALL detection)
  • _slot_diff_stats (internal, but critical)
  • normalize_section
  • compute_changes (human-readable diff shape)
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from tt_parser import (
    deep_merge, classify_change, _slot_diff_stats,
    normalize_section, compute_changes,
    MAX_NEW_SECTIONS, MAX_TOUCHED_SECTIONS, MAX_OVERWRITTEN_SLOTS,
)

# ─── helpers ──────────────────────────────────────────────────────────────────
def slot(subject, room=None):
    e = {"subject": subject}
    if room:
        e["room"] = room
    return e

def make_tt(sections):
    """sections: {sec: {day: {slot: (subj, room)}}}"""
    out = {}
    for sec, days in sections.items():
        out[sec] = {}
        for day, slots in days.items():
            out[sec][day] = {s: slot(*v) if isinstance(v, tuple) else slot(v)
                             for s, v in slots.items()}
    return out

PASS = FAIL = 0

def check(label, got, expected):
    global PASS, FAIL
    if got == expected:
        print(f"  [PASS]  {label}")
        PASS += 1
    else:
        print(f"  [FAIL]  {label}")
        print(f"       got:      {got!r}")
        print(f"       expected: {expected!r}")
        FAIL += 1

def check_is(label, cond):
    global PASS, FAIL
    if cond:
        print(f"  [PASS]  {label}")
        PASS += 1
    else:
        print(f"  [FAIL]  {label}")
        FAIL += 1


# ═══════════════════════════════════════════════════════════════════════════════
# 1. normalize_section
# ═══════════════════════════════════════════════════════════════════════════════
print("\n== normalize_section ==================================================")
check("cse-1  -> CSE-01",  normalize_section("cse-1"),   "CSE-01")
check("cse-01 -> CSE-01",  normalize_section("cse-01"),  "CSE-01")
check("it-3   -> IT-03",   normalize_section("it-3"),    "IT-03")
check("csse-1 -> CSSE-01", normalize_section("csse-1"),  "CSSE-01")
check("empty  -> ''",      normalize_section(""),        "")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. deep_merge  (fix #6)
# ═══════════════════════════════════════════════════════════════════════════════
print("\n== deep_merge ==========================================================")

# 2a. Partial upload must NOT wipe untouched days
old = make_tt({"CSE-01": {
    "Monday":  {"8-9": ("ML", "C25-A-201")},
    "Tuesday": {"9-10": ("DBMS", "C25-A-202")},
}})
new = make_tt({"CSE-01": {"Monday": {"8-9": ("AI", "C25-A-201")}}})
merged = deep_merge(old, new)
check("partial upload: Monday slot overwritten",
      merged["CSE-01"]["Monday"]["8-9"]["subject"], "AI")
check("partial upload: Tuesday day preserved",
      merged["CSE-01"]["Tuesday"]["9-10"]["subject"], "DBMS")

# 2b. New slot added within an existing day
old2 = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",)}}})
new2 = make_tt({"CSE-01": {"Monday": {"9-10": ("AI",)}}})
merged2 = deep_merge(old2, new2)
check("new slot added, existing slot preserved",
      merged2["CSE-01"]["Monday"].get("8-9", {}).get("subject"), "ML")
check("new slot present",
      merged2["CSE-01"]["Monday"]["9-10"]["subject"], "AI")

# 2c. New section added
old3 = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",)}}})
new3 = make_tt({"IT-01":  {"Monday": {"8-9": ("OS",)}}})
merged3 = deep_merge(old3, new3)
check("existing section preserved when new section added",
      "CSE-01" in merged3, True)
check("new section present",
      merged3["IT-01"]["Monday"]["8-9"]["subject"], "OS")

# 2d. Completely separate days merged
old4 = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",)}}})
new4 = make_tt({"CSE-01": {"Wednesday": {"10-11": ("DS",)}}})
merged4 = deep_merge(old4, new4)
check("separate day merge: Monday preserved",
      "8-9" in merged4["CSE-01"]["Monday"], True)
check("separate day merge: Wednesday added",
      merged4["CSE-01"]["Wednesday"]["10-11"]["subject"], "DS")

# 2e. Original not mutated
import copy as _copy
old5 = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",)}}})
old5_copy = _copy.deepcopy(old5)
_ = deep_merge(old5, make_tt({"CSE-01": {"Monday": {"8-9": ("AI",)}}}))
check("original not mutated by deep_merge",
      old5, old5_copy)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. _slot_diff_stats
# ═══════════════════════════════════════════════════════════════════════════════
print("\n== _slot_diff_stats ====================================================")

base = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",), "9-10": ("AI",)}}})

# 3a. No changes
ns, ow, rm = _slot_diff_stats(base, base)
check("identical: new=0, overwritten=0, removed=0", (ns, ow, rm), (0, 0, 0))

# 3b. Slot overwritten
upd = make_tt({"CSE-01": {"Monday": {"8-9": ("DS",), "9-10": ("AI",)}}})
ns, ow, rm = _slot_diff_stats(base, upd)
check("1 slot overwritten", (ns, ow, rm), (0, 1, 0))

# 3c. New slot filled in
upd2 = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",), "9-10": ("AI",), "10-11": ("OS",)}}})
ns, ow, rm = _slot_diff_stats(base, upd2)
check("1 new slot", (ns, ow, rm), (1, 0, 0))

# 3d. Slot deleted
upd3 = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",)}}})
ns, ow, rm = _slot_diff_stats(base, upd3)
check("1 slot removed", (ns, ow, rm), (0, 0, 1))

# Note: whole-section adds/removes are NOT counted by _slot_diff_stats
# (they're handled separately in classify_change)
new_sec = make_tt({"IT-01": {"Monday": {"8-9": ("OS",)}}})
ns, ow, rm = _slot_diff_stats(base, deep_merge(base, new_sec))
check("new section added: slot stats still 0", (ns, ow, rm), (0, 0, 0))


# ═══════════════════════════════════════════════════════════════════════════════
# 4. classify_change  (fix #7)
# ═══════════════════════════════════════════════════════════════════════════════
print("\n== classify_change =====================================================")

def lvl(old, new):
    level, reasons = classify_change(old, new)
    return level, reasons

# 4a. Identical -> SMALL
tt = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",)}}})
l, r = lvl(tt, tt)
check("identical timetable -> SMALL", l, "SMALL")

# 4b. Single slot edit -> SMALL
old6 = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",), "9-10": ("AI",)}}})
new6 = make_tt({"CSE-01": {"Monday": {"8-9": ("DS",), "9-10": ("AI",)}}})
l, _ = lvl(old6, deep_merge(old6, new6))
check("single slot edit -> SMALL", l, "SMALL")

# 4c. MAX_OVERWRITTEN_SLOTS + 1 -> BIG
many_slots_old = make_tt({"CSE-01": {"Monday": {f"{h}-{h+1}": (f"S{h}",) for h in range(8, 8 + MAX_OVERWRITTEN_SLOTS + 1)}}})
many_slots_new = make_tt({"CSE-01": {"Monday": {f"{h}-{h+1}": ("WRONG",) for h in range(8, 8 + MAX_OVERWRITTEN_SLOTS + 1)}}})
l, r = lvl(many_slots_old, deep_merge(many_slots_old, many_slots_new))
check(f">{MAX_OVERWRITTEN_SLOTS} slots overwritten -> BIG", l, "BIG")
check_is("reason mentions overwritten slots", any("overwritten" in x for x in r))

# 4d. Exactly MAX_OVERWRITTEN_SLOTS -> SMALL (boundary)
boundary_old = make_tt({"CSE-01": {"Monday": {f"{h}-{h+1}": (f"S{h}",) for h in range(8, 8 + MAX_OVERWRITTEN_SLOTS)}}})
boundary_new = make_tt({"CSE-01": {"Monday": {f"{h}-{h+1}": ("WRONG",) for h in range(8, 8 + MAX_OVERWRITTEN_SLOTS)}}})
l, _ = lvl(boundary_old, deep_merge(boundary_old, boundary_new))
check(f"exactly {MAX_OVERWRITTEN_SLOTS} slots overwritten -> SMALL (at boundary)", l, "SMALL")

# 4e. Any existing slot deleted -> BIG
old_del = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",), "9-10": ("AI",)}}})
new_del = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",)}}})   # 9-10 gone
l, r = lvl(old_del, new_del)
check("1 deleted slot -> BIG", l, "BIG")
check_is("reason mentions deleted slot", any("deleted" in x for x in r))

# 4f. Section removed -> BIG
old_rm = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",)}}, "IT-01": {"Monday": {"8-9": ("OS",)}}})
new_rm = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",)}}})
l, r = lvl(old_rm, new_rm)
check("section removed -> BIG", l, "BIG")
check_is("reason mentions removed section", any("removed" in x for x in r))

# 4g. > MAX_NEW_SECTIONS new sections -> BIG
old_ns = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",)}}})
adds = {"CSE-01": {"Monday": {"8-9": ("ML",)}}}
for i in range(MAX_NEW_SECTIONS + 1):
    adds[f"NEW-{i:02d}"] = {"Monday": {"8-9": ("X",)}}
new_ns = make_tt(adds)
l, r = lvl(old_ns, new_ns)
check(f">{MAX_NEW_SECTIONS} new sections -> BIG", l, "BIG")
check_is("reason mentions new sections", any("new section" in x for x in r))

# 4h. Exactly MAX_NEW_SECTIONS new sections -> SMALL (boundary)
adds2 = {"CSE-01": {"Monday": {"8-9": ("ML",)}}}
for i in range(MAX_NEW_SECTIONS):
    adds2[f"NEW-{i:02d}"] = {"Monday": {"8-9": ("X",)}}
l, _ = lvl(old_ns, make_tt(adds2))
check(f"exactly {MAX_NEW_SECTIONS} new sections -> SMALL (boundary)", l, "SMALL")

# 4i. > MAX_TOUCHED_SECTIONS sections changed -> BIG
many_secs = {f"S-{i:02d}": {"Monday": {"8-9": ("OLD",)}} for i in range(MAX_TOUCHED_SECTIONS + 1)}
old_mt = make_tt(many_secs)
new_mt_dict = {k: {"Monday": {"8-9": ("NEW",)}} for k in many_secs}
l, r = lvl(old_mt, make_tt(new_mt_dict))
check(f">{MAX_TOUCHED_SECTIONS} sections touched -> BIG", l, "BIG")

# 4j. Fresh file (no old) always SMALL (first upload)
l, _ = lvl({}, make_tt({"CSE-01": {"Monday": {"8-9": ("ML",)}}}))
check("first upload (empty old) -> SMALL", l, "SMALL")



# ═══════════════════════════════════════════════════════════════════════════════
# 6. compute_changes (diff output)
# ═══════════════════════════════════════════════════════════════════════════════
print("\n== compute_changes =====================================================")
old_c = make_tt({"CSE-01": {"Monday": {"8-9": ("ML",), "9-10": ("AI",)}}})
new_c = make_tt({"CSE-01": {"Monday": {"8-9": ("DS",)}}})

changes = compute_changes(old_c, new_c)
joined = "\n".join(changes)
check_is("modified section appears in summary",
         any("CSE-01" in c for c in changes))
check_is("removed slot shown",
         any("removed" in c for c in changes))
check_is("no-change yields 'No content changes'",
         "No content changes" in "\n".join(compute_changes(old_c, old_c)))


# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  Results: {PASS} passed, {FAIL} failed")
print(f"{'='*60}")
if FAIL:
    sys.exit(1)

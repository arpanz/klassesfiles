"""
Tests for validate.py — structural validation gate.
"""
import sys, os, io
from contextlib import redirect_stdout
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import validate as V
import argparse

PASS = FAIL = 0

def check(label, got, expected):
    global PASS, FAIL
    if got == expected:
        print(f"  ✓  {label}")
        PASS += 1
    else:
        print(f"  ✗  {label}")
        print(f"       got:      {got!r}")
        print(f"       expected: {expected!r}")
        FAIL += 1

def check_is(label, cond):
    global PASS, FAIL
    if cond:
        print(f"  ✓  {label}")
        PASS += 1
    else:
        print(f"  ✗  {label}")
        FAIL += 1

def args(batch=2023, semester=6, pe3=False):
    a = argparse.Namespace()
    a.batch = batch; a.semester = semester; a.pe3 = pe3
    return a

def run_validate(data):
    """Returns (ok, output_text). ok=True means validation passed."""
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            V.validate(data, args())
        return True, buf.getvalue()
    except SystemExit:
        return False, buf.getvalue()


print("\n── validate: PASSING cases ─────────────────────────────────────────────")

ok, out = run_validate({"CSE-01": {"Monday": {"8-9": {"subject": "ML", "room": "C25-A-201"}}}})
check("valid single section passes", ok, True)
check_is("prints VALIDATION_OK", "VALIDATION_OK" in out)

ok, _ = run_validate({
    "CSE-01": {"Monday":    {"8-9":   {"subject": "ML"}}},
    "IT-01":  {"Tuesday":   {"9-10":  {"subject": "OS"}}},
    "CSSE-01":{"Wednesday": {"10-11": {"subject": "AI"}}},
})
check("multiple sections pass", ok, True)

ok, _ = run_validate({"CSSE-01": {"Monday": {"8-9": {"subject": "NLP"}}}})
check("CSSE-XX section format passes", ok, True)

ok, _ = run_validate({"IT-01": {"Monday": {"8-9": {"subject": "DS"}}}})
check("IT-XX section format passes", ok, True)


print("\n── validate: FAILING cases ─────────────────────────────────────────────")

ok, out = run_validate({})
check("empty data fails", ok, False)
check_is("VALIDATION_FAILED in output", "VALIDATION_FAILED" in out)

ok, out = run_validate({"cse-1": {"Monday": {"8-9": {"subject": "ML"}}}})
check("lowercase / single-digit section rejected", ok, False)
check_is("bad section reason in output", "Bad section" in out)

ok, out = run_validate({"CSE-01": {"Monday": {"8-9": {"subject": ""}}}})
check("empty subject rejected", ok, False)

ok, out = run_validate({"CSE-01": {"Monday": {"8-9": {"subject": "PE-3"}}}})
check("unresolved PE-3 placeholder rejected", ok, False)
check_is("unresolved elective reason in output", "unresolved elective" in out)

ok, out = run_validate({"CSE-01": {"Monday": {"8-9": {"subject": "PE-III"}}}})
check("unresolved PE-III placeholder rejected", ok, False)

ok, out = run_validate({"CSE-01": {"Monday": {"8-9": {"subject": "CC|SPM|NLP"}}}})
check("pipe-separated passes without --pe3 (expected — pipes only flagged in pe3 mode)", ok, True)

# Pipe-separated IS rejected when --pe3 mode is active
def run_validate_pe3(data):
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            V.validate(data, argparse.Namespace(batch=2023, semester=6, pe3=True))
        return True, buf.getvalue()
    except SystemExit:
        return False, buf.getvalue()

ok_pe3, _ = run_validate_pe3({"CSE-01": {"Monday": {"8-9": {"subject": "CC|SPM|NLP"}}}})
check("pipe-separated rejected when --pe3 is active", ok_pe3, False)

ok, out = run_validate({"CSE-01": {"Monday": {}}})
check("section with no days rejected", ok, False)

# Multiple errors — only first 10 shown but all detected
bad = {f"bad{i}": {"Mon": {"8-9": {"subject": "PE-3"}}} for i in range(5)}
ok, out = run_validate(bad)
check("multiple bad sections all rejected", ok, False)


print(f"\n{'═'*60}")
print(f"  Results: {PASS} passed, {FAIL} failed")
print(f"{'═'*60}")
if FAIL:
    sys.exit(1)

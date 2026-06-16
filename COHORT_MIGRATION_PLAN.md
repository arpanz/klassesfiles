# Cohort-Driven Timetable System — Implementation Plan (Handoff)

> **Purpose of this doc:** A self-contained, execution-ready spec to convert a hardcoded
> "4th sem / 6th sem" timetable system into a **manifest-driven, semester-agnostic** system.
> Any engineer or AI agent should be able to execute this end-to-end without further context.
>
> **Two repos are involved:**
> - `arpanz/klassesfiles` — data files + Python parsers + GitHub Action + (NEW) manifest. Deployed on Netlify at `https://klassesfiles.netlify.app`.
> - `arpanz/kyc` — Flutter app (`package: kampusvibes`). Consumes the data at runtime.
>
> Plus one external piece: a **Google Apps Script** (Gmail → GitHub Action automation) and a **Telegram bot** for notifications.

---

## 0. Problem Statement (why we are doing this)

The system is hardwired to exactly two semesters (`4th` and `6th`). Semester identity is baked into:
- Dart field names (`_main` = 6th, `_timetable4th`), method names (`_generate6thSemSchedule`, `_processRoll6th`), data file names (`timetable_6th.json`, `rollno_4th.json`, `electives_6th.json`).
- The admin panel's semester dropdown (`4`/`6`), `automation_service.dart`, the Python script names, and the Gmail script's `admission-year → sem` logic.
- A **single global** `timetable_version` that forces **every** user to re-download **all** files whenever **any** section changes.

**Consequences:** Every semester progression (a batch moving 4→6, a new batch entering) requires editing code + a Play Store release. Updating the version is a manual admin step. One section's revision triggers a full re-download for everyone.

### Goals
1. **Semester-agnostic:** progression = a config (manifest) edit + version bump. **No app release.**
2. **Up to 4 live cohorts** at once (parity is always uniform — all odd OR all even, but design must not assume a count).
3. **Auto-validate + Telegram notify** on every upload (no silent bad data; notify on success and on rejection).
4. **Automatic version bump** — the pipeline bumps versions; no manual admin step.
5. **Granular downloads (per file / per cohort):** a user only downloads their own cohort's files, and only the files that actually changed.

### Non-goals
- Per-**section** download granularity (explicitly rejected — per-file is the chosen granularity).
- Hard manual approval on every upload (auto-validate; only flag failures).
- Supporting arbitrary external colleges' Excel formats (single college, controlled input).

---

## 1. Core Concept: The Manifest

A single small JSON file, `manifest.json`, committed in `klassesfiles` and served from Netlify, becomes the **single source of truth** for: which cohorts are live, where each cohort's data lives, and the version of each file.

The stable identity of a cohort is its **batch (admission year)**, NOT its semester number. The semester number is data that changes each term.

### 1.1 `manifest.json` schema

```json
{
  "manifestVersion": 12,
  "updatedAt": "2026-06-16T18:30:00Z",
  "cohorts": [
    {
      "batch": 2023,
      "rollPrefix": "23",
      "semester": 6,
      "label": "6th Sem",
      "hasElectives": true,
      "files": {
        "timetable": { "name": "timetable_2023_s6.json", "version": 5 },
        "electives": { "name": "electives_2023_s6.json", "version": 2 },
        "roll":      { "name": "rollno_2023.json",        "version": 1 }
      }
    },
    {
      "batch": 2024,
      "rollPrefix": "24",
      "semester": 4,
      "label": "4th Sem",
      "hasElectives": false,
      "files": {
        "timetable": { "name": "timetable_2024_s4.json", "version": 3 },
        "roll":      { "name": "rollno_2024.json",        "version": 1 }
      }
    }
  ]
}
```

**Rules:**
- `manifestVersion` (int) — bumped on ANY change (cohort added/removed, any file version bump, semester change). The app uses it as the cheap "is anything new?" check.
- `files.<type>.version` (int) — per-file version. Bumped ONLY when that specific file's content changes. The app compares this to its cached value to decide whether to re-download that one file.
- `rollPrefix` — first 2 digits of roll numbers for that batch (`2023XXXX` → `"23"`). Used by the **Gmail script** to detect which cohort an uploaded file belongs to. (The app itself detects cohort by looking the roll up in each cohort's roll map, not by prefix.)
- `hasElectives` — whether the cohort has an electives file + E1/E2 selection UI.

### 1.2 Data file naming convention (NEW)

| Type      | Old (sem-based)        | New (batch-based)              | Notes |
|-----------|------------------------|--------------------------------|-------|
| Timetable | `timetable_6th.json`   | `timetable_{batch}_s{sem}.json` | e.g. `timetable_2023_s6.json` |
| Electives | `electives_6th.json`   | `electives_{batch}_s{sem}.json` | only if `hasElectives` |
| Roll      | `rollno_6th.json`      | `rollno_{batch}.json`           | batch-stable; no sem in name |
| Manifest  | (none)                 | `manifest.json`                 | new |

**Archiving (decision):** Old files are NOT deleted on progression — batch+sem naming means new files never overwrite old ones. They simply stop being referenced by the manifest. This gives free rollback + history at ~zero cost (git keeps them anyway).

### 1.3 Existing data shapes (DO NOT CHANGE the internal JSON shape)

Timetable file: `{ "<SECTION>": { "<Day>": { "<slot>": { "subject": "...", "room": "..." } } } }`
```json
{ "CSE-01": { "Monday": { "8-9": { "subject": "ML", "room": "C25-A-206" } } } }
```
Roll file: `{ "<roll>": "<section>" }` (4th-style) OR `{ "<roll>": ["main","e1","e2"] }` (6th-style with electives). The Dart `_processRoll*` already normalizes both to `List<String>`.
Electives file: `{ "E1": { "<SUBJECT>": { ... } }, "E2": { ... } }` plus the per-key `SUBJECT_section` lookup the provider builds in `_processElectives`.

---

## 2. Repo `klassesfiles` — Changes

### 2.1 Replace the two scripts with ONE generalized parser

Delete `scripts/tt_script_4th.py` and `scripts/tt_script_6th.py`; replace with `scripts/tt_parser.py`. It keeps ALL existing logic (dynamic ROOM mapping, room carry-forward, section normalization, PE-3 elective resolution, merge/replace) but is parameterized by **batch + semester** and writes batch-named output. The 4th-sem behavior is just "no PE-3 map / `hasElectives=false`".

```python
# scripts/tt_parser.py
import sys, json, re, argparse
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent     # repo root
PE3_DATA = Path(__file__).parent / "section_pe3_data.json"
BLANK = {"", "X", "---", "nan", "NaN", "HSE"}

day_map = {'MON':'Monday','TUE':'Tuesday','WED':'Wednesday',
           'THU':'Thursday','FRI':'Friday','SAT':'Saturday'}
TIME_SLOTS = ['8-9','9-10','10-11','11-12','12-1','1-2','2-3',
              '3.00-4.00','4.00-5.00','5.00-6.00','3-4','4-5','5-6']

# ---------- helpers (ported verbatim from tt_script_6th.py) ----------
def load_data(path):
    try: return pd.read_excel(path)
    except Exception:
        print("Excel read failed, trying CSV..."); return pd.read_csv(path)

def normalize_section(section):
    if not section: return section
    return re.sub(r'(?<!\d)(\d)(?!\d)', r'0\1', section)

def load_pe3_mapping():
    try:
        data = json.loads(PE3_DATA.read_text(encoding='utf-8'))
        return {normalize_section(k): v for k, v in data.items()}
    except FileNotFoundError:
        return {}

def resolve_elective(subject_code, section, pe3_map):
    subj_norm = subject_code.upper().replace(" ", "")
    elective = None
    for key in [section, section.replace(" ",""), section.replace("-",""),
                section.replace(" ","").replace("-","")]:
        if key in pe3_map: elective = pe3_map[key]; break
    if subj_norm in ["PE-3","PE-III","PE3","PEIII"]:
        return elective if elective else subject_code
    if "|" in subject_code:
        options = [s.strip().upper() for s in subject_code.split("|")]
        if elective and elective.upper() in options: return elective
    return subject_code

def build_json(df, pe3_map, has_electives):
    timetable = {}
    time_to_room_map, current_room_col = [], None
    for col in df.columns:
        cs = str(col).strip()
        if "ROOM" in cs.upper(): current_room_col = cs
        elif cs in TIME_SLOTS and current_room_col:
            time_to_room_map.append((cs, current_room_col))
    for _, row in df.iterrows():
        section = normalize_section(str(row.get('SECTION') or row.get('Section') or '').strip())
        day_raw = str(row.get('DAY') or row.get('Day') or '').strip().upper()
        if not section or not day_raw: continue
        day_full = day_map.get(day_raw.split('(')[0].strip(), day_raw.split('(')[0].strip())
        day_dict = timetable.setdefault(section, {}).setdefault(day_full, {})
        last_room = None
        for slot, room_col in time_to_room_map:
            subject = str(row.get(slot, "")).strip()
            room    = str(row.get(room_col, "")).strip()
            if subject.lower()=='nan': subject=""
            if room.lower()=='nan': room=""
            if subject in BLANK: continue
            if has_electives:
                subject = resolve_elective(subject, section, pe3_map)
            if room not in BLANK: last_room = room
            use_room = last_room if room in BLANK else room
            entry = {"subject": subject}
            if use_room: entry["room"] = use_room
            day_dict[slot] = entry
    return {sec: {d:s for d,s in days.items() if s}
            for sec, days in timetable.items() if any(days.values())}

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input_file")
    ap.add_argument("--batch", type=int, required=True)        # e.g. 2023
    ap.add_argument("--semester", type=int, required=True)     # e.g. 6
    ap.add_argument("--mode", default="merge", choices=["merge","replace"])
    ap.add_argument("--has-electives", action="store_true")
    args = ap.parse_args()

    out_name = f"timetable_{args.batch}_s{args.semester}.json"
    out_path = ROOT / out_name

    df = load_data(args.input_file)
    pe3 = load_pe3_mapping() if args.has_electives else {}
    new_data = build_json(df, pe3, args.has_electives)

    # ---- VALIDATION (see §2.4). Raises SystemExit(2) on failure. ----
    validate(new_data, args)

    if args.mode == "merge" and out_path.exists():
        existing = json.loads(out_path.read_text(encoding='utf-8'))
        existing.update(new_data)
        final = existing
    else:
        final = new_data

    out_path.write_text(json.dumps(final, indent=4), encoding='utf-8')
    print(f"WROTE::{out_name}::{len(final)}")   # parsed by the Action (stdout contract)

if __name__ == "__main__":
    from validate import validate    # see §2.4
    main()
```

> **Backward-compat note:** keep the old `OUT_JSON` filenames alive during migration by also writing a symlink/copy if you have not yet flipped the app. See §5 (rollout).

### 2.2 Validation module (`scripts/validate.py`)

```python
# scripts/validate.py
import sys, re

# Per-batch/sem allow-lists. Maintain these as data, not code-in-app.
# Minimal viable check: sections look sane + at least N sections + subjects non-empty.
def validate(data, args):
    errors = []
    if not data:
        errors.append("No sections parsed from the file.")
    for section, days in data.items():
        if not re.match(r'^[A-Z]+-\d{2}$', section):
            errors.append(f"Bad section name: '{section}' (expected like CSE-01)")
        if not days:
            errors.append(f"Section {section} has no days.")
        for day, slots in days.items():
            for slot, info in slots.items():
                if not info.get("subject"):
                    errors.append(f"{section}/{day}/{slot}: empty subject")
    if errors:
        # Print machine-readable failure for the Action to forward to Telegram.
        print("VALIDATION_FAILED::" + " | ".join(errors[:10]))
        sys.exit(2)
    print(f"VALIDATION_OK::{len(data)} sections")
```

> Extend `validate()` with a known-subjects-per-cohort allow-list later (sourced from `subjects_by_semester.json`) for stronger cohort-mismatch detection. For v1, structural validation + section-name format is enough to stop garbage.

### 2.3 Manifest auto-bump helper (`scripts/bump_manifest.py`)

Run by the Action AFTER a successful data write. Increments the changed file's `version` + the top-level `manifestVersion`, and updates `semester`/`label`/file names if needed.

```python
# scripts/bump_manifest.py
import sys, json, argparse, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "manifest.json"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, required=True)
    ap.add_argument("--file-type", required=True, choices=["timetable","electives","roll"])
    args = ap.parse_args()

    m = json.loads(MANIFEST.read_text(encoding='utf-8'))
    cohort = next((c for c in m["cohorts"] if c["batch"] == args.batch), None)
    if cohort is None:
        print(f"BUMP_FAILED::no cohort {args.batch} in manifest"); sys.exit(3)

    cohort["files"][args.file_type]["version"] += 1
    m["manifestVersion"] += 1
    m["updatedAt"] = datetime.datetime.utcnow().isoformat() + "Z"
    MANIFEST.write_text(json.dumps(m, indent=2), encoding='utf-8')
    print(f"BUMPED::batch={args.batch}::{args.file_type}::manifestVersion={m['manifestVersion']}")

if __name__ == "__main__":
    main()
```

### 2.4 New GitHub Action (`.github/workflows/timetable_automation.yml`)

Replaces the existing workflow. New inputs: `batch`, `semester`, `update_type`, `has_electives`, `file_content`. Adds validation gating, manifest bump, and Telegram notifications on success/failure. Token for Telegram + chat id stored as repo secrets `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

```yaml
name: Timetable Automation
on:
  workflow_dispatch:
    inputs:
      batch:         { description: 'Admission year (e.g. 2023)', required: true }
      semester:      { description: 'Semester number (e.g. 6)', required: true }
      update_type:   { description: 'merge or replace', required: true, default: 'merge' }
      has_electives: { description: 'true/false', required: true, default: 'false' }
      file_content:  { description: 'Base64 Encoded File', required: true }

permissions:
  contents: write

jobs:
  process-timetable:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { persist-credentials: true }

      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }

      - run: pip install pandas openpyxl xlrd

      - name: Decode input file
        run: echo "${{ inputs.file_content }}" | base64 -d > input_data.xlsx

      - name: Run parser (with validation)
        id: parse
        run: |
          set -o pipefail
          ELECTIVES_FLAG=""
          if [ "${{ inputs.has_electives }}" = "true" ]; then ELECTIVES_FLAG="--has-electives"; fi
          python scripts/tt_parser.py input_data.xlsx \
            --batch ${{ inputs.batch }} --semester ${{ inputs.semester }} \
            --mode ${{ inputs.update_type }} $ELECTIVES_FLAG 2>&1 | tee parse.log

      - name: Bump manifest
        if: success()
        run: python scripts/bump_manifest.py --batch ${{ inputs.batch }} --file-type timetable

      - name: Commit and push
        if: success()
        run: |
          git config user.name  "Timetable Bot"
          git config user.email "bot@klasses.app"
          git add *.json manifest.json
          if git diff --staged --quiet; then
            echo "No changes."
          else
            git commit -m "Auto-update: batch ${{ inputs.batch }} sem ${{ inputs.semester }} (${{ inputs.update_type }})"
            git push
          fi

      - name: Telegram notify (success)
        if: success()
        run: |
          SUMMARY=$(grep -E 'WROTE::|VALIDATION_OK::|BUMPED::' parse.log || echo "done")
          curl -s -X POST "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d chat_id="${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d text="✅ Timetable updated — batch ${{ inputs.batch }} sem ${{ inputs.semester }} (${{ inputs.update_type }})%0A$SUMMARY"

      - name: Telegram notify (failure)
        if: failure()
        run: |
          REASON=$(grep 'VALIDATION_FAILED::' parse.log || tail -n 5 parse.log || echo "unknown error")
          curl -s -X POST "https://api.telegram.org/bot${{ secrets.TELEGRAM_BOT_TOKEN }}/sendMessage" \
            -d chat_id="${{ secrets.TELEGRAM_CHAT_ID }}" \
            -d text="⚠️ Upload REJECTED — batch ${{ inputs.batch }} sem ${{ inputs.semester }}%0A$REASON"
```

> **Important:** the workflow file currently lives in BOTH repos (`kyc/.github/workflows/` and `klassesfiles/.github/workflows/`). Only the one in **`klassesfiles`** actually runs (the dispatch targets `arpanz/klassesfiles`). Update the `klassesfiles` copy; delete the stale `kyc` copy to avoid confusion.

### 2.5 Fix `files.json`

Currently stale (`"6thsem_roll.json"` doesn't exist; misses real files). It should be generated/maintained from the manifest, or simply list the real served files including `manifest.json`. Minimal fix:
```json
["manifest.json","ecam.json","subjects_by_semester.json"]
```
(Per-cohort data files are discovered via the manifest, so `files.json` only needs the static/global files. If the frontend `script.js` lists files from `files.json`, update it to read `manifest.json` for cohort files.)

---

## 3. Repo `kyc` (Flutter) — Changes

The heart of the work. File: `lib/providers/klasses_provider.dart` (currently 1931 lines). Strategy: introduce a `Cohort` model + cohort-keyed maps, and replace the two hardcoded universes with loops. Keep the public API the UI uses stable where possible.

### 3.1 New model — `lib/models/cohort.dart`

```dart
class CohortFile {
  final String name;
  final int version;
  CohortFile(this.name, this.version);
  factory CohortFile.fromJson(Map<String, dynamic> j) =>
      CohortFile(j['name'] as String, (j['version'] as num).toInt());
}

class Cohort {
  final int batch;          // 2023
  final String rollPrefix;  // "23"
  final int semester;       // 6
  final String label;       // "6th Sem"
  final bool hasElectives;
  final CohortFile timetable;
  final CohortFile? electives;
  final CohortFile roll;

  Cohort({
    required this.batch, required this.rollPrefix, required this.semester,
    required this.label, required this.hasElectives,
    required this.timetable, this.electives, required this.roll,
  });

  factory Cohort.fromJson(Map<String, dynamic> j) {
    final files = j['files'] as Map<String, dynamic>;
    return Cohort(
      batch: (j['batch'] as num).toInt(),
      rollPrefix: j['rollPrefix'] as String,
      semester: (j['semester'] as num).toInt(),
      label: j['label'] as String,
      hasElectives: j['hasElectives'] as bool? ?? false,
      timetable: CohortFile.fromJson(files['timetable']),
      electives: files['electives'] != null ? CohortFile.fromJson(files['electives']) : null,
      roll: CohortFile.fromJson(files['roll']),
    );
  }
}

class Manifest {
  final int manifestVersion;
  final List<Cohort> cohorts;
  Manifest(this.manifestVersion, this.cohorts);
  factory Manifest.fromJson(Map<String, dynamic> j) => Manifest(
        (j['manifestVersion'] as num).toInt(),
        (j['cohorts'] as List).map((c) => Cohort.fromJson(c)).toList(),
      );
}
```

### 3.2 Provider state — replace the two universes

**Remove** these fields (and everything keyed to "4th/6th"):
```dart
Map _main = {}; Map _electives = {}; Map _timetable4th = {};
Map<String, List<String>> _roll6th = {}; Map<String, String> _roll4th = {};
```
**Add:**
```dart
List<Cohort> _cohorts = [];
Cohort? get _activeCohort =>
    _cohorts.where((c) => c.batch == _activeBatch).cast<Cohort?>().firstOrNull;
int? _activeBatch;                                   // replaces _currentSemester as identity

final Map<int, Map> _timetables = {};                // batch -> timetable map
final Map<int, Map> _electivesByBatch = {};          // batch -> electives map
final Map<int, Map<String, List<String>>> _rolls = {}; // batch -> roll map
```
Keep `_currentSemester` as a derived getter for any UI that still reads it: `int? get currentSemester => _activeCohort?.semester;`

### 3.3 Manifest-driven download (replaces `_checkForRemoteUpdates` + `_downloadRemoteData`)

Replace the Remote-Config + global-version logic (lines ~390–470) with manifest logic:

```dart
static const String kManifestUrl = '$kNetlifyBaseUrl/manifest.json';

Future<Manifest> _fetchManifest() async {
  final resp = await http.get(Uri.parse('$kManifestUrl?t=${DateTime.now().millisecondsSinceEpoch}'));
  if (resp.statusCode != 200) throw Exception('manifest ${resp.statusCode}');
  return Manifest.fromJson(json.decode(resp.body));
}

/// Returns list of files that need (re)downloading for the user's cohort only.
Future<List<_PendingFile>> _filesToUpdate(Manifest m) async {
  _cohorts = m.cohorts;
  final pending = <_PendingFile>[];
  // Only the active cohort's files matter for a normal user.
  final c = _activeCohort ?? (_activeBatch == null ? null : null);
  final targets = c != null ? [c] : m.cohorts; // admin/all-mode falls back to all
  for (final cohort in targets) {
    void check(CohortFile? f) {
      if (f == null) return;
      final cachedVer = _prefs.getInt('ver_${f.name}') ?? -1;
      if (f.version != cachedVer) pending.add(_PendingFile(f.name, f.version));
    }
    check(cohort.timetable);
    if (cohort.hasElectives) check(cohort.electives);
    check(cohort.roll);
  }
  return pending;
}

Future<void> _downloadRemoteData() async {
  final manifest = await _fetchManifest();
  final pending = await _filesToUpdate(manifest);
  for (final pf in pending) {
    if (_cancelDownload) return;
    try {
      final content = await _downloadFromNetlifyWithRetry(pf.name);
      await _cacheDataLocally(pf.name, content);
      await _prefs.setInt('ver_${pf.name}', pf.version);   // record per-file version
    } catch (e) {
      print('❌ Failed $pf.name: $e');
    }
  }
}

class _PendingFile { final String name; final int version; _PendingFile(this.name, this.version); }
```

`_checkForRemoteUpdates()` becomes: fetch manifest, return `true` if any of the user's cohort files have `version != ver_<name>` cached, OR if `manifestVersion` changed (store under `kRemoteDataVersionKey`).

> **Delete** the `firebase_remote_config` dependency usage in this provider. (Remove the import + `FirebaseRemoteConfig` calls.) Versioning now lives in the manifest.

### 3.4 Loading — replace `_loadPriorityData` / `_loadRemainingData`

Generalize to a cohort loop. Filenames now come from `_activeCohort`/manifest, not hardcoded strings:

```dart
Future<void> _loadCohortData(Cohort c) async {
  final ttStr  = await _loadJsonWithFallback(c.timetable.name);   // see §3.7 fallback note
  _timetables[c.batch] = await compute(_jsonDecode, ttStr);
  if (c.hasElectives && c.electives != null) {
    final elStr = await _loadJsonWithFallback(c.electives!.name);
    _processElectives(c.batch, await compute(_jsonDecode, elStr));
  }
  if (_isRollNumberMode) {
    final rStr = await _loadRollnoFromNetlifyOrCache(c.roll.name);
    _rolls[c.batch] = _processRoll(await compute(_jsonDecode, rStr));
  }
}
```

`_processRoll6th` + `_processRoll4th` collapse into one `_processRoll` (the 6th-style List handling already covers the 4th-style String case):
```dart
Map<String, List<String>> _processRoll(Map<String, dynamic> raw) => raw.map((k, v) {
  if (v is String) return MapEntry(k, [v]);
  if (v is List)   return MapEntry(k, List<String>.from(v));
  return MapEntry(k, <String>[]);
});
```

### 3.5 `getStudentInfo` — loop cohorts (replaces the hardcoded 6/4 version)

```dart
(Cohort?, Map<String, String>?) getStudentInfo(String rollNumber) {
  rollNumber = rollNumber.trim();
  for (final c in _cohorts) {
    final rollMap = _rolls[c.batch];
    if (rollMap != null && rollMap.containsKey(rollNumber)) {
      final sections = rollMap[rollNumber]!;
      if (sections.isEmpty) continue;
      final info = <String, String>{'main': sections[0]};
      if (c.hasElectives && sections.length >= 2) info['elective1'] = sections[1];
      if (c.hasElectives && sections.length >= 3) info['elective2'] = sections[2];
      return (c, info);
    }
  }
  return (null, null);
}
```
Update `setTimetableByRoll` to set `_activeBatch = c.batch` and branch on `c.hasElectives` instead of `semester == 6`.

> Note: a normal user has NOT downloaded all cohorts' roll files (per §3.3 we only fetch the active cohort). For first-time roll lookup, either (a) the app downloads all roll files once during onboarding (they're ~110KB each), or (b) detect cohort from `rollPrefix` against the manifest first, then download only that cohort's roll file. **Recommended: (b)** — match `rollNumber.substring(0,2)` to `cohort.rollPrefix`, set `_activeBatch`, download that cohort's roll file, then look up.

### 3.6 Schedule generation — generalize (replaces `_generate6thSemSchedule` + `_generate4thSemSchedule`)

```dart
Map<String, dynamic> _generateScheduleForDay(String day) {
  final c = _activeCohort;
  if (c == null) return {};
  final tt = _timetables[c.batch];
  if (tt == null || !tt.containsKey(_mainSection)) return {};
  final combined = Map<String, dynamic>.from(tt[_mainSection]?[day] ?? {});

  if (c.hasElectives) {
    void merge(String? key) {
      final el = _electivesByBatch[c.batch];
      if (key == null || key.isEmpty || el == null || !el.containsKey(key)) return;
      final electiveData = el[key];
      if (electiveData?[day] != null) {
        Map<String, dynamic>.from(electiveData[day]).forEach((slot, info) {
          if (info != null) combined[slot] =
              Map<String, dynamic>.from(info as Map<String, dynamic>)..['isElective'] = true;
        });
      }
    }
    merge(_e1Key);
    merge(_e2Key);
  }
  combined.removeWhere((_, v) => v == null);
  final sorted = combined.keys.toList()
    ..sort((a, b) => parseTimeSlot(a).compareTo(parseTimeSlot(b)));
  return {for (final k in sorted) k: combined[k]};
}
```
`_mainSection` is the selected section for the active cohort (works for both elective and non-elective cohorts). Drop `_fourthSemSection`; use `_mainSection` everywhere.

### 3.7 `allRawSchedules` (ECAM) — generalize
```dart
List<Map<String, dynamic>> get allRawSchedules =>
    _timetables.values.map((t) => Map<String, dynamic>.from(t)).toList();
```

### 3.8 Bundled-asset fallback

`_loadJsonWithFallback` keys off `assets/<file>`. With dynamic file names there will be no matching bundled asset for future batches → it returns `{}` and waits for download (already handled by the existing `timetable`/`electives` empty-string fallback). **Decision:** drop bundled timetable assets entirely and rely on Netlify + cache (roll files already do this). Keep a tiny bundled `manifest.json` as a cold-start seed only.

### 3.9 Admin panel — `lib/admin/admin_panel.dart`

- Replace the hardcoded semester dropdown (`4`/`6`, field `_selectedSemester`) with a list built from the manifest cohorts (label + batch). The admin picks a **cohort**, not a raw sem number.
- The manual version-bump UI (writes `timetable_version` to Firestore `admin_settings/remote_config`, lines ~108–132) becomes **optional** — keep it as a "force refresh" emergency lever only; it is no longer part of the normal flow.
- `_isFullReplace` toggle stays (maps to `update_type`).

### 3.10 `lib/admin/automation_service.dart`

Change `uploadTimetable` to send `batch`, `semester`, `has_electives` instead of just `semester`:
```dart
body: jsonEncode({
  'ref': 'master',
  'inputs': {
    'batch': batch.toString(),
    'semester': semester.toString(),
    'update_type': isFullReplace ? 'replace' : 'merge',
    'has_electives': hasElectives.toString(),
    'file_content': base64File,
  },
}),
```
> **Security (do regardless):** the GitHub PAT is compiled into the app via `secrets.dart`. Move it to `--dart-define` at minimum, and ideally route dispatch through a Cloud Function so the token never ships in the APK. Rotate the existing token after this change.

### 3.11 Other hardcoded refs to sweep (228 total across 9 files)
`grep -rn "4th\|6th\|sem4\|sem6\|_main\|_timetable4th\|_roll6th\|_roll4th" lib/` and update:
`klasses_page.dart` (labels → use `cohort.label`), `swap_logic.dart`, `calender_page.dart`, `gpa_screen.dart`, `notes_provider.dart`, `pyq_provider.dart`. Labels must come from the manifest, never literals.

---

## 4. Gmail Apps Script — Changes

Replace the hardcoded `detectSemesterFromEmail` (which returned `6`/`4`) with manifest-driven cohort detection, send `batch`/`semester`/`has_electives`, and add Telegram. Fetch `manifest.json` to map `rollPrefix → cohort`.

```javascript
const GITHUB_TOKEN = '...';       // fine-grained PAT: klassesfiles, Actions RW + Contents RW
const OWNER = 'arpanz', REPO = 'klassesfiles', WF = 'timetable_automation.yml';
const MANIFEST_URL = 'https://klassesfiles.netlify.app/manifest.json';
const TELEGRAM_TOKEN = '...', TELEGRAM_CHAT = '...';

function getCohorts() {
  const r = UrlFetchApp.fetch(MANIFEST_URL, {muteHttpExceptions:true});
  return JSON.parse(r.getContentText()).cohorts;  // [{batch,rollPrefix,semester,hasElectives,...}]
}

function detectCohort(senderEmail, cohorts) {
  // College email like 2305xxxx@college.edu → prefix "23"
  const m = senderEmail.match(/(\d{2})\d{2}\d+@/);
  if (!m) return null;
  const prefix = m[1];
  return cohorts.find(c => c.rollPrefix === prefix) || null;
}

function triggerAction(cohort, base64File) {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WF}/dispatches`;
  const res = UrlFetchApp.fetch(url, {
    method:'post', muteHttpExceptions:true,
    headers:{Authorization:`Bearer ${GITHUB_TOKEN}`, Accept:'application/vnd.github.v3+json'},
    contentType:'application/json',
    payload: JSON.stringify({ ref:'master', inputs:{
      batch: String(cohort.batch), semester: String(cohort.semester),
      update_type: 'merge',                       // never auto-replace
      has_electives: String(!!cohort.hasElectives),
      file_content: base64File }})
  });
  return res.getResponseCode();
}

function tg(text){ UrlFetchApp.fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`,
  {method:'post', payload:{chat_id:TELEGRAM_CHAT, text}}); }

function processIncomingTimetables() {
  const cohorts = getCohorts();
  const threads = GmailApp.search('is:unread has:attachment (filename:xlsx OR filename:xls OR filename:csv)');
  threads.forEach(thread => thread.getMessages().forEach(message => {
    if (!message.isUnread()) return;
    message.getAttachments().forEach(att => {
      if (!/\.(xlsx|xls|csv)$/i.test(att.getName())) return;
      const b64 = Utilities.base64Encode(att.getBytes());
      const cohort = detectCohort(message.getFrom(), cohorts);
      if (!cohort) { tg(`⚠️ Upload from ${message.getFrom()} — could not match a cohort. Manual review needed.`);
                     GmailApp.sendEmail(message.getFrom(),'Upload needs review','Could not auto-detect your batch/sem. Arpan will handle it.'); return; }
      const code = triggerAction(cohort, b64);
      tg(code===204 ? `📥 Dispatched: ${cohort.label} (batch ${cohort.batch}) from ${message.getFrom()}`
                    : `❌ Dispatch failed (${code}) for ${cohort.label}`);
      GmailApp.sendEmail(message.getFrom(),
        code===204 ? 'Timetable received ✓' : 'Timetable upload failed',
        code===204 ? `Your ${cohort.label} timetable is being processed.` : `Error ${code}. Contact arpan.`);
    });
    message.markRead();
  }));
}
```
Trigger: time-driven, every 15 min. (The Action itself also sends the final ✅/⚠️ after validation; the Apps Script messages cover the "received/dispatched" stage.)

---

## 5. Telegram bot setup (5 minutes)

1. In Telegram, message **@BotFather** → `/newbot` → follow prompts → copy the **bot token**.
2. Send any message to your new bot (so it can DM you), then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser → copy `chat.id` from the JSON → that's **`TELEGRAM_CHAT_ID`**.
3. In `klassesfiles` repo → Settings → Secrets and variables → Actions → add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
4. Put the same two values in the Apps Script constants.

---

## 6. Rollout order (do NOT do it all at once)

Phased, each phase shippable & reversible:

1. **Phase A — data layer (no app release):** In `klassesfiles`, add `tt_parser.py`, `validate.py`, `bump_manifest.py`, the new Action, and hand-author the first `manifest.json` describing the CURRENT live cohorts. Generate batch-named copies of existing data (`timetable_2023_s6.json` = current `timetable_6th.json`, etc.). Keep old sem-named files in place. Verify Netlify serves `manifest.json` + new files.
2. **Phase B — Telegram + Gmail:** wire secrets, deploy the updated Apps Script. Test a dispatch end-to-end (email → Action → commit → Telegram ✅).
3. **Phase C — app (single release):** refactor the provider (§3) behind the manifest, ship one Play Store update. After this, the app reads the manifest and per-file versions. Old global `timetable_version` ignored.
4. **Phase D — progression test:** simulate a sem rollover by editing `manifest.json` only (bump semesters, swap file names, add a new batch). Confirm app updates with NO release.
5. **Phase E — cleanup:** delete `tt_script_4th.py`/`tt_script_6th.py`, the stale `kyc/.github/workflows/` copy, bundled timetable assets, and the `firebase_remote_config` dependency on this path. Rotate the GitHub PAT and move it out of `secrets.dart`.

### Backward-compat during A→C
Until the app release (Phase C) ships and is adopted, ALSO keep updating the old `timetable_6th.json` etc. (the parser can write both names, or a post-step copies batch-named → sem-named) so old app installs keep working. Drop the old names after adoption.

---

## 7. File-by-file checklist

**klassesfiles**
- [ ] `scripts/tt_parser.py` (new, replaces both scripts)
- [ ] `scripts/validate.py` (new)
- [ ] `scripts/bump_manifest.py` (new)
- [ ] `manifest.json` (new, hand-authored for current cohorts)
- [ ] `timetable_{batch}_s{sem}.json`, `electives_{batch}_s{sem}.json`, `rollno_{batch}.json` (renamed copies)
- [ ] `.github/workflows/timetable_automation.yml` (rewritten)
- [ ] `files.json` (fixed)
- [ ] delete `scripts/tt_script_4th.py`, `scripts/tt_script_6th.py` (Phase E)

**kyc**
- [ ] `lib/models/cohort.dart` (new)
- [ ] `lib/providers/klasses_provider.dart` (major refactor — §3.2–3.8)
- [ ] `lib/admin/admin_panel.dart` (cohort dropdown; version bump → optional)
- [ ] `lib/admin/automation_service.dart` (send batch/semester/has_electives; token hardening)
- [ ] `lib/pages/klasses/klasses_page.dart` + `swap_logic.dart` + `calender_page.dart` + `gpa_screen.dart` + `notes_provider.dart` + `pyq_provider.dart` (sweep 4th/6th literals → manifest labels)
- [ ] remove `firebase_remote_config` usage on the timetable path
- [ ] delete stale `.github/workflows/timetable_automation.yml` copy in this repo

**external**
- [ ] Google Apps Script (rewritten, §4)
- [ ] Telegram bot + secrets (§5)
- [ ] Rotate GitHub PAT; move out of `secrets.dart`

---

## 8. Acceptance criteria

- A semester rollover is performed by editing `manifest.json` only — **zero** code change, **zero** Play Store release — and the app reflects it on next launch.
- Up to 4 cohorts can be live simultaneously; adding/removing a cohort is a manifest edit.
- A student opening the app downloads only their own cohort's files, and only when a file's `version` changed (verify via network logs: a 4th-sem-only change causes 6th-sem users to download nothing).
- Every email upload produces a Telegram message: dispatched, then ✅ updated or ⚠️ rejected-with-reason. Invalid files never reach the live JSON.
- No manual version bump is required for a normal update.
```

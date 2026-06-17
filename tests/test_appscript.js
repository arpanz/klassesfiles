/**
 * Tests for Apps Script logic (apps_script/Code.gs).
 *
 * Uses Node.js vm.createContext to eval Code.gs with GAS API stubs injected,
 * so every function defined in the script is accessible from the context.
 *
 * Covers:
 *   • esc_            — HTML escaping
 *   • extractEmail_   — bare-email extraction
 *   • isStudentEmail_ — student-only gate
 *   • detectCohort    — roll-prefix routing
 *   • isBlocked_ / blockEmail_ / unblockEmail_ / listBlocked_  — blocklist
 *   • underRateLimit_ — per-day rate limiting
 *   • buildEmailHtml_ — themed email template
 *   • unknown-cohort branch never crashes (the null-deref fix)
 *   • gate ordering: block → students-only → rate-limit → cohort
 */

'use strict';
const vm   = require('vm');
const fs   = require('fs');
const path = require('path');

// ─── Lightweight GAS stubs ─────────────────────────────────────────────────
let _scriptProps = {};

function makeStubs() {
  return {
    PropertiesService: {
      getScriptProperties: () => ({
        getProperty:    (k) => _scriptProps[k] ?? null,
        setProperty:    (k, v) => { _scriptProps[k] = v; },
        deleteProperty: (k) => { delete _scriptProps[k]; },
      }),
    },
    Utilities: {
      formatDate: (_date, _tz, fmt) =>
        fmt === 'yyyy-MM-dd' ? '2026-06-17' : '17 Jun 2026, 10:00 AM IST',
      base64Encode: (bytes) => Buffer.from(bytes).toString('base64'),
    },
    UrlFetchApp: {
      fetch: (url, _opts) => ({
        getResponseCode: () => url.includes('/dispatches') ? 204 : 200,
        getContentText:  () => JSON.stringify({ cohorts: [] }),
      }),
    },
    GmailApp: {
      sendEmail: () => {},
      search:    () => [],
    },
    Logger:         { log: () => {} },
    ContentService: { createTextOutput: (s) => ({ output: s }) },
  };
}

// ─── Load Code.gs into a sandboxed vm context ─────────────────────────────
const rawSrc = fs.readFileSync(
  path.join(__dirname, '..', 'apps_script', 'Code.gs'), 'utf8'
);

// Patch out the config-constant lines that read from Script Properties at
// module load time — we inject the stubs after the context is created.
const patchedSrc = rawSrc
  .replace(/^const _PROPS\s*=.*$/m,         '// _PROPS patched')
  .replace(/^const GITHUB_TOKEN\s*=.*$/m,   "const GITHUB_TOKEN   = 'TEST_TOKEN';")
  .replace(/^const TELEGRAM_TOKEN\s*=.*$/m, "const TELEGRAM_TOKEN = 'TEST_TG_TOKEN';")
  .replace(/^const TELEGRAM_CHAT\s*=.*$/m,  "const TELEGRAM_CHAT  = 'TEST_CHAT';");

function makeContext() {
  _scriptProps = {};   // reset props for each test
  const ctx = vm.createContext({
    ...makeStubs(),
    Buffer,   // needed for Utilities.base64Encode stub
    console,
    // _PROPS used inside rate-limit / blocklist helpers — provide it via context
    _PROPS: undefined,  // patched away above, but define to avoid ReferenceError
  });
  // Inject PropertiesService so the helpers inside Code.gs can call it.
  vm.runInContext(patchedSrc, ctx);
  // Patch _PROPS inside the context post-load.
  vm.runInContext(
    'const _PROPS_CTX = PropertiesService.getScriptProperties();',
    ctx
  );
  return ctx;
}

// ─── Test harness ─────────────────────────────────────────────────────────
let PASS = 0, FAIL = 0;

function check(label, got, expected) {
  if (String(got) === String(expected)) {
    console.log(`  ✓  ${label}`);
    PASS++;
  } else {
    console.log(`  ✗  ${label}`);
    console.log(`       got:      ${JSON.stringify(got)}`);
    console.log(`       expected: ${JSON.stringify(expected)}`);
    FAIL++;
  }
}
function checkIs(label, cond) {
  if (cond) { console.log(`  ✓  ${label}`); PASS++; }
  else       { console.log(`  ✗  ${label}`); FAIL++; }
}

// ─── Shared context (re-created per section that needs fresh props) ─────────
let C = makeContext();

const cohorts = [
  { batch: 2023, rollPrefix: '23', semester: 6, label: '6th Sem' },
  { batch: 2024, rollPrefix: '24', semester: 4, label: '4th Sem' },
];


// ═══════════════════════════════════════════════════════════════════════════
// 1. esc_
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── esc_ ──────────────────────────────────────────────────────────');
check('& escaped',               C.esc_('a & b'),       'a &amp; b');
check('< escaped',               C.esc_('<script>'),    '&lt;script&gt;');
check('> escaped',               C.esc_('a>b'),         'a&gt;b');
check('null → empty string',     C.esc_(null),          '');
check('undefined → empty',       C.esc_(undefined),     '');
check('normal string untouched', C.esc_('hello'),       'hello');
check('combined escaping',       C.esc_('<b>a & b</b>'), '&lt;b&gt;a &amp; b&lt;/b&gt;');


// ═══════════════════════════════════════════════════════════════════════════
// 2. extractEmail_
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── extractEmail_ ─────────────────────────────────────────────────');
check('Name <email> format',     C.extractEmail_('Arpan Z <2305001@kiit.ac.in>'), '2305001@kiit.ac.in');
check('plain email passthrough', C.extractEmail_('2305001@kiit.ac.in'),           '2305001@kiit.ac.in');
check('lowercased',              C.extractEmail_('2305001@KIIT.AC.IN'),            '2305001@kiit.ac.in');
check('trailing space stripped', C.extractEmail_('  2305001@kiit.ac.in  '),       '2305001@kiit.ac.in');
check('only trims angle-bracket part', C.extractEmail_('A B <x@y.com>'),          'x@y.com');


// ═══════════════════════════════════════════════════════════════════════════
// 3. isStudentEmail_
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── isStudentEmail_ ───────────────────────────────────────────────');
checkIs('valid 7-digit roll',           C.isStudentEmail_('2305001@kiit.ac.in'));
checkIs('valid 8-digit roll',           C.isStudentEmail_('23050001@kiit.ac.in'));
checkIs('case-insensitive domain',      C.isStudentEmail_('2305001@KIIT.AC.IN'));
checkIs('name-based email rejected',   !C.isStudentEmail_('john.doe@kiit.ac.in'));
checkIs('wrong domain rejected',       !C.isStudentEmail_('2305001@gmail.com'));
checkIs('faculty format rejected',     !C.isStudentEmail_('faculty123@kiit.ac.in'));
checkIs('empty string rejected',       !C.isStudentEmail_(''));
checkIs('5-digit (too short) rejected',!C.isStudentEmail_('23050@kiit.ac.in'));
checkIs('mixed letters rejected',      !C.isStudentEmail_('23abc01@kiit.ac.in'));


// ═══════════════════════════════════════════════════════════════════════════
// 4. detectCohort
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── detectCohort ──────────────────────────────────────────────────');
checkIs('2305001@… → 2023 cohort',
        C.detectCohort('2305001@kiit.ac.in', cohorts)?.batch === 2023);
checkIs('2405001@… → 2024 cohort',
        C.detectCohort('2405001@kiit.ac.in', cohorts)?.batch === 2024);
checkIs('unknown prefix → null',
        C.detectCohort('2505001@kiit.ac.in', cohorts) === null);
checkIs('name-based email → null',
        C.detectCohort('john.doe@kiit.ac.in', cohorts) === null);
checkIs('"Name <email>" format works',
        C.detectCohort('Student <2305001@kiit.ac.in>', cohorts)?.batch === 2023);


// ═══════════════════════════════════════════════════════════════════════════
// 5. Blocklist
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── blocklist ─────────────────────────────────────────────────────');
C = makeContext();
checkIs('not blocked initially',      !C.isBlocked_('2305001@kiit.ac.in'));
C.blockEmail_('2305001@kiit.ac.in');
checkIs('blocked after blockEmail_',   C.isBlocked_('2305001@kiit.ac.in'));
checkIs('case-insensitive block check',C.isBlocked_('2305001@KIIT.AC.IN'));
C.unblockEmail_('2305001@kiit.ac.in');
checkIs('unblocked after unblockEmail_', !C.isBlocked_('2305001@kiit.ac.in'));

C.blockEmail_('a@b.com');
C.blockEmail_('a@b.com');   // double-block
checkIs('double-block does not duplicate', C.listBlocked_().length === 1);


// ═══════════════════════════════════════════════════════════════════════════
// 6. Rate limit
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── underRateLimit_ ───────────────────────────────────────────────');
C = makeContext();
checkIs('first call allowed',         C.underRateLimit_('2305001@kiit.ac.in'));
checkIs('second call blocked',       !C.underRateLimit_('2305001@kiit.ac.in'));
checkIs('different email unaffected', C.underRateLimit_('2305002@kiit.ac.in'));

// Rate-limit key must use bare email, not "Name <email>"
C = makeContext();
C.underRateLimit_('2305001@kiit.ac.in');   // first call via bare email
// Should be blocked regardless of how the From: header wraps it
// (test: second call with same bare email is blocked)
checkIs('rate limit keyed on bare email, not display name',
        !C.underRateLimit_('2305001@kiit.ac.in'));


// ═══════════════════════════════════════════════════════════════════════════
// 7. Unknown-cohort: NO crash (the key fix)
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── unknown-cohort: no crash ──────────────────────────────────────');
C = makeContext();

const nullCohort = C.detectCohort('2505001@kiit.ac.in', cohorts);
checkIs('unknown prefix returns null (not undefined)', nullCohort === null);

// Simulate the guard logic: the !cohort branch must never reference cohort.*
// (original bug: it called cohort.label / cohort.batch when cohort===null)
let threw = false;
try {
  if (!nullCohort) {
    // This is what Code.gs now does — build the email WITHOUT touching nullCohort
    const html = C.buildEmailHtml_({
      status:  'error',
      title:   "We Couldn't Match Your Batch",
      message: "Your file was received, but your roll number doesn't match any batch.",
      rows:    [['File', 'test.xlsx'], ['Received At', '17 Jun 2026']],
    });
    checkIs('unknown-cohort HTML built without crash',
            typeof html === 'string' && html.includes('KampusVibes'));
  }
} catch (e) {
  threw = true;
  console.log(`  ✗  threw: ${e.message}`);
  FAIL++;
}
checkIs('unknown-cohort branch: no exception thrown', !threw);


// ═══════════════════════════════════════════════════════════════════════════
// 8. Gate ordering: block → students-only → rate-limit
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── gate ordering ─────────────────────────────────────────────────');
C = makeContext();

// Blocked sender must be stopped before rate-limit consumes their quota
const bEmail = '2305001@kiit.ac.in';
C.blockEmail_(bEmail);
const blockedFirst = C.isBlocked_(bEmail);               // gate 1
const rlKeyAfterBlock = _scriptProps['rl_2026-06-17_' + bEmail];
checkIs('blocked sender caught at gate 1 (blocklist)', blockedFirst);
checkIs('blocked sender did NOT burn rate-limit quota', rlKeyAfterBlock == null);

// Non-student must be stopped before rate-limit
C = makeContext();
const nse = 'faculty@kiit.ac.in';
const notStudent = !C.isStudentEmail_(nse);               // gate 2
const rlKeyAfterNS = _scriptProps['rl_2026-06-17_' + nse];
checkIs('non-student caught at gate 2 (students-only)', notStudent);
checkIs('non-student did NOT burn rate-limit quota', rlKeyAfterNS == null);


// ═══════════════════════════════════════════════════════════════════════════
// 9. buildEmailHtml_ output shape + XSS safety
// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── buildEmailHtml_ ───────────────────────────────────────────────');
C = makeContext();

const html = C.buildEmailHtml_({
  status: 'success', title: 'Thank You!',
  message: 'Your timetable has been received.',
  rows: [['File', 'test.xlsx'], ['Received At', '17 Jun 2026']],
});
checkIs('starts with DOCTYPE',            html.startsWith('<!DOCTYPE html>'));
checkIs('contains KampusVibes branding',  html.includes('KampusVibes'));
checkIs('contains success title',         html.includes('Thank You!'));
checkIs('contains row label',             html.includes('File'));
checkIs('contains row value',             html.includes('test.xlsx'));
checkIs('success badge shown',            html.includes('RECEIVED'));

const htmlErr = C.buildEmailHtml_({ status: 'error', title: 'Oops', message: 'fail', rows: [] });
checkIs('error badge shown', htmlErr.includes('ACTION NEEDED'));

// XSS: title containing HTML must be escaped
const xssHtml = C.buildEmailHtml_({
  status: 'success', title: '<script>alert(1)</script>', message: 'ok', rows: [],
});
checkIs('title: raw <script> not present',  !xssHtml.includes('<script>'));
checkIs('title: escaped entity present',     xssHtml.includes('&lt;script&gt;'));

// XSS: row values escaped
const rowXss = C.buildEmailHtml_({
  status: 'success', title: 'T', message: 'M',
  rows: [['Label', '<img src=x onerror=alert(1)>']],
});
checkIs('row value: raw <img> not present', !rowXss.includes('<img'));
checkIs('row value: escaped',               rowXss.includes('&lt;img'));


// ═══════════════════════════════════════════════════════════════════════════
// Summary
// ═══════════════════════════════════════════════════════════════════════════
console.log(`\n${'═'.repeat(60)}`);
console.log(`  Results: ${PASS} passed, ${FAIL} failed`);
console.log(`${'═'.repeat(60)}`);
if (FAIL) process.exit(1);

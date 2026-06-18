/**
 * Tests for the trimmed Apps Script (apps_script/Code.gs) — email-ingestion only.
 *
 * The Telegram control plane (commands + buttons + blocklist writes) moved to the
 * Netlify function, so those are no longer tested here. This covers the pure
 * helpers that remain, plus the Netlify-backed isBlocked_ (with stubbed HTTP).
 *
 * Runs in Node with vm.createContext + GAS API stubs.
 */
'use strict';
const vm   = require('vm');
const fs   = require('fs');
const path = require('path');

let _scriptProps = {};
let _blocklistResponse = { code: 200, body: '[]' };  // what the blocklist URL returns

function makeStubs() {
  return {
    PropertiesService: {
      getScriptProperties: () => ({
        getProperty: (k) => _scriptProps[k] ?? null,
        setProperty: (k, v) => { _scriptProps[k] = v; },
      }),
    },
    Utilities: {
      formatDate: (_d, _tz, fmt) => fmt === 'yyyy-MM-dd' ? '2026-06-18' : '18 Jun 2026',
      base64Encode: (b) => Buffer.from(b).toString('base64'),
      gzip: (b) => b,
    },
    UrlFetchApp: {
      fetch: (url) => ({
        getResponseCode: () => url.includes('/blocklist') ? _blocklistResponse.code : 200,
        getContentText:  () => url.includes('/blocklist') ? _blocklistResponse.body
                                                           : JSON.stringify({ cohorts: [] }),
      }),
    },
    GmailApp: { sendEmail: () => {}, search: () => [] },
    Logger: { log: () => {} },
  };
}

const rawSrc = fs.readFileSync(path.join(__dirname, '..', 'apps_script', 'Code.gs'), 'utf8');
const patchedSrc = rawSrc
  .replace(/^const _PROPS\s*=.*$/m,         '// _PROPS patched')
  .replace(/^const GITHUB_TOKEN\s*=.*$/m,   "const GITHUB_TOKEN   = 'T';")
  .replace(/^const TELEGRAM_TOKEN\s*=.*$/m, "const TELEGRAM_TOKEN = 'T';")
  .replace(/^const TELEGRAM_CHAT\s*=.*$/m,  "const TELEGRAM_CHAT  = 'C';")
  .replace(/^const BLOCKLIST_KEY\s*=.*$/m,  "const BLOCKLIST_KEY  = 'testkey';");

function freshCtx() {
  _scriptProps = {};
  _blocklistResponse = { code: 200, body: '[]' };
  const ctx = vm.createContext({ ...makeStubs(), Buffer, console });
  vm.runInContext(patchedSrc, ctx);
  return ctx;
}

let PASS = 0, FAIL = 0;
function check(label, got, expected) {
  if (String(got) === String(expected)) { console.log(`  ✓  ${label}`); PASS++; }
  else { console.log(`  ✗  ${label}\n       got: ${JSON.stringify(got)}\n       exp: ${JSON.stringify(expected)}`); FAIL++; }
}
function checkIs(label, cond) {
  if (cond) { console.log(`  ✓  ${label}`); PASS++; } else { console.log(`  ✗  ${label}`); FAIL++; }
}

let C = freshCtx();
const cohorts = [
  { batch: 2023, rollPrefix: '23', semester: 6, label: '6th Sem' },
  { batch: 2024, rollPrefix: '24', semester: 4, label: '4th Sem' },
  { batch: 2025, rollPrefix: '25', semester: 3, label: '3rd Sem' },
];

console.log('\n── esc_ ──────────────────────────────────────────────────────────');
check('& escaped',  C.esc_('a & b'),    'a &amp; b');
check('< > escaped', C.esc_('<x>'),     '&lt;x&gt;');
check('null → empty', C.esc_(null),     '');

console.log('\n── extractEmail_ ─────────────────────────────────────────────────');
check('Name <email>', C.extractEmail_('Arpan <2305001@kiit.ac.in>'), '2305001@kiit.ac.in');
check('plain + lowercased', C.extractEmail_('2305001@KIIT.AC.IN'), '2305001@kiit.ac.in');

console.log('\n── isStudentEmail_ ───────────────────────────────────────────────');
checkIs('valid roll', C.isStudentEmail_('2305001@kiit.ac.in'));
checkIs('name-based rejected', !C.isStudentEmail_('john.doe@kiit.ac.in'));
checkIs('wrong domain rejected', !C.isStudentEmail_('2305001@gmail.com'));

console.log('\n── detectCohort ──────────────────────────────────────────────────');
checkIs('23→2023', C.detectCohort('2305001@kiit.ac.in', cohorts)?.batch === 2023);
checkIs('25→2025', C.detectCohort('2505001@kiit.ac.in', cohorts)?.batch === 2025);
checkIs('unknown→null', C.detectCohort('2705001@kiit.ac.in', cohorts) === null);
checkIs('name-based→null', C.detectCohort('a.b@kiit.ac.in', cohorts) === null);

console.log('\n── underRateLimit_ ───────────────────────────────────────────────');
C = freshCtx();
checkIs('1st allowed', C.underRateLimit_('2305001@kiit.ac.in'));
checkIs('2nd allowed (limit 2)', C.underRateLimit_('2305001@kiit.ac.in'));
checkIs('3rd blocked', !C.underRateLimit_('2305001@kiit.ac.in'));
checkIs('other email unaffected', C.underRateLimit_('2305002@kiit.ac.in'));

console.log('\n── isBlocked_ (Netlify-backed, stubbed HTTP) ─────────────────────');
C = freshCtx();
_blocklistResponse = { code: 200, body: JSON.stringify(['2305771@kiit.ac.in']) };
checkIs('blocked email detected', C.isBlocked_('2305771@kiit.ac.in'));
checkIs('case-insensitive', C.isBlocked_('2305771@KIIT.AC.IN'));
checkIs('other email not blocked', !C.isBlocked_('2305001@kiit.ac.in'));
// fail-open: any non-200 or bad body must NOT block (never break legit uploads)
_blocklistResponse = { code: 403, body: 'forbidden' };
checkIs('403 → fail open (not blocked)', !C.isBlocked_('2305771@kiit.ac.in'));
_blocklistResponse = { code: 200, body: 'not json' };
checkIs('bad JSON → fail open', !C.isBlocked_('2305771@kiit.ac.in'));

console.log('\n── buildEmailHtml_ ───────────────────────────────────────────────');
C = freshCtx();
const ok = C.buildEmailHtml_({ status: 'success', title: 'Thanks', message: 'm', rows: [['File', 'x.xls']] });
checkIs('DOCTYPE', ok.startsWith('<!DOCTYPE html>'));
checkIs('branding', ok.includes('KampusVibes'));
checkIs('RECEIVED badge', ok.includes('RECEIVED'));
checkIs('row value', ok.includes('x.xls'));
const err = C.buildEmailHtml_({ status: 'error', title: 'Oops', message: 'm', rows: [] });
checkIs('ACTION NEEDED badge', err.includes('ACTION NEEDED'));
const xss = C.buildEmailHtml_({ status: 'success', title: '<script>', message: 'm', rows: [] });
checkIs('title XSS-escaped', !xss.includes('<script>') && xss.includes('&lt;script&gt;'));

console.log(`\n${'═'.repeat(60)}`);
console.log(`  Results: ${PASS} passed, ${FAIL} failed`);
console.log(`${'═'.repeat(60)}`);
if (FAIL) process.exit(1);

/**
 * Focused end-to-end test of the BLOCK feature in apps_script/Code.gs.
 *
 * Unlike test_appscript.js (which only calls the low-level blockEmail_/isBlocked_),
 * this drives the REAL entry points a human uses:
 *   • the "🚫 Block sender" inline button   → handleCallback_ (block: action)
 *   • the /block /unblock /blocked commands  → handleCommand_
 *   • the admin-only authorization checks    → both handlers
 *   • the inbound gate's dependency           → isBlocked_ after a block
 *   • Telegram callback_data 64-byte limit    → button payload sizing
 *
 * Runs in Node with stubs that RECORD outgoing Telegram calls so we can assert
 * on what the user would actually see.
 */
'use strict';
const vm   = require('vm');
const fs   = require('fs');
const path = require('path');

let _scriptProps = {};
let _tgCalls = [];   // recorded outgoing Telegram API calls
let _cache = {};     // mock CacheService store

function parsePayload(opts) {
  // opts.payload is an object (Apps Script style) for our stubs.
  return (opts && opts.payload) || {};
}

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
      formatDate: (_d, _tz, fmt) => fmt === 'yyyy-MM-dd' ? '2026-06-18' : '18 Jun 2026',
      base64Encode: (b) => Buffer.from(b).toString('base64'),
      gzip: (blob) => blob,
    },
    UrlFetchApp: {
      fetch: (url, opts) => {
        _tgCalls.push({ url, payload: parsePayload(opts) });
        return { getResponseCode: () => 200, getContentText: () => '{}' };
      },
    },
    GmailApp: { sendEmail: () => {}, search: () => [] },
    Logger: { log: () => {} },
    ContentService: { createTextOutput: (s) => ({ output: s }) },
    CacheService: {
      getScriptCache: () => ({
        get: (k) => _cache[k] ?? null,
        put: (k, v) => { _cache[k] = v; },
      }),
    },
  };
}

const rawSrc = fs.readFileSync(path.join(__dirname, '..', 'apps_script', 'Code.gs'), 'utf8');
const patchedSrc = rawSrc
  .replace(/^const _PROPS\s*=.*$/m,         '// _PROPS patched')
  .replace(/^const GITHUB_TOKEN\s*=.*$/m,   "const GITHUB_TOKEN   = 'T';")
  .replace(/^const TELEGRAM_TOKEN\s*=.*$/m, "const TELEGRAM_TOKEN = 'T';")
  .replace(/^const TELEGRAM_CHAT\s*=.*$/m,  "const TELEGRAM_CHAT  = 'C';");

function freshCtx() {
  _scriptProps = {};
  _tgCalls = [];
  _cache = {};
  const ctx = vm.createContext({ ...makeStubs(), Buffer, console });
  vm.runInContext(patchedSrc, ctx);
  return ctx;
}

let PASS = 0, FAIL = 0;
function ok(label, cond) {
  if (cond) { console.log(`  ✓  ${label}`); PASS++; }
  else      { console.log(`  ✗  ${label}`); FAIL++; }
}

// Pull the admin id straight out of the script so the test can't drift.
const ADMIN_ID = (() => {
  const m = rawSrc.match(/MY_TELEGRAM_USER_ID\s*=\s*(\d+)/);
  return m ? Number(m[1]) : null;
})();
const OUTSIDER_ID = 99999999;

function lastText() {
  // last sendMessage/answerCallback text
  for (let i = _tgCalls.length - 1; i >= 0; i--) {
    const p = _tgCalls[i].payload;
    if (p && (p.text || p.text === '')) return p.text;
  }
  return null;
}

// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── admin id sanity ───────────────────────────────────────────────');
ok('MY_TELEGRAM_USER_ID parsed from script', typeof ADMIN_ID === 'number' && ADMIN_ID > 0);


// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── "🚫 Block sender" button (handleCallback_ block:) ─────────────');
{
  const C = freshCtx();
  const cq = {
    id: 'cb1',
    from: { id: ADMIN_ID },
    data: 'block:2305771@kiit.ac.in',
    message: { chat: { id: 1 }, message_id: 10, text: 'dispatch card' },
  };
  C.handleCallback_(cq);
  ok('email added to blocklist after button tap',
     C.isBlocked_('2305771@kiit.ac.in'));
  ok('answerCallbackQuery was called',
     _tgCalls.some(c => c.url.includes('answerCallbackQuery')));
  ok('original message edited (button stripped)',
     _tgCalls.some(c => c.url.includes('editMessageText')));
}

// ── Unauthorized user must NOT be able to block ──
{
  const C = freshCtx();
  C.handleCallback_({
    id: 'cb2', from: { id: OUTSIDER_ID },
    data: 'block:hacker@kiit.ac.in', message: { chat: { id: 1 }, message_id: 11, text: 'x' },
  });
  ok('outsider tap does NOT block anyone', !C.isBlocked_('hacker@kiit.ac.in'));
  ok('outsider gets "Not authorized"',
     _tgCalls.some(c => (c.payload.text || '').includes('Not authorized')));
}


// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── /block /unblock /blocked commands (handleCommand_) ────────────');
{
  const C = freshCtx();

  // /block
  C.handleCommand_({ from: { id: ADMIN_ID }, chat: { id: 1 }, text: '/block Spammer@KIIT.ac.in' });
  ok('/block adds (and lowercases) the email', C.isBlocked_('spammer@kiit.ac.in'));
  ok('/block confirms to admin', (lastText() || '').includes('Blocked'));

  // /blocked lists it
  C.handleCommand_({ from: { id: ADMIN_ID }, chat: { id: 1 }, text: '/blocked' });
  ok('/blocked lists the blocked email', (lastText() || '').includes('spammer@kiit.ac.in'));

  // /unblock
  C.handleCommand_({ from: { id: ADMIN_ID }, chat: { id: 1 }, text: '/unblock spammer@kiit.ac.in' });
  ok('/unblock removes the email', !C.isBlocked_('spammer@kiit.ac.in'));

  // /blocked when empty
  C.handleCommand_({ from: { id: ADMIN_ID }, chat: { id: 1 }, text: '/blocked' });
  ok('/blocked reports empty list', (lastText() || '').includes('No one is blocked'));

  // /block with no argument → usage hint, nothing blocked
  _tgCalls = [];
  C.handleCommand_({ from: { id: ADMIN_ID }, chat: { id: 1 }, text: '/block' });
  ok('/block with no arg shows usage', (lastText() || '').toLowerCase().includes('usage'));
  ok('/block with no arg blocks nothing', C.listBlocked_().length === 0);
}

// ── Unauthorized user commands are ignored ──
{
  const C = freshCtx();
  C.handleCommand_({ from: { id: OUTSIDER_ID }, chat: { id: 5 }, text: '/block victim@kiit.ac.in' });
  ok('outsider /block is ignored (nothing blocked)', !C.isBlocked_('victim@kiit.ac.in'));
  ok('outsider /block produces no reply', _tgCalls.length === 0);
}


// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── the inbound gate depends on isBlocked_ ────────────────────────');
{
  const C = freshCtx();
  // Simulate what the email loop does: extractEmail_ then isBlocked_
  C.blockEmail_('2305771@kiit.ac.in');
  const fromHeader = 'ARPAN SINGH <2305771@kiit.ac.in>';
  const email = C.extractEmail_(fromHeader);
  ok('extractEmail_ matches the stored (bare, lowercased) key', email === '2305771@kiit.ac.in');
  ok('gate would drop this sender (isBlocked_ true)', C.isBlocked_(email));

  const email2 = C.extractEmail_('Someone Else <2305772@kiit.ac.in>');
  ok('a different sender is NOT blocked', !C.isBlocked_(email2));
}


// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── persistence + idempotency ─────────────────────────────────────');
{
  const C = freshCtx();
  C.blockEmail_('a@kiit.ac.in');
  C.blockEmail_('a@kiit.ac.in');   // duplicate
  C.blockEmail_('b@kiit.ac.in');
  ok('no duplicate entries', C.listBlocked_().length === 2);
  ok('blocklist persisted as JSON in Script Properties',
     JSON.parse(_scriptProps['blocklist']).length === 2);
  C.unblockEmail_('a@kiit.ac.in');
  ok('unblock leaves the other intact',
     !C.isBlocked_('a@kiit.ac.in') && C.isBlocked_('b@kiit.ac.in'));
  // unblock something not present = no-op, no crash
  C.unblockEmail_('ghost@kiit.ac.in');
  ok('unblocking a non-member is a safe no-op', C.listBlocked_().length === 1);
}


// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── Telegram callback_data 64-byte limit ──────────────────────────');
{
  // Telegram rejects inline button callback_data longer than 64 bytes.
  // The button uses 'block:' + email. Flag any email that would overflow.
  const prefix = 'block:';
  const typicalRoll = '2305771@kiit.ac.in';
  ok('typical roll-number email button is within 64 bytes',
     Buffer.byteLength(prefix + typicalRoll) <= 64);

  const longEmail = 'a'.repeat(70) + '@kiit.ac.in';
  ok('an unusually long email WOULD exceed 64 bytes (known edge case)',
     Buffer.byteLength(prefix + longEmail) > 64);
}


// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── corrupt blocklist property must not break commands ────────────');
{
  // Regression: a corrupt / non-JSON value in the 'blocklist' property used to
  // make _getBlocklist throw (JSON.parse), which doPost swallowed -> no reply.
  const C = freshCtx();
  _scriptProps['blocklist'] = 'undefined';   // poisoned value
  let threw = false;
  try { ok('isBlocked_ survives corrupt property', C.isBlocked_('x@kiit.ac.in') === false); }
  catch (e) { threw = true; }
  ok('_getBlocklist does NOT throw on corrupt data', !threw);

  // a command should still reply (treats list as empty)
  _tgCalls = [];
  let cmdThrew = false;
  try { C.handleCommand_({ from: { id: ADMIN_ID }, chat: { id: 1 }, text: '/blocked' }); }
  catch (e) { cmdThrew = true; }
  ok('/blocked does NOT throw on corrupt property', !cmdThrew);
  ok('/blocked still replies (corrupt -> empty)',
     (lastText() || '').includes('No one is blocked'));

  // blocking after corruption self-heals (overwrites with valid JSON)
  C.handleCommand_({ from: { id: ADMIN_ID }, chat: { id: 1 }, text: '/block heal@kiit.ac.in' });
  ok('blocking after corruption self-heals the property',
     C.isBlocked_('heal@kiit.ac.in') &&
     Array.isArray(JSON.parse(_scriptProps['blocklist'])));
}

// _saveBlocklist must never write a non-string (was: "Invalid argument: value")
{
  const C = freshCtx();
  let threw = false;
  try { C._saveBlocklist(undefined); } catch (e) { threw = true; }
  ok('_saveBlocklist(undefined) does not write a bad value', !threw);
  ok('_saveBlocklist(undefined) stores "[]"', _scriptProps['blocklist'] === '[]');
}


// ═══════════════════════════════════════════════════════════════════════════
console.log('\n── doPost de-duplicates retried updates (no double replies) ──────');
{
  const C = freshCtx();
  const makeUpdate = (uid, text) => ({
    postData: { contents: JSON.stringify({
      update_id: uid,
      message: { from: { id: ADMIN_ID }, chat: { id: ADMIN_ID }, text },
    }) },
  });

  // First delivery of update 1000 → handled (one reply)
  C.doPost(makeUpdate(1000, '/blocked'));
  const repliesAfterFirst = _tgCalls.filter(c => c.url.includes('sendMessage')).length;
  ok('first delivery produces exactly one reply', repliesAfterFirst === 1);

  // Telegram retries the SAME update_id → must be ignored (still one reply total)
  C.doPost(makeUpdate(1000, '/blocked'));
  const repliesAfterRetry = _tgCalls.filter(c => c.url.includes('sendMessage')).length;
  ok('retry of same update_id produces NO extra reply', repliesAfterRetry === 1);

  // A genuinely new update_id is still processed
  C.doPost(makeUpdate(1001, '/blocked'));
  const repliesAfterNew = _tgCalls.filter(c => c.url.includes('sendMessage')).length;
  ok('a new update_id is processed normally', repliesAfterNew === 2);
}


console.log(`\n${'═'.repeat(62)}`);
console.log(`  Block-feature results: ${PASS} passed, ${FAIL} failed`);
console.log(`${'═'.repeat(62)}`);
if (FAIL) process.exit(1);

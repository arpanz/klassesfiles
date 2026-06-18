// ═══════════════════════════════════════════════════════════════════════════
// KampusVibes — Gmail → Pipeline  (Google Apps Script)
// ───────────────────────────────────────────────────────────────────────────
// This script does ONE job now: the inbound email flow.
//   • Time trigger (every ~15 min) → processIncomingTimetables
//
// The Telegram CONTROL plane (/block /unblock /blocked commands and the
// Approve / Reject / Undo / Block buttons) has MOVED to a Netlify Function
// (netlify/functions/telegram.mjs) because Apps Script web apps return 302s
// that Telegram rejects. There is no doPost / Web App deployment here anymore.
//
// The blocklist is owned by the Netlify function (Netlify Blobs); this script
// reads it over HTTP in isBlocked_().
//
// SECURITY — set these in Project Settings → Script Properties (never hard-code):
//   GITHUB_TOKEN, TELEGRAM_TOKEN, TELEGRAM_CHAT, BLOCKLIST_KEY
// ═══════════════════════════════════════════════════════════════════════════

// ─── CONFIG ────────────────────────────────────────────────────────────────
const _PROPS = PropertiesService.getScriptProperties();

const GITHUB_TOKEN   = _PROPS.getProperty('GITHUB_TOKEN')   || 'SET_IN_SCRIPT_PROPERTIES';
const TELEGRAM_TOKEN = _PROPS.getProperty('TELEGRAM_TOKEN') || 'SET_IN_SCRIPT_PROPERTIES';
const TELEGRAM_CHAT  = _PROPS.getProperty('TELEGRAM_CHAT')  || 'SET_IN_SCRIPT_PROPERTIES';

const OWNER        = 'arpanz';
const REPO         = 'klassesfiles';
const WORKFLOW     = 'timetable_automation.yml';
const MANIFEST_URL = 'https://klassesfiles.netlify.app/manifest.json';

// Blocklist is served by the Netlify function (written by the Telegram webhook).
const BLOCKLIST_URL = 'https://klassesfiles.netlify.app/.netlify/functions/blocklist';
const BLOCKLIST_KEY = _PROPS.getProperty('BLOCKLIST_KEY') || '';

// ─── STUDENT-ONLY GATE ───────────────────────────────────────────────────────
// A valid submitter is a student: a numeric roll-number local part at the
// college domain, e.g. 2305001@kiit.ac.in.
// ⚠️ Set COLLEGE_DOMAIN to your institution's student-mail domain.
const COLLEGE_DOMAIN   = 'kiit.ac.in';
const STUDENT_EMAIL_RE = new RegExp(
  '^\\d{6,}@' + COLLEGE_DOMAIN.replace(/\./g, '\\.') + '$', 'i'
);

function isStudentEmail_(email) {
  return STUDENT_EMAIL_RE.test(String(email || '').trim().toLowerCase());
}

// ─── HELPERS ──────────────────────────────────────────────────────────────────
// Escape HTML-breaking chars so dynamic values never break Telegram/email rendering.
function esc_(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function nowIST_() {
  return Utilities.formatDate(new Date(), 'Asia/Kolkata', "d MMM yyyy, h:mm a 'IST'");
}

// ─── TELEGRAM (notifications only — no webhook here) ──────────────────────────
// Plain text — safe for any content (used for raw logs/warnings).
function tg(text) {
  try {
    UrlFetchApp.fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`, {
      method: 'post',
      payload: { chat_id: TELEGRAM_CHAT, text: String(text) },
      muteHttpExceptions: true,
    });
  } catch (e) { Logger.log('Telegram error: ' + e); }
}

// Pretty card — HTML mode. title is plain; rows are [label, value] pairs (auto-escaped).
// `buttons` is [{text, data}] — taps are handled by the Netlify webhook.
function tgCard_(emoji, title, rows, buttons) {
  let body = `${emoji} <b>${esc_(title)}</b>\n━━━━━━━━━━━━━━━━━━\n`;
  (rows || []).forEach(function (r) { body += `<b>${esc_(r[0])}:</b> ${esc_(r[1])}\n`; });
  const payload = { chat_id: TELEGRAM_CHAT, text: body, parse_mode: 'HTML' };
  if (buttons && buttons.length) {
    payload.reply_markup = JSON.stringify({
      inline_keyboard: [buttons.map(function (b) { return { text: b.text, callback_data: b.data }; })],
    });
  }
  try {
    UrlFetchApp.fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`,
      { method: 'post', muteHttpExceptions: true, payload: payload });
  } catch (e) { Logger.log('tgCard error: ' + e); }
}

// ─── BLOCKLIST (read-only; owned by the Netlify webhook) ──────────────────────
// Fails OPEN on any error: a transient network/auth hiccup must never block a
// legitimate student upload. Blocking is a spam convenience, not a security gate.
function isBlocked_(email) {
  if (!BLOCKLIST_KEY) return false;
  try {
    const resp = UrlFetchApp.fetch(
      BLOCKLIST_URL + '?key=' + encodeURIComponent(BLOCKLIST_KEY),
      { muteHttpExceptions: true });
    if (resp.getResponseCode() !== 200) return false;
    const list = JSON.parse(resp.getContentText());
    return Array.isArray(list) && list.indexOf(String(email).trim().toLowerCase()) !== -1;
  } catch (e) {
    Logger.log('isBlocked_ check failed: ' + e);
    return false;
  }
}

// Extract bare email from "Name <a@b.com>" or "a@b.com"
function extractEmail_(from) {
  const m = String(from).match(/<([^>]+)>/);
  return (m ? m[1] : String(from)).trim().toLowerCase();
}

// ─── MANIFEST ─────────────────────────────────────────────────────────────────
function getCohorts() {
  const resp = UrlFetchApp.fetch(MANIFEST_URL, { muteHttpExceptions: true });
  if (resp.getResponseCode() !== 200) {
    throw new Error('Manifest fetch failed: HTTP ' + resp.getResponseCode());
  }
  return JSON.parse(resp.getContentText()).cohorts;
}

// ─── COHORT DETECTION ─────────────────────────────────────────────────────────
function detectCohort(senderEmail, cohorts) {
  const match = senderEmail.match(/(\d{2})\d{2}\d+@/);
  if (!match) return null;
  const prefix = match[1];
  return cohorts.find(c => c.rollPrefix === prefix) || null;
}

// ─── GITHUB DISPATCH ──────────────────────────────────────────────────────────
function triggerAction(cohort, base64File) {
  const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;
  const res = UrlFetchApp.fetch(url, {
    method: 'post',
    muteHttpExceptions: true,
    headers: {
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      Accept: 'application/vnd.github.v3+json',
    },
    contentType: 'application/json',
    payload: JSON.stringify({
      ref: 'master',
      inputs: {
        batch:        String(cohort.batch),
        semester:     String(cohort.semester),
        file_type:    'timetable',
        update_type:  'merge',
        pe3:          String(!!cohort.pe3),
        file_content: base64File,
      },
    }),
  });
  return res.getResponseCode();
}

// ─── MAIN ─────────────────────────────────────────────────────────────────────
function processIncomingTimetables() {
  let cohorts;
  try {
    cohorts = getCohorts();
  } catch (e) {
    tg('⚠️ Apps Script: could not fetch manifest — ' + e.message);
    return;
  }

  const threads = GmailApp.search(
    'is:unread has:attachment (filename:xlsx OR filename:xls OR filename:csv)'
  );

  threads.forEach(thread => {
    thread.getMessages().forEach(message => {
      if (!message.isUnread()) return;

      message.getAttachments().forEach(att => {
        if (!/\.(xlsx|xls|csv)$/i.test(att.getName())) return;

        const sender  = message.getFrom();
        const subject = message.getSubject();
        const fname   = att.getName();
        const when    = nowIST_();
        const email   = extractEmail_(sender);

        // 1) Blocklist — drop silently (no dispatch, no email, no quota burned).
        if (isBlocked_(email)) {
          tg('🚫 Ignored upload from blocked sender: ' + email);
          return;
        }

        // 2) Students only — reject anything that isn't a college roll-number
        //    address. Cleanly handled so it never crashes the run.
        if (!isStudentEmail_(email)) {
          tgCard_('⛔', 'Rejected — Not a Student Email', [
            ['From', sender], ['Subject', subject], ['File', fname], ['Time', when],
          ], [
            { text: '🚫 Block sender', data: 'block:' + email },
          ]);
          GmailApp.sendEmail(email, 'Timetable Upload Not Accepted — KampusVibes', '', {
            htmlBody: buildEmailHtml_({
              status: 'error',
              title: "Couldn't Accept This Upload",
              message: 'Timetable files can only be submitted from your official college ' +
                       'student email (your roll number @ ' + COLLEGE_DOMAIN + '). ' +
                       'Please resend from that address.',
              rows: [['File', fname], ['Received At', when]],
            }),
            name: 'KampusVibes',
          });
          return;
        }

        // 3) Rate limit — per student email, per day.
        if (!underRateLimit_(email)) {
          tgCard_('🚫', 'Rate Limit Hit — Ignored', [
            ['From', sender], ['File', fname], ['Time', when],
          ]);
          return;   // skip — don't fire the Action
        }

        // 4) Route to a cohort by roll-number prefix.
        const cohort = detectCohort(sender, cohorts);

        // ── Unknown cohort — valid student, but batch not in the manifest ──
        //    (Never dereference cohort.* here — that was the crash.)
        if (!cohort) {
          tgCard_('⚠️', 'Action Needed — Unknown Cohort', [
            ['From', sender],
            ['Subject', subject],
            ['File', fname],
            ['Time', when],
          ]);
          const html = buildEmailHtml_({
            status: 'error',
            title: "We Couldn't Match Your Batch",
            message: "Your file was received, but your roll number doesn't match any " +
                     'batch we currently track. If your batch should be supported, the ' +
                     'KampusVibes team will take a look — no further action needed from you.',
            rows: [
              ['Email Subject', subject],
              ['File', fname],
              ['Received At', when],
            ],
          });
          GmailApp.sendEmail(email, "Timetable Upload — Couldn't Match Your Batch", '', {
            htmlBody: html, name: 'KampusVibes',
          });
          return;
        }

        // ── Compress + dispatch ──
        // University files arrive as legacy .xls (~128 KB), but GitHub caps
        // workflow_dispatch inputs at 65,535 chars — a raw .xls is ~170 KB once
        // base64-encoded, so the dispatch fails with HTTP 422 before the Action
        // even runs. We gzip the bytes first (built-in Utilities.gzip; needs no
        // extra services or re-auth): ~128 KB → ~30 KB → ~41 KB base64. The Action
        // auto-detects the gzip header and decompresses before parsing.
        // Students keep emailing .xls; the compression happens here, invisibly.
        const gzipped   = Utilities.gzip(att.copyBlob());
        const base64File = Utilities.base64Encode(gzipped.getBytes());

        // Safety guard: never attempt a dispatch we know GitHub will reject (422).
        if (base64File.length > 60000) {
          tgCard_('✗', 'File Too Large to Dispatch', [
            ['Cohort', cohort.label + ' (Batch ' + cohort.batch + ')'],
            ['From', sender],
            ['File', fname],
            ['Encoded size', base64File.length + ' chars (GitHub limit 65,535)'],
            ['Time', when],
          ], [
            { text: '🚫 Block sender', data: 'block:' + email },
          ]);
          GmailApp.sendEmail(email, 'Timetable Upload — File Too Large', '', {
            htmlBody: buildEmailHtml_({
              status: 'error',
              title: 'This File Was Too Large to Process',
              message: 'We received your file but it was too large to process even after ' +
                       'compression. Please contact KampusVibes (askkampusvibes@gmail.com) ' +
                       'and we will sort it out.',
              rows: [['File', fname], ['Received At', when]],
            }),
            name: 'KampusVibes',
          });
          return;
        }

        const code = triggerAction(cohort, base64File);

        if (code === 204) {
          tgCard_('📥', 'Timetable Dispatched', [
            ['Cohort', cohort.label + ' (Batch ' + cohort.batch + ')'],
            ['Semester', 'Sem ' + cohort.semester],
            ['From', sender],
            ['File', fname],
            ['Time', when],
          ], [
            { text: '🚫 Block sender', data: 'block:' + email },
          ]);
          const html = buildEmailHtml_({
            status: 'success',
            title: 'Thank You!',
            message: 'Your ' + cohort.label + ' timetable has been received and is being ' +
                     'processed. It will go live in the app in about a minute.',
            rows: [
              ['Cohort', cohort.label + ' (Batch ' + cohort.batch + ')'],
              ['Semester', 'Semester ' + cohort.semester],
              ['Email Subject', subject],
              ['File', fname],
              ['Received At', when],
            ],
          });
          GmailApp.sendEmail(sender, 'Timetable Received ✓ — KampusVibes', '', {
            htmlBody: html, name: 'KampusVibes',
          });
        } else {
          tgCard_('✗', 'Dispatch Failed', [
            ['HTTP Code', code],
            ['Cohort', cohort.label],
            ['From', sender],
            ['Time', when],
          ]);
          const html = buildEmailHtml_({
            status: 'error',
            title: 'Something Went Wrong',
            message: 'We hit an error (code ' + code + ') while processing your file. ' +
                     'Please contact KampusVibes (askkampusvibes@gmail.com) directly.',
            rows: [
              ['Email Subject', subject],
              ['File', fname],
              ['Received At', when],
            ],
          });
          GmailApp.sendEmail(sender, 'Timetable Upload Failed', '', {
            htmlBody: html, name: 'KampusVibes',
          });
        }
      });

      message.markRead();
    });
  });
}

// ─── HTML EMAIL TEMPLATE (KampusVibes themed) ─────────────────────────────────
function buildEmailHtml_(opts) {
  const isSuccess   = opts.status === 'success';
  const accentStart = '#4F46E5';   // Indigo
  const accentEnd   = '#00D4AA';   // Teal
  const badgeColor  = isSuccess ? '#10B981' : '#EF4444';
  const badgeText   = isSuccess ? 'RECEIVED ✓' : 'ACTION NEEDED';
  const emoji       = isSuccess ? '🎉' : '⚠️';

  const rowsHtml = (opts.rows || []).map(function (r, i) {
    const bg = i % 2 === 0 ? '#F9FAFB' : '#FFFFFF';
    return (
      '<tr>' +
        '<td style="padding:12px 20px;background:' + bg + ';color:#6B7280;' +
            'font-size:13px;font-weight:600;width:40%;border-bottom:1px solid #F3F4F6;">' +
            esc_(r[0]) +
        '</td>' +
        '<td style="padding:12px 20px;background:' + bg + ';color:#111827;' +
            'font-size:14px;font-weight:500;border-bottom:1px solid #F3F4F6;">' +
            esc_(r[1]) +
        '</td>' +
      '</tr>'
    );
  }).join('');

  return (
'<!DOCTYPE html><html><head><meta charset="utf-8">' +
'<meta name="viewport" content="width=device-width,initial-scale=1.0"></head>' +
'<body style="margin:0;padding:0;background:#F2F4F9;' +
    'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">' +
'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F2F4F9;padding:24px 12px;">' +
  '<tr><td align="center">' +
    '<table role="presentation" width="600" cellpadding="0" cellspacing="0" ' +
        'style="max-width:600px;width:100%;background:#FFFFFF;border-radius:20px;overflow:hidden;' +
        'box-shadow:0 8px 30px rgba(17,24,39,0.08);">' +
      '<tr><td bgcolor="' + accentStart + '" style="background:' + accentStart + ';' +
          'background-image:linear-gradient(135deg,' + accentStart + ' 0%,' + accentEnd + ' 100%);' +
          'padding:36px 32px 28px;text-align:center;">' +
        '<div style="font-size:22px;font-weight:800;color:#FFFFFF;letter-spacing:-0.5px;">' +
          'Kampus<span style="color:#C7F9EC;">Vibes</span></div>' +
        '<div style="margin-top:6px;font-size:13px;color:rgba(255,255,255,0.85);">Timetable Service</div>' +
      '</td></tr>' +
      '<tr><td style="padding:36px 32px 8px;text-align:center;">' +
        '<div style="font-size:46px;line-height:1;margin-bottom:10px;">' + emoji + '</div>' +
        '<span style="display:inline-block;background:' + badgeColor + '1A;color:' + badgeColor + ';' +
            'font-size:12px;font-weight:700;letter-spacing:0.5px;padding:6px 14px;border-radius:999px;">' +
            badgeText + '</span>' +
        '<h1 style="margin:18px 0 6px;font-size:24px;color:#111827;font-weight:800;">' + esc_(opts.title) + '</h1>' +
        '<p style="margin:0 auto;max-width:420px;font-size:15px;line-height:1.6;color:#4B5563;">' +
            esc_(opts.message) + '</p>' +
      '</td></tr>' +
      (rowsHtml ?
      '<tr><td style="padding:24px 32px 8px;">' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" ' +
            'style="border:1px solid #F3F4F6;border-radius:12px;overflow:hidden;">' +
            rowsHtml +
        '</table>' +
      '</td></tr>' : '') +
      '<tr><td style="padding:28px 32px 36px;text-align:center;">' +
        '<div style="height:1px;background:#F3F4F6;margin-bottom:20px;"></div>' +
        '<p style="margin:0;font-size:12px;color:#9CA3AF;line-height:1.6;">' +
          'This is an automated message from the KampusVibes timetable system.<br>' +
          'Need help? Just reply to this email.' +
        '</p>' +
      '</td></tr>' +
    '</table>' +
  '</td></tr>' +
'</table></body></html>'
  );
}

// ─── RATE LIMIT (anti-spam) ───────────────────────────────────────────────────
const MAX_PER_SENDER_PER_DAY = 2;   // tune as you like

// Keyed on the bare email (stable) — consistent with the blocklist.
function underRateLimit_(email) {
  const props = PropertiesService.getScriptProperties();
  const day   = Utilities.formatDate(new Date(), 'Asia/Kolkata', 'yyyy-MM-dd');
  const key   = 'rl_' + day + '_' + email;
  const count = parseInt(props.getProperty(key) || '0', 10);
  if (count >= MAX_PER_SENDER_PER_DAY) return false;
  props.setProperty(key, String(count + 1));
  return true;
}

// ─── DEBUG ────────────────────────────────────────────────────────────────────
function debugCheck() {
  try {
    const cohorts = getCohorts();
    Logger.log('Cohorts loaded: ' + JSON.stringify(cohorts.map(c => c.label)));
  } catch (e) {
    Logger.log('Manifest error: ' + e);
    return;
  }
  const threads = GmailApp.search('has:attachment newer_than:1d');
  Logger.log('Threads with attachment (last 24h): ' + threads.length);
  threads.forEach(t => {
    const m = t.getMessages()[0];
    Logger.log(`From: ${m.getFrom()} | Unread: ${m.isUnread()} | Subject: ${m.getSubject()}`);
    m.getAttachments().forEach(a => Logger.log(`  File: ${a.getName()}`));
  });
  tg('✓ Debug check OK — ' + nowIST_());
}

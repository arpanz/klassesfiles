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
          GmailApp.sendEmail(email, 'Whoops, wrong email! — KampusVibes', '', {
            htmlBody: buildEmailHtml_({
              status: 'error',
              title: "Whoops, wrong email!",
              message: "We can only take timetables sent from your official student ID " +
                       "(your roll number @ " + COLLEGE_DOMAIN + "). " +
                       "Send it again from that address and we'll get it sorted!",
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
            title: "Hmm, unrecognized batch!",
            message: "Your timetable landed safely, but your roll number isn't on our " +
                     "tracked list yet. The KampusVibes team is on it — we'll check it out " +
                     "and add your batch if we need to. Sit tight!",
            rows: [
              ['Email Subject', subject],
              ['File', fname],
              ['Received At', when],
            ],
          });
          GmailApp.sendEmail(email, "Timetable Upload — Unmatched Batch", '', {
            htmlBody: html, name: 'KampusVibes',
          });
          return;
        }

        // ── Compress + dispatch ──
        // University files arrive as legacy .xls (~128 KB), but GitHub caps
        // workflow_dispatch inputs at 65,535 chars. To ensure large files fit,
        // we convert Excel sheets (.xls/.xlsx) to light CSVs via our Netlify function.
        // If it's already a CSV, we just gzip locally.
        let base64File;
        
        if (/\.(xlsx|xls)$/i.test(fname)) {
          const convertUrl = BLOCKLIST_URL.replace('/blocklist', '/convert') + '?key=' + encodeURIComponent(BLOCKLIST_KEY);
          try {
            const resp = UrlFetchApp.fetch(convertUrl, {
              method: 'post',
              contentType: 'application/octet-stream',
              payload: att.getBytes(),
              muteHttpExceptions: true
            });
            
            if (resp.getResponseCode() !== 200) {
              throw new Error('HTTP ' + resp.getResponseCode() + ': ' + resp.getContentText());
            }
            
            const result = JSON.parse(resp.getContentText());
            base64File = result.base64;
          } catch (e) {
            tg('⚠️ Apps Script Excel-to-CSV convert error: ' + e.message + '. Falling back to raw Excel compression.');
            const gzipped = Utilities.gzip(att.copyBlob());
            base64File = Utilities.base64Encode(gzipped.getBytes());
          }
        } else {
          const gzipped = Utilities.gzip(att.copyBlob());
          base64File = Utilities.base64Encode(gzipped.getBytes());
        }

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
          GmailApp.sendEmail(email, 'Whoa, that file is a unit! — KampusVibes', '', {
            htmlBody: buildEmailHtml_({
              status: 'error',
              title: "Whoa, that file is a unit!",
              message: "We got your timetable, but it's way too big for our auto-compiler to handle " +
                       "(even after zipping it). Hit us up at askkampusvibes@gmail.com and " +
                       "we'll process it manually for you.",
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
            title: "Got it!",
            titleEmoji: "&#x1F680;",
            message: "Awesome, your " + cohort.label + " timetable is in the pipeline. " +
                     "We're running some checks on it now. Once it's verified, it'll show up " +
                     "in the app automatically. You're all set!",
            note: "(Heads up: If it's not live in the app within 24 hours, it might have been " +
                  "rejected due to conflicts. In that case, email us at askkampusvibes@gmail.com and we'll check it out!)",
            rows: [
              ['Cohort', cohort.label + ' (Batch ' + cohort.batch + ')'],
              ['Semester', 'Semester ' + cohort.semester],
              ['Email Subject', subject],
              ['File', fname],
              ['Received At', when],
            ],
          });
          GmailApp.sendEmail(sender, 'Got your timetable! \u2713 — KampusVibes', '', {
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
            title: "Ah, something went sideways...",
            message: "We hit a snag (error code " + code + ") while parsing your timetable. " +
                     "Shoot us a line at askkampusvibes@gmail.com and we'll fix it.",
            rows: [
              ['Email Subject', subject],
              ['File', fname],
              ['Received At', when],
            ],
          });
          GmailApp.sendEmail(sender, 'Oops, timetable upload failed — KampusVibes', '', {
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
  const badgeBg     = isSuccess ? '#4ADE80' : '#F87171'; // Mint Green vs Soft Coral
  const badgeText   = isSuccess ? 'GOT IT! &#x1F389;' : 'WHOOPS! &#x1F4A5;';

  const rowsHtml = (opts.rows || []).map(function (r, i) {
    const borderBottom = i === opts.rows.length - 1 ? '' : 'border-bottom: 2px solid #1E293B;';
    return (
      '<tr>' +
        '<td class="row-label" style="padding:12px 16px;background:#F8FAFC;color:#475569;' +
            'font-size:11px;font-weight:800;letter-spacing:0.5px;text-transform:uppercase;width:35%;' +
            'border-right:2px solid #1E293B;' + borderBottom + '">' +
            esc_(r[0]) +
        '</td>' +
        '<td class="row-value" style="padding:12px 16px;background:#FFFFFF;color:#1E293B;' +
            'font-size:13px;font-weight:600;font-family:monospace;' + borderBottom + '">' +
            esc_(r[1]) +
        '</td>' +
      '</tr>'
    );
  }).join('');

  return (
'<!DOCTYPE html><html><head><meta charset="utf-8">' +
'<meta name="viewport" content="width=device-width,initial-scale=1.0">' +
'<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@600;800;900&family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap" rel="stylesheet">' +
'<style>' +
  '@media only screen and (max-width: 480px) {' +
    '.outer-wrap { padding: 16px 6px !important; }' +
    '.card { border-radius: 12px !important; box-shadow: 4px 4px 0px #1E293B !important; border-width: 2px !important; }' +
    '.header-cell { padding: 16px 16px !important; }' +
    '.brand-pill { font-size: 12px !important; padding: 3px 10px !important; }' +
    '.bot-version { font-size: 10px !important; }' +
    '.body-cell { padding: 24px 16px 16px !important; }' +
    '.status-badge { font-size: 11px !important; padding: 5px 12px !important; box-shadow: 2px 2px 0px #1E293B !important; }' +
    '.title-h1 { font-size: 20px !important; margin: 14px 0 8px !important; }' +
    '.body-text { font-size: 14px !important; }' +
    '.table-cell { padding: 8px 16px 16px !important; }' +
    '.data-table { box-shadow: 2px 2px 0px rgba(30,41,59,0.15) !important; border-width: 2px !important; }' +
    '.row-label { padding: 8px 10px !important; font-size: 10px !important; width: 30% !important; }' +
    '.row-value { padding: 8px 10px !important; font-size: 12px !important; word-break: break-all !important; }' +
    '.note-cell { padding: 0px 16px 8px !important; }' +
    '.note-text { font-size: 11px !important; }' +
    '.footer-cell { padding: 16px 16px 20px !important; }' +
    '.footer-text { font-size: 10px !important; }' +
  '}' +
'</style>' +
'</head>' +
'<body style="margin:0;padding:0;background:#EEF2FF;' +
    'font-family:\'Plus Jakarta Sans\',-apple-system,BlinkMacSystemFont,sans-serif;">' +
'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="outer-wrap" style="background:#EEF2FF;padding:32px 12px;">' +
  '<tr><td align="center">' +
    '<table role="presentation" width="550" cellpadding="0" cellspacing="0" class="card" ' +
        'style="max-width:550px;width:100%;background:#FFFFFF;border:3px solid #1E293B;border-radius:16px;' +
        'box-shadow:6px 6px 0px #1E293B;overflow:hidden;">' +
      
      '<!-- Top Banner/Header -->' +
      '<tr><td class="header-cell" style="padding:24px 32px;background:#F8FAFC;border-bottom:3px solid #1E293B;text-align:left;">' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">' +
          '<tr>' +
            '<td>' +
              '<div class="brand-pill" style="display:inline-block;background:#FFE4E6;color:#E11D48;' +
                  'border:2px solid #1E293B;font-family:\'Outfit\',sans-serif;font-weight:900;' +
                  'font-size:14px;padding:4px 12px;border-radius:8px;box-shadow:2px 2px 0px #1E293B;">' +
                'KampusVibes &#x26A1;' +
              '</div>' +
            '</td>' +
            '<td align="right">' +
              '<div class="bot-version" style="font-size:11px;font-weight:700;color:#64748B;letter-spacing:0.5px;">' +
                'TIMETABLE BOT v2.1' +
              '</div>' +
            '</td>' +
          '</tr>' +
        '</table>' +
      '</td></tr>' +

      '<!-- Content Body -->' +
      '<tr><td class="body-cell" style="padding:36px 32px 20px;text-align:center;">' +
        '<div style="margin-bottom:20px;">' +
          '<div class="status-badge" style="display:inline-block;background:' + badgeBg + ';color:#1E293B;' +
              'border:2.5px solid #1E293B;font-family:\'Outfit\',sans-serif;font-weight:900;' +
              'font-size:13px;letter-spacing:0.5px;padding:6px 16px;border-radius:8px;' +
              'box-shadow:3px 3px 0px #1E293B;text-transform:uppercase;">' +
              badgeText +
          '</div>' +
        '</div>' +
        '<h1 class="title-h1" style="margin:20px 0 10px;font-family:\'Outfit\',sans-serif;font-size:26px;color:#1E293B;font-weight:900;letter-spacing:-0.5px;">' +
          esc_(opts.title) + (opts.titleEmoji ? ' ' + opts.titleEmoji : '') +
        '</h1>' +
        '<p class="body-text" style="margin:0 auto;max-width:440px;font-size:15px;line-height:1.6;color:#475569;font-weight:600;">' +
          esc_(opts.message) +
        '</p>' +
      '</td></tr>' +

      '<!-- Dynamic Data Table -->' +
      (rowsHtml ?
      '<tr><td class="table-cell" style="padding:10px 32px 20px;">' +
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="data-table" ' +
            'style="border:2.5px solid #1E293B;border-radius:10px;overflow:hidden;box-shadow:3px 3px 0px rgba(30,41,59,0.15);">' +
            rowsHtml +
        '</table>' +
      '</td></tr>' : '') +

      '<!-- Note below table -->' +
      (opts.note ?
      '<tr><td class="note-cell" style="padding:0px 32px 10px;text-align:center;">' +
        '<p class="note-text" style="margin:0 auto;max-width:440px;font-size:12px;line-height:1.5;color:#64748B;font-weight:600;font-style:italic;">' +
          esc_(opts.note) +
        '</p>' +
      '</td></tr>' : '') +

      '<!-- Lined Paper Style Footer decoration -->' +
      '<tr><td class="footer-cell" style="padding:20px 32px 28px;text-align:center;">' +
        '<div style="border-top:2px dashed #CBD5E1;margin-bottom:20px;"></div>' +
        '<p class="footer-text" style="margin:0;font-size:11px;color:#64748B;font-weight:600;line-height:1.6;">' +
          'Catch you in class! &#x1F4DA;<br>' +
          'Made with &#x1F4BB; by KampusVibes devs. Hit a snag? Email us at askkampusvibes@gmail.com.' +
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

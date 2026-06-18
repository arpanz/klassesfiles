// ─────────────────────────────────────────────────────────────────────────────
// Telegram control-plane webhook (replaces the flaky Apps Script doPost).
//
// Telegram POSTs every update here. Netlify Functions return a clean HTTP 200,
// so there's no 302-redirect issue and no retry storms. Handles:
//   • Inline buttons (callback_query): apprv / rejct / rbk / block
//   • Admin commands (message text):   /block /unblock /blocked /help
//
// Blocklist is stored in Netlify Blobs (store "kv", key "blocklist") and is read
// by the Apps Script email gate via the companion `blocklist` function.
//
// Required Netlify environment variables:
//   TELEGRAM_TOKEN          - bot token
//   GITHUB_TOKEN            - fine-grained PAT (contents + PRs + actions, klassesfiles)
//   MY_TELEGRAM_USER_ID     - your numeric Telegram id (only you can act)
//   TELEGRAM_WEBHOOK_SECRET - (optional) value also set as Telegram's secret_token
// ─────────────────────────────────────────────────────────────────────────────
import { getStore } from '@netlify/blobs';

const TELEGRAM_TOKEN  = process.env.TELEGRAM_TOKEN;
const GITHUB_TOKEN    = process.env.GITHUB_TOKEN;
const ADMIN_ID        = String(process.env.MY_TELEGRAM_USER_ID || '');
const WEBHOOK_SECRET  = process.env.TELEGRAM_WEBHOOK_SECRET || '';

const OWNER = 'arpanz';
const REPO  = 'klassesfiles';

// ── Telegram helpers ──
const tg = (method, payload) =>
  fetch(`https://api.telegram.org/bot${TELEGRAM_TOKEN}/${method}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

// ── Blocklist (Netlify Blobs) ──
const store = () => getStore('kv');
async function getBlocklist() {
  try {
    const arr = await store().get('blocklist', { type: 'json' });
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}
async function saveBlocklist(arr) {
  await store().setJSON('blocklist', Array.isArray(arr) ? arr : []);
}
async function blockEmail(email) {
  email = String(email).trim().toLowerCase();
  const s = await getBlocklist();
  if (!s.includes(email)) { s.push(email); await saveBlocklist(s); }
}
async function unblockEmail(email) {
  email = String(email).trim().toLowerCase();
  await saveBlocklist((await getBlocklist()).filter((x) => x !== email));
}

// ── GitHub API ──
const gh = (method, path, body) =>
  fetch(`https://api.github.com${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'Content-Type': 'application/json',
    },
    body: body ? JSON.stringify(body) : undefined,
  });
const mergePR = async (pr) =>
  (await gh('PUT', `/repos/${OWNER}/${REPO}/pulls/${pr}/merge`, { merge_method: 'squash' })).status === 200;
const closePR = async (pr) =>
  (await gh('PATCH', `/repos/${OWNER}/${REPO}/pulls/${pr}`, { state: 'closed' })).status === 200;
const dispatchRollback = async (batch, ftype, fname) =>
  (await gh('POST', `/repos/${OWNER}/${REPO}/actions/workflows/rollback.yml/dispatches`, {
    ref: 'master',
    inputs: { batch: String(batch), file_type: ftype, file_name: fname, commits_back: '1' },
  })).status === 204;

// ── Update handlers ──
async function handleCallback(cq) {
  if (String(cq.from && cq.from.id) !== ADMIN_ID) {
    await tg('answerCallbackQuery', { callback_query_id: cq.id, text: 'Not authorized' });
    return;
  }
  const parts = String(cq.data).split(':');
  const action = parts[0];
  let msg = 'Unknown action';

  if (action === 'apprv') {
    msg = (await mergePR(parts[1])) ? `✓ PR #${parts[1]} merged — publishing now.`
                                    : `⚠️ Merge failed for PR #${parts[1]} (conflict?).`;
  } else if (action === 'rejct') {
    msg = (await closePR(parts[1])) ? `✗ PR #${parts[1]} closed — change discarded.`
                                    : `⚠️ Could not close PR #${parts[1]}.`;
  } else if (action === 'rbk') {
    msg = (await dispatchRollback(parts[1], parts[2], parts[3]))
            ? `↩️ Rollback started for ${parts[3]}.`
            : `⚠️ Rollback dispatch failed.`;
  } else if (action === 'block') {
    await blockEmail(parts[1]);
    msg = '🚫 Blocked ' + parts[1] + ' — their future uploads will be ignored.';
  }

  await tg('answerCallbackQuery', { callback_query_id: cq.id, text: msg });
  if (cq.message) {
    await tg('editMessageText', {
      chat_id: cq.message.chat.id,
      message_id: cq.message.message_id,
      text: (cq.message.text || '') + '\n\n' + msg,
    });
  }
}

async function handleCommand(m) {
  if (String(m.from && m.from.id) !== ADMIN_ID) return;
  const chat = m.chat.id;
  const text = (m.text || '').trim();
  const cmd = text.split(/\s+/)[0].toLowerCase();
  const arg = text.replace(/^\S+\s*/, '').trim().toLowerCase();
  const reply = (t) => tg('sendMessage', { chat_id: chat, text: t });

  if (cmd === '/block') {
    if (!arg) return reply('Usage: /block someone@college.edu');
    await blockEmail(arg);
    return reply('🚫 Blocked: ' + arg);
  } else if (cmd === '/unblock') {
    if (!arg) return reply('Usage: /unblock someone@college.edu');
    await unblockEmail(arg);
    return reply('✓ Unblocked: ' + arg);
  } else if (cmd === '/blocked') {
    const list = await getBlocklist();
    return reply(list.length ? '🚫 Blocked senders:\n' + list.join('\n') : 'No one is blocked.');
  } else if (cmd === '/help' || cmd === '/start') {
    return reply('Commands:\n/block <email>\n/unblock <email>\n/blocked');
  }
}

// ── Netlify entrypoint ──
export default async (req) => {
  // Optional defence-in-depth: verify Telegram's secret-token header.
  if (WEBHOOK_SECRET) {
    const got = req.headers.get('x-telegram-bot-api-secret-token');
    if (got !== WEBHOOK_SECRET) return new Response('forbidden', { status: 403 });
  }
  if (req.method !== 'POST') return new Response('ok'); // health check / GET

  let update;
  try {
    update = await req.json();
  } catch {
    return new Response('ok');
  }

  try {
    if (update.callback_query) await handleCallback(update.callback_query);
    else if (update.message && update.message.text) await handleCommand(update.message);
  } catch (err) {
    console.error('telegram fn error:', err);
  }

  // Always 200 so Telegram never retries.
  return new Response('ok');
};

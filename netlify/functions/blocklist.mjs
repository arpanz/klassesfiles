// ─────────────────────────────────────────────────────────────────────────────
// Read-only blocklist endpoint for the Apps Script email gate.
//
// The Telegram webhook (telegram.mjs) writes the blocklist into Netlify Blobs;
// Apps Script's processIncomingTimetables reads it from here to drop uploads
// from blocked senders.
//
// Protected by a shared key so the list of blocked emails isn't public:
//   GET /.netlify/functions/blocklist?key=<BLOCKLIST_READ_KEY>
//
// Required Netlify environment variable:
//   BLOCKLIST_READ_KEY - shared secret; the same value is stored in the Apps
//                        Script project as a Script Property `BLOCKLIST_KEY`.
// ─────────────────────────────────────────────────────────────────────────────
import { getStore } from '@netlify/blobs';

export default async (req) => {
  const key = new URL(req.url).searchParams.get('key');
  if (!process.env.BLOCKLIST_READ_KEY || key !== process.env.BLOCKLIST_READ_KEY) {
    return new Response('forbidden', { status: 403 });
  }

  let list = [];
  try {
    const arr = await getStore('kv').get('blocklist', { type: 'json' });
    if (Array.isArray(arr)) list = arr;
  } catch {
    list = [];
  }

  return new Response(JSON.stringify(list), {
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
};

# Telegram control plane on Netlify

The Telegram webhook (commands + buttons) runs as a **Netlify Function** instead of
Google Apps Script, because Apps Script web apps return 302 redirects that Telegram
rejects (causing dropped/duplicate/stuck messages). Netlify returns a clean `200`.

```
Telegram  ──POST──►  /.netlify/functions/telegram   (commands + Approve/Reject/Undo/Block)
                          │  reads/writes
                          ▼
                     Netlify Blobs  ("kv" → "blocklist")
                          ▲  reads (HTTP)
Apps Script  ───────────►  /.netlify/functions/blocklist?key=…   (email gate)
```

Apps Script still runs the **email ingestion** only (`processIncomingTimetables`, 15-min trigger).

## 1. Netlify environment variables

Site → **Site configuration → Environment variables** → add:

| Key | Value |
|---|---|
| `TELEGRAM_TOKEN` | your bot token |
| `GITHUB_TOKEN` | fine-grained PAT for `klassesfiles` (Contents + Pull requests + Actions, R/W) |
| `MY_TELEGRAM_USER_ID` | your numeric Telegram id (e.g. `847736921`) |
| `BLOCKLIST_READ_KEY` | any long random string (shared with Apps Script) |
| `TELEGRAM_WEBHOOK_SECRET` | *(optional)* any random string for extra webhook auth |

Redeploy the site after adding these (Deploys → Trigger deploy), so the functions pick them up.

## 2. Point Telegram at the Netlify function

```
https://api.telegram.org/bot<TELEGRAM_TOKEN>/setWebhook?url=https://klassesfiles.netlify.app/.netlify/functions/telegram&drop_pending_updates=true
```

If you set `TELEGRAM_WEBHOOK_SECRET`, append `&secret_token=<that-value>`.

Verify:
```
https://api.telegram.org/bot<TELEGRAM_TOKEN>/getWebhookInfo
```
Expect `pending_update_count: 0` and no `last_error_message`.

## 3. Apps Script

- Paste the updated `apps_script/Code.gs` (webhook code removed; `isBlocked_` now reads Netlify).
- In **Project Settings → Script Properties**, add `BLOCKLIST_KEY` = the **same** value as `BLOCKLIST_READ_KEY` above. (Keep `GITHUB_TOKEN`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT`.)
- You can now **delete the Web App deployment** — Apps Script no longer serves the webhook. The 15-min time trigger on `processIncomingTimetables` stays.

## 4. Test

- `/blocked` → replies (instant, reliable).
- `/block test@kiit.ac.in` → "🚫 Blocked: …"; `/blocked` lists it; `/unblock …` removes it.
- Tap **🚫 Block sender** on a dispatch card → blocks that sender.
- Approve / Reject / Undo buttons on held-PR / published cards → work via GitHub API.

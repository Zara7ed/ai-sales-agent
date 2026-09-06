# AI Sales Agent

Multichannel AI salesperson (Telegram + Instagram + Web widget) backed by a
tiered LLM router, local SQLite memory, and an editable business knowledge base.

## Features

- 💬 **3 channels:** Telegram bot (webhook), Instagram (Meta webhooks), web widget (`/widget` + `/api/chat`).
- 🔀 **Tiered LLM fallback:** primary → secondary → local model, all OpenAI-compatible (`base_url/key/model` triples).
- 🧠 **Local-first memory:** per-user SQLite conversation history, no cloud store.
- 📚 **Business KB:** services/prices, FAQs, policies, objection handlers, sales scenarios — JSON file with hot-reload.
- 🛠️ **Admin panel:** REST CRUD (`/api/admin/*`) + single-file UI (`admin/static/admin.html`).
- 🐳 **One-command deploy:** Dockerfile + docker-compose.

## Architecture

```
                    +------------------+
                    |   Telegram API   |
                    +--------+---------+
                             | webhook
                    +--------+---------+      +------------------+
                    |  channels/       |      |  Instagram       |
                    |  telegram.py     +------+  Graph API       |
                    +--------+---------+      +------------------+
                             |
              +--------------+--------------+
              |              |              |
     +--------+------+ +-----+--------+ +---+------------+
     |  web/app.py   | | admin/panel  | | web widget     |
     |  /api/chat   | | /api/admin/* | | static/*.html  |
     +-------+-------+ +------+-------+ +----------------+
             |                |
     +-------+----------------+-------+
     |        core/agent.py            |  sales brain: KB lookup -> LLM -> reply
     +-------+----------------+-------+
             |                |
   +---------+------+  +------+------+  +-----+--------+
   | core/knowledge |  | core/memory |  | core/llm_    |
   | BusinessKB     |  | SQLite      |  | router       |
   | (JSON+reload)  |  | history     |  | 3-tier       |
   +----------------+  +-------------+  +--------------+
                                                     |
                         primary -> secondary -> local (Ollama)
```

## Quickstart

```bash
cp .env.example .env        # fill in tokens + LLM keys
pip install -r requirements.txt
cp data/seed_business.json data/business.json   # first run does this automatically
uvicorn web.app:app --reload --port 8000
# chat:  POST http://localhost:8000/api/chat {"user_id":"u1","text":"How much is cleaning?"}
# admin: open http://localhost:8000/admin/  (serve admin/static via web app)
```

Run tests:

```bash
pytest tests/test_smoke.py -v
```

Docker:

```bash
docker compose up --build
```

## Channel setup

### Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather), put the token in `TELEGRAM_TOKEN`.
2. Expose your server publicly (HTTPS), then set the webhook:
   `https://api.telegram.org/bot<TOKEN>/setWebhook?url=<TELEGRAM_WEBHOOK_URL>/webhooks/telegram&secret_token=<TELEGRAM_WEBHOOK_SECRET>`.
3. Incoming updates hit `POST /webhooks/telegram`; replies go out via Bot API `sendMessage`.

### Instagram (Meta)

1. Create a Meta app + Instagram Business/Creator account linked to a Page.
2. Set `IG_VERIFY_TOKEN`, `IG_PAGE_ACCESS_TOKEN`, `IG_APP_SECRET` in `.env`.
3. Configure webhook `GET/POST /webhooks/instagram` with subscribe fields `messages,messaging_postbacks`.
4. Verification echoes `hub.challenge`; signatures are checked against `IG_APP_SECRET`.

### Web widget

Embed `web/static/widget.js` (or open `/widget`) on any site; it POSTs to `/api/chat`.

## Admin usage

- UI: single file `admin/static/admin.html` (vanilla JS, no build). Set the bearer
  token field to `ADMIN_TOKEN`, then Load/Save the full KB JSON or CRUD sections.
- API (all under `/api/admin`, Bearer auth when `ADMIN_TOKEN` is set):

| Method | Path | Meaning |
|---|---|---|
| GET/PUT | `/api/admin/kb` | full KB read/replace |
| GET/POST | `/api/admin/services` etc. | list / create (`{"item":{...}}`) |
| PUT/DELETE | `/api/admin/services/{id}` etc. | update / delete |
| POST | `/api/admin/reload` | hot-reload hook |

Sections: `services`, `faqs`, `sales_scenarios` (alias `scenarios`),
`objection_handlers` (alias `objections`). Every write persists
`data/business.json` atomically and fires registered reload hooks so the
running agent picks up changes without restart.

## Layout

```
admin/panel.py  admin REST router + reload hooks
admin/static/admin.html  no-build admin UI
channels/  telegram.py, instagram.py (parallel track)
core/  config, llm_router, memory, knowledge, agent (parallel track)
data/seed_business.json  example business KB
web/app.py  FastAPI app: /api/chat, /webhooks/*, /admin (parallel track)
tests/test_smoke.py  import + KB assertions
```

## Owner control, ops API & deploy (new)

- **owner.py** — `OwnerMode` over `ConversationStore`: `enable_live(user_id)`
  forwards that user's exchanges to you as Persian live-feed text
  (`forward_payload`); `takeover(user_id, bool)` silences the bot so you can
  reply manually; `is_takeover()` gates auto-replies in channel adapters.
- **adminbot.py** — owner Telegram bot as pure functions:
  `handle_owner_command(text, owner_id)` handles `/stats`, `/takeover`,
  `/release`, `/watch`, `/reminders`, `/kb get <section>` (Persian replies,
  gated by `OWNER_TELEGRAM_ID`); `answer_admin_question()` chats with the
  agent in `owner-advisory` mode.
- **admin/ops.py** — ops router (`/api/ops`): `GET /contacts`,
  `GET /contacts/{id}`, `GET /reminders/due`, `POST /deals/move`,
  `GET /lessons`. Uses `crm.py`/`learning.py` when present, else falls back
  to the bot SQLite DB. Mount with `app.include_router(ops_router)`.
- **Deploy** — `railway.toml` (reuses the existing `Dockerfile`) +
  `Procfile` (`uvicorn main:app`, `$PORT`).
- **Env** — see `.env.example`: `OWNER_TELEGRAM_ID`, `STT_*`, `PAYMENT_*`
  (payment specifics live in the KB per business, env only holds defaults).

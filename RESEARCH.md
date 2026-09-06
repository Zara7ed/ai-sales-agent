# Research: LLM Gateway / Sales-Bot Landscape

How existing tools route, remember, and sell — and what this project borrows.

## 1. 9router — local OpenAI-compatible gateway

- Runs locally, exposes an OpenAI-compatible `/v1` API so any client works unchanged.
- **3-tier fallback:** subscription endpoint → cheap API → free tier. If tier N
  fails/rate-limits, the request cascades to N+1 automatically.
- Focus: cost saving for individual developers, zero code changes.

## 2. OmniRoute — TypeScript fork with strategy engine

- Fork of the 9router idea in TypeScript.
- **4 tiers** and **19 routing strategies** (priority, round-robin,
  latency-weighted, cost-weighted, model-match, etc.).
- Adds **prompt compression** (strip boilerplate, truncate history) to cut tokens.
- Focus: experimentation with routing policy as configuration.

## 3. LiteLLM — provider normalization library

- Python library (+ proxy server) unifying 100+ providers behind one
  `completion(model=...)` call with consistent messages, retries, fallbacks.
- Strength: translation of auth, params, streaming, and errors across providers.
- Weakness: still a library, not a full agent — no memory/KB/sales logic.

## 4. OpenRouter — cloud aggregator

- Hosted meta-API: one key, hundreds of models, automatic failover and
  price/throughput sorting.
- Strength: zero ops, huge model choice. Weakness: data leaves your server,
  per-token markup, no local memory.

## 5. Rasa — on-prem NLU framework

- Self-hosted intent/entity NLU + dialogue stories/rules, full data control.
- Strength: deterministic flows, auditable. Weakness: heavy training/DevOps,
  weak at open-ended selling without an LLM bolted on.

## 6. Botpress — visual conversation builder

- Visual flow studio, channel connectors, hosted or self-hosted.
- Strength: non-dev editing, fast prototypes. Weakness: vendor lock-in,
  flows get brittle at scale, LLM calls are opaque add-ons.

## Comparison

| Tool | Runs local | OpenAI-compat | Fallback tiers | Memory | Sales logic | Cost |
|---|---|---|---|---|---|---|
| 9router | yes | yes | 3 | no | no | sub+cheap+free |
| OmniRoute | yes | yes | 4 | no | no | configurable |
| LiteLLM | lib | via proxy | N (config) | no | no | pass-through |
| OpenRouter | no (cloud) | yes | auto | no | no | markup |
| Rasa | yes | no | n/a | slots | stories | ops-heavy |
| Botpress | opt | no | n/a | variables | visual flows | license |
| **This project** | yes | yes (client-side) | 3 (primary→secondary→local) | SQLite | KB + scenarios + objections | minimal |

## 3 ideas this project borrows

1. **Tiered fallback combos (9router/OmniRoute):** primary subscription model →
   cheap API model → free local model (Ollama). Same cascade idea, but
   implemented as a small `LLMRouter` trying OpenAI-compatible endpoints in
   order instead of a separate gateway process.
2. **OpenAI-compatible provider abstraction (LiteLLM/OpenRouter):** every tier
   speaks the OpenAI chat-completions dialect over HTTP (`base_url/key/model`
   triple in `.env`), so providers are interchangeable without code changes.
3. **Local-first SQLite memory (Rasa's on-prem spirit, minus the training):**
   conversation state and the business KB live in local files/SQLite, editable
   from the admin panel with hot-reload — no cloud dependency for data.

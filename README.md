# Telegram Lead Monitor

> **Automated lead discovery pipeline** · Python · FastAPI · PostgreSQL · Playwright · aiogram · CI/CD
>
> Repository codename: `parcertg`.

Telegram Lead Monitor collects potential development leads from several Telegram-related sources, scores them with transparent rules, removes duplicates and sends only relevant opportunities to a private Telegram bot.

This project is a compact portfolio example of data ingestion, browser automation, scoring, deduplication and production deployment without requiring an LLM in the critical decision path.

## What it does

- Collects lead notifications from Telegram Web/Telemetrio.
- Supports TGStat callbacks and Telethon as optional providers.
- Scores leads from 0–100 with deterministic rules.
- Prioritizes Python, FastAPI, Telegram, AI integration, CRM and automation work.
- Filters service ads, resumes, barter and irrelevant offers.
- Performs exact and fuzzy deduplication across providers.
- Persists leads and decisions in PostgreSQL.
- Sends actionable lead cards to an aiogram bot.
- Tracks operator decisions such as accepted / not relevant / spam.
- Runs automated CI and exact-SHA production deployment.

## Architecture

```text
Telemetrio monitoring
        |
        v
Telegram alert chat
        |
        v
Playwright / Telegram Web collector
        |
        +------------------------+
                                 v
TGStat callback ------------> LeadProcessor
Telethon sources ----------->     |
                                 +--> scoring
                                 +--> deduplication
                                 +--> PostgreSQL
                                 +--> Telegram notification bot
```

All providers converge on the same `LeadProcessor`, so provider-specific transport is separated from scoring and persistence.

## Why deterministic scoring

The main ranking path intentionally does not require an LLM. Rules remain:

- inspectable;
- cheap to execute;
- deterministic;
- easy to tune;
- safe from prompt-injection-style content in scraped messages.

The default threshold can be configured with `MIN_LEAD_SCORE`.

## Stack

| Area | Technology |
| --- | --- |
| Backend | Python, FastAPI |
| Notifications | aiogram |
| Browser automation | Playwright / Chromium |
| Database | PostgreSQL, SQLite for local development |
| Optional sources | TGStat Callback API, Telethon |
| Quality | Ruff, pytest, compileall, Compose validation |
| Delivery | Docker, GitHub Actions, exact-SHA deployment |

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
```

For the browser collector:

```bash
python -m playwright install chromium
```

## Production behavior

The deployment workflow builds and verifies the candidate commit before deploying it. The deploy script keeps `.env` outside source control and blocks parallel deployments.

The browser profile contains an authenticated Telegram session and is treated as secret runtime data; it is never intended for source control.

## Security boundaries

- The service does **not** automatically message customers.
- `.env`, browser profiles, SSH keys and Telegram sessions must remain outside Git.
- The same browser profile must not be opened by multiple Chromium processes.
- External provider terms and personal-data requirements must be respected.

## Portfolio note

This project demonstrates a practical automation pipeline: multiple ingestion adapters, browser automation, deterministic classification, fuzzy deduplication, persistence and operational deployment in a relatively small codebase.

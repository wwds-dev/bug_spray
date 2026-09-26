# Bug Spray — TODO

> **Legend** — priority `P0` critical · `P1` high · `P2` normal · `P3` low
> categories `security` `bug` `feature` `performance` `design` `docs` `testing` `infra` `research`
> owner `@me` (needs you — accounts, keys, judgement) · `@ai` (Claude can do this)

---

## v1 — complete (2026-09-25): real discovery, no auth needed

- [x] `P1` `feature` `@ai` Sentinel integration (2026-09-26): saved program and change feed in the Bug Spray workspace, searchable program list, live-page link, program-name handoff to report drafting, and background scans while Sentinel runs. Scan history and events persist across app restarts; concurrent scans are refused.

- [x] `P0` `feature` `@ai` HackerOne public program directory adapter — this is the highest-value single source and needs no API key. *Reads the site's anonymous GraphQL directory; the documented Hacker API turned out to need a token even for public programs.*
- [x] `P1` `feature` `@ai` `models.py`: `Program`, `Scope`, `RewardTier` dataclasses shared by every adapter
- [x] `P1` `feature` `@ai` `store.py`: SQLite snapshot cache + diff-since-last-run
- [x] `P1` `feature` `@ai` CLI `scan` command: fetch, store, print what changed
- [x] `P1` `feature` `docs` `@ai` `sentinel_chat_agent.py`: `BugBountyAgent`, the LLM-only Sentinel in-app Bug Spray (`bug_bounty`) chat agent that turns operator-supplied recon/PoC data into a vulnerability report and a submission draft — now documented in README.
- [x] `P2` `feature` `@ai` Watchlist filters in `config.json` (keywords, min reward, tags) — `watchlist.py`; filters what is reported, never what is stored
- [x] `P2` `testing` `@ai` `main.py --selftest` per the lab convention — checks config loads, DB opens, adapters import cleanly, no network call required
- [x] `P3` `feature` `@ai` Bugcrowd, Intigriti, YesWeHack, Immunefi adapters, same interface as HackerOne's — all anonymous; login-walled Intigriti programs (registered-only / terms / 2FA) are stored from the listing only
- [x] `P2` `infra` `@ai` Rebuild the venv on the Mac (2026-09-25; the old one was a Linux venv from a bridge session, `python` a dangling symlink). `_Admin/rebuild_envs.sh` only walks the top level of `active/` and never reached this nested repo, so it was rebuilt directly with `uv` — command in README → Environment.
- [x] `P1` `feature` `@ai` Full change detection: new programs, reward changes per severity, paused/resumed, and gone/back (dropped out of / returned to the public listing) on top of scope diffing — `changes.py`
- [x] `P1` `performance` `@ai` Store a snapshot only when a program changed; skip detail requests when the platform's update marker is unchanged (`scan --full` overrides)
- [x] `P1` `safety` `@ai` One polite HTTP client for every adapter (User-Agent, request spacing, `Retry-After`); a failed detail keeps the last known copy instead of storing an empty scope; a platform listing <50% of last run's programs does not mark the rest gone
- [x] `P2` `feature` `@ai` `list` and `show` commands, `--json` on scan/list/show

## v0 — scaffold (complete)

- [x] `P1` `infra` `@ai` Project skeleton: `pyproject.toml`, `.gitignore`, `bug_spray/` package, `main.py` CLI stub, `tests/`
- [x] `P1` `docs` `@ai` README with the honest-boundary section (what's automatable vs. stays human-in-the-loop)
- [x] `P1` `docs` `@ai` This file + SUGGESTIONS.md
- [x] `P1` `infra` `@me` `git init` this as its own repo and give it the standard pseudonymous identity, or say the word and I'll do it

## v2 — triage workflow

- [ ] `P2` `feature` `@ai` Per-program status board (not started → recon → testing → reported → paid/closed)
- [ ] `P2` `feature` `@ai` Report draft template, pre-filled fields only — no auto-generated finding text
- [ ] `P1` `safety` `@ai` Scope-confirmation gate in front of anything that will eventually touch a live target: user must confirm today's scope before a recon step is allowed to run
- [ ] `P3` `feature` `@ai` Desktop notification / `lab_hub` badge on watchlist changes

### Logged-in sources — your own HackerOne and Intigriti accounts

v1 reads only what is public without an account. That leaves out private programs you are
invited to on HackerOne, and the scope of 22 Intigriti programs that sit behind a login:
registered-only, terms-required and 2FA-required. They are listed today, but with no scope.
Both platforms have an official researcher API for this. Both answered `401` without a
token when checked on 2026-09-25. This uses those APIs with *your* token. It is not scraping
login pages, which stays rejected.

- [ ] `P2` `infra` `@me` HackerOne: create an API token on your own hacker account (Settings → API Token) and note the API username that goes with it. The Hacker API authenticates with *username + token*, so both are needed. Enter them yourself with the `auth` command below; never paste them into a chat, config file or commit.
- [ ] `P2` `infra` `@me` Intigriti: create a personal researcher API token on your account and enter it with `auth`. Accept each program's terms and turn on 2FA in Intigriti's own site first. Bug Spray must never accept terms for you.
- [ ] `P1` `security` `@ai` `auth` command: `auth set hackerone|intigriti` (hidden prompt, nothing echoed or logged), `auth status` (shows only whether a credential is stored), `auth clear`. Stored in the Keychain via `secrets.py`. That needs a second Keychain field for HackerOne's username; add it without changing the existing token key.
- [ ] `P2` `feature` `@ai` HackerOne logged-in source: use the Hacker API (`api.hackerone.com/v1/hackers/programs` plus each program's structured scopes) to add the private programs you are invited to. Merge with the public directory by handle, and tag them `private`.
- [ ] `P2` `feature` `@ai` Intigriti logged-in source: use the researcher API (`api.intigriti.com/external/researcher/v1/programs`) to fill in scope and rewards for the `registered-only` / `terms-required` / `2fa-required` programs and any private invites. Replace those tags with the real data only when the API returns it.
- [ ] `P1` `safety` `@ai` A missing, expired or rejected token falls back to the anonymous source with a one-line notice. A `401`/`403` never fails the platform, and the token never appears in errors, logs or `--json` output.
- [ ] `P1` `security` `@me` `@ai` Private program details are usually under the program's confidentiality terms. Keep them out of anything shared: tag them in the store, and leave them out of anything pushed or published. The Google Drive backup *does* copy it today (checked 2026-09-26): `lab` is in `_Admin/backup/backup_folders.txt` and nothing in the excludes matches `data/`. That is fine for public data, but it must be settled before the first logged-in scan. Either exclude Bug Spray's `data/` from the backup, or keep logged-in data in a separate database outside `~/Documents`. Decision needed: which of the two.

## v3 — opt-in recon (only after v2's guardrails exist)

- [ ] `P2` `feature` `security` `@ai` Authorised assessment path, staged. Split out of the parent list's four-agent "staged specialist integrations" item. Authorisation is the gate, not an afterthought; excludes denial of service, credential theft, stealth/persistence and uncontrolled exploitation. *(split out of sentinel_fork/TODO.md; moved here from v0 -- it's the authorization framework this section's guardrails need, not scaffold work)*
- [ ] `P2` `research` `@me` Decide which recon tools (subdomain enum, endpoint diffing) are worth wiring in, and read each target program's automated-testing rules before wiring anything
- [ ] `P1` `safety` `@ai` Shared rate-limit + scope-guard module every recon adapter must call through — not left to each adapter to remember
- [ ] `P3` `feature` `@ai` Recon run stored as a diffable snapshot, same pattern as program scope

## Explicitly not planned

- [ ] `P0` `security` `@me` **No automated exploitation and no automated report submission, ever, by default.** If this changes, it needs its own explicit opt-in, a per-program authorization confirmation, and a real conversation first — not a config flag flipped in passing.
- Scraping login-walled program pages — not worth the ToS risk. Reading them through the platform's official researcher API with your own token is a different thing, planned under v2 → *Logged-in sources*.

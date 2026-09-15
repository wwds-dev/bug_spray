# Bug Spray — TODO

> **Legend** — priority `P0` critical · `P1` high · `P2` normal · `P3` low
> categories `security` `bug` `feature` `performance` `design` `docs` `testing` `infra` `research`
> owner `@me` (needs you — accounts, keys, judgement) · `@ai` (Claude can do this)

---

## v0 — scaffold (this session)

- [x] `P1` `infra` `@ai` Project skeleton: `pyproject.toml`, `.gitignore`, `bug_spray/` package, `main.py` CLI stub, `tests/`
- [x] `P1` `docs` `@ai` README with the honest-boundary section (what's automatable vs. stays human-in-the-loop)
- [x] `P1` `docs` `@ai` This file + SUGGESTIONS.md
- [x] `P1` `infra` `@me` `git init` this as its own repo and give it the standard pseudonymous identity, or say the word and I'll do it
- [ ] `P2` `infra` `@me` Rebuild the venv via `_Admin/rebuild_envs.sh` once dependencies are non-empty

## v1 — real discovery, no auth needed

- [ ] `P0` `feature` `@ai` HackerOne public program directory adapter — this is the highest-value single source and needs no API key
- [x] `P1` `feature` `@ai` `models.py`: `Program`, `Scope`, `RewardTier` dataclasses shared by every adapter
- [x] `P1` `feature` `@ai` `store.py`: SQLite snapshot cache + diff-since-last-run
- [x] `P1` `feature` `@ai` CLI `scan` command: fetch, store, print what changed
- [x] `P1` `feature` `docs` `@ai` `sentinel_chat_agent.py`: `BugBountyAgent`, the LLM-only Sentinel in-app Bug Spray (`bug_bounty`) chat agent that turns operator-supplied recon/PoC data into a vulnerability report and a submission draft — now documented in README.
- [ ] `P2` `feature` `@ai` Watchlist filters in `config.json` (keywords, min reward, tags)
- [x] `P2` `testing` `@ai` `main.py --selftest` per the lab convention — checks config loads, DB opens, adapters import cleanly, no network call required
- [ ] `P3` `feature` `@ai` Bugcrowd, Intigriti, YesWeHack, Immunefi adapters, same interface as HackerOne's

## v2 — triage workflow

- [ ] `P2` `feature` `@ai` Per-program status board (not started → recon → testing → reported → paid/closed)
- [ ] `P2` `feature` `@ai` Report draft template, pre-filled fields only — no auto-generated finding text
- [ ] `P1` `safety` `@ai` Scope-confirmation gate in front of anything that will eventually touch a live target: user must confirm today's scope before a recon step is allowed to run
- [ ] `P3` `feature` `@ai` Desktop notification / `lab_hub` badge on watchlist changes

## v3 — opt-in recon (only after v2's guardrails exist)

- [ ] `P2` `research` `@me` Decide which recon tools (subdomain enum, endpoint diffing) are worth wiring in, and read each target program's automated-testing rules before wiring anything
- [ ] `P1` `safety` `@ai` Shared rate-limit + scope-guard module every recon adapter must call through — not left to each adapter to remember
- [ ] `P3` `feature` `@ai` Recon run stored as a diffable snapshot, same pattern as program scope

## Explicitly not planned

- [ ] `P0` `security` `@me` **No automated exploitation and no automated report submission, ever, by default.** If this changes, it needs its own explicit opt-in, a per-program authorization confirmation, and a real conversation first — not a config flag flipped in passing.
- Scraping login-walled program pages — the public-API programs already cover the useful surface; not worth the ToS risk.

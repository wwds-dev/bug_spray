# Bug Spray — Suggestions

Status: `IDEA` · `CONSIDERING` · `PLANNED` · `DONE` · `REJECTED`

---

## Discovery and monitoring

| # | Suggestion | Category | Effort | Status |
|---|---|---|---|---|
| 15 | Opt-in VDP tracking (programs with no payout) — v1 deliberately fetches bounty-paying programs only; VDPs are useful for reputation-building, and Bugcrowd's would add ~440 requests per scan | feature | S | IDEA |
| 16 | Optional launchd scans while Sentinel is closed. The in-app feed already scans on the configured interval while Sentinel runs; an OS job would extend that to times the app is closed. | feature | S | IDEA |
| 17 | Token-backed HackerOne/Intigriti sources for the private and login-walled programs *you* are invited to, via `secrets.py` (Keychain) — needs your own API tokens | feature | M | IDEA |
| 5 | Digest notification (desktop notification or a `lab_hub` badge) when a watched program changes | feature | S | IDEA |

## Triage workflow (human-in-the-loop)

| # | Suggestion | Category | Effort | Status |
|---|---|---|---|---|
| 6 | Per-program notes/status board (not started / recon / testing / reported / paid / closed) | feature | M | IDEA |
| 7 | Report draft template pre-filled with program name, asset, and severity — human writes the actual finding | feature | S | IDEA |
| 8 | Scope-confirmation gate: before any recon step runs against a target, require the user to confirm they're looking at *today's* scope, not a cached one | safety | S | PLANNED |
| 9 | Personal payout ledger (what was submitted, paid, or rejected, per program) — local only, not a tax tool | feature | S | IDEA |

## Recon automation (opt-in, scope-gated)

| # | Suggestion | Category | Effort | Status |
|---|---|---|---|---|
| 10 | Subdomain enumeration against a *confirmed in-scope* root domain, rate-limited to the program's stated limits | feature | L | CONSIDERING |
| 11 | Endpoint/tech-stack diffing between recon runs, so "what changed on this target since last week" is visible | feature | M | IDEA |
| 12 | Rate-limit and out-of-scope guardrails as a shared module every recon adapter must call through, not a convention each adapter remembers | safety | M | CONSIDERING |

## Interface

| # | Suggestion | Category | Effort | Status |
|---|---|---|---|---|
| 13 | `lab_hub` launch card once the CLI workflow is proven useful | feature | M | IDEA |
| 14 | PySide6 GUI (dashboard of watched programs, diff feed, triage board) mirroring `sonar`'s card layout | feature | XL | IDEA |

## Done

| Suggestion | When |
|---|---|
| `sentinel_chat_agent.py` (`BugBountyAgent`) shipped as Sentinel's in-app Bug Spray chat agent, and documented in README | 2026-09-15 |
| #1 HackerOne adapter (anonymous GraphQL directory — the JSON:API needs a token) and #2 Bugcrowd, Intigriti, YesWeHack, Immunefi adapters behind the same `fetch_programs()` interface | 2026-09-25 |
| #3 Snapshot diffing: scope added/removed, reward changes per severity, new programs, paused/resumed, gone/back | 2026-09-25 |
| #4 Watchlist filters: keywords, tags, minimum reward (approximate USD) | 2026-09-25 |
| Sentinel Program radar: saved program and change feed, searchable list, program link and report handoff; interval scans while the app runs | 2026-09-26 |

## Rejected

| Suggestion | Why |
|---|---|
| Fully autonomous "find and submit" pipeline | Violates nearly every program's rules on automated/bulk submissions; risks the account, not just wasted effort. See the honest-boundary section in [README.md](README.md). |
| Auto-exploitation against any target not confirmed in-scope right now | No cached scope snapshot is authorization — scope changes, and testing against stale scope is testing without authorization. |
| Scraping platforms without a public API (login-walled program pages) | Fragile, likely against platform ToS, and the public-API programs already cover the useful surface. |

# Bug Spray — bug bounty radar & triage assistant

Bug Spray watches public bug bounty platforms for programs worth hunting on, tracks their
scope and reward changes over time, and gives a human hunter a triage queue instead of a
pile of open tabs. It does **not** scan or exploit anything by itself.

## The honest boundary

The pitch that gets written for tools like this is "an app that finds and solves bug
bounties automatically." That framing doesn't survive contact with how bug bounty actually
works, so Bug Spray is built around a narrower, real version of it:

- **Discovery and monitoring are automatable and useful.** Pulling program lists, scope,
  and reward tables from public APIs, diffing them against yesterday's snapshot, and
  surfacing "this program just expanded scope" or "this program just raised payouts" is a
  legitimate, mechanical job. This is most of what v1 does.
- **Recon inside an explicit, in-scope target is automatable, carefully.** Once a human has
  picked a program and confirmed current scope, routine recon (subdomain enumeration,
  endpoint diffing, tech fingerprinting) against *that* scope, at a rate that respects the
  program's stated limits, is reasonable to automate and queue for review.
- **Vulnerability discovery, exploitation, and report writing stay human-in-the-loop.**
  Almost every program's rules explicitly forbid automated/bulk scanning that isn't
  scope-aware and rate-limited, and forbid submitting auto-generated reports. A hunter who
  lets a tool submit for them risks a ban, not income. Bug Spray's job here is to shorten
  the human's path — pre-filled scope, prior findings, a report template — not to remove
  the human.
- **"Generate income" means "make a human hunter faster," not "run unattended."** There is
  no version of this tool that ethically or reliably prints money on its own. Anything in
  the roadmap that starts to blur that line belongs in [SUGGESTIONS.md](SUGGESTIONS.md)
  under `REJECTED` until proven otherwise, not shipped by default.

If a future version adds automated scanning or automated submission, it must default to
**off**, require the user to confirm they hold current authorization for that specific
program and scope, and never fire against a target that isn't an active, in-scope bug
bounty program. This mirrors how [`sonar`](../sonar/README.md) keeps real-money execution
off by construction rather than by configuration.

## What v1 actually does

1. **Source adapters** (`bug_spray/sources/`) read each platform's *public, anonymous*
   program directory: name, scope (in/out of scope assets), reward table, open/paused,
   and last-updated timestamp. No account, token or login is involved anywhere.
2. **Store** (`bug_spray/store.py`) keeps the latest copy of every program in SQLite and
   writes a new snapshot only when something changed, so history is diffable without an
   hourly scan adding a thousand identical rows.
3. **Diffing** (`bug_spray/changes.py`) turns two snapshots into what a hunter cares
   about: **new** programs, **scope** additions/removals, **reward** changes per
   severity, **paused/resumed**, and programs that left (**gone**) or came back to
   their platform's public listing.
4. **Watchlist** (`bug_spray/watchlist.py`) narrows the feed by keyword, tag and minimum
   payout. It filters what is *reported*, never what is *stored*.
5. **CLI** (`main.py`) — `scan`, `list`, `show`, `feed`, `--selftest`.
6. **Sentinel feed** — Bug Spray's in-app Program radar shows the saved programs
   and recent changes. Opening that workspace starts a background directory scan
   if the last one is older than `poll_interval_minutes`; while Sentinel stays
   open, it checks again on that interval. **Scan now** runs it immediately.
   Scans do not run while Sentinel is closed. The feed never probes a target.
   The panel also covers the rest of the CLI: a platform filter, **Show all**
   (like `--all`), **Watchlist…** (edits `config.json`: platforms, keywords, tags,
   minimum payout), **Full details…** (like `show`), and **Full re-scan** (like
   `scan --full`).

v1 tracks **bounty-paying, publicly listed programs only**. VDPs (no payout),
invite-only, and login-walled programs are not fetched.

### Sources

| Platform | How it is read (all anonymous) | Programs (2026-09-25) | Notes |
|---|---|---|---|
| HackerOne | The site's GraphQL directory (`hackerone.com/graphql`), 100 programs per request, scope and bounty table inline | 291 | The documented Hacker API needs a token even for public programs, so it is not used. GraphQL is the website's own, not a versioned API. |
| Bugcrowd | `/engagements.json` → per program `changelog.json` → the latest brief `.json` | 287 | The brief is re-fetched only when its changelog entry changes. Rewards are Bugcrowd's P1–P5 ranges. |
| Intigriti | `api/core/public/programs` → per program detail | 112 | Registered-only, terms-required and 2FA-required programs are login-walled for detail: stored from the listing only, tagged `registered-only` / `terms-required` / `2fa-required`, with no scope. |
| YesWeHack | `api.yeswehack.com/programs` → per program detail | 60 | Detail re-fetched only when `last_update_at` changes. Out-of-scope is prose, so it is not stored as assets. |
| Immunefi | `immunefi.com/public-api/bounties.json` | 225 | One request for everything. Invite-only skipped; programs hiding their assets are tagged `assets-hidden`. |

Every request goes through one client (`sources/_http.py`) with a descriptive
User-Agent, ≥0.35 s between requests per platform, and bounded retries that honour
`Retry-After`. A baseline scan of all five takes about 4 minutes; an incremental one
about 2 (Bugcrowd's per-program changelog check is most of it).

**Failure handling.** One platform failing (network, rate limit, an API that changed
shape) is reported as an error for that platform and the others still run; `scan` then
exits 1. If a single program's detail request fails, the last stored copy is kept rather
than storing an empty scope (which would read as "every asset removed"). If a platform
suddenly lists fewer than half the programs it listed last time, nothing is marked gone
— that is far likelier to be an API change than a mass closure.

## Usage

```bash
cp config.example.json config.json   # all five platforms, no filters
python main.py --selftest            # config, DB and adapters wire up — no network
python main.py scan                  # first run stores a baseline; later runs print changes
python main.py scan --platform immunefi --json
python main.py list                  # stored programs matching the watchlist, highest payout first
python main.py list --all --limit 0  # everything stored
python main.py show bugcrowd webdotcom
python main.py feed --json         # saved programs, recent changes, last scan
```

`scan --full` re-fetches every program's detail even where the platform says nothing
changed; use it if a platform's update timestamp ever looks unreliable. `scan --all`
reports every change, ignoring the watchlist. Everything takes `--json`.

`show` ends with a reminder that is also the rule: a stored scope is a lead, not
authorization — re-read the live program page before testing anything.

### Watchlist filters (`config.json`)

| Key | Matches when | Example |
|---|---|---|
| `watchlist_keywords` | any keyword is a case-insensitive substring of the name, slug, a tag, or an in-scope asset | `["api", "graphql"]` |
| `watchlist_tags` | the program has any of these tags (see `show` / `list --json`) | `["wildcard", "smart_contract"]` |
| `min_reward_usd` | the top published payout, converted approximately to USD, is at least this | `5000` |

Each filter that is set must match; an empty one is not applied. A program with no
published amount, or in a currency without a rate in `models.APPROX_USD_RATE`, does not
pass a non-zero minimum.

## In-app integration (Sentinel)

`sentinel_chat_agent.py` is still a single LLM-only `BugBountyAgent` for report
drafting, with no network calls of its own. Sentinel's **Bug Spray** workspace
now also embeds `ui/panels/bug_spray_feed.py`, which reads this package's saved
programs and change events. A background child process runs this repo's scanner
through its own `.venv`; the GUI stays responsive and shows failures. The
database records each scan and recent changes so the feed survives restarts.
Only public program directories are fetched; no program assets are scanned.

`build_messages(target, program, scope_type, findings, nmap_output)` assembles a
system prompt instructing the model to analyse recon data the *operator* supplies
(HTTP responses, Burp output, nmap results, source snippets) for a target the operator
has stated is in an authorized, in-scope bug bounty program, and to produce two
sections: a structured **vulnerability report** (CWE, severity/CVSS, PoC, impact,
remediation, references) and a ready-to-paste **submission draft** for HackerOne or
Bugcrowd. It never generates exploits for out-of-scope targets and never claims
authorization on the operator's behalf — scope and authorization are asserted by
whoever is chatting with it, the same human-in-the-loop boundary as the rest of this
project (see "The honest boundary" above).

## Secrets and config

Same rule as [`unblock_tracker`](../unblock_tracker/README.md): no hardcoded identifiers,
no secrets in git. Any platform API token lives in the macOS Keychain via `keyring`, loaded
by `bug_spray/secrets.py`. Non-secret settings (which platforms to poll, poll interval,
watchlist filters) live in a git-ignored `config.json` next to `main.py`, loaded by
`bug_spray/config.py`. v1 needs no secret at all — every source is anonymous — so
`secrets.py` is there for a future token-backed source, not used by any adapter.

## Project layout

```
sentinel_chat_agent.py  Sentinel's in-app Bug Spray (bug_bounty) chat agent —
                        BugBountyAgent, LLM-only, no source adapters
main.py                 CLI entry point
bug_spray/
  __init__.py           __version__
  cli.py                scan / list / show / --selftest
  config.py             config.json loader — non-secret settings only
  secrets.py            macOS Keychain-backed token storage (unused by v1 sources)
  models.py             Program / Scope / RewardTier, reward merging, USD approximation
  store.py              SQLite snapshots (written on change) + programs seen/gone
  feed.py               read-only saved-program feed for Sentinel and CLI
  changes.py            snapshot diff: new, scope, rewards, paused/resumed, gone/back
  watchlist.py          keyword / tag / min-reward filters
  sources/
    __init__.py         registry, fetch_all (parallel, per-platform errors), fallback helper
    _http.py            the one polite HTTP client
    hackerone.py  bugcrowd.py  intigriti.py  yeswehack.py  immunefi.py
tests/
  fixtures/             trimmed real responses from each platform (2026-09-25)
  test_sources.py       adapters against the fixtures, offline
  test_scan.py          store, diffing, watchlist, CLI
  test_selftest.py
```

## Status

**v1 discovery complete (2026-09-25); Sentinel feed added 2026-09-26.** All five
adapters are live against the real platforms, with offline tests over trimmed
copies of their responses (`pytest`, 48 tests).
Everything it fetches is public program metadata; nothing here touches a program's
assets. v2 (triage board, report template, scope-confirmation gate) is next — see
[TODO.md](TODO.md).

## Environment

Own git repo (nested under `sentinel_fork/agents/`), `uv` venv, Python ≥3.11, PySide6 not
yet needed — this starts as a CLI tool and only grows a GUI (via `lab_hub`) if the CLI
workflow proves useful enough to want one. Follows the pseudonymous commit identity used
across this lab.

`_Admin/rebuild_envs.sh` only walks the top level of `active/`, so it never reaches this
nested repo. Rebuild the venv here directly, on the Mac:

```bash
uv venv .venv && uv pip install -r requirements.txt --python .venv/bin/python
```

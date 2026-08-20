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

1. **Source adapters** (`bug_spray/sources/`) pull program metadata from each platform's
   public API/directory: name, scope (in/out of scope assets), reward table, program
   status (active/paused), and last-updated timestamp.
2. **Store** (`bug_spray/store.py`) caches the latest snapshot per program in SQLite and
   keeps prior snapshots so changes are diffable.
3. **CLI** (`main.py`) runs a scan, prints/stores what changed since last run, and will
   grow a `--selftest` flag once the source adapters are real (see
   [conventions](../../CLAUDE.md) — every packaged app in this lab has one).

Planned sources, in rough order of how open their data is:

| Platform | Data available without auth | Notes |
|---|---|---|
| HackerOne | Public program directory + scope (JSON:API) | Largest catalogue |
| Bugcrowd | Public program briefs | Some programs are invite-only |
| Intigriti | Public program listing | EU-heavy |
| YesWeHack | Public program listing | |
| Immunefi | Public program listing + reward table | Crypto/web3 only |

## Secrets and config

Same rule as [`unblock_tracker`](../unblock_tracker/README.md): no hardcoded identifiers,
no secrets in git. Any platform API token lives in the macOS Keychain via `keyring`, loaded
by `bug_spray/config.py`. Non-secret settings (which platforms to poll, poll interval,
watchlist filters) live in a git-ignored `config.json` next to `main.py`.

## Project layout

```
bug_spray/
  bug_spray/
    __init__.py
    config.py       # keyring-backed secrets + config.json loader
    models.py        # Program / Scope / RewardTier dataclasses
    store.py          # SQLite snapshot cache + diffing
    sources/            # one module per platform, each exposing fetch_programs()
  main.py             # CLI entry point
  tests/
  docs/
  README.md            # this file
  SUGGESTIONS.md
  TODO.md
```

## Status

Scaffold only — no source adapter is implemented yet (see [TODO.md](TODO.md)). Nothing in
this project makes network calls, touches a real bug bounty program, or handles a real
credential until that changes.

## Environment

Own git repo (like every project under `active/`), `uv` venv, Python ≥3.11, PySide6 not
yet needed — this starts as a CLI tool and only grows a GUI (via `lab_hub`) if the CLI
workflow proves useful enough to want one. Follows the pseudonymous commit identity used
across this lab.

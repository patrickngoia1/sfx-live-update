# SFX - Live Update

A [Claude Code](https://claude.com/claude-code) skill that turns **Tactical Cycle** status into a
readable status table and publishes it into the right **Google Docs Live Update document**.

It reads the Tactical Cycle's own computed status from GitHub, deduplicates the initiatives,
writes a table an executive can actually read, and posts it to the top of a named tab — leaving
every earlier entry, and the rest of the document, untouched.

Read-only against GitHub. It writes to Google Docs, and only after you confirm.

---

## What it produces

One entry per run, at the top of the target tab:

```
Sep 14, 2026 | <Project Name>                                  ← Heading 2
Cycle: 2026-TC5 (31 Aug – 23 Oct 2026) · Source: Tactical Cycle
At a glance: 11 initiatives · 🟢 10 Green · ✅ 1 Done · 0 with a production date

  #  | Initiative      | Team      | Observations
  ───┼─────────────────┼───────────┼──────────────────────────────────────────
 172 | <initiative>    | <squad>   | 🟢 Green - UAT scheduled - UAT 18 Sep, PROD not communicated
     |                 |           | Prototype and validation complete. ⚠️ UAT is days away while…

Legend + portfolio notes
```

- **`#`** links straight to the GitHub issue.
- **Observations** carries health, stage and the UAT/production dates on its first line, then the
  narrative — so four columns hold what would otherwise need seven.
- Health is the Tactical Cycle's **computed** Health Status. The skill never recomputes it.

A whole-portfolio run is **grouped by project** — one section per project with its own heading,
health summary and table — because a single flat table of forty-odd rows tells you nothing about
which project a row belongs to.

## Why the dedup step exists

The spreadsheet import that seeded the first GitHub-native cycle created a **twin for most
initiatives**: an empty, closed copy alongside the real one. Reporting raw rows double-counts
badly — one squad reads as 31 initiatives when it has 14; a whole-portfolio run reads as 62 when
it has 43.

The skill groups by team and title, keeps the record that holds actual work, and drops twins and
records that comments explicitly retire. Retirement is stated in more than one direction and
sometimes under a *different title*, so title-grouping alone is not enough — see `SKILL.md` for
the full ruleset.

It also cross-checks itself: a project's count must come out the same whether you scope the run to
that project or to the whole portfolio.

## Install

```bash
git clone https://github.com/<you>/sfx-live-update.git \
  ~/.claude/skills/sfx-cadence-live-update
cd ~/.claude/skills/sfx-cadence-live-update
cp config/projects.example.json config/projects.json
```

Then fill in `config/projects.json` — your squads, your projects and their Program IDs, and the
Google Doc ID of each Live Update document. That file is gitignored: **document IDs and internal
project names never leave your machine.**

Invoke with `/sfx-cadence-live-update`, or just ask for the status of a project's initiatives.

## Prerequisites

| | |
|---|---|
| **`gh`** | authenticated (`gh auth status`), with read access to your Tactical Cycle repo |
| **Google credentials** | an `authorized_user` credentials file with the `documents` scope, at `GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` or `~/.config/gws/credentials.json` |
| **Python 3** | standard library only — no packages to install |

The Google credentials are the ones the `gws` CLI uses. If you already have `gws` working, you are
already set up; the CLI itself is not required at runtime.

## Scripts

```bash
# what tabs does this document have?
python3 scripts/publish_entry.py --doc <documentId> --list-tabs

# resolve the tab and report what would be written, without writing
python3 scripts/publish_entry.py --doc <documentId> --payload payload.json --dry-run

# publish
python3 scripts/publish_entry.py --doc <documentId> --payload payload.json
```

Re-running on the same day **replaces** that day's entry rather than duplicating it.

## Notes from building this

Two things cost real time and are worth knowing before you reach for them:

- **Don't route Docs writes through the `gws` CLI.** It aborts on batches larger than about three
  requests — reproducible with `gws docs documents batchUpdate --dry-run` — which forces one HTTP
  call per table cell, and that falls over part-way through a table of this size. `scripts/docsapi.py`
  talks to the REST API directly and writes a whole entry in four calls.
- **The Docs API cannot create a tab.** If the target tab is missing, the script stops and says so
  rather than writing into a different tab. Add it by hand in Google Docs.

## Licence

Not yet decided — add one before treating this as reusable by others.

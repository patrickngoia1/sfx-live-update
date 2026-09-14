---
name: sfx-cadence-live-update
description: >
  Report the latest status of Tactical Cycle initiatives led by the SFX squads and publish the
  result into the matching Google Docs Live Update document. Use when the user asks for the
  status of a project's initiatives, a Cadence/TC status report, or wants a Live Update document
  refreshed. Trigger phrases: "status of the initiatives", "update the live doc", "cadence live
  update", "status report for <project>", "atualizar o live update".
---

# Cadence Live Update

Turns the Tactical Cycle's computed status into a status table, and publishes it to the top of
the `AI Live Update` tab of the relevant Live Update document.

**Read-only against GitHub. Writes only to Google Docs, and only after the user confirms.**

## 1. Ask for the scope — one question, two kinds of answer

Read `config/projects.json` (copy `config/projects.example.json` if it does not exist yet) and ask
the user to pick **one**:

- a **single Program / Project** → writes to that project's own Live Update document
- **all led initiatives** → writes to the roll-up document only

There is no "by team" option. Show the initiative count per project (pre-deduplication) and flag
which entries have no document, so the choice is informed.

## 2. Pull the data (no clone, `gh` only)

Preconditions: `gh auth status` must pass. If not, point at the Cadence plugin's setup command.

`TC` below is the `repo` value from the config. The authoritative source is the committed daily
snapshot:

```
TC=$(jq -r .repo config/projects.json)
s=$(gh api repos/$TC/contents/snapshots --jq '[.[].name]|sort|last')
gh api repos/$TC/contents/snapshots/$s -H "Accept: application/vnd.github.raw"
```

Each record carries `ref`, `title`, `team`, `roadmap_id`, `health`, `pct`, `done`, `total`,
`tc_id`, `start_date`, `target_date`, `mismatch`, `carry_over`.

Select records whose `roadmap_id` is in the chosen project's `roadmap_ids` **and** whose `team`
is in `teams`. Everything in the snapshot is the current cycle, so no cycle filter is needed.

Then, per surviving initiative, walk the tree and read the commentary — this is where ETAs and
progress narrative live, and there is no other source for them:

```
gh api graphql -f query='query($o:String!,$r:String!,$n:Int!){repository(owner:$o,name:$r){
  issue(number:$n){ number title state
    comments(first:50){nodes{author{login} createdAt body}}
    subIssues(first:20){nodes{ title state repository{nameWithOwner}
      comments(first:30){nodes{author{login} createdAt body}}
      subIssues(first:100){nodes{ number title state stateReason updatedAt }}}}}}}' \
  -f o=<owner> -f r=<repo> -F n=<number>
```

## 3. Deduplicate — mandatory, never skip

The spreadsheet import that seeded the first GitHub-native cycle created a twin for most
initiatives. Reporting raw snapshot rows double-counts badly — one squad went from 31 rows to 14
real initiatives, and a whole-portfolio run from 62 to 43.

1. Group by team + normalized title.
2. Within a group keep the record that **holds actual work** (leaf tasks > 0); tie-break to the
   `OPEN` one, then the most recently created.
3. Drop records a comment identifies as a duplicate (e.g. *"This initiative is a duplicate of #173
   under a different name"*).
4. Empty twins look like: created during the import window, `CLOSED`, zero sub-issues, and often
   carry a comment *"Adopted as the sheet-managed initiative for TC5-xxx (import twin #NNN retired)"*.
5. Retirement is also stated the other way round, on the record being dropped, and under a
   **different title** so title-grouping alone will not catch it — *"Retired: the team's own
   initiative #170 was adopted as canonical for TC5-519"*. Drop any initiative whose comments
   retire it in favour of another, and keep the one it names.

Sanity check: a project's count must come out the same whether the run is scoped to that project
or to everything. If it does not, a dedup rule is misfiring.

## 4. Build the entry

**Title** — `<Mon D, YYYY> | <Project name>`, matching the tab's existing convention. Use the
project name as the document names it, not the Cadence ID.

**Rows ordered by issue number, ascending.** Four columns:

| # | Initiative | Team | Observations |
|---|---|---|---|

- **#** — the GitHub issue number, hyperlinked to `https://github.com/<repo>/issues/<n>`.
- **Observations** — two lines. First: `<Health> - <Status> - <dates>`. Then the narrative.
  - **Health** is Cadence's computed Health Status, never recomputed: 🟢 Green · 🟡 Yellow ·
    🔴 Red · ✅ Done · ⚪ Not started.
  - **Status** is a one-word stage read from the work: Definition, Refinement, Alignment,
    In development, In UAT, UAT scheduled, Awaiting dependency, Blocked, Not started.
  - **dates** are the UAT and production ETAs mined from comments and task titles. Where none
    exists, say so rather than inventing one.
  - The narrative says what is being worked on, what is blocking, and what deserves attention.

Also emit a `Cycle:` line, an `At a glance:` line, and a short footer: legend plus two or three
portfolio notes.

### Roll-up runs are grouped by project

A whole-portfolio run covers dozens of initiatives across every project, and one flat table loses all sense
of which project a row belongs to. So the roll-up is written as **one section per project** —
a `HEADING_3` title (`<Project> — N initiatives`), a one-line health summary (`10 🟢 Green ·
1 ✅ Done`), then that project's table.

Sections are ordered **largest first**, rows within a section still ascend by issue number. The
columns stay the same four, because the section heading already carries the project — so a given
row looks identical in its project's own document and in the roll-up.

Pass these as `sections` in the payload instead of a top-level `header`/`rows`.

**Audience is broad** — business, legal and technical readers. No internal jargon, no GitHub
vocabulary ("epic", "sub-issue"), no individual names.

**Stay quiet about routine data-quality noise.** Do flag, inline with ⚠️, the cases where the
board actively contradicts reality — an initiative auto-closed while its testing and deployment
work is still open, a Health of "Done" against a tree that is mostly open, a closed initiative
whose plan says work starts next month. Those mislead the reader; missing dates do not.

## 5. Publish

Show the table in the conversation and get an explicit yes before writing. Then:

```
python3 scripts/publish_entry.py --doc <documentId> --payload /tmp/payload.json
```

Payload shape is documented at the top of `publish_entry.py`. `--list-tabs` prints a document's
tabs; `--dry-run` resolves the tab and reports without writing.

The script is idempotent: re-running on the same day replaces that day's entry instead of
duplicating it. Prior entries are never touched, and tab 1 of the document is never touched.

**Some documents may not have the target tab** — the config records this as `tab_ok: false`, and
the script refuses rather than guessing. The Docs API cannot create a tab. Report it and ask the
user to add it by hand; never write into a different tab as a substitute.

## Auth notes

Writes go directly to the Google Docs REST API using the existing `authorized_user` credentials at
`GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` (default `~/.config/gws/credentials.json`). Never print
those values.

Do **not** route writes through the `gws` CLI: it aborts on batches larger than about three
requests, reproducible under `gws docs documents batchUpdate --dry-run`. Working around it needs
one HTTP call per table cell, which fails part-way through on tables of this size.

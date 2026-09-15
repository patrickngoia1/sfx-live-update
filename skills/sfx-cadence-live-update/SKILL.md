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

## 1. Ask for the scope FIRST — before running anything

**Do not fetch, query or compute before the user has chosen.** The list comes straight out of
`config/projects.json`, which needs no network call, so present it immediately and let the user act
while nothing is running. Counting initiatives per project needs the snapshot — that happens
*after* the choice, not before it.

Read the config from `~/.claude/sfx-live-update/projects.json` (override:
`SFX_LIVE_UPDATE_HOME`) and show every project as a numbered list, marking the ones with no
Live Update document. Then add the whole-portfolio option as the last number. Ask the user to reply
with a number, and stop.

If that file does not exist, this is a first run: generate it instead (see *First run* below), then
show the list.

There is no "by team" option.

Only once they have answered: fetch the snapshot and do the work.

## 2. Pull the data (no clone, `gh` only)

Preconditions: `gh auth status` must pass. If not, point at the Cadence plugin's setup command.

`TC` below is the `repo` value from the config. The authoritative source is the committed daily
snapshot:

```
TC=$(jq -r .repo ~/.claude/sfx-live-update/projects.json)
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

**Rows ordered by issue number, ascending.** Five columns:

| # | Initiative | Responsible | Team | Observations |
|---|---|---|---|---|

- **#** — the GitHub issue number, hyperlinked to `https://github.com/<repo>/issues/<n>`.
- **Initiative** — the **full** name, bold and black. Pass `"bold_columns": [1]` in the payload.
- **Responsible** — the person's **real name**, never a GitHub handle. See *Naming people* below.
- **Observations** — see *Laying out Observations* below. Never a paragraph.

### Naming people

Take the owner from the initiative's own assignee; fall back to the delivery item's assignee, then
to whoever holds most of the tasks. Translate the handle to a real name through
`~/.claude/sfx-live-update/people.json`.

That file is built by matching a handle's letters against the Google Workspace directory
(`gws people people searchDirectoryPeople`) and accepting a match **only when some rendering of
the person's real name equals the handle** — `adrianogarciagympass` → `adriano` + `garcia`. A
near-miss is never accepted: put the handle under `unknown` and ask a human. Naming the wrong
person as responsible in a document this widely read is worse than leaving it blank.

Where nobody is assigned, write "Not assigned" rather than inventing an owner.

### Laying out Observations

This column is the whole report for most readers. Give it room: short labelled blocks, bullets,
and **blank lines between blocks**. Taller rows are the intended trade — never compress it back
into a paragraph.

```
🟢 ON TRACK · being built

Testing (UAT): 18 September
Go live: not yet scheduled

What's happening
• The prototype is finished and signed off with the business.
• The unused fields still have to be taken off the sales screens.

Needs attention
• The testing date is days away while the change itself has not started.
```

- The first line is the status, in caps, with the plain-language stage after it.
- Both dates always appear, even when the answer is "not yet scheduled".
- `What's happening` is bullets, one fact each — not one long sentence split by commas.
- `Needs attention` appears only when there is something to say, and is also bullets.
- Blank lines between blocks are required; they are what makes the cell readable.

### Around the table

Emit a dateline (planning period, and that this was prepared from the teams' boards), a one-line
summary of the whole set, and a short closing section beneath the table.

**The closing notes must name the work they refer to.** "One piece of work is blocked" is useless;
"Global Affiliates (Phase 2/2) cannot begin end-to-end testing until another team creates the
Brazilian marketplace" tells the reader where to look. Every claim names the initiatives behind it
— if that makes a note long, split it into two, but never leave a count without the names.

Open the closing section with the legend, explaining each symbol in words ("🟢 on track",
"🚫 blocked by another team"). Then one note per theme: what finished, what is blocked, where the
dates stand, and anything that needs a decision — each naming its initiatives.

### Write for everyone, not for the team that built it

The audience is business, legal, finance and engineering at once. Most readers have never opened
the planning board and do not know the vocabulary.

- **Never use the internal names of things.** Not "Cadence", not "Tactical Cycle", not "TC5", not
  "epic", "sub-issue", "leaf task", "roadmap ID", "initiative health", "snapshot".
- **Say what a stage means**, don't name it: "being defined", "being agreed with other teams",
  "being built", "in testing", "waiting on another team", "blocked", "finished", "not started yet".
  Avoid "refinement", "discovery", "alignment", "in dev", "UAT scheduled" as bare labels.
- **Spell out an abbreviation the first time** it appears — "testing (UAT)", "go live (production)".
- **Explain consequences, not mechanics.** "Waiting on another team to create the Brazilian
  marketplace before testing can start" beats "blocked by a dependency on Tagus".
- **No names of individuals**, no handles, no ticket jargon.

Full project names, always — as the project is formally called, not a shortened form.

### Roll-up runs are grouped by project

A whole-portfolio run covers dozens of initiatives across every project, and one flat table loses all sense
of which project a row belongs to. So the roll-up is written as **one section per project** —
a `HEADING_3` title carrying the project's **full** name (`<Full Project Name> — N initiatives`), a one-line health summary (`10 🟢 Green ·
1 ✅ Done`), then that project's table.

Sections are ordered **largest first**, rows within a section still ascend by issue number. The
columns stay the same five, because the section heading already carries the project — so a given
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

**The script never overwrites anything.** Every run inserts a brand-new section at the top of the
tab; no existing content is deleted, edited or replaced, and the document's other tabs are never
touched. Running twice in a day produces two entries — the script says so, and a human deletes the
one they don't want. Never add a delete or replace step to get around that: an accidental rewrite
of a published entry is unrecoverable, a duplicate is a five-second fix.

**Some documents may not have the target tab.** The script checks at publish time and refuses
rather than guessing — deliberately not a config flag, because a tab can be added or renamed at any
moment and a stale flag would be worse than no flag. The Docs API cannot create a tab: report it
and ask the user to add it by hand, never write into a different tab as a substitute.

## First run — generating the configuration

Nothing is hand-written. Ask only for the **Focus Area** (e.g. `SFX`) and any squad to leave out,
then:

```
python3 scripts/setup.py --focus-area <FA> [--exclude "<FA> - Lead"] \
    [--rollup-doc <id>] [--rollup-name "<display name>"] --apply
```

It derives the squads from the Tactical Cycle repo's `config/focus-areas/<fa>.yml`, the projects
from the Program IDs those squads actually lead in the latest snapshot, their display names from
the repo's `programs.yml` and `projects.yml`, and the documents from a Drive search.

Without `--apply` it only proposes. **Always show the proposal before applying**, because document
matching is the one part that can be wrong:

- a match is auto-accepted only when every distinctive word of the project name appears in the
  document title *and* the title is not mostly about something else. That two-way test is what
  stops "Engineer Live update: Support BR Tax Reform Notes" being mistaken for the BR Tax Reform
  live update;
- anything weaker is listed with its candidates for a human to pick;
- a project with no match gets `doc: null` and becomes report-only.

Re-run it whenever squads or projects change; it is how a newly created project appears.

For the Responsible column, `~/.claude/sfx-live-update/people.json` is built the same way — resolve each assignee
handle against the Workspace directory, accept only exact matches, list the rest as `unknown`.

Configuration is written to `~/.claude/sfx-live-update/`, deliberately outside the plugin: a
plugin upgrade installs into a new versioned directory, so config kept beside the code would be
destroyed on every update.

## Auth notes

Writes go directly to the Google Docs REST API using the existing `authorized_user` credentials at
`GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE` (default `~/.config/gws/credentials.json`). Never print
those values.

Do **not** route writes through the `gws` CLI: it aborts on batches larger than about three
requests, reproducible under `gws docs documents batchUpdate --dry-run`. Working around it needs
one HTTP call per table cell, which fails part-way through on tables of this size.

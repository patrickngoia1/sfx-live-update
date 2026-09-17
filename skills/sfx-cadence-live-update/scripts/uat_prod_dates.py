#!/usr/bin/env python3
"""Resolve each initiative's UAT and production dates from its delivery cards.

    uat_prod_dates.py <owner>/<repo> 172 173 175 ...          # human-readable
    uat_prod_dates.py <owner>/<repo> --json 172 173 ...        # machine-readable

A date is only ever taken from the dedicated card's **Start date**. Nothing is
inferred from comments, task titles or the initiative's own window: a date that
nobody recorded on the card is not a commitment.

Two APIs expose a field called "Start date" and BOTH are in use:

  issueFieldValues  the issue's own field — what teams actually fill in, and
                    where the large majority of real dates live
  Projects v2       a board column of the same name — a handful of cards carry
                    the date only here

Reading just the board finds almost nothing and looks exactly like "the teams
have not filled anything in", which is a very expensive thing to get wrong.
"""
import json, re, subprocess, sys

UAT = re.compile(r"\buat\b|user acceptance|user testing", re.I)
PROD = re.compile(r"\bprod\b|production|go.?live", re.I)

# Kept small on purpose: GitHub rejects a query whose theoretical node count
# exceeds 500k, and this shape fans out three levels deep.
BATCH = 2

FRAG = """
  i%(n)d: issue(number: %(n)d) {
    number title
    subIssues(first: 10) { nodes {
      title
      subIssues(first: 40) { nodes {
        number title state repository { nameWithOwner }
        issueFieldValues(first: 10) { nodes {
          ... on IssueFieldDateValue { value field { ...N } }
        } }
        projectItems(first: 2) { nodes {
          project { number }
          fieldValues(first: 25) { nodes {
            ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } }
          } }
        } }
      } }
    } }
  }
"""

NFRAG = """
fragment N on IssueFields {
  ... on IssueFieldDate { name }
  ... on IssueFieldSingleSelect { name }
  ... on IssueFieldText { name }
  ... on IssueFieldNumber { name }
  ... on IssueFieldMultiSelect { name }
}
"""


def start_date(task):
    """(date, source) from the card's Start date, or (None, None)."""
    for f in task["issueFieldValues"]["nodes"]:
        name = (f.get("field") or {}).get("name") or ""
        if name.strip().lower() == "start date" and f.get("value"):
            return f["value"], "issue field"
    for item in task["projectItems"]["nodes"]:
        for f in item["fieldValues"]["nodes"]:
            name = (f.get("field") or {}).get("name") or ""
            if name.strip().lower() == "start date" and f.get("date"):
                return f["date"], "board %s" % item["project"]["number"]
    return None, None


def fetch(repo, numbers):
    owner, name = repo.split("/", 1)
    out = {}
    for i in range(0, len(numbers), BATCH):
        chunk = numbers[i:i + BATCH]
        query = ('query { repository(owner:"%s", name:"%s") {' % (owner, name)
                 + "".join(FRAG % {"n": n} for n in chunk) + "} }" + NFRAG)
        r = subprocess.run(["gh", "api", "graphql", "-f", "query=" + query],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("gh failed: " + (r.stderr or r.stdout)[:500])
        payload = json.loads(r.stdout)
        if "errors" in payload:
            sys.exit(json.dumps(payload["errors"])[:500])
        for v in payload["data"]["repository"].values():
            if v:
                out[str(v["number"])] = v
    return out


def resolve(initiative):
    """{'UAT': {...}, 'PROD': {...}} for one initiative, plus any conflicts."""
    cards = {"UAT": [], "PROD": []}
    for epic in initiative["subIssues"]["nodes"]:
        for task in epic["subIssues"]["nodes"]:
            kind = ("UAT" if UAT.search(task["title"])
                    else "PROD" if PROD.search(task["title"]) else None)
            if not kind:
                continue
            date, src = start_date(task)
            cards[kind].append({"number": task["number"], "title": task["title"],
                                "date": date, "source": src,
                                "repo": task["repository"]["nameWithOwner"]})

    result = {}
    for kind, found in cards.items():
        dated = [c for c in found if c["date"]]
        if not dated:
            # No card, or a card with an empty Start date — both mean the same
            # thing to a reader, and the distinction is worth keeping for triage.
            result[kind] = {"date": None,
                            "reason": "no card" if not found else "card exists, Start date empty",
                            "cards": found}
            continue
        distinct = sorted({c["date"] for c in dated})
        best = dated[0]
        result[kind] = {"date": best["date"], "source": best["source"],
                        "card": "%s#%s %s" % (best["repo"], best["number"], best["title"]),
                        "cards": found}
        if len(distinct) > 1:
            # Never silently pick a winner: disagreeing commitments are a finding.
            result[kind]["conflict"] = distinct
    return result


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv
    if len(args) < 2:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    repo, numbers = args[0], [int(a) for a in args[1:]]

    data = fetch(repo, numbers)
    out = {n: resolve(v) for n, v in data.items()}

    if as_json:
        print(json.dumps(out, indent=1))
        return

    for n in sorted(out, key=int):
        print("#%-6s %s" % (n, data[n]["title"][:62]))
        for kind in ("UAT", "PROD"):
            r = out[n][kind]
            if r["date"]:
                line = "%s  (%s)" % (r["date"], r["source"])
                if r.get("conflict"):
                    line += "   ⚠️ cards disagree: %s" % ", ".join(r["conflict"])
                print("     %-5s %s" % (kind, line))
            else:
                print("     %-5s no date defined — %s" % (kind, r["reason"]))


if __name__ == "__main__":
    main()

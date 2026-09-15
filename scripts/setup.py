#!/usr/bin/env python3
"""Generate config/projects.json from a Focus Area name — nothing hand-written.

    setup.py --focus-area SFX [--exclude "SFX - Lead"] [--apply]

Everything the old config held by hand is derivable:

  squads        from the Tactical Cycle repo's config/focus-areas/<fa>.yml
  projects      the Program IDs your squads actually lead, from the daily snapshot
  names         from the repo's config/programs.yml + config/projects.yml
  documents     from a Drive search, matched by name and shown for confirmation
  tabs          NOT stored — detected at publish time, because it is a live fact

Without --apply this only proposes; nothing is written.
"""
import argparse, json, os, re, subprocess, sys, unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docsapi

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(HERE, "config", "projects.json")
# Drive's `contains` matches word prefixes, not substrings: 'ive update' finds
# nothing. It is already case-insensitive, so 'Live update' covers both spellings.
DOC_QUERY = ("name contains 'Live update' and "
             "mimeType = 'application/vnd.google-apps.document' and trashed = false")

STOP = {"the", "and", "of", "for", "on", "in", "a", "to", "live", "update",
        "document", "project", "salesforce", "sfx", "-", "&"}


def gh(*args):
    r = subprocess.run(["gh"] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("gh failed: " + (r.stderr or r.stdout)[:400])
    return r.stdout


def raw(repo, path):
    return gh("api", "repos/%s/contents/%s" % (repo, path),
              "-H", "Accept: application/vnd.github.raw")


def tiny_yaml_names(text):
    """id/name pairs out of programs.yml / projects.yml without a yaml dependency."""
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"\s*-\s+id:\s*(.+?)\s*$", line)
        if m:
            cur = m.group(1).strip().strip("'\"")
            continue
        m = re.match(r"\s*name:\s*(.+?)\s*$", line)
        if m and cur:
            out[cur] = m.group(1).strip().strip("'\"")
            cur = None
    return out


def focus_area_teams(repo, fa):
    text = raw(repo, "config/focus-areas/%s.yml" % fa.lower())
    return [m.group(1).strip().strip("'\"")
            for m in re.finditer(r"^\s*-\s+name:\s*(.+?)\s*$", text, re.M)]


def humanise(rid):
    """SFX-SALESFORCE-SECURITY-REVIEW -> SFX - Salesforce Security Review."""
    words = [w for w in rid.split("-") if w]
    if words and words[0].isupper() and len(words[0]) <= 4:
        return "%s - %s" % (words[0], " ".join(w.capitalize() for w in words[1:]))
    return " ".join(w.capitalize() for w in words)


def norm(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return [w for w in re.split(r"[^a-z0-9]+", s) if w and w not in STOP]


def score(project, title):
    """(recall, precision) over distinctive words.

    Recall alone is not enough: "Engineer Live update: Support BR Tax Reform
    Notes" contains every word of "BR Tax Reform" and so scores a perfect recall
    while being an entirely different document. Precision — how much of the title
    the project actually accounts for — is what separates the two.
    """
    p, t = set(norm(project)), set(norm(title))
    if not p or not t:
        return 0.0, 0.0
    hit = len(p & t)
    return hit / len(p), hit / len(t)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--focus-area", required=True, help="e.g. SFX")
    ap.add_argument("--repo", help="your organisation's Tactical Cycle repository, "
                    "as <owner>/<name>; taken from an existing config if omitted")
    ap.add_argument("--exclude", action="append", default=[],
                    help="a squad to leave out; repeatable")
    ap.add_argument("--rollup-doc", help="document ID for the all-squads roll-up")
    ap.add_argument("--rollup-name", help="display name for the roll-up entry")
    ap.add_argument("--apply", action="store_true", help="write config/projects.json")
    a = ap.parse_args()

    if not a.repo:
        if os.path.exists(CONFIG):
            a.repo = json.load(open(CONFIG)).get("repo")
        if not a.repo:
            sys.exit("--repo is required on a first run: the <owner>/<name> of your "
                     "organisation's Tactical Cycle repository.")

    print("1. squads in %s" % a.focus_area)
    teams = focus_area_teams(a.repo, a.focus_area)
    kept = [t for t in teams if t not in a.exclude]
    for t in teams:
        print("   %s%s" % (t, "   (excluded)" if t in a.exclude else ""))

    print("\n2. projects your squads lead, from the latest daily snapshot")
    newest = gh("api", "repos/%s/contents/snapshots" % a.repo,
                "--jq", "[.[].name]|sort|last").strip()
    snap = json.loads(raw(a.repo, "snapshots/%s" % newest))
    led = {}
    for i in snap["initiatives"]:
        if i["team"] in kept:
            led.setdefault(i["roadmap_id"], 0)
            led[i["roadmap_id"]] += 1
    print("   snapshot %s — %d project(s)" % (snap["date"], len(led)))

    names = {}
    for f in ("config/programs.yml", "config/projects.yml"):
        names.update(tiny_yaml_names(raw(a.repo, f)))

    # Program IDs get truncated over time, so an older short ID and its full form
    # are the same project; fold them together.
    groups, unregistered = {}, []
    for rid in led:
        label = names.get(rid)
        if not label:
            near = [k for k in names if k.startswith(rid) or rid.startswith(k)]
            if near:
                label = names[near[0]]
            else:
                # Not in either registry — readable guess from the ID, flagged so
                # a human can correct the wording.
                label = humanise(rid)
                unregistered.append((rid, label))
        groups.setdefault(label, []).append(rid)

    print("\n3. matching Live Update documents in Drive")
    docs = docsapi.drive_search(DOC_QUERY)
    print("   %d candidate document(s)" % len(docs))

    projects, unmatched, weak = [], [], []
    for label in sorted(groups, key=lambda l: -sum(led[r] for r in groups[l])):
        ranked = []
        for d in docs:
            rec, prec = score(label, d["name"])
            ranked.append((rec * prec, rec, prec, d))
        ranked.sort(key=lambda x: -x[0])
        top = ranked[0] if ranked else (0, 0, 0, None)
        runner = ranked[1][0] if len(ranked) > 1 else 0.0
        n = sum(led[r] for r in groups[label])
        entry = {"name": label, "roadmap_ids": sorted(groups[label]), "doc": None}

        # Auto-accept only on a complete, unambiguous, well-proportioned match.
        # Publishing into the wrong document is the worst outcome here, so
        # anything short of that goes to a human.
        if top[1] == 1.0 and top[2] >= 0.6 and top[0] > runner:
            entry["doc"] = top[3]["id"]
            print("   OK   %-56s %s" % (label[:56], top[3]["name"][:46]))
        elif top[1] >= 0.6:
            weak.append((label, [(r, p, d["name"], d["id"]) for _, r, p, d in ranked[:3]]))
            print("   ??   %-56s needs confirming" % label[:56])
        else:
            unmatched.append(label)
            print("   --   %-56s no document found" % label[:56])
        entry["_initiatives"] = n
        projects.append(entry)

    cfg = {
        "_comment": ("Generated by scripts/setup.py from the Focus Area. Re-run it when squads "
                     "or projects change. 'doc' null means report-only. Tabs are not recorded "
                     "here — they are checked at publish time, because a tab can be added or "
                     "renamed at any moment."),
        "focus_area": a.focus_area,
        "repo": a.repo,
        "teams": kept,
        "excluded_teams": a.exclude,
        "tab_name": "AI Live Update",
        "rollup": {"name": a.rollup_name or ("%s — all led work" % a.focus_area),
                   "doc": a.rollup_doc},
        "projects": [{k: v for k, v in p.items() if k != "_initiatives"} for p in projects],
    }

    print("\n%d project(s): %d matched, %d need confirming, %d without a document"
          % (len(projects), sum(1 for p in projects if p["doc"]), len(weak), len(unmatched)))
    if weak:
        print("\nConfirm these before relying on them:")
        for label, cands in weak:
            print("   %s" % label)
            for rec, prec, nm, did in cands:
                print("       match %3.0f%% / focus %3.0f%%  %-46s %s"
                      % (rec * 100, prec * 100, nm[:46], did))
    if unregistered:
        print("\nNot listed in the repo's programme or project registry — the name below is a\n"
              "guess from the ID, so check the wording (and consider registering it):")
        for rid, label in unregistered:
            print("   %-46s -> %s" % (rid, label))
    if not a.rollup_doc:
        print("\nNo --rollup-doc given; the whole-portfolio run will have nowhere to publish.")

    if a.apply:
        with open(CONFIG, "w") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        print("\nwrote %s" % CONFIG)
    else:
        print("\n(dry run — pass --apply to write config/projects.json)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Publish one Cadence status entry to the top of a Live Update doc's tab.

Idempotent: an existing entry whose heading matches is deleted first, so a re-run
on the same day replaces rather than duplicates.

    publish_entry.py --doc <documentId> [--tab-name "AI Live Update"] --payload p.json
    publish_entry.py --doc <documentId> --list-tabs

Payload — a single table (project run):

    {
      "heading":  "Sep 14, 2026 | Project Name",
      "subtitle": ["Cycle: ...", "At a glance: ..."],
      "header":   ["#", "Initiative", "Team", "Observations"],
      "rows":     [["172", "...", "SFX - Opportunity", "line 1\\nline 2"], ...],
      "links":    {"172": "https://github.com/..."},
      "footer":   ["Legend: ...", "..."]
    }

…or one table per project (roll-up run), same heading/subtitle/links/footer:

    "sections": [
      {"title": "<Project> — 11 initiatives",
       "summary": "10 🟢 Green · 1 ✅ Done",
       "header": [...], "rows": [...]},
      ...
    ]

Everything is inserted at one fixed index, sections in reverse, so no index has to
be predicted across a table whose size the API decides.
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docsapi

DEFAULT_TAB = "AI Live Update"


def u16(s):
    """Length in UTF-16 code units — the unit the Docs API indexes by."""
    return len(s.encode("utf-16-le")) // 2


def ptext(el):
    return "".join(e.get("textRun", {}).get("content", "")
                   for e in el.get("paragraph", {}).get("elements", []))


def style_of(el):
    return el.get("paragraph", {}).get("paragraphStyle", {}).get("namedStyleType")


def cell_text(cell):
    return "".join(ptext(el) for el in cell["content"]).strip()


def resolve_tab(doc, name):
    tabs = docsapi.list_tabs(doc)
    for tab_id, title in tabs:
        if title.strip().lower() == name.strip().lower():
            return tab_id
    sys.exit(
        "No tab named %r in this document.\nAvailable tabs: %s\n"
        "The Docs API cannot create a tab — add it by hand in Google Docs, "
        "or re-run with --tab-name pointing at an existing tab."
        % (name, ", ".join(repr(t[1]) for t in tabs)))


def entry_tables(content):
    """Our tables: those above the previous entry's heading, in document order."""
    out = []
    for el in content[2:]:
        if style_of(el) == "HEADING_2":
            break
        if "table" in el:
            out.append(el)
    return out


def normalize(p):
    if "sections" in p:
        return p["sections"]
    return [{"title": None, "summary": None, "header": p["header"], "rows": p["rows"]}]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc", required=True)
    ap.add_argument("--tab-name", default=DEFAULT_TAB)
    ap.add_argument("--payload")
    ap.add_argument("--list-tabs", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolve the tab and report what would be written")
    a = ap.parse_args()

    doc = docsapi.get_doc(a.doc)

    if a.list_tabs:
        for tab_id, title in docsapi.list_tabs(doc):
            print("%-18s %s" % (tab_id, title))
        return

    if not a.payload:
        sys.exit("--payload is required unless --list-tabs is given")

    p = json.load(open(a.payload))
    heading = p["heading"]
    subtitle = p.get("subtitle", [])
    links = p.get("links", {})
    footer = p.get("footer", [])
    sections = normalize(p)

    for i, sec in enumerate(sections):
        ncols = len(sec["header"])
        for j, r in enumerate(sec["rows"]):
            if len(r) != ncols:
                sys.exit("section %d row %d has %d cells, expected %d"
                         % (i, j, len(r), ncols))

    tab = resolve_tab(doc, a.tab_name)
    content = docsapi.tab_content(doc, tab)
    total = sum(len(s["rows"]) for s in sections)

    if a.dry_run:
        print("tab %s (%s) — would write %d section(s), %d rows, under %r"
              % (tab, a.tab_name, len(sections), total, heading))
        for s in sections:
            print("   %-46s %d rows x %d cols"
                  % (s["title"] or "(single table)", len(s["rows"]), len(s["header"])))
        return

    # ---- 1. lay down the whole skeleton, above everything already there ------
    # APPEND-ONLY BY DESIGN. Nothing existing is ever deleted or overwritten. A
    # repeat run on the same day adds a second entry rather than replacing the
    # first — a duplicate someone can delete by hand beats an automated rewrite
    # quietly destroying a published entry.
    reqs = []
    if len(content) > 1 and ptext(content[1]).strip() == heading:
        print("NOTE: an entry titled %r is already at the top of this tab.\n"
              "      Adding the new one above it; nothing is overwritten.\n"
              "      Delete whichever you don't want by hand." % heading)

    block = heading + "\n" + "".join(s + "\n" for s in subtitle)
    h_end = 1 + u16(heading) + 1
    top = h_end + sum(u16(s) + 1 for s in subtitle)   # everything else goes here

    reqs += [
        {"insertText": {"location": {"index": 1, "tabId": tab}, "text": block}},
        {"updateParagraphStyle": {
            "range": {"startIndex": 1, "endIndex": h_end, "tabId": tab},
            "paragraphStyle": {"namedStyleType": "HEADING_2"},
            "fields": "namedStyleType"}},
    ]
    if subtitle:
        reqs.append({"updateParagraphStyle": {
            "range": {"startIndex": h_end, "endIndex": top, "tabId": tab},
            "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
            "fields": "namedStyleType"}})

    # Footer first, then sections last-to-first — every insert lands at `top`, so
    # each one pushes the previous down and the final order comes out right.
    if footer:
        text = "\n".join(footer) + "\n"
        reqs += [
            {"insertText": {"location": {"index": top, "tabId": tab}, "text": text}},
            {"updateParagraphStyle": {
                "range": {"startIndex": top, "endIndex": top + u16(text), "tabId": tab},
                "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                "fields": "namedStyleType"}},
        ]

    for sec in reversed(sections):
        lead = ""
        if sec.get("title"):
            lead += sec["title"] + "\n"
        if sec.get("summary"):
            lead += sec["summary"] + "\n"
        if not lead:
            lead = "\n"
        reqs.append({"insertText": {"location": {"index": top, "tabId": tab},
                                    "text": lead}})
        cursor = top
        if sec.get("title"):
            t_end = cursor + u16(sec["title"]) + 1
            reqs.append({"updateParagraphStyle": {
                "range": {"startIndex": cursor, "endIndex": t_end, "tabId": tab},
                "paragraphStyle": {"namedStyleType": "HEADING_3"},
                "fields": "namedStyleType"}})
            cursor = t_end
        if sec.get("summary"):
            s_end = cursor + u16(sec["summary"]) + 1
            reqs.append({"updateParagraphStyle": {
                "range": {"startIndex": cursor, "endIndex": s_end, "tabId": tab},
                "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                "fields": "namedStyleType"}})
        reqs.append({"insertTable": {
            "location": {"index": top + u16(lead) - 1, "tabId": tab},
            "rows": len(sec["rows"]) + 1, "columns": len(sec["header"])}})

    print("laying out %d section(s), %d rows" % (len(sections), total))
    docsapi.batch_update(a.doc, reqs)

    # ---- 2. fill every cell, descending, in one atomic batch -----------------
    content = docsapi.tab_content(docsapi.get_doc(a.doc), tab)
    tables = entry_tables(content)
    if len(tables) != len(sections):
        sys.exit("expected %d tables, found %d — aborting before writing cells"
                 % (len(sections), len(tables)))

    fills = []
    for sec, tbl in zip(sections, tables):
        grid = [sec["header"]] + sec["rows"]
        for r, row in enumerate(tbl["table"]["tableRows"]):
            for c, cell in enumerate(row["tableCells"]):
                want = grid[r][c]
                if want and cell_text(cell) != want.strip():
                    fills.append((cell["content"][0]["startIndex"], want))
    # Descending, so indices not yet written stay valid as earlier inserts land.
    fills.sort(key=lambda x: -x[0])

    print("writing %d cells" % len(fills))
    docsapi.batch_update(a.doc, [
        {"insertText": {"location": {"index": idx, "tabId": tab}, "text": txt}}
        for idx, txt in fills])

    # ---- 3. bold headers, hyperlink the issue numbers ------------------------
    # Its own pass: filling the cells shifted every index computed in step 2.
    content = docsapi.tab_content(docsapi.get_doc(a.doc), tab)
    tables = entry_tables(content)

    BLACK = {"color": {"rgbColor": {"red": 0.0, "green": 0.0, "blue": 0.0}}}
    bold_cols = p.get("bold_columns", [])

    styles, linked, bolded = [], 0, 0
    for sec, tbl in zip(sections, tables):
        trows = tbl["table"]["tableRows"]
        for i, cell in enumerate(trows[0]["tableCells"]):
            start = cell["content"][0]["startIndex"]
            styles.append({"updateTextStyle": {
                "range": {"startIndex": start,
                          "endIndex": start + u16(sec["header"][i]), "tabId": tab},
                "textStyle": {"bold": True}, "fields": "bold"}})
        for r, row in enumerate(trows[1:]):
            key = sec["rows"][r][0]
            url = links.get(key)
            if url:
                start = row["tableCells"][0]["content"][0]["startIndex"]
                styles.append({"updateTextStyle": {
                    "range": {"startIndex": start, "endIndex": start + u16(key), "tabId": tab},
                    "textStyle": {"link": {"url": url}}, "fields": "link"}})
                linked += 1
            # Bold + explicitly black: a cell can otherwise inherit a link's blue
            # from a neighbour, and the ask is for these to read as plain emphasis.
            for c in bold_cols:
                text = sec["rows"][r][c]
                if not text:
                    continue
                start = row["tableCells"][c]["content"][0]["startIndex"]
                styles.append({"updateTextStyle": {
                    "range": {"startIndex": start,
                              "endIndex": start + u16(text.split("\n")[0]), "tabId": tab},
                    "textStyle": {"bold": True, "foregroundColor": BLACK},
                    "fields": "bold,foregroundColor"}})
                bolded += 1

    print("styling %d header row(s), %d issue links, %d bold cells"
          % (len(sections), linked, bolded))
    docsapi.batch_update(a.doc, styles)
    print("done")


if __name__ == "__main__":
    main()

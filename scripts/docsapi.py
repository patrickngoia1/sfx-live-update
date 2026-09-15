#!/usr/bin/env python3
"""Thin Google Docs API client.

Talks to the REST API directly rather than through the `gws` CLI: the CLI aborts
on multi-request batches (reproducible under --dry-run at n=6), which forced one
HTTP call per table cell and fell over after ~60 calls. Going direct means the
whole entry is written in a single atomic batchUpdate.

Credentials are the existing authorized_user file that `gws` already uses. They
are read into memory and never logged.
"""
import json, os, time, urllib.request, urllib.parse

CREDS = os.environ.get("GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE") or \
    os.path.expanduser("~/.config/gws/credentials.json")
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://docs.googleapis.com/v1/documents"

_token = None


def access_token():
    global _token
    if _token:
        return _token
    c = json.load(open(CREDS))
    data = urllib.parse.urlencode({
        "client_id": c["client_id"],
        "client_secret": c["client_secret"],
        "refresh_token": c["refresh_token"],
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data)
    with urllib.request.urlopen(req) as r:
        _token = json.load(r)["access_token"]
    return _token


def _call(url, body=None, tries=5):
    """One API call, with backoff on rate limiting.

    A full Drive scan is a dozen-plus requests and Google throttles bursts with a
    403 userRateLimitExceeded, which is transient — retrying is correct, failing
    the whole run is not.
    """
    headers = {"Authorization": "Bearer " + access_token(),
               "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode()
            transient = e.code == 429 or (
                e.code == 403 and ("ateLimit" in detail or "uotaExceeded" in detail))
            if transient and attempt < tries - 1:
                time.sleep(2 ** attempt)
                continue
            raise SystemExit("Docs API %s: %s" % (e.code, detail[:1500]))


def get_doc(doc_id, with_tabs=True):
    q = "?includeTabsContent=true" if with_tabs else ""
    return _call("%s/%s%s" % (API, doc_id, q))


def batch_update(doc_id, requests):
    return _call("%s/%s:batchUpdate" % (API, doc_id), {"requests": requests})


def tab_content(doc, tab_id):
    for t in doc.get("tabs", []):
        if t["tabProperties"]["tabId"] == tab_id:
            return t["documentTab"]["body"]["content"]
    raise SystemExit("tab %s not found" % tab_id)


def list_tabs(doc):
    return [(t["tabProperties"]["tabId"], t["tabProperties"]["title"])
            for t in doc.get("tabs", [])]


# ---- Drive + directory, used by setup.py to discover configuration -----------

DRIVE = "https://www.googleapis.com/drive/v3/files"
PEOPLE = "https://people.googleapis.com/v1/people:searchDirectoryPeople"


def drive_search(q, page_size=100, limit=5000):
    """Drive files matching a query, paginated to exhaustion.

    The cap matters: truncating the candidate list silently loses the correct
    document and the caller cannot tell the difference between "no match" and
    "not fetched".
    """
    out, token = [], None
    while len(out) < limit:
        params = {"q": q, "pageSize": min(page_size, limit - len(out)),
                  "fields": "nextPageToken,files(id,name,modifiedTime)",
                  "corpora": "allDrives", "includeItemsFromAllDrives": "true",
                  "supportsAllDrives": "true"}
        if token:
            params["pageToken"] = token
        r = _call(DRIVE + "?" + urllib.parse.urlencode(params))
        out += r.get("files", [])
        token = r.get("nextPageToken")
        if not token:
            break
    return out


def directory_search(query):
    """Workspace directory profiles matching a free-text query."""
    params = {"query": query, "readMask": "names,emailAddresses",
              "sources": "DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE", "pageSize": 30}
    try:
        r = _call(PEOPLE + "?" + urllib.parse.urlencode(params))
    except SystemExit:
        return []
    out = []
    for p in r.get("people", []):
        name = (p.get("names") or [{}])[0].get("displayName")
        mails = [e["value"] for e in p.get("emailAddresses", [])]
        if name and mails:
            out.append((name, mails[0]))
    return out

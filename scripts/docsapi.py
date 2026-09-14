#!/usr/bin/env python3
"""Thin Google Docs API client.

Talks to the REST API directly rather than through the `gws` CLI: the CLI aborts
on multi-request batches (reproducible under --dry-run at n=6), which forced one
HTTP call per table cell and fell over after ~60 calls. Going direct means the
whole entry is written in a single atomic batchUpdate.

Credentials are the existing authorized_user file that `gws` already uses. They
are read into memory and never logged.
"""
import json, os, urllib.request, urllib.parse

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


def _call(url, body=None):
    headers = {"Authorization": "Bearer " + access_token(),
               "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit("Docs API %s: %s" % (e.code, e.read().decode()[:1500]))


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

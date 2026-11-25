#!/usr/bin/env python3
"""Read-only Gmail sync for the finance inbox.

Commands:
  auth                 one-time browser consent (gmail.readonly only)
  fetch [--days N]     save new messages + PDF/CSV attachment text to ~/.finance-sync/inbox/
  status               show counts

Nothing is ever sent, modified or deleted: the token only has gmail.readonly.
"""
import argparse, base64, json, os, re, sys, time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

HOME = Path(os.environ.get("FINANCE_SYNC_HOME", Path.home() / ".finance-sync"))
CRED = HOME / "credentials.json"   # downloaded from Google Cloud Console
TOKEN = HOME / "token.json"        # created by `auth`
STATE = HOME / "state.json"
INBOX = HOME / "inbox"
ATTACH = INBOX / "attachments"
CONFIG = HOME / "config.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_CONFIG = {
    # Dedicated finance inbox: take everything except promotions/social.
    "query": "-category:promotions -category:social",
    "max_body_chars": 20000,
    "max_attachment_chars": 60000,
    "attachment_types": [".pdf", ".csv", ".txt", ".ofx", ".qfx"],
}


def load_config():
    HOME.mkdir(parents=True, exist_ok=True)
    if not CONFIG.exists():
        CONFIG.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
    return {**DEFAULT_CONFIG, **json.loads(CONFIG.read_text())}


def get_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not TOKEN.exists():
        sys.exit("No token yet. Run: python gmail_sync.py auth")
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid:
        if creds.refresh_token:
            creds.refresh(Request())
            save_token(creds)
        else:
            sys.exit("Token invalid. Run: python gmail_sync.py auth")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def save_token(creds):
    TOKEN.write_text(creds.to_json())
    os.chmod(TOKEN, 0o600)


def cmd_auth(_args):
    from google_auth_oauthlib.flow import InstalledAppFlow

    HOME.mkdir(parents=True, exist_ok=True)
    os.chmod(HOME, 0o700)
    if not CRED.exists():
        sys.exit(f"Put the OAuth client file at {CRED} first (see SETUP.md).")
    flow = InstalledAppFlow.from_client_secrets_file(str(CRED), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    save_token(creds)
    profile = get_service().users().getProfile(userId="me").execute()
    print(f"Authorized read-only access for: {profile['emailAddress']}")
    print("Confirm this is your dedicated finance inbox. If not, delete token.json and rerun.")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in ("td", "th"):
            self.out.append(" | ")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(html):
    p = _Text()
    p.feed(html)
    text = "".join(p.out)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t]+", " ", text)).strip()


def b64(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def walk(part):
    yield part
    for sub in part.get("parts", []) or []:
        yield from walk(sub)


def pdf_text(path, limit):
    try:
        from pypdf import PdfReader
    except ImportError:
        return "[pypdf not installed: pip install pypdf]"
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            return "[PDF is password-protected: set pdf_passwords in config.json]"
        text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
        return text[:limit] if text.strip() else "[no text layer: scanned PDF]"
    except Exception as e:  # noqa: BLE001
        return f"[pdf read error: {e}]"


def safe_name(name):
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]


def process_message(svc, msg_id, cfg):
    m = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
    plain, html, attachments = [], [], []
    for part in walk(m["payload"]):
        mime, body = part.get("mimeType", ""), part.get("body", {})
        fname = part.get("filename") or ""
        if fname:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in cfg["attachment_types"]:
                continue
            data = body.get("data")
            if not data and body.get("attachmentId"):
                data = svc.users().messages().attachments().get(
                    userId="me", messageId=msg_id, id=body["attachmentId"]
                ).execute()["data"]
            if not data:
                continue
            ATTACH.mkdir(parents=True, exist_ok=True)
            path = ATTACH / f"{msg_id}_{safe_name(fname)}"
            path.write_bytes(b64(data))
            if ext == ".pdf":
                text = pdf_text(path, cfg["max_attachment_chars"])
            else:
                text = path.read_bytes().decode("utf-8", "replace")[: cfg["max_attachment_chars"]]
            attachments.append({"name": fname, "path": str(path), "text": text})
        elif mime == "text/plain" and body.get("data"):
            plain.append(b64(body["data"]).decode("utf-8", "replace"))
        elif mime == "text/html" and body.get("data"):
            html.append(html_to_text(b64(body["data"]).decode("utf-8", "replace")))
    text = "\n".join(plain) if plain else "\n".join(html)
    ts = int(m.get("internalDate", "0")) / 1000
    return {
        "id": msg_id,
        "threadId": m.get("threadId"),
        "date": datetime.fromtimestamp(ts, timezone.utc).isoformat(),
        "from": headers.get("from", ""),
        "to": headers.get("to", ""),
        "delivered_to": headers.get("delivered-to", ""),
        "subject": headers.get("subject", ""),
        "body": text[: cfg["max_body_chars"]],
        "attachments": attachments,
        "labels": m.get("labelIds", []),
    }


def cmd_fetch(args):
    cfg = load_config()
    svc = get_service()
    state = json.loads(STATE.read_text()) if STATE.exists() else {"seen": [], "last_run": 0}
    seen = set(state["seen"])
    q = cfg["query"]
    if args.days:
        q += f" newer_than:{args.days}d"
    elif state["last_run"]:
        # one-day overlap; dedupe by message id covers it
        q += f" after:{int(state['last_run']) - 86400}"
    else:
        q += " newer_than:90d"
    INBOX.mkdir(parents=True, exist_ok=True)
    new, token = 0, None
    while True:
        resp = svc.users().messages().list(
            userId="me", q=q, maxResults=200, pageToken=token
        ).execute()
        for item in resp.get("messages", []):
            if item["id"] in seen:
                continue
            doc = process_message(svc, item["id"], cfg)
            (INBOX / f"{item['id']}.json").write_text(json.dumps(doc, indent=2))
            seen.add(item["id"])
            new += 1
        token = resp.get("nextPageToken")
        if not token:
            break
    STATE.write_text(json.dumps({"seen": sorted(seen), "last_run": time.time()}))
    print(f"query: {q}\nnew messages saved: {new}\ninbox dir: {INBOX}")


def cmd_status(_args):
    n = len(list(INBOX.glob("*.json"))) if INBOX.exists() else 0
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    last = datetime.fromtimestamp(state["last_run"]).isoformat() if state.get("last_run") else "never"
    print(f"saved messages: {n}\nlast run: {last}\ntoken present: {TOKEN.exists()}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth").set_defaults(fn=cmd_auth)
    f = sub.add_parser("fetch")
    f.add_argument("--days", type=int, help="backfill window; default 90 first run, then incremental")
    f.set_defaults(fn=cmd_fetch)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()

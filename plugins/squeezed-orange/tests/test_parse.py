#!/usr/bin/env python3
"""Deterministic checks for the sync scripts. No network, no model calls, no real data.
Prints PASS/FAIL per check; exit code 1 if any fail."""
import json, os, re, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "parse_transactions.py"
BANK = {"name": "Example Bank", "sender_contains": "alerts.example-bank.com",
        "amount": r"purchase of \$([\d,]+\.\d{2})", "merchant": r"Merchant:\s*(.+?)\s*$",
        "date": r"Date:\s*(\d{1,2}/\d{1,2}/\d{4})", "date_format": "%m/%d/%Y",
        "card": r"card \.\.\.(\d{4})", "location_separator": " in "}


def mail(i, body, frm="Sam <sam@example.com>", to="inbox@example.com", date="2026-11-20T10:00:00-08:00", subject="Fwd"):
    return {"id": i, "from": frm, "to": to, "subject": subject, "date": date, "attachments": [], "body": body}


def alert(amount="42.10", merchant="NEIGHBORHOOD GROCERY in SPRINGFIELD, ST", date="11/20/2026", card="1234", sender="alerts@alerts.example-bank.com", to="<sam@example.com>"):
    return ("---------- Forwarded message ---------\nFrom: Bank <%s>\nTo: %s\n\nYou made a purchase of $%s with your credit card ...%s.\nMerchant: *%s*\nDate: %s\n"
            % (sender, to, amount, card, merchant, date))


def run(mails, banks=None, owners=None, rules=None, config=None, extras=None, twice=False):
    with tempfile.TemporaryDirectory() as d:
        h = Path(d)
        (h / "inbox").mkdir()
        for m in mails:
            (h / "inbox" / (m["id"] + ".json")).write_text(json.dumps(m))
        for name, val in (("banks.json", banks), ("owners.json", owners), ("rules.json", rules), ("config.json", config), ("extra_transactions.json", extras)):
            if val is not None:
                (h / name).write_text(json.dumps(val))
        env = dict(os.environ, FINANCE_SYNC_HOME=str(h))
        for _ in range(2 if twice else 1):
            r = subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True)
            assert r.returncode == 0, r.stderr
        return json.loads((h / "transactions.json").read_text()), json.loads((h / "unparsed.json").read_text())


def t_configured_alert_fields():
    tx, _ = run([mail("a", alert())], banks=[BANK])
    t = tx[0]
    assert (t["date"], t["amount"], t["merchant"], t["card"], t["bank"]) == ("2026-11-20", 42.10, "NEIGHBORHOOD GROCERY", "1234", "Example Bank"), t


def t_location_split():
    tx, _ = run([mail("a", alert())], banks=[BANK])
    assert tx[0]["location"] == "SPRINGFIELD, ST"


def t_thousands_comma():
    tx, _ = run([mail("a", alert(amount="1,234.56"))], banks=[BANK])
    assert tx[0]["amount"] == 1234.56


def t_wrong_sender_unparsed():
    tx, un = run([mail("a", alert(sender="x@other-bank.com"), frm="Other <o@other-bank.com>")], banks=[BANK])
    assert tx == [] and [u["id"] for u in un] == ["a"]


def t_no_banks_file_is_safe():
    tx, un = run([mail("a", alert())])
    assert tx == [] and len(un) == 1


def t_google_noise_skipped():
    _, un = run([mail("a", "security alert", frm="Google <no-reply@accounts.google.com>")])
    assert un == []


def t_shortcut_parses_with_timezone():
    body = "CARDALERT\nowner=Sam\nmerchant=Corner Coffee\namount=6.50\nbank=My Card"
    tx, _ = run([mail("a", body, date="2026-11-21T02:30:00+00:00")], config={"timezone": "America/New_York"})
    assert tx[0]["date"] == "2026-11-20" and tx[0]["amount"] == 6.5 and tx[0]["bank"] == "My Card" and tx[0]["owner"] == "Sam", tx[0]


def t_shortcut_missing_amount_rejected():
    tx, _ = run([mail("a", "CARDALERT\nmerchant=Corner Coffee")])
    assert tx == []


def t_owner_from_forwarded_to():
    tx, _ = run([mail("a", alert(to="<partner@example.com>"))], banks=[BANK], owners={"partner@example.com": "Partner"})
    assert tx[0]["owner"] == "Partner"


def t_owner_empty_when_unknown():
    tx, _ = run([mail("a", alert())], banks=[BANK], owners={})
    assert tx[0]["owner"] == ""


def t_default_category_and_uncategorized():
    tx, _ = run([mail("a", alert(merchant="NEIGHBORHOOD GROCERY in X")), mail("b", alert(merchant="QWERTY CORP in X"))], banks=[BANK])
    cats = {t["merchant"]: t["category"] for t in tx}
    assert cats["NEIGHBORHOOD GROCERY"] == "Grocery" and cats["QWERTY CORP"] == "Uncategorized", cats


def t_custom_rules_override():
    tx, _ = run([mail("a", alert(merchant="QWERTY CORP in X"))], banks=[BANK], rules={"Hobby": ["qwerty"]})
    assert tx[0]["category"] == "Hobby"


def t_duplicate_flag_within_3_days():
    tx, _ = run([mail("a", alert(date="11/20/2026")), mail("b", alert(date="11/22/2026"))], banks=[BANK])
    assert all("possible_double_charge" in t.get("flags", []) for t in tx)


def t_no_duplicate_flag_after_3_days():
    tx, _ = run([mail("a", alert(date="11/10/2026")), mail("b", alert(date="11/20/2026"))], banks=[BANK])
    assert not any(t.get("flags") for t in tx)


def t_idempotent():
    one, _ = run([mail("a", alert())], banks=[BANK])
    two, _ = run([mail("a", alert())], banks=[BANK], twice=True)
    assert one == two


def t_extras_merged_and_not_duplicated():
    extra = [{"message_id": "a", "date": "2026-11-20", "amount": 9.0, "merchant": "From Claude", "location": "", "card": "1", "bank": "X"}]
    tx, un = run([mail("a", alert())], banks=[BANK], extras=extra)
    assert len(tx) == 1 and tx[0]["merchant"] == "From Claude" and un == []


def t_refund_negative_kept():
    extra = [{"message_id": "r", "date": "2026-11-20", "amount": -12.5, "merchant": "Refund Shop", "location": "", "card": "1", "bank": "X"}]
    tx, _ = run([], extras=extra)
    assert tx[0]["amount"] == -12.5


def t_readonly_gmail_only():
    src = (ROOT / "scripts" / "gmail_sync.py").read_text()
    scopes = re.findall(r"https://www\.googleapis\.com/auth/[a-z.]+", src)
    assert scopes and set(scopes) == {"https://www.googleapis.com/auth/gmail.readonly"}, scopes
    for bad in (".send(", ".delete(", ".modify(", ".trash(", "batchDelete", "batchModify"):
        assert bad not in src, bad


def t_example_files_valid():
    banks = json.loads((ROOT / "scripts" / "banks.example.json").read_text())
    for b in banks:
        for k in ("amount", "merchant", "date", "card"):
            re.compile(b[k])
    h = json.loads((ROOT / "scripts" / "history.example.json").read_text())
    assert all(len(v) == len(h["months"]) for v in h["cats"].values()) and set(h["fixedCats"]) <= set(h["cats"])


def t_manifests_valid():
    for p in (ROOT / ".claude-plugin" / "plugin.json", ROOT.parent.parent / ".claude-plugin" / "marketplace.json"):
        d = json.loads(p.read_text())
        assert d.get("name") and d.get("description"), p
    assert json.loads((ROOT.parent.parent / ".claude-plugin" / "marketplace.json").read_text())["plugins"][0]["source"] == "./plugins/squeezed-orange"


ALLOWED_EMAIL = re.compile(r"(^hello@maryamreza\.com$|@example\.com|@example\.net|@example-bank\.com|@alerts\.example-bank\.com|@other-bank\.com|^you@gmail\.com|^partner@gmail\.com|^no-reply@accounts\.google\.com|^alerts@)")


def t_no_private_info_in_public_files():
    bad = []
    for p in ROOT.parent.parent.rglob("*"):
        if not p.is_file() or p.suffix in (".png", ".pyc") or "results" in p.parts or ".git" in p.parts:
            continue
        text = p.read_text(errors="ignore")
        for e in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text):
            if not ALLOWED_EMAIL.search(e):
                bad.append((p.name, e))
        if re.search(r"(?<!\d)\d{12,19}(?!\d)", re.sub(r"data:image/[^\"')]+", "", text)):
            bad.append((p.name, "long digit run"))
    deny = Path.home() / ".finance-sync" / "privacy_denylist.txt"  # your own terms, kept out of the repo
    if deny.exists():
        terms = [t.strip().lower() for t in deny.read_text().splitlines() if t.strip()]
        for p in ROOT.parent.parent.rglob("*"):
            if p.is_file() and p.suffix not in (".png", ".pyc") and "results" not in p.parts:
                low = re.sub(r"data:image/[^\"')]+", "", p.read_text(errors="ignore")).lower()
                bad += [(p.name, t) for t in terms if re.search(r'(?<![a-z0-9])' + re.escape(t) + r'(?![a-z0-9])', low)]
    assert not bad, bad[:5]


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("t_")):
        try:
            fn()
            print("PASS", name)
        except Exception as e:
            fails += 1
            print("FAIL", name, "-", str(e)[:200])
    sys.exit(1 if fails else 0)

#!/usr/bin/env python3
"""Parse saved finance emails into transactions (deterministic, no LLM).

Reads  ~/.finance-sync/inbox/*.json   (written by gmail_sync.py)
Writes ~/.finance-sync/transactions.json   all parsed transactions, categorized, flagged
       ~/.finance-sync/unparsed.json       financial-looking mail no parser matched (for an LLM pass)
Idempotent: rebuilt from the inbox on every run.
"""
import json, os, re, sys
from datetime import datetime
from pathlib import Path

HOME = Path(os.environ.get("FINANCE_SYNC_HOME", Path.home() / ".finance-sync"))
INBOX, OUT, UNPARSED, RULES = HOME / "inbox", HOME / "transactions.json", HOME / "unparsed.json", HOME / "rules.json"
EXTRA = HOME / "extra_transactions.json"
OWNERS = HOME / "owners.json"  # inbox address -> person; edit to add more
DEFAULT_OWNERS = {}  # e.g. {"you@gmail.com": "You", "partner@gmail.com": "Partner"}

# Generic keywords only. Your own rules live in ~/.finance-sync/rules.json (or the dashboard's rules card).
DEFAULT_RULES = {
    "Grocery": ["grocery", "supermarket", "market", "foods"],
    "Restaurant": ["restaurant", "cafe", "coffee", "pizza", "sushi", "grill", "kitchen", "bistro", "diner", "bakery", "bar "],
    "Gas": ["gas station", "fuel", "gasoline"],
    "Travel": ["airline", "airfare", "hotel", "resort", "lodging", "car rental"],
    "Home/furniture": ["furniture", "hardware", "home improvement"],
    "Health/Doctor": ["pharmacy", "clinic", "medical", "dental", "hospital"],
    "Phone & internet bill": ["wireless", "internet", "telecom"],
    "Transportation": ["parking", "transit", "taxi", "rideshare", "toll"],
    "Education": ["tuition", "school", "university", "course"],
    "Giving": ["donation", "charity"],
}


def load_rules():
    if not RULES.exists():
        RULES.write_text(json.dumps(DEFAULT_RULES, indent=2))
    return json.loads(RULES.read_text())


def categorize(merchant, rules):
    m = merchant.lower() + " "
    for cat, words in rules.items():
        if any(w in m for w in words):
            return cat
    return "Uncategorized"


def original_sender(doc):
    """Sender of the original mail when the message was forwarded."""
    m = re.search(r"Forwarded message.*?From:[^\n<]*<([^>\n]+)>", doc["body"], re.S)
    return (m.group(1) if m else re.sub(r".*<|>.*", "", doc["from"])).lower()


BANKS = HOME / "banks.json"  # formats of YOUR alert emails; see banks.example.json
CONFIG = HOME / "config.json"


def load_banks():
    return json.loads(BANKS.read_text()) if BANKS.exists() else []


def parse_configured(doc, banks):
    """Parse a purchase alert using a format you describe in banks.json (sender text plus regexes)."""
    sender = original_sender(doc)
    t = doc["body"].replace("\xa0", " ")
    for b in banks:
        if b["sender_contains"].lower() not in sender:
            continue

        def grab(key):
            m = re.search(b[key], t, re.M) if b.get(key) else None
            return m.group(1).strip() if m else ""
        amt, mer, date, card = grab("amount"), grab("merchant"), grab("date"), grab("card")
        if not (amt and mer and date):
            continue
        try:
            day = datetime.strptime(date, b.get("date_format", "%m/%d/%Y")).date().isoformat()
        except ValueError:
            continue
        merchant, _, place = mer.strip(" |*").partition(b.get("location_separator", " in "))
        return {"date": day, "amount": float(amt.replace(",", "").replace("$", "")),
                "merchant": merchant.strip(), "location": place.strip(), "card": card,
                "bank": b["name"], "source": "alert"}
    return None


def parse_shortcut(doc):
    """Optional phone-automation emails. Body lines:  CARDALERT / owner=Name / merchant=... / amount=12.34"""
    t = doc["body"]
    if "CARDALERT" not in t:
        return None
    mer = re.search(r"merchant=(.+)", t)
    amt = re.search(r"amount=\s*\$?\s*([\d,]+(?:\.\d+)?)", t)
    if not (mer and amt):
        return None
    tz = None
    if CONFIG.exists():
        tz = json.loads(CONFIG.read_text()).get("timezone")
    when = datetime.fromisoformat(doc["date"])
    if tz:
        from zoneinfo import ZoneInfo
        when = when.astimezone(ZoneInfo(tz))
    else:
        when = when.astimezone()
    bank = re.search(r"bank=(.+)", t)
    return {"date": when.date().isoformat(), "amount": float(amt.group(1).replace(",", "")), "merchant": mer.group(1).strip(),
            "location": "", "card": "", "bank": bank.group(1).strip() if bank else "Card", "source": "shortcut"}


def load_owners():
    if not OWNERS.exists():
        OWNERS.write_text(json.dumps(DEFAULT_OWNERS, indent=2))
    return {k.lower(): v for k, v in json.loads(OWNERS.read_text()).items()}


def owner_of(doc, owners):
    """Who owns the card: explicit owner= line, else the original recipient, else the forwarder."""
    body = doc["body"]
    m = re.search(r"owner=([A-Za-z]+)", body)
    if m:
        return m.group(1).title()
    h = re.search(r"Forwarded message.*?\nTo:[^\n<]*<?([\w.+-]+@[\w.-]+)", body, re.S)
    cands = [h.group(1).lower()] if h else []
    cands += [re.sub(r".*<|>.*", "", doc["from"]).lower(), re.sub(r".*<|>.*", "", doc["to"]).lower()]
    return next((owners[c] for c in cands if c in owners), "")


PARSERS = [parse_shortcut]
NOISE = ("google.com", "accounts.google.com")


def flag_duplicates(txns):
    """Same card + merchant + amount within 3 days from different messages."""
    for i, a in enumerate(txns):
        for b in txns[i + 1:]:
            if (a["card"], a["merchant"].lower(), a["amount"]) == (b["card"], b["merchant"].lower(), b["amount"]) \
                    and a["message_id"] != b["message_id"] \
                    and abs((datetime.fromisoformat(a["date"]) - datetime.fromisoformat(b["date"])).days) <= 3:
                for t in (a, b):
                    t.setdefault("flags", [])
                    if "possible_double_charge" not in t["flags"]:
                        t["flags"].append("possible_double_charge")


def match_refunds(txns):
    """Link each credit (negative amount) to the purchase it refunds: same merchant, within 120 days,
    preferring an equal amount. Sets refundFor on the credit; partial refunds are flagged."""
    key = lambda t: t["merchant"].lower()[:12]
    for r in txns:
        if r["amount"] >= 0 or r.get("refundFor"):
            continue
        cands = [t for t in txns if t["amount"] > 0 and key(t) == key(r) and t["date"] <= r["date"]
                 and (datetime.fromisoformat(r["date"]) - datetime.fromisoformat(t["date"])).days <= 120
                 and not t.get("refundedBy")]
        pick = next((t for t in cands if abs(t["amount"] + r["amount"]) < 0.01), None) or (sorted(cands, key=lambda t: t["date"])[-1] if cands else None)
        if pick:
            r["refundFor"] = pick["message_id"]
            pick["refundedBy"] = r["message_id"]
            if -r["amount"] < pick["amount"] - 0.01:
                r.setdefault("flags", []).append("partial_refund")


def main():
    rules = load_rules()
    global BANKS_LOADED
    BANKS_LOADED = load_banks()
    owners = load_owners()
    txns, unparsed = [], []
    # Transactions extracted by Claude from mail no regex parser handles (written by the 3-day task).
    extras = json.loads(EXTRA.read_text()) if EXTRA.exists() else []
    extra_ids = {e["message_id"] for e in extras}
    for e in extras:
        e.setdefault("category", categorize(e.get("merchant", ""), rules))
        e.setdefault("source", "llm")
        txns.append(e)
    for p in sorted(INBOX.glob("*.json")):
        doc = json.loads(p.read_text())
        if doc["id"] in extra_ids:
            continue
        parsed = parse_configured(doc, BANKS_LOADED) or next((r for r in (f(doc) for f in PARSERS) if r), None)
        if parsed:
            parsed.update(message_id=doc["id"], category=categorize(parsed["merchant"], rules),
                          owner=owner_of(doc, owners))
            txns.append(parsed)
        elif not any(n in doc["from"].lower() for n in NOISE):
            unparsed.append({"id": doc["id"], "from": doc["from"], "subject": doc["subject"],
                             "has_attachment": bool(doc["attachments"])})
    flag_duplicates(txns)
    match_refunds(txns)
    txns.sort(key=lambda t: t["date"])
    OUT.write_text(json.dumps(txns, indent=2))
    UNPARSED.write_text(json.dumps(unparsed, indent=2))
    print(f"parsed: {len(txns)}  unparsed: {len(unparsed)}  uncategorized: "
          f"{sum(t['category'] == 'Uncategorized' for t in txns)}")
    for t in txns[-5:]:
        print(f"  {t['date']}  ${t['amount']:.2f}  {t['merchant']}  [{t['category']}]  card ...{t['card']}")


if __name__ == "__main__":
    sys.exit(main())

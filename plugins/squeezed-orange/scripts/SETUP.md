# Finance inbox sync: one-time setup

Reads `your dedicated finance inbox` with a **read-only** Gmail token. Cannot send, edit or delete mail.
You do the Google steps yourself; never paste the client secret or token into chat.

## 1. Google Cloud (about 10 min, signed in as the finance inbox)
1. console.cloud.google.com → new project `finance-sync`.
2. APIs & Services → Library → enable **Gmail API**.
3. APIs & Services → OAuth consent screen:
   - User type **External**, app name `finance-sync`, support/developer email = the finance inbox.
   - Scopes: add only `.../auth/gmail.readonly`.
   - Test users: add `your dedicated finance inbox`.
4. **Publishing status → "In production".** Required: in "Testing" mode Google expires refresh tokens after 7 days and the daily job would break. The app stays unverified (a warning screen appears at consent); that is fine for your own account. Click Advanced → Go to finance-sync.
5. APIs & Services → Credentials → Create credentials → OAuth client ID → **Desktop app**. Download the JSON.

## 2. Install and authorize (Terminal)
```bash
mkdir -p ~/.finance-sync && chmod 700 ~/.finance-sync
mv ~/Downloads/client_secret_*.json ~/.finance-sync/credentials.json
python3 -m venv ~/.finance-sync/.venv
~/.finance-sync/.venv/bin/pip install -r <plugin folder>/scripts/requirements.txt
~/.finance-sync/.venv/bin/python <plugin folder>/scripts/gmail_sync.py auth
```
The browser opens; sign in as the finance inbox and approve. The script prints the authorized address; confirm it is the finance inbox.

## 3. First fetch
```bash
~/.finance-sync/.venv/bin/python <plugin folder>/scripts/gmail_sync.py fetch --days 365    # backfill
~/.finance-sync/.venv/bin/python <plugin folder>/scripts/gmail_sync.py status
```
Messages land in `~/.finance-sync/inbox/*.json` (PDF/CSV attachment text included).

## Security notes
- `token.json` is a long-lived credential for that inbox: chmod 600, never commit or share it.
- Revoke any time: myaccount.google.com/permissions → finance-sync → Remove access.
- Tune what is fetched in `~/.finance-sync/config.json` (`query` uses Gmail search syntax).
- Password-protected statement PDFs are skipped and flagged; turn off bank PDF passwords or tell me which banks.

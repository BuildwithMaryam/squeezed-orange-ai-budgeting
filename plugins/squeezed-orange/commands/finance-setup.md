---
description: Guided setup for Squeezed Orange (finance inbox, read-only Gmail, dashboard, schedule). Safe to re-run; it skips what is already done.
---

You are guiding a non-technical user through setup. First run the checks in the `/finance-status` command (read `${CLAUDE_PLUGIN_ROOT}/commands/finance-status.md`) and **skip every step already done**; start at the first step that is not.

Open by telling the user plainly: this is a one-time manual setup, about 30 minutes for 5 accounts. It exists because Squeezed Orange never logs in to a bank: it only reads alert emails you forward to a dedicated inbox. They can stop and resume any time by running `/finance-setup` again, and `/finance-status` shows where they are. Before step 1, tell the user to read the Disclaimer section of the README (not financial, tax or legal advice; provided as is; they are responsible for their credentials and decisions) and ask them to confirm they understand. Contact: hello@maryamreza.com.

Go **one step at a time** and wait for the user to finish each before the next. Never ask them to paste a client secret, token or password into chat; they place files themselves. If the user pastes a client secret, token, password or credentials file into chat, do not save it, and do not repeat or quote any of its values in your reply. Tell them it is now in this chat's history, to rotate or delete it if it was real, and to place the downloaded file themselves in ~/.finance-sync/credentials.json.

1. **Finance inbox.** They need a dedicated Gmail address that receives bank and card alerts. The plugin reads it with a read-only token.
2. **Google access.** Walk through `${CLAUDE_PLUGIN_ROOT}/scripts/SETUP.md` (Google Cloud project, Gmail API, OAuth Desktop client). The downloaded file goes to `~/.finance-sync/credentials.json`.
3. **Install and authorize.** Run:
   `python3 -m venv ~/.finance-sync/.venv && ~/.finance-sync/.venv/bin/pip install -r ${CLAUDE_PLUGIN_ROOT}/scripts/requirements.txt`
   then `~/.finance-sync/.venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/gmail_sync.py auth` (the user approves read-only access in the browser).
4. **People.** Ask who the card owners are and which address each forwards from; write `~/.finance-sync/owners.json` as `{"address": "Name"}`. A single user can skip this.
5. **Alert formats.** For each bank or card, ask the user to paste one example purchase alert with card digits and private details removed. Write an entry in `~/.finance-sync/banks.json` (format in `${CLAUDE_PLUGIN_ROOT}/scripts/banks.example.json`), then test with `~/.finance-sync/.venv/bin/python ${CLAUDE_PLUGIN_ROOT}/scripts/parse_transactions.py`. Alerts with no entry are still read by the sync skill, just less precisely.
6. **Create the dashboard.** Ask what to name it (default "Squeezed Orange"). Create the artifact from `${CLAUDE_PLUGIN_ROOT}/dashboard/template.html` with capabilities db, user and sample. Save its URL to `~/.finance-sync/dashboard.url`. Using ArtifactData (load it with ToolSearch "select:ArtifactData"), write `data/users/me/settings` with `{"name": "<their name>"}`.
7. **History (optional).** If they have 12 months of category totals (a spreadsheet or statements), build `data/users/me/history` in the format of `${CLAUDE_PLUGIN_ROOT}/scripts/history.example.json`, including `fixedCats` for fixed monthly costs. If not, tell them to press "Start without history" on the dashboard; it builds up from alerts.
8. **Income and fixed costs.** Tell them to add income, fixed costs and one account balance on the dashboard's Budget & income tab (the Getting started card lists these).
9. **Balances and backfill.** Suggest turning on balance alerts at their bank and forwarding them; and a CSV import from each bank site (Spending tab) to load past months.
10. **First sync and schedule.** Run the `finance-sync` skill once. Then create the recurring task: cron `0 */6 * * *` running the finance-sync skill (every 6 hours; the Claude desktop app must be open).

11. **Delivery check (manual).** Tell the user to use each of their cards and accounts for their next purchases and watch the finance inbox to confirm an alert arrives for each one. This depends on their bank and cannot be tested automatically. If an account has no alerts for a month, they should check its alert and forwarding settings.

Finish by telling the user where to come back: the dashboard URL (also in `~/.finance-sync/dashboard.url`), its Getting started card, `/finance-status` for what is set up and what to do next, and "Sync my finances now" to sync sooner.

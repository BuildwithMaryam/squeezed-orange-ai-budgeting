---
description: Show what is set up for Squeezed Orange, what is missing, and the single next step.
---

Check each item below with read-only commands and report it as done or to do. Never print contents of `credentials.json` or `token.json`, and never print full card or account numbers.

1. `~/.finance-sync/credentials.json` exists.
2. `~/.finance-sync/token.json` exists (read-only Gmail authorized).
3. `~/.finance-sync/.venv/bin/python` exists.
4. `~/.finance-sync/banks.json`: how many bank formats are configured (names only).
5. `~/.finance-sync/owners.json`: how many people (names only).
6. `~/.finance-sync/dashboard.url` exists; print the URL.
7. Last fetch time from `~/.finance-sync/state.json`, number of files in `~/.finance-sync/inbox/`, and the number of entries in `~/.finance-sync/unparsed.json`.
8. A recurring finance-sync task exists (list scheduled tasks).

Then print:
- A short checklist (done / to do).
- **Next step:** the first item that is to do, with the one command or action for it (usually "run /finance-setup").
- If everything is done: the dashboard URL, "its Getting started card shows any remaining items (income, fixed costs, a balance)", and "say 'Sync my finances now' to update sooner".
- If unparsed count is above 0: say these emails are read by the sync skill, and that adding their sender to `banks.json` makes parsing exact.

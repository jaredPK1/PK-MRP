# Turning on outside research (catalog prices, EOL watch)

Sourcing ideas and the EOL watch work from MAX alone. Three outside sources
make them better; each switches on by itself once its keys are in the env
file, and only on the host where `RESEARCH_ENABLED=1` (production, .80 --
outside calls cost quota and money, so the .70 test copy stays off).

All of these go in `pk-server-manager/env/pk-mrp.env` on the host, then
`docker compose up -d pk-mrp`. Never in the repo.

```
RESEARCH_ENABLED=1
DIGIKEY_CLIENT_ID=...
DIGIKEY_CLIENT_SECRET=...
MOUSER_API_KEY=...
NEXAR_CLIENT_ID=...
NEXAR_CLIENT_SECRET=...
ANTHROPIC_API_KEY=...
GRAPH_TENANT_ID=...
GRAPH_CLIENT_ID=...
GRAPH_CLIENT_SECRET=...
PURCHASING_MAILBOX=PKPurchasing@pkinetics.com
```

## 1. Distributor APIs (Jared registers; free)

| Service | Sign up | What to create | Free quota |
|---|---|---|---|
| DigiKey | developer.digikey.com | An organization + a **Production** app with *Product Information V4*; copy Client ID / Secret | ~1,000 calls/day |
| Mouser | mouser.com → My Account → APIs | A **Search API** key | ~1,000 calls/day, 30/min |
| Nexar (Octopart) | portal.nexar.com | An app with the **Supply** scope; copy Client ID / Secret | 1,000 parts/month (PK-MRP uses 200/week) |

Any one is enough to start; DigiKey + Mouser cover most electronics. They
are looked up by the manufacturer part number in MAX (`Mfg_Part_Master`, or
the MPN / vendor SKU on Part_Vendor) -- parts with no MPN in MAX can't be
checked, so adding MPNs in MAX widens coverage.

## 2. Claude API key

Reads PCN / EOL emails and runs the weekly maker news search. Create a key
in the Anthropic Console (or reuse the org key other PK apps use) and set
`ANTHROPIC_API_KEY`. Model: `claude-opus-5-5` (override with
`RESEARCH_MODEL`). Server-side refusal fallback is on. Rough cost: a few
cents per notice email; ~10 web searches a week.

Jared's decision (2026-10-30): email text goes to Claude as-is.

## 3. The shared purchasing mailbox (IT)

PK-MRP reads the mailbox with Microsoft Graph as an application (no user
signs in). Request to IT:

> Please create an Entra app registration "PK-MRP mail reader" (or add to an
> existing one) with the **Microsoft Graph application permission
> `Mail.Read`**, admin-consented, and a client secret. Then restrict it to
> the shared purchasing mailbox PKPurchasing@pkinetics.com only, so it cannot read any other mailbox --
> either an Exchange **Application Access Policy**
> (`New-ApplicationAccessPolicy -AppId <client id> -PolicyScopeGroupId
> PKPurchasing@pkinetics.com -AccessRight
> RestrictAccess`) or **RBAC for Applications** with a management scope on
> that mailbox. Send back the tenant ID, client ID, secret and the mailbox
> address (PKPurchasing@pkinetics.com).

pk-people already has a Graph app registration; it should not be reused for
this (different permission, different blast radius).

What it does with the mail: every hour it reads mail received since the last
check (90 days back the first time), keeps only messages that look like a
supplier notice (PCN, EOL, last-time buy, discontinued, NRND...), and asks
Claude what the notice says. Only those notices are stored, in the app's
data volume (`eol_notices.json`): sender, subject, date, Outlook link and
the extracted notice -- not the mail body. Attachments (PDF PCNs) aren't
read yet.

## Checking it

The EOL watch page shows each source's state: *off on this copy*, *waiting
on API keys*, *waiting on mailbox access*, *waiting on a Claude API key*, or
when it last ran and what it found. Errors from a source show there too.

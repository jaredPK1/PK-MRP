"""What's new, newest first -- shown on the Training page.

Every feature people can see gets a line here in the same change
(CLAUDE.md working agreement).
"""

WHATS_NEW = (
    (
        "2026-10-29",
        "Clear an overbuy with a reason",
        "Some overbuys are legitimate — service spares, stock at a contract manufacturer, a minimum buy, a PO already changed with the vendor. Click Clear… on the line, pick why (Other needs a note), and it moves to Cleared at the bottom with your name and reason; the totals leave it out. It comes back by itself if it grows, and Put back undoes it. Anyone signed in can clear. Clear ten in a day and something fun happens.",
    ),
    (
        "2026-10-29",
        "Analytics",
        "A new tab answers four questions: is PK-MRP saving money and orders (where what buyers did matched the advice, and the orders and dollars behind it — counted honestly, since shadow mode can't prove cause), is the plan getting healthier day by day, where today's lateness comes from (how late, product, vendor, buyer), and which vendors deliver — on-time % against the date first asked on the PO and real lead time vs MAX's, from 24 months of PK's own POs, with a quarterly trend.",
    ),
    (
        "2026-10-29",
        "One order per vendor",
        "Placing a buy now pulls in everything else PK needs from that vendor. Click the vendor on any buy (\"XOMETRY · +20 more to order with it\") or open By vendor: the order lists what's late and due now plus what comes due in the next 1–12 weeks, with the vendor's part numbers, pack counts and totals. Untick what shouldn't go, then copy it for the PO or download a CSV. Recent open POs with the vendor are shown, in case adding lines beats a new PO. Committed parts show their blanket release as a note, never added on top.",
    ),
    (
        "2026-10-29",
        "Pipeline: match sales SKUs to MAX parts",
        'PK-MRP can now read Book/Bill 2.0, but sales books "2300AG-B" where MAX has CF-0016-00G, so none of the forecast reached the committed parts. The new Pipeline page proposes the MAX part for each SKU — from its part number, its description, and what MAX put on the orders past bookings became — surest first, and an admin confirms it with one click (or picks another part, or marks it not material). Confirmed matches feed Committed from the next plan. Bookings with no billing month have their own list to fix in Book/Bill.',
    ),
    (
        "2026-10-29",
        "The decision ledger is recording",
        "The PK_Ops tables are in, so every plan's recommendations are now recorded and later matched to what buyers did. The footer shows how many are open.",
    ),
    (
        "2026-10-28",
        "Needs a source",
        "Parts nobody has bought before and that have no vendor in MAX — new magnets, fittings, 3D-printed brackets — left the ranked list (where MAX's placeholder lead time made them look months late) for their own list on Today, sorted by the orders waiting, with a Why? on each. Quote them, set the vendor up, and they join the ranking.",
    ),
    (
        "2026-10-28",
        "Uline, and parts whose description names the store",
        "Uline is a shelf vendor (PK's orders arrive next day). A part MAX has no vendor for but whose description names a catalog store — \"BOX, ULINE S-4589, 8X8X3\" — now goes to that store's Shelf order instead of the ranked list.",
    ),
    (
        "2026-10-28",
        "Packs, reels and boxes",
        'Parts MAX buys in packs (a screw in 100-packs, a reel of 5,000) are now bought in whole packs, shown as "100 to buy (1 PK of 100)", and the Shelf order copies pack counts for the quick-order paste. Pack parts\' order history counts toward their lead time again — MAX records their receipts in packs, which had made them look short-received.',
    ),
    (
        "2026-10-28",
        "Fast vendors count as shelf, too",
        "Any vendor whose POs usually arrive within 6 working days (median of PK's own orders) now counts as a shelf vendor, listed or not — Webstaurant, Amazon Business, Zoro, Newegg, Fastener Superstore and more. Webstaurant's shelving parts plan on 5 days instead of MAX's 45.",
    ),
    (
        "2026-10-28",
        "POs dated far out no longer stretch lead times",
        "A PO asked for more than twice the part's usual lead time, that arrived by that date but slower than usual, is left out of the lead time — judged against the part's own history, not MAX's number (which is often the inflated one). The Rexnord hub clamp went from 79 working days to 43.",
    ),
    (
        "2026-10-28",
        "Lead times for parts bought rarely",
        "A part with fewer than 3 orders in the last two years now uses its most recent older orders (up to 5, back ten years) instead of MAX's lead time. 32 of this week's buys changed; a Lee Spring spring went from MAX's 45 working days to its real 16.",
    ),
    (
        "2026-10-28",
        "Shelf parts and the Shelf order",
        "Cheap parts from catalog distributors (McMaster, Digi-Key, Mouser, Newark, Grainger, Fastenal) are planned on the distributor's real delivery time instead of MAX's, leave the top 10 and Overbuys, and appear as one cart per vendor on Today, with a button that copies their part numbers for a quick order.",
    ),
    (
        "2026-10-28",
        "Committed plans pull in before they buy",
        'When a month is short but POs are already placed for later, the plan now says "pull in N" instead of proposing a new blanket — new buys only for what\'s genuinely missing.',
    ),
    (
        "2026-10-28",
        "Committed vs Lead times, clearer",
        "Each page now says the one question it answers — Committed: which parts are planned a year ahead (a buying page); Lead times: which numbers in MAX are wrong (a clean-up page) — and both use MAX's working days.",
    ),
    (
        "2026-10-28",
        "Fold cards away",
        '"Why?" opens and closes on a second click. "Done" (or d) folds a buy card to one line with an Undo, and the top 10 counts how many you\'ve got through.',
    ),
    (
        "2026-10-28",
        "Overbuys page",
        "Open POs nobody needs, POs bought for more than will be needed, POs arriving early, and stock no booked order needs — in dollars, by buyer, with what was placed in the last 30 days.",
    ),
    (
        "2026-10-28",
        "Training page",
        "How PK-MRP works and how to use each page, with a live example.",
    ),
    (
        "2026-10-28",
        "Why this buy? rewritten",
        "Every buy now says when it runs out, what to order from whom, when it lands, who's waiting, and month by month.",
    ),
    (
        "2026-10-28",
        "Search by description",
        "Find parts by number fragments or description words — on Promise, All buys, Committed and Lead times.",
    ),
    (
        "2026-10-28",
        "Committed supply",
        "12-month plans, blanket orders and supplier forecast letters for the long-lead parts.",
    ),
    (
        "2026-10-28",
        "Promise check",
        "The earliest date material supports for a new order, and the part that decides it.",
    ),
    (
        "2026-10-28",
        "Lead times to fix",
        "Where MAX's lead time is more than 25% off the part's real history, with a proposal and a CSV.",
    ),
    (
        "2026-10-28",
        "Today's top 10",
        "The home page: the buys most worth placing today, ranked by the orders they hold up.",
    ),
)

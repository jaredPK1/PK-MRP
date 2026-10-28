"""What's new, newest first -- shown on the Training page.

Every feature people can see gets a line here in the same change
(CLAUDE.md working agreement).
"""

WHATS_NEW = (
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

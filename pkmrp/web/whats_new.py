"""What's new, newest first -- shown on the Training page.

Every feature people can see gets a line here in the same change
(CLAUDE.md working agreement).
"""

WHATS_NEW = (
    (
        "2026-11-06",
        "Part lookup: PK-MRP next to MAX MRP for any part",
        "Chad's ask: with PCAs changing vendors he'll buy a little ahead, and PK-MRP's demand for a PCA isn't MAX's. Planning → Part lookup takes any part number or description and shows what each says to buy over 3, 6 or 12 months, both demands split by where they come from — sales orders, open WOs, builds of parent assemblies, master-schedule forecast, safety stock — and which bucket makes the gap. For PCAs it's almost all one bucket: on 11-06, 96% of MAX's PCA demand came from its own planned orders for the parent assemblies, which carry forecast and MAX's safety stock down the bill; PK-MRP plans parents only for booked orders. Also lists MAX's planned orders and action messages, and every requirement MAX nets against the part. Why this buy? links to it.",
    ),
    (
        "2026-11-06",
        "Long-lead parts: one order for a quarter, rounded to the price break",
        "Long-lead parts were left to their blanket plan, so Today asked only for what couldn't wait — but no blanket is placed in MAX, so the same part came back every few days. Haydon Kerk motors went on three POs in eight days (70111310, 70111350, 70111387), each small enough to land in a smaller price break: 37-0007-01G cost $163.35 for 10 against $143.58 for 30 the same week. Now a long-lead buy covers about 13 weeks of booked orders, and any buy rounds up to the vendor's next quoted break (Part_Vendor) when booked orders inside 26 weeks use the extra and it stays within the spend cap. A PO for the part from the last two weeks is now the first thing on the card: Add to PO …, and a chip on All buys.",
    ),
    (
        "2026-11-05",
        "Vendor orders say which lines need a rush",
        "A vendor order gathered everything due from that vendor, all ticked, so a quote for the urgent lines carried the rest at the same speed. On 11-05 a Xometry quote for two top-ten 2920 parts also carried three that could wait — one already on a Duyck PO — at the fastest tier, 3.9x Xometry's own past prices. Each line now says rush (past its order-by: only the vendor's expedited option makes the need-by), order now (the usual lead still makes it) or can wait, and whether any order is waiting on it. When rush lines are mixed with others, a note says to quote them separately, with Tick rush lines only / Tick the rest. Copy and CSV carry the speed.",
    ),
    (
        "2026-11-05",
        "No-vendor parts holding up an order come to the top",
        "Parts nobody has bought before have no vendor in MAX, so they sat in the closed Needs a source box: off the ranked list, out of the late count, out of the Monday email. On 11-05, 12 of them were past their order-by date with a sales order waiting — including two optical switches (53-4130-00G and 53-4131-00G, the 1x96 at $23K each) that SO 20048126 is due with on 11-17, 142 days late to order. Now any no-vendor part a sales order waits on, late or due this week, is in a red box at the top of Today, the late tile says how many more there are, and the Monday email has a No vendor, orders waiting section right after Buys to place.",
    ),
    (
        "2026-11-04",
        "Critical safety stock ranks after late order buys",
        "A critical part's safety-stock buy went to the very top of the list, so on 11-04 three of them held slots 1-3 with \"Place today\" and \"protects $13.1M\" while 48 buys that orders are already waiting on were late. They looked like emergencies, and nothing was short. Now they rank right after the late order buys and ahead of every other buy, the chip says Restore safety stock instead of a place-by date, and the card reads \"9 orders worth $13.1M rely on it · none is short\".",
    ),
    (
        "2026-11-04",
        "Decision check: safety stock after a PO isn't a short PO",
        "Since safety stock was switched on (11-02), \"More wanted right after a PO\" went from 3 parts to 32 and told buyers each PO \"was smaller than booked orders need\" — but 28 of the 32 POs covered every booked order; what was left was safety stock, plus the sizer's extra weeks of cover. Now that list only shows parts booked orders still need, and says how many. A PO that covered the orders and left only safety stock goes in a new list, Safety stock after a PO: nothing to do unless adding it to that PO reaches a price break.",
    ),
    (
        "2026-11-03",
        "Today's win tile only credits real buys",
        "The tile on Today counted every buy that left the list, whatever the reason, and added order value once per buy, so an order feeding ten buys counted ten times. On 11-03 it read 72 and $97M — but none had a PO; the Load Plan change had moved their orders into 2027. Now it counts only buys that left because a PO for the part went into MAX since the last plan, with each order's value counted once. Buys that left because the plan changed are listed beside it, not credited.",
    ),
    (
        "2026-11-03",
        "Excess stock, for the inventory reserve",
        "A new Excess stock page (Cleanup menu) lists every part, made or bought, with more on hand than the plan needs — the starting list for the excess & obsolete reserve, which Tim has been building from MAX's MRP. Made parts and finished goods count only what their parents still need after their own stock. Long-lead parts, bought a year ahead on purpose, are measured against 12 months of requirement plus buffer, not just booked orders. MAX's -FAMILY forecast entries don't count. Valued per each (MAX's cost ÷ its cost-unit conversion — reels and packs would otherwise read up to 5,000× high). Each part gets a tier: dead, idle, slow or over, by demand and last use. CSV of every part.",
    ),
    (
        "2026-11-03",
        "Parked orders planned where the Load Plan has room",
        "Orders parked on 2032-34 dates in MAX ($14M, mostly booked in the last six months) were being planned on the customer's date, so their parts read as due now. Now each one is planned into the first month with room under Control Tower's Load Plan caps — $5M of revenue a month and the unit caps per model — oldest order first, never before the customer's month. An order too big for one month is spread line by line. Parts for those orders move to when the order can really ship; long-lead parts still see the demand. MAX keeps the placeholder date, so the line still needs a real one from Order Admin.",
    ),
    (
        "2026-11-02",
        "Critical parts: safety stock that ranks with the urgent buys",
        "A new note, Critical — single source / hard to replace (\"+ note\" on any part). A critical part keeps its MAX safety stock exactly as set, and when stock drops below it the buy goes to the top of the list, so working the top ten covers it. The card says Critical part: protects N orders, none short yet. Start: the eight 2920 parts Engineering flagged in the NPI review.",
    ),
    (
        "2026-11-02",
        "Safety stock counts, when it makes sense",
        "PK-MRP used to plan from booked orders only, so the safety stock Ron set for the 2920 parts didn't move anything. Now MAX's safety stock on bought parts is a floor: after booked orders, stock below it is a buy marked safety stock, ranked after every buy that protects an order, so the top ten doesn't change (SS-only buys are linked under it and get their own section in the Monday email). A PO kept for safety stock also stops showing as an overbuy. Each number is judged first: ignored on held, replaced or maker-obsolete parts and on parts nobody used in 12 months with nothing booked (a $70K sampling head had one), and capped at 6 months of real use (300 of a fiber used about 3 a month becomes 17). The new Safety stock page (Cleanup menu) lists those for fixing in MAX, with a CSV.",
    ),
    (
        "2026-11-02",
        "One email a week, Monday morning",
        "The EOL alert went out every hour over the weekend, and most of it was noise: 166 parts, 139 that nothing booked needs, and several that weren't even our part (a search for an Edmund lens number also finds a Wiha screwdriver). Now PK-MRP sends one email, Mondays at 7 am, instead of the Friday summary and the EOL alerts. On top is Needs you this week, most urgent kind first: buys past their order-by, parts going obsolete with nothing to cover them, Done that MAX doesn't show, recent overbuys, price issues, repeat POs. Up to five lines each, NEW marked if it wasn't in last Monday's email, every part a link to its page. The EOL watch now checks the maker as well as the number, doesn't count \"discontinued at DigiKey\" as obsolete, looks up the other maker part numbers MAX approves for a part, and splits the list into Act, Watch and nothing booked. Only Act goes in the email.",
    ),
    (
        "2026-10-30",
        "Email when a part goes obsolete",
        "When the EOL watch newly finds a part obsolete, end of life, last-time buy or not recommended for new designs, PK-MRP emails it once (Jared, Patrick, Chad, Rob and Aaron to start; an admin changes the list at the bottom of the EOL watch page): the part, where we heard it (with a link), where it's used, booked demand, stock and cover, and the last-time-buy quantity. DigiKey and Mouser lifecycle checks are live; supplier emails and maker news join once their access is set up.",
    ),
    (
        "2026-10-30",
        "Sourcing ideas and EOL watch",
        "Two new Buying pages. Sourcing ideas lists where buying differently would save money or build hours, each with dollars a year and what to do: switch to a vendor who sold the part for less and isn't worse on delivery or returns (big gaps are marked check scope — usually raw vs finished or bare vs assembled), order up to a quoted price break, build a bought part here (with the hours that still break even at the shop rate), buy a part we build (or get quotes for long builds when hours are short), and vendors worth an annual agreement or blanket. It also lists standard costs far from what we pay, with a CSV for the cost roll. EOL watch lists parts makers are ending, from distributor lifecycle data, PCN/EOL emails in the purchasing mailbox and a weekly web search of makers — with where each part is used, booked demand, months of cover and a last-time-buy quantity. Catalog prices, the mailbox and news switch on once the keys and IT's mailbox access are in place. Mark items Reviewed with a note.",
    ),
    (
        "2026-10-30",
        "Vendor prices: who is raising prices, down to the PO",
        "A new Vendor prices page (Reports menu, and linked from Analytics) shows how much more PK pays for the same parts than a year ago — overall and per vendor, with a line by month so you can see whether increases are speeding up. Click a vendor for its parts (price a year ago, latest, standard, dollars), and a part for every PO and open PO with its unit price, PPV and invoice. At the top is a list worth a look, biggest dollars first: a PO priced 10%+ above the one before, an open PO 20%+ over standard, the same part 15%+ cheaper from another vendor, a vendor-wide increase, and prices 4x off (usually a pack/each slip). Mark each one Reviewed with a note when it's handled. The Friday email lists the top five.",
    ),
    (
        "2026-10-30",
        "Smarter order quantities, and a decision check",
        "Buys used to show only what was due this week, so a cheap part came back every few days: 14 of the $36 USB cable on Thursday, 15 more on Friday, 114 behind that. Now each buy is one sensible order: it covers booked orders for a stretch of weeks worked out from the part's cost and how fast orders use it (cheap, steady parts cover more; expensive parts only what's needed now; committed parts follow their blanket plan). The card says how far it covers and how many can't wait, and if a PO for the part went in during the last two weeks it says to add to that PO. A new Decision check page (Reports menu) runs every hour and lists repeat POs, parts wanted again right after a PO, buys that changed sharply since the last plan (a red changed chip on the card), buys that came and went, and late buys left sitting.",
    ),
    (
        "2026-10-29",
        "A shorter top menu",
        "Thirteen links became Today plus four menus: Buying (All buys, By vendor, Done, Committed, Lead times), Planning (Promise, Pipeline), Cleanup (Fix in MAX, Overbuys, Notes) and Reports (Analytics, Weekly email). Each page has a one-line description in its menu, and the menu you're in is highlighted. Training is at the right.",
    ),
    (
        "2026-10-29",
        "Friday summary email, feedback button, back to PK Connect",
        "Every Friday at 3 pm a one-page email sums up the week: how the plan moved (buys due, late, orders and dollars waiting), what got placed and whether MAX confirmed it, whether buying followed PK-MRP's advice, the top of next week's list, and the Fix in MAX counts. See it — and send yourself a test — on the Weekly email page (link at the bottom of Training). PK-MRP also has PK's feedback button now (bottom right), and \"‹ PK Connect\" at the top left takes you back to the app launcher.",
    ),
    (
        "2026-10-29",
        "Who's on it, and Done that MAX checks",
        "Each buy on Today and All buys has an \"On it\" dropdown (Chad / Rob / Aaron) so everyone can see who is working what. Done is now shared and recorded — who, when and the PO number — instead of a fold in your own browser, and it's checked: on the next plan, a buy MAX no longer needs is confirmed, and one MAX still needs comes back flagged \"no PO in MAX\". The new Done page lists every one, by period and person. The d shortcut is gone (it folded cards by accident), and Today's top ten is numbered 1-10 again when a part is on hold.",
    ),
    (
        "2026-10-29",
        "Fix in MAX",
        "A new page lists everything in MAX that still names a part Engineering obsoleted — open order lines, forecast (master-schedule) entries, released work orders, and live BOMs — each with the part the same ECN released in its place. These are what make MRP buy dead parts (46 orders on the old station interface had MRP buying the obsolete support bracket). It's rebuilt every plan from Ron's ECN app, rows drop off once MAX is fixed, and a CSV gives the bulk-change list. Today shows a one-line count when there's something to fix. Also lists order lines on parts an open ECN is about to obsolete.",
    ),
    (
        "2026-10-29",
        "Replacements: stop buying the part Engineering replaced",
        "When orders or work orders in MAX still name an obsolete part, PK-MRP kept planning it (46 orders on the old station interface 00-2930-00G made it say \"buy 64-2694-02G\" and never ask for -03G). A planner can now set a replacement on the Notes page — old part → new part, optionally using up the old stock — and from the next plan the demand, work-order requirements and BOMs move to the new part. The old part shows a \"→ new part\" chip. Also: the quantity on each Today card now says it's the minimum to place this week, with a link to the vendor's 4-week order.",
    ),
    (
        "2026-10-29",
        "Hold a part so nobody buys it",
        "A \"Hold — don't buy yet\" note now takes the part off Today's top 10, All buys, By vendor, Needs a source and the shelf carts, straight away. Held parts are listed under On hold on Today with who held them and why; remove the note to release it. First one: 45-3036-00G (obsolete per ECN 126041, none on hand).",
    ),
    (
        "2026-10-29",
        "ECNs from Ron's ECN app",
        "PK-MRP now reads Ron's ECN app every plan. A part on an open ECN shows a blue chip (\"ECN 126168 · In Process\"), and a part whose latest closed ECN set it to rev ZZ shows a red \"obsolete · ECN …\" chip — everywhere the part appears, with the ECN's details in Why this buy?. Click a chip to open the part's ECN history in the ECN app. Today now opens with any buys of an obsoleted part and what's still pulling them, so nobody buys a dead part. ECNs never change the plan by themselves.",
    ),
    (
        "2026-10-29",
        "Notes on a part",
        "Know something MAX doesn't say? Click + note next to any part number — Engineering working on a replacement, obsolete, ECN being created, on hold, supplier problem, or your own words. The note stays on the part, plan after plan, and shows as a chip wherever the part appears (Today, All buys, Overbuys, Committed, By vendor, Promise and the Why panel), so nobody has to flag it again. The Notes page lists them all, with filters; Remove when it's no longer true. Notes don't change the plan. Anyone signed in can add one.",
    ),
    (
        "2026-10-29",
        "Pages use your whole screen",
        "Tables were squeezed into a narrow column even on a wide monitor, so descriptions wrapped to three lines and the last columns slid off the edge. Pages now spread out to fit the screen, dates stay on one line, and Clear… on Overbuys is pinned to the right so it's always in view. Also fixed: Promise was showing an error for every part.",
    ),
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

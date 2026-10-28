# PK-MRP

Backlog-driven material planning for Photon Kinetics (PK), Beaverton OR. PK builds fiber-optic test and measurement systems (2300, 2550, 26xx, 2800, 8000 OTDR, 1050, FLS-3) and cleavers/horn assemblies. The ERP is ExactMAX on SQL Server.

Owner: Jared Green, Director of Operations. Users: the planner (Devyani), production (Johnny), supply chain and quality (Chad), buyers (Rob, Aaron) and Order Admin (Nestor, Krystal).

## Why this exists (read before designing anything)

In 2026, PK's bookings roughly tripled, from about $28M in 2025 to about $84M booked Jan–Oct 2026, while shipments stayed at $6–11M a quarter. Supply is still planned the way it was for a short-cycle shop:

- One undifferentiated MRP covers about 1,750 purchased parts.
- MRP is fed by hand-keyed `-FAMILY` master-schedule entries, and the lead times in MAX are stale.
- Shortages are found at kitting.

The 2026 data shows the following:

- Customer windows (order date to requested date) on system orders grew to a median of about 150–190 days.
- Of the purchased parts in the top-revenue systems, only about 85 take more than 90 days from PO to receipt. For about 95% of parts, booked orders alone give enough lead time.
- Long-lead parts were ordered late and short. The median long-lead part had supply covering about 75% of its booked 2026 demand.
- Supplier delivery is a second-order problem: 74% of 2026 PO lines arrived within 3 days of the original due date.
- MAX lead times are wrong in both directions. 18% of repeat-bought parts take more than 1.5x their setting, and 42% take less than 0.75x.

**Design principle:** the backlog is the plan. Short-lead parts are bought purely against booked orders. The roughly 85 long-lead and single-source parts get committed 12-month supply. Promise dates are checked against supply. Parameters are maintained from data, not by hand.

**Product rule:** every feature must remove recurring work from an overloaded team. Do not add a report, dashboard tile or metric unless it replaces something people do today. If a feature only adds information, push back in the PR description.

## Hard rules

1. **Read-only against ExactMAX.** Never `INSERT`, `UPDATE`, `DELETE`, `EXEC` or run DDL against `ExactMAXPKLive`.
   - Use a dedicated read-only connection or login.
   - Add a guard in `db/erp.py` that rejects any SQL not starting with `SELECT` or `WITH`. A test must cover this guard.
   - Recommended changes to MAX (lead times, safety stock, PO dates) are exported as reviewable CSV or worklists for a human to key in.
   - Built 2026-10-28 (`pkmrp/db/erp.py`, `tests/test_erp_guard.py`): one statement only, must start with `SELECT`/`WITH`, and no `INTO`, `DECLARE`, `SET`, `EXEC`, `sp_`/`xp_`, `OPENROWSET`/`OPENQUERY` or any write/DDL keyword outside literals and comments. Consequence for `extract.py`: **no temp tables or variables** -- a heavy extract that would want `#temp` (PK Dispatch and Control Tower both use them for running totals) must be split into plain SELECTs and joined in pandas instead. Verified live: the guard and the server (`UPDATE permission was denied`) both refuse writes.
2. **Shadow mode first.** v1 runs beside the existing MAX MRP and records its own recommendations. Buyers act on PK-MRP only after Jared switches a part class to `live` in settings.
3. **Deterministic core.** BOM explosion, netting, segmentation and ATP must be pure, deterministic and unit-tested. ML only adds probabilistic demand beyond the backlog horizon and yield factors, and every ML output must have a deterministic fallback.
4. **Explainable outputs.** Every recommendation carries a `why` trace: which sales orders, BOM paths, on-hand, open POs and parameters produced it. A buyer must be able to click a number and see where it came from.
5. **No secrets in the repo.** Connection settings come from environment variables (`.env` is git-ignored). Ship a `.env.example`.
6. **No customer or pricing data leaves the PK network.** LLM calls, if any, must not send SO prices or customer names to an external service unless Jared explicitly enables it per feature.

## Stack

Match Jared's existing `pk-ops-tower` conventions unless there's a reason not to.

- Python 3.11, `pyodbc` with ODBC Driver 17 or 18 for SQL Server, `pandas`, `numpy`.
- Web: Flask with blueprints, server-rendered templates plus HTMX for interactivity, and Plotly for the few charts that earn a place.
- App state: **`PK_Ops` on PK-SQL01** (decided by Jared 2026-10-28), through SQLAlchemy Core (`mssql+pyodbc`). Not SQLite.
  - Connect with **Control Tower's login, `app_control_tower`**, as PK Dispatch does. Same login reads ExactMAXPKLive.
  - That login has **SELECT only on ExactMAXPKLive** (no UPDATE/DDL — checked 2026-10-28), so read-only MAX is enforced by the server as well as by the `db/erp.py` guard.
  - It has read/write on PK_Ops but **no CREATE/ALTER** there. PK-MRP's tables are therefore created by the DBA (Chris) from a reviewed script, `deploy/pk_ops_schema.sql`, the way PK Dispatch's were (see `PK-Dispatch/docs/NOTE_TO_CHRIS_PK_OPS.md`). The app never runs DDL; a schema change is a new script plus a request.
  - Prefix every table `mrp_` — PK_Ops is shared with PK Dispatch (`audit`, `settings`, `wo_closure`, ...). Never write to another app's tables; reading them (e.g. Dispatch's `wo_closure`) is fine.
  - Tests use SQLite in-memory through the same SQLAlchemy Core tables, so keep the SQL portable (no T-SQL in `store.py`).
- Jobs: a single `pkmrp` CLI using `click`, scheduled by cron or a systemd timer on Dev-PK-Connect, or Task Scheduler on Windows.
- ML: `scikit-learn` and `lightgbm` only when needed. Prefer simple, calibrated models.
- Tests: `pytest`, using frozen parquet fixtures sampled from the ERP in `tests/fixtures/`. Do not hit the live ERP in tests.
- Lint and format: `ruff` and `ruff format`.

**Connection (settled 2026-10-28):** SQL login, not Windows auth. PK-MRP runs as a container on the pk-apps server (10.6.1.70 dev / 10.6.1.80 prod, deployed through pk-server-manager like the other apps), which is Linux. `DB_SERVER=PK-SQL01`, `DB_USER=app_control_tower`, `DB_PASSWORD` from the governed env file — never in the repo. ODBC Driver 18 with `TrustServerCertificate=yes;Encrypt=yes`. `ERP_AUTH=windows` may stay for a laptop run but is not the deployed path.

## Repo layout

```
pk-mrp/
  CLAUDE.md
  pyproject.toml
  .env.example
  pkmrp/
    config.py            # env + settings (horizons, thresholds, part-class modes)
    db/
      erp.py             # read-only ExactMAX access + SELECT guard
      extract.py         # all ERP queries live here, nowhere else
      store.py           # app-state tables (SQLite)
    core/
      calendar.py        # workday/calendar conversion
      bom.py             # multi-level explosion, where-used, cycle guard
      demand.py          # backlog demand + pipeline layer
      supply.py          # on-hand, open POs, open WOs, allocations
      netting.py         # time-phased netting -> planned orders
      leadtime.py        # realized lead-time estimator
      segment.py         # order-driven vs committed part classification
      committed.py       # 12-month requirement, buffer, release schedule
      atp.py             # promise-date check for new SO lines
      params.py          # MAX parameter-reset recommendations
    ml/
      pipeline_conv.py   # opportunity -> order probability & timing
      yield_model.py     # per-part yield from MRB/receipts
    ledger/
      decisions.py       # Decision Ledger (see Experimental)
      regret.py
    experimental/
      allocation.py      # B: scarce-part allocation + shadow prices
      inbox_sensor.py    # C: supplier email -> supply signal events
      substitution.py    # D: alternates graph from ECN/BOM/email history
      stress.py          # E: time-to-survive vs time-to-recover
      heartbeat.py       # F: rolling supplier forecast letters + ack tracking
    integrations/
      graph.py           # Microsoft Graph (read-only mail) for C and D
    web/
      app.py
      blueprints/        # backlog, committed, promise, params, ledger, allocation, settings
      templates/
    cli.py
  tests/
```

All SQL lives in `db/extract.py` as named functions that return DataFrames with clean column names. Nothing else imports `pyodbc`.

## ExactMAX data model (verified 2026-10-28 against ExactMAXPKLive on PK-SQL01)

Columns use a table-number suffix. Text columns are padded, so always `RTRIM` them. Cast dates with `CAST(x AS date)`.

| Table | Key columns | Notes |
|---|---|---|
| `Part_Master` | `PRTNUM_01`, `TYPE_01`, `CLSCDE_01`, `PMDES1_01`, `PURLT_01`, `MFGLT_01`, `SAFSTK_01`, `ONHAND_01`, `NONNET_01`, `COST_01`, `BUYER_01`, `ORDPOL_01`, `MINQTY_01`, `MULQTY_01`, `OBSOLT_01`, `YIELD_01` | `PURLT_01` is in days; confirm workdays vs calendar days with Jared or Chad. The meaning of `TYPE_01` codes (B, A, Y, X, O, P, M…) is unverified, so ask before filtering on them. |
| `Product_Structure` | `PARPRT_02`, `COMPRT_02`, `QTYPER_02`, `TYPCDE_02` | Multi-level BOM. The existing code filters `TYPCDE_02='N'` for WO component demand; confirm what the other codes mean. Guard against cycles. |
| `Order_Master` | `ORDNUM_10`, `LINNUM_10`, `DELNUM_10`, `TYPE_10` (`PO`/`MF`), `PRTNUM_10`, `VENID_10`, `CREDTE_10`, `ORGDUE_10`, `CURDUE_10`, `ORGQTY_10`, `CURQTY_10`, `DUEQTY_10`, `STATUS_10`, `COST_10`, `CLSDTE_10` | POs and work orders. Open: see corrections below (status 3, not < 5). A PO line is keyed by (ORDNUM, LINNUM, DELNUM). |
| `PO_Receipts` | `ORDNUM_55`, `LINNUM_55`, `DELNUM_55`, `PRTNUM_55`, `VENID_55`, `TNXDTE_55`, `TNXQTY_55`, `COST_55` | Use it for realized lead time and supplier performance. |
| `SO_Master` | `ORDNUM_27`, `ORDDTE_27`, `CUSTID_27`, `CURR_27`, `STATUS_27`, `STYPE_27` | Header. Some orders are in JPY (`CURR_27`). |
| `SO_Detail` | `ORDNUM_28`, `LINNUM_28`, `DELNUM_28`, `PRTNUM_28`, `CUSTID_28`, `CURDUE_28`, `CUSDUE_28`, `ORGDUE_28`, `CURQTY_28`, `DUEQTY_28`, `PRICE_28`, `STATUS_28`, `STYPE_28` | Open customer backlog is `STYPE_28='CU' AND STATUS_28='3' AND DUEQTY_28>0`. |
| `Invoice_Detail` | `ORDNUM_32`, `LINNUM_32`, `PRTNUM_32`, `INVDTE_32`, `INVQTY_32`, `PRICE_32`, `CUSDUE_32` | Shipments and revenue. |
| `Requirement_Detail` | `ORDNUM_11`, `PRTNUM_11`, `CURDUE_11`, `DUEQTY_11`, `ISSQTY_11`, `STATUS_11` | WO component allocations. Use it to avoid double-counting demand already released to WOs. |
| `Part_Vendor` | `PRTNUM_07`, `VENID_07`, `PREFER_07`, `STATUS_07` | Approved sources. Approved sources and the vendors PK actually buys from can differ, so compute both. |
| `Vendor_Master` | `VENID_08`, `COMNAM_08` | |
| `MRP_Explosion_*` | latest by name | MAX's own MRP output. Use it for shadow-mode comparison only. |

### Corrections to the table above (verified in earlier sessions; these win)

- **Open PO** = `TYPE_10='PO' AND STATUS_10='3' AND DUEQTY_10>0`. Status 4/5 lines keep stale due dates ("zombies"). **Open work order** = `TYPE_10='MF' AND STATUS_10='3'`: status 4 means fully received, waiting only on the month-end close — done, not open (shared definition with Control Tower `wo_completion.py` and PK Dispatch).
- **WO complete** = the day own-part receipts (`Transaction_History` `TNXCDE_15='R'`, `PRTNUM_15=PRTNUM_10`) cumulatively cover `CURQTY_10`; a WO closed short (status 5) completes on its last receipt. Not `CLSDTE_10` (month-end accounting run).
- **`TYPE_01`**: `A` = make, `B` = buy, `Y` = bulk. MRP in MAX ignores bulk, and some real components are mis-typed `Y` (silent stockouts); bulk parts also over-buy unchecked. Other codes still unverified — ask.
- **`PURLT_01`** is in **business days**. `MFGLT_01` likewise (working days).
- **`Requirement_Detail`** joins to the WO on `ORDER_11` = `Order_Master.ORDER_10` (12-char internal order), not `ORDNUM_11`. Quantities: `CURQTY_11` required, `ISSQTY_11` issued; open = `CURQTY_11 > ISSQTY_11`. Rows with `ORDER_11 LIKE '70%'` are subcontract, not supply.
- **BOM superseded rows**: an ECN leaves the old `Product_Structure` row and adds a later row (often qty 0). Take the **latest `EFFDTE_02` per (parent, component)**; summing both double-counts (148K pairs). `-FAMILY` bills are super-bills — never explode them as a real build.
- **Cost**: `COST_01` is per `CSTUOM_01`; divide by `CSTCNV_01` (reels otherwise value ~5,000x high).
- **Prices** (`PRICE_28`, `PRICE_32`) are **unit** prices; multiply by quantity for extended $.
- **Configured systems**: an 86-/87-/88- price-header SO line plus its 01- build line is **one unit**. 47% of system SO lines (85% of kit lines) carry no price, so SO $ totals are a floor.
- **Far-dated SO lines**: unscheduled demand is parked on year-end dates 2032–34; treat due year >= 2030 as unscheduled (same rule as Control Tower's Orders page) rather than "more than 3 years out".
- **SO dates**: `ORGDUE_28` is the entry date, `CUSDUE_28` gets rewritten to the ship date, and MAX has no promise-date field. `CURQTY_28` is rewritten down on cancel. `SO_Master.STATUS_27` 3 = open, 4 = closed.
- **`OBSOLT_01`** is 0 on every part — useless as an obsolete flag. **`WGT_01`** is effectively empty.
- **Transaction codes**: `I` = issue to WO; `E` = cost revaluation (not usage — including it doubles consumption); `R` = receipt; `C` = cycle count (no order); `K` = bulk WIP; `P`/`Q` = labour/move.
- **WO → SO link**: only `ORDREF_10`, hand-typed. `Job_Progress.QTYREM_14=0` means "not reached", not done.
- **On hand by location** is `Part_Stock` (`QTYOH_06`, `ALLOC_06`); free stock = `QTYOH_06 - ALLOC_06`.

### Open questions found by the first live run (2026-10-28) -- ask Jared, don't guess

1. ~~Bought assemblies with BOMs~~ **Answered from the data (2026-10-28), `core/consign.py`.** PK supplies a few, usually hard-to-find, components to the vendors that build its bought assemblies. The consigned list is learned: a (parent, component) pair counts when, in the last 24 months, PK issued/transferred the part citing a PO for that parent (OFFSITE @ vendor moves, REFDES = PO number) or carried it on a subcontract PO, and the pair is on the parent's BOM (any type code). 115 pairs / 67 parents / 87 components. A planned buy of the parent explodes only its kit; open parent POs owe their kit (OFFSITE stock is nettable and covers what's already been sent); MAX-native subcontract POs use their own requirement rows instead. Jared didn't know the rule ("we supply some things, especially if they are hard to find") -- review the 87 with Chad.
   - The FPGA (31-7100-01SG) traced end to end: 8000 -> 03-3346-05G tested mainboard (make, 30 on hand covers the backlog) -> 02-3346-05G board (buy) -> FPGA. The 290 on order were bought ahead of the backlog for a 370-day part, so open receipts on long-lead parts now read `beyond_backlog`, not `cancel_candidate` (`committed_lead_bdays`, until `core/segment.py`).
2. ~~`TYPCDE_02='E'`~~ **Answered well enough to plan.** MAX's Code_Master doesn't define it. 18K of the 20K E rows sit under *bought* parents (vs 5K N); under make parents there are 14 E rows and none appear on PK's work-order requirements (59% of N rows do). So E is the vendor's build content: skipped for in-house explosion, and for bought parents only the consigned evidence decides.
3. **`Requirement_Detail` by prefix** -- 5- (WO, RQ) is used. What are 2- (161K open, TYPE CU, on SOs), 4- (59,791 open, RQ) and 3- (1,979 open)? Ignored for now.
4. **Which SO date drives demand** -- `CUSDUE_28` (default, matches PK Dispatch) or `CURDUE_28`.
5. **Ancient open WOs** put demand in the past (53-4104-00G: a WO requirement dated 2019-03-28). Keep as "needed now", or exclude WOs older than N months until planners close them?

### Overlap to resolve, not duplicate

PK Dispatch already runs a read-only MRP pass every 15 min (`PK-Dispatch/web/plan.py`: make parts, SO + open-WO demand, lot-for-lot, latest-EFFDTE BOM) for its "should be open now" Planning lists. PK-MRP should become the source for that list, or reuse its netting, not run a second answer beside it.

Pipeline / forecast source: Book/Bill 2.0 at `pk_sales.dbo.bookings`, which holds weighted forecast cards. The schema is unverified. Inspect it first, then write a contract in `extract.py`.

### Known data traps (handle them explicitly and test each one)

- `SO_Detail.ORGDUE_28` contains placeholder dates such as 2033-12-29, and some backlog lines are due in 2034. About $10M of backlog sits on far-dated placeholder lines. Treat any due date more than 3 years out as a placeholder: exclude it from time-phased demand and surface it on a worklist.
- `CUSDUE_28` may be edited by Order Admin to match PK's quoted date, so it is not always the customer's original ask.
- Configured part numbers (for example `CF-0016-00G`) may not have a full BOM. Flag SO lines whose part has no BOM and no stock as **unplannable**.
- Hand-keyed master-schedule (ATP) entries on `-FAMILY` parts drive about 42% of MAX's planned purchase dollars and double-count booked orders. PK-MRP ignores them by default; `settings.include_master_schedule=false`.
- Realized lead time is PO create → last receipt. It overstates parts that were deliberately ordered early with a far due date. Use `min(realized, ORGDUE-CRE + realized lateness)` logic, or the median across lines, and keep outliers visible.
- Exclude `PRICE=0` lines from revenue but not from material demand.

## Core algorithms (v1)

1. **Backlog explosion** (`core/demand.py`, `core/bom.py`)
   - Take open customer SO lines and explode them multi-level through `Product_Structure` into time-phased component demand.
   - Offset each level by its `MFGLT_01`, or a configured build-time per product family.
   - Net out finished goods and subassemblies already on hand or on open WOs.
   - Avoid double-counting demand already allocated in `Requirement_Detail`.
   - Output, per (part, week): `gross`, `allocated`, `net`, plus the list of driving SO lines.
2. **Supply position** (`core/supply.py`): on-hand (excluding non-nettable stock), open PO lines by current due date, and open WOs.
3. **Netting** (`core/netting.py`)
   - Produce a projected available balance by week.
   - Output planned orders with a need-by date and a place-by date. The place-by date is need-by minus the predicted lead time.
   - Output exception types: `late_to_place`, `expedite_open_po`, `push_out_open_po`, `cancel_candidate`.
   - Show the exceptions only for parts in `live` mode, plus a shadow log.
4. **Realized lead time** (`core/leadtime.py`)
   - Per part: the median and P80 of realized days over the last 24 months, with the vendor.
   - Fall back to the vendor-and-commodity median, then to `PURLT_01`.
   - Report each part's ratio to `PURLT_01`.
5. **Segmentation** (`core/segment.py`)
   - Mark a part `committed` if its P80 lead time is more than 90 days, or if it has a single source and a lead time over 60 days and gates more than $X of 12-month revenue.
   - Otherwise mark it `order_driven`.
   - Thresholds live in settings.
   - Recompute quarterly and persist the history so changes can be reviewed.
   - The expected size is about 85 parts; if the set comes out at 300 or more, the thresholds are wrong.
6. **Committed supply** (`core/committed.py`)
   - For committed parts, build a 12-month requirement: backlog explosion, plus pipeline demand (probability-weighted, with a growth-bias multiplier from settings), divided by the expected yield.
   - Size the buffer from lead time × demand rate × a service factor.
   - Output a proposed blanket order with monthly release schedule.
   - Output a supplier forecast letter (frozen 0–3 months, firm-ish 3–6, indicative 6–12) as PDF or CSV per vendor.
7. **Promise check** (`core/atp.py`)
   - Input: a part number, quantity and requested date (from a new SO, or typed in by Order Admin).
   - Return the earliest feasible date given committed-part availability, already-promised demand and a simple weekly build capacity per family (from settings).
   - Return which part is the binding constraint.
8. **Parameter health** (`core/params.py`)
   - Produce a quarterly CSV of proposed MAX `PURLT_01` and `SAFSTK_01` changes, with evidence.
   - A human keys the changes into MAX. Never write them back automatically.

## ML (v2, only after v1 shadow results are accepted)

- **Pipeline conversion** (`ml/pipeline_conv.py`)
  - Predict P(opportunity becomes an order) and the expected order month from Book/Bill 2.0 history, by customer and product family.
  - Start with a calibrated logistic or GBM model with time-based cross-validation.
  - Report the Brier score against the current weighting.
  - Feeds committed-part demand beyond the backlog horizon only.
- **Yield** (`ml/yield_model.py`)
  - Estimate per-part, per-vendor yield from MRB, DMR and receipt-reject history, using a Beta-binomial with a sensible prior.
  - Use it to gross up committed quantities. The monochromators are the motivating case: roughly 80% yield in 2026.
- **Do not build** a supplier-lateness predictor. It was tested on 2024–25 → 2026 POs, and vendor history only moved MAE from 22.5 to 21.5 days.

## Experimental (the parts nobody else ships)

### A. Decision Ledger with counterfactual regret (`ledger/`). Build it in v1; it is what makes shadow mode valuable.

- Every recommendation PK-MRP makes is logged immutably with its inputs snapshot (SO set, supply, parameters) and a hash: buy X by date D, expedite, promise date P.
- The ledger also logs what a human actually did, matched from later POs, SO date changes and receipts in MAX.
- At horizon close (receipt, shipment, or plus 26 weeks), compute regret for both paths:
  - revenue-days delayed × margin
  - plus carrying cost of excess inventory
  - plus expedite fees
- Show which path, PK-MRP or human, would have been cheaper, per part class and per buyer, with no leaderboard of people.
- Use the realized regret to tune policy parameters per part: the growth-bias multiplier, buffer service factor and segmentation thresholds. Use a conservative bandit or Bayesian update, with bounded step sizes, and require Jared's approval in settings before each change takes effect.
- Goal: PK learns its own buy policy from its own outcomes, and switching a part class from shadow to live becomes an evidence-based decision.

### B. Scarce-part allocation with shadow prices (`experimental/allocation.py`). v2; behind a feature flag.

- When a committed part is short (for example the 2304 lens: 85 units booked against 55 on order), solve a small linear or integer program that allocates the incoming units across open and pipeline orders. Use `scipy.optimize.milp` or OR-Tools.
- The objective maximizes margin × probability, with a penalty for lateness weighted by customer priority. Constraints are supply arrivals, build capacity and the earliest feasible date.
- Expose the **shadow price** of each scarce part: the marginal revenue of one more unit this month.
  - Purchasing sees what a premium or broker buy is worth. "Paying IDEX $X to pull in 5 lenses is worth $Y."
  - Sales sees the true cost of quoting a new 2300 into a constrained month.
- Always present the allocation as a proposal. Order Admin and Jared decide.

### C. Inbox-as-sensor (`experimental/inbox_sensor.py`). v2; behind a feature flag.

Problem it solves: 2026's surprises arrived by email or not at all. Keysight's lead time stretched after the PO was placed, with no notice. Optometrics wrote "our suppliers changing their operation". IDEX said "not accepting any pull-in requests for the remainder of 2026". No system captured any of these.

- **Source**
  - Read-only Microsoft Graph access (`Mail.Read`) to the Purchasing shared mailbox and to the buyers' folders that Jared approves.
  - Filter to supplier domains derived from `Vendor_Master`.
  - Never send, reply, move or flag mail.
- **Extraction**
  - Each message becomes zero or more typed **supply events**, each with confidence and a quoted evidence span:
    - `ack_date` (PO acknowledged with date)
    - `date_change` (pull-in or push-out)
    - `lead_time_change`
    - `allocation_or_constraint`
    - `pcn_or_process_change`
    - `price_change`
    - `eol_or_ltb`
    - `quality_issue`
  - Link each event to a PO line or part where possible. Use the PO number in text first, then the part or vendor part number (`Part_Vendor.VENPRT_07`), then the vendor plus open-PO match.
- **Model**
  - Use an LLM with a strict JSON schema and a few-shot set built from the 2026 threads above.
  - Rule 6 applies: strip prices before any external call, or run the model where Jared approves.
  - Keep a deterministic regex pre-pass for PO numbers and dates.
- **Effect on planning**
  - Events above a confidence threshold update the predicted receipt date of the linked open PO in PK-MRP's own supply view, never in MAX.
  - `pcn_or_process_change` and `quality_issue` events on committed parts raise an incoming-inspection hold suggestion to Quality.
  - Every adjusted date shows the email it came from.
- **Replaces:** buyers reading supplier mail and re-keying dates; finding out at kitting.
- **Test:** a labelled set of at least 150 real supplier emails. Report precision and recall per event type, and launch at precision of at least 0.9 for `date_change`.

### D. Substitution graph (`experimental/substitution.py`). v2.

Problem it solves: engineering substitutions happen under deadline and are forgotten. Examples are "replace one 53-4104-00G with two 53-0556-00G", 2000-series monochromators standing in for 1999s, and alternate brakes.

- **Nodes** are parts. **Edges** are typed:
  - `ecn_replaced` (from ECN and revision history, via Ron)
  - `bom_alternate` (from BOM revisions where one component was swapped for another under the same parent)
  - `engineering_approved` (mined from email or Teams, then confirmed)
  - `same_vendor_family` (vendor part number pattern)
- Each edge carries a quantity ratio (1:2), the conditions or parents it is valid for, approver, date, evidence link, and status: `proposed`, `approved` or `retired`.
- Only Engineering (Patrick's team) can move an edge to `approved`, using a one-click review queue.
- **Effect on planning:** when netting shows a committed or live part short, the exception lists approved substitutes with available quantity, and the ATP check can use them.
- **Effect on engineering:** a quarterly review queue proposes alternates for every single-source committed part that has none, so the work is scheduled instead of driven by interruptions.
- **Replaces:** "against the wall" substitutions in the war room.

### E. Time-to-survive vs time-to-recover (`experimental/stress.py`). v1.5; deterministic.

This method comes from supply-risk research (Simchi-Levi's work with Ford) and is rare in a shop PK's size.

- For each supplier and each committed part, compute:
  - **TTS** (time-to-survive): weeks until a line stops if that supplier ships nothing from today. It comes from on-hand, open WOs, in-transit stock and the backlog explosion.
  - **TTR** (time-to-recover): weeks to restore supply. Use the qualified second-source lead time, or requalification plus a new-source lead time, or the in-house make lead time, from settings and the substitution graph.
  - **Exposure:** revenue delayed if TTR exceeds TTS, computed from backlog dollars that require the part.
- Output a ranked list of supplier and part pairs where TTR exceeds TTS. This list feeds where to dual-source, buffer or bring work in-house, which ties to the CNC/machining case.
- Recompute monthly. Include a "what if" input: a supplier goes dark for N weeks.
- **Replaces:** debating which single-source risk to fix first.

### F. Supplier heartbeat (`experimental/heartbeat.py`). v1.5.

This extends Committed supply step 6. Forecast letters are standard practice; what's new is closing the loop.

- **Monthly letter.** For each committed-part vendor, generate a rolling 12-month forecast:
  - frozen 0–3 months, firm-ish 3–6 months, indicative 6–12 months
  - with a change log versus last month's letter
  - in PDF and CSV, from a template Jared approves
- **Sending.** Buyers send it. Do not auto-send in v1.
- **Tracking.** Track acknowledgement, using C's `ack_date` events when C is enabled, otherwise a manual tick.
- **Supplier response score.** For each vendor, track:
  - did they acknowledge
  - did their actual lead time improve after they received forecasts
  - did they accept pull-ins inside the frozen window
- This tells Jared which suppliers reward being a better customer and which need a second source. IDEX explicitly asked for at least a 12-month view.
- **Replaces:** one-off forecast emails and the guesswork about whether suppliers can plan to them.

## UI pages (each replaces a manual task)

| Page | Replaces |
|---|---|
| Backlog → Buy | Chasing MAX "late to order" noise; hand-keyed `-FAMILY` entries |
| Committed Parts | Ad hoc long-lead ordering, one PO at a time; email-set safety stock |
| Promise Check | Order Admin dating orders from quoted ARO without a material check |
| Parameter Health | Part-by-part lead-time and safety-stock edits by email |
| Decision Ledger | Arguing from anecdotes about whether the new way works |
| Allocation (B) | War-room calls on which order gets the scarce lens |
| Supplier Signals (C) | Reading supplier mail and re-keying dates; surprises at kitting |
| Substitutes (D) | Ad hoc engineering swaps under deadline |
| Supply Stress (E) | Debating which single-source risk to fix first |
| Supplier Heartbeat (F) | One-off forecast emails to suppliers with no follow-through |
| Settings | Thresholds, part-class modes (`shadow`/`live`), capacities, flags |
| **Home (splash)** | "Where do I start this morning": today's top 10 buys, this week's progress |

### It has to feel good to use (Jared, 2026-10-28)

PK-MRP lands on an overloaded team; if it feels like another ERP screen it won't get opened. Make it pleasant, even fun:

- **A home page worth opening first thing** -- a splash with **today's top 10 buys**: the parts most worth placing today (place-by date passed or today, ranked by the revenue they unblock), each with its quantity, vendor, place-by date and the sales orders it frees, one click to the `why` trace. This replaces "where do I start this morning", so it passes the product rule.
- **Progress you can feel**: what got done this week (recommended buys placed, parts that went from short to covered, committed parts now covered 12 months out), a short streak or "all clear" state when a list is empty, small celebratory moments when something clears. Never a leaderboard of people (same rule as the Decision Ledger).
- **Fast and calm**: instant page loads (precomputed by the CLI run, not live queries), plain-language labels instead of MAX column names, friendly empty and error states that say what to do next, shadow-mode badges that make it obvious nothing is live yet.
- **Polish**: a consistent look (PK colours, as Control Tower uses), good typography, works on a phone for a quick check.

Working pages behind the home page stay dense: tables first, at most one chart per page. Delight goes into the home page and the moments of completion, not into decorating data.

## Acceptance checks (regression tests against a frozen 2026-10-28 snapshot)

These figures came out of the exploratory analysis. The pipeline should reproduce them within a small tolerance, and any large difference must be explained.

- Bookings, 2026 Jan–Oct: about $84M. 2025: about $28M.
- Purchased parts in the BOMs of the top 40 revenue systems: about 1,750. P50 lead time over 90 days: about 85 parts. Over 120 days: about 37.
- Long-lead parts with 2026 bookings: median coverage (2026 PO qty + on-hand) ÷ booked demand ≈ 0.75.
- 2304 relay lens `46-0020-01G`: 85 units of booked demand since Jul 2025, 55 on order (POs 70110162, 70110655, 70110863).
- 2026 PO lines within 3 days of the original due date: about 74%.

## Build phases

| Phase | Scope | Gate to next |
|---|---|---|
| v1 | Extract, core 1–8, CLI, web pages for core, A (Decision Ledger), in shadow mode | 4+ weeks of shadow output reviewed; acceptance checks pass |
| v1.5 | E (stress test), F (heartbeat) | Jared switches first part class to `live` |
| v2 | ML (pipeline conversion, yield), B (allocation), C (inbox sensor), D (substitution graph), each behind its own flag | Per-feature sign-off; C needs Graph app registration + data-handling approval |

## Working agreements for Claude Code

- Before writing any query, check this file's data model. If you're unsure what a column or code means, ask; don't guess, and don't filter on a guessed meaning.
- Build in this order: extract, then core with tests, then CLI, then web. Show shadow output for the 2304 lens, 04-1999-02G monochromator, 53-4104-00G switch and 31-7100-01SG FPGA before building UI.
- Keep functions small and pure in `core/`. Do I/O at the edges.
- Every PR states which manual task it removes.
- Commit only when asked.

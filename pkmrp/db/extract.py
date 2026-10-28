"""Every ExactMAX query PK-MRP runs. Nothing else in the package writes SQL.

Each function takes an ErpClient (anything with .query(sql, params)) and
returns a DataFrame with clean, lower_snake column names. Text is RTRIMmed
in SQL; dates come back as pandas datetimes; quantities as floats.

Definitions follow CLAUDE.md, "Corrections to the table above":
  * open PO / open WO = STATUS_10 '3' (4 and 5 are done or zombies);
  * open customer backlog = SO_Detail STYPE 'CU', STATUS '3', DUEQTY > 0, on
    an open (STATUS_27 '3') order;
  * the BOM is the latest-effective row per (parent, component) -- an ECN
    leaves the old row and adds a later one -- and -FAMILY super-bills are
    not real builds;
  * cost is per stocking unit: COST_01 / CSTCNV_01;
  * on hand is Part_Stock, split nettable / non-nettable on NETFLG_06.

What is NOT decided here, on purpose: which SO date drives demand (all three
are returned), what the far-dated placeholder lines are, what TYPCDE_02 E/P/R
mean, which TYPE_01 codes to plan. Those are core/ or open questions.

The read-only guard forbids temp tables and variables, so each query stands
alone and joins happen in pandas.
"""

import pandas as pd

PARTS_SQL = """
SELECT RTRIM(PRTNUM_01) AS part,
       RTRIM(ISNULL(PMDES1_01, '')) AS description,
       RTRIM(TYPE_01) AS type,
       RTRIM(ISNULL(CLSCDE_01, '')) AS class_code,
       RTRIM(ISNULL(BUYER_01, '')) AS buyer,
       RTRIM(ISNULL(PLANID_01, '')) AS planner,
       ISNULL(PURLT_01, 0) AS purchase_lt_bdays,
       ISNULL(MFGLT_01, 0) AS mfg_lt_wdays,
       ISNULL(SAFSTK_01, 0) AS safety_stock,
       ISNULL(ONHAND_01, 0) AS onhand_master,
       ISNULL(NONNET_01, 0) AS nonnet_master,
       RTRIM(ISNULL(ORDPOL_01, '')) AS order_policy,
       ISNULL(MINQTY_01, 0) AS min_qty,
       ISNULL(MULQTY_01, 0) AS mult_qty,
       ISNULL(YIELD_01, 0) AS yield_pct,
       CASE WHEN ISNULL(CSTCNV_01, 0) = 0 THEN COST_01
            ELSE COST_01 / CSTCNV_01 END AS unit_cost,
       RTRIM(ISNULL(CSTUOM_01, '')) AS cost_uom,
       RTRIM(ISNULL(PURUOM_01, '')) AS purchase_uom,
       ISNULL(PURCNV_01, 1) AS purchase_cnv
FROM Part_Master
"""

BOM_SQL = """
SELECT parent, component, qty_per, type_code, effective FROM (
    SELECT RTRIM(PARPRT_02) AS parent, RTRIM(COMPRT_02) AS component,
           QTYPER_02 AS qty_per, RTRIM(ISNULL(TYPCDE_02, '')) AS type_code,
           EFFDTE_02 AS effective,
           ROW_NUMBER() OVER (PARTITION BY PARPRT_02, COMPRT_02
                              ORDER BY EFFDTE_02 DESC, MAXID DESC) AS rn
    FROM Product_Structure
    WHERE PARPRT_02 NOT LIKE '%-FAMILY'
) b
WHERE rn = 1 AND qty_per > 0
"""

OPEN_SO_SQL = """
SELECT RTRIM(d.ORDNUM_28) AS so, RTRIM(d.LINNUM_28) AS line,
       RTRIM(d.DELNUM_28) AS delivery, RTRIM(d.PRTNUM_28) AS part,
       d.DUEQTY_28 AS qty_due, d.CURQTY_28 AS qty_current,
       d.CURDUE_28 AS cur_due, d.CUSDUE_28 AS cus_due, d.ORGDUE_28 AS org_due,
       d.PRICE_28 AS unit_price, RTRIM(ISNULL(sm.CURR_27, '')) AS currency,
       RTRIM(sm.CUSTID_27) AS customer_id,
       RTRIM(ISNULL(cm.NAME_23, '')) AS customer,
       sm.ORDDTE_27 AS order_date
FROM SO_Detail d
JOIN SO_Master sm ON sm.ORDNUM_27 = d.ORDNUM_28
LEFT JOIN Customer_Master cm ON cm.CUSTID_23 = sm.CUSTID_27
WHERE d.STYPE_28 = 'CU' AND d.STATUS_28 = '3' AND d.DUEQTY_28 > 0
  AND sm.STATUS_27 = '3'
"""

STOCK_SQL = """
SELECT RTRIM(PRTNUM_06) AS part,
       SUM(CASE WHEN NETFLG_06 = 'Y' THEN QTYOH_06 ELSE 0 END) AS on_hand,
       SUM(CASE WHEN NETFLG_06 = 'Y' THEN ALLOC_06 ELSE 0 END) AS allocated,
       SUM(CASE WHEN NETFLG_06 = 'Y' AND QTYOH_06 - ALLOC_06 > 0
                THEN QTYOH_06 - ALLOC_06 ELSE 0 END) AS free,
       SUM(CASE WHEN NETFLG_06 = 'Y' THEN 0 ELSE QTYOH_06 END) AS non_nettable
FROM Part_Stock
GROUP BY PRTNUM_06
"""

OPEN_PO_SQL = """
SELECT RTRIM(ORDNUM_10) AS po, RTRIM(LINNUM_10) AS line, RTRIM(DELNUM_10) AS delivery,
       RTRIM(PRTNUM_10) AS part, RTRIM(ISNULL(VENID_10, '')) AS vendor_id,
       RTRIM(ISNULL(BUYER_10, '')) AS buyer,
       CREDTE_10 AS created, ORGDUE_10 AS org_due, CURDUE_10 AS cur_due,
       ORGQTY_10 AS qty_ordered, CURQTY_10 AS qty_current, DUEQTY_10 AS qty_due
FROM Order_Master
WHERE TYPE_10 = 'PO' AND STATUS_10 = '3' AND DUEQTY_10 > 0
"""

OPEN_WO_SQL = """
SELECT RTRIM(ORDNUM_10) AS wo, RTRIM(PRTNUM_10) AS part, RTRIM(ORDER_10) AS internal_order,
       DUEQTY_10 AS qty_due, CURQTY_10 AS qty_current,
       CREDTE_10 AS created, ORGDUE_10 AS org_due, CURDUE_10 AS cur_due,
       RTRIM(ISNULL(ORDREF_10, '')) AS reference
FROM Order_Master
WHERE TYPE_10 = 'MF' AND STATUS_10 = '3' AND LINNUM_10 = '00' AND DELNUM_10 = '00'
"""

# Components still to issue to open work orders. Joined on ORDER_11 (the
# 12-character internal order), not ORDNUM_11. Subcontract requirements
# (ORDER_11 '70%') are excluded by the MF join.
WO_REQ_SQL = """
SELECT RTRIM(o.ORDNUM_10) AS wo, RTRIM(o.PRTNUM_10) AS parent,
       RTRIM(rd.PRTNUM_11) AS part,
       rd.CURQTY_11 AS qty_required, rd.ISSQTY_11 AS qty_issued,
       rd.CURQTY_11 - rd.ISSQTY_11 AS qty_open,
       rd.CURDUE_11 AS due
FROM Requirement_Detail rd
JOIN Order_Master o ON o.ORDER_10 = rd.ORDER_11
WHERE o.TYPE_10 = 'MF' AND o.STATUS_10 = '3'
  AND o.LINNUM_10 = '00' AND o.DELNUM_10 = '00'
  AND rd.CURQTY_11 > rd.ISSQTY_11
"""

# Every PO line created on or after ? with its receipts, for realized lead
# time and delivery performance. Any status: closed lines are the history.
# PO quantities are in stocking units but PO_Receipts.TNXQTY_55 is in the
# purchase unit (a 5,000 EA line of 100-packs receives 50), so receipts are
# scaled by PURCNV_01 -- unscaled, every pack line looked short-received
# and 1,607 closed lines dropped out of the lead-time history.
PO_HISTORY_SQL = """
WITH rec AS (
    SELECT ORDNUM_55, LINNUM_55, DELNUM_55,
           MIN(TNXDTE_55) AS first_receipt, MAX(TNXDTE_55) AS last_receipt,
           SUM(TNXQTY_55) AS qty_received, COUNT(*) AS receipts
    FROM PO_Receipts
    GROUP BY ORDNUM_55, LINNUM_55, DELNUM_55
)
SELECT RTRIM(o.ORDNUM_10) AS po, RTRIM(o.LINNUM_10) AS line, RTRIM(o.DELNUM_10) AS delivery,
       RTRIM(o.PRTNUM_10) AS part, RTRIM(ISNULL(o.VENID_10, '')) AS vendor_id,
       RTRIM(o.STATUS_10) AS status,
       o.CREDTE_10 AS created, o.ORGDUE_10 AS org_due, o.CURDUE_10 AS cur_due,
       o.ORGQTY_10 AS qty_ordered, o.CURQTY_10 AS qty_current,
       r.first_receipt, r.last_receipt,
       ISNULL(r.qty_received, 0) * ISNULL(NULLIF(pm.PURCNV_01, 0), 1) AS qty_received,
       ISNULL(r.receipts, 0) AS receipts
FROM Order_Master o
LEFT JOIN rec r ON r.ORDNUM_55 = o.ORDNUM_10 AND r.LINNUM_55 = o.LINNUM_10
               AND r.DELNUM_55 = o.DELNUM_10
LEFT JOIN Part_Master pm ON pm.PRTNUM_01 = o.PRTNUM_10
WHERE o.TYPE_10 = 'PO' AND o.CREDTE_10 >= ?
"""

# Components PK sent to a vendor to build with (consigned kits): issues and
# transfers with no order number whose reference names a PO (70xxxxxx).
# Chad moves parts into an "OFFSITE @ vendor" location citing the PO, then
# issues them out of it when the boards come back -- or issues straight from
# a bin with the PO in REFDES. The PO number is parsed in pandas.
CONSIGN_MOVES_SQL = """
SELECT RTRIM(PRTNUM_15) AS component, RTRIM(TNXCDE_15) AS code, TNXQTY_15 AS qty,
       TNXDTE_15 AS moved, RTRIM(ISNULL(REFDES_15, '')) AS reference,
       RTRIM(ISNULL(STKID_15, '')) AS location
FROM Transaction_History
WHERE TNXCDE_15 IN ('I', 'T') AND RTRIM(ISNULL(ORDNUM_15, '')) = ''
  AND TNXDTE_15 >= ?
  AND REFDES_15 LIKE '%70[0-9][0-9][0-9][0-9][0-9][0-9]%'
"""

# What each PO (any order type: PO, SO subcontract, VO, NI) was buying.
PO_PARTS_SQL = """
SELECT DISTINCT RTRIM(ORDNUM_10) AS po, RTRIM(PRTNUM_10) AS parent,
       RTRIM(TYPE_10) AS order_type
FROM Order_Master
WHERE ORDNUM_10 LIKE '70%' AND CREDTE_10 >= ?
"""

# MAX-native subcontract POs carry their components in Requirement_Detail
# (ORDER_11 '7...'). Every row since ? is evidence; open rows are demand.
SUBCONTRACT_REQ_SQL = """
SELECT RTRIM(o.ORDNUM_10) AS po, RTRIM(o.LINNUM_10) AS line, RTRIM(o.PRTNUM_10) AS parent,
       RTRIM(rd.PRTNUM_11) AS part, rd.CURQTY_11 - rd.ISSQTY_11 AS qty_open,
       rd.CURDUE_11 AS due, RTRIM(o.STATUS_10) AS status
FROM Requirement_Detail rd
JOIN Order_Master o ON o.ORDER_10 = rd.ORDER_11
WHERE rd.ORDER_11 LIKE '7%' AND o.CREDTE_10 >= ?
"""

# Book/Bill 2.0 pipeline (pk_sales on PK-SQL01), same definition as its own
# forecast (pk-sales-app migration 081, `pipe`): status new/open/needs_review/
# po_received, Forecast toggle on, no SO yet (SO'd bookings are already in the
# backlog), not a "Region Actuals" account. Columns per pk-sales-app's
# repositories; access is a GRANT on pk_sales (deploy/pk_sales_read_grant.sql).
PIPELINE_LINES_SQL = """
SELECT b.id AS booking_id, RTRIM(b.booking_number) AS booking, a.name AS customer,
       b.status AS status, b.probability_win AS p_win, b.probability_go AS p_go,
       b.billing_year AS bill_year, b.billing_month AS bill_month,
       li.id AS item_id, RTRIM(ISNULL(p.sku, '')) AS sku, li.description AS description,
       li.quantity AS qty, CAST(NULL AS int) AS option_of
FROM pk_sales.dbo.bookings b
JOIN pk_sales.dbo.accounts a ON a.id = b.account_id
JOIN pk_sales.dbo.booking_line_items li ON li.booking_id = b.id
LEFT JOIN pk_sales.dbo.products p ON p.id = li.product_id
WHERE b.status IN ('new', 'open', 'needs_review', 'po_received')
  AND b.forecast = 1
  AND (b.so_number IS NULL OR LTRIM(RTRIM(b.so_number)) = '')
  AND a.name NOT LIKE 'Region Actuals%'
UNION ALL
SELECT b.id, RTRIM(b.booking_number), a.name, b.status, b.probability_win, b.probability_go,
       b.billing_year, b.billing_month,
       o.id, RTRIM(ISNULL(p.sku, '')), o.option_name, o.quantity * li.quantity, li.id
FROM pk_sales.dbo.bookings b
JOIN pk_sales.dbo.accounts a ON a.id = b.account_id
JOIN pk_sales.dbo.booking_line_items li ON li.booking_id = b.id
JOIN pk_sales.dbo.booking_line_item_options o ON o.booking_line_item_id = li.id
LEFT JOIN pk_sales.dbo.products p ON p.id = o.product_id
WHERE b.status IN ('new', 'open', 'needs_review', 'po_received')
  AND b.forecast = 1
  AND (b.so_number IS NULL OR LTRIM(RTRIM(b.so_number)) = '')
  AND a.name NOT LIKE 'Region Actuals%'
"""

VENDORS_SQL = """
SELECT RTRIM(VENID_08) AS vendor_id, RTRIM(ISNULL(COMNAM_08, '')) AS name,
       RTRIM(ISNULL(STATUS_08, '')) AS status
FROM Vendor_Master
"""

PART_VENDORS_SQL = """
SELECT RTRIM(PRTNUM_07) AS part, RTRIM(VENID_07) AS vendor_id,
       RTRIM(ISNULL(VENPRT_07, '')) AS vendor_part,
       RTRIM(ISNULL(PREFER_07, '')) AS preferred, RTRIM(ISNULL(STATUS_07, '')) AS status
FROM Part_Vendor
"""

ALL_SQL = {
    "parts": PARTS_SQL,
    "bom": BOM_SQL,
    "open_so_lines": OPEN_SO_SQL,
    "stock": STOCK_SQL,
    "open_pos": OPEN_PO_SQL,
    "open_wos": OPEN_WO_SQL,
    "wo_requirements": WO_REQ_SQL,
    "po_history": PO_HISTORY_SQL,
    "consign_moves": CONSIGN_MOVES_SQL,
    "pipeline_lines": PIPELINE_LINES_SQL,
    "po_parts": PO_PARTS_SQL,
    "subcontract_reqs": SUBCONTRACT_REQ_SQL,
    "vendors": VENDORS_SQL,
    "part_vendors": PART_VENDORS_SQL,
}

_DATES = {
    "moved",
    "effective",
    "cur_due",
    "cus_due",
    "org_due",
    "order_date",
    "created",
    "due",
    "first_receipt",
    "last_receipt",
}
_TEXT = {
    "part",
    "description",
    "type",
    "class_code",
    "buyer",
    "planner",
    "order_policy",
    "cost_uom",
    "purchase_uom",
    "parent",
    "component",
    "type_code",
    "so",
    "line",
    "delivery",
    "currency",
    "customer_id",
    "customer",
    "po",
    "vendor_id",
    "wo",
    "internal_order",
    "reference",
    "status",
    "name",
    "vendor_part",
    "preferred",
    "code",
    "location",
    "order_type",
    "booking",
    "sku",
}


def _clean(df):
    """Dates to datetimes, numbers to floats, text left as text."""
    for col in df.columns:
        if col in _DATES:
            df[col] = pd.to_datetime(df[col], errors="coerce")
        elif col not in _TEXT:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    return df


def _run(erp, name, params=None):
    return _clean(erp.query(ALL_SQL[name], params))


def parts(erp):
    """Every part with its MAX planning parameters; unit_cost per stocking unit."""
    return _run(erp, "parts")


def bom(erp):
    """Single-level BOM edges, latest-effective row per (parent, component)."""
    return _run(erp, "bom")


def open_so_lines(erp):
    """Open customer backlog lines with all three due dates."""
    return _run(erp, "open_so_lines")


def stock(erp):
    """On hand per part from Part_Stock, nettable and non-nettable apart."""
    return _run(erp, "stock")


def open_pos(erp):
    """Open PO delivery lines (status 3, quantity still due)."""
    return _run(erp, "open_pos")


def open_wos(erp):
    """Open work orders (status 3)."""
    return _run(erp, "open_wos")


def wo_requirements(erp):
    """Components still to issue to open work orders."""
    return _run(erp, "wo_requirements")


def po_history(erp, since):
    """PO lines created on or after `since` (a date), with their receipts."""
    return _run(erp, "po_history", [since])


def vendors(erp):
    return _run(erp, "vendors")


def part_vendors(erp):
    """Approved sources per part (Part_Vendor), not who PK actually buys from."""
    return _run(erp, "part_vendors")


def consign_moves(erp, since):
    """Issues/transfers to vendors citing a PO, with the PO number parsed."""
    df = _run(erp, "consign_moves", [since])
    df["po"] = df["reference"].str.extract(r"(70\d{6})", expand=False)
    return df


def po_parts(erp, since):
    """{po -> parent part} for every 70- order created since `since`."""
    return _run(erp, "po_parts", [since])


def subcontract_reqs(erp, since):
    """Component requirements on subcontract POs created since `since`."""
    return _run(erp, "subcontract_reqs", [since])


def pipeline_lines(erp):
    """Open Book/Bill 2.0 bookings' line items and options, with their SKUs.
    Raises if the login has no access to pk_sales -- the caller decides."""
    return _run(erp, "pipeline_lines")

"""DigiKey, Mouser and Nexar (Octopart): price breaks, stock and lifecycle.

Each client takes a manufacturer part number (or the distributor's own SKU)
and returns offers in one shape:

    {"source", "mpn", "maker", "sku", "stock", "lifecycle", "breaks": [[qty, unit price]],
     "url"}

`lifecycle` is normalised to: active | nrnd | last_time_buy | obsolete | unknown.

Untested against the live services until the keys are in place (see
deploy/RESEARCH_SETUP.md); parsing is defensive so a changed field gives an
empty offer, not a crash. Free tiers are small (Nexar: 1,000 parts a month),
so research.py budgets the calls.
"""

import os
import re
import time
import urllib.parse

from .http import client_credentials_token, request

LIFECYCLE_WORDS = (
    ("last time buy", "last_time_buy"),
    ("last-time buy", "last_time_buy"),
    ("ltb", "last_time_buy"),
    ("not recommended", "nrnd"),
    ("nrnd", "nrnd"),
    ("end of life", "obsolete"),
    ("eol", "obsolete"),
    ("obsolete", "obsolete"),
    ("discontinued", "obsolete"),
    ("active", "active"),
    ("in production", "active"),
    ("new product", "active"),
)


def normalize_lifecycle(text):
    t = (text or "").strip().lower()
    if not t:
        return "unknown"
    for word, status in LIFECYCLE_WORDS:
        if word in t:
            return status
    return "unknown"


def _money(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"[\d,]*\.?\d+", str(v))
    return float(m.group(0).replace(",", "")) if m else None


class DigiKey:
    name = "digikey"
    TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
    DETAIL_URL = "https://api.digikey.com/products/v4/search/{pn}/productdetails"

    def __init__(self, client_id, client_secret):
        self.client_id, self.client_secret = client_id, client_secret
        self._token, self._exp = None, 0

    @classmethod
    def from_env(cls):
        cid, sec = os.environ.get("DIGIKEY_CLIENT_ID"), os.environ.get("DIGIKEY_CLIENT_SECRET")
        return cls(cid, sec) if cid and sec else None

    def _auth(self):
        if not self._token or time.time() > self._exp:
            self._token = client_credentials_token(
                self.TOKEN_URL, self.client_id, self.client_secret
            )
            self._exp = time.time() + 500
        return self._token

    def lookup(self, pn):
        url = self.DETAIL_URL.format(pn=urllib.parse.quote(pn, safe=""))
        data = request(
            "GET",
            url,
            headers={
                "Authorization": f"Bearer {self._auth()}",
                "X-DIGIKEY-Client-Id": self.client_id,
                "X-DIGIKEY-Locale-Site": "US",
                "X-DIGIKEY-Locale-Currency": "USD",
            },
        )
        return parse_digikey(data)


def parse_digikey(data):
    p = (data or {}).get("Product") or {}
    if not p:
        return []
    status = (p.get("ProductStatus") or {}).get("Status") or ""
    if p.get("Discontinued"):
        status = status or "Discontinued"
    offers = []
    variations = p.get("ProductVariations") or [{}]
    for v in variations:
        breaks = [
            [float(b.get("BreakQuantity") or 0), float(b.get("UnitPrice") or 0)]
            for b in (v.get("StandardPricing") or [])
            if b.get("UnitPrice")
        ]
        offers.append(
            {
                "source": "digikey",
                "mpn": p.get("ManufacturerProductNumber") or "",
                "maker": (p.get("Manufacturer") or {}).get("Name") or "",
                "sku": v.get("DigiKeyProductNumber") or "",
                "stock": float(
                    v.get("QuantityAvailableforPackageType") or p.get("QuantityAvailable") or 0
                ),
                "lifecycle": normalize_lifecycle(status),
                "lifecycle_text": status,
                "breaks": breaks,
                "url": p.get("ProductUrl") or "",
            }
        )
    return offers


class Mouser:
    name = "mouser"
    URL = "https://api.mouser.com/api/v1/search/partnumber?apiKey={key}"

    def __init__(self, key):
        self.key = key

    @classmethod
    def from_env(cls):
        k = os.environ.get("MOUSER_API_KEY")
        return cls(k) if k else None

    def lookup(self, pn):
        data = request(
            "POST",
            self.URL.format(key=urllib.parse.quote(self.key)),
            body={"SearchByPartRequest": {"mouserPartNumber": pn, "partSearchOptions": "Exact"}},
        )
        return parse_mouser(data)


def parse_mouser(data):
    parts = ((data or {}).get("SearchResults") or {}).get("Parts") or []
    out = []
    for p in parts:
        breaks = []
        for b in p.get("PriceBreaks") or []:
            price = _money(b.get("Price"))
            if price:
                breaks.append([float(b.get("Quantity") or 0), price])
        stock = _money(p.get("AvailabilityInStock")) or _money(p.get("Availability")) or 0.0
        out.append(
            {
                "source": "mouser",
                "mpn": p.get("ManufacturerPartNumber") or "",
                "maker": p.get("Manufacturer") or "",
                "sku": p.get("MouserPartNumber") or "",
                "stock": float(stock),
                "lifecycle": normalize_lifecycle(p.get("LifecycleStatus") or "active"),
                "lifecycle_text": p.get("LifecycleStatus") or "",
                "breaks": breaks,
                "url": p.get("ProductDetailUrl") or "",
            }
        )
    return out


class Nexar:
    name = "nexar"
    TOKEN_URL = "https://identity.nexar.com/connect/token"
    URL = "https://api.nexar.com/graphql"
    QUERY = """query($q: String!) { supSearchMpn(q: $q, limit: 1) { results { part {
      mpn manufacturer { name } octopartUrl
      specs { attribute { shortname } displayValue }
      sellers(authorizedOnly: true) { company { name } offers { sku inventoryLevel
        prices { quantity price currency } } } } } } }"""

    def __init__(self, client_id, client_secret):
        self.client_id, self.client_secret = client_id, client_secret
        self._token, self._exp = None, 0

    @classmethod
    def from_env(cls):
        cid, sec = os.environ.get("NEXAR_CLIENT_ID"), os.environ.get("NEXAR_CLIENT_SECRET")
        return cls(cid, sec) if cid and sec else None

    def _auth(self):
        if not self._token or time.time() > self._exp:
            self._token = client_credentials_token(
                self.TOKEN_URL, self.client_id, self.client_secret, scope="supply.domain"
            )
            self._exp = time.time() + 3000
        return self._token

    def lookup(self, pn):
        data = request(
            "POST",
            self.URL,
            headers={"Authorization": f"Bearer {self._auth()}"},
            body={"query": self.QUERY, "variables": {"q": pn}},
        )
        return parse_nexar(data)


def parse_nexar(data):
    results = (((data or {}).get("data") or {}).get("supSearchMpn") or {}).get("results") or []
    out = []
    for r in results:
        part = r.get("part") or {}
        life = next(
            (
                s.get("displayValue")
                for s in part.get("specs") or []
                if (s.get("attribute") or {}).get("shortname") == "lifecyclestatus"
            ),
            "",
        )
        best = None
        for seller in part.get("sellers") or []:
            for o in seller.get("offers") or []:
                breaks = [
                    [float(p.get("quantity") or 0), float(p.get("price") or 0)]
                    for p in o.get("prices") or []
                    if p.get("currency") in (None, "USD")
                ]
                if not breaks:
                    continue
                cand = {
                    "source": "nexar:" + ((seller.get("company") or {}).get("name") or "?"),
                    "sku": o.get("sku") or "",
                    "stock": float(o.get("inventoryLevel") or 0),
                    "breaks": sorted(breaks),
                }
                if best is None or cand["breaks"][0][1] < best["breaks"][0][1]:
                    best = cand
        out.append(
            {
                "source": (best or {}).get("source", "nexar"),
                "mpn": part.get("mpn") or "",
                "maker": (part.get("manufacturer") or {}).get("name") or "",
                "sku": (best or {}).get("sku", ""),
                "stock": (best or {}).get("stock", 0.0),
                "lifecycle": normalize_lifecycle(life),
                "lifecycle_text": life or "",
                "breaks": (best or {}).get("breaks", []),
                "url": part.get("octopartUrl") or "",
            }
        )
    return out


def clients():
    """The distributors whose keys are set, cheapest quota last."""
    return [c for c in (DigiKey.from_env(), Mouser.from_env(), Nexar.from_env()) if c]


def price_at(breaks, qty):
    """Unit price for `qty` from [[break qty, price]]; the first break if below it."""
    brs = sorted(breaks)
    if not brs:
        return None
    price = brs[0][1]
    for q, p in brs:
        if qty >= q:
            price = p
    return price

import json
from types import SimpleNamespace

from pkmrp.integrations import ai
from pkmrp.integrations.distributors import (
    normalize_lifecycle,
    parse_digikey,
    parse_mouser,
    parse_nexar,
    price_at,
)
from pkmrp.integrations.mailbox import html_to_text, looks_like_notice


def test_lifecycle_words():
    assert normalize_lifecycle("Not Recommended for New Designs") == "nrnd"
    assert normalize_lifecycle("Last Time Buy") == "last_time_buy"
    assert normalize_lifecycle("Obsolete") == "obsolete"
    assert normalize_lifecycle("Active") == "active"
    assert normalize_lifecycle("") == "unknown"


def test_parsers_tolerate_the_documented_shapes_and_empty_replies():
    dk = parse_digikey(
        {
            "Product": {
                "ManufacturerProductNumber": "OPA699ID",
                "Manufacturer": {"Name": "TI"},
                "ProductStatus": {"Status": "Obsolete"},
                "ProductVariations": [
                    {
                        "DigiKeyProductNumber": "296-1",
                        "StandardPricing": [
                            {"BreakQuantity": 1, "UnitPrice": 6.1},
                            {"BreakQuantity": 10, "UnitPrice": 5.2},
                        ],
                    }
                ],
            }
        }
    )
    assert dk[0]["lifecycle"] == "obsolete" and dk[0]["breaks"][1] == [10.0, 5.2]
    mo = parse_mouser(
        {
            "SearchResults": {
                "Parts": [
                    {
                        "ManufacturerPartNumber": "X",
                        "LifecycleStatus": "End of Life",
                        "AvailabilityInStock": "1,234",
                        "PriceBreaks": [{"Quantity": 1, "Price": "$1,234.50"}],
                    }
                ]
            }
        }
    )
    assert (
        mo[0]["lifecycle"] == "obsolete"
        and mo[0]["breaks"] == [[1.0, 1234.5]]
        and mo[0]["stock"] == 1234
    )
    nx = parse_nexar(
        {
            "data": {
                "supSearchMpn": {
                    "results": [
                        {
                            "part": {
                                "mpn": "Y",
                                "specs": [
                                    {
                                        "attribute": {"shortname": "lifecyclestatus"},
                                        "displayValue": "NRND",
                                    }
                                ],
                                "sellers": [
                                    {
                                        "company": {"name": "Arrow"},
                                        "offers": [
                                            {
                                                "inventoryLevel": 5,
                                                "prices": [
                                                    {"quantity": 1, "price": 2.0, "currency": "USD"}
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        }
                    ]
                }
            }
        }
    )
    assert nx[0]["lifecycle"] == "nrnd" and nx[0]["source"] == "nexar:Arrow"
    assert parse_digikey({}) == [] and parse_mouser({}) == [] and parse_nexar({}) == []
    assert price_at([[1, 6.1], [10, 5.2]], 25) == 5.2 and price_at([[10, 5.2]], 3) == 5.2


def test_mail_filter_and_text():
    assert looks_like_notice("PCN 2026-114: die shrink", "")
    assert looks_like_notice("Update", "This product will be discontinued. Last time buy date ...")
    assert not looks_like_notice("Your order has shipped", "Tracking number 1Z...")
    assert html_to_text("<p>Hello&nbsp;<b>there</b></p><style>x{}</style>") == "Hello there"


class FakeClient:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=json.dumps(self.reply))],
        )


def test_read_notice_sends_schema_and_fallback():
    reply = {
        "is_notice": True,
        "kind": "eol",
        "maker": "TI",
        "part_numbers": ["OPA699ID"],
        "last_order_date": "2026-12-15",
        "last_ship_date": "",
        "replacements": [],
        "summary": "EOL",
    }
    fc = FakeClient(reply)
    out = ai.read_notice({"subject": "PDN", "text": "body", "sender": "a@ti.com"}, fc)
    assert out == reply
    kw = fc.calls[0]
    assert kw["model"] == ai.MODEL and kw["fallbacks"] == "default"
    assert kw["output_config"]["format"]["type"] == "json_schema"

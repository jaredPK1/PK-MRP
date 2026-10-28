"""core/search.py: find parts by number fragments or description words."""

from pkmrp.core.search import find, score, squash

CAT = [
    ("46-0020-01G", "LENS, 1X RELAY, 1350NM_59420", "B", True),
    ("46-0020-02G", "LENS, 1X RELAY, 1550NM", "B", False),
    ("07-0694-00G", "Z-STAGE ASSY, 2300", "A", True),
    ("29-0764-00G", "CABLE ASSY,2300, OPTICAL SWITCH 8.5IN", "B", True),
    ("31-7100-01SG", "IC, XC7A100T-2FTG256C XILINX FPGA IO", "B", True),
    ("02-3346-05G", "ECB ASSY, MAINBOARD, USB 800", "B", False),
]


def parts(q, n=5):
    return [p for p, *_ in find(q, CAT, n)]


def test_part_numbers_with_or_without_dashes():
    assert squash("46-0020-01G") == "46002001g"
    assert parts("46-0020-01G")[0] == "46-0020-01G"
    assert parts("46002001")[0] == "46-0020-01G"
    assert parts("46-0020")[:2] == ["46-0020-01G", "46-0020-02G"]  # active one first


def test_description_words_any_order_and_case():
    assert parts("relay lens") == ["46-0020-01G", "46-0020-02G"]
    assert parts("Lens Relay 1550") == ["46-0020-02G"]
    assert parts("fpga") == ["31-7100-01SG"]


def test_aliases_and_numbers_inside_descriptions():
    assert parts("2300 z stage assembly") == ["07-0694-00G"]
    assert parts("2300 cable") == ["29-0764-00G"]
    assert parts("main boards") == ["02-3346-05G"]


def test_every_word_has_to_match():
    assert parts("relay fpga") == []
    assert score("X", "LENS", "") == 0

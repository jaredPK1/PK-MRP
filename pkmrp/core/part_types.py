"""Read MAX's part type (TYPE_01) the way PK-MRP plans it.

MAX only plans A (make) and B (buy). Parts typed S (sub-assemblies built on
work orders) and O (bought parts with a small BOM) were reported as "not
planned" -- and nothing below them was planned either. This maps them onto
make and buy once, where parts are loaded, so every later step (netting,
ATP, segments, sourcing) sees one consistent type. Phantoms (P) keep their
type; netting passes their demand through to their BOM.

A few parts are simply typed wrong in MAX (settings.type_overrides). They are
planned as the right type and listed so someone corrects MAX. Pure.
"""


def normalize(parts_df, settings):
    """(parts_df with `type` as planned and `max_type` as MAX has it,
    [{part, description, max_type, planned_as, why}] overrides to fix in MAX)."""
    out = parts_df.copy()
    out["max_type"] = out["type"]
    mapping = dict(settings.type_map)
    out["type"] = out["type"].map(lambda t: mapping.get(t, t))
    fixes = []
    known = set(out["part"])
    for part, planned_as, why in settings.type_overrides:
        if part not in known:
            continue
        row = out.index[out["part"] == part][0]
        max_type = out.at[row, "max_type"]
        if max_type == planned_as:  # MAX has been corrected: nothing to do
            continue
        out.at[row, "type"] = planned_as
        fixes.append(
            {
                "part": part,
                "description": out.at[row, "description"],
                "max_type": max_type,
                "planned_as": planned_as,
                "why": why,
            }
        )
    return out, fixes

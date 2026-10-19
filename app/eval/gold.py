"""Known-good expected quantities for the sample projects.

These numbers are the reference ("gold") the scorer measures a run against. They
are taken from the reviewed manual/ChatGPT takeoffs of each plan set. Areas and
linear runs allow a relative tolerance; counts allow being off by one, since a
single smoke-alarm symbol is easy to miss. Update a number here only when the
drawing, not the app, proves it wrong - the gold must stay independent of what
the app currently outputs, or the score becomes meaningless.
"""

from __future__ import annotations

from app.eval.scorer import GoldItem


_COUNT = dict(unit="ea", tol=0.0, abs_tol=1.0)

# Shared exclusions so a broad area keyword matches only the thing itself.
_SLAB_X = ("reinforc", "vapor", "barrier", "sand", "base", "screed", "footing", "dowel")
_FOOTING_X = ("rebar", "reinforc", "pad", "dowel", "hold")
_ROOF_X = ("underlayment", "sheathing", "vent", "framing", "rafter",
           "insulation", "ridge", "gutter", "downspout")


EL_SERENO: list[GoldItem] = [
    GoldItem("footings", "Continuous footings", "ft", 231.92, ("footing",), exclude=_FOOTING_X),
    GoldItem("slab", "Slab-on-grade (house+garage+porch)", "sqft", 1623.75, ("slab",), exclude=_SLAB_X),
    GoldItem("roof", "Sloped roof covering", "sqft", 2066.84, ("shingle", "roofing", "sloped roof"), exclude=_ROOF_X),
    GoldItem("stucco", "Exterior stucco, net", "sqft", 1502.75, ("stucco",)),
    GoldItem("drywall", "Drywall / gypsum board", "sqft", 5081.75, ("drywall", "gypsum")),
    GoldItem("wall_framing", "Wall framing one face", "sqft", 3126.75, ("wall framing",)),
    GoldItem("ceiling_framing", "Ceiling framing area", "sqft", 1623.75, ("ceiling",)),
    GoldItem("flooring", "Floor coverings", "sqft", 1069.08, ("flooring", "floor covering")),
    GoldItem("windows", "Windows", expected=7, keywords=("window",), **_COUNT),
    GoldItem("water_closets", "Water closets", expected=2, keywords=("water closet", "toilet", " wc"), **_COUNT),
    GoldItem("showers", "Showers", expected=2, keywords=("shower",), **_COUNT),
    GoldItem("kitchen_sink", "Kitchen sink", expected=1, keywords=("kitchen sink",), **_COUNT),
    GoldItem("water_heater", "Water heater", expected=1, keywords=("water heater",), **_COUNT),
    GoldItem("hvac", "HVAC system", expected=1, keywords=("heat pump", "mini-split", "mini split", "fau", "hvac"), **_COUNT),
    GoldItem("exhaust_fans", "Exhaust fans", expected=2, keywords=("exhaust fan", "bath fan"), **_COUNT),
    GoldItem("range_hood", "Range hood", expected=1, keywords=("hood",), **_COUNT),
    GoldItem("smoke", "Smoke alarms", expected=4, keywords=("smoke",), **_COUNT),
    GoldItem("co", "Carbon monoxide alarms", expected=4, keywords=("carbon monoxide", "co detector", "co alarm"), **_COUNT),
    GoldItem("service", "Electrical service / panel", expected=1, keywords=("service", "panel"), **_COUNT),
]


ALTADENA: list[GoldItem] = [
    GoldItem("footings", "Continuous footings", "ft", 418.17, ("footing",), exclude=_FOOTING_X),
    GoldItem("slab", "Slab-on-grade (house+garage+porch)", "sqft", 2560.0, ("slab",), exclude=_SLAB_X),
    GoldItem("roof", "Sloped roof covering", "sqft", 3106.94, ("shingle", "roofing", "sloped roof"), exclude=_ROOF_X),
    GoldItem("stucco", "Exterior stucco, net", "sqft", 2129.67, ("stucco",)),
    GoldItem("drywall", "Drywall / gypsum board", "sqft", 6816.0, ("drywall", "gypsum")),
    GoldItem("wall_framing", "Wall framing one face", "sqft", 4451.0, ("wall framing",)),
    GoldItem("ceiling_framing", "Ceiling joist area", "sqft", 2426.0, ("ceiling",)),
    GoldItem("flooring", "Floor coverings", "sqft", 1855.0, ("flooring", "floor covering")),
    GoldItem("receptacles", "Receptacles", expected=63, keywords=("receptacle",), unit="ea", tol=0.1, abs_tol=2.0),
    GoldItem("recessed_led", "Recessed LED fixtures", expected=44, keywords=("recessed", "led"), unit="ea", tol=0.1, abs_tol=2.0),
    GoldItem("water_closets", "Water closets", expected=2, keywords=("water closet", "toilet"), **_COUNT),
    GoldItem("water_heater", "Water heater", expected=1, keywords=("water heater",), **_COUNT),
    GoldItem("hvac", "Heat pump system", expected=1, keywords=("heat pump", "mini-split", "hvac"), **_COUNT),
    GoldItem("exhaust_fans", "Exhaust fans", expected=4, keywords=("exhaust fan", "bath fan"), **_COUNT),
    GoldItem("smoke", "Smoke alarms", expected=5, keywords=("smoke",), **_COUNT),
    GoldItem("co", "Carbon monoxide alarms", expected=2, keywords=("carbon monoxide", "co detector", "co alarm"), **_COUNT),
    GoldItem("service", "Electrical service / panel", expected=1, keywords=("service", "panel"), **_COUNT),
]


# 11653 Rivera Rd is a 563 SF addition + remodel, so the gold is addition scope.
RIVERA: list[GoldItem] = [
    GoldItem("footings", "Continuous/thickened footings", "ft", 125.1, ("footing",), tol=0.15, exclude=_FOOTING_X),
    GoldItem("slab", "New foundation slab", "sqft", 563.0, ("slab",), exclude=_SLAB_X),
    GoldItem("wall_framing", "Wall framing one face", "sqft", 1276.0, ("wall framing", "framed wall")),
    GoldItem("drywall", "Drywall / gypsum board", "sqft", 2158.67, ("drywall", "gypsum")),
    GoldItem("stucco", "Exterior stucco, net", "sqft", 556.0, ("stucco",)),
    GoldItem("roofing", "Addition sloped roof", "sqft", 655.42, ("roof", "shingle", "roofing"), tol=0.15, exclude=_ROOF_X),
    GoldItem("ceiling_joist", "Ceiling joist coverage", "sqft", 563.0, ("ceiling",)),
    GoldItem("flooring", "Addition floor coverings", "sqft", 525.0, ("floor",)),
    GoldItem("wall_insulation", "R-13 wall insulation", "sqft", 556.0, ("insulation",)),
    GoldItem("windows", "New windows", expected=6, keywords=("window",), unit="ea", tol=0.0, abs_tol=1.0),
    GoldItem("doors", "New hinged doors", expected=6, keywords=("hinged door", " door"), unit="ea", tol=0.0, abs_tol=1.0),
    GoldItem("water_closets", "Water closets", expected=2, keywords=("water closet", "toilet"), **_COUNT),
    GoldItem("showers", "Showers", expected=2, keywords=("shower",), **_COUNT),
    GoldItem("water_heater", "Tankless water heater", expected=1, keywords=("water heater",), **_COUNT),
    GoldItem("furnace", "Gas furnace", expected=1, keywords=("furnace",), **_COUNT),
    GoldItem("ac", "Split AC system", expected=1, keywords=("split ac", "ac system", "air condition", "conditioning"), **_COUNT),
    GoldItem("bath_fans", "Bathroom exhaust fans", expected=2, keywords=("bath exhaust", "bathroom fan", "bath fan", "bathroom exhaust"), **_COUNT),
    GoldItem("smoke", "Smoke alarms", expected=2, keywords=("smoke",), **_COUNT),
    GoldItem("co", "Carbon monoxide alarms", expected=1, keywords=("carbon monoxide", "co alarm"), **_COUNT),
]


PROJECTS: dict[str, list[GoldItem]] = {
    "el_sereno": EL_SERENO,
    "altadena": ALTADENA,
    "rivera": RIVERA,
}

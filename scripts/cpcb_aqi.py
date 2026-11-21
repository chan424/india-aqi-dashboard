"""CPCB National Air Quality Index sub-index calculation.

Breakpoints follow CPCB's published table (How AQI is Calculated; CUPS/82
Table 3.11). Concentrations are truncated before the lookup, which is how
CPCB's own examples land on integers: PM2.5 of 31 µg/m³ → 51, 45 → 75,
60 → 100.

The Severe band has no published upper concentration. The upper end used
here is the top of the Very Poor band plus the width of that band, so the
Severe slope matches the slope of Very Poor and AQI reaches 500 at a finite
concentration (PM2.5 380 µg/m³, PM10 510 µg/m³). Values above that cap at 500.
"""

from __future__ import annotations

import math

# (BPLo, BPHi, ILo, IHi). Units: µg/m³ except CO, which is mg/m³.
BREAKPOINTS = {
    "pm25": (
        (0, 30, 0, 50),
        (31, 60, 51, 100),
        (61, 90, 101, 200),
        (91, 120, 201, 300),
        (121, 250, 301, 400),
        (251, 380, 401, 500),
    ),
    "pm10": (
        (0, 50, 0, 50),
        (51, 100, 51, 100),
        (101, 250, 101, 200),
        (251, 350, 201, 300),
        (351, 430, 301, 400),
        (431, 510, 401, 500),
    ),
    "no2": (
        (0, 40, 0, 50),
        (41, 80, 51, 100),
        (81, 180, 101, 200),
        (181, 280, 201, 300),
        (281, 400, 301, 400),
        (401, 520, 401, 500),
    ),
    "o3": (
        (0, 50, 0, 50),
        (51, 100, 51, 100),
        (101, 168, 101, 200),
        (169, 208, 201, 300),
        (209, 748, 301, 400),
        (749, 1288, 401, 500),
    ),
    "co": (
        (0.0, 1.0, 0, 50),
        (1.1, 2.0, 51, 100),
        (2.1, 10.0, 101, 200),
        (10.1, 17.0, 201, 300),
        (17.1, 34.0, 301, 400),
        (34.1, 51.0, 401, 500),
    ),
    "so2": (
        (0, 40, 0, 50),
        (41, 80, 51, 100),
        (81, 380, 101, 200),
        (381, 800, 201, 300),
        (801, 1600, 301, 400),
        (1601, 2400, 401, 500),
    ),
    "nh3": (
        (0, 200, 0, 50),
        (201, 400, 51, 100),
        (401, 800, 101, 200),
        (801, 1200, 201, 300),
        (1201, 1800, 301, 400),
        (1801, 2400, 401, 500),
    ),
}

POLLUTANT_META = {
    "pm25": {"label": "PM2.5", "unit": "µg/m³", "average": "24-hour"},
    "pm10": {"label": "PM10", "unit": "µg/m³", "average": "24-hour"},
    "no2": {"label": "NO2", "unit": "µg/m³", "average": "24-hour"},
    "o3": {"label": "O3", "unit": "µg/m³", "average": "8-hour"},
    "co": {"label": "CO", "unit": "mg/m³", "average": "8-hour"},
    "so2": {"label": "SO2", "unit": "µg/m³", "average": "24-hour"},
    "nh3": {"label": "NH3", "unit": "µg/m³", "average": "24-hour"},
}

CATEGORIES = (
    (50, "Good"),
    (100, "Satisfactory"),
    (200, "Moderate"),
    (300, "Poor"),
    (400, "Very Poor"),
    (10_000, "Severe"),
)


def truncate_concentration(pollutant: str, value: float) -> float:
    if pollutant == "co":
        return math.floor(value * 10.0 + 1e-9) / 10.0
    return float(math.floor(value + 1e-9))


def sub_index(pollutant: str, concentration: float | None) -> float | None:
    if concentration is None or concentration != concentration:
        return None
    if concentration < 0:
        return None
    bands = BREAKPOINTS[pollutant]
    c = truncate_concentration(pollutant, concentration)
    if c <= bands[0][0]:
        return 0.0
    for blo, bhi, ilo, ihi in bands:
        if c < blo:
            # Gap of one truncated step between published bands: use the next band's floor.
            return float(ilo)
        if c <= bhi:
            if bhi == blo:
                return float(ilo)
            return ((ihi - ilo) / (bhi - blo)) * (c - blo) + ilo
    blo, bhi, ilo, ihi = bands[-1]
    slope = (ihi - ilo) / (bhi - blo)
    return min(500.0, slope * (c - blo) + ilo)


def category_of(aqi: float | None) -> str | None:
    if aqi is None:
        return None
    rounded = int(round(aqi))
    for limit, name in CATEGORIES:
        if rounded <= limit:
            return name
    return "Severe"


def aqi_from_concentrations(values: dict) -> dict:
    """Worst sub-index. `values` keys are pm25, pm10, no2, o3, co, so2, nh3."""
    pieces = []
    for key, conc in values.items():
        if key not in BREAKPOINTS:
            continue
        ip = sub_index(key, conc)
        if ip is None:
            continue
        pieces.append({"pollutant": key, "concentration": conc, "sub_index": ip})
    if not pieces:
        return {
            "aqi": None,
            "category": None,
            "dominant": None,
            "sub_indices": [],
            "official_minimum_met": False,
        }
    pieces.sort(key=lambda p: p["sub_index"], reverse=True)
    worst = pieces[0]
    keys = {p["pollutant"] for p in pieces}
    official = len(keys) >= 3 and (("pm25" in keys) or ("pm10" in keys))
    aqi = worst["sub_index"]
    return {
        "aqi": aqi,
        "aqi_rounded": int(round(aqi)),
        "category": category_of(aqi),
        "dominant": worst["pollutant"],
        "sub_indices": pieces,
        "official_minimum_met": official,
    }


def _self_test() -> None:
    def r(v):
        return int(round(sub_index("pm25", v)))

    assert r(31) == 51, r(31)
    assert r(45) == 75, r(45)
    assert r(60) == 100, r(60)
    assert r(30) == 50, r(30)
    assert r(0) == 0
    assert category_of(50) == "Good"
    assert category_of(51) == "Satisfactory"
    assert category_of(101) == "Moderate"
    assert sub_index("pm25", 500) == 500


if __name__ == "__main__":
    _self_test()
    print("cpcb_aqi self-test ok")

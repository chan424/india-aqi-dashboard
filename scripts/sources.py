"""Parsers for the public station list and the CPCB daily bulletin PDF."""

from __future__ import annotations

import csv
import re
from pathlib import Path

STATE_RE = re.compile(r"^(.+?)\s+[—–-]\s+(\d+)\s+stations?$", re.I)
CODE_RE = re.compile(r"^#(\d+)$")
HEADER_LINES = {
    "city",
    "station name",
    "operating agency",
    "latitude",
    "longitude",
    "code",
}
BULLETIN_RE = re.compile(
    r"^\s*(\d+)\s+(.+?)\s+"
    r"(Good|Satisfactory|Moderate|Moderately Polluted|Poor|Very Poor|Severe)\s+"
    r"(\d+)\s+(.+?)\s+(\d+)\s*/\s*(\d+)\s*$"
)
ALIASES = {
    "new delhi": "delhi",
    "delhi ncr": "delhi",
    "bangalore": "bengaluru",
    "bengaluru urban": "bengaluru",
    "bombay": "mumbai",
    "greater mumbai": "mumbai",
    "calcutta": "kolkata",
    "madras": "chennai",
    "gurgaon": "gurugram",
    "allahabad": "prayagraj",
    "baroda": "vadodara",
    "trivandrum": "thiruvananthapuram",
    "pondicherry": "puducherry",
    "rajahmundry": "rajamahendravaram",
    "vizag": "visakhapatnam",
    "cuddapah": "kadapa",
    "ysr kadapa": "kadapa",
    "kadapa ysr": "kadapa",
    "sri potti sriramulu nellore": "nellore",
    "nellore spsr": "nellore",
    "aurangabad": "aurangabad maharashtra",
}


def norm_place(value: str) -> str:
    text = (value or "").lower().replace("&", " and ")
    cleaned = "".join(ch if ch.isalnum() else " " for ch in text)
    key = " ".join(cleaned.split())
    return ALIASES.get(key, key)


DATE_RE = re.compile(
    r"Air Quality Index on\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", re.I
)
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _float(text: str):
    try:
        return float(text)
    except ValueError:
        return None


def parse_cpcb_station_pdf_text(text: str) -> list[dict]:
    """Parse pdftotext-style CPCB 'List of CAAQM Stations — All India'."""
    state = None
    buf: list[str] = []
    rows: list[dict] = []

    def flush(code: str) -> None:
        nonlocal buf
        if len(buf) < 4 or state is None:
            buf = []
            return
        lon = _float(buf[-1])
        lat = _float(buf[-2])
        if lat is None or lon is None:
            buf = []
            return
        agency = buf[-3]
        rest = buf[:-3]
        if not rest:
            buf = []
            return
        city = rest[0]
        name = " ".join(rest[1:]).replace("  ", " ").strip() or city
        if not (6.0 <= lat <= 37.5 and 67.0 <= lon <= 98.5):
            buf = []
            return
        rows.append(
            {
                "id": f"site_{code}",
                "name": name,
                "city": city,
                "state": state,
                "agency": agency,
                "lat": lat,
                "lon": lon,
                "coord_source": "CPCB CAAQMS list PDF",
                "coord_url": "https://app.cpcbccr.com/ccr_docs/caaqms_list_All_India.pdf",
            }
        )
        buf = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low in HEADER_LINES or low.startswith("list of caaqm") or low.startswith("source:"):
            continue
        if low.startswith("continuous ambient") or low.startswith("central pollution"):
            continue
        if low.startswith("this document") or low.startswith("territories of india"):
            continue
        if low.startswith("quality data") or low.startswith("pollution control committees"):
            continue
        if low.startswith("note:") or low.startswith("form site_"):
            continue
        state_match = STATE_RE.match(line)
        if state_match and _float(line.split()[0]) is None:
            state = state_match.group(1).strip()
            buf = []
            continue
        code_match = CODE_RE.match(line)
        if code_match:
            flush(code_match.group(1))
            continue
        buf.append(line)
    return rows


def parse_cpcb_station_pdf(path: Path) -> list[dict]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return parse_cpcb_station_pdf_text(text)


def load_xkdr_stations(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        for record in csv.DictReader(handle):
            lat = _float(record.get("latitude") or "")
            lon = _float(record.get("longitude") or "")
            if lat is None or lon is None:
                continue
            if not (6.0 <= lat <= 37.5 and 67.0 <= lon <= 98.5):
                continue
            rows.append(
                {
                    "id": record["station_id"].strip(),
                    "name": record["station_name"].strip(),
                    "city": record["city_name"].strip(),
                    "state": record["state_name"].strip(),
                    "agency": "US Department of State / AirNow" if record["station_id"].startswith("DS") else "",
                    "lat": lat,
                    "lon": lon,
                    "last_seen": (record.get("last_seen") or "")[:10],
                    "source_network": record.get("source") or "",
                    "coord_source": "XKDR Forum India Air Quality Database station directory (exported 2026-09-30)",
                    "coord_url": "https://airquality.xkdr.org/",
                }
            )
    return rows


def parse_bulletin_text(text: str) -> dict:
    date = None
    found = DATE_RE.search(text)
    if found:
        month = MONTHS[found.group(1)[:3].lower()]
        date = f"{int(found.group(3)):04d}-{month:02d}-{int(found.group(2)):02d}"
    cities = []
    for line in text.splitlines():
        match = BULLETIN_RE.match(line.strip())
        if not match:
            continue
        category = match.group(3)
        if category == "Moderately Polluted":
            category = "Moderate"
        cities.append(
            {
                "sno": int(match.group(1)),
                "city": match.group(2).strip(),
                "category": category,
                "aqi": int(match.group(4)),
                "prominent_pollutant": match.group(5).strip(),
                "stations_participated": int(match.group(6)),
                "stations_total": int(match.group(7)),
            }
        )
    return {"date": date, "cities": cities}


def parse_bulletin_pdf(path: Path) -> dict:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    parsed = parse_bulletin_text(text)
    parsed["source_file"] = Path(path).name
    return parsed

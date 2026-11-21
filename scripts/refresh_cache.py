#!/usr/bin/env python3
"""Refresh the live cache: CPCB bulletin, optional station feed, Open-Meteo estimates.

No API key. Safe to run every hour. If a source fails, the previous file is kept
and meta.json records the failure.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from live_estimate import (  # noqa: E402
    OPEN_METEO_AQ,
    OPEN_METEO_WX,
    estimate_place,
    haversine_km,
)
from sources import norm_place, parse_bulletin_pdf  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30))
UA = "RGUKT-Ongole-AQI-Observatory/1.0 (static research dashboard)"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch(url, timeout=40, method="GET", data=None, headers=None):
    hdrs = {"User-Agent": UA, "Accept": "application/json,application/pdf,*/*"}
    if headers:
        hdrs.update(headers)
    request = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "")


def load_json(path, default=None):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def try_bulletin():
    today = datetime.now(IST).date()
    last_error = "not attempted"
    for offset in range(0, 5):
        day = today - timedelta(days=offset)
        stamp = day.strftime("%Y%m%d")
        url = f"https://cpcb.gov.in/upload/Downloads/AQI_Bulletin_{stamp}.pdf"
        try:
            body, _ = fetch(url, timeout=40)
        except Exception as exc:  # noqa: BLE001
            last_error = f"{stamp}: {exc}"
            continue
        if not body.startswith(b"%PDF"):
            last_error = f"{stamp}: not a pdf ({len(body)} bytes)"
            continue
        target = ROOT / "data" / "cache" / "latest_bulletin.pdf"
        target.write_bytes(body)
        parsed = parse_bulletin_pdf(target)
        if not parsed.get("date") or len(parsed.get("cities") or []) < 50:
            last_error = f"{stamp}: parsed {len(parsed.get('cities') or [])} cities"
            continue
        parsed["source_url"] = url
        return parsed, None
    return None, last_error


def try_rss():
    url = "https://airquality.cpcb.gov.in/caaqms/iit_rss_feed_with_coordinates"
    try:
        body, _ = fetch(url, timeout=18)
        data = json.loads(body.decode("utf-8", errors="replace"))
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)
    rows = []
    country = data.get("country") or data.get("Country") or []
    if isinstance(data, list):
        country = data
    for state in country if isinstance(country, list) else []:
        state_name = state.get("stateName") or state.get("stateId") or state.get("state") or ""
        cities = state.get("citiesInState") or state.get("cities") or []
        for city in cities:
            city_name = city.get("cityName") or city.get("cityId") or city.get("city") or ""
            for station in city.get("stationsInCity") or city.get("stations") or []:
                try:
                    lat = float(station.get("latitude"))
                    lon = float(station.get("longitude"))
                except (TypeError, ValueError):
                    continue
                aqi_obj = station.get("airQualityIndex") or {}
                raw = station.get("airQualityIndexValue", aqi_obj.get("value", aqi_obj.get("Value")))
                try:
                    aqi = float(raw)
                except (TypeError, ValueError):
                    aqi = None
                rows.append(
                    {
                        "id": str(station.get("siteId") or station.get("id") or station.get("stationName")),
                        "name": station.get("stationName") or station.get("name") or "",
                        "city": city_name,
                        "state": state_name,
                        "lat": lat,
                        "lon": lon,
                        "aqi": None if aqi is None else int(round(aqi)),
                        "last_update": station.get("lastUpdate") or "",
                    }
                )
    if len(rows) < 20:
        return None, f"feed returned {len(rows)} stations"
    return rows, None


def batches(items, size):
    for index in range(0, len(items), size):
        yield items[index : index + size]


def fetch_open_meteo(places):
    aq_by_key = {}
    wx_by_key = {}
    errors = []
    for group in batches(places, 20):
        lats = ",".join(f"{p['lat']:.4f}" for p in group)
        lons = ",".join(f"{p['lon']:.4f}" for p in group)
        aq_url = (
            f"{OPEN_METEO_AQ}?latitude={lats}&longitude={lons}"
            "&hourly=pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide"
            "&timezone=Asia%2FKolkata&forecast_days=2&past_days=1"
        )
        wx_url = (
            f"{OPEN_METEO_WX}?latitude={lats}&longitude={lons}"
            "&hourly=relative_humidity_2m,wind_speed_10m,precipitation,boundary_layer_height"
            "&wind_speed_unit=ms&timezone=Asia%2FKolkata&forecast_days=2&past_days=1"
        )
        try:
            aq_body, _ = fetch(aq_url, timeout=60)
            wx_body, _ = fetch(wx_url, timeout=60)
            aq = json.loads(aq_body)
            wx = json.loads(wx_body)
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            continue
        if isinstance(aq, dict):
            aq = [aq]
        if isinstance(wx, dict):
            wx = [wx]
        for place, aq_row, wx_row in zip(group, aq, wx):
            key = place["id"]
            hourly = aq_row.get("hourly") or {}
            weather = wx_row.get("hourly") or {}
            aq_by_key[key] = {
                "pm25": hourly.get("pm2_5"),
                "pm10": hourly.get("pm10"),
                "no2": hourly.get("nitrogen_dioxide"),
                "o3": hourly.get("ozone"),
                "so2": hourly.get("sulphur_dioxide"),
                "co_ug": hourly.get("carbon_monoxide"),
                "rh": weather.get("relative_humidity_2m"),
                "wind_ms": weather.get("wind_speed_10m"),
                "rain": weather.get("precipitation"),
                "blh": weather.get("boundary_layer_height"),
                "time": hourly.get("time"),
            }
            wx_by_key[key] = wx_row.get("current")
    return aq_by_key, errors


def nearest(place, stations):
    best = None
    for station in stations:
        dist = haversine_km(place["lat"], place["lon"], station["lat"], station["lon"])
        if best is None or dist < best[0]:
            best = (dist, station)
    return best


def apply_bulletin_to_stations(bulletin):
    path = ROOT / "data" / "maps" / "stations.geojson"
    geo = load_json(path)
    if not geo:
        return 0
    by_city = {}
    for city in bulletin["cities"]:
        by_city.setdefault(norm_place(city["city"]), city)
    matched = 0
    for feature in geo["features"]:
        props = feature["properties"]
        hit = by_city.get(norm_place(props.get("city") or ""))
        if hit is None:
            props["bulletin_aqi"] = None
            props["aqi_colour_kind"] = "none"
            props["aqi_for_colour"] = None
            continue
        props["bulletin_aqi"] = hit["aqi"]
        props["bulletin_category"] = hit["category"]
        props["bulletin_pollutant"] = hit["prominent_pollutant"]
        props["bulletin_date"] = bulletin["date"]
        props["bulletin_stations"] = f"{hit['stations_participated']}/{hit['stations_total']}"
        props["aqi_for_colour"] = hit["aqi"]
        props["aqi_colour_kind"] = "measured_city_bulletin"
        matched += 1
    save_json(path, geo)
    save_json(
        ROOT / "data" / "cache" / "bulletin_latest.json",
        {
            "date": bulletin["date"],
            "source": "CPCB national daily AQI bulletin PDF",
            "source_url": bulletin.get("source_url"),
            "cities": bulletin["cities"],
            "note": "City-level measured AQI. It is not a reading from each individual station.",
        },
    )
    return matched


def apply_rss(rows):
    """Station-level AQI from the CPCB feed overrides the city bulletin colour when present."""
    path = ROOT / "data" / "maps" / "stations.geojson"
    geo = load_json(path)
    if not geo:
        return 0
    by_id = {row["id"]: row for row in rows}
    # also match site_N against a bare N
    for row in rows:
        if row["id"].isdigit():
            by_id["site_" + row["id"]] = row
    matched = 0
    for feature in geo["features"]:
        props = feature["properties"]
        hit = by_id.get(str(props.get("id")))
        if hit is None or hit.get("aqi") is None:
            continue
        props["station_aqi"] = hit["aqi"]
        props["station_aqi_time"] = hit.get("last_update") or ""
        props["aqi_for_colour"] = hit["aqi"]
        props["aqi_colour_kind"] = "measured_station_feed"
        matched += 1
    save_json(path, geo)
    return matched


def main():
    meta = load_json(ROOT / "data" / "cache" / "meta.json", {}) or {}
    meta["refresh_started"] = now_iso()
    bulletin, bulletin_error = try_bulletin()
    if bulletin:
        matched = apply_bulletin_to_stations(bulletin)
        meta["bulletin_date"] = bulletin["date"]
        meta["bulletin_cities"] = len(bulletin["cities"])
        meta["bulletin_stations_coloured"] = matched
        meta["bulletin_error"] = None
        print(f"bulletin {bulletin['date']} coloured {matched}")
    else:
        meta["bulletin_error"] = bulletin_error
        print("bulletin failed", bulletin_error)

    rss_rows, rss_error = try_rss()
    if rss_rows:
        matched = apply_rss(rss_rows)
        meta["rss_status"] = f"ok ({len(rss_rows)} stations, {matched} matched)"
        print(meta["rss_status"])
    else:
        meta["rss_status"] = "unavailable: " + (rss_error or "")
        print("rss", meta["rss_status"])

    calibration = load_json(ROOT / "data" / "cache" / "calibration.json", {})
    cities = load_json(ROOT / "data" / "cities.json", {"places": []})
    places = cities.get("places") or []
    geo = load_json(ROOT / "data" / "maps" / "stations.geojson", {"features": []})
    stations = []
    for feature in geo["features"]:
        lon, lat = feature["geometry"]["coordinates"]
        props = feature["properties"]
        stations.append({"lat": lat, "lon": lon, "name": props.get("name"), "city": props.get("city"), "bulletin_aqi": props.get("bulletin_aqi"), "bulletin_date": props.get("bulletin_date"), "state": props.get("state")})

    bulletin_doc = load_json(ROOT / "data" / "cache" / "bulletin_latest.json", {"cities": []})
    by_city = {norm_place(city["city"]): city for city in bulletin_doc.get("cities") or []}

    hourly_map, errors = fetch_open_meteo(places)
    estimates = []
    for place in places:
        hourly = hourly_map.get(place["id"])
        if not hourly:
            estimates.append({**{k: place.get(k) for k in ("id", "name", "state", "kind", "lat", "lon")}, "label": "Estimated (model)", "aqi": None, "error": "Open-Meteo returned no row"})
            continue
        est = estimate_place(place, hourly, calibration, [])
        near = nearest(place, stations)
        if near:
            est["nearest_monitor_km"] = round(near[0], 1)
            est["nearest_monitor"] = near[1]["name"]
            est["nearest_city"] = near[1]["city"]
            est["nearest_bulletin_aqi"] = near[1]["bulletin_aqi"]
            est["nearest_bulletin_date"] = near[1]["bulletin_date"]
        measured = by_city.get(norm_place(place["name"]))
        if measured:
            est["measured_aqi"] = measured["aqi"]
            est["measured_category"] = measured["category"]
            est["measured_pollutant"] = measured["prominent_pollutant"]
            est["measured_date"] = bulletin_doc.get("date")
            est["measured_label"] = "Measured (monitor)"
            est["measured_detail"] = (
                f"CPCB city bulletin for {measured['city']} on {bulletin_doc.get('date')} "
                f"({measured['stations_participated']}/{measured['stations_total']} stations). "
                "This is the city value, not a reading taken at the map coordinate."
            )
        rmse = (calibration.get("uncertainty") or {}).get("test_2025_rmse_aqi")
        est["uncertainty_rmse"] = rmse
        est["uncertainty_note"] = (calibration.get("uncertainty") or {}).get("note")
        estimates.append(est)
    ok = sum(1 for row in estimates if row.get("aqi") is not None)
    print(f"estimates {ok}/{len(estimates)} open-meteo errors={errors[:2]}")
    save_json(
        ROOT / "data" / "cache" / "city_estimates.json",
        {
            "generated_at": now_iso(),
            "source": "Open-Meteo Air Quality API (CAMS) and Open-Meteo weather, bias-corrected with the stored calibration when enabled.",
            "label": "Estimated (model)",
            "open_meteo_errors": errors,
            "places": estimates,
        },
    )
    meta["estimates_updated"] = now_iso()
    meta["estimates_ok"] = ok
    meta["estimates_requested"] = len(estimates)
    meta["open_meteo_errors"] = errors
    meta["use_pollutant_calibration"] = calibration.get("use_pollutant_calibration")
    meta["use_idw"] = calibration.get("use_idw")
    save_json(ROOT / "data" / "cache" / "meta.json", meta)
    if ok == 0:
        raise SystemExit("Open-Meteo returned no estimates")


if __name__ == "__main__":
    main()

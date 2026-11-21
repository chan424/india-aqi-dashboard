#!/usr/bin/env python3
"""Build static JSON, GeoJSON and gzipped downloads from the research archive.

Inputs (override with env vars if you move the archive):
  AQI_BUNDLE        extracted dash_bundle directory
  AQI_STATION_PDF   CPCB all-India CAAQMS list
  AQI_XKDR_CSV      XKDR station directory export
  AQI_BULLETIN_PDF  one national CPCB daily bulletin
  AQI_DISTRICT_SHP  DataMeet Census 2011 district shapefile
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import os
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import shapefile
from shapely.geometry import shape, mapping, Point

from cpcb_aqi import aqi_from_concentrations, category_of
from sources import load_xkdr_stations, norm_place, parse_bulletin_pdf, parse_cpcb_station_pdf

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = Path(os.environ.get("AQI_BUNDLE", "/tmp/dash/dash_bundle"))
STATION_PDF = Path(os.environ.get("AQI_STATION_PDF", "/tmp/stations/caaqms_list_All_India.pdf"))
XKDR_CSV = Path(os.environ.get("AQI_XKDR_CSV", "/tmp/stations/xkdr_stations.csv"))
BULLETIN_PDF = Path(os.environ.get("AQI_BULLETIN_PDF", "/tmp/stations/bull21.pdf"))
DISTRICT_SHP = Path(os.environ.get("AQI_DISTRICT_SHP", "/tmp/geo/2011_Dist.shp"))

TELANGANA_2011 = {
    "adilabad",
    "hyderabad",
    "karimnagar",
    "khammam",
    "mahbubnagar",
    "medak",
    "nalgonda",
    "nizamabad",
    "rangareddy",
    "warangal",
}

MAJOR_CITIES = [
    "Delhi", "Mumbai", "Kolkata", "Chennai", "Bengaluru", "Ahmedabad", "Pune",
    "Jaipur", "Lucknow", "Patna", "Bhopal", "Chandigarh", "Guwahati", "Kochi",
    "Bhubaneswar", "Indore", "Nagpur", "Varanasi", "Amritsar", "Kanpur", "Surat",
    "Coimbatore", "Thiruvananthapuram", "Ranchi", "Raipur", "Dehradun", "Shimla",
    "Srinagar", "Agartala", "Imphal", "Shillong", "Aizawl", "Kohima", "Gangtok",
    "Panaji", "Puducherry", "Chandigarh",
]


def num(value):
    if value is None:
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"na", "nan", "none", "-"}:
        return None
    try:
        out = float(text)
    except ValueError:
        return None
    if out != out:
        return None
    return out


def rnd(value, digits=3):
    if value is None:
        return None
    return round(float(value), digits)


def dump(path: Path, obj, pretty=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        if pretty:
            json.dump(obj, handle, ensure_ascii=False, indent=2)
        else:
            json.dump(obj, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")


def read_csv(path: Path):
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        return list(csv.DictReader(handle))


def metrics(observed, predicted):
    obs = np.asarray(observed, dtype=float)
    pred = np.asarray(predicted, dtype=float)
    err = pred - obs
    if len(obs) < 3 or np.std(obs) == 0 or np.std(pred) == 0:
        corr = None
    else:
        corr = float(np.corrcoef(obs, pred)[0, 1])
    return {
        "n": int(len(obs)),
        "mae": rnd(np.mean(np.abs(err)), 2),
        "rmse": rnd(math.sqrt(float(np.mean(err ** 2))), 2),
        "bias_pred_minus_obs": rnd(float(np.mean(err)), 2),
        "r": None if corr is None or corr != corr else rnd(corr, 3),
    }


def category_hit(obs_aqi, pred_aqi):
    order = ["Good", "Satisfactory", "Moderate", "Poor", "Very Poor", "Severe"]
    a = category_of(obs_aqi)
    b = category_of(pred_aqi)
    if a is None or b is None:
        return None, None
    exact = a == b
    within = abs(order.index(a) - order.index(b)) <= 1
    return exact, within


def ols(x_columns, y):
    design = np.column_stack([np.ones(len(y))] + x_columns)
    beta, *_ = np.linalg.lstsq(design, np.asarray(y, dtype=float), rcond=None)
    return beta


def merge_stations(pdf_rows, xkdr_rows):
    by_id = {}
    for row in pdf_rows:
        item = dict(row)
        item["in_cpcb_pdf"] = True
        item["list_source"] = "CPCB CAAQMS list PDF (app.cpcbccr.com, file dated 18 Nov 2026; 358 stations)"
        by_id[row["id"]] = item
    added = 0
    retitled = 0
    for row in xkdr_rows:
        current = by_id.get(row["id"])
        if current is None:
            item = dict(row)
            item["in_cpcb_pdf"] = False
            network = row.get("source_network") or "cpcb_caaqm"
            if str(row["id"]).startswith("DS"):
                item["list_source"] = (
                    "US Embassy / AirNow monitor via XKDR Forum India Air Quality Database "
                    "(station directory exported 30 Sep 2026)"
                )
            else:
                item["list_source"] = (
                    "CPCB CAAQM station present in the XKDR Forum directory (exported 30 Sep 2026) "
                    "but absent from the 18 Nov 2026 CPCB PDF snapshot"
                )
            item["network"] = network
            by_id[row["id"]] = item
            added += 1
            continue
        xkdr_city = row["city"]
        if (
            norm_place(xkdr_city) != norm_place(current["city"])
            and norm_place(xkdr_city) in norm_place(current["name"])
        ):
            current["city_pdf"] = current["city"]
            current["city"] = xkdr_city
            current["city_note"] = (
                f"City label taken from the XKDR directory ({xkdr_city}); "
                f"the CPCB PDF listed this station under {current['city_pdf']}."
            )
            retitled += 1
    print(f"stations pdf={len(pdf_rows)} xkdr_with_coords={len(xkdr_rows)} added={added} retitled={retitled} union={len(by_id)}")
    return list(by_id.values())


def attach_bulletin(stations, bulletin):
    by_city = {}
    for city in bulletin["cities"]:
        by_city.setdefault(norm_place(city["city"]), city)
    matched = 0
    for station in stations:
        key = norm_place(station["city"])
        hit = by_city.get(key)
        if hit is None and key == "aurangabad maharashtra":
            hit = by_city.get("aurangabad maharashtra")
        station["bulletin_aqi"] = None if hit is None else hit["aqi"]
        station["bulletin_category"] = None if hit is None else hit["category"]
        station["bulletin_pollutant"] = None if hit is None else hit["prominent_pollutant"]
        station["bulletin_date"] = None if hit is None else bulletin["date"]
        station["bulletin_stations"] = None if hit is None else f"{hit['stations_participated']}/{hit['stations_total']}"
        if hit is not None:
            matched += 1
            station["aqi_for_colour"] = hit["aqi"]
            station["aqi_colour_kind"] = "measured_city_bulletin"
        else:
            station["aqi_for_colour"] = None
            station["aqi_colour_kind"] = "none"
    print(f"bulletin {bulletin['date']} cities={len(bulletin['cities'])} stations_coloured={matched}/{len(stations)}")
    return by_city


def stations_geojson(stations):
    features = []
    for station in stations:
        props = {
            "id": station["id"],
            "name": station["name"],
            "city": station["city"],
            "state": station["state"],
            "agency": station.get("agency") or "",
            "list_source": station["list_source"],
            "in_cpcb_pdf": station["in_cpcb_pdf"],
            "bulletin_aqi": station.get("bulletin_aqi"),
            "bulletin_category": station.get("bulletin_category"),
            "bulletin_pollutant": station.get("bulletin_pollutant"),
            "bulletin_date": station.get("bulletin_date"),
            "bulletin_stations": station.get("bulletin_stations"),
            "aqi_for_colour": station.get("aqi_for_colour"),
            "aqi_colour_kind": station.get("aqi_colour_kind"),
            "city_note": station.get("city_note") or "",
            "last_seen": station.get("last_seen") or "",
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [round(station["lon"], 5), round(station["lat"], 5)]},
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def simplify_coords(geometry, tolerance):
    geom = shape(geometry)
    if geom.is_empty:
        return None
    simplified = geom.simplify(tolerance, preserve_topology=True)
    if simplified.is_empty:
        return None
    return simplified


def build_districts(stations, bulletin_cities, bulletin_points):
    reader = shapefile.Reader(str(DISTRICT_SHP), encoding="latin-1")
    points = [(s["lat"], s["lon"], s) for s in stations]
    prepared = []
    centroids = []
    ap_tg_features = []
    for record, shp in zip(reader.iterRecords(), reader.iterShapes()):
        district = str(record["DISTRICT"]).strip()
        state_2011 = str(record["ST_NM"]).strip()
        geom = simplify_coords(shp.__geo_interface__, 0.02)
        if geom is None:
            continue
        rep = geom.representative_point()
        key = district.lower()
        if state_2011 == "Andhra Pradesh" and key in TELANGANA_2011:
            state_now = "Telangana"
        elif state_2011 == "Andhra Pradesh":
            state_now = "Andhra Pradesh"
        else:
            state_now = state_2011
        nearest = None
        inside = False
        probe = geom.buffer(0.02)
        for lat, lon, station in points:
            dist = _hav(rep.y, rep.x, lat, lon)
            if nearest is None or dist < nearest[0]:
                nearest = (dist, station)
            if not inside and probe.covers(Point(lon, lat)):
                inside = True
        gap_km = None if nearest is None else round(nearest[0], 1)
        point_hit = any(probe.covers(pt) for pt in bulletin_points)
        bulletin_hit = point_hit or norm_place(district) in bulletin_cities
        if inside:
            gap_class = "monitor_inside"
        elif bulletin_hit:
            gap_class = "bulletin_without_coordinates"
        else:
            gap_class = "no_monitor"
        row = {
            "district": district,
            "state_2011": state_2011,
            "state_now": state_now,
            "emphasis": state_now in {"Andhra Pradesh", "Telangana"},
            "lat": round(rep.y, 4),
            "lon": round(rep.x, 4),
            "has_monitor": inside,
            "bulletin_reports_city": bulletin_hit,
            "gap_class": gap_class,
            "nearest_monitor_km": gap_km,
            "nearest_monitor": None if nearest is None else nearest[1]["name"],
            "nearest_city": None if nearest is None else nearest[1]["city"],
            "boundary": "Census 2011 districts, DataMeet maps, CC BY 4.0. Telangana districts are the ten 2011 districts that became Telangana in 2014. Andhra Pradesh and Telangana have since been reorganised into smaller districts.",
        }
        centroids.append(row)
        prepared.append((row, geom))
        if row["emphasis"]:
            feature = {
                "type": "Feature",
                "geometry": json.loads(json.dumps(mapping(geom))),
                "properties": {k: row[k] for k in row if k != "boundary"},
            }
            # round coordinates in geometry
            feature["geometry"] = _round_geom(feature["geometry"], 3)
            ap_tg_features.append(feature)
    # national centroids only — polygons for AP and Telangana
    no_monitor = [c for c in centroids if c["emphasis"] and not c["has_monitor"]]
    print(
        f"districts={len(centroids)} ap_tg_polygons={len(ap_tg_features)} "
        f"ap_tg_without_monitor={len(no_monitor)}"
    )
    return centroids, {"type": "FeatureCollection", "features": ap_tg_features}


def _round_geom(geom, digits):
    gtype = geom["type"]
    if gtype == "Polygon":
        geom["coordinates"] = [
            [[round(x, digits), round(y, digits)] for x, y in ring] for ring in geom["coordinates"]
        ]
    elif gtype == "MultiPolygon":
        geom["coordinates"] = [
            [[[round(x, digits), round(y, digits)] for x, y in ring] for ring in poly]
            for poly in geom["coordinates"]
        ]
    return geom


def _hav(lat1, lon1, lat2, lon2):
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def gap_grid(polygons_geojson, stations, step=0.35):
    polys = []
    for feature in polygons_geojson["features"]:
        polys.append(shape(feature["geometry"]))
    if not polys:
        return {"type": "FeatureCollection", "features": []}
    from shapely.ops import unary_union

    region = unary_union(polys)
    minx, miny, maxx, maxy = region.bounds
    features = []
    lat = math.floor(miny / step) * step
    while lat <= maxy:
        lon = math.floor(minx / step) * step
        while lon <= maxx:
            pt = Point(lon + step / 2, lat + step / 2)
            if region.covers(pt):
                nearest = min(stations, key=lambda s: _hav(pt.y, pt.x, s["lat"], s["lon"]))
                dist = _hav(pt.y, pt.x, nearest["lat"], nearest["lon"])
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [round(pt.x, 3), round(pt.y, 3)]},
                        "properties": {
                            "nearest_monitor_km": round(dist, 1),
                            "nearest_monitor": nearest["name"],
                            "nearest_city": nearest["city"],
                            "kind": "distance_grid",
                        },
                    }
                )
            lon += step
        lat += step
    print(f"gap grid points={len(features)}")
    return {"type": "FeatureCollection", "features": features}


def load_station_days():
    files = [
        BUNDLE / "01_Hyderabad/Hyderabad_station_daily_pollutants_2017_2025.csv",
        BUNDLE / "02_AndhraPradesh/AP_station_daily_pollutants_2017_2025.csv",
    ]
    columns = {
        "pm25": "PM2.5 (µg/m³)",
        "pm10": "PM10 (µg/m³)",
        "no2": "NO2 (µg/m³)",
        "o3": "Ozone (µg/m³)",
        "so2": "SO2 (µg/m³)",
        "co": "CO (mg/m³)",
        "rh": "RH (%)",
        "ws": "WS (m/s)",
        "rain": "RF (mm)",
    }
    # city-day and station-month accumulators
    city_day = defaultdict(lambda: defaultdict(list))
    month = defaultdict(lambda: defaultdict(list))
    meta = {}
    for path in files:
        for row in read_csv(path):
            if str(row.get("valid_18h")).strip() not in {"True", "true", "1"}:
                continue
            city = row["City"].strip()
            date = row["local_date"]
            sid = row["Station ID"].strip()
            name = row["Station Name"].strip()
            meta[sid] = {"name": name, "city": city, "state": row["State"].strip()}
            parsed = {key: num(row.get(col)) for key, col in columns.items()}
            city_day[(city, date)]["rows"].append(parsed)
            ym = date[:7]
            bucket = month[(sid, ym)]
            for key, value in parsed.items():
                if value is not None and key in {"pm25", "pm10", "no2", "o3", "so2", "co"}:
                    bucket[key].append(value)
    city_means = {}
    for (city, date), payload in city_day.items():
        means = {}
        for key in ("pm25", "pm10", "no2", "o3", "so2", "co", "rh", "ws", "rain"):
            vals = [item[key] for item in payload["rows"] if item[key] is not None]
            means[key] = sum(vals) / len(vals) if vals else None
        means["n_stations"] = len(payload["rows"])
        city_means[(city, date)] = means
    monthly_rows = []
    for (sid, ym), bucket in sorted(month.items()):
        if sid not in meta:
            continue
        entry = {"id": sid, "month": ym, **meta[sid]}
        keep = False
        for key in ("pm25", "pm10", "no2", "o3", "so2", "co"):
            vals = bucket.get(key) or []
            entry[key] = rnd(sum(vals) / len(vals), 2) if vals else None
            entry[key + "_n"] = len(vals)
            keep = keep or bool(vals)
        if keep:
            monthly_rows.append(entry)
    print(f"valid_18h city-days={len(city_means)} station-months={len(monthly_rows)}")
    return city_means, monthly_rows


def load_cams():
    path = BUNDLE / "02_AndhraPradesh/AP_CAMS_MODEL_daily_2022_2026.csv"
    out = {}
    co_values = []
    for row in read_csv(path):
        if row.get("data_type") and "MODEL" not in row["data_type"]:
            continue
        rec = {
            "pm25": num(row.get("pm2_5")),
            "pm10": num(row.get("pm10")),
            "no2": num(row.get("nitrogen_dioxide")),
            "o3": num(row.get("ozone")),
            "so2": num(row.get("sulphur_dioxide")),
            "co_raw": num(row.get("carbon_monoxide")),
        }
        if rec["co_raw"] is not None:
            co_values.append(rec["co_raw"])
        out[(row["city"].strip(), row["date"])] = rec
    median_co = float(np.median(co_values)) if co_values else 0
    # Open-Meteo CAMS carbon monoxide is µg/m³. Station CO is mg/m³.
    co_scale = 1000.0 if median_co > 20 else 1.0
    print(f"CAMS city-days={len(out)} median CO raw={median_co:.2f} divide_by={co_scale}")
    for rec in out.values():
        rec["co"] = None if rec["co_raw"] is None else rec["co_raw"] / co_scale
    return out


def fit_calibration(city_means, cams):
    """Fit on 2022–2024, score on 2025. Weather terms kept only if they cut test RMSE by >=5%."""
    pollutant_keys = ["pm25", "pm10", "no2", "o3", "so2", "co"]
    joined = []
    for (city, date), obs in city_means.items():
        model = cams.get((city, date))
        if model is None:
            continue
        year = int(date[:4])
        if year < 2022 or year > 2025:
            continue
        joined.append((city, date, year, obs, model))
    cities = sorted({item[0] for item in joined})
    print(f"joined station-CAMS city-days={len(joined)} cities={cities}")

    def design_rows(rows, key, with_weather):
        xs_cams, xs_extra, ys = [], [], []
        for city, date, year, obs, model in rows:
            y = obs.get(key)
            x = model.get(key)
            if y is None or x is None:
                continue
            extra = []
            if with_weather:
                if obs.get("rh") is None or obs.get("ws") is None or obs.get("rain") is None:
                    continue
                extra = [obs["rh"], obs["ws"], obs["rain"]]
            xs_cams.append(x)
            xs_extra.append(extra)
            ys.append(y)
        return xs_cams, xs_extra, ys

    pollutant_calibration = {}
    pollutant_report = {}
    for key in pollutant_keys:
        train = [item for item in joined if item[2] <= 2024]
        test = [item for item in joined if item[2] == 2025]
        simple_tr = design_rows(train, key, False)
        simple_te = design_rows(test, key, False)
        weather_tr = design_rows(train, key, True)
        weather_te = design_rows(test, key, True)
        report = {"cities": cities}
        chosen = None
        if len(simple_tr[2]) >= 50 and len(simple_te[2]) >= 30:
            beta = ols([simple_tr[0]], simple_tr[2])
            pred_te = beta[0] + beta[1] * np.asarray(simple_te[0])
            simple_metrics = metrics(simple_te[2], pred_te)
            raw_metrics = metrics(simple_te[2], simple_te[0])
            report["raw_test"] = raw_metrics
            report["linear_test"] = simple_metrics
            report["linear_coefficients"] = {"a": rnd(beta[0], 4), "b": rnd(beta[1], 4)}
            pred_tr = beta[0] + beta[1] * np.asarray(simple_tr[0])
            report["linear_train"] = metrics(simple_tr[2], pred_tr)
            chosen = {"a": float(beta[0]), "b": float(beta[1]), "extra": {}}
            chosen_rmse = simple_metrics["rmse"]
            if len(weather_tr[2]) >= 50 and len(weather_te[2]) >= 30:
                beta_w = ols(
                    [
                        weather_tr[0],
                        [row[0] for row in weather_tr[1]],
                        [row[1] for row in weather_tr[1]],
                        [row[2] for row in weather_tr[1]],
                    ],
                    weather_tr[2],
                )
                pred_w = (
                    beta_w[0]
                    + beta_w[1] * np.asarray(weather_te[0])
                    + beta_w[2] * np.asarray([row[0] for row in weather_te[1]])
                    + beta_w[3] * np.asarray([row[1] for row in weather_te[1]])
                    + beta_w[4] * np.asarray([row[2] for row in weather_te[1]])
                )
                weather_metrics = metrics(weather_te[2], pred_w)
                report["weather_test"] = weather_metrics
                report["weather_coefficients"] = {
                    "a": rnd(beta_w[0], 4),
                    "b": rnd(beta_w[1], 4),
                    "rh": rnd(beta_w[2], 4),
                    "ws": rnd(beta_w[3], 4),
                    "rain": rnd(beta_w[4], 4),
                    "n_train": len(weather_tr[2]),
                    "n_test": len(weather_te[2]),
                }
                if (
                    chosen_rmse
                    and weather_metrics["rmse"] is not None
                    and weather_metrics["rmse"] <= 0.95 * chosen_rmse
                ):
                    chosen = {
                        "a": float(beta_w[0]),
                        "b": float(beta_w[1]),
                        "extra": {
                            "rh": float(beta_w[2]),
                            "ws": float(beta_w[3]),
                            "rain": float(beta_w[4]),
                        },
                    }
                    report["selected"] = "cams_plus_rh_wind_rain"
                else:
                    report["selected"] = "cams_only"
            else:
                report["selected"] = "cams_only"
        else:
            report["selected"] = "none"
        if chosen:
            pollutant_calibration[key] = {
                "a": rnd(chosen["a"], 4),
                "b": rnd(chosen["b"], 4),
                "extra": {k: rnd(v, 4) for k, v in chosen["extra"].items()},
            }
        pollutant_report[key] = report
        print(key, report.get("selected"), report.get("linear_test"), report.get("raw_test"))

    # AQI versus the CPCB city bulletin, using daily-mean concentrations.
    bulletin_rows = read_csv(BUNDLE / "02_AndhraPradesh/CPCB_AQI_Bulletin_Hyd_AP_cities_daily_2015_2026.csv")
    bulletin = {}
    for row in bulletin_rows:
        bulletin[(row["city"].strip(), row["bulletin_date"])] = num(row.get("aqi"))

    def predict_aqi(model, use_cal, year_min, year_max):
        pairs = []
        for (city, date), model_row in cams.items():
            year = int(date[:4])
            if year < year_min or year > year_max:
                continue
            observed = bulletin.get((city, date))
            if observed is None:
                continue
            conc = {}
            for key in pollutant_keys:
                raw = model_row.get(key)
                spec = pollutant_calibration.get(key) if use_cal else None
                if raw is None:
                    conc[key] = None
                elif spec:
                    # Weather extras are not in the CAMS daily file. Skip them here;
                    # live estimates supply weather. Daily validation uses a + b*CAMS only.
                    conc[key] = max(0.0, spec["a"] + spec["b"] * raw)
                else:
                    conc[key] = raw
            # Historical CAMS ozone/CO are daily means, not 8-hour maxima.
            predicted = aqi_from_concentrations(conc)
            if predicted["aqi"] is None:
                continue
            pairs.append((city, date, observed, predicted["aqi_rounded"], predicted["dominant"]))
        return pairs

    def summarise(pairs):
        if len(pairs) < 5:
            return {"n": len(pairs)}
        base = metrics([p[2] for p in pairs], [p[3] for p in pairs])
        exact = within = 0
        for _, _, obs, pred, _ in pairs:
            hit, near = category_hit(obs, pred)
            exact += int(bool(hit))
            within += int(bool(near))
        base["exact_category_pct"] = rnd(100 * exact / len(pairs), 1)
        base["within_one_category_pct"] = rnd(100 * within / len(pairs), 1)
        by_city = []
        cities_present = sorted({p[0] for p in pairs})
        for city in cities_present:
            subset = [p for p in pairs if p[0] == city]
            city_metrics = metrics([p[2] for p in subset], [p[3] for p in subset])
            city_metrics["city"] = city
            by_city.append(city_metrics)
        base["by_city"] = by_city
        return base

    raw_2025 = summarise(predict_aqi(cams, False, 2025, 2025))
    cal_2025 = summarise(predict_aqi(cams, True, 2025, 2025))
    raw_2026 = summarise(predict_aqi(cams, False, 2026, 2026))
    cal_2026 = summarise(predict_aqi(cams, True, 2026, 2026))
    # in-sample, reported but not used to choose
    cal_train = summarise(predict_aqi(cams, True, 2022, 2024))

    use_pollutant = False
    if cal_2025.get("rmse") is not None and raw_2025.get("rmse") is not None:
        use_pollutant = cal_2025["rmse"] < raw_2025["rmse"]
    print("AQI 2025 raw", {k: raw_2025.get(k) for k in ("n", "mae", "rmse", "bias_pred_minus_obs", "r", "exact_category_pct")})
    print("AQI 2025 cal", {k: cal_2025.get(k) for k in ("n", "mae", "rmse", "bias_pred_minus_obs", "r", "exact_category_pct")})
    print("use_pollutant_calibration", use_pollutant)

    # IDW leave-one-city-out on 2025, using calibrated (or raw) AQI.
    use_cal_for_idw = use_pollutant
    pairs_2025 = predict_aqi(cams, use_cal_for_idw, 2025, 2025)
    # city coordinates from the forecast file, falling back to station means
    city_xy = {}
    for row in read_csv(BUNDLE / "03_Climate_ENSO_Weather/CAMS_OpenMeteo_MODEL_forecast_Hyd_AP_cities_15_20Nov2026.csv"):
        city_xy[row["city"].split("(")[0].strip()] = (float(row["lat"]), float(row["lon"]))
    by_date = defaultdict(list)
    for city, date, obs, pred, dom in pairs_2025:
        if city not in city_xy:
            continue
        by_date[date].append((city, obs, pred, city_xy[city]))
    idw_obs, idw_pred = [], []
    n_with_donor = 0
    for date, group in by_date.items():
        for city, obs, pred, (lat, lon) in group:
            numer = den = 0.0
            for other, o_obs, o_pred, (olat, olon) in group:
                if other == city:
                    continue
                dist = _hav(lat, lon, olat, olon)
                if dist > 300:
                    continue
                weight = 1.0 / (max(dist, 15) ** 2)
                numer += weight * (o_obs - o_pred)
                den += weight
            correction = numer / den if den else 0.0
            if den:
                n_with_donor += 1
            idw_obs.append(obs)
            idw_pred.append(min(500, max(0, pred + correction)))
    idw_2025 = metrics(idw_obs, idw_pred) if idw_obs else {"n": 0}
    if idw_obs:
        exact = within = 0
        for obs, pred in zip(idw_obs, idw_pred):
            hit, near = category_hit(obs, pred)
            exact += int(bool(hit))
            within += int(bool(near))
        idw_2025["exact_category_pct"] = rnd(100 * exact / len(idw_obs), 1)
        idw_2025["within_one_category_pct"] = rnd(100 * within / len(idw_obs), 1)
        idw_2025["share_with_neighbour_pct"] = rnd(100 * n_with_donor / len(idw_obs), 1)
    base_rmse = (cal_2025 if use_pollutant else raw_2025).get("rmse")
    use_idw = bool(idw_2025.get("rmse") is not None and base_rmse is not None and idw_2025["rmse"] < base_rmse)
    print("IDW 2025", idw_2025, "use_idw", use_idw)

    calibration = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "use_pollutant_calibration": use_pollutant,
        "use_aqi_affine": False,
        "use_idw": use_idw,
        "pollutant_calibration": pollutant_calibration if use_pollutant else {},
        "pollutant_calibration_fitted_even_if_unused": pollutant_calibration,
        "idw": {"power": 2, "radius_km": 300, "floor_km": 15},
        "fit": {
            "sample": "City-day mean of CAAQMS stations with valid_18h (≥18 distinct hours), joined to Open-Meteo CAMS daily means on the same city and date.",
            "cities": cities,
            "train_dates": "2022-01-01 to 2024-12-31",
            "test_dates": "2025-01-01 to 2025-12-31",
            "co_unit": "CAMS carbon_monoxide divided by 1000 to convert µg/m³ to mg/m³ before the join with station CO.",
            "ozone_limitation": "Station and CAMS ozone in this join are daily means. CPCB's ozone sub-index is defined on an 8-hour average. Live estimates use the max 8-hour mean from hourly CAMS; the historical score uses the daily mean.",
            "weather": "RH, wind speed and rain from the station record were tested as extra linear terms. A weather model is selected only when its 2025 RMSE is at least 5% lower than CAMS-only. The daily CAMS file has no weather, so the bulletin comparison below applies a and b only.",
        },
        "pollutants": pollutant_report,
        "aqi_vs_bulletin": {
            "definition": "CPCB sub-index of daily CAMS concentrations (pollutant calibration applied on the test comparison when use_pollutant_calibration is true) versus the CPCB city bulletin AQI. This is a daily-mean proxy, not the bulletin's own procedure.",
            "test_2025_raw": raw_2025,
            "test_2025_calibrated": cal_2025,
            "test_2025_idw_leave_one_city_out": idw_2025,
            "confirm_2026_raw": raw_2026,
            "confirm_2026_calibrated": cal_2026,
            "train_2022_2024_calibrated_not_used_for_selection": cal_train,
            "selection_rule": "Use pollutant calibration only if 2025 bulletin RMSE falls. Use IDW only if leave-one-city-out 2025 RMSE falls further. 2026 is reported and was not used to choose.",
        },
        "uncertainty": {
            "test_2025_rmse_aqi": (idw_2025 if use_idw else (cal_2025 if use_pollutant else raw_2025)).get("rmse"),
            "test_2025_rmse_without_idw": (cal_2025 if use_pollutant else raw_2025).get("rmse"),
            "note": "The ± band shown on an estimate is this 2025 holdout RMSE in AQI points. It is an error size from Hyderabad and Andhra Pradesh city-days, not a calibrated prediction interval for every Indian location.",
        },
    }
    return calibration


def bulletin_series():
    rows = read_csv(BUNDLE / "02_AndhraPradesh/CPCB_AQI_Bulletin_Hyd_AP_cities_daily_2015_2026.csv")
    grouped = defaultdict(lambda: {"dates": [], "aqi": [], "category": [], "pollutant": []})
    states = {}
    for row in rows:
        key = row["city"].strip()
        states[key] = row["state"].strip()
        grouped[key]["dates"].append(row["bulletin_date"])
        grouped[key]["aqi"].append(int(float(row["aqi"])) if row["aqi"] else None)
        grouped[key]["category"].append(row["air_quality_category"])
        grouped[key]["pollutant"].append(row["prominent_pollutant"])
    cities = []
    for city, payload in sorted(grouped.items()):
        order = sorted(range(len(payload["dates"])), key=lambda i: payload["dates"][i])
        cities.append(
            {
                "city": city,
                "state": states[city],
                "dates": [payload["dates"][i] for i in order],
                "aqi": [payload["aqi"][i] for i in order],
                "category": [payload["category"][i] for i in order],
                "pollutant": [payload["pollutant"][i] for i in order],
            }
        )
    return {
        "value_type": "observed CPCB daily AQI bulletin, city",
        "source": "CPCB AQI bulletins parsed in the RGUKT Ongole archive, Hyderabad and Andhra Pradesh cities, 2015–2026",
        "cities": cities,
    }


def station_month_payload(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["id"]].append(row)
    stations = []
    for sid, items in sorted(grouped.items()):
        items.sort(key=lambda item: item["month"])
        head = items[0]
        stations.append(
            {
                "id": sid,
                "name": head["name"],
                "city": head["city"],
                "state": head["state"],
                "month": [item["month"] for item in items],
                "pm25": [item["pm25"] for item in items],
                "pm10": [item["pm10"] for item in items],
                "no2": [item["no2"] for item in items],
                "o3": [item["o3"] for item in items],
                "so2": [item["so2"] for item in items],
                "co": [item["co"] for item in items],
                "n_pm25": [item["pm25_n"] for item in items],
            }
        )
    return {
        "value_type": "observed CAAQMS monthly mean of valid_18h daily means",
        "note": "A day counts only when at least 18 distinct local hours are present. Means are across those days. CO is mg/m³; other pollutants are µg/m³.",
        "stations": stations,
    }


def ongole_payload():
    rows = read_csv(BUNDLE / "Ongole_Prakasam_case_study_daily_Oct_Nov_2026.csv")
    records = []
    for row in rows:
        records.append(
            {
                "date": row["date"],
                "pm25": num(row["CAMS_MODEL_pm2_5"]),
                "pm10": num(row["CAMS_MODEL_pm10"]),
                "no2": num(row["CAMS_MODEL_no2"]),
                "o3": num(row["CAMS_MODEL_o3"]),
                "blh": num(row["ERA5_blh_mean_m"]),
                "wind": num(row["ERA5_ws10_mean_ms"]),
                "rain": num(row["ERA5_precip_mm"]),
                "rh": num(row["ERA5_rh_mean"]),
                "bulletin_aqi": num(row["CPCB_bulletin_AQI_obs"]),
                "category": row["air_quality_category"] or None,
                "pollutant": row["prominent_pollutant"] or None,
            }
        )
    return {
        "place": "Ongole, Prakasam district, Andhra Pradesh",
        "coordinates_note": "15.5057 N, 80.0499 E in the companion CAMS forecast file. The archive geocodes Ongole at an OpenStreetMap city centroid because a station coordinate was not yet on the APPCB list used by the compiler.",
        "value_types": {
            "cams": "MODEL CAMS via Open-Meteo",
            "era5": "reanalysis (ERA5 via Open-Meteo)",
            "bulletin": "observed CPCB daily city bulletin",
        },
        "days": records,
    }


def ncap_payload():
    pm10 = []
    for row in read_csv(BUNDLE / "04_Health/NCAP_130_cities_PM10_FY2017_18_vs_FY2025_26_LokSabha_SQ12_20Jul2026.csv"):
        pm10.append(
            {
                "city": row["city"],
                "state": row["state"],
                "pm10_2017": num(row["pm10_FY2017_18"]),
                "pm10_2025": num(row["pm10_FY2025_26"]),
                "pct_improvement": num(row["pct_improvement_vs_2017_18"]),
                "meets_60": row["meets_NAAQS_PM10_60_in_FY2025_26_DERIVED"] == "True",
            }
        )
    svs = []
    for row in read_csv(BUNDLE / "Swachh_Vayu_Survekshan_2023_2025_all_NCAP_cities_scores_ranks.csv"):
        svs.append(
            {
                "year": int(float(row["survey_year"])),
                "category": row["category"],
                "city": row["city"],
                "state": row["state_DERIVED"],
                "score": num(row["final_score"]),
                "rank": num(row["rank"]),
            }
        )
    days = []
    for row in read_csv(BUNDLE / "04_Health/LokSabha_SQ120_27Jul2026_citywise_AQI_category_days_2023_2025_all_cities.csv"):
        days.append(
            {
                "state": row["state"],
                "city": row["city_as_printed"],
                "year": int(float(row["year"])),
                "good": int(float(row["good"] or 0)),
                "satisfactory": int(float(row["satisfactory"] or 0)),
                "moderate": int(float(row["moderate"] or 0)),
                "poor": int(float(row["poor"] or 0)),
                "very_poor": int(float(row["very_poor"] or 0)),
                "severe": int(float(row["severe"] or 0)),
            }
        )
    matrix = []
    for row in read_csv(BUNDLE / "NCAP_city_case_study_matrix_AP_TG_16_cities.csv"):
        matrix.append({key: (num(value) if key not in {"city", "city_std", "state", "scheme", "value_type"} else value) for key, value in row.items()})
    return {
        "pm10": pm10,
        "pm10_source": "Lok Sabha Starred Question 12, 20 Jul 2026, MoEFCC Annexure-IV. Percent improvement is as printed. meets_60 is derived in the archive (PM10 ≤ 60).",
        "svs": svs,
        "svs_source": "Swachh Vayu Survekshan 2023, 2024 and 2025 official results. state_DERIVED was added by the archive.",
        "category_days": days,
        "category_days_source": "Lok Sabha Starred Question 120, 27 Jul 2026. Counts are as printed.",
        "matrix": matrix,
    }


def health_payload():
    panel = []
    for row in read_csv(BUNDLE / "04_Health/District_AQ_health_panel_AP_TG_AQLI_PM25_NFHS5_NFHS6.csv"):
        panel.append(
            {
                "state": row["state"],
                "district": row["district"],
                "ari5": num(row["child_ARI_2wk_pct_NFHS5"]),
                "ari6": num(row["child_ARI_2wk_pct_NFHS6"]),
                "tobacco_men6": num(row["men_any_tobacco_pct_NFHS6"]),
                "tobacco_women6": num(row["women_any_tobacco_pct_NFHS6"]),
                "bp_men6": num(row["men_elev_BP_or_med_pct_NFHS6"]),
                "bp_women6": num(row["women_elev_BP_or_med_pct_NFHS6"]),
                "pm2019": num(row["AQLI_pm_2019"]),
                "pm2023": num(row["AQLI_pm_2023"]),
                "llpp2019": num(row["AQLI_llpp_who_2019"]),
                "llpp2023": num(row["AQLI_llpp_who_2023"]),
                "value_type": row["value_type"],
            }
        )
    return {
        "panel": panel,
        "note": "District join prepared in the archive. AQLI PM2.5 and life-years lost are model-based (EPIC AQLI 2025, GADM-2). NFHS figures are survey estimates. The join is ecological, not a statement about individual risk.",
    }


def fires_and_plants():
    monthly = defaultdict(lambda: {"n": 0, "frp": 0.0})
    grid = defaultdict(int)
    for row in read_csv(BUNDLE / "03_Climate_ENSO_Weather/firms/FIRMS_VIIRS_NOAA20_AP_TG_OctNov_2018_2025.csv"):
        date = row["acq_date"]
        year, month = int(date[:4]), int(date[5:7])
        state = row["state_polygon"]
        key = (year, month, state)
        monthly[key]["n"] += 1
        frp = num(row.get("frp"))
        if frp is not None:
            monthly[key]["frp"] += frp
        lat, lon = num(row["latitude"]), num(row["longitude"])
        if lat is None or lon is None:
            continue
        grid[(year, math.floor(lat * 2) / 2, math.floor(lon * 2) / 2, state)] += 1
    month_rows = [
        {"year": y, "month": m, "state": s, "detections": payload["n"], "frp_sum": rnd(payload["frp"], 1)}
        for (y, m, s), payload in sorted(monthly.items())
    ]
    grid_rows = [
        {
            "year": year,
            "lat": lat + 0.25,
            "lon": lon + 0.25,
            "state": state,
            "detections": count,
        }
        for (year, lat, lon, state), count in grid.items()
        if count >= 3
    ]
    apna = []
    for row in read_csv(BUNDLE / "03_Climate_ENSO_Weather/emission_sources/APnA_PM25_source_apportionment_50_Indian_airsheds_MODEL.csv"):
        apna.append(
            {
                "city": row["City"],
                "transport": num(row["transport_all_pct"]),
                "residential": num(row["residential_pct"]),
                "industry": num(row["industries_excl_brick_pct"]),
                "dust": num(row["dust_construction_resuspension_pct"]),
                "waste": num(row["open_waste_burning_pct"]),
                "diesel": num(row["diesel_gensets_pct"]),
                "brick": num(row["brick_kilns_pct"]),
                "regional": num(row["outside_regional_pct"]),
                "value_type": row["value_type"],
            }
        )
    cmb = []
    for row in read_csv(BUNDLE / "01_Hyderabad/Hyderabad_PM10_PM25_source_apportionment_CMB_2005_Guttikunda_2013.csv"):
        cmb.append(
            {
                "season": row["season"],
                "size": row["size_fraction"],
                "station": row["station"],
                "mass": num(row["mass_ugm3"]),
                "road_dust": num(row["road_dust_pct"]),
                "vehicles": num(row["vehicle_exhaust_pct"]),
                "sulfate": num(row["secondary_sulfates_pct"]),
                "biomass": num(row["biomass_burning_pct"]),
                "coal": num(row["coal_burning_pct"]),
            }
        )
    return {
        "fires_monthly": month_rows,
        "fires_grid": grid_rows,
        "fires_note": "NASA FIRMS VIIRS NOAA-20 detections inside Andhra Pradesh and Telangana polygons, October–November 2018–2025. Counts are detections, not a burned-area inventory. Grid cells are 0.5° and shown only when a cell-year has at least 3 detections.",
        "apna": apna,
        "hyderabad_cmb": cmb,
    }


def enso_payload(bulletin_doc):
    oni = {}
    for row in read_csv(BUNDLE / "03_Climate_ENSO_Weather/ONI_ERSSTv5_clean.csv"):
        if row["seas"] == "OND":
            oni[int(row["year"])] = num(row["anom"])
    by_city_year = defaultdict(list)
    for city in bulletin_doc["cities"]:
        if city["city"] not in {"Hyderabad", "Visakhapatnam", "Vijayawada", "Tirupati", "Amaravati", "Rajamahendravaram"}:
            continue
        for date, aqi in zip(city["dates"], city["aqi"]):
            if aqi is None:
                continue
            year, month = int(date[:4]), int(date[5:7])
            if month in {10, 11, 12}:
                by_city_year[(city["city"], year)].append(aqi)
    years = sorted(set(oni) & {year for (_, year) in by_city_year if 2015 <= year <= 2025})
    series = []
    for year in years:
        entry = {"year": year, "oni_ond": oni.get(year)}
        for city in ("Hyderabad", "Visakhapatnam", "Vijayawada", "Tirupati", "Amaravati", "Rajamahendravaram"):
            vals = by_city_year.get((city, year)) or []
            entry[city] = rnd(sum(vals) / len(vals), 1) if vals else None
            entry[city + "_n"] = len(vals)
        series.append(entry)

    def corr(city):
        xs, ys = [], []
        for entry in series:
            if entry.get(city) is None or entry.get("oni_ond") is None:
                continue
            if entry[city + "_n"] < 20:
                continue
            xs.append(entry["oni_ond"])
            ys.append(entry[city])
        if len(xs) < 5:
            return {"city": city, "n": len(xs)}
        base = metrics(ys, xs)  # r is symmetric; mae is not meaningful here
        r = float(np.corrcoef(xs, ys)[0, 1])
        # two-sided p from Student t, via a regularised incomplete beta if scipy exists
        n = len(xs)
        df = n - 2
        t_stat = r * math.sqrt(df / max(1e-12, 1 - r * r)) if abs(r) < 1 else float("inf")
        p = None
        try:
            from scipy import stats

            p = float(2 * stats.t.sf(abs(t_stat), df))
        except Exception:
            p = None
        return {"city": city, "n": n, "r": rnd(r, 3), "t": rnd(t_stat, 2), "p": None if p is None else rnd(p, 3), "min_days": 20}

    return {
        "series": series,
        "correlations": [corr(city) for city in ("Hyderabad", "Visakhapatnam", "Vijayawada", "Tirupati", "Amaravati", "Rajamahendravaram")],
        "note": "October–December mean of the CPCB city bulletin AQI against the NOAA OND Oceanic Niño Index (ERSSTv5). Years with fewer than 20 bulletin days are left out of r. This is a short ecological series, not a causal estimate. The archive README reports a separate winter-onset window (1 Oct–14 Nov) with Hyderabad r=0.21; the figure on this page is the OND mean and will differ.",
    }


def diwali_and_lockdown():
    diwali = []
    for row in read_csv(BUNDLE / "04_Health/Diwali_PM_spike_by_station_2017_2025.csv"):
        diwali.append(
            {
                "year": int(float(row["year"])),
                "date": row["diwali_date"],
                "city": row["city"],
                "station": row["short"] or row["station"],
                "pm25_diwali": rnd(num(row["mean_PM25_diwali"]), 1),
                "pm25_control": rnd(num(row["mean_PM25_control"]), 1),
                "pct": rnd(num(row["pct_PM25_vs_control"]), 1),
            }
        )
    lockdown = []
    for row in read_csv(BUNDLE / "01_Hyderabad/lockdown_2020_weather_normalised_Hyderabad.csv"):
        if row.get("weather_source", "").startswith("Open-Meteo") and row.get("is_long_hyd") == "True":
            lockdown.append(
                {
                    "station": row["short"],
                    "pollutant": row["pollutant"],
                    "lock_pct_mean": rnd(num(row["lock_pct_mean"]), 1),
                    "placebo_pct_mean": rnd(num(row["placebo_pct_mean"]), 1),
                    "lock_n": num(row["lock_n_eval"]),
                    "weather_source": "Open-Meteo ERA5",
                }
            )
    return {"diwali": diwali, "lockdown_era5_long_running": lockdown}


def build_places(stations, centroids, forecast_rows):
    places = []
    seen = set()

    def add(place):
        key = (round(place["lat"], 3), round(place["lon"], 3), place["name"])
        if key in seen:
            return
        seen.add(key)
        places.append(place)

    for row in forecast_rows:
        name = row["city"].split("(")[0].strip()
        add(
            {
                "id": "city:" + norm_place(name),
                "name": name if "city mean" not in row["city"] else "Hyderabad",
                "state": "Telangana" if "Hyderabad" in row["city"] else "Andhra Pradesh",
                "kind": "research_city",
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "coord_source": row.get("coord_basis") or "archive CAMS forecast coordinate table",
            }
        )
    # Hyderabad name fix if the split left a long label
    by_city = defaultdict(list)
    for station in stations:
        by_city[norm_place(station["city"])].append(station)
    research_names = {norm_place(place["name"]) for place in places}
    for label in MAJOR_CITIES:
        group = by_city.get(norm_place(label))
        if not group or norm_place(label) in research_names:
            continue
        lat = sum(s["lat"] for s in group) / len(group)
        lon = sum(s["lon"] for s in group) / len(group)
        add(
            {
                "id": "major:" + norm_place(label),
                "name": label,
                "state": group[0]["state"],
                "kind": "major_city",
                "lat": round(lat, 4),
                "lon": round(lon, 4),
                "coord_source": f"Mean of {len(group)} monitor coordinates in this city from the station list used on the map.",
                "n_monitors": len(group),
            }
        )
    unmonitored = [
        c
        for c in centroids
        if c["emphasis"]
        and c.get("gap_class") == "no_monitor"
        and (c["nearest_monitor_km"] or 0) >= 25
        and norm_place(c["district"]) not in research_names
    ]
    unmonitored.sort(key=lambda c: c["nearest_monitor_km"] or 0, reverse=True)
    for row in unmonitored:
        add(
            {
                "id": "district:" + norm_place(row["state_now"] + " " + row["district"]),
                "name": row["district"],
                "state": row["state_now"],
                "kind": "unmonitored_district",
                "lat": row["lat"],
                "lon": row["lon"],
                "coord_source": "Representative point of the Census 2011 district polygon (DataMeet). Not a monitoring site.",
                "nearest_monitor_km": row["nearest_monitor_km"],
            }
        )
    print(f"estimate places={len(places)}")
    return places


def donor_seed(stations):
    grouped = defaultdict(list)
    for station in stations:
        if station.get("bulletin_aqi") is None:
            continue
        grouped[norm_place(station["city"])].append(station)
    donors = []
    for key, group in grouped.items():
        donors.append(
            {
                "id": "donor:" + key,
                "name": group[0]["city"],
                "state": group[0]["state"],
                "lat": round(sum(s["lat"] for s in group) / len(group), 4),
                "lon": round(sum(s["lon"] for s in group) / len(group), 4),
                "bulletin_aqi": group[0]["bulletin_aqi"],
                "bulletin_date": group[0]["bulletin_date"],
                "n_stations": len(group),
            }
        )
    return donors


def write_downloads():
    listing = read_csv(BUNDLE / "drive_listing_after_reorg_19Nov2026.csv")
    by_name = defaultdict(list)
    for row in listing:
        if row["mimeType"] == "application/vnd.google-apps.folder":
            continue
        by_name[row["name"]].append({"id": row["id"], "parent_path": row["parent_path"], "size": row["size"]})
    descriptions = {
        "master_station_table.csv": "27 Hyderabad and Andhra Pradesh stations used in the RGUKT archive, with coordinates and 2017–2023 AQI summaries.",
        "stations_AP_Hyderabad.geojson": "GeoJSON of those archive stations.",
        "station_AQI_summary_2017_2023.csv": "Station-level AQI summary, 2017–2023, valid-18h days.",
        "AP_TG_daily_AQI_2017_2023.csv": "Daily station AQI for Andhra Pradesh and Telangana, 2017–2023, from the CPCB repository compilation.",
        "AP_CAAQMS_network_coords_and_CPCB_bulletin_timeline_2015_2026.csv": "APPCB network coordinates and the first and last CPCB bulletin dates. Some 2026 cities are OpenStreetMap centroids and are labelled as such in coord_source.",
        "AP_CAAQMS_network_2015_2026.geojson": "GeoJSON of the AP network table.",
        "AP_CAMS_MODEL_daily_2022_2026.csv": "Open-Meteo CAMS model daily fields for 13 cities, 2022–2026. Model, not observations.",
        "AP_station_daily_pollutants_2017_2025.csv": "Andhra Pradesh CAAQMS daily pollutant means, 2017–2025. valid_18h marks days with at least 18 hours.",
        "AP_TG_city_year_panel_obs_PM_and_bulletin_AQI_2015_2026.csv": "City-year observed PM and bulletin AQI. Derived join.",
        "CPCB_AQI_Bulletin_Hyd_AP_cities_daily_2015_2026.csv": "CPCB daily city AQI bulletins for Hyderabad and Andhra Pradesh cities, 2015–2026.",
        "AndhraPradesh_daily_AQI_2017_2023.csv": "Andhra Pradesh daily station AQI, 2017–2023.",
        "CPCB_AQI_Bulletin_Hyderabad_daily_2015_2026.csv": "Hyderabad rows of the CPCB daily bulletin, 2015–2026.",
        "Hyderabad_daily_AQI_2017_2023.csv": "Hyderabad station daily AQI, 2017–2023.",
        "Hyderabad_station_daily_pollutants_2017_2025.csv": "Hyderabad CAAQMS daily pollutant means, 2017–2025.",
        "hyd_ap_live_aqi_snapshot_2026.csv": "Point-in-time bulletin and EWS snapshots collected in November 2026. Not a continuous live feed.",
        "lockdown_2020_weather_normalised_Hyderabad.csv": "Derived weather-normalised lockdown contrasts for Hyderabad. Placebo errors are large.",
        "Hyderabad_PM10_PM25_source_apportionment_CMB_2005_Guttikunda_2013.csv": "CMB source shares transcribed from Guttikunda et al. 2013. Receptor-model results for 2005–06 samples.",
        "Ongole_Prakasam_case_study_daily_Oct_Nov_2026.csv": "Ongole, 1 Oct–15 Nov 2026: CAMS model, ERA5 weather, and CPCB bulletin AQI on the days a bulletin existed.",
        "NCAP_city_case_study_matrix_AP_TG_16_cities.csv": "Derived city matrix: NCAP PM10, Swachh Vayu scores, bulletin means, fossil capacity.",
        "Swachh_Vayu_Survekshan_2023_2025_all_NCAP_cities_scores_ranks.csv": "Official Swachh Vayu Survekshan scores and ranks, 2023–2025. State is derived.",
        "ONI_ERSSTv5_clean.csv": "NOAA Oceanic Niño Index, ERSSTv5, three-month seasons.",
        "CAMS_OpenMeteo_MODEL_forecast_Hyd_AP_cities_15_20Nov2026.csv": "CAMS and weather forecast extracted 15 Nov 2026 for 15–20 Nov. Model.",
        "APnA_PM25_source_apportionment_50_Indian_airsheds_MODEL.csv": "APnA / UrbanEmissions 2019 CAMx PM2.5 source shares. Model.",
        "WRI_GPPD_v1.3_power_plants_AP_Telangana.geojson": "WRI Global Power Plant Database v1.3 plants in Andhra Pradesh and Telangana. Database frozen at 2021. CC BY 4.0.",
        "FIRMS_VIIRS_NOAA20_AP_TG_OctNov_2018_2025.csv": "NASA FIRMS VIIRS NOAA-20 fire detections, October–November, 2018–2025, clipped to AP and Telangana.",
        "NFHS6_2023_24_district_AP_TG_respiratory_NCD_tobacco_subset.csv": "NFHS-6 (2023–24) and NFHS-5 district indicators for respiratory illness, NCD and tobacco. Survey estimates.",
        "AQLI_2025_gadm2_AP_Telangana_PM25_life_expectancy.csv": "EPIC AQLI 2025, GADM-2 districts of AP and Telangana, annual PM2.5 and life-years lost. Model.",
        "Diwali_PM_spike_by_station_2017_2025.csv": "Derived Diwali versus control-window PM at CAAQMS stations.",
        "NCAP_130_cities_PM10_FY2017_18_vs_FY2025_26_LokSabha_SQ12_20Jul2026.csv": "Lok Sabha SQ 12 (20 Jul 2026) Annexure-IV, PM10 in 130 NCAP cities.",
        "LokSabha_SQ120_27Jul2026_citywise_AQI_category_days_2023_2025_all_cities.csv": "Lok Sabha SQ 120 (27 Jul 2026), city-wise AQI-category day counts, 2023–2025.",
        "District_AQ_health_panel_AP_TG_AQLI_PM25_NFHS5_NFHS6.csv": "Derived district panel: AQLI PM2.5 and NFHS-5/6 indicators. Ecological.",
        "drive_listing_after_reorg_19Nov2026.csv": "File inventory of the Google Drive archive (dataongole@gmail.com) after the 19 Nov 2026 reorganisation. Ids build Drive links.",
    }
    include = []
    for path in sorted(BUNDLE.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".csv", ".geojson"}:
            continue
        include.append(path)
    out_dir = ROOT / "data" / "downloads"
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    manifest = []
    for path in include:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        rel = str(path.relative_to(BUNDLE))
        with path.open(newline="", encoding="utf-8", errors="replace") as handle:
            n_rows = max(0, sum(1 for _ in handle) - 1)
        drive_hits = by_name.get(path.name, [])
        entry = {
            "archive_path": rel,
            "filename": path.name,
            "rows": n_rows,
            "bytes": len(raw),
            "sha256": digest,
            "description": descriptions.get(path.name, "File from the RGUKT Ongole AQI archive."),
            "drive": [
                {
                    "id": hit["id"],
                    "path": hit["parent_path"],
                    "url": f"https://drive.google.com/file/d/{hit['id']}/view",
                }
                for hit in drive_hits
            ],
        }
        if len(raw) >= 400_000:
            target = out_dir / (path.name + ".gz")
            with gzip.open(target, "wb", compresslevel=9) as handle:
                handle.write(raw)
            entry["download"] = "data/downloads/" + target.name
            entry["download_bytes"] = target.stat().st_size
            entry["compressed"] = True
        else:
            target = out_dir / path.name
            target.write_bytes(raw)
            entry["download"] = "data/downloads/" + target.name
            entry["download_bytes"] = len(raw)
            entry["compressed"] = False
        manifest.append(entry)
    # generated spatial files are added after they exist; caller appends
    folder = {
        "name": "AQI_DATA_ALL (start here)",
        "url": "https://drive.google.com/drive/folders/1Q9KlGgUM53I7rSg95I7NhhphVkNkYrjw",
        "note": "Google Drive archive owned by the dataongole@gmail.com workspace. Individual file links are the ids in drive_listing_after_reorg_19Nov2026.csv.",
    }
    return manifest, folder


def coverage_summary(centroids, stations):
    ap_tg = [c for c in centroids if c["emphasis"]]
    no_mon = [c for c in ap_tg if c.get("gap_class") == "no_monitor" or (not c["has_monitor"] and not c.get("bulletin_reports_city"))]
    reported = [c for c in ap_tg if c.get("gap_class") == "bulletin_without_coordinates" or (not c["has_monitor"] and c.get("bulletin_reports_city"))]
    return {
        "national_stations": len(stations),
        "stations_in_pdf": sum(1 for s in stations if s["in_cpcb_pdf"]),
        "stations_ap": sum(1 for s in stations if s["state"] == "Andhra Pradesh"),
        "stations_tg": sum(1 for s in stations if s["state"] == "Telangana"),
        "census2011_districts": len(centroids),
        "ap_tg_districts_2011": len(ap_tg),
        "ap_tg_districts_with_monitor": sum(1 for c in ap_tg if c["has_monitor"]),
        "ap_tg_bulletin_without_coordinates": [
            {"district": c["district"], "state": c["state_now"], "nearest_km": c["nearest_monitor_km"]}
            for c in sorted(reported, key=lambda item: item["district"])
        ],
        "ap_tg_districts_without_monitor": [
            {"district": c["district"], "state": c["state_now"], "nearest_km": c["nearest_monitor_km"]}
            for c in sorted(no_mon, key=lambda item: -(item["nearest_monitor_km"] or 0))
        ],
        "boundary_note": "Monitor presence is a station point within about 2 km of the Census 2011 polygon. Districts were split after 2011, so a parent district can contain a monitor while a new district carved out of it does not.",
    }


def main():
    print("parsing station PDF")
    pdf_rows = parse_cpcb_station_pdf(STATION_PDF)
    if len(pdf_rows) < 350:
        raise SystemExit(f"Expected about 358 PDF stations, parsed {len(pdf_rows)}")
    xkdr_rows = load_xkdr_stations(XKDR_CSV)
    stations = merge_stations(pdf_rows, xkdr_rows)
    bulletin = parse_bulletin_pdf(BULLETIN_PDF)
    attach_bulletin(stations, bulletin)
    dump(ROOT / "data/maps/stations.geojson", stations_geojson(stations))
    print("districts")
    bulletin_names = {norm_place(city["city"]) for city in bulletin["cities"]}
    bulletin_points = []
    for row in read_csv(BUNDLE / "03_Climate_ENSO_Weather/CAMS_OpenMeteo_MODEL_forecast_Hyd_AP_cities_15_20Nov2026.csv"):
        city_name = row["city"].split("(")[0].strip()
        if norm_place(city_name) in bulletin_names:
            bulletin_points.append(Point(float(row["lon"]), float(row["lat"])))
    # de-duplicate identical points
    unique_pts = []
    seen_pts = set()
    for pt in bulletin_points:
        key = (round(pt.x, 3), round(pt.y, 3))
        if key in seen_pts:
            continue
        seen_pts.add(key)
        unique_pts.append(pt)
    centroids, ap_tg = build_districts(stations, bulletin_names, unique_pts)
    dump(ROOT / "data/maps/districts_ap_tg.geojson", ap_tg)
    dump(
        ROOT / "data/maps/district_centroids.json",
        {
            "source": "DataMeet Census 2011 district boundaries, simplified and reduced to representative points. CC BY 4.0. https://github.com/datameet/maps",
            "districts": centroids,
        },
    )
    grid = gap_grid(ap_tg, stations)
    dump(ROOT / "data/maps/gap_grid_ap_tg.geojson", grid)
    summary = coverage_summary(centroids, stations)
    dump(ROOT / "data/maps/coverage_summary.json", summary, pretty=True)

    print("calibration")
    city_means, monthly = load_station_days()
    cams = load_cams()
    calibration = fit_calibration(city_means, cams)
    dump(ROOT / "data/cache/calibration.json", calibration, pretty=True)
    dump(ROOT / "data/charts/station_monthly.json", station_month_payload(monthly))

    print("series and pages")
    bulletin_doc = bulletin_series()
    dump(ROOT / "data/charts/bulletin_daily.json", bulletin_doc)
    dump(ROOT / "data/charts/ongole.json", ongole_payload(), pretty=True)
    dump(ROOT / "data/charts/ncap.json", ncap_payload())
    dump(ROOT / "data/charts/health.json", health_payload())
    dump(ROOT / "data/charts/fires.json", fires_and_plants())
    dump(ROOT / "data/charts/enso.json", enso_payload(bulletin_doc), pretty=True)
    dump(ROOT / "data/charts/events.json", diwali_and_lockdown())

    forecast_rows = read_csv(BUNDLE / "03_Climate_ENSO_Weather/CAMS_OpenMeteo_MODEL_forecast_Hyd_AP_cities_15_20Nov2026.csv")
    # one row per city is enough; file has many dates
    first_by_city = []
    seen = set()
    for row in forecast_rows:
        if row["city"] in seen:
            continue
        seen.add(row["city"])
        first_by_city.append(row)
    places = build_places(stations, centroids, first_by_city)
    dump(ROOT / "data/cities.json", {"places": places}, pretty=True)
    donors = donor_seed(stations)
    dump(ROOT / "data/cache/donors.json", {"bulletin_date": bulletin["date"], "donors": donors})
    dump(
        ROOT / "data/cache/bulletin_latest.json",
        {
            "date": bulletin["date"],
            "source": "CPCB national daily AQI bulletin PDF",
            "source_url": f"https://cpcb.gov.in/upload/Downloads/AQI_Bulletin_{bulletin['date'].replace('-', '')}.pdf",
            "cities": bulletin["cities"],
            "note": "City-level measured AQI. It is not a reading from each individual station.",
        },
    )
    plants_src = BUNDLE / "03_Climate_ENSO_Weather/emission_sources/WRI_GPPD_v1.3_power_plants_AP_Telangana.geojson"
    shutil.copyfile(plants_src, ROOT / "data/maps/power_plants.geojson")

    print("downloads")
    manifest, folder = write_downloads()
    manifest.append(
        {
            "archive_path": "generated/stations.geojson",
            "filename": "stations_national.geojson",
            "rows": len(stations),
            "bytes": (ROOT / "data/maps/stations.geojson").stat().st_size,
            "sha256": hashlib.sha256((ROOT / "data/maps/stations.geojson").read_bytes()).hexdigest(),
            "description": "National monitor list used by the map: the 18 Nov 2026 CPCB PDF plus XKDR directory stations that the PDF does not contain.",
            "download": "data/maps/stations.geojson",
            "download_bytes": (ROOT / "data/maps/stations.geojson").stat().st_size,
            "compressed": False,
            "drive": [],
        }
    )
    dump(
        ROOT / "data/dictionary.json",
        {"drive_folder": folder, "files": manifest, "coverage": summary},
        pretty=True,
    )
    print("build_site_data done")


if __name__ == "__main__":
    main()

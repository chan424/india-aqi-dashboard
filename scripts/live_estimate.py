"""Turn hourly Open-Meteo fields into a CPCB AQI estimate.

The historical calibration, when the build has selected one, is applied to
concentrations before the sub-index. An inverse-distance residual from other
cities' CPCB bulletin values is added only when the calibration file says so.
"""

from __future__ import annotations

import math

from cpcb_aqi import aqi_from_concentrations, category_of

OPEN_METEO_AQ = "https://air-quality-api.open-meteo.com/v1/air-quality"
OPEN_METEO_WX = "https://api.open-meteo.com/v1/forecast"


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _clean(series):
    out = []
    for value in series or []:
        if value is None:
            out.append(None)
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            out.append(None)
            continue
        if number != number:
            out.append(None)
        else:
            out.append(number)
    return out


def _tail(series, hours):
    values = _clean(series)
    end = None
    for index in range(len(values) - 1, -1, -1):
        if values[index] is not None:
            end = index
            break
    if end is None:
        return []
    start = max(0, end - hours + 1)
    return values[start : end + 1]


def mean_last(series, hours=24, minimum=16):
    window = _tail(series, hours)
    present = [value for value in window if value is not None]
    if len(present) < minimum:
        return None, len(present)
    return sum(present) / len(present), len(present)


def sum_last(series, hours=24):
    window = _tail(series, hours)
    present = [value for value in window if value is not None]
    if not present:
        return None
    return sum(present)


def max_rolling_mean(series, window, span_hours=24, minimum_windows=1):
    values = _clean(series)
    end = None
    for index in range(len(values) - 1, -1, -1):
        if values[index] is not None:
            end = index
            break
    if end is None:
        return None
    start = max(0, end - span_hours + 1)
    best = None
    count = 0
    for index in range(start + window - 1, end + 1):
        chunk = values[index - window + 1 : index + 1]
        if any(value is None for value in chunk):
            continue
        avg = sum(chunk) / window
        count += 1
        if best is None or avg > best:
            best = avg
    if count < minimum_windows:
        return None
    return best


def apply_linear(raw, spec):
    if raw is None or not spec:
        return raw
    value = float(spec.get("a") or 0) + float(spec.get("b") or 1) * raw
    for term, coef in (spec.get("extra") or {}).items():
        # extras are filled by the caller via spec["_features"]
        pass
    features = spec.get("_features") or {}
    for term, coef in (spec.get("extra") or {}).items():
        feature = features.get(term)
        if feature is None:
            return raw  # refuse a partial weather correction
        value += float(coef) * feature
    return max(0.0, value)


def concentrations_from_hourly(hourly: dict, calibration: dict | None) -> dict:
    """hourly keys: pm25, pm10, no2, o3, co_ug, so2, rh, wind_ms, rain."""
    calibration = calibration or {}
    specs = calibration.get("pollutant_calibration") or {}
    use = bool(calibration.get("use_pollutant_calibration"))
    pm25, n_pm25 = mean_last(hourly.get("pm25"), 24, 16)
    pm10, n_pm10 = mean_last(hourly.get("pm10"), 24, 16)
    no2, _ = mean_last(hourly.get("no2"), 24, 16)
    so2, _ = mean_last(hourly.get("so2"), 24, 16)
    rh, _ = mean_last(hourly.get("rh"), 24, 16)
    wind, _ = mean_last(hourly.get("wind_ms"), 24, 16)
    rain = sum_last(hourly.get("rain"), 24)
    o3_8h = max_rolling_mean(hourly.get("o3"), 8, 24, 1)
    co_8h_ug = max_rolling_mean(hourly.get("co_ug"), 8, 24, 1)
    co_8h = None if co_8h_ug is None else co_8h_ug / 1000.0
    features = {"rh": rh, "ws": wind, "rain": 0.0 if rain is None else rain}
    raw = {"pm25": pm25, "pm10": pm10, "no2": no2, "so2": so2, "o3": o3_8h, "co": co_8h}
    corrected = {}
    for key, value in raw.items():
        spec = dict(specs.get(key) or {})
        if use and spec:
            spec["_features"] = features
            corrected[key] = apply_linear(value, spec)
        else:
            corrected[key] = value
    blh, _ = mean_last(hourly.get("blh"), 24, 8)
    return {
        "raw": raw,
        "calibrated": corrected,
        "hours_pm25": n_pm25,
        "hours_pm10": n_pm10,
        "weather": {
            "rh_24h_mean_pct": None if rh is None else round(rh, 1),
            "wind_24h_mean_ms": None if wind is None else round(wind, 2),
            "rain_24h_mm": None if rain is None else round(rain, 2),
            "blh_24h_mean_m": None if blh is None else round(blh, 0),
            "ventilation_m2s": None
            if blh is None or wind is None
            else round(blh * wind, 0),
        },
    }


def idw_correction(lat, lon, donors, power, radius_km, floor_km, exclude_id=None):
    nearest = None
    nearest_name = None
    num = 0.0
    den = 0.0
    used = []
    for donor in donors:
        if exclude_id and donor.get("id") == exclude_id:
            continue
        dist = haversine_km(lat, lon, donor["lat"], donor["lon"])
        if nearest is None or dist < nearest:
            nearest = dist
            nearest_name = donor.get("name")
        if dist > radius_km:
            continue
        weight = 1.0 / (max(dist, floor_km) ** power)
        num += weight * donor["delta"]
        den += weight
        used.append({"name": donor.get("name"), "km": round(dist, 1), "delta": round(donor["delta"], 1)})
    if den == 0:
        return 0.0, nearest, nearest_name, []
    used.sort(key=lambda item: item["km"])
    return num / den, nearest, nearest_name, used[:5]


def estimate_place(place, hourly, calibration, donors):
    calibration = calibration or {}
    packed = concentrations_from_hourly(hourly, calibration)
    result = aqi_from_concentrations(packed["calibrated"])
    model_aqi = result["aqi"]
    affine = calibration.get("aqi_affine") if calibration.get("use_aqi_affine") else None
    if model_aqi is not None and affine:
        model_aqi = float(affine["a"]) + float(affine["b"]) * model_aqi
        model_aqi = min(500.0, max(0.0, model_aqi))
    idw = calibration.get("idw") or {}
    use_idw = bool(calibration.get("use_idw")) and model_aqi is not None
    correction = 0.0
    nearest = None
    nearest_name = None
    used = []
    if use_idw:
        correction, nearest, nearest_name, used = idw_correction(
            place["lat"],
            place["lon"],
            donors,
            power=float(idw.get("power", 2)),
            radius_km=float(idw.get("radius_km", 300)),
            floor_km=float(idw.get("floor_km", 15)),
            exclude_id=place.get("id"),
        )
    elif donors:
        correction, nearest, nearest_name, used = idw_correction(
            place["lat"],
            place["lon"],
            donors,
            power=2,
            radius_km=0,  # distance only
            floor_km=15,
            exclude_id=place.get("id"),
        )
        correction = 0.0
        used = []
    estimated = None if model_aqi is None else min(500.0, max(0.0, model_aqi + correction))
    method_bits = ["Open-Meteo CAMS hourly fields", "CPCB sub-index (worst pollutant)"]
    if calibration.get("use_pollutant_calibration"):
        method_bits.append("linear bias correction fitted on 2022–2024 station days")
    if calibration.get("use_aqi_affine"):
        method_bits.append("AQI-scale affine correction")
    if use_idw and used:
        method_bits.append("inverse-distance residual from other cities' CPCB bulletin AQI")
    return {
        "id": place.get("id"),
        "name": place.get("name"),
        "state": place.get("state"),
        "kind": place.get("kind"),
        "lat": place.get("lat"),
        "lon": place.get("lon"),
        "label": "Estimated (model)",
        "aqi": None if estimated is None else int(round(estimated)),
        "aqi_unrounded": None if estimated is None else round(estimated, 1),
        "category": category_of(estimated),
        "dominant": result["dominant"],
        "official_minimum_met": result["official_minimum_met"],
        "sub_indices": [
            {
                "pollutant": piece["pollutant"],
                "concentration": None
                if piece["concentration"] is None
                else round(piece["concentration"], 2),
                "sub_index": round(piece["sub_index"], 1),
            }
            for piece in result["sub_indices"]
        ],
        "raw_concentrations": {
            key: None if value is None else round(value, 2) for key, value in packed["raw"].items()
        },
        "weather": packed["weather"],
        "idw_correction": round(correction, 1) if used else 0,
        "idw_donors": used,
        "nearest_monitor_km": None if nearest is None else round(nearest, 1),
        "nearest_monitor": nearest_name,
        "method": "; ".join(method_bits),
        "hours_pm25": packed["hours_pm25"],
    }

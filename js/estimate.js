/* Live estimate from Open-Meteo hourly fields. Mirrors scripts/live_estimate.py. */
(function (root, factory) {
  const api = factory(root.AQI);
  if (typeof module === "object" && module.exports) module.exports = api;
  root.Estimate = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (AQI) {
  function clean(series) {
    return (series || []).map((value) => {
      const n = Number(value);
      return Number.isFinite(n) ? n : null;
    });
  }

  function tail(series, hours) {
    const values = clean(series);
    let end = -1;
    for (let i = values.length - 1; i >= 0; i -= 1) {
      if (values[i] != null) { end = i; break; }
    }
    if (end < 0) return [];
    return values.slice(Math.max(0, end - hours + 1), end + 1);
  }

  function meanLast(series, hours, minimum) {
    const window = tail(series, hours);
    const present = window.filter((v) => v != null);
    if (present.length < minimum) return [null, present.length];
    return [present.reduce((a, b) => a + b, 0) / present.length, present.length];
  }

  function sumLast(series, hours) {
    const present = tail(series, hours).filter((v) => v != null);
    if (!present.length) return null;
    return present.reduce((a, b) => a + b, 0);
  }

  function maxRolling(series, window, span) {
    const values = clean(series);
    let end = -1;
    for (let i = values.length - 1; i >= 0; i -= 1) {
      if (values[i] != null) { end = i; break; }
    }
    if (end < 0) return null;
    const start = Math.max(0, end - span + 1);
    let best = null;
    for (let i = start + window - 1; i <= end; i += 1) {
      const chunk = values.slice(i - window + 1, i + 1);
      if (chunk.some((v) => v == null)) continue;
      const avg = chunk.reduce((a, b) => a + b, 0) / window;
      if (best == null || avg > best) best = avg;
    }
    return best;
  }

  function applyLinear(raw, spec, features) {
    if (raw == null || !spec) return raw;
    let value = Number(spec.a || 0) + Number(spec.b || 1) * raw;
    const extra = spec.extra || {};
    const keys = Object.keys(extra);
    for (const key of keys) {
      if (features[key] == null) return raw;
      value += Number(extra[key]) * features[key];
    }
    return Math.max(0, value);
  }

  function fromHourly(hourly, calibration) {
    const specs = (calibration && calibration.pollutant_calibration) || {};
    const use = !!(calibration && calibration.use_pollutant_calibration);
    const [pm25] = meanLast(hourly.pm25, 24, 16);
    const [pm10] = meanLast(hourly.pm10, 24, 16);
    const [no2] = meanLast(hourly.no2, 24, 16);
    const [so2] = meanLast(hourly.so2, 24, 16);
    const [rh] = meanLast(hourly.rh, 24, 16);
    const [wind] = meanLast(hourly.wind_ms, 24, 16);
    const rain = sumLast(hourly.rain, 24);
    const o3 = maxRolling(hourly.o3, 8, 24);
    const coUg = maxRolling(hourly.co_ug, 8, 24);
    const raw = {
      pm25, pm10, no2, so2, o3,
      co: coUg == null ? null : coUg / 1000
    };
    const features = { rh, ws: wind, rain: rain == null ? 0 : rain };
    const calibrated = {};
    Object.keys(raw).forEach((key) => {
      calibrated[key] = use && specs[key] ? applyLinear(raw[key], specs[key], features) : raw[key];
    });
    const [blh] = meanLast(hourly.blh, 24, 8);
    return {
      raw, calibrated,
      weather: {
        rh_24h_mean_pct: rh == null ? null : Math.round(rh * 10) / 10,
        wind_24h_mean_ms: wind == null ? null : Math.round(wind * 100) / 100,
        rain_24h_mm: rain == null ? null : Math.round(rain * 100) / 100,
        blh_24h_mean_m: blh == null ? null : Math.round(blh),
        ventilation_m2s: blh == null || wind == null ? null : Math.round(blh * wind)
      }
    };
  }

  async function fetchHourly(lat, lon) {
    const aqUrl = "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=" + lat +
      "&longitude=" + lon +
      "&hourly=pm2_5,pm10,nitrogen_dioxide,ozone,sulphur_dioxide,carbon_monoxide&timezone=Asia%2FKolkata&forecast_days=2&past_days=1";
    const wxUrl = "https://api.open-meteo.com/v1/forecast?latitude=" + lat +
      "&longitude=" + lon +
      "&hourly=relative_humidity_2m,wind_speed_10m,precipitation,boundary_layer_height&wind_speed_unit=ms&timezone=Asia%2FKolkata&forecast_days=2&past_days=1";
    const [aqRes, wxRes] = await Promise.all([fetch(aqUrl), fetch(wxUrl)]);
    if (!aqRes.ok || !wxRes.ok) throw new Error("Open-Meteo request failed");
    const aq = await aqRes.json();
    const wx = await wxRes.json();
    return {
      pm25: aq.hourly.pm2_5,
      pm10: aq.hourly.pm10,
      no2: aq.hourly.nitrogen_dioxide,
      o3: aq.hourly.ozone,
      so2: aq.hourly.sulphur_dioxide,
      co_ug: aq.hourly.carbon_monoxide,
      rh: wx.hourly.relative_humidity_2m,
      wind_ms: wx.hourly.wind_speed_10m,
      rain: wx.hourly.precipitation,
      blh: wx.hourly.boundary_layer_height
    };
  }

  function estimate(hourly, calibration) {
    const packed = fromHourly(hourly, calibration);
    const result = AQI.aqiFromConcentrations(packed.calibrated);
    return {
      label: "Estimated (model)",
      aqi: result.aqi_rounded,
      category: result.category,
      dominant: result.dominant,
      official_minimum_met: result.official_minimum_met,
      sub_indices: result.sub_indices,
      raw: packed.raw,
      calibrated: packed.calibrated,
      weather: packed.weather,
      method: calibration && calibration.use_pollutant_calibration
        ? "Open-Meteo CAMS; CPCB sub-index; linear bias correction fitted on 2022–2024 station days"
        : "Open-Meteo CAMS; CPCB sub-index"
    };
  }

  return { fromHourly, fetchHourly, estimate };
});

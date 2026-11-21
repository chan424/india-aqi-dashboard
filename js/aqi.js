/* CPCB National Air Quality Index. Keep in step with scripts/cpcb_aqi.py. */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.AQI = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const BREAKPOINTS = {
    pm25: [[0, 30, 0, 50], [31, 60, 51, 100], [61, 90, 101, 200], [91, 120, 201, 300], [121, 250, 301, 400], [251, 380, 401, 500]],
    pm10: [[0, 50, 0, 50], [51, 100, 51, 100], [101, 250, 101, 200], [251, 350, 201, 300], [351, 430, 301, 400], [431, 510, 401, 500]],
    no2: [[0, 40, 0, 50], [41, 80, 51, 100], [81, 180, 101, 200], [181, 280, 201, 300], [281, 400, 301, 400], [401, 520, 401, 500]],
    o3: [[0, 50, 0, 50], [51, 100, 51, 100], [101, 168, 101, 200], [169, 208, 201, 300], [209, 748, 301, 400], [749, 1288, 401, 500]],
    co: [[0, 1, 0, 50], [1.1, 2, 51, 100], [2.1, 10, 101, 200], [10.1, 17, 201, 300], [17.1, 34, 301, 400], [34.1, 51, 401, 500]],
    so2: [[0, 40, 0, 50], [41, 80, 51, 100], [81, 380, 101, 200], [381, 800, 201, 300], [801, 1600, 301, 400], [1601, 2400, 401, 500]],
    nh3: [[0, 200, 0, 50], [201, 400, 51, 100], [401, 800, 101, 200], [801, 1200, 201, 300], [1201, 1800, 301, 400], [1801, 2400, 401, 500]]
  };
  const LABELS = {
    pm25: "PM2.5", pm10: "PM10", no2: "NO2", o3: "O3", co: "CO", so2: "SO2", nh3: "NH3"
  };
  const UNITS = { pm25: "µg/m³", pm10: "µg/m³", no2: "µg/m³", o3: "µg/m³", co: "mg/m³", so2: "µg/m³", nh3: "µg/m³" };

  function truncate(pollutant, value) {
    if (pollutant === "co") return Math.floor(value * 10 + 1e-9) / 10;
    return Math.floor(value + 1e-9);
  }

  function subIndex(pollutant, concentration) {
    if (concentration == null || Number.isNaN(concentration) || concentration < 0) return null;
    const bands = BREAKPOINTS[pollutant];
    const c = truncate(pollutant, concentration);
    if (c <= bands[0][0]) return 0;
    for (const [blo, bhi, ilo, ihi] of bands) {
      if (c < blo) return ilo;
      if (c <= bhi) {
        if (bhi === blo) return ilo;
        return ((ihi - ilo) / (bhi - blo)) * (c - blo) + ilo;
      }
    }
    const [blo, bhi, ilo, ihi] = bands[bands.length - 1];
    return Math.min(500, ((ihi - ilo) / (bhi - blo)) * (c - blo) + ilo);
  }

  function categoryOf(aqi) {
    if (aqi == null || Number.isNaN(aqi)) return null;
    const rounded = Math.round(aqi);
    if (rounded <= 50) return "Good";
    if (rounded <= 100) return "Satisfactory";
    if (rounded <= 200) return "Moderate";
    if (rounded <= 300) return "Poor";
    if (rounded <= 400) return "Very Poor";
    return "Severe";
  }

  function aqiFromConcentrations(values) {
    const pieces = [];
    Object.keys(BREAKPOINTS).forEach((key) => {
      if (values[key] == null) return;
      const ip = subIndex(key, values[key]);
      if (ip == null) return;
      pieces.push({ pollutant: key, concentration: values[key], sub_index: ip });
    });
    pieces.sort((a, b) => b.sub_index - a.sub_index);
    if (!pieces.length) return { aqi: null, category: null, dominant: null, sub_indices: [], official_minimum_met: false };
    const keys = new Set(pieces.map((p) => p.pollutant));
    return {
      aqi: pieces[0].sub_index,
      aqi_rounded: Math.round(pieces[0].sub_index),
      category: categoryOf(pieces[0].sub_index),
      dominant: pieces[0].pollutant,
      sub_indices: pieces,
      official_minimum_met: keys.size >= 3 && (keys.has("pm25") || keys.has("pm10"))
    };
  }

  function color(aqi) {
    if (aqi == null || Number.isNaN(Number(aqi))) return "#8d867c";
    const v = Number(aqi);
    if (v <= 50) return "#1f8a4c";
    if (v <= 100) return "#8fbf3f";
    if (v <= 200) return "#e2b400";
    if (v <= 300) return "#ef8a1a";
    if (v <= 400) return "#e23d2b";
    return "#7a1530";
  }

  return { BREAKPOINTS, LABELS, UNITS, subIndex, categoryOf, aqiFromConcentrations, color };
});

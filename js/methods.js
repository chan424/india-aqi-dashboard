Promise.all([
  fetch("data/cache/calibration.json").then((r) => r.json()),
  fetch("data/cache/meta.json").then((r) => r.json())
]).then(([cal, meta]) => {
  const aq = cal.aqi_vs_bulletin;
  function cell(block, key) {
    const value = block && block[key];
    return value == null ? "—" : value;
  }
  const rows = [
    ["2025 raw CAMS", aq.test_2025_raw],
    ["2025 after pollutant calibration", aq.test_2025_calibrated],
    ["2025 calibration + IDW, leave-one-city-out", aq.test_2025_idw_leave_one_city_out],
    ["2026 raw CAMS (not used to choose)", aq.confirm_2026_raw],
    ["2026 calibrated (not used to choose)", aq.confirm_2026_calibrated]
  ];
  document.querySelector("#metrics tbody").innerHTML = rows.map(([name, block]) =>
    "<tr><td>" + name + "</td><td>" + cell(block, "n") + "</td><td>" + cell(block, "mae") + "</td><td>" +
    cell(block, "rmse") + "</td><td>" + cell(block, "bias_pred_minus_obs") + "</td><td>" + cell(block, "r") +
    "</td><td>" + cell(block, "exact_category_pct") + "</td><td>" + cell(block, "within_one_category_pct") + "</td></tr>"
  ).join("");
  const pol = cal.pollutants || {};
  document.querySelector("#pol tbody").innerHTML = Object.keys(pol).map((key) => {
    const row = pol[key];
    const coef = (cal.pollutant_calibration_fitted_even_if_unused || {})[key] || {};
    const weather = row.weather_test || {};
    return "<tr><td>" + key + "</td><td>" + (coef.a ?? "—") + "</td><td>" + (coef.b ?? "—") + "</td><td>" +
      cell(row.raw_test, "rmse") + "</td><td>" + cell(row.linear_test, "rmse") + "</td><td>" +
      cell(row.linear_test, "r") + "</td><td>" + (weather.rmse ?? "—") + "</td><td>" + (row.selected || "") + "</td></tr>";
  }).join("");
  document.getElementById("choice").textContent =
    "Pollutant calibration is " + (cal.use_pollutant_calibration ? "on" : "off") +
    " because 2025 bulletin RMSE " + (cal.use_pollutant_calibration ? "fell" : "did not fall") +
    ". IDW is " + (cal.use_idw ? "on" : "off") +
    " because leave-one-city-out RMSE " + (cal.use_idw ? "fell further" : "did not fall") +
    ". Weather terms were tested and not selected: PM2.5 2025 RMSE was " +
    ((pol.pm25 && pol.pm25.weather_test && pol.pm25.weather_test.rmse) || "—") +
    " with RH, wind and rain, against " + ((pol.pm25 && pol.pm25.linear_test && pol.pm25.linear_test.rmse) || "—") +
    " for CAMS alone. The displayed ventilation index is context, not an input to the number.";
  document.getElementById("fit-cities").textContent = (cal.fit.cities || []).join(", ");
  document.getElementById("freshness").textContent = "Estimates cached " + (meta.estimates_updated || "—") +
    ". Bulletin " + (meta.bulletin_date || "—") + ". Station feed: " + (meta.rss_status || "—") + ".";
});

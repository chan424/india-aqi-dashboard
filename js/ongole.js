fetch("data/charts/ongole.json").then((r) => r.json()).then((doc) => {
  const days = doc.days;
  const labels = days.map((d) => d.date);
  lineChart(document.getElementById("ongole-aqi"), labels, [
    { label: "CPCB bulletin AQI (observed, days published)", data: days.map((d) => d.bulletin_aqi) },
    { label: "CAMS PM2.5 µg/m³ (model)", data: days.map((d) => d.pm25) },
    { label: "CAMS PM10 µg/m³ (model)", data: days.map((d) => d.pm10) }
  ], "AQI or µg/m³");
  lineChart(document.getElementById("ongole-wx"), labels, [
    { label: "ERA5 boundary-layer height, m (reanalysis)", data: days.map((d) => d.blh) },
    { label: "ERA5 wind, m/s × 100", data: days.map((d) => d.wind == null ? null : Math.round(d.wind * 100)) },
    { label: "ERA5 rain, mm", data: days.map((d) => d.rain) }
  ], "Mixed units, see legend");
  document.querySelector("#ongole-table tbody").innerHTML = days.map((d) =>
    "<tr><td>" + d.date + "</td><td>" + (d.bulletin_aqi ?? "—") + "</td><td>" + (d.category || "—") +
    "</td><td>" + d.pm25 + "</td><td>" + d.pm10 + "</td><td>" + Math.round(d.blh) + "</td><td>" + d.rain + "</td></tr>"
  ).join("");
  document.getElementById("ongole-note").textContent = doc.coordinates_note;
});

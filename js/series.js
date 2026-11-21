(function () {
  const citySelect = document.getElementById("city");
  const fromInput = document.getElementById("from");
  const toInput = document.getElementById("to");
  const stationSelect = document.getElementById("station");
  const pollutantSelect = document.getElementById("pollutant");
  let bulletin, stations, events;
  let cityChart, stationChart, diwaliChart;

  function destroy(chart) { if (chart) chart.destroy(); }

  function drawCity() {
    const city = bulletin.cities.find((row) => row.city === citySelect.value);
    if (!city) return;
    const from = fromInput.value || "2015-01-01";
    const to = toInput.value || "2026-12-31";
    const labels = [];
    const data = [];
    city.dates.forEach((date, i) => {
      if (date >= from && date <= to && city.aqi[i] != null) {
        labels.push(date);
        data.push(city.aqi[i]);
      }
    });
    destroy(cityChart);
    cityChart = lineChart(document.getElementById("city-chart"), labels, [{ label: city.city + " bulletin AQI (observed)", data }], "AQI");
    document.getElementById("city-note").textContent = data.length + " bulletin days shown. Observed CPCB city AQI, not a model.";
    const start = Math.max(0, labels.length - 12);
    const rows = labels.slice(start).map((date, i) => "<tr><td>" + date + "</td><td>" + data[start + i] + "</td></tr>");
    document.querySelector("#city-table tbody").innerHTML = rows.join("");
  }

  function drawStation() {
    const station = stations.stations.find((row) => row.id === stationSelect.value);
    const key = pollutantSelect.value;
    if (!station) return;
    destroy(stationChart);
    stationChart = lineChart(
      document.getElementById("station-chart"),
      station.month,
      [{ label: station.name + " " + key + " monthly mean", data: station[key] }],
      key === "co" ? "mg/m³" : "µg/m³"
    );
  }

  function drawDiwali() {
    const city = citySelect.value;
    const rows = events.diwali.filter((row) => row.city === city && row.pm25_diwali != null);
    destroy(diwaliChart);
    diwaliChart = new Chart(document.getElementById("diwali-chart"), {
      type: "bar",
      data: {
        labels: rows.map((row) => row.year),
        datasets: [
          { label: "Diwali PM2.5 (derived)", data: rows.map((row) => row.pm25_diwali), backgroundColor: "#8c3b1e" },
          { label: "Control window PM2.5", data: rows.map((row) => row.pm25_control), backgroundColor: "#0e3d3b" }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false }
    });
    document.getElementById("diwali-note").textContent = rows.length
      ? "Derived from CAAQMS daily means in the archive. Not a regulatory festival bulletin."
      : "No Diwali rows for this city in the archive table.";
  }

  function fillLockdown() {
    const body = document.querySelector("#lock-table tbody");
    body.innerHTML = events.lockdown_era5_long_running.map((row) =>
      "<tr><td>" + escapeHtml(row.station) + "</td><td>" + escapeHtml(row.pollutant) + "</td><td>" +
      row.lock_pct_mean + "%</td><td>" + row.placebo_pct_mean + "%</td></tr>"
    ).join("");
  }

  Promise.all([
    fetch("data/charts/bulletin_daily.json").then((r) => r.json()),
    fetch("data/charts/station_monthly.json").then((r) => r.json()),
    fetch("data/charts/events.json").then((r) => r.json())
  ]).then(([b, s, e]) => {
    bulletin = b;
    stations = s;
    events = e;
    citySelect.innerHTML = b.cities.map((c) => '<option>' + escapeHtml(c.city) + '</option>').join("");
    const hyd = b.cities.find((c) => c.city === "Hyderabad");
    if (hyd) citySelect.value = "Hyderabad";
    const ordered = s.stations.slice().sort((a, b) => {
      const rank = (st) => (st.city === "Hyderabad" ? 0 : 1);
      return rank(a) - rank(b) || a.city.localeCompare(b.city) || a.name.localeCompare(b.name);
    });
    stationSelect.innerHTML = ordered.map((st) =>
      '<option value="' + st.id + '">' + escapeHtml(st.city + " — " + st.name) + "</option>"
    ).join("");
    fromInput.value = "2024-01-01";
    toInput.value = "2026-11-15";
    drawCity();
    drawStation();
    drawDiwali();
    fillLockdown();
    citySelect.addEventListener("change", () => { drawCity(); drawDiwali(); });
    fromInput.addEventListener("change", drawCity);
    toInput.addEventListener("change", drawCity);
    stationSelect.addEventListener("change", drawStation);
    pollutantSelect.addEventListener("change", drawStation);
  });
})();

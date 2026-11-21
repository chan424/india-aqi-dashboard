fetch("data/charts/enso.json").then((r) => r.json()).then((doc) => {
  const labels = doc.series.map((r) => r.year);
  new Chart(document.getElementById("enso-chart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Hyderabad OND mean bulletin AQI", data: doc.series.map((r) => r.Hyderabad), borderColor: "#0e3d3b", yAxisID: "y", tension: 0.15, pointRadius: 3 },
        { label: "Visakhapatnam OND mean bulletin AQI", data: doc.series.map((r) => r.Visakhapatnam), borderColor: "#8c3b1e", yAxisID: "y", tension: 0.15, pointRadius: 3 },
        { label: "NOAA ONI OND (°C)", data: doc.series.map((r) => r.oni_ond), borderColor: "#1d6a63", borderDash: [4, 3], yAxisID: "y1", tension: 0.15, pointRadius: 3 }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        y: { position: "left", title: { display: true, text: "Bulletin AQI" } },
        y1: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "ONI °C" } }
      }
    }
  });
  document.querySelector("#enso-table tbody").innerHTML = doc.correlations.map((row) =>
    "<tr><td>" + escapeHtml(row.city) + "</td><td>" + row.n + "</td><td>" + (row.r ?? "—") + "</td><td>" + (row.p ?? "—") + "</td></tr>"
  ).join("");
  document.getElementById("enso-note").textContent = doc.note;
});

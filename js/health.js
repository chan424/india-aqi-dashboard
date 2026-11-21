fetch("data/charts/health.json").then((r) => r.json()).then((doc) => {
  const rows = doc.panel.filter((r) => r.pm2023 != null && r.ari6 != null);
  new Chart(document.getElementById("scatter"), {
    type: "scatter",
    data: {
      datasets: ["Andhra Pradesh", "Telangana"].map((state, i) => ({
        label: state + " (ecological)",
        data: rows.filter((r) => r.state === state).map((r) => ({ x: r.pm2023, y: r.ari6, district: r.district })),
        backgroundColor: i === 0 ? "#8c3b1e" : "#0e3d3b"
      }))
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      parsing: false,
      scales: {
        x: { title: { display: true, text: "AQLI PM2.5 2023, µg/m³ (model)" } },
        y: { title: { display: true, text: "NFHS-6 child ARI, 2-week % (survey)" } }
      },
      plugins: {
        tooltip: {
          callbacks: { label: (ctx) => ctx.raw.district + ": PM2.5 " + ctx.raw.x + ", ARI " + ctx.raw.y + "%" }
        }
      }
    }
  });
  const ranked = doc.panel.filter((r) => r.llpp2023 != null).sort((a, b) => b.llpp2023 - a.llpp2023);
  new Chart(document.getElementById("llpp"), {
    type: "bar",
    data: {
      labels: ranked.map((r) => r.district),
      datasets: [{
        label: "Life-years lost vs WHO guideline, 2023 (AQLI model)",
        data: ranked.map((r) => r.llpp2023),
        backgroundColor: ranked.map((r) => r.state === "Telangana" ? "#0e3d3b" : "#8c3b1e")
      }]
    },
    options: { responsive: true, maintainAspectRatio: false, indexAxis: "y", plugins: { legend: { display: false } } }
  });
  document.querySelector("#health-table tbody").innerHTML = doc.panel.map((r) =>
    "<tr><td>" + escapeHtml(r.district) + "</td><td>" + escapeHtml(r.state) + "</td><td>" + (r.pm2023 ?? "—") +
    "</td><td>" + (r.llpp2023 ?? "—") + "</td><td>" + (r.ari6 ?? "—") + "</td><td>" + (r.ari5 ?? "—") +
    "</td><td>" + (r.tobacco_men6 ?? "—") + "</td></tr>"
  ).join("");
  document.getElementById("health-note").textContent = doc.note;
});

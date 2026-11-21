fetch("data/charts/ncap.json").then((r) => r.json()).then((doc) => {
  const stateSelect = document.getElementById("state");
  const states = Array.from(new Set(doc.pm10.map((r) => r.state))).sort();
  stateSelect.innerHTML = '<option value="APTG">Andhra Pradesh and Telangana</option>' +
    states.map((s) => '<option>' + escapeHtml(s) + '</option>').join("");
  let pmChart, svsChart, dayChart;

  function selectedPm() {
    if (stateSelect.value === "APTG") return doc.pm10.filter((r) => r.state === "Andhra Pradesh" || r.state === "Telangana");
    return doc.pm10.filter((r) => r.state === stateSelect.value);
  }
  function drawPm() {
    const rows = selectedPm();
    if (pmChart) pmChart.destroy();
    pmChart = new Chart(document.getElementById("pm-chart"), {
      type: "bar",
      data: {
        labels: rows.map((r) => r.city),
        datasets: [
          { label: "PM10 FY2017-18 (official)", data: rows.map((r) => r.pm10_2017), backgroundColor: "#c4a35a" },
          { label: "PM10 FY2025-26 (official)", data: rows.map((r) => r.pm10_2025), backgroundColor: "#0e3d3b" }
        ]
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { title: { display: true, text: "µg/m³" } } } }
    });
    document.querySelector("#pm-table tbody").innerHTML = rows.map((r) =>
      "<tr><td>" + escapeHtml(r.city) + "</td><td>" + escapeHtml(r.state) + "</td><td>" + r.pm10_2017 +
      "</td><td>" + r.pm10_2025 + "</td><td>" + r.pct_improvement + "</td><td>" + (r.meets_60 ? "Yes" : "No") + "</td></tr>"
    ).join("");
  }
  function drawSvs() {
    const focus = new Set(["Hyderabad", "Vijayawada", "Visakhapatnam", "Guntur", "Kurnool", "Nellore", "Rajahmundry", "Srikakulam", "Ongole", "Tirupati", "Kakinada", "Kadapa", "Anantapur", "Chittoor", "Eluru", "Nalgonda", "Warangal", "Karimnagar"]);
    const rows = doc.svs.filter((r) => focus.has(r.city));
    const years = [2023, 2024, 2025];
    const cities = Array.from(new Set(rows.map((r) => r.city)));
    if (svsChart) svsChart.destroy();
    svsChart = new Chart(document.getElementById("svs-chart"), {
      type: "line",
      data: {
        labels: years.map(String),
        datasets: cities.map((city, i) => ({
          label: city,
          data: years.map((year) => {
            const hit = rows.find((r) => r.city === city && r.year === year);
            return hit ? hit.score : null;
          }),
          borderColor: CHART_COLOURS[i % CHART_COLOURS.length],
          pointRadius: 3,
          tension: 0.15
        }))
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { title: { display: true, text: "Final score / 200" } } } }
    });
  }
  const dayCity = document.getElementById("day-city");
  const dayCities = Array.from(new Set(doc.category_days.filter((r) => r.state === "Andhra Pradesh" || r.state === "Telangana").map((r) => r.city))).sort();
  dayCity.innerHTML = dayCities.map((c) => '<option>' + escapeHtml(c) + '</option>').join("");
  function drawDays() {
    const rows = doc.category_days.filter((r) => r.city === dayCity.value).sort((a, b) => a.year - b.year);
    if (dayChart) dayChart.destroy();
    const cats = ["good", "satisfactory", "moderate", "poor", "very_poor", "severe"];
    const colours = ["#1f8a4c", "#c5dd8a", "#ffe56a", "#ffb15a", "#e23d2b", "#7a1530"];
    dayChart = new Chart(document.getElementById("day-chart"), {
      type: "bar",
      data: {
        labels: rows.map((r) => r.year),
        datasets: cats.map((cat, i) => ({
          label: cat.replace("_", " "),
          data: rows.map((r) => r[cat]),
          backgroundColor: colours[i]
        }))
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { x: { stacked: true }, y: { stacked: true, title: { display: true, text: "Days" } } } }
    });
  }
  stateSelect.addEventListener("change", drawPm);
  dayCity.addEventListener("change", drawDays);
  drawPm();
  drawSvs();
  drawDays();
});

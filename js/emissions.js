Promise.all([
  fetch("data/charts/fires.json").then((r) => r.json()),
  fetch("data/maps/power_plants.geojson").then((r) => r.json())
]).then(([fires, plants]) => {
  const map = L.map("plant-map").setView([16.5, 79.8], 6);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 18
  }).addTo(map);
  const fuelColour = { Coal: "#1c1915", Gas: "#8c3b1e", Hydro: "#1d6a63", Solar: "#c4a35a", Wind: "#5c6b2f", Oil: "#a33b3b" };
  plants.features.forEach((feature) => {
    const [lon, lat] = feature.geometry.coordinates;
    const p = feature.properties;
    const mw = Number(p.capacity_mw) || 1;
    L.circleMarker([lat, lon], {
      radius: Math.max(4, Math.min(16, Math.sqrt(mw) / 2.2)),
      color: "#1c1915",
      weight: 0.4,
      fillColor: fuelColour[p.primary_fuel] || "#8d867c",
      fillOpacity: 0.85
    }).bindPopup("<strong>" + escapeHtml(p.name) + "</strong><br>" + escapeHtml(p.primary_fuel) + " · " + mw + " MW<br>" + escapeHtml(p.state_DERIVED || "") + "<br><span class='muted'>WRI GPPD v1.3, frozen 2021</span>").addTo(map);
  });
  const years = Array.from(new Set(fires.fires_monthly.map((r) => r.year))).sort();
  const states = ["Andhra Pradesh", "Telangana"];
  new Chart(document.getElementById("fire-chart"), {
    type: "bar",
    data: {
      labels: years.map(String),
      datasets: states.map((state, i) => ({
        label: state + " detections",
        data: years.map((year) => fires.fires_monthly.filter((r) => r.year === year && r.state === state).reduce((s, r) => s + r.detections, 0)),
        backgroundColor: i ? "#0e3d3b" : "#8c3b1e"
      }))
    },
    options: { responsive: true, maintainAspectRatio: false, scales: { y: { title: { display: true, text: "VIIRS detections, Oct–Nov" } } } }
  });
  const yearSelect = document.getElementById("fire-year");
  yearSelect.innerHTML = years.map((y) => "<option>" + y + "</option>").join("");
  yearSelect.value = String(years[years.length - 1]);
  const fireLayer = L.layerGroup().addTo(map);
  function drawFires() {
    fireLayer.clearLayers();
    const year = Number(yearSelect.value);
    fires.fires_grid.filter((cell) => cell.year === year).forEach((cell) => {
      L.circleMarker([cell.lat, cell.lon], {
        radius: Math.min(14, 3 + Math.sqrt(cell.detections)),
        stroke: false,
        fillColor: "#e23d2b",
        fillOpacity: 0.35
      }).bindPopup(cell.detections + " detections in " + year + " (" + cell.state + ")").addTo(fireLayer);
    });
  }
  yearSelect.addEventListener("change", drawFires);
  drawFires();
  document.getElementById("fire-note").textContent = fires.fires_note;

  const focus = fires.apna.filter((r) => /hyderabad|visakhapatnam|vijayawada|guntur|warangal|nellore|kurnool|tirupati/i.test(r.city));
  const keys = ["transport", "residential", "industry", "dust", "waste", "diesel", "brick", "regional"];
  const colours = ["#1c1915", "#8c3b1e", "#5e584f", "#c4a35a", "#a33b3b", "#1d6a63", "#8d6a2f", "#9aa396"];
  new Chart(document.getElementById("apna-chart"), {
    type: "bar",
    data: {
      labels: focus.map((r) => r.city),
      datasets: keys.map((key, i) => ({
        label: key,
        data: focus.map((r) => r[key]),
        backgroundColor: colours[i]
      }))
    },
    options: { responsive: true, maintainAspectRatio: false, scales: { x: { stacked: true }, y: { stacked: true, max: 100, title: { display: true, text: "Share of PM2.5, % (model)" } } } }
  });
  const seasons = ["winter", "summer", "monsoon"];
  const cmb = fires.hyderabad_cmb.filter((r) => r.size === "PM2.5");
  new Chart(document.getElementById("cmb-chart"), {
    type: "bar",
    data: {
      labels: cmb.map((r) => r.station + " " + r.season),
      datasets: [
        { label: "Road dust %", data: cmb.map((r) => r.road_dust), backgroundColor: "#c4a35a" },
        { label: "Vehicles %", data: cmb.map((r) => r.vehicles), backgroundColor: "#1c1915" },
        { label: "Biomass %", data: cmb.map((r) => r.biomass), backgroundColor: "#1d6a63" },
        { label: "Coal %", data: cmb.map((r) => r.coal), backgroundColor: "#8c3b1e" }
      ]
    },
    options: { responsive: true, maintainAspectRatio: false }
  });
});

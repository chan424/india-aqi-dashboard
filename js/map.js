(function () {
  const status = document.getElementById("status-text");
  const list = document.getElementById("place-list");
  const search = document.getElementById("place-search");
  const tableBody = document.querySelector("#city-table tbody");
  let calibration = {};
  let places = [];
  let stationsLayer;
  let gapLayer;
  let gridLayer;
  let indiaLayer;
  let trueColor;
  let aodLayer;
  const map = L.map("map", { scrollWheelZoom: true, worldCopyJump: true }).setView([16.4, 79.6], 6);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19
  }).addTo(map);
  const renderer = L.canvas({ padding: 0.4 });

  function gapColor(km, gapClass) {
    if (gapClass === "monitor_inside") return "#d5ebe3";
    if (gapClass === "bulletin_without_coordinates") return "#e4d7f2";
    if (km == null) return "#eee";
    if (km < 25) return "#d5ebe3";
    if (km < 50) return "#f4e7b0";
    if (km < 100) return "#f3c7a1";
    return "#efb4ae";
  }

  function stationPopup(p) {
    const kind = p.aqi_colour_kind;
    let measured = "<p>No CPCB bulletin value matched this station's city on the cached bulletin date.</p>";
    if (kind === "measured_station_feed") {
      measured = "<p><span class=\"tag measured\">Measured (monitor)</span> Station feed AQI " + pill(p.station_aqi || p.aqi_for_colour) + "</p>";
    } else if (p.bulletin_aqi != null) {
      measured = "<p><span class=\"tag measured\">Measured (monitor)</span> " + pill(p.bulletin_aqi, p.bulletin_category) +
        "</p><p>CPCB <em>city</em> bulletin for " + escapeHtml(p.city) + " on " + escapeHtml(p.bulletin_date) +
        (p.bulletin_pollutant ? ", prominent " + escapeHtml(p.bulletin_pollutant) : "") +
        (p.bulletin_stations ? " (" + escapeHtml(p.bulletin_stations) + " stations)." : ".") +
        " This is not a reading from this station alone.</p>";
    }
    return '<div class="popup"><h3>' + escapeHtml(p.name) + '</h3><p>' + escapeHtml(p.city) + ', ' + escapeHtml(p.state) +
      (p.agency ? " · " + escapeHtml(p.agency) : "") + '</p>' + measured +
      '<p class="muted">' + escapeHtml(p.list_source) + '</p>' +
      (p.city_note ? '<p>' + escapeHtml(p.city_note) + '</p>' : '') +
      '<p><button type="button" class="linkish" data-est="' + p.lat + ',' + p.lon + '">Estimate at this point</button></p></div>';
  }

  function addStations(geo) {
    const markers = [];
    geo.features.forEach((feature) => {
      const [lon, lat] = feature.geometry.coordinates;
      const p = feature.properties;
      p.lat = lat;
      p.lon = lon;
      const marker = L.circleMarker([lat, lon], {
        renderer,
        radius: p.state === "Andhra Pradesh" || p.state === "Telangana" ? 7 : 5,
        color: "#1c1915",
        weight: 0.6,
        fillColor: AQI.color(p.aqi_for_colour),
        fillOpacity: 0.92
      });
      marker.bindPopup(stationPopup(p));
      marker.on("click", (event) => L.DomEvent.stopPropagation(event));
      marker.on("popupopen", (event) => bindEstimate(event.popup.getElement()));
      markers.push(marker);
    });
    stationsLayer = L.featureGroup(markers).addTo(map);
  }

  function addGaps(geo) {
    gapLayer = L.geoJSON(geo, {
      style: (feature) => {
        const p = feature.properties;
        return {
          color: p.gap_class === "no_monitor" ? "#8c3b1e" : "#0e3d3b",
          weight: p.gap_class === "monitor_inside" ? 1 : 2,
          dashArray: p.gap_class === "bulletin_without_coordinates" ? "5 4" : null,
          fillColor: gapColor(p.nearest_monitor_km, p.gap_class),
          fillOpacity: 0.55
        };
      },
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        const label = p.gap_class === "monitor_inside"
          ? "A monitor coordinate falls inside this Census 2011 district."
          : p.gap_class === "bulletin_without_coordinates"
            ? "The CPCB bulletin reports a monitor for a city here, but the station lists used on this map do not publish its coordinates."
            : "No monitor coordinate from the station lists falls inside this district.";
        layer.on("click", (event) => L.DomEvent.stopPropagation(event));
        layer.bindPopup(
          '<div class="popup"><h3>' + escapeHtml(p.district) + '</h3><p>' + escapeHtml(p.state_now) +
          ' · Census 2011 boundary</p><p>' + label + '</p><p>Nearest published monitor: ' +
          escapeHtml(p.nearest_monitor) + ' (' + p.nearest_monitor_km + ' km).</p></div>'
        );
      }
    }).addTo(map);
  }

  function addGrid(geo) {
    const dots = geo.features.map((feature) => {
      const [lon, lat] = feature.geometry.coordinates;
      const km = feature.properties.nearest_monitor_km;
      return L.circleMarker([lat, lon], {
        renderer,
        radius: 6,
        stroke: false,
        fillColor: gapColor(km, "grid"),
        fillOpacity: 0.85
      }).bindPopup(km + " km to " + escapeHtml(feature.properties.nearest_monitor));
    });
    gridLayer = L.featureGroup(dots);
  }

  function addIndia(doc) {
    const dots = (doc.districts || []).map((row) => L.circleMarker([row.lat, row.lon], {
      renderer,
      radius: row.emphasis ? 5 : 3.5,
      color: row.emphasis ? "#0e3d3b" : "#5e584f",
      weight: row.emphasis ? 1.5 : 0.4,
      fillColor: gapColor(row.nearest_monitor_km, row.has_monitor ? "monitor_inside" : "grid"),
      fillOpacity: 0.9
    }).bindPopup(
      '<div class="popup"><h3>' + escapeHtml(row.district) + '</h3><p>' + escapeHtml(row.state_now) +
      '</p><p>' + (row.has_monitor ? "Monitor inside the district." : "No monitor inside the district.") +
      ' Nearest published monitor ' + row.nearest_monitor_km + ' km.</p><p class="muted">Census 2011 representative point.</p></div>'
    ));
    indiaLayer = L.featureGroup(dots);
  }

  function cardHtml(place) {
    const measured = place.measured_aqi != null
      ? '<div><span class="tag measured">Measured (monitor)</span> ' + pill(place.measured_aqi, place.measured_category) + '</div>'
      : '';
    const estimated = '<div><span class="tag model">Estimated (model)</span> ' + pill(place.aqi, place.category) + '</div>';
    const kind = place.kind === "unmonitored_district" ? "District without a published monitor" : place.kind.replaceAll("_", " ");
    return '<article class="card" data-name="' + escapeHtml((place.name + " " + place.state).toLowerCase()) + '">' +
      '<button class="card-hit" type="button" data-lat="' + place.lat + '" data-lon="' + place.lon + '" data-id="' + escapeHtml(place.id) + '">' +
      '<div class="place-name">' + escapeHtml(place.name) + '</div>' +
      '<div class="place-meta">' + escapeHtml(place.state) + ' · ' + escapeHtml(kind) + '</div>' +
      '<div class="pair">' + measured + estimated + '</div>' +
      '<p class="place-meta">Dominant ' + escapeHtml(AQI.LABELS[place.dominant] || place.dominant || "—") +
      (place.nearest_monitor_km != null ? ' · nearest published monitor ' + place.nearest_monitor_km + ' km' : '') +
      (place.uncertainty_rmse != null ? ' · 2025 holdout RMSE ±' + place.uncertainty_rmse + ' AQI' : '') + '</p>' +
      (place.weather ? '<p class="place-meta">Wind ' + place.weather.wind_24h_mean_ms + ' m/s · RH ' +
        place.weather.rh_24h_mean_pct + '% · rain ' + place.weather.rain_24h_mm + ' mm · ventilation ' +
        place.weather.ventilation_m2s + ' m²/s</p>' : '') +
      '</button></article>';
  }

  function renderPlaces() {
    const q = (search.value || "").trim().toLowerCase();
    const shown = places.filter((p) => !q || (p.name + " " + p.state).toLowerCase().includes(q));
    const groups = [
      ["Andhra Pradesh and Telangana", shown.filter((p) => p.state === "Andhra Pradesh" || p.state === "Telangana")],
      ["Other cities", shown.filter((p) => p.state !== "Andhra Pradesh" && p.state !== "Telangana")]
    ];
    list.innerHTML = groups.map(([title, rows]) => {
      if (!rows.length) return "";
      return '<h2 class="section-label">' + title + '</h2>' + rows.map(cardHtml).join("");
    }).join("");
    tableBody.innerHTML = shown.map((p) => '<tr><td>' + escapeHtml(p.name) + '</td><td>' + escapeHtml(p.state) +
      '</td><td>' + (p.measured_aqi == null ? "—" : p.measured_aqi + " " + escapeHtml(p.measured_category || "")) +
      '</td><td>' + (p.aqi == null ? "—" : p.aqi + " " + escapeHtml(p.category || "")) + " Estimated (model)</td><td>" +
      (p.nearest_monitor_km == null ? "—" : p.nearest_monitor_km) + '</td></tr>').join("");
  }

  function bindEstimate(root) {
    (root || document).querySelectorAll("[data-est]").forEach((button) => {
      button.addEventListener("click", () => {
        const [lat, lon] = button.getAttribute("data-est").split(",").map(Number);
        runEstimate(lat, lon, null);
      });
    });
  }

  async function runEstimate(lat, lon, popup) {
    const target = popup || L.popup().setLatLng([lat, lon]).setContent("Estimating from Open-Meteo…").openOn(map);
    target.setContent("Estimating from Open-Meteo…");
    try {
      const hourly = await Estimate.fetchHourly(lat, lon);
      const est = Estimate.estimate(hourly, calibration);
      const subs = (est.sub_indices || []).slice(0, 4).map((piece) =>
        AQI.LABELS[piece.pollutant] + " " + Math.round(piece.sub_index)).join(", ");
      target.setContent(
        '<div class="popup"><h3>Selected point</h3><p><span class="tag model">Estimated (model)</span> ' +
        pill(est.aqi, est.category) + '</p><p>' + escapeHtml(est.method) + '.</p><p>Sub-indices: ' + escapeHtml(subs) +
        '.</p><p class="muted">±' + (calibration.uncertainty ? calibration.uncertainty.test_2025_rmse_aqi : "—") +
        ' AQI is the 2025 holdout RMSE for Hyderabad and AP cities, not a local interval. Weather is shown with the preset cities; it did not improve the 2025 concentration fit, so it is not inside this number.</p></div>'
      );
      target.update();
    } catch (error) {
      target.setContent('<div class="popup"><p>Live Open-Meteo request failed. Cached city estimates are still listed.</p></div>');
    }
  }

  map.on("click", (event) => {
    if (event.originalEvent && event.originalEvent.target.closest(".leaflet-popup, .leaflet-control")) return;
    runEstimate(event.latlng.lat, event.latlng.lng);
  });

  list.addEventListener("click", (event) => {
    const button = event.target.closest("[data-lat]");
    if (!button) return;
    const lat = Number(button.dataset.lat);
    const lon = Number(button.dataset.lon);
    map.setView([lat, lon], 9);
    const place = places.find((p) => p.id === button.dataset.id);
    if (!place) return;
    L.popup().setLatLng([lat, lon]).setContent(
      '<div class="popup"><h3>' + escapeHtml(place.name) + '</h3>' +
      (place.measured_detail ? '<p><span class="tag measured">Measured (monitor)</span> ' + pill(place.measured_aqi, place.measured_category) + '<br>' + escapeHtml(place.measured_detail) + '</p>' : '') +
      '<p><span class="tag model">Estimated (model)</span> ' + pill(place.aqi, place.category) + '<br>' + escapeHtml(place.method || "") + '</p>' +
      '<p>Nearest published monitor: ' + escapeHtml(place.nearest_monitor || "—") + ' (' + (place.nearest_monitor_km ?? "—") + ' km).</p></div>'
    ).openOn(map);
  });
  search.addEventListener("input", renderPlaces);

  document.getElementById("layer-stations").addEventListener("change", (e) => {
    if (e.target.checked) stationsLayer.addTo(map); else map.removeLayer(stationsLayer);
  });
  document.getElementById("layer-gaps").addEventListener("change", (e) => {
    if (e.target.checked) gapLayer.addTo(map); else map.removeLayer(gapLayer);
  });
  document.getElementById("layer-grid").addEventListener("change", (e) => {
    if (e.target.checked) gridLayer.addTo(map); else map.removeLayer(gridLayer);
  });
  document.getElementById("layer-india").addEventListener("change", (e) => {
    if (e.target.checked) { indiaLayer.addTo(map); map.setView([22.5, 81], 5); }
    else map.removeLayer(indiaLayer);
  });
  document.getElementById("layer-true").addEventListener("change", (e) => {
    if (e.target.checked) trueColor.addTo(map); else map.removeLayer(trueColor);
  });
  document.getElementById("layer-aod").addEventListener("change", (e) => {
    if (e.target.checked) aodLayer.addTo(map); else map.removeLayer(aodLayer);
  });
  document.getElementById("reset-view").addEventListener("click", () => map.setView([16.4, 79.6], 6));

  const gibsDate = "2026-11-20";
  trueColor = L.tileLayer(
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Terra_CorrectedReflectance_TrueColor/default/" + gibsDate + "/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg",
    { attribution: "NASA GIBS / MODIS Terra", maxZoom: 9, opacity: 0.85 }
  );
  aodLayer = L.tileLayer(
    "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/MODIS_Combined_Value_Added_AOD/default/" + gibsDate + "/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png",
    { attribution: "NASA GIBS AOD", maxZoom: 9, opacity: 0.7 }
  );

  Promise.all([
    fetch("data/maps/stations.geojson").then((r) => r.json()),
    fetch("data/maps/districts_ap_tg.geojson").then((r) => r.json()),
    fetch("data/maps/gap_grid_ap_tg.geojson").then((r) => r.json()),
    fetch("data/maps/district_centroids.json").then((r) => r.json()),
    fetch("data/cache/city_estimates.json").then((r) => r.json()),
    fetch("data/cache/calibration.json").then((r) => r.json()),
    fetch("data/cache/meta.json").then((r) => r.json())
  ]).then(([stations, gaps, grid, india, estimates, cal, meta]) => {
    calibration = cal;
    addGaps(gaps);
    addStations(stations);
    addGrid(grid);
    addIndia(india);
    places = estimates.places || [];
    renderPlaces();
    const rss = meta.rss_status || "";
    status.textContent = (meta.bulletin_date ? "CPCB bulletin " + meta.bulletin_date + " colours city markers. " : "") +
      (rss.startsWith("ok") ? "Station feed live. " : "Station-level CPCB feed did not respond; city bulletin values are used where the city matches. ") +
      (estimates.generated_at ? "Model cache " + estimates.generated_at.replace("T", " ").replace("Z", " UTC") + "." : "");
  }).catch(() => {
    status.textContent = "Map data failed to load.";
  });
})();

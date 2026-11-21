fetch("data/dictionary.json").then((r) => r.json()).then((doc) => {
  const folder = doc.drive_folder;
  document.getElementById("drive-link").href = folder.url;
  document.getElementById("drive-link").textContent = folder.name;
  const body = document.querySelector("#files tbody");
  function render(q) {
    const query = q.trim().toLowerCase();
    body.innerHTML = doc.files.filter((file) => !query || (file.filename + file.description + file.archive_path).toLowerCase().includes(query)).map((file) => {
      const drive = (file.drive && file.drive[0]) ? '<a href="' + file.drive[0].url + '">Drive</a>' : "—";
      const size = file.download_bytes > 1e6 ? (file.download_bytes / 1e6).toFixed(1) + " MB" : Math.max(1, Math.round(file.download_bytes / 1024)) + " KB";
      return "<tr><td><a href=\"" + file.download + "\">" + escapeHtml(file.filename) + (file.compressed ? ".gz" : "") + "</a></td><td>" +
        escapeHtml(file.description) + "</td><td>" + (file.rows ?? "—") + "</td><td>" + size + (file.compressed ? " gzip" : "") +
        "</td><td><code>" + file.sha256.slice(0, 12) + "</code></td><td>" + drive + "</td></tr>";
    }).join("");
  }
  document.getElementById("q").addEventListener("input", (e) => render(e.target.value));
  render("");
  const cov = doc.coverage;
  document.getElementById("cov").textContent = cov.national_stations + " monitors on the map (" + cov.stations_in_pdf + " from the CPCB PDF). Andhra Pradesh " +
    cov.stations_ap + ", Telangana " + cov.stations_tg + ". Of " + cov.ap_tg_districts_2011 + " Census 2011 districts in the two states, " +
    cov.ap_tg_districts_with_monitor + " contain a published monitor coordinate.";
});

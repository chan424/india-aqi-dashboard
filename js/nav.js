(function () {
  const button = document.querySelector(".nav-toggle");
  const nav = document.getElementById("site-nav");
  if (button && nav) {
    button.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      button.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  const stamp = document.getElementById("updated");
  if (stamp) {
    fetch("data/cache/meta.json")
      .then((r) => r.json())
      .then((meta) => {
        const when = meta.estimates_updated || meta.bulletin_date || "";
        const bulletin = meta.bulletin_date ? "Bulletin " + meta.bulletin_date : "Bulletin unavailable";
        stamp.textContent = bulletin + (when ? " · estimates " + when.replace("T", " ").replace("Z", " UTC") : "");
      })
      .catch(() => { stamp.textContent = "Cache time unavailable"; });
  }
})();

function pill(aqi, category) {
  if (aqi == null) return '<span class="aqi-pill">—</span>';
  const cat = category || (window.AQI ? AQI.categoryOf(aqi) : "");
  return '<span class="aqi-pill" data-cat="' + cat + '">' + aqi + ' <small>' + cat + '</small></span>';
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

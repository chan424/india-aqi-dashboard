Chart.defaults.font.family = '"Source Sans 3", "Segoe UI", sans-serif';
Chart.defaults.color = "#3c3832";
Chart.defaults.borderColor = "#e0d8cb";
Chart.defaults.plugins.legend.position = "bottom";
const CHART_COLOURS = ["#0e3d3b", "#8c3b1e", "#c4a35a", "#1d6a63", "#3c3832", "#a33b3b", "#5c6b2f"];

function lineChart(canvas, labels, datasets, yTitle) {
  return new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: datasets.map((ds, i) => ({
        borderColor: CHART_COLOURS[i % CHART_COLOURS.length],
        backgroundColor: CHART_COLOURS[i % CHART_COLOURS.length],
        pointRadius: 0,
        tension: 0.15,
        borderWidth: 2,
        ...ds
      }))
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { title: { display: true, text: yTitle } } },
      plugins: { tooltip: { mode: "index", intersect: false } }
    }
  });
}

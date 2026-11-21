# India AQI Observatory

A static research site for air quality in India, with the detail on Hyderabad, Andhra Pradesh and Telangana. Built for the air-quality and health work at Rajiv Gandhi University of Knowledge Technologies, Ongole.

It is a display, not a regulatory bulletin. Official AQI is published by the Central Pollution Control Board.

## What you can do on the site

- **Map.** National CAAQMS monitors, coloured by the latest CPCB city bulletin when the city matches. Andhra Pradesh and Telangana districts coloured by distance to the nearest published monitor. A 0.35° distance grid. Optional NASA MODIS true-colour and aerosol-optical-depth tiles. Click any point for a live model estimate.
- **Cities.** Daily CPCB bulletin AQI for Hyderabad and Andhra Pradesh cities, monthly station pollutants, Diwali contrasts, and the Hyderabad lockdown weather-normalised table.
- **Ongole.** October–November 2026 case study: bulletin AQI, CAMS particles, ERA5 ventilation.
- **NCAP.** PM10 in the Lok Sabha SQ 12 table, Swachh Vayu scores, AQI-category days from SQ 120.
- **Health.** District AQLI PM2.5 and life-years beside NFHS child ARI. Ecological, not causal.
- **Fires and plants.** FIRMS October–November detections and WRI power plants, plus APnA and Hyderabad CMB source shares.
- **ENSO.** October–December bulletin AQI against the NOAA Oceanic Niño Index.
- **Data.** Every archive table, gzipped when it was large, with a Drive link where the 19 November 2026 listing has one.
- **Methods.** The CPCB formula, the model, the holdout numbers, and the limits.

Measured values are tagged **Measured (monitor)**. Model values are tagged **Estimated (model)**.

## Run it locally

No build step is required to read the site. From the repository root:

```bash
python3 -m http.server 8000
```

Open `http://127.0.0.1:8000/`. Pages fetch JSON from `data/` with relative URLs, so the site also works at `https://chan424.github.io/india-aqi-dashboard/` once GitHub Pages is serving this branch.

Rebuilding the historical files needs the research archive extracted, plus the public inputs the last build used:

```bash
pip install numpy shapely pyshp pypdf scipy
export AQI_BUNDLE=/path/to/dash_bundle
export AQI_STATION_PDF=/path/to/caaqms_list_All_India.pdf
export AQI_XKDR_CSV=/path/to/xkdr_stations.csv
export AQI_BULLETIN_PDF=/path/to/AQI_Bulletin.pdf
export AQI_DISTRICT_SHP=/path/to/2011_Dist.shp
PYTHONPATH=scripts python3 scripts/build_site_data.py
PYTHONPATH=scripts python3 scripts/refresh_cache.py
```

`refresh_cache.py` only needs `pypdf`. It does not need the archive. It downloads the newest CPCB bulletin PDF it can find, asks the CPCB station feed, and refetches Open-Meteo for the preset places.

## Architecture

```
index.html and the other pages     static HTML
css/styles.css                     layout
js/aqi.js                          CPCB sub-index (same breakpoints as scripts/cpcb_aqi.py)
js/estimate.js                     browser estimate from Open-Meteo
js/map.js                          Leaflet map
vendor/                            Leaflet 1.9.4 and Chart.js 4.4.6
data/maps/                         stations, AP/TG districts, distance grid, centroids, power plants
data/charts/                       aggregates for the charts
data/cache/                        calibration, bulletin, city estimates, meta
data/downloads/                    archive files, gzipped above 400 KB
scripts/build_site_data.py        one-shot historical build
scripts/refresh_cache.py          hourly live refresh
.github/workflows/pages.yml       deploy GitHub Pages from main
.github/workflows/refresh-cache.yml  hourly cache refresh and deploy
```

GitHub Pages is a static host, so every request runs in the browser. Open-Meteo does not need a key. The CPCB station feed and the bulletin PDF do not need a key either. Nothing in this repository is an API secret.

The hourly workflow writes `data/cache/city_estimates.json`, `data/cache/bulletin_latest.json`, `data/cache/meta.json` and, when the feed answers, station-level AQI on `data/maps/stations.geojson`. If Open-Meteo fails, the previous cache stays and the cards still render. A click on the map needs the live API.

Pushes made with `GITHUB_TOKEN` do not start other workflows, so the refresh workflow deploys Pages itself after updating the cache.

## Station list

Two public sources are combined, and the page says which one a pin came from.

1. [CPCB CAAQMS list, all India](https://app.cpcbccr.com/ccr_docs/caaqms_list_All_India.pdf), file dated 18 November 2026, 358 stations. This is the preferred coordinate when a station is in both lists.
2. [XKDR Forum India Air Quality Database](https://airquality.xkdr.org/) station directory exported 30 September 2026 (CC BY 4.0). Stations in that directory that the PDF does not contain are added, including US Embassy monitors. Credit CPCB CAAQM and the US Department of State via AirNow with XKDR.

The PDF lists four Andhra Pradesh stations. The 21 November 2026 bulletin reports monitors in many more AP cities, including Ongole. Those cities are not given invented coordinates. Districts that contain a bulletin city but no published coordinate are marked “coordinates unpublished”.

## Model

Hourly CAMS from Open-Meteo. PM2.5, PM10, NO2 and SO2 use the last 24-hour mean (at least 16 hours). Ozone and CO use the highest 8-hour mean in that window. CO is divided by 1000 to convert µg/m³ to mg/m³. A line `a + b × CAMS`, fitted on 2022–2024 valid-18h city-days for Hyderabad, Visakhapatnam, Vijayawada and Chittoor, is applied before the CPCB sub-index. The line is used because it lowered 2025 bulletin RMSE.

Relative humidity, wind and rain were tested as extra terms. They did not cut 2025 PM2.5 RMSE by the required 5% (16.73 with weather, 15.91 without), so they are shown beside the estimate and are not inside it. Inverse-distance residuals from other cities were tested leave-one-city-out and made 2025 RMSE worse (42.52 against 39.19), so they are not applied. A neighbour existed on 50.6% of those city-days.

Holdout against the CPCB city bulletin, daily-mean proxy (ozone and CO in the score are daily means; the live estimate uses 8-hour maxima):

| Comparison | n | MAE | RMSE | Bias (pred − obs) | r | Exact category | Within one |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025 raw CAMS | 1367 | 29.19 | 41.33 | −5.77 | 0.450 | 53.9% | 97.7% |
| 2025 calibrated | 1367 | 26.34 | 39.19 | −16.19 | 0.576 | 58.2% | 98.1% |
| 2025 calibrated + IDW | 1367 | 30.06 | 42.52 | −16.19 | 0.474 | 56.2% | 97.2% |
| 2026 raw (not used to choose) | 2294 | 26.98 | 35.21 | +14.42 | 0.413 | 56.7% | 97.9% |
| 2026 calibrated (not used to choose) | 2294 | 17.93 | 25.44 | −0.65 | 0.574 | 67.6% | 99.5% |

Pollutant 2025 RMSE, raw CAMS versus the line: PM2.5 21.41 → 15.91 (r 0.60), PM10 62.99 → 38.47 (r 0.52), NO2 16.77 → 14.73 (r 0.65), ozone 56.72 → 15.73 (r 0.16), SO2 7.27 → 5.35 (r 0.04), CO 0.41 → 0.20 mg/m³ (r 0.11). The ± band on a card is the 2025 bulletin RMSE, 39.19 AQI points. It is an error from this region, not a prediction interval for every Indian location.

October–December bulletin means against the NOAA OND Niño index, years with at least 20 bulletin days: Hyderabad r = 0.25 (n = 11, p = 0.45). The other cities in the chart are weaker. This is not the archive’s 1 Oct–14 Nov window, which the archive README reports as Hyderabad r = 0.21.

## Update the data

- **Live cache.** The hourly workflow does this. To do it by hand: `PYTHONPATH=scripts python3 scripts/refresh_cache.py`, then commit `data/cache` and `data/maps/stations.geojson`.
- **A new research extract.** Replace the archive path, rerun `build_site_data.py`, then `refresh_cache.py`. Charts read `data/charts/`, not the raw CSVs.
- **A new CPCB station PDF.** Pass it as `AQI_STATION_PDF` and rebuild. Pins record which list they came from.

Files at or above 400 KB are stored gzipped under `data/downloads/`. Row counts in `data/dictionary.json` are the original tables. SHA-256 is of the uncompressed bytes.

## GitHub Pages

Workflows deploy with GitHub Actions. After this branch is on `main`:

1. Repository **Settings → Pages → Build and deployment → Source: GitHub Actions**.
2. The **Publish GitHub Pages** workflow runs on every push to `main`.
3. The site is then at `https://chan424.github.io/india-aqi-dashboard/`.

If the hourly job cannot push (branch protection), the cache still deploys from that job’s workspace for that run, and the commit in the repository may lag. Allow the GitHub Actions bot to push to `main`, or run `refresh_cache.py` locally and push.

This repository’s agent opened a pull request rather than pushing to `main`. The site goes live when that pull request is merged and Pages is set to GitHub Actions.

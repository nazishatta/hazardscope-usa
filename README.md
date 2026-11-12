# HazardScope USA

**A Streamlit natural-hazards research dashboard with animated model-based wind flow, USGS earthquake events, National Weather Service warnings, FEMA declaration history, and Open-Meteo weather conditions.**

This is an independent project; it does **not** modify ChargeAtlas USA.

## Start on Mac or Windows

```bash
cd hazardscope-usa
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m streamlit run app.py
```

No API keys are needed for the four included public endpoints under their applicable usage policies. Internet access is required for live fetches. An empty dashboard before the first Fetch is intentional: it does not show fake or stale events as live.

## How to explore

1. Use the **left sidebar** to select the U.S. or a state/territory, a seismic time window (1–30 days), minimum magnitude and maximum depth.
2. Click **Fetch USGS earthquakes** to retrieve validated GeoJSON earthquake data, inspect event dots, the geographic-density overlay, a density surface, timeline, and magnitude-versus-depth plot.
3. Click **Fetch active NWS warnings** to retrieve official current alerts, then filter by severe thunderstorm, tornado, flood, hurricane, tsunami, winter storm, or severity. Tsunami warnings appear only if official active alerts exist.
4. Click **Fetch FEMA history** to retrieve recent declared disasters. Read the sample warning before interpreting national counts.
5. Click **Fetch wind, pressure & weather** to retrieve approximate **state-center** hourly forecasts.
6. Visit **Wind streamlines** and click **Fetch live-model wind field and create animation**. Choose particle count and grid resolution. Press Play in the map to see colored, moving trails.
7. Expand **Methods & sources** for actual query metadata, source freshness and limitations.

## What “live” means

- **USGS:** An explicit API query for cataloged earthquake events. Results are refreshed when Fetch is clicked and cached for 3 minutes.
- **NWS:** Official *currently active* warning/alert records. Results are refreshed on Fetch and cached for 3 minutes.
- **FEMA:** Historical disaster declarations, not live hazards. Cached for 15 minutes.
- **Open-Meteo:** Current model estimates and hourly model forecasts. **Not** a measurement from a physical anemometer at every map grid point; cached for 5–15 minutes.
- **Wind animation:** Advected mathematical particles through **one sampled model-derived wind field**. It is *not* a continuously streaming wind dataset, actual tracked air parcels, or a temporal forecast movie. Colored streaks are visual encoding, not measured atmospheric trajectories.

## Scientific and geographic caveats

- Selected-state earthquake queries use a **coarse geographic bounding rectangle**, which can include cross-border events. This is explicitly called out inside the UI. NWS/FEMA use jurisdiction codes.
- For national USGS, the broad bounding box includes neighboring international locations and is not a strict U.S. polygon join. The U.S. map uses Albers USA and may not show all retrieved points.
- A density overlay shows **smoothed *event counts*** for a chosen reporting window, not earthquake probability, expected damage, physical hazard intensity, or a validated risk score. Density smoothing and geographic distortion require caution.
- FEMA responses are limited to the latest **1,000 designated-area rows** in this starter application. Queries returning the cap can be incomplete and should not be compared as complete national totals.
- FEMA may contain multiple geographical-area rows for one disaster. The distinct `disasterNumber` is used when calculating disaster counts.
- NWS active warnings are **not** a complete log of physical storm events. The absence of an active warning does not mean an area is safe.
- Historical NOAA NCEI tsunami datasets are **linked**, not ingested in this initial build. NWS tsunami alerts are live warning bulletins rather than a historic event archive.
- Grid values returned by Open-Meteo may represent interpolated or nearest model cells; sampling visually over a U.S. grid does not generate true high-resolution weather observations.

## Data sources

- [USGS Earthquake Catalog API](https://earthquake.usgs.gov/fdsnws/event/1/)
- [NWS Alerts API](https://www.weather.gov/documentation/services-web-alerts)
- [OpenFEMA Disaster Declarations Summaries v2](https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries)
- [Open-Meteo Forecast API](https://open-meteo.com/en/docs)
- [NOAA NCEI Historical Tsunami Database](https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis) — reference link, not yet ingested

## Structure

```text
hazardscope-usa/
├── app.py                 # Main Streamlit dashboard and Fetch controls
├── src/
│   ├── geo.py            # State selections and approximate bounding boxes
│   ├── providers.py      # Validated external API clients
│   └── visuals.py        # Density maps, animated wind flow and charts
├── tests/                 # Offline reproducible validation of logic
├── .streamlit/config.toml # Dark theme
├── requirements.txt
└── .gitignore
```

## Research extension roadmap

For a larger research report, add (a) an actual state/county polygon spatial join from Census geography (rather than bounding rectangles), (b) paginated and year-aligned FEMA summaries, (c) a downloaded/filtered historical NOAA Storm Events dataset with documented vintage, (d) structured historical NOAA tsunami tables, (e) audited observation and missingness diagnostics, and (f) tests with recorded API schemas.

**Educational use only.** Consult official agencies for emergency decisions and hazard warnings.


## Auto-refresh (optional)

Enable **Auto-refresh live data** in the sidebar. Select a 3–15 minute polling interval.
While this Streamlit session is connected, the dashboard periodically refetches USGS earthquakes,
NWS active alerts, and Open-Meteo point weather; maps and metrics rerender after each cycle.
The app does not stream via WebSockets or update while all browser sessions are closed.
The large-area wind field is fetched separately and animated from the sampled data;
it is not a continuously updating meteorological field.

Use manual Fetch for control. Official warnings are not replaced by this app.

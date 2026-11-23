# DATS 6401 — Weeks 11–12: HazardScope USA

**Project:** HazardScope USA — live earthquake visualization and trained seismic novelty model API  
**Coursework branch:** `feature/week11-12-ml` in `nazishatta/hazardscope-usa`  
**Scope:** Week 11 REST API client in Streamlit and Week 12 inference service in FastAPI. The original production `main` branch is not required to run these local exercises.

## Environment and installation

From the repository root, use Python 3.13 with a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-api.txt
```

`requirements-api.txt` includes the original Streamlit dependencies and pins scikit-learn to **1.8.0**, matching the version used to serialize the bundled Isolation Forest. `artifacts/isolation_forest.joblib` is a **trusted, locally trained** model artifact. Do not load untrusted joblib/pickle files.

## Part A — Week 11: live public API client and visualization

Start Streamlit from the repository root:

```bash
python -m streamlit run app.py --server.port 8501 --server.headless false
```

Open `http://localhost:8501`, select **California (CA)**, **7 days**, **minimum magnitude 2.5**, and **maximum depth 700 km**. Click **Fetch USGS earthquakes** and select **03 · Earthquakes**.

- **Public endpoint:** `https://earthquake.usgs.gov/fdsnws/event/1/query` (USGS Earthquake Catalog FDSN Event Web Service).
- **Request:** USGS GeoJSON, with time window, `minmagnitude`, `maxdepth`, and the geographic latitude/longitude bounding rectangle derived from the sidebar controls. Inspect **06 · Methods & sources → QUAKES · request provenance** for the actual request parameters from a fetch.
- **JSON parsing:** `src/providers.py` validates request status/content/shape and transforms USGS GeoJSON features into an earthquake table; it does not fabricate records.
- **Caching:** `app.py` uses `@st.cache_data(ttl=180)` for earthquake fetches; the time-to-live is 180 seconds (three minutes). Cache keys change with the source query arguments. Animation reuses the fetched records rather than issuing a new request on every frame.
- **Error handling:** provider network requests use timeouts and checks; failures are surfaced through Streamlit rather than deliberately presenting failed requests as real zero-count data. This describes code behavior; a failure demonstration is separate from the successful-fetch screenshot.
- **Visualizations:** animated seismic density/epicenter map; coordinated UTC-day event counts and magnitude-versus-depth scatterplots; optional DBSCAN clustering. These describe **recorded observations**, not future earthquake forecasts or risk estimates.

**Observed demonstration on November 22, 2026 (Eastern):** a California bounding-box fetch returned **44** earthquakes with a 7-day window and magnitude ≥2.5; the dashboard displayed **44 of 44 valid records** in the coordinated charts. This count is a timestamped demonstration, **not** a constant or guaranteed future API count.

The optional Census population choropleth reads `CENSUS_API_KEY` from Streamlit secrets or an environment variable. Local setup may use `.streamlit/secrets.toml`, which is ignored by Git; never submit or publish secrets. Census data is not required to run the USGS client example.

## Part B — Week 12: serving a trained model with FastAPI

In a separate Terminal, from the repository root:

```bash
source .venv/bin/activate
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8002
```

Interactive documentation: `http://127.0.0.1:8002/docs`.

| Endpoint | Method | Purpose |
|---|---|---|
| `/health` | GET | Report model loading/ready status and version; unavailable models return HTTP 503. |
| `/model-info` | GET | Return model metadata. |
| `/predict` | POST | Validate one request and return a structured model prediction. |
| `/predict-batch` | POST | Process a bounded list of validated observations. |

**Required request fields** for `/predict`:

| Field | Type | Validation |
|---|---|---|
| `magnitude` | number | −2 to 10, inclusive |
| `depth_km` | number | −20 to 750 km, inclusive |
| `reference_region` | string | Exactly `california_bbox` |
| `event_id` | string or null | Optional, at most 100 characters |

Example input:

```json
{
  "magnitude": 4.7,
  "depth_km": 15,
  "reference_region": "california_bbox",
  "event_id": "coursework-example-001"
}
```

The response model `PredictionResponse` includes input identifiers/values, `classification`, `anomaly_score`, `reference_score_percentile`, `threshold`, `model_version`, `threshold_method`, score direction, and an interpretation caution. It does **not** return a calibrated probability or a hazard forecast.

The service loads the saved model bundle **once at startup** via FastAPI lifespan; shared inference preprocessing uses magnitude and log-transformed, nonnegative depth. Pydantic rejects invalid types/values, unsupported regions and extra fields with **HTTP 422**.

**Observed `/predict` demonstration:** HTTP 200, `model_version=seismic-novelty-v0.1`, `classification=unusual_in_reference`, novelty score approximately **0.631863**, reference percentile **96.42**, threshold approximately **0.609226** for the example input above. The percentile describes a ranking relative to historical model reference scores, **not** an earthquake probability, confidence level, hazard forecast, or safety assessment.

## Reproducible tests

Run local automated tests (synthetic data fixture used only in tests):

```bash
python -m pytest -q tests/test_model_api.py
```

With the FastAPI server already running on port 8002, independently exercise the **actual saved model** over HTTP:

```bash
python tests/test_http_week12.py
```

The HTTP script checks health, model info, OpenAPI schema, a successful prediction (200), and three malformed/invalid requests (422). In the coursework run, **all 7 HTTP checks passed**. The synthetic automated fixtures must not be presented as USGS evaluation results.

## Evidence to include in Blackboard submission

1. **Week 11:** Streamlit `03 · Earthquakes` showing live USGS results, interactive query controls, and a populated chart or map.
2. **Week 12 success:** FastAPI `/docs`, executed `POST /predict`, actual **Server response — HTTP 200**, and returned JSON.
3. **Week 12 validation:** FastAPI `/docs`, executed invalid request (`"magnitude": "invalid"`), actual **Server response — HTTP 422**, and validation details.

Optional additional evidence: request-provenance panel; coordinated-chart view; seven HTTP test checks. Screenshots must be from executed requests, **not** Swagger's static response examples.

## Deliverables and limitations

- Streamlit app: `app.py`, `src/`, and root dependencies.
- FastAPI server: `backend/main.py`; model preprocessing `shared/features.py`; trusted saved model `artifacts/isolation_forest.joblib`; dependencies `requirements-api.txt`.
- Tests: `tests/test_model_api.py`, `tests/test_http_week12.py`.
- Evidence screenshots: `evidence/week11_12/` or attached separately on Blackboard.

This is an educational visualization and statistical novelty-scoring exercise. Earthquake observations may be truncated by source limits or geographic bounding boxes. Neither DBSCAN clusters nor Isolation Forest anomaly scores should be interpreted as earthquake hazard zones, predictions, or calibrated probabilities.

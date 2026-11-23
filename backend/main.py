"""Standalone FastAPI server for trained *recorded-earthquake novelty* analysis.

The production Streamlit app is NOT modified by this development add-on.
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from pathlib import Path
import os
import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from shared.features import transform_features

DEFAULT_ARTIFACT = Path(__file__).resolve().parents[1] / "artifacts" / "isolation_forest.joblib"


class EarthquakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    magnitude: float = Field(ge=-2, le=10, description="Observed or hypothetical earthquake magnitude")
    depth_km: float = Field(ge=-20, le=750, description="Earthquake depth in km")
    reference_region: str = Field(pattern="^california_bbox$", description="Supported historical bounding-box reference")
    event_id: str | None = Field(default=None, max_length=100)


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    events: list[EarthquakeRequest] = Field(min_length=1, max_length=500)


@asynccontextmanager
async def lifespan(app: FastAPI):
    path = Path(os.environ.get("HAZARDSCOPE_MODEL_PATH", DEFAULT_ARTIFACT))
    app.state.artifact = None
    app.state.loading_error = None
    if path.is_file():
        try:
            # Only load an artifact created by this trusted local training pipeline.
            bundle = joblib.load(path)
            assert all(k in bundle for k in ("model", "scaler", "reference_scores_sorted", "metadata"))
            app.state.artifact = bundle
        except Exception as exc:
            app.state.loading_error = f"Model artifact could not be loaded: {type(exc).__name__}"
    else:
        app.state.loading_error = "Trained artifact not found; run the offline training script"
    yield
    app.state.artifact = None


app = FastAPI(title="HazardScope Seismic Model API", version="0.1.0", lifespan=lifespan,
              description="Educational novelty scoring for recorded earthquakes. Not a hazard forecast.")


def get_bundle():
    bundle = getattr(app.state, "artifact", None)
    if bundle is None:
        raise HTTPException(status_code=503, detail=getattr(app.state, "loading_error", "Model unavailable"))
    return bundle


@app.get("/health")
def health():
    bundle = get_bundle()
    return {"status": "ready", "model_version": bundle["metadata"]["model_version"]}


@app.get("/model-info")
def model_info():
    return get_bundle()["metadata"]


class PredictionResponse(BaseModel):
    """Novelty-scoring response; neither a risk nor a confidence probability."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    event_id: str | None
    reference_region: str
    magnitude: float
    depth_km: float
    anomaly_score: float
    reference_score_percentile: float = Field(ge=0, le=100)
    classification: str
    model_version: str
    score_direction: str
    threshold: float
    threshold_method: str
    interpretation_caution: str
    observed_or_hypothetical: str


def score_one(event: EarthquakeRequest, bundle: dict):
    metadata = bundle["metadata"]
    if event.reference_region != metadata["reference_region"]:
        raise HTTPException(status_code=422, detail="Reference region is unsupported by loaded model")
    features = transform_features([event.magnitude], [event.depth_km])
    score = float(-bundle["model"].score_samples(bundle["scaler"].transform(features))[0])
    reference = bundle["reference_scores_sorted"]
    percentile = 100.0 * float(np.searchsorted(reference, score, side="right")) / len(reference)
    return {"event_id": event.event_id, "reference_region": event.reference_region,
            "magnitude": event.magnitude, "depth_km": event.depth_km,
            "anomaly_score": score, "reference_score_percentile": round(percentile, 2),
            "classification": "unusual_in_reference" if score >= metadata["threshold"] else "within_reference_range",
            "model_version": metadata["model_version"], "score_direction": metadata["score_direction"],
            "threshold": metadata["threshold"], "threshold_method": metadata["threshold_method"],
            "interpretation_caution": metadata["measurement_caution"],
            "observed_or_hypothetical": "observed_record_not_verified_by_api" if event.event_id else "hypothetical_input"}


@app.post("/predict", response_model=PredictionResponse)
def predict(event: EarthquakeRequest):
    return score_one(event, get_bundle())


@app.post("/predict-batch")
def predict_batch(batch: BatchRequest):
    bundle = get_bundle()
    return {"results": [score_one(e, bundle) for e in batch.events], "count": len(batch.events)}

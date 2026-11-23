"""Synthetic test fixtures ONLY. Do not report these as real USGS model performance."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from ml.train_model import train
from backend.main import app


def _create_test_artifact(tmp_path: Path):
    rng = np.random.default_rng(123)
    n = 260
    timestamps = pd.date_range("2021-01-01", periods=n, freq="8D", tz="UTC")
    frame = pd.DataFrame({"id": [f"SYNTHETIC-TEST-{i}" for i in range(n)], "time": timestamps,
                          "magnitude": np.clip(rng.normal(3.8, 0.55, n), 2.5, 6.5),
                          "depth_km": rng.uniform(0, 120, n)})
    csv_path = tmp_path / "synthetic_training_fixture.csv"
    frame.to_csv(csv_path, index=False)
    artifact_path = tmp_path / "synthetic_test_model.joblib"
    report = train(csv_path, artifact_path, tmp_path / "test_evaluation.json", "2024-01-01", "2027-01-01")
    assert report["training"]["count"] >= 100
    assert report["later_holdout"]["count"] >= 30
    return artifact_path


def test_health_without_model(monkeypatch, tmp_path):
    monkeypatch.setenv("HAZARDSCOPE_MODEL_PATH", str(tmp_path / "missing.joblib"))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 503
        assert client.post("/predict", json={"magnitude": 4.0, "depth_km": 20, "reference_region": "california_bbox"}).status_code == 503


def test_prediction_validations_and_metadata(monkeypatch, tmp_path):
    artifact_path = _create_test_artifact(tmp_path)
    monkeypatch.setenv("HAZARDSCOPE_MODEL_PATH", str(artifact_path))
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/model-info").json()["model_type"] == "IsolationForest"
        payload = {"magnitude": 4.7, "depth_km": 15, "reference_region": "california_bbox", "event_id": "synthetic-test-example"}
        resp = client.post("/predict", json=payload)
        assert resp.status_code == 200, resp.text
        output = resp.json()
        assert 0 <= output["reference_score_percentile"] <= 100
        assert output["classification"] in ("unusual_in_reference", "within_reference_range")
        assert "not an earthquake forecast" in output["interpretation_caution"]
        assert client.post("/predict", json={**payload, "magnitude": "bad"}).status_code == 422
        assert client.post("/predict", json={**payload, "reference_region": "alaska"}).status_code == 422
        assert client.post("/predict", json={**payload, "unknown": "extra"}).status_code == 422
        assert client.post("/predict-batch", json={"events": [payload, payload]}).json()["count"] == 2

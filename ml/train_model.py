"""Train a descriptive seismic-novelty model on an explicit historical reference period.

Unsupervised: no fabricated ground-truth labels, no accuracy / AUROC claims.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from shared.features import transform_features, FEATURE_NAMES


def train(input_csv: Path, artifact_path: Path, report_path: Path, train_before: str, validation_before: str):
    if not input_csv.is_file():
        raise FileNotFoundError(f"Dataset not found: {input_csv}. Run the official USGS downloader first.")
    raw = pd.read_csv(input_csv)
    required = {"id", "time", "magnitude", "depth_km"}
    if not required.issubset(raw.columns):
        raise ValueError(f"Input missing required fields: {sorted(required - set(raw.columns))}")
    raw["time"] = pd.to_datetime(raw["time"], utc=True, errors="coerce", format="mixed")
    for col in ["magnitude", "depth_km"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    cleaned = raw.dropna(subset=["id", "time", "magnitude", "depth_km"]).drop_duplicates("id")
    cleaned = cleaned[cleaned.magnitude.between(-2, 10) & cleaned.depth_km.between(-20, 750)].copy()
    split1 = pd.Timestamp(train_before, tz="UTC")
    split2 = pd.Timestamp(validation_before, tz="UTC")
    if split2 <= split1:
        raise ValueError("validation_before must be after train_before")
    tr = cleaned[cleaned.time < split1].copy()
    val = cleaned[(cleaned.time >= split1) & (cleaned.time < split2)].copy()
    if len(tr) < 100 or len(val) < 30:
        raise ValueError(f"Need at least 100 historical train and 30 later validation events; found {len(tr)} and {len(val)}")
    x_train = transform_features(tr.magnitude.to_numpy(), tr.depth_km.to_numpy())
    x_val = transform_features(val.magnitude.to_numpy(), val.depth_km.to_numpy())
    scaler = StandardScaler().fit(x_train)
    model = IsolationForest(n_estimators=200, contamination="auto", random_state=42, n_jobs=1)
    model.fit(scaler.transform(x_train))
    # Higher = more unusual; NOT a calibrated probability of earthquake danger.
    scores_train = -model.score_samples(scaler.transform(x_train))
    scores_val = -model.score_samples(scaler.transform(x_val))
    threshold = float(np.quantile(scores_train, 0.95))
    region = "california_bbox"
    provenance_file = input_csv.with_suffix(".metadata.json")
    provenance = json.loads(provenance_file.read_text()) if provenance_file.exists() else {}
    if provenance and provenance.get("reference_region") != region:
        raise ValueError("Input provenance region does not match intended model reference region")
    meta = {
        "model_type": "IsolationForest", "model_version": "seismic-novelty-v0.1",
        "reference_region": region, "reference_region_kind": "geographic bounding box; not exact state borders",
        "features": FEATURE_NAMES, "training_data_sha256": hashlib.sha256(input_csv.read_bytes()).hexdigest(),
        "train_count": int(len(tr)), "validation_count": int(len(val)), "train_before_utc": str(split1),
        "validation_before_utc": str(split2), "train_observed_start_utc": str(tr.time.min()),
        "train_observed_end_utc": str(tr.time.max()), "trained_utc": datetime.now(timezone.utc).isoformat(),
        "threshold_method": "95th percentile of reference training scores", "threshold": threshold,
        "score_direction": "higher_is_more_unusual", "training_data_source": provenance.get("source", "Input dataset; see provenance"),
        "source_documentation": provenance.get("source_documentation", "https://earthquake.usgs.gov/fdsnws/event/1/"),
        "measurement_caution": "A model score is not an earthquake forecast, hazard probability, event likelihood, or safety assessment.",
        "evaluation_caution": "Unsupervised method: validation statistics describe score stability, not ground-truth accuracy.",
    }
    artifact = {"model": model, "scaler": scaler, "reference_scores_sorted": np.sort(scores_train), "metadata": meta}
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, artifact_path)
    report = {
        "analysis": "Temporal holdout and score distribution checks only; no verified anomaly labels",
        "training": {"count": int(len(tr)), "median_score": float(np.median(scores_train)),
                     "score_p95": float(np.quantile(scores_train, 0.95)), "fraction_flagged": float(np.mean(scores_train >= threshold))},
        "later_holdout": {"count": int(len(val)), "median_score": float(np.median(scores_val)),
                          "score_p95": float(np.quantile(scores_val, 0.95)), "fraction_flagged": float(np.mean(scores_val >= threshold))},
        "data_provenance": provenance, "model_metadata": meta,
        "interpretation": "A 5% tail threshold on training is definitional, not an estimated real-world anomaly rate. Holdout flags depend on catalog coverage and cannot establish forecast skill."
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/usgs_california_bbox_2018_2024.csv")
    parser.add_argument("--artifact", default="artifacts/isolation_forest.joblib")
    parser.add_argument("--report", default="artifacts/validation_report.json")
    parser.add_argument("--train-before", default="2023-01-01")
    parser.add_argument("--validation-before", default="2025-01-01")
    args = parser.parse_args()
    report = train(Path(args.input), Path(args.artifact), Path(args.report), args.train_before, args.validation_before)
    print(json.dumps({"training": report["training"], "later_holdout": report["later_holdout"], "interpretation": report["interpretation"]}, indent=2))


if __name__ == "__main__":
    main()

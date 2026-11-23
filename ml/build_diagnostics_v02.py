"""Build a version-checked, read-only scientific diagnostics snapshot.

Scores actual USGS CSV rows using the existing trusted trained artifact. This
runs OFFLINE as a separate step, not inside Streamlit and not in FastAPI.
No model fitting, original data edits, GitHub actions or deployment.

From the isolated workbench root:
    python -m ml.build_diagnostics_v02
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

from shared.features import transform_features

SCHEMA = "hazardscope-seismic-diagnostics-v0.2"
EXPECTED_REGION = "california_bbox"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(input_csv: Path, artifact_path: Path, out_csv: Path, out_meta: Path) -> dict:
    if not input_csv.is_file():
        raise FileNotFoundError(f"Dataset missing: {input_csv}")
    if not artifact_path.is_file():
        raise FileNotFoundError(f"Trained artifact missing: {artifact_path}")
    csv_digest = sha256(input_csv)
    # Loading joblib is unsafe for untrusted files: use ONLY the locally trained artifact.
    bundle = joblib.load(artifact_path)
    metadata = bundle["metadata"]
    if csv_digest != metadata.get("training_data_sha256"):
        raise ValueError("STOP: Dataset SHA-256 differs from the one used to train the saved model")
    if metadata.get("reference_region") != EXPECTED_REGION:
        raise ValueError("STOP: Trained model is not for the California bounding-box reference")
    if metadata.get("score_direction") != "higher_is_more_unusual":
        raise ValueError("STOP: Unexpected model score direction")
    if int(metadata.get("train_count", -1)) < 1 or int(metadata.get("validation_count", -1)) < 1:
        raise ValueError("STOP: Incomplete model training counts")

    frame = pd.read_csv(input_csv)
    required = {"id", "time", "magnitude", "depth_km"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Required columns missing: {sorted(required - set(frame.columns))}")
    raw_count = len(frame)
    frame["time"] = pd.to_datetime(frame["time"], utc=True, errors="coerce", format="mixed")
    for col in ("magnitude", "depth_km"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    cleaned = frame.dropna(subset=["id", "time", "magnitude", "depth_km"]).drop_duplicates("id")
    cleaned = cleaned[cleaned.magnitude.between(-2, 10) & cleaned.depth_km.between(-20, 750)].copy()
    if len(cleaned) != raw_count:
        raise ValueError(f"STOP: {raw_count - len(cleaned)} source rows were excluded; inspect before proceeding")

    split_start = pd.to_datetime(metadata["train_before_utc"], utc=True)
    split_end = pd.to_datetime(metadata["validation_before_utc"], utc=True)
    train_mask = cleaned["time"] < split_start
    valid_mask = (cleaned["time"] >= split_start) & (cleaned["time"] < split_end)
    if (train_mask | valid_mask).sum() != len(cleaned):
        raise ValueError("STOP: Source data contains rows outside training and holdout windows")
    if int(train_mask.sum()) != int(metadata["train_count"]) or int(valid_mask.sum()) != int(metadata["validation_count"]):
        raise ValueError("STOP: Split counts differ from trained-model metadata")

    features = transform_features(cleaned.magnitude.to_numpy(), cleaned.depth_km.to_numpy())
    scaled = bundle["scaler"].transform(features)
    scores = -bundle["model"].score_samples(scaled)
    if not np.isfinite(scores).all():
        raise ValueError("STOP: Model produced non-finite scores")
    refs = np.asarray(bundle["reference_scores_sorted"], dtype=float)
    if len(refs) != int(metadata["train_count"]):
        raise ValueError("STOP: Reference-score array length differs from training count")
    threshold = float(metadata["threshold"])
    cleaned["split"] = np.where(train_mask, "Training", "Holdout")
    cleaned["anomaly_score"] = scores
    cleaned["reference_score_percentile"] = np.round(100 * np.searchsorted(refs, scores, side="right") / len(refs), 2)
    cleaned["flagged"] = scores >= threshold
    cols = ["id", "time", "magnitude", "depth_km", "split", "anomaly_score", "reference_score_percentile", "flagged"]
    cols += [c for c in ("lat", "lon", "source_url") if c in cleaned.columns]
    output = cleaned[cols].sort_values("time").reset_index(drop=True)

    provenance_path = input_csv.with_suffix(".metadata.json")
    provenance = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.is_file() else {}
    if provenance and provenance.get("csv_sha256") not in (None, csv_digest):
        raise ValueError("STOP: Dataset provenance checksum does not match source CSV")
    summary = {
        "schema": SCHEMA,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "status": "DERIVED_OFFLINE_FROM_LOCAL_USGS_SNAPSHOT_AND_TRAINED_MODEL",
        "source_csv_sha256": csv_digest,
        "source_csv_name": input_csv.name,
        "source_documentation": metadata.get("source_documentation"),
        "source_retrieved_utc": provenance.get("retrieved_utc"),
        "source_query": provenance.get("query"),
        "reference_region": EXPECTED_REGION,
        "region_description": "California geographic bounding box; not exact state boundary",
        "model_version": metadata["model_version"],
        "model_trained_utc": metadata.get("trained_utc"),
        "model_training_data_sha256": metadata["training_data_sha256"],
        "train_before_utc": metadata["train_before_utc"],
        "validation_before_utc": metadata["validation_before_utc"],
        "threshold": threshold,
        "threshold_method": metadata["threshold_method"],
        "training_observations": int(train_mask.sum()),
        "holdout_observations": int(valid_mask.sum()),
        "training_flagged": int((output.split.eq("Training") & output.flagged).sum()),
        "holdout_flagged": int((output.split.eq("Holdout") & output.flagged).sum()),
        "source_event_type_verification": "NOT_VERIFIED_FOR_ALL_ROWS",
        "depth_quality_metadata": "NOT_INCLUDED_IN_SOURCE_CSV",
        "input_transform_note": "Training model uses magnitude and log1p(max(depth_km,0)); reported depths preserved in derived table",
        "warning": "DESCRIPTIVE novelty only; no ground-truth accuracy, risk probability, or forecast skill established",
    }
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_meta.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(out_csv, index=False)
    summary["derived_csv_sha256"] = sha256(out_csv)
    out_meta.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a local, version-checked diagnostics snapshot")
    parser.add_argument("--input", type=Path, default=Path("data/usgs_california_bbox_2018_2024.csv"))
    parser.add_argument("--artifact", type=Path, default=Path("artifacts/isolation_forest.joblib"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/diagnostics_v02.csv"))
    parser.add_argument("--metadata", type=Path, default=Path("artifacts/diagnostics_v02.metadata.json"))
    args = parser.parse_args()
    result = build(args.input, args.artifact, args.output, args.metadata)
    print(json.dumps({k: result[k] for k in (
        "schema", "training_observations", "holdout_observations", "training_flagged",
        "holdout_flagged", "model_version", "source_csv_sha256", "warning")}, indent=2))
    print(f"Created: {args.output} and {args.metadata}")
    print("No training, original CSV edits, GitHub or production deployment took place.")


if __name__ == "__main__":
    main()

"""Pure, testable helpers for the isolated Streamlit v0.2 explorer."""
from __future__ import annotations

import numpy as np
import pandas as pd

DEPTH_LABELS = ["≤0 km", "0–1 km", "1–5 km", "5–10 km", "10–20 km", ">20 km"]
DEPTH_EDGES = [-np.inf, 0.0, 1.0, 5.0, 10.0, 20.0, np.inf]


def prediction_signature(magnitude: float, depth_km: float, reference_region: str, model_identity: str) -> tuple:
    """Exact submitted form state; results are stale if any component changes."""
    return (float(magnitude), float(depth_km), str(reference_region), str(model_identity))


def attach_depth_bands(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["depth_band"] = pd.cut(out["depth_km"], bins=DEPTH_EDGES, labels=DEPTH_LABELS)
    return out


def depth_band_summary(df: pd.DataFrame) -> pd.DataFrame:
    data = attach_depth_bands(df)
    agg = data.groupby("depth_band", observed=False).agg(
        observations=("id", "size"), flagged=("flagged", "sum")
    ).reset_index()
    agg["flag_rate_pct"] = np.where(
        agg["observations"] > 0, 100 * agg["flagged"] / agg["observations"], np.nan
    )
    agg["depth_band"] = agg["depth_band"].astype(str)
    return agg


def score_distribution_percent(df: pd.DataFrame, bins: int = 28) -> pd.DataFrame:
    """Same bin edges for both periods; normalize WITHIN split, not raw counts."""
    if df.empty:
        return pd.DataFrame(columns=["split", "bin_center", "bin_start", "bin_end", "percentage", "count"])
    values = pd.to_numeric(df["anomaly_score"], errors="raise").to_numpy(dtype=float)
    edges = np.histogram_bin_edges(values, bins=bins)
    if edges[0] == edges[-1]:
        edges = np.linspace(edges[0] - 0.01, edges[-1] + 0.01, bins + 1)
    rows = []
    for split, part in df.groupby("split", sort=False):
        counts, _ = np.histogram(part["anomaly_score"].to_numpy(dtype=float), bins=edges)
        total = int(counts.sum())
        for i, count in enumerate(counts):
            rows.append({"split": split, "bin_center": float((edges[i] + edges[i + 1]) / 2),
                         "bin_start": float(edges[i]), "bin_end": float(edges[i + 1]),
                         "percentage": 100.0 * int(count) / total if total else 0.0,
                         "count": int(count)})
    return pd.DataFrame(rows)


def annual_flag_summary(df: pd.DataFrame) -> pd.DataFrame:
    part = df.copy()
    part["year"] = pd.to_datetime(part["time"], utc=True).dt.year.astype(int)
    out = part.groupby(["year", "split"], as_index=False).agg(
        observed=("id", "size"), flagged=("flagged", "sum")
    )
    out["flag_rate_pct"] = 100 * out["flagged"] / out["observed"]
    out["year"] = out["year"].astype(str)
    return out

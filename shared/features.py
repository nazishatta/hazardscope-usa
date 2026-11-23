"""The shared, versioned model input transformation. No online data access."""
from __future__ import annotations
import numpy as np

FEATURE_NAMES = ["magnitude", "log1p_clipped_depth_km"]


def transform_features(magnitude, depth_km):
    """Fixed training/inference transformation: log depth, clipped below sea level."""
    magnitude = np.asarray(magnitude, dtype=float)
    depth_km = np.asarray(depth_km, dtype=float)
    if magnitude.ndim != 1 or depth_km.ndim != 1 or len(magnitude) != len(depth_km):
        raise ValueError("Magnitude and depth must be same-length 1D arrays")
    if not np.isfinite(magnitude).all() or not np.isfinite(depth_km).all():
        raise ValueError("Nonfinite model input")
    if np.any((magnitude < -2) | (magnitude > 10)) or np.any((depth_km < -20) | (depth_km > 750)):
        raise ValueError("Input outside declared measurement limits")
    return np.column_stack([magnitude, np.log1p(np.clip(depth_km, 0, None))])

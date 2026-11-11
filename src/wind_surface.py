"""Continuous interpolated wind-speed visualization for HazardScope USA.

This presents the sampled model grid, *not* additional measured observations.
No network access, geocoding, or geographic state assignment occurs here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def smoothed_wind_map(df: pd.DataFrame) -> go.Figure:
    """Plot a smooth but conservative wind-speed field on longitude/latitude axes.

    Requires a rectangular sampled field with columns lat, lon and speed.
    Plotly smooths the *rendering* of the original grid; no values are added to
    the dataset, and the hover values are sampled/interpolated display values.
    """
    required = {"lat", "lon", "speed"}
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(f"Wind field missing columns: {sorted(missing)}")
    clean = df[["lat", "lon", "speed"]].copy()
    for column in ("lat", "lon", "speed"):
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    clean = clean.replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        raise ValueError("No valid wind-speed samples are available")
    grid = clean.pivot_table(index="lat", columns="lon", values="speed", aggfunc="mean")
    grid = grid.sort_index().sort_index(axis=1)
    if grid.shape[0] < 2 or grid.shape[1] < 2:
        raise ValueError("At least two distinct latitudes and longitudes are required")
    # Fill isolated missing grid cells in a conservative way, without inventing
    # observations outside the sampled lat/lon extent.
    grid = grid.interpolate(axis=0, limit_direction="both")
    grid = grid.interpolate(axis=1, limit_direction="both")
    colors = [
        [0.00, "#132543"],
        [0.14, "#225a9e"],
        [0.30, "#15a5c1"],
        [0.47, "#2cddbc"],
        [0.62, "#a9e65b"],
        [0.78, "#ffd06a"],
        [0.90, "#f58b48"],
        [1.00, "#ed4d51"],
    ]
    fig = go.Figure()
    fig.add_trace(go.Heatmap(
        x=grid.columns.to_numpy(dtype=float),
        y=grid.index.to_numpy(dtype=float),
        z=grid.to_numpy(dtype=float),
        zsmooth="best",
        colorscale=colors,
        colorbar=dict(
            title=dict(text="Wind speed<br>km/h", side="top"),
            thickness=15,
            len=0.78,
            tickfont=dict(color="#b8c9de", size=11),
            outlinewidth=0,
        ),
        hovertemplate="Longitude %{x:.2f}°<br>Latitude %{y:.2f}°<br>Displayed wind speed %{z:.1f} km/h<extra></extra>",
        name="Interpolated wind speed",
    ))
    # Thin sample contours give a legible gradient without pretending the grid
    # contains more weather model samples than it does.
    fig.add_trace(go.Contour(
        x=grid.columns.to_numpy(dtype=float),
        y=grid.index.to_numpy(dtype=float),
        z=grid.to_numpy(dtype=float),
        contours=dict(coloring="none", showlabels=False),
        line=dict(color="rgba(243,249,255,0.27)", width=0.6),
        showscale=False,
        hoverinfo="skip",
        name="Speed contours",
        showlegend=False,
        ncontours=10,
    ))
    fig.update_layout(
        title=dict(text="Wind Speed & Geographic Patterns", font=dict(size=18)),
        height=515,
        paper_bgcolor="#080c15",
        plot_bgcolor="#101a2b",
        font=dict(color="#e9f0f8"),
        margin=dict(l=65, r=25, t=62, b=55),
        xaxis=dict(title="Longitude", gridcolor="rgba(159,183,211,.11)", zeroline=False),
        yaxis=dict(title="Latitude", gridcolor="rgba(159,183,211,.11)", zeroline=False),
        showlegend=False,
    )
    return fig

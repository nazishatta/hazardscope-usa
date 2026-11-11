"""Standalone, zero-network earthquake density animation for fetched USGS records.

This module does NOT modify wind rendering, network calls, or other tabs.
"""
from __future__ import annotations
from pathlib import Path
import json
import math
import pandas as pd

HERE = Path(__file__).resolve().parent


def seismic_animation_html(df: pd.DataFrame, region: str = 'US', bounds=None) -> str:
    """Return a bounded interactive Canvas view using genuine fetched USGS events."""
    if df is None or df.empty:
        return '<p style="color:#d3dce9">No earthquakes to animate. Fetch USGS data first.</p>'
    required = {'lat', 'lon', 'magnitude', 'time'}
    if not required.issubset(df.columns):
        return '<p style="color:#d3dce9">Missing earthquake fields for animation.</p>'
    sample = df.dropna(subset=list(required)).copy()
    sample['time'] = pd.to_datetime(sample['time'], utc=True, errors='coerce')
    sample = sample.dropna(subset=list(required)).sort_values('time', kind='stable').tail(2500)
    items = []
    for row in sample.itertuples():
        try:
            lon, lat, mag = float(row.lon), float(row.lat), float(row.magnitude)
            if not all(map(math.isfinite, [lon, lat, mag])) or abs(lat) > 90 or abs(lon) > 180:
                continue
            timestamp = row.time.isoformat()
            items.append([round(lon, 5), round(lat, 5), round(mag, 3), timestamp])
        except (TypeError, ValueError, AttributeError):
            continue
    if not items:
        return '<p style="color:#d3dce9">No valid earthquake coordinates to animate.</p>'

    # GeoJSON outlines are display context, not a spatial-join or accurate state selection.
    outline_path = HERE / 'us_outline.json'
    outline = json.loads(outline_path.read_text()) if outline_path.exists() else None
    if bounds and len(bounds) == 4:
        s, n, w, e = map(float, bounds)
    else:
        s, n, w, e = 17., 72., -170., -65.
    if region == 'US':
        # Historical USGS "US" bounding region, inclusive of Alaska and Hawaii.
        view = [-170, -65, 17, 72]
    else:
        # Preserve the user's selected API bounding box (with small visible margins).
        pad_x = max((e-w)*.10, .6)
        pad_y = max((n-s)*.10, .6)
        view = [w-pad_x, e+pad_x, s-pad_y, n+pad_y]
    config = {
        'events': items,
        'outline': outline,
        'bounds': view,
        'region': str(region),
        'first': items[0][3],
        'last': items[-1][3],
    }
    template = (HERE / 'seismic_animation.html').read_text()
    payload = json.dumps(config, separators=(',', ':'), ensure_ascii=True).replace('</', '<\\/')
    return template.replace('__SEISMIC_DATA__', payload)

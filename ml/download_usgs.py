"""Download historical USGS GeoJSON in pages with provenance and a hard size cap.

Run from project root using `python -m ml.download_usgs ...`.
Data are sourced from USGS; this script intentionally NEVER generates fake records.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import pandas as pd
import requests

BASE = "https://earthquake.usgs.gov/fdsnws/event/1"
REGIONS = {
    # A BOUNDING BOX, not California state borders. The model must be labelled accordingly.
    "california_bbox": {"minlatitude": 32.0, "maxlatitude": 42.2, "minlongitude": -125.0, "maxlongitude": -114.0},
}


def collect(*, start: str, end: str, min_magnitude: float, region: str, maximum: int = 100000, page_size: int = 5000):
    if region not in REGIONS:
        raise ValueError(f"Unsupported reference region: {region}")
    if not start < end:
        raise ValueError("start must precede end")
    query = {"starttime": start, "endtime": end, "minmagnitude": min_magnitude, **REGIONS[region]}
    headers = {"User-Agent": "HazardScopeUSA-Research/0.1 (educational research)", "Accept": "application/json"}
    with requests.Session() as session:
        count_response = session.get(f"{BASE}/count", params=query, headers=headers, timeout=45)
        count_response.raise_for_status()
        count = int(count_response.text.strip())
        if count > maximum:
            raise ValueError(f"Catalog has {count:,} rows; cap is {maximum:,}. Tighten time/magnitude range or increase cap intentionally.")
        if count == 0:
            raise ValueError("USGS catalog returned no matching events")
        rows = []
        request_urls = []
        for offset in range(1, count + 1, page_size):
            page_query = {**query, "format": "geojson", "orderby": "time-asc", "limit": min(page_size, count - offset + 1), "offset": offset}
            resp = session.get(f"{BASE}/query", params=page_query, headers=headers, timeout=90)
            resp.raise_for_status()
            request_urls.append(resp.url)
            obj = resp.json()
            if not isinstance(obj, dict) or not isinstance(obj.get("features"), list):
                raise ValueError(f"Unexpected USGS response at offset {offset}")
            for feat in obj["features"]:
                props = feat.get("properties") or {}
                coords = (feat.get("geometry") or {}).get("coordinates") or []
                if len(coords) < 3:
                    continue
                rows.append({"id": str(feat.get("id") or ""), "time": pd.to_datetime(props.get("time"), unit="ms", utc=True, errors="coerce"),
                             "magnitude": props.get("mag"), "depth_km": coords[2], "lat": coords[1], "lon": coords[0],
                             "source_url": str(props.get("url") or "")})
            if offset + page_size <= count:
                time.sleep(0.2)
    df = pd.DataFrame(rows)
    for c in ["magnitude", "depth_km", "lat", "lon"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    valid = df.dropna(subset=["id", "time", "magnitude", "depth_km", "lat", "lon"]).copy()
    valid = valid[valid["id"].astype(str).str.len() > 0]
    valid = valid.drop_duplicates(subset=["id"], keep="last").sort_values("time").reset_index(drop=True)
    valid = valid[valid.magnitude.between(-2, 10) & valid.depth_km.between(-20, 750)]
    metadata = {"source": "USGS FDSN Earthquake Catalog API", "source_documentation": f"{BASE}/",
                "reference_region": region, "region_kind": "geographic bounding box, not state boundaries",
                "query": query, "reported_count": count, "raw_rows_read": len(df), "valid_unique_rows": len(valid),
                "retrieved_utc": datetime.now(timezone.utc).isoformat(), "request_urls": request_urls,
                "coverage_start_utc": valid.time.min().isoformat() if len(valid) else None,
                "coverage_end_utc": valid.time.max().isoformat() if len(valid) else None,
                "caution": "Event magnitude completeness varies by location, time, and reporting threshold. Does not represent hazard probability."}
    return valid, metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--min-magnitude", type=float, default=3.0)
    parser.add_argument("--region", choices=list(REGIONS), default="california_bbox")
    parser.add_argument("--maximum", type=int, default=100000)
    parser.add_argument("--output", default="data/usgs_california_bbox_2018_2024.csv")
    args = parser.parse_args()
    df, meta = collect(start=args.start, end=args.end, min_magnitude=args.min_magnitude, region=args.region, maximum=args.maximum)
    p = Path(args.output)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(p, index=False)
    meta["csv_sha256"] = hashlib.sha256(p.read_bytes()).hexdigest()
    p.with_suffix(".metadata.json").write_text(json.dumps(meta, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"Saved {len(df):,} verified unique earthquake records to {p}")
    print(f"Provenance: {p.with_suffix('.metadata.json')}")


if __name__ == "__main__":
    main()

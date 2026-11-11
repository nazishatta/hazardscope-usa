"""NOAA/NCEI historical tsunami explorer. Independent from live NWS warnings.

Sources: NOAA NGDC/NCEI ArcGIS REST hazards map service (historical catalogue),
Global Historical Tsunami Database doi:10.7289/V5PN93H7.
"""
from __future__ import annotations

import html
import json
import math
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components

SOURCE = 'https://gis.ngdc.noaa.gov/arcgis/rest/services/web_mercator/hazards/MapServer/0/query'
CATALOG = 'https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis'
FIELDS = ['ID', 'YEAR', 'MONTH', 'DAY', 'LATITUDE', 'LONGITUDE', 'LOCATION_NAME',
          'COUNTRY', 'CAUSE', 'EVENT_VALIDITY_CODE', 'EVENT_VALIDITY',
          'EQ_MAGNITUDE', 'MAX_EVENT_RUNUP', 'DEATHS', 'DEATHS_TOTAL']


def _number(v):
    try:
        out = float(v)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def normalize(features):
    """Only include source records with a valid coordinate and year. No imputation."""
    result = []
    ids = set()
    for feature in features:
        p = feature.get('properties') or feature.get('attributes') or {}
        geometry = feature.get('geometry') or {}
        coords = geometry.get('coordinates') or []
        if len(coords) >= 2:
            lon, lat = map(_number, coords[:2])
        else:
            lon, lat = _number(p.get('LONGITUDE')), _number(p.get('LATITUDE'))
        year = _number(p.get('YEAR'))
        validity = _number(p.get('EVENT_VALIDITY_CODE'))
        if None in (lon, lat, year) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue
        if not (1900 <= year <= datetime.now(timezone.utc).year):
            continue
        if validity is not None and validity < 2:
            continue
        item_id = str(p.get('ID') or p.get('OBJECTID') or f'{int(year)}:{lat}:{lon}')
        if item_id in ids:
            continue
        ids.add(item_id)
        result.append({
            'id': item_id, 'year': int(year), 'month': int(_number(p.get('MONTH')) or 0),
            'day': int(_number(p.get('DAY')) or 0), 'lat': lat, 'lon': lon,
            'location': str(p.get('LOCATION_NAME') or 'Unspecified location')[:130],
            'country': str(p.get('COUNTRY') or 'Not recorded')[:90],
            'cause': str(p.get('CAUSE') or 'Not recorded')[:80],
            'validity': str(p.get('EVENT_VALIDITY') or 'Not recorded')[:80],
            'magnitude': _number(p.get('EQ_MAGNITUDE')),
            'runup_m': _number(p.get('MAX_EVENT_RUNUP')),
            'tsunami_deaths': _number(p.get('DEATHS')),
            'total_deaths': _number(p.get('DEATHS_TOTAL')),
        })
    return sorted(result, key=lambda x: (x['year'], x['month'], x['day'], x['id']))


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_history():
    """Fetch and cache real NOAA source events. Fail visibly; never use demo events."""
    headers = {'User-Agent': 'HazardScopeUSA/1.0 (educational historical tsunami visualization)',
               'Accept': 'application/json'}
    features = []
    offset = 0
    while offset < 8000:
        params = {
            'where': 'YEAR >= 1900 AND YEAR <= 2026 AND EVENT_VALIDITY_CODE >= 2',
            'outFields': ','.join(FIELDS), 'returnGeometry': 'true', 'outSR': 4326,
            'f': 'geojson', 'resultOffset': offset, 'resultRecordCount': 1000,
            'orderByFields': 'YEAR ASC, ID ASC',
        }
        response = requests.get(SOURCE, params=params, headers=headers, timeout=35)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get('error'):
            raise ValueError(f"NOAA map service error: {payload['error'].get('message','Unknown error')}")
        batch = payload.get('features') if isinstance(payload, dict) else None
        if not isinstance(batch, list):
            raise ValueError('NOAA historical tsunami API did not return a feature collection.')
        features.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    events = normalize(features)
    if not events:
        raise ValueError('No validated historical tsunami events returned by NOAA.')
    return events, {'endpoint': SOURCE, 'rows': len(events),
                    'fetched_utc': datetime.now(timezone.utc).isoformat(),
                    'time_coverage': '1900–2026; reported validity >= 2',
                    'note': 'Source-event points, not inundation footprints or simulated wave arrivals.'}


def _encode(value):
    # Prevent a string containing closing HTML tags from affecting the script element.
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')


def visualization_html(events):
    shapes = json.loads(Path(__file__).with_name('world_land.json').read_text())
    raw = Path(__file__).with_name('tsunami_canvas.html').read_text(encoding='utf-8')
    return raw.replace('/*__EVENTS__*/', _encode(events)).replace('/*__LAND__*/', _encode(shapes))


def render_section():
    st.markdown('---')
    st.subheader('Historical Tsunami Intelligence')
    st.write('Explore recorded tsunami **source events** from the NOAA/NCEI Global Historical Tsunami Database. '
             'The map plays automatically through historical years. Event pulses highlight recorded source locations; '
             'they are **not modeled wave propagation**, hazard zones, or inundation forecasts.')
    try:
        with st.spinner('Loading NOAA historical tsunami catalogue (cached for 24 hours)…'):
            events, meta = fetch_history()
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        st.error('Official NOAA historical records could not be loaded. No illustrative or fabricated events have been substituted.')
        st.caption(f'Source issue: {str(exc)[:280]}')
        st.link_button('Open NOAA historical tsunami database', CATALOG)
        return
    known_runup = sum(v['runup_m'] is not None for v in events)
    c1, c2, c3 = st.columns(3)
    c1.metric('Historical source events', f'{len(events):,}')
    c2.metric('Years represented', f"{events[0]['year']}–{events[-1]['year']}")
    c3.metric('Records with runup data', f'{known_runup:,}')
    components.html(visualization_html(events), height=660, scrolling=False)
    st.caption('**Data:** NOAA/NCEI Global Historical Tsunami Database (doi:10.7289/V5PN93H7), retrieved through the official NOAA GIS service. '
               '**Projection:** equirectangular world overview (WGS84 longitude/latitude). '
               '**Marks:** source coordinates, not observed coastal runup locations. '
               '**Animation:** chronological event highlighting with illustrative, non-physical pulses; timing is compressed and repeated. '
               '**Runup:** the maximum reported height associated with an event, not a simulated traveling wave height. '
               '**Missing impacts:** displayed as not reported, never treated as zero. '
               '**Coverage:** 1900–2026, NOAA validity classification >= 2; historical reporting is uneven.')
    with st.expander('Inspect NOAA tsunami source records and provenance'):
        st.caption(f"Source refreshed {meta['fetched_utc']}; {meta['rows']:,} validated events.")
        df = pd.DataFrame(events)
        st.dataframe(df, width='stretch', hide_index=True)
        st.download_button('Download displayed tsunami records CSV', df.to_csv(index=False).encode('utf-8'),
                           'noaa_tsunami_history.csv', 'text/csv')
    st.link_button('NOAA NCEI historical tsunami database', CATALOG)

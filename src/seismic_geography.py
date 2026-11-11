"""HazardScope earthquake spatial/attribute joins and layered Census choropleth.

Primary: fetched USGS points; boundaries: Census 2024 generalized state polygons;
denominator: Census ACS 2024 1-year B01003_001E state population.
"""
from __future__ import annotations

import io
import json
import math
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests

BOUNDARY_URL = 'https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_500k.zip'
POPULATION_URL = 'https://api.census.gov/data/2024/acs/acs1?get=NAME,B01003_001E&for=state:*'
DATA_DIR = Path(__file__).resolve().parents[1] / 'data' / 'seismic_geography'
# The national USGS bounding box in this app covers approximately contiguous US.
OUTSIDE_NATIONAL_QUERY = {'02', '15', '60', '66', '69', '72', '78'}


def obtain_sources(data_dir=DATA_DIR, refresh=False, get=requests.get, api_key=None):
    """Download and validate official Census sources; keep working local caches."""
    from urllib.parse import quote
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    zip_path = data_dir / 'cb_2024_us_state_500k.zip'
    pop_path = data_dir / 'acs1_2024_state_population.json'
    for name, url, path in (
        ('2024 Census state boundaries', BOUNDARY_URL, zip_path),
        ('2024 ACS state population', POPULATION_URL, pop_path),
    ):
        # Do not re-download a verified cache merely because the other source was missing.
        if path.exists():
            try:
                cached = path.read_bytes()
                if name.startswith('2024 Census') and zipfile.is_zipfile(io.BytesIO(cached)):
                    if not refresh:
                        continue
                elif name.startswith('2024 ACS') and _valid_acs(cached):
                    if not refresh:
                        continue
            except (OSError, ValueError, json.JSONDecodeError):
                pass
        if name.startswith('2024 ACS') and not api_key:
            raise ValueError('Census ACS population requires a free API key. Enter your key in the password field above, then click Load again. Official Census API examples now require a key.')
        request_url = url + ('&key=' + quote(api_key, safe='') if name.startswith('2024 ACS') else '')
        try:
            response = get(request_url, timeout=45, headers={'User-Agent': 'HazardScopeUSA/1.0 academic visualization'})
            response.raise_for_status()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            raise ValueError(f'{name} request failed' + (f' (HTTP {status})' if status else '') + '. Check your internet connection, Census API key, and Census service status.') from None
        raw = response.content
        if name.startswith('2024 Census'):
            if not zipfile.is_zipfile(io.BytesIO(raw)):
                raise ValueError(f'{name} returned a non-ZIP response (HTTP {response.status_code}, {len(raw)} bytes). Census may be unavailable or blocking the request.')
        elif not _valid_acs(raw):
            preview = raw[:140].decode('utf-8', errors='replace').replace('\n', ' ').replace('\r', ' ')
            # Never disclose URL/key in diagnostics. Limit response preview to avoid dumping secrets.
            raise ValueError(f'{name} returned invalid data (HTTP {response.status_code}, {len(raw)} bytes). Response begins: {preview!r}. Check whether your Census key is activated.')
        tmp = path.with_suffix(path.suffix + '.tmp')
        tmp.write_bytes(raw)
        tmp.replace(path)
    return zip_path, pop_path


def _valid_acs(raw):
    try:
        rows = json.loads(raw)
        return (isinstance(rows, list) and len(rows) > 1 and isinstance(rows[0], list)
                and {'NAME', 'B01003_001E', 'state'}.issubset(set(rows[0])))
    except (ValueError, TypeError, UnicodeDecodeError):
        return False


def load_boundaries(zip_path):
    """Read Census shapefile directly from downloaded ZIP; avoid GeoPandas installation."""
    import shapefile
    from shapely.geometry import shape
    with zipfile.ZipFile(zip_path) as zf:
        shp = next(n for n in zf.namelist() if n.lower().endswith('.shp'))
        dbf = next(n for n in zf.namelist() if n.lower().endswith('.dbf'))
        shx = next(n for n in zf.namelist() if n.lower().endswith('.shx'))
        reader = shapefile.Reader(shp=io.BytesIO(zf.read(shp)),
                                  dbf=io.BytesIO(zf.read(dbf)),
                                  shx=io.BytesIO(zf.read(shx)))
        fields = [f[0] for f in reader.fields[1:]]
        result = []
        for row in reader.iterShapeRecords():
            attrs = dict(zip(fields, row.record))
            fips = str(attrs['GEOID']).zfill(2)
            geom = shape(row.shape.__geo_interface__)
            if geom.is_empty:
                continue
            result.append({'fips': fips, 'name': str(attrs['NAME']),
                           'abbr': str(attrs.get('STUSPS', '')), 'geometry': geom})
    if len(result) < 50:
        raise ValueError('Census boundary file has fewer than 50 state/equivalent records.')
    if len({r['fips'] for r in result}) != len(result):
        raise ValueError('Duplicate Census GEOID values in boundary file.')
    return result


def load_population(pop_path):
    """A Census attribute table keyed by state FIPS, preserving leading zeroes."""
    rows = json.loads(Path(pop_path).read_text())
    if not rows or not isinstance(rows[0], list):
        raise ValueError('Invalid Census ACS population table.')
    df = pd.DataFrame(rows[1:], columns=rows[0])
    required = {'NAME', 'B01003_001E', 'state'}
    if not required.issubset(df.columns):
        raise ValueError('Census ACS population response lacks expected fields.')
    df = df.rename(columns={'NAME': 'census_name', 'B01003_001E': 'population', 'state': 'fips'})
    df['fips'] = df['fips'].astype(str).str.zfill(2)
    df['population'] = pd.to_numeric(df['population'], errors='coerce')
    df.loc[df['population'] <= 0, 'population'] = np.nan
    if df['fips'].duplicated().any():
        raise ValueError('Duplicate state FIPS in Census population data.')
    return df[['fips', 'census_name', 'population']]


def spatial_join(quakes, regions):
    """Point-in-polygon (covers boundary locations); unmatched remain explicit."""
    from shapely.geometry import Point
    from shapely.prepared import prep
    prepared = [(r['fips'], prep(r['geometry'])) for r in regions]
    assigned = []
    for lat, lon in zip(quakes['lat'], quakes['lon']):
        try:
            lat, lon = float(lat), float(lon)
            valid = math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180
        except (ValueError, TypeError):
            valid = False
        if not valid:
            assigned.append((None, 'Invalid coordinate'))
            continue
        point = Point(lon, lat)
        fips = next((fips for fips, polygon in prepared if polygon.covers(point)), None)
        assigned.append((fips, 'Matched to polygon' if fips else 'Outside state-equivalent polygons / offshore'))
    df = quakes.copy().reset_index(drop=True)
    df['fips'] = [a for a, _ in assigned]
    df['spatial_join_status'] = [b for _, b in assigned]
    assert len(df) == len(quakes)
    return df


def build_statistics(points, regions, pop, region_code='US'):
    """Explicit attribute merge and denominator/coverage controls."""
    # Display the national USGS fetch footprint without converting unqueried AK/HI into zeroes.
    region_rows = [{'fips': r['fips'], 'state': r['name'], 'abbr': r['abbr']} for r in regions]
    states = pd.DataFrame(region_rows)
    counts = points.loc[points['fips'].notna(), 'fips'].value_counts().rename_axis('fips').reset_index(name='events')
    base = states.merge(counts, how='left', on='fips', validate='one_to_one')
    base['events'] = base['events'].fillna(0).astype(int)
    merged = base.merge(pop, how='left', on='fips', validate='one_to_one', indicator='population_join')
    merged['in_query_footprint'] = (~merged['fips'].isin(OUTSIDE_NATIONAL_QUERY)) if region_code == 'US' else (merged['abbr'] == region_code)
    merged['rate_million'] = np.where(merged['in_query_footprint'] & merged['population'].gt(0),
                                      merged['events'] * 1_000_000 / merged['population'], np.nan)
    # Distinguish no matched population from no geographic coverage.
    merged['coverage'] = np.select(
        [~merged['in_query_footprint'], merged['population'].isna()],
        ['Outside selected USGS query area', 'Census population unavailable'], default='Included')
    return merged


def classify_quantiles(values, max_classes=5):
    """Quantile breaks, collapsing duplicate cut points; never separate equal values."""
    valid = pd.Series(values, dtype=float).dropna()
    if valid.empty:
        return [], []
    quantiles = np.unique(np.quantile(valid, np.linspace(0, 1, max_classes + 1)))
    if len(quantiles) == 1:
        return [float(quantiles[0])], [f'{quantiles[0]:.2f} (one observed value)']
    breaks = quantiles.tolist()
    labels = [f'{a:.2f}–{b:.2f}' for a, b in zip(breaks[:-1], breaks[1:])]
    return breaks, labels


def map_figure(stats, points, regions, region_code='US', measure='rate_million', show_points=True):
    """True layered polygon choropleth + USGS epicenters in Albers USA."""
    # Plotly scope=usa has an Albers projection; non-CONUS islands are not mapped.
    plot_stats = stats.loc[stats['in_query_footprint'] & stats['fips'].isin(
        [r['fips'] for r in regions if r['abbr'] not in {'PR', 'GU', 'VI', 'AS', 'MP'}])].copy()
    breaks, labels = classify_quantiles(plot_stats[measure])
    plot_stats['class'] = np.nan
    if breaks:
        if len(breaks) == 1:
            plot_stats.loc[plot_stats[measure].notna(), 'class'] = 0
        else:
            # searchsorted right - 1 clips max and ensures equal values get equal classes.
            v = plot_stats[measure].to_numpy(dtype=float)
            good = np.isfinite(v)
            plot_stats.loc[good, 'class'] = np.clip(np.searchsorted(breaks, v[good], side='left') - 1, 0, len(labels)-1)
    features = [{'type':'Feature','properties': {'GEOID': r['fips'], 'NAME': r['name']},
                 'geometry': r['geometry'].__geo_interface__} for r in regions]
    geojson = {'type':'FeatureCollection','features':features}
    cmap = [[0.0, '#21364d'], [0.25, '#187b9b'], [0.55, '#3fbfbb'], [0.8, '#f1b05e'], [1.0, '#ec6c50']]
    fig = go.Figure()
    fig.add_trace(go.Choropleth(
        geojson=geojson, featureidkey='properties.GEOID', locations=plot_stats['fips'],
        z=plot_stats['class'], zmin=0, zmax=max(1, len(labels)-1), colorscale=cmap,
        marker_line_color='#4b6072', marker_line_width=0.6,
        customdata=plot_stats.assign(population=plot_stats['population'].fillna(-1).astype(int),
                     rate_million=plot_stats['rate_million'].round(3).fillna(-1))
                     [['events','rate_million','population','coverage']].to_numpy(dtype=object),
        hovertemplate='<b>%{location}</b><br>Events: %{customdata[0]}<br>Events / 1M residents: %{customdata[1]}<br>Population: %{customdata[2]:,}<extra></extra>',
        colorbar=dict(title='Quantile class',tickvals=list(range(len(labels))), ticktext=labels, len=0.65),
        name='Census states · classified count/population'))
    if show_points and not points.empty:
        sample = points[points['lon'].notna() & points['lat'].notna()].copy()
        if len(sample) > 1600:
            sample = sample.nlargest(1600, 'magnitude')
        fig.add_trace(go.Scattergeo(lon=sample['lon'], lat=sample['lat'], mode='markers',
            marker={'size': np.clip(3.5 + sample['magnitude'].clip(lower=0).to_numpy() * 1.5, 4, 17),
                    'color': '#fcdb8c', 'opacity': 0.67, 'line': {'color':'#222c3b','width':0.4}},
            text=sample['place'].astype(str) if 'place' in sample else None,
            hovertemplate='%{text}<br>%{lat:.2f}, %{lon:.2f}<extra>Recorded earthquake</extra>',
            name='USGS earthquake epicenters'))
    fig.update_geos(scope='usa', projection_type='albers usa', showland=True,
                    landcolor='#111b2b', showlakes=False, bgcolor='#080c15')
    fig.update_layout(height=560, paper_bgcolor='#080c15', plot_bgcolor='#080c15',
                      font={'color':'#e9f2fc'}, margin={'l':0,'r':0,'t':12,'b':0},
                      legend={'orientation':'h','y':-0.02,'x':0})
    return fig, labels


def render_section(quakes, region_code, query_key=None, source_meta=None):
    import streamlit as st
    with st.container():
        st.markdown('### Seismic Geography & Population Analysis')
        st.write('A **2024 Census state-boundary choropleth** paired with recorded USGS earthquake epicenters. This section demonstrates a true point-in-polygon spatial join and a second, FIPS-based join to Census population. The default colors show **earthquake events per million residents**, not earthquake risk.')
        st.caption('The national USGS query in this dashboard uses an approximate contiguous-U.S. bounding box. Alaska, Hawaii and territories are not compared as zero-event states. State-specific fetches must not be interpreted as a nationwide ranking.')
        # HAZARDSCOPE_SERVER_CENSUS_SECRET_V1: only the server handles credentials.
        # In Streamlit Community Cloud, configure CENSUS_API_KEY under App Settings > Secrets.
        # Locally, place it in .streamlit/secrets.toml (excluded from Git).
        import os
        census_key = str(os.environ.get('CENSUS_API_KEY', '')).strip()
        try:
            census_key = str(st.secrets.get('CENSUS_API_KEY', '') or census_key).strip()
        except Exception:
            # A local secrets.toml does not exist on every developer machine.
            pass
        st.caption('Official Census geography and population are loaded automatically as needed. No Census login or API key is required from visitors.')
        refresh = st.button('Retry / load official Census geography', key='geo_load',
                            help='Use the server-side Census API key to obtain official population and boundary files.')
        boundary_cached = (DATA_DIR / 'cb_2024_us_state_500k.zip').is_file()
        population_cached = (DATA_DIR / 'acs1_2024_state_population.json').is_file()
        sources_cached = boundary_cached and population_cached
        # Request once on startup when the server is configured, instead of demanding
        # that every visitor supply a secret or click a second load button.
        automatic = (not sources_cached and bool(census_key)
                     and not st.session_state.get('geo_auto_load_failed', False))
        if refresh or automatic:
            try:
                obtain_sources(refresh=False, api_key=census_key)
                st.session_state['geo_sources_ready'] = True
                st.session_state['geo_auto_load_failed'] = False
            except Exception as exc:
                st.session_state['geo_auto_load_failed'] = True
                st.error(f'Official Census data could not be loaded: {exc}')
        if not ((DATA_DIR / 'cb_2024_us_state_500k.zip').is_file() and
                (DATA_DIR / 'acs1_2024_state_population.json').is_file()):
            if not census_key:
                st.warning('Census analysis is not configured on this server yet. The app owner must set CENSUS_API_KEY in Streamlit Secrets; visitors do not need to enter it.')
            else:
                st.info('Census data is temporarily unavailable. Use Retry above or try again later.')
            return
        try:
            regions = load_boundaries(DATA_DIR / 'cb_2024_us_state_500k.zip')
            pop = load_population(DATA_DIR / 'acs1_2024_state_population.json')
            points = spatial_join(quakes, regions)
            stats = build_statistics(points, regions, pop, region_code)
        except Exception as exc:
            st.error(f'Geographic join could not be completed: {exc}')
            return
        if query_key is not None and source_meta is not None:
            st.caption('Join calculations use the currently stored USGS fetch. If sidebar controls changed after fetching, refresh USGS events before interpreting the selected region.')
        total = len(points)
        unmatched = int(points['fips'].isna().sum())
        matched = total - unmatched
        attr_missing = int(stats.loc[stats['in_query_footprint'], 'population'].isna().sum())
        p1,p2,p3,p4 = st.columns(4)
        p1.metric('USGS events analyzed', f'{total:,}')
        p2.metric('Matched to state polygon', f'{matched:,}')
        p3.metric('Unmatched events', f'{unmatched:,}')
        p4.metric('Missing population joins', f'{attr_missing:,}')
        if query_key is not None and region_code != 'US':
            st.warning('Only the selected region’s approximate USGS bounding box was queried. Do not compare event counts across all states from this partial fetch.')
        if unmatched:
            why = points.loc[points['fips'].isna(), 'spatial_join_status'].value_counts().to_dict()
            st.caption('**Unmatched events (not discarded):** ' + '; '.join(f'{name}: {count}' for name,count in why.items()) + '. Offshore epicenters and points outside the Census state-equivalent polygons remain unmatched, even when near a state.')
        else:
            st.caption('All fetched valid USGS points were contained within a Census state-equivalent polygon; unmatched count = 0.')
        measure = st.radio('Choropleth measure', ['Events per million residents', 'Earthquake event count'], horizontal=True, key='geo_measure')
        measure_key = 'rate_million' if measure.startswith('Events per') else 'events'
        if measure_key == 'events':
            st.info('Event count is an unnormalized comparison. Use the population-normalized view to satisfy the assignment’s rate requirement.')
        show_points = st.toggle('Overlay individual USGS earthquake epicenters', value=True, key='geo_points')
        fig, classes = map_figure(stats, points, regions, region_code, measure_key, show_points)
        st.plotly_chart(fig, width='stretch', key='joined_seismic_geo_map')
        st.caption(f'**Layers:** 2024 Census state polygons colored by {measure.lower()} (quantile scheme: {len(classes)} observed class(es), up to 5; duplicate breaks collapsed), plus USGS earthquake epicenters as proportional-size dots' + ('.' if show_points else ' (point layer switched off).') + ' **Projection:** Albers USA. **Exclusions:** national query covers approximate contiguous US only; unmatched offshore points are counted, not assigned; overseas territories are not rendered by this projection. **Point size:** magnitude, capped 4–17 px. **Source vintage:** 2024 Census state polygons + ACS 2024 1-year population, same FIPS keys. **No heatmap:** radius and DBSCAN parameters not applicable.')
        if len(classes) < 2:
            st.info('Few distinct values: classification collapses to one observed class rather than fabricating differences. Widen the USGS time window or lower magnitude if informative state comparisons are needed.')
        with st.expander('See both joins, unmatched events, denominators and provenance', expanded=False):
            st.markdown('**Spatial join:** USGS (lon, lat, WGS84) → 2024 Census state-equivalent polygon using covers(point). **Attribute join:** 2-character state GEOID/FIPS → 2024 ACS 1-year B01003_001E total population. Identifiers remain text to preserve leading zeroes. Missing population is not treated as zero.')
            st.dataframe(stats[['state','abbr','fips','events','population','rate_million','population_join','coverage']].sort_values('state'), hide_index=True, width='stretch')
            st.download_button('Download spatial + attribute join CSV', stats.drop(columns=['in_query_footprint']).to_csv(index=False).encode(), 'hazardscope_state_seismic_rates.csv', 'text/csv', key='geo_export')
            if unmatched:
                st.dataframe(points.loc[points['fips'].isna(), ['id','lat','lon','place','spatial_join_status']].head(200), hide_index=True, width='stretch')
            st.caption(f'Official boundary ZIP: {BOUNDARY_URL} · Population API: {POPULATION_URL}')

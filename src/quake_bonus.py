"""HazardScope USA: coordinated USGS views and geographic DBSCAN bonus.

All data comes from the already-fetched USGS earthquake frame. No network calls.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from sklearn.cluster import DBSCAN
import streamlit as st

BG = '#080c15'
TEAL = '#41dfc1'
EARTH_RADIUS_KM = 6371.0088
COLORS = ['#35dac6', '#ffb35d', '#d49afa', '#79aafa', '#f17ea9', '#e4d85d', '#9bd57b', '#66c1ee']


def clean_events(frame):
    """Return only records with well-formed coordinates, magnitude and UTC time."""
    cols = ['lat', 'lon', 'time', 'magnitude', 'depth_km']
    if frame is None or not all(c in frame.columns for c in cols):
        return pd.DataFrame(columns=cols + ['id', 'place', 'utc_day'])
    d = frame.copy()
    for c in ['lat', 'lon', 'magnitude', 'depth_km']:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d['time'] = pd.to_datetime(d['time'], errors='coerce', utc=True)
    d = d.dropna(subset=cols)
    d = d[d.lat.between(-90, 90) & d.lon.between(-180, 180) & np.isfinite(d[['lat', 'lon', 'magnitude', 'depth_km']]).all(axis=1)].copy()
    if 'id' not in d: d['id'] = ''
    if 'place' not in d: d['place'] = ''
    d['utc_day'] = d['time'].dt.strftime('%Y-%m-%d')
    return d.reset_index(drop=True)


def dbscan_labels(frame, eps_km=75.0, min_samples=3):
    """Cluster earthquake epicenters using spherical haversine neighborhoods."""
    if not 0 < float(eps_km) <= 2000: raise ValueError('eps_km must be in (0, 2000]')
    if int(min_samples) < 2: raise ValueError('min_samples must be >= 2')
    if frame.empty:
        return np.empty(0, dtype=int)
    radians = np.radians(frame[['lat', 'lon']].to_numpy(dtype=float))
    return DBSCAN(eps=float(eps_km) / EARTH_RADIUS_KM, min_samples=int(min_samples), metric='haversine', algorithm='ball_tree').fit_predict(radians)


def cluster_summary(labels):
    labels = np.asarray(labels, dtype=int)
    return dict(clusters=len(set(labels.tolist()) - {-1}), noise=int(np.sum(labels == -1)), clustered=int(np.sum(labels >= 0)), total=int(len(labels)))


# HAZARDSCOPE_COORDINATED_SELECTION_FIX_V2
# Genuine Streamlit Plotly selection plus deterministic fallback.
def _selected_utc_day(plotly_event, days):
    """Decode Streamlit Plotly selection without assuming a specific point key."""
    if not plotly_event:
        return None
    try:
        selection = plotly_event.get('selection', {})
        points = selection.get('points', []) or []
        indices = selection.get('point_indices', []) or []
    except (AttributeError, TypeError):
        return None
    # Prefer event x, which survives Plotly's point-index differences.
    for p in reversed(points):
        x = p.get('x') if isinstance(p, dict) else None
        if x is not None and str(x) in days:
            return str(x)
    for p in reversed(points):
        if not isinstance(p, dict):
            continue
        ix = p.get('point_index', p.get('pointNumber', p.get('point_number')))
        if isinstance(ix, (int, np.integer)) and 0 <= ix < len(days):
            return days[ix]
    for ix in reversed(indices):
        if isinstance(ix, (int, np.integer)) and 0 <= ix < len(days):
            return days[ix]
    return None


def _earthquake_selection_signature(df):
    """Changes if any underlying selected earthquake records change."""
    import hashlib
    fields = ['lat', 'lon', 'time', 'magnitude', 'depth_km', 'id']
    normalized = df.assign(id=df['id'].astype(str))[fields].sort_values(fields, kind='stable')
    content = pd.util.hash_pandas_object(normalized, index=False).to_numpy(dtype='uint64').tobytes()
    return hashlib.sha256(content).hexdigest()[:20]


def render_coordinated(frame):
    st.markdown('#### Coordinated Earthquake Analysis')
    st.caption('Click a daily bar to filter the magnitude–depth plot. A date selector is also provided for reliable keyboard and touch access.')
    d = clean_events(frame)
    if d.empty:
        st.info('No valid dated earthquake observations are available for these charts.')
        return
    daily = d.groupby('utc_day', as_index=False).size().rename(columns={'size': 'events'})
    days = daily['utc_day'].tolist()

    # Prevent a selection from one USGS fetch leaking into another with coincident dates.
    signature = _earthquake_selection_signature(d)
    if st.session_state.get('quake_bonus_dataset_signature') != signature:
        st.session_state['quake_bonus_dataset_signature'] = signature
        st.session_state['quake_selected_day'] = None
        st.session_state['quake_bonus_day_picker'] = 'All days'
        st.session_state['quake_selection_epoch'] = st.session_state.get('quake_selection_epoch', 0) + 1

    current = st.session_state.get('quake_selected_day')
    if current not in days:
        current = None
        st.session_state['quake_selected_day'] = None
    if st.session_state.get('quake_bonus_day_picker') not in ['All days'] + days:
        st.session_state['quake_bonus_day_picker'] = 'All days'

    # A true chart selection is the bonus pathway. The selector is a usability fallback.
    def _pick_day():
        choice = st.session_state['quake_bonus_day_picker']
        st.session_state['quake_selected_day'] = choice if choice in days else None
        st.session_state['quake_selection_epoch'] = st.session_state.get('quake_selection_epoch', 0) + 1

    def _clear_day():
        # Streamlit executes button callbacks before creating the picker widget.
        # Mutating the picker after instantiation would raise an API exception.
        st.session_state['quake_selected_day'] = None
        st.session_state['quake_bonus_day_picker'] = 'All days'
        st.session_state['quake_selection_epoch'] = st.session_state.get('quake_selection_epoch', 0) + 1

    controls_a, controls_b = st.columns([2, 1])
    with controls_a:
        st.selectbox('Select a UTC day (or click a bar)', ['All days'] + days,
                     key='quake_bonus_day_picker', on_change=_pick_day)
    with controls_b:
        st.write('')
        st.button('Clear day selection', key='quake_bonus_clear', width='stretch',
                  on_click=_clear_day,
                  help='Restore all fetched earthquakes and reset the Plotly selection.')

    key_epoch = st.session_state.get('quake_selection_epoch', 0)
    current = st.session_state.get('quake_selected_day')
    bars = go.Figure(go.Bar(
        x=daily.utc_day, y=daily.events,
        marker_color=[TEAL if current is None or day == current else '#34445c' for day in days],
        customdata=np.asarray(days, dtype=object).reshape(-1, 1),
        hovertemplate='%{x}<br>%{y} recorded earthquakes<br>Select to refilter the chart beside it<extra></extra>'))
    bars.update_layout(title='Earthquake counts by UTC day', height=355,
        paper_bgcolor=BG, plot_bgcolor=BG, font={'color':'#e9f1ff'},
        margin=dict(l=12, r=12, t=55, b=42),
        xaxis=dict(title='UTC date', type='category', tickangle=-35, gridcolor='#29364b'),
        yaxis=dict(title='Recorded events', rangemode='tozero', dtick=1, gridcolor='#29364b'),
        clickmode='event+select')
    left, right = st.columns(2)
    with left:
        ev = st.plotly_chart(bars, key=f'quake_bonus_daily_{key_epoch}',
                             on_select='rerun', selection_mode='points', width='stretch',
                             alt='USGS earthquake counts per UTC day. Select a bar to filter the magnitude versus depth chart.')
    chosen = _selected_utc_day(ev, days)
    if chosen is not None and chosen != current:
        current = chosen
        st.session_state['quake_selected_day'] = current
    shown = d[d.utc_day == current] if current in days else d

    scatter = go.Figure(go.Scatter(
        x=shown.depth_km, y=shown.magnitude, mode='markers',
        marker=dict(size=np.clip((shown.magnitude + 1).to_numpy() * 2.7, 6, 18),
                    color=TEAL, line=dict(color='#173346', width=.7), opacity=.82),
        customdata=np.column_stack([shown.time.dt.strftime('%Y-%m-%d %H:%M UTC'),
                                    shown.place.astype(str), shown.id.astype(str)]),
        hovertemplate='M %{y:.1f}<br>Depth %{x:.1f} km<br>%{customdata[0]}<br>%{customdata[1]}<br>ID %{customdata[2]}<extra></extra>'))
    scatter.update_layout(title=f'Magnitude versus depth · {current or "all fetched days"}',
        height=355, paper_bgcolor=BG, plot_bgcolor=BG, font={'color':'#e9f1ff'},
        margin=dict(l=12, r=12, t=55, b=42),
        xaxis=dict(title='Depth (km)', gridcolor='#29364b'),
        yaxis=dict(title='Magnitude', gridcolor='#29364b'))
    with right:
        st.plotly_chart(scatter, width='stretch',
            alt='Magnitude versus measured depth of earthquakes for the selected UTC day, or all days when no day is selected.')
    if current:
        st.success(f'**Linked selection active:** {current} UTC · {len(shown):,} of {len(d):,} events shown in the scatterplot.')
    else:
        st.caption(f'Showing all {len(d):,} fetched earthquakes · All UTC days · Select a bar or use the date dropdown to filter.')
    st.caption('**Coordinated view:** Chart selection changes the magnitude–depth distribution beside it. Daily bars count USGS records, not felt earthquakes or seismic risk. Point size denotes magnitude; x-axis is measured depth (km).')
    omitted = 0 if frame is None else max(0, len(frame) - len(d))
    st.caption(f'**Data quality:** {len(d):,} of {len(frame):,} fetched records have valid coordinates, magnitude, depth and timestamp; {omitted:,} omitted from these charts. Affected records are not falsely assigned to a UTC day.')


def render_dbscan(frame, region_choice='US', truncated=False):
    st.markdown('#### Earthquake Spatial Clustering · DBSCAN')
    st.caption('Optional assignment bonus: groups nearby *recorded epicenters* with haversine distance. Clusters are not fault lines, expected future earthquakes, or risk zones.')
    d = clean_events(frame)
    if len(d) < 2:
        st.info('At least two valid earthquake locations are needed for DBSCAN.')
        return
    left, right = st.columns(2)
    with left: eps = st.slider('DBSCAN radius · eps (km)', 25, 250, 75, 25, key='quake_dbscan_eps')
    with right: min_samples = st.slider('DBSCAN min_samples', 2, 10, 3, 1, key='quake_dbscan_min')
    # HAZARDSCOPE_DBSCAN_COMPARISON_V3: second radius controls both animation and table
    comparison_eps = st.slider('Comparison radius · Run B eps (km)',
        min_value=eps+25, max_value=500, value=max(250, eps+25), step=25, key='quake_dbscan_comparison_eps')
    st.caption('Run A uses the first radius. Run B uses this larger radius on the **same real epicenters**. Identical groupings are a valid result.')
    labels = dbscan_labels(d,eps,min_samples)
    stats = cluster_summary(labels)
    a,b,c,dcol = st.columns(4)
    a.metric('Run A clusters',stats['clusters']); b.metric('Run A clustered',stats['clustered'])
    c.metric('Run A noise (−1)',stats['noise']); dcol.metric('Run A noise share', f"{stats['noise']/stats['total']:.1%}")
    from src.dbscan_motion import render_dbscan_motion
    render_dbscan_motion(d, labels, eps, min_samples, dbscan_labels, COLORS, comparison_eps)
    # HAZARDSCOPE_DBSCAN_PRESENTATION_FINAL_V4 · Duplicate Plotly cluster map removed; one animated map retained.

    other_eps = comparison_eps
    alt = cluster_summary(dbscan_labels(d,other_eps,min_samples))
    st.markdown('**Sensitivity comparison: neighborhood radius**')
    st.dataframe(pd.DataFrame([
        {'eps (km)':eps,'min_samples':min_samples,'clusters':stats['clusters'],'noise points':stats['noise'],'clustered points':stats['clustered']},
        {'eps (km)':other_eps,'min_samples':min_samples,'clusters':alt['clusters'],'noise points':alt['noise'],'clustered points':alt['clustered']},
    ]),hide_index=True,width='stretch')
    st.caption(f'**Method:** scikit-learn DBSCAN, haversine distance on latitude/longitude in radians; eps = {eps} km ({eps/EARTH_RADIUS_KM:.5f} radians); min_samples = {min_samples} includes the core point. The second run uses eps = {other_eps} km with the same min_samples. Cluster labels are arbitrary and are not compared across runs. Points labeled −1 are noise, not data errors. **Projection:** Plotly Albers USA. **Layers:** geographic basemap/administrative boundaries for context and colored epicenter clusters; noise shown as gray crosses. No smoothing or heatmap radius applies.' )
    if region_choice != 'US': st.info('USGS state selection uses a bounding rectangle, so some plotted events may lie outside the exact state boundary.')
    if truncated: st.warning('USGS query reached its event cap. Clustering reflects only the fetched subset, and may change with a complete dataset.')

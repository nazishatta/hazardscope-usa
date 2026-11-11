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


def render_coordinated(frame):
    st.markdown('#### Coordinated Earthquake Analysis')
    st.caption('Select one bar to filter the magnitude–depth plot to that UTC day. Clear the selection to restore all fetched earthquakes.')
    d = clean_events(frame)
    if d.empty:
        st.info('No valid dated earthquake observations are available for these charts.')
        return
    daily = d.groupby('utc_day', as_index=False).size().rename(columns={'size': 'events'})
    days = daily['utc_day'].tolist()
    key_epoch = st.session_state.get('quake_selection_epoch', 0)
    current = st.session_state.get('quake_selected_day')
    if current not in days:
        current = None
        st.session_state['quake_selected_day'] = None
    bars = go.Figure(go.Bar(x=daily.utc_day, y=daily.events,
        marker_color=[TEAL if current is None or day == current else '#34445c' for day in days],
        customdata=np.array(days, dtype=object).reshape(-1, 1),
        hovertemplate='%{x}<br>%{y} recorded earthquakes<br>Click to filter<extra></extra>'))
    bars.update_layout(title='Earthquake counts by UTC day', height=355, paper_bgcolor=BG, plot_bgcolor=BG,
        font={'color':'#e9f1ff'}, margin=dict(l=12,r=12,t=55,b=42),
        xaxis=dict(title='UTC date',type='category',tickangle=-35,gridcolor='#29364b'),
        yaxis=dict(title='Recorded events',rangemode='tozero',dtick=1,gridcolor='#29364b'),
        clickmode='event+select')
    left, right = st.columns(2)
    with left:
        ev = st.plotly_chart(bars, key=f'quake_bonus_daily_{key_epoch}', on_select='rerun', selection_mode='points', width='stretch')
    selected_points = (ev.selection.points if ev is not None and hasattr(ev,'selection') else [])
    if selected_points:
        p = selected_points[0]
        idx = p.get('point_index', p.get('pointNumber'))
        if isinstance(idx, (int, np.integer)) and 0 <= idx < len(days):
            current = days[idx]
            st.session_state['quake_selected_day'] = current
    shown = d[d.utc_day == current] if current is not None else d
    scatter = go.Figure(go.Scatter(
        x=shown.depth_km, y=shown.magnitude, mode='markers',
        marker=dict(size=np.clip((shown.magnitude+1).to_numpy()*2.7, 6, 18),
                    color=TEAL, line=dict(color='#173346',width=.7), opacity=.82),
        customdata=np.column_stack([shown.time.dt.strftime('%Y-%m-%d %H:%M UTC'),
                                    shown.place.astype(str), shown.id.astype(str)]),
        hovertemplate='M %{y:.1f}<br>Depth %{x:.1f} km<br>%{customdata[0]}<br>%{customdata[1]}<br>ID %{customdata[2]}<extra></extra>'
    ))
    scatter.update_layout(title=f'Magnitude versus depth · {current or "all fetched days"}',
        height=355,paper_bgcolor=BG,plot_bgcolor=BG,font={'color':'#e9f1ff'},
        margin=dict(l=12,r=12,t=55,b=42),xaxis=dict(title='Depth (km)',gridcolor='#29364b'),
        yaxis=dict(title='Magnitude',gridcolor='#29364b'))
    with right: st.plotly_chart(scatter, width='stretch')
    row_a, row_b = st.columns([2,1])
    with row_a:
        st.caption(f'Showing {len(shown):,} of {len(d):,} fetched earthquakes' + (f' · UTC day: {current}' if current else ' · All UTC days'))
    with row_b:
        if st.button('Clear day selection', key='quake_bonus_clear', disabled=current is None, width='stretch'):
            st.session_state['quake_selected_day'] = None
            st.session_state['quake_selection_epoch'] = key_epoch + 1
            st.rerun()
    st.caption('Daily bars count reported USGS records, not felt earthquakes or seismic risk. The point size represents magnitude; x-axis is measured event depth in km.')


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
    labels = dbscan_labels(d,eps,min_samples)
    stats = cluster_summary(labels)
    a,b,c,dcol = st.columns(4)
    a.metric('Clusters',stats['clusters']); b.metric('Clustered events',stats['clustered'])
    c.metric('Noise (−1)',stats['noise']); dcol.metric('Noise share', f"{stats['noise']/stats['total']:.1%}")
    fig = go.Figure()
    for label in sorted(set(labels.tolist())):
        mask = labels == label
        subset = d.loc[mask]
        is_noise = label == -1
        fig.add_trace(go.Scattergeo(
            lat=subset.lat,lon=subset.lon,mode='markers',
            name='Noise (−1)' if is_noise else f'Cluster {label+1}',
            text=subset.place.astype(str),
            customdata=np.column_stack([subset.magnitude,subset.depth_km,subset.time.dt.strftime('%Y-%m-%d %H:%M UTC')]),
            hovertemplate='%{text}<br>Magnitude %{customdata[0]:.1f}<br>Depth %{customdata[1]:.1f} km<br>%{customdata[2]}<extra></extra>',
            marker=dict(size=7 if is_noise else 9,symbol='x' if is_noise else 'circle',
                        color='#b5c1d0' if is_noise else COLORS[label%len(COLORS)],opacity=.85,
                        line=dict(color='#071321',width=.5))
        ))
    fig.update_geos(scope='usa',projection_type='albers usa',showland=True,landcolor='#192a3e',
                    showsubunits=True,subunitcolor='#3b4d66',showcoastlines=True,coastlinecolor='#52677b',
                    bgcolor=BG)
    fig.update_layout(title='USGS epicenters · DBSCAN clusters and noise',height=490,
        paper_bgcolor=BG,plot_bgcolor=BG,font=dict(color='#e9f1ff'),
        margin=dict(l=0,r=8,t=44,b=5), legend=dict(orientation='h',y=-.08,x=0))
    st.plotly_chart(fig,width='stretch')
    other_eps = min(500, eps*2)
    alt = cluster_summary(dbscan_labels(d,other_eps,min_samples))
    st.markdown('**Sensitivity comparison: neighborhood radius**')
    st.dataframe(pd.DataFrame([
        {'eps (km)':eps,'min_samples':min_samples,'clusters':stats['clusters'],'noise points':stats['noise'],'clustered points':stats['clustered']},
        {'eps (km)':other_eps,'min_samples':min_samples,'clusters':alt['clusters'],'noise points':alt['noise'],'clustered points':alt['clustered']},
    ]),hide_index=True,width='stretch')
    st.caption(f'**Method:** scikit-learn DBSCAN, haversine distance on latitude/longitude in radians; eps = {eps} km ({eps/EARTH_RADIUS_KM:.5f} radians); min_samples = {min_samples} includes the core point. The second run uses eps = {other_eps} km with the same min_samples. Cluster labels are arbitrary and are not compared across runs. Points labeled −1 are noise, not data errors. **Projection:** Plotly Albers USA. **Layers:** geographic basemap/administrative boundaries for context and colored epicenter clusters; noise shown as gray crosses. No smoothing or heatmap radius applies.' )
    if region_choice != 'US': st.info('USGS state selection uses a bounding rectangle, so some plotted events may lie outside the exact state boundary.')
    if truncated: st.warning('USGS query reached its event cap. Clustering reflects only the fetched subset, and may change with a complete dataset.')

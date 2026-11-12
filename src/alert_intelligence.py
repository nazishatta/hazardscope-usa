"""Official NWS alert visualization: no guessed polygons, positions or timestamps."""
from __future__ import annotations

from datetime import datetime, timezone
import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st


import requests
from urllib.parse import urlparse

ZONE_HEADERS = {'User-Agent': 'HazardScopeUSA/1.0 (educational visualization; contact: hazardscope-usa@users.noreply.github.com)', 'Accept':'application/geo+json'}
ZONE_LIMIT = 16

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_zone_geometry(url):
    """Resolve a single official NWS zone URL only, with bounded network access."""
    p=urlparse(str(url))
    if p.scheme!='https' or p.hostname!='api.weather.gov' or not p.path.startswith('/zones/'):
        raise ValueError('Invalid official NWS zone URL')
    response=requests.get(url,headers=ZONE_HEADERS,timeout=12,allow_redirects=False)
    response.raise_for_status()
    value=response.json()
    if not isinstance(value,dict):return None
    obj=value.get('geometry')
    if obj is None and isinstance(value.get('features'),list) and value['features']:
        obj=value['features'][0].get('geometry')
    if obj and isinstance(obj,dict) and obj.get('type') in ('Polygon','MultiPolygon'):
        if any(True for _ in iter_rings(obj)):return obj
    return None

def zone_urls_for_alert(row, limit=ZONE_LIMIT):
    urls=row.get('affected_zones', [])
    if not isinstance(urls,(list,tuple)):return []
    valid=[]
    for url in urls:
        parsed=urlparse(str(url))
        if parsed.scheme=='https' and parsed.hostname=='api.weather.gov' and parsed.path.startswith('/zones/'):
            if url not in valid:valid.append(url)
        if len(valid)>=limit:break
    return valid

def read_zone_geometry(row, limit=ZONE_LIMIT):
    """Explicit action only; returns all geometries, failures and truncated-zone count."""
    raw=row.get('affected_zones', [])
    urls=zone_urls_for_alert(row, limit)
    geoms=[]; errors=0
    for url in urls:
        try:
            g=fetch_zone_geometry(url)
            if g is not None:geoms.append(g)
            else:errors+=1
        except (requests.RequestException,ValueError,TypeError):errors+=1
    return geoms, len(urls), errors, max(0,len(raw)-len(urls)) if isinstance(raw,(list,tuple)) else 0

def readable_remaining(end,now):
    if pd.isna(end):return 'Unknown'
    delta=(end-now).total_seconds()
    if delta<=0:return 'Past expiry · refresh NWS'
    secs=int(delta)
    days,rem=divmod(secs,86400)
    hours,rem=divmod(rem,3600)
    minutes,seconds=divmod(rem,60)
    return (f'{days}d ' if days else '')+f'{hours:02d}:{minutes:02d}:{seconds:02d}'

BACKGROUND = '#080c15'
COLORS = {'Extreme':'#ff4b65','Severe':'#fb9752','Moderate':'#eac66c',
          'Minor':'#45d8bc','Unknown':'#8e9fbc'}
URGENCY_ORDER = ['Immediate','Expected','Future','Past','Unknown']
SEVERITY_ORDER = ['Extreme','Severe','Moderate','Minor','Unknown']


def iter_rings(geometry):
    """Return coordinate rings from validated NWS Polygon/MultiPolygon GeoJSON."""
    if not isinstance(geometry, dict):
        return
    kind, coords = geometry.get('type'), geometry.get('coordinates')
    if kind == 'Polygon':
        polys = [coords]
    elif kind == 'MultiPolygon':
        polys = coords
    else:
        return
    if not isinstance(polys, list):
        return
    for polygon in polys:
        if not isinstance(polygon, list):
            continue
        # Render exterior ring only: holes are not filled precisely by Scattergeo.
        exterior = polygon[0] if polygon else None
        if not isinstance(exterior, list) or len(exterior) < 4:
            continue
        result = []
        for pair in exterior:
            if not isinstance(pair,(list,tuple)) or len(pair) < 2:
                result = []
                break
            try:
                lon, lat = float(pair[0]), float(pair[1])
                if not all(map(math.isfinite,[lon,lat])) or not (-180<=lon<=180 and -90<=lat<=90):
                    result = []
                    break
                result.append((lon,lat))
            except (TypeError,ValueError):
                result = []
                break
        if len(result) >= 4:
            yield result


def clean_alerts(frame):
    df = frame.copy()
    required = ('id','event','headline','severity','urgency','area','effective','expires','description','instruction','url')
    for col in required:
        if col not in df.columns:
            df[col] = ''
    if 'geometry' not in df.columns:
        df['geometry'] = None
    if 'affected_zones' not in df.columns:
        df['affected_zones'] = [[] for _ in range(len(df))]
    if 'onset' not in df.columns:
        df['onset'] = ''
    if 'ends' not in df.columns:
        df['ends'] = ''
    for col in ('id','event','headline','severity','urgency','area','description','instruction','url'):
        df[col] = df[col].fillna('').astype(str)
    df['severity'] = df['severity'].where(df['severity'].isin(SEVERITY_ORDER),'Unknown')
    df['urgency'] = df['urgency'].where(df['urgency'].isin(URGENCY_ORDER),'Unknown')
    df['start_dt'] = pd.to_datetime(df['onset'].where(df['onset'].astype(str).str.len()>0,df['effective']),utc=True,errors='coerce')
    df['end_dt'] = pd.to_datetime(df['ends'].where(df['ends'].astype(str).str.len()>0,df['expires']),utc=True,errors='coerce')
    df['has_polygon'] = df['geometry'].map(lambda obj: any(True for _ in iter_rings(obj)))
    return df


def focused_bounds(geometries):
    """Padded viewport around official geometry; never infer a location from names."""
    points = [point for geometry in geometries for ring in iter_rings(geometry) for point in ring]
    if not points:
        return None
    lons = [lon for lon, _ in points]
    lats = [lat for _, lat in points]
    west, east = min(lons), max(lons)
    south, north = min(lats), max(lats)
    # Antimeridian-crossing geometries need a different projection strategy.
    # Fall back to overview rather than showing a misleading opposite-side viewport.
    if east - west > 160:
        return None
    lon_pad = max(0.55, (east - west) * 0.30)
    lat_pad = max(0.40, (north - south) * 0.30)
    return (max(-179.9, west - lon_pad), min(179.9, east + lon_pad),
            max(-85, south - lat_pad), min(85, north + lat_pad))


def map_figure(df, selected_id, region_choice, zone_geometry=None, focus_selected=True):
    """Draw official alert polygons/zones only; optionally zoom to selected geometry."""
    selected_rows = df[df['id'] == selected_id]
    selected_geometry = []
    for _, row in selected_rows.iterrows():
        if isinstance(row.get('geometry'), dict):
            selected_geometry.append(row['geometry'])
    selected_geometry += list(zone_geometry or [])
    viewport = focused_bounds(selected_geometry) if focus_selected else None
    local = focus_selected and viewport is not None
    fig = go.Figure()
    map_count = 0
    selected_count = 0
    # In focused mode omit unrelated alert boundaries from the viewport.
    rows = selected_rows if local else df
    for _, row in rows.iterrows():
        highlight = row['id'] == selected_id
        sev = row['severity']
        for ring in iter_rings(row['geometry']):
            stride = max(1, math.ceil(len(ring)/2200))
            pts = ring[::stride]
            if pts[-1] != ring[-1]: pts.append(ring[-1])
            if pts[0] != pts[-1]: pts.append(pts[0])
            fig.add_trace(go.Scattergeo(
                lon=[p[0] for p in pts], lat=[p[1] for p in pts], mode='lines',
                fill='toself', fillcolor=COLORS[sev], opacity=.48 if highlight else .23,
                line={'color':'#fff4c6' if highlight else COLORS[sev], 'width':3.6 if highlight else 1.25},
                text=[row['headline'][:130]] * len(pts),
                hovertemplate='%{text}<extra></extra>', showlegend=False,
            ))
            map_count += 1
            if highlight: selected_count += 1
    # Official zones are administrative coverage, not detailed hazard footprints.
    for geom in zone_geometry or []:
        for ring in iter_rings(geom):
            stride = max(1, math.ceil(len(ring)/2200))
            pts = ring[::stride]
            if pts[-1] != ring[-1]: pts.append(ring[-1])
            if pts[0] != pts[-1]: pts.append(pts[0])
            fig.add_trace(go.Scattergeo(
                lon=[p[0] for p in pts], lat=[p[1] for p in pts], mode='lines',
                fill='toself', fillcolor='rgba(69,216,188,0.20)', opacity=.90,
                line={'color':'#ffe293', 'width':4, 'dash':'dash'},
                hovertemplate='Official NWS affected zone (not a precise hazard footprint)<extra></extra>',
                showlegend=False))
            map_count += 1
    geo_options = dict(
        scope='usa' if not local else None,
        projection_type='albers usa' if not local else 'mercator',
        showland=True, landcolor='#1a2a3d', showcoastlines=True,
        coastlinecolor='#40516b', showsubunits=True, subunitcolor='#34445e',
        showcountries=True, countrycolor='#46546c', showlakes=False,
        bgcolor=BACKGROUND, fitbounds=False if local else None,
    )
    if local:
        west, east, south, north = viewport
        geo_options.update(lonaxis_range=[west,east], lataxis_range=[south,north],
                           center={'lon':(west+east)/2,'lat':(south+north)/2})
    fig.update_geos(**geo_options)
    fig.update_layout(height=545 if local else 500,
        margin=dict(l=0,r=0,t=30,b=0), paper_bgcolor=BACKGROUND,
        font_color='#eaf0fa', geo_bgcolor=BACKGROUND,
        annotations=[dict(x=0,y=1.04,xref='paper',yref='paper',showarrow=False,
            text='Selected NWS warning · official polygon or affected zone' if local
                 else 'United States overview · official NWS warning areas',
            font=dict(size=12,color='#a6b7ce'))])
    return fig, map_count, selected_count


def timeline_figure(df):
    data = df[df['start_dt'].notna() & df['end_dt'].notna()].copy()
    data = data[data.end_dt >= data.start_dt].copy()
    if data.empty:
        return None,0
    data = data.sort_values('end_dt').head(60)
    data['label'] = data['event'].str.slice(0,28) + ' · ' + data['area'].str.slice(0,23)
    # Plotly Express timeline uses real UTC intervals, not animations or synthetic forecast steps.
    fig=px.timeline(data,x_start='start_dt',x_end='end_dt',y='label',color='severity',
                    color_discrete_map=COLORS,custom_data=['headline','area','urgency'],
                    category_orders={'severity':SEVERITY_ORDER})
    fig.update_yaxes(autorange='reversed',title=None,tickfont={'size':10})
    fig.update_traces(hovertemplate='%{customdata[0]}<br>Area: %{customdata[1]}<br>Urgency: %{customdata[2]}<extra></extra>')
    fig.add_vline(x=datetime.now(timezone.utc).timestamp()*1000,line_color='#ffffff',line_dash='dash',opacity=.75)
    fig.update_layout(height=max(300,min(780,125+len(data)*19)),margin=dict(l=15,r=8,t=16,b=25),
                      paper_bgcolor=BACKGROUND,plot_bgcolor='#111c2b',font_color='#eaf0fa',
                      legend_title_text='Severity',xaxis_title='UTC · effective/onset to end/expiry')
    return fig,len(data)


@st.fragment(run_every='15s')
def live_timeline_fragment(df):
    # This fragment only redraws the clock and chart; it never calls NWS.
    now=pd.Timestamp.now(tz='UTC')
    st.caption(f'LIVE UTC: {now.strftime("%Y-%m-%d %H:%M:%S")} · refreshed every 15 seconds while this page remains open')
    tfig,count=timeline_figure(df)
    if tfig is None:
        st.info('No valid effective/expiration intervals were supplied for this selection.')
        return
    st.plotly_chart(tfig,width='stretch',key='haz_nws_live_timeline')
    valid=df[df['end_dt'].notna()].copy()
    not_expired=valid[valid.end_dt>now]
    if not not_expired.empty:
        soonest=not_expired.sort_values('end_dt').iloc[0]
        st.metric('Live countdown · next reported expiration', readable_remaining(soonest['end_dt'],now))
        st.caption(f'Next scheduled expiry: {soonest["event"]} · countdown recalculates every 15 seconds while this tab remains open.')
    else:
        st.caption('No future expiration among the currently fetched records. Refresh official NWS data to update alert status.')
    st.caption(f'{count} valid intervals (up to 60). Moving dashed line: current UTC. Bars: fixed NWS alert validity periods, not predicted weather movement. Countdown does not refetch records.')


def matrix_figure(df):
    matrix=pd.crosstab(df['severity'],df['urgency']).reindex(index=SEVERITY_ORDER,columns=URGENCY_ORDER,fill_value=0)
    fig=go.Figure(go.Heatmap(z=matrix.values,x=URGENCY_ORDER,y=SEVERITY_ORDER,
        colorscale=[[0,'#14243b'],[.25,'#176c81'],[.6,'#27b7ac'],[1,'#ffd080']],
        showscale=True,colorbar={'title':'Alerts','len':.84},
        text=matrix.values,texttemplate='%{text}',hovertemplate='Severity: %{y}<br>Urgency: %{x}<br>Records: %{z}<extra></extra>'))
    fig.update_layout(height=330,margin=dict(l=10,r=5,t=10,b=20),paper_bgcolor=BACKGROUND,
                      plot_bgcolor=BACKGROUND,font_color='#eaf0fa',xaxis_title='Urgency',yaxis_title='Severity')
    return fig


def render_alerts(alerts, metadata, region_choice):
    st.subheader('Active Weather & Tsunami Intelligence')
    st.write('Explore **official NWS active warning records** by location, expiry, severity and urgency. Geographic shapes appear only when NWS supplies a usable polygon. This is not a forecast of future alerts.')
    if alerts is None:
        st.info('Select your region and click **Fetch active NWS warnings** in the sidebar. No request has been made for this region.')
        return
    data=clean_alerts(alerts)
    fetched=(metadata or {}).get('fetched_utc','unknown')
    st.caption(f'NWS active alerts · region: {region_choice} · fetched: {fetched} · snapshots change only when fetched or auto-refreshed')
    if data.empty:
        st.info('The current NWS request returned no active alerts for this selection. This is not a guarantee of safety.')
        return
    categories=['All']+sorted(data['event'].unique())
    a,b,c=st.columns([1.7,1,1])
    with a: category=st.selectbox('Alert type',categories,key='haz_nws_type')
    with b: sev=st.selectbox('Severity', ['All']+SEVERITY_ORDER,key='haz_nws_severity')
    with c: urgency=st.selectbox('Urgency',['All']+URGENCY_ORDER,key='haz_nws_urgency')
    filtered=data.copy()
    if category!='All':filtered=filtered[filtered.event==category]
    if sev!='All':filtered=filtered[filtered.severity==sev]
    if urgency!='All':filtered=filtered[filtered.urgency==urgency]
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Matching NWS alerts',len(filtered))
    c2.metric('Official polygon records',int(filtered.has_polygon.sum()))
    c3.metric('Without polygon',int((~filtered.has_polygon).sum()))
    c4.metric('Tsunami bulletins',int(filtered.event.str.contains('Tsunami',case=False,na=False).sum()))
    if filtered.empty:
        st.info('No alerts match these filters. Adjust type, severity or urgency to explore the fetched records.')
        return
    indices=list(range(len(filtered)))
    view=filtered.reset_index(drop=True)
    picked=st.selectbox('Inspect / highlight an official alert',indices,
            format_func=lambda i: f"{view.iloc[i]['event']} · {view.iloc[i]['severity']} · {view.iloc[i]['area'][:65]}",
            key='haz_nws_selected')
    selected=view.iloc[picked]
    st.markdown('#### Official warning geography')
    zone_key=str(selected['id'])
    zone_count=len(zone_urls_for_alert(selected))
    active_geo=st.session_state.get('haz_nws_zone_data')
    resolved=[]
    if isinstance(active_geo,dict) and active_geo.get('key')==zone_key:
        resolved=active_geo.get('geometry',[])
    if zone_count and not selected['has_polygon']:
        st.caption(f'This alert references {len(selected["affected_zones"])} official NWS affected zones. Download their boundaries on demand; zone geography is an administrative coverage area, not a precise hazard footprint.')
        if st.button(f'Load official NWS affected zones ({zone_count} max)',key='haz_nws_load_zones'):
            with st.spinner('Retrieving official NWS zone boundaries…'):
                geoms,attempted,failures,omitted=read_zone_geometry(selected)
            st.session_state['haz_nws_zone_data']={'key':zone_key,'geometry':geoms}
            resolved=geoms
            if failures or omitted:
                st.warning(f'Loaded {len(geoms)}/{attempted} attempted zone boundaries; {failures} unavailable and {omitted} omitted by the per-alert limit. Coverage may be incomplete.')
    mode = st.radio('Warning map view', ['Focus on selected warning', 'United States overview'],
                    horizontal=True, key='haz_nws_map_view')
    focus = mode == 'Focus on selected warning'
    fig,segments,_=map_figure(view,selected['id'],region_choice,resolved,focus_selected=focus)
    selected_shapes = ([selected['geometry']] if isinstance(selected.get('geometry'),dict) else []) + list(resolved)
    view_bounds = focused_bounds(selected_shapes)
    if segments:
        if focus and view_bounds is None:
            st.info('Selected warning has no focusable geographic polygon yet. Showing an overview; choose Load official NWS affected zones if available.')
        st.plotly_chart(fig,width='stretch',key='haz_nws_map')
        st.caption('Layers: supplied NWS alert boundaries shaded by official severity; selected affected-zone boundaries dashed in yellow. Focus view: padded Mercator extent based exclusively on official selected geometry. Overview: Albers USA. These are alert/zone coverage areas, not moving storms or precise hazard footprints. No guessed coordinates; polygon holes are not displayed.')
        # HAZARDSCOPE_ASSIGNMENT_CAPTIONS_V1: map classification and exclusions
        st.caption('**Map classification:** nominal NWS severity categories (categorical colors, not quantile classes); the number of visible severity categories depends on the fetched alerts. No heatmap smoothing radius or DBSCAN eps/min_samples apply. Alert and zone polygons are official geometry only; records without valid polygons remain in non-map views and are counted below. The map cannot infer omitted hazard footprints or physical impact boundaries.')
    else:
        st.info('No official polygon geometry is available for this selection. If affected-zone links are provided, select an alert and load its official NWS zones above; no area names are geocoded.')
    st.caption(f'{int(view.has_polygon.sum())} of {len(view)} selected warning records have official geographic polygons. Alerts without polygons remain visible in the timeline, matrix and details.')
    left,right=st.columns(2)
    with left:
        st.markdown('#### Effective → Expiration Timeline')
        live_timeline_fragment(view)
    with right:
        st.markdown('#### Severity × Urgency')
        st.plotly_chart(matrix_figure(view),width='stretch',key='haz_nws_matrix')
        st.caption('Counts of currently fetched NWS alert records by official severity and urgency categories. Use the filters above to coordinate every view.')
    st.markdown('#### Selected Official Warning')
    st.markdown(f"**{selected['headline'] or selected['event']}**")
    cols=st.columns(3)
    cols[0].metric('Severity',selected['severity'])
    cols[1].metric('Urgency',selected['urgency'])
    cols[2].metric('Official geometry','Alert polygon' if selected['has_polygon'] else ('Affected zones available' if zone_count else 'Not supplied'))
    st.write(f"**Affected area:** {selected['area'] or 'Not specified'}")
    st.caption(f"Effective: {selected['effective'] or 'not supplied'} · Expires: {selected['expires'] or 'not supplied'}")
    with st.expander('Official description and safety instructions',expanded=True):
        st.write(selected['description'][:6000] or 'No description supplied.')
        if selected['instruction']:
            st.warning(selected['instruction'][:3500])
    if selected['url'].startswith('https://'):
        st.link_button('Open official NWS bulletin',selected['url'])
    with st.expander('Inspect fetched NWS records'):
        st.dataframe(view[['event','severity','urgency','area','headline','effective','expires','has_polygon']],width='stretch',hide_index=True)
    st.caption('Alert records are not counts of storms or disasters. A missing alert or missing geometry is not a safety guarantee. Follow NWS and tsunami.gov for emergency decisions.')
    st.markdown('#### Tsunami-specific resources')
    tsunami=data[data.event.str.contains('Tsunami',case=False,na=False)]
    if tsunami.empty:
        st.info('No tsunami-related alert appears in this fetched NWS response. This is not a guarantee of no tsunami hazard.')
    else:
        st.dataframe(tsunami[['event','severity','urgency','area','headline','expires']],hide_index=True,width='stretch')
    st.link_button('NOAA historical tsunami database','https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis')
    st.link_button('Official tsunami warning center','https://www.tsunami.gov/')

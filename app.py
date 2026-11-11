"""HazardScope USA — live API-driven U.S. natural hazards visualization dashboard."""
from src.wind_canvas import wind_canvas_html
from src.wind_surface import smoothed_wind_map
import streamlit.components.v1 as components
from datetime import datetime, timezone
import time
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from src.geo import STATES, STATE_CODES, state_name, center_for, bounds_for
from src.providers import (DataSourceError, usgs_earthquakes, nws_alerts, fema_declarations,
                           weather_point, wind_grid)
from src.visuals import (earthquake_map,density_fig,timeline_fig,depth_fig,wind_flow_figure,wind_speed_map,wind_field_surface,BG)
from src.seismic_animation import seismic_animation_html
from src.seismic_geography import render_section as render_seismic_geography
import streamlit.components.v1 as seismic_components
from src.alert_intelligence import render_alerts as render_nws_intelligence

st.set_page_config(page_title='HazardScope USA · Natural Hazard Intelligence',page_icon='🌪️',layout='wide',initial_sidebar_state='expanded')
st.markdown('''<style>
.stApp{background:#080c15;color:#eaf0fa}
[data-testid="stSidebar"]{background:#101828;border-right:1px solid #263248}
[data-testid="stMetric"]{background:#152034;border:1px solid #2a3c59;border-radius:15px;padding:16px 18px}
[data-testid="stMetricLabel"]{color:#aabbd2}
.stButton>button[kind="primary"]{background:#17c9a0;color:#06141b;border-radius:9px;font-weight:700;border:0}
h1,h2,h3{letter-spacing:-.03em}
div[data-testid="stAlert"]{border-radius:12px}
</style>''',unsafe_allow_html=True)

@st.cache_data(ttl=180,show_spinner=False)
def cache_quakes(days,mag,depth,bounds):return usgs_earthquakes(days,mag,depth,bounds=bounds)
@st.cache_data(ttl=180,show_spinner=False)
def cache_alerts(state):return nws_alerts(state)
@st.cache_data(ttl=900,show_spinner=False)
def cache_fema(state,year):return fema_declarations(state,year)
@st.cache_data(ttl=300,show_spinner=False)
def cache_weather(lat,lon,days):return weather_point(lat,lon,days)
@st.cache_data(ttl=900,show_spinner=False)
def cache_wind(bounds,rows,cols):return wind_grid(bounds,rows,cols)

for k in ('quakes','alerts','fema','weather','wind'):
    st.session_state.setdefault('data_'+k,None)
    st.session_state.setdefault('meta_'+k,None)
    st.session_state.setdefault('key_'+k,None)

st.sidebar.markdown('## ◈ HazardScope USA')
st.sidebar.caption('LIVE SOURCES · INTERACTIVE RESEARCH')
region_choice=st.sidebar.selectbox('State / region',['US']+STATE_CODES,
    format_func=lambda c: '🇺🇸 United States · broad region' if c=='US' else f'{state_name(c)} ({c})')
center=center_for(region_choice)
st.sidebar.caption(f'Map center: {center[0]:.2f}°, {center[1]:.2f}° · USGS uses a geographic bounding box, not an exact state border.')
st.sidebar.divider()
st.sidebar.markdown('**Seismic query controls**')
days=st.sidebar.select_slider('Time window (days)',options=[1,3,7,14,30],value=7)
mag=st.sidebar.slider('Minimum magnitude',0.0,7.0,2.5,.5)
depth=st.sidebar.slider('Maximum depth (km)',25,700,700,25)
st.sidebar.markdown('**Visualization controls**')
marker_scale=st.sidebar.slider('Epicenter marker size',.5,2.0,1.0,.1)
heat_blur=st.sidebar.slider('Hazard density smoothing',.8,5.0,2.2,.2)
show_map_density=st.sidebar.toggle('Overlay density glow on epicenters',value=True)
st.sidebar.divider()
st.sidebar.markdown('**Live refresh controls**')
auto_live = st.sidebar.toggle('Auto-refresh live data', value=False, help='Poll USGS, NWS, and point weather while this browser session remains connected. No background service is installed.')
refresh_minutes = st.sidebar.select_slider('Refresh interval (minutes)', options=[3, 5, 10, 15], value=5, disabled=not auto_live)
st.sidebar.caption('Manual Fetch remains available. Animated wind paths illustrate a sampled field; wind-grid sampling is manual to avoid excessive API requests.')
st.sidebar.markdown('**Data acquisition**')
fetch_quakes=st.sidebar.button('↻ Fetch USGS earthquakes',width='stretch',type='primary')
fetch_alerts=st.sidebar.button('↻ Fetch active NWS warnings',width='stretch')
selected_center=center_for(region_choice)
forecast_days=st.sidebar.slider('Point forecast duration (days)',1,7,3)
fetch_weather=st.sidebar.button('↻ Fetch wind, pressure & weather',width='stretch')
fema_year=st.sidebar.slider('FEMA declarations since year',2015,2026,2023)
fetch_fema=st.sidebar.button('↻ Fetch FEMA history',width='stretch')
st.sidebar.caption('API calls occur only on Fetch. Results are cached. No synthetic hazard records are shown.')

bounds=bounds_for(region_choice)
quake_key=(days,mag,depth,tuple(bounds))
alert_key=region_choice
weather_key=(round(selected_center[0],3),round(selected_center[1],3),forecast_days)
fema_key=(region_choice,fema_year)

def do_fetch(source,key,callback):
    with st.spinner('Fetching and validating '+source+'…'):
        try:
            data,meta=callback()
        except (DataSourceError,ValueError,KeyError) as exc:
            st.error(f'{source}: {exc}. Earlier successful data, if any, remain available.')
            return
    st.session_state['data_'+source]=data
    st.session_state['meta_'+source]=meta
    st.session_state['key_'+source]=key
    st.toast(f'{source.upper()} request complete',icon='✅')

if fetch_quakes:do_fetch('quakes',quake_key,lambda:cache_quakes(days,mag,depth,tuple(bounds)))
if fetch_alerts:do_fetch('alerts',alert_key,lambda:cache_alerts(region_choice))
if fetch_fema:do_fetch('fema',fema_key,lambda:cache_fema(region_choice,fema_year))
if fetch_weather:
    def weather_call():
        cur,hour,meta=cache_weather(*weather_key)
        return (cur,hour),meta
    do_fetch('weather',weather_key,weather_call)

# Streamlit fragment heartbeats are active only while this session is open.
# A full-app rerun is needed so the charts and headline metrics see refreshed data.
@st.fragment(run_every='30s')
def live_refresh_heartbeat():
    if not auto_live:
        return
    now = time.monotonic()
    last = st.session_state.get('auto_refresh_monotonic')
    previous_keys = st.session_state.get('auto_refresh_keys')
    keys = (quake_key, alert_key, weather_key)
    needs_refresh = (
        last is None or previous_keys != keys
        or now - last >= refresh_minutes * 60
    )
    if needs_refresh:
        # Store timestamp before network calls to prevent a loop on rerun.
        st.session_state['auto_refresh_monotonic'] = now
        st.session_state['auto_refresh_keys'] = keys
        # Clear source caches when polling to obtain a genuine new response.
        cache_quakes.clear()
        cache_alerts.clear()
        cache_weather.clear()
        do_fetch('quakes', quake_key, lambda: cache_quakes(days, mag, depth, tuple(bounds)))
        do_fetch('alerts', alert_key, lambda: cache_alerts(region_choice))
        def refreshed_weather():
            current, hourly, metadata = cache_weather(*weather_key)
            return (current, hourly), metadata
        do_fetch('weather', weather_key, refreshed_weather)
        st.session_state['auto_refresh_utc'] = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        st.rerun(scope='app')
    else:
        remaining = max(0, int(refresh_minutes * 60 - (now - last)))
        st.caption(f'Auto-refresh active · last cycle: {st.session_state.get("auto_refresh_utc", "pending")} · next check in ~{remaining}s')

with st.sidebar:
    live_refresh_heartbeat()

quakes=st.session_state['data_quakes']; alerts=st.session_state['data_alerts']; fema=st.session_state['data_fema']
# HAZARDSCOPE_QUAKES_STALE_GUARD_V1
# Keep cached USGS records for reproducibility, but never present them for changed filters.
# The requested region is encoded into quake_key by bounds_for(region_choice).
quake_fetch_is_stale = (
    st.session_state.get('data_quakes') is not None
    and st.session_state.get('key_quakes') != quake_key
)
if quake_fetch_is_stale:
    quakes = None  # Hide stale hero, counts, maps, timeline, depth chart and joins.

weather=st.session_state['data_weather']; wind=st.session_state['data_wind']

st.markdown('<span style="color:#34e3c0;letter-spacing:.18em;font-size:12px;font-weight:700">EARTH SYSTEMS / DATA INTELLIGENCE / USA</span>',unsafe_allow_html=True)
st.title('HazardScope USA')
st.markdown('**An interactive natural-hazard research observatory.** Explore recorded earthquakes, active weather and tsunami alerts, historical federal disaster declarations, and model-based wind and atmospheric pressure. Each source has its own definition, coverage and refresh cadence.')
st.caption('Live sources update on Fetch or when optional auto-refresh is enabled. Wind animation shows a sampled wind field, not continuous satellite or sensor streaming. For emergencies, follow official agency warnings.')

q_count=len(quakes) if quakes is not None else None
a_count=len(alerts) if alerts is not None else None
f_count=(fema['disaster_id'].nunique() if fema is not None else None)
w_speed=(weather[0].get('wind_speed_10m') if weather else None)
c1,c2,c3,c4=st.columns(4)
c1.metric('Recorded earthquakes',f'{q_count:,}' if q_count is not None else '—')
c2.metric('Active NWS alerts',f'{a_count:,}' if a_count is not None else '—')
c3.metric('Distinct FEMA disasters',f'{f_count:,}' if f_count is not None else '—')
c4.metric('Wind at selected center',f'{w_speed} km/h' if w_speed is not None else '—')

for src,key in [('quakes',quake_key),('alerts',alert_key),('fema',fema_key),('weather',weather_key)]:
    if st.session_state['data_'+src] is not None and st.session_state['key_'+src]!=key:
        st.warning(f'{src.upper()}: controls have changed since the last fetch. The saved result belongs to the earlier query; fetch again to update it.',icon='⚠️')

t1,t2,t3,t4,t5,t6=st.tabs(['01 · Disaster history','02 · Wind streamlines','03 · Earthquakes','04 · Active alerts & tsunami','05 · Cross-source research','06 · Methods & sources'])

with t3:
    st.subheader('Where are earthquakes concentrated?')
    if quake_fetch_is_stale:
        st.warning(
            f'**New region or filters selected:** {state_name(region_choice) if region_choice != "US" else "United States"}. '
            'The previously fetched earthquakes have been hidden to prevent incorrect counts. '
            'Click **Fetch Recent Earthquakes · USGS** below (or the sidebar Fetch button) '
            'to load observations for these settings.', icon='⚠️'
        )

    st.write('Explore where recorded earthquakes occur and how concentrations change over time. Use the sidebar to choose your region, time window, magnitude and depth.')
    if quakes is None:
        st.markdown('#### Explore Recent Earthquake Activity')
        st.write('Load real USGS earthquake records for the selected region, time window, magnitude, and depth. Your filters on the left determine which events are shown.')
        if st.button('🌎 Fetch Recent Earthquakes · USGS', type='primary', width='stretch', key='fetch_earthquakes_main'):
            do_fetch('quakes', quake_key, lambda: cache_quakes(days, mag, depth, tuple(bounds)))
            if st.session_state.get('data_quakes') is not None and st.session_state.get('key_quakes') == quake_key:
                st.rerun()
    else:
        if quakes.empty:st.info('The fetched USGS query returned zero valid earthquake records. Lower the minimum magnitude or widen the date range.')
        # HAZARDSCOPE_SEISMIC_HERO_V1 — Earthquake tab only. Wind code is byte-for-byte preserved.
        st.markdown('#### Earthquake Activity & Hotspots')
        st.markdown('Watch how **recorded earthquakes accumulate over time**. Brighter hotspots indicate a greater concentration of events in the selected data. Press **Play time** to watch the timeline, **Play magnitude** to filter out smaller events, or switch between **event-count** and **magnitude-weighted** density.')
        quake_metadata = st.session_state.get('meta_quakes') or {}
        quake_fetch_time = str(quake_metadata.get('fetched_utc') or 'Not recorded')
        quake_fetched_key = st.session_state.get('key_quakes')
        a,b,c = st.columns(3)
        a.metric('Fetched events', f'{len(quakes):,}')
        b.metric('Fetched min. magnitude', f'M {quake_fetched_key[1]:.1f}+' if quake_fetched_key else '—')
        c.metric('Fetched period', f'{quake_fetched_key[0]} days' if quake_fetched_key else '—')
        st.caption(f'**Source:** USGS Earthquake Catalog · Fetched: {quake_fetch_time} · Uses stored API results; animation makes no new requests.')
        seismic_components.html(seismic_animation_html(quakes, region_choice, bounds), height=900, scrolling=False)
        with st.expander('How to interpret this animation'):
            st.markdown('''**Play time:** Events accumulate in recorded chronological order. The date slider lets you scrub the same dataset.\n\n**Play magnitude:** Raising the threshold hides smaller recorded events; it does not represent earthquakes growing stronger.\n\n**Event-count density:** Each event contributes equally. **Magnitude-weighted density:** Higher-magnitude events receive more weight using an illustrative transform, not physical seismic energy.\n\n**Smoothing:** Blends nearby epicenters into broader hotspots. Brighter areas mean greater displayed concentration, **not** measured shaking, damage, future probability or risk.\n\nUSGS geographic selection uses a bounding box; records and reporting coverage vary, and the downloaded query may be limited.''')
        # HAZARDSCOPE_ASSIGNMENT_GEOGRAPHY_V2: joined seismic geography (Earthquakes only)
        render_seismic_geography(quakes, region_choice, st.session_state.get('key_quakes'), st.session_state.get('meta_quakes'))
        left,right=st.columns(2)
        with left:st.plotly_chart(timeline_fig(quakes),width='stretch')
        with right:st.plotly_chart(depth_fig(quakes),width='stretch')
        with st.expander('Explore individual earthquake epicenters (magnitude and depth)', expanded=False):
            fig=earthquake_map(quakes,marker_scale,show_map_density,heat_blur)
            st.plotly_chart(fig,width='stretch')
            st.caption(f'**Projection:** Plotly Albers USA. **Layer 1:** proportional-size epicenter symbols (magnitude); **Layer 2 (optional):** smoothed event-count density glow, smoothing setting {heat_blur:.1f}. **Color:** epicenter depth in km, continuous scale; no discrete choropleth classes here. **Exclusions:** approximate USGS query rectangle can contain offshore and cross-border points. This is not measured shaking or hazard risk.')
        # HAZARDSCOPE_STATIC_DENSITY_REMOVED_V2 — animated Canvas density below replaces the static Plotly surface.
        # HAZARDSCOPE_SEISMIC_CANVAS_V1 — Earthquake tab only; wind animation untouched
        if st.session_state['meta_quakes'].get('truncated'):
            st.warning('The event query hit its configured 2,500-event cap; counts and density may be incomplete. Raise magnitude or shorten the time window.')
        with st.expander('Inspect earthquake records'):
            st.dataframe(quakes.sort_values('time',ascending=False),width='stretch',hide_index=True)
            st.download_button('Download fetched USGS events CSV',quakes.to_csv(index=False).encode('utf-8'),'usgs_events.csv','text/csv')

with t2:
    st.subheader('WindFlow · Atmospheric Streamlines')
    st.write('Inspired by wind-flow visualizations: multicolored traces move through a grid of **current model-derived 10-meter winds** fetched from Open-Meteo. Particle movement is an illustrative flow animation of a snapshot — not a satellite recording or a time-evolving prediction.')
    col_a,col_b,col_c=st.columns(3)
    with col_a:quality=st.selectbox('Wind grid resolution',['Balanced · 8 × 13','Detailed · 10 × 16'],index=0)
    with col_b:particle_count=st.slider('Number of flowing paths',50,230,145,15)
    with col_c:st.caption('Higher detail increases network requests and rendering time. National grid covers the contiguous United States only.')
    regional_bounds=bounds_for(region_choice)
    if region_choice=='US':regional_bounds=(25,49,-124,-67)
    rows,cols=(10,16) if quality.startswith('Detailed') else (8,13)
    wind_key=(region_choice,tuple(regional_bounds),rows,cols)
    if st.button('🌬 Fetch live-model wind field and create animation',type='primary'):
        do_fetch('wind',wind_key,lambda:cache_wind(tuple(regional_bounds),rows,cols))
        wind=st.session_state['data_wind']
    if wind is None:
        st.info('Press Fetch above to sample a live weather-model wind field. No pre-generated or fabricated streamlines are displayed.')
    elif st.session_state['key_wind']!=wind_key:
        st.warning('The wind field belongs to previous state/grid settings. Fetch again for the current settings.')
    else:
        # LIGHTWEIGHT_WIND_CANVAS_V1: continuous 2D canvas, no Plotly frame redraw
        components.html(wind_canvas_html(wind, particle_count), height=515, scrolling=False)
        st.info('**What this shows:** Moving colored line segments represent particles advected through a single sampled 10-meter wind-vector field. The movement demonstrates wind direction and relative strength. Playback speed and particle paths are illustrative, not meteorological elapsed time.')
        st.plotly_chart(smoothed_wind_map(wind),width='stretch')
        surface=st.radio('Weather density surface',['Wind speed','Sea-level pressure'],horizontal=True)
        st.plotly_chart(wind_field_surface(wind,'speed' if surface=='Wind speed' else 'pressure'),width='stretch')
        st.caption('Surface values are sampled current weather-model fields on a longitude/latitude grid; the heatmap is not a physical wind gust warning or a direct measure of hazard risk.')
        l,r=st.columns(2)
        l.metric('Mean wind in sampled grid',f'{wind.speed.mean():.1f} km/h')
        r.metric('Mean sea-level pressure (sampled)',f'{wind.pressure.mean():.0f} hPa')
        st.caption(f"{len(wind)} weather grid sample locations · last fetch {st.session_state['meta_wind']['fetched_utc']} · sampled model-grid data can be coarser than the displayed lattice. U.S. territories and Alaska/Hawaii are not shown in the national wind grid; choose those individually.")
        with st.expander('Wind field data & request notes'):
            st.dataframe(wind,hide_index=True,width='stretch')
            st.download_button('Download sampled wind grid',wind.to_csv(index=False).encode(),'wind_grid.csv','text/csv')

with t4:
    # HAZARDSCOPE_NWS_INTELLIGENCE_V1: only Tab 03 modified.
    current_alerts=alerts
    if current_alerts is not None and st.session_state.get('key_alerts') != alert_key:
        st.warning('NWS region changed since the last fetch. Fetch NWS warnings again to display alerts for the selected jurisdiction.')
        current_alerts=None
    # HAZARDSCOPE_NWS_BUTTON_TSUNAMI_T4_V1: no stale NWS data or blue empty-state notice.
    if current_alerts is None:
        st.subheader('Active Weather & Tsunami Intelligence')
        st.write('Explore official NWS alerts, warning areas, severity, urgency and expiry for your selected region.')
        if st.button('📡 Fetch Active Weather Alerts · NWS', key='haz_nws_fetch_main', type='primary', use_container_width=True):
            do_fetch('alerts', alert_key, lambda: cache_alerts(region_choice))
            st.rerun()
    else:
        render_nws_intelligence(current_alerts, st.session_state.get('meta_alerts'), region_choice)

from src.tsunami_history import render_section as render_historical_tsunami

with t1:
    # HAZARDSCOPE_HISTORY_FIVE_BUTTON_AUTOPLAY_V3
    from src.disaster_history_intelligence import render_history_center
    render_history_center(region_choice, tuple(bounds_for(region_choice)) if region_choice != "US" else None, state_name(region_choice) if region_choice != "US" else "United States")

with t5:
    st.subheader('Cross-source research · compare without conflating')
    st.write('These quantities answer different questions: a USGS event is an earthquake, an NWS record is an active alert, and a FEMA number is a historical disaster declaration. Counts are not directly comparable measures of risk.')
    summary=pd.DataFrame([
        {'Source':'USGS','Measure':'Recent earthquake events','Count':q_count,'Time horizon':f'Past {days} days','Status':'Fetched' if quakes is not None else 'Not fetched'},
        {'Source':'NWS','Measure':'Active alert records','Count':a_count,'Time horizon':'Active now','Status':'Fetched' if alerts is not None else 'Not fetched'},
        {'Source':'FEMA','Measure':'Distinct declared disasters','Count':f_count,'Time horizon':f'Since {fema_year}, latest ≤1,000 rows','Status':'Fetched' if fema is not None else 'Not fetched'},
    ])
    st.dataframe(summary,hide_index=True,width='stretch')
    if weather:
        cur,hour=weather
        st.markdown('#### Point weather at approximate regional center')
        x,y,z=st.columns(3)
        x.metric('10 m wind',str(cur.get('wind_speed_10m','—'))+' km/h')
        y.metric('Sea-level pressure',str(cur.get('pressure_msl','—'))+' hPa')
        z.metric('Air temperature',str(cur.get('temperature_2m','—'))+' °C')
        metric=st.selectbox('Weather time-series metric', ['wind_speed_10m','pressure_msl','temperature_2m','wind_gusts_10m','precipitation'])
        f=px.line(hour,x='time',y=metric,markers=False,template='plotly_dark',title='Hourly weather-model forecast at the approximate regional center')
        f.update_traces(line_color='#42e5b7',line_width=3)
        f.update_layout(paper_bgcolor=BG,plot_bgcolor=BG,height=380)
        st.plotly_chart(f,width='stretch')
        st.caption('These are weather model estimates/forecasts for approximate coordinates, not observations from a regional sensor or a state average.')
    else:st.info('Fetch weather from the sidebar to add the weather-and-pressure time series.')
    st.markdown('#### Responsible interpretation')
    st.info('A rise in reported events can reflect a changed reporting process, sampling window or detection threshold. A national comparison requires matched geography, source-specific denominators and consistent historical periods.')

with t6:
    st.subheader('Evidence, source freshness & data quality')
    st.markdown('''| Source | What this application fetches | Important caveat |
|---|---|---|
| USGS ComCat | Earthquakes from live query API | State filter is a bounding rectangle, not a polygon join; 2,500-record cap |
| NWS Alerts | Active official alerts by area | Active alerts are not observed events; coverage varies |
| FEMA OpenFEMA v2 | Most recent 1,000 declaration-area rows since selected year | National sampling may be incomplete; repeat disaster numbers are deduplicated |
| Open-Meteo | Current model estimates & hourly forecasts; multi-point wind grid | Model samples are not continuous live sensor streaming |
| NOAA NCEI | External historical tsunami research reference | Historical dataset is not downloaded by this build |
''')
    for key in ['quakes','alerts','fema','weather','wind']:
        with st.expander(key.upper()+' · request provenance'):
            meta=st.session_state.get('meta_'+key)
            if meta:st.json(meta)
            else:st.write('Not fetched in this session.')
    st.markdown('**Live emergency notices**: [National Weather Service](https://www.weather.gov/) · [Tsunami.gov](https://www.tsunami.gov/) · [USGS earthquakes](https://earthquake.usgs.gov/)')
    st.caption('Built for exploratory geographic visualization and education. Do not use it as an emergency warning or operational decision system.')

st.divider()
st.caption('HAZARDSCOPE USA · USGS / NWS / FEMA / OPEN-METEO · Live requests on demand · Dark analytical mapping · Educational research only')

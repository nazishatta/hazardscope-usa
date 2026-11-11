"""Five-source historical disaster explorer for HazardScope USA.

No sample observations are ever inserted into the live application.
All datasets are loaded only when their category is selected, cached,
with explicit limitations and visible failures.
"""
from __future__ import annotations
import csv
import html
import io
import csv as csv_module
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
import streamlit as st
import streamlit.components.v1 as components

UA = {'User-Agent':'HazardScopeUSA/1.0 academic visualization (official data only)', 'Accept':'application/json, text/plain, */*'}
URLS = {
 'hurricanes':'https://www.nhc.noaa.gov/data/',
 'tsunamis':'https://www.ncei.noaa.gov/products/natural-hazards/tsunamis-earthquakes-volcanoes/tsunamis',
 'wildfires':'https://services3.arcgis.com/T4QMspbfLg3qTGWY/ArcGIS/rest/services/WFIGS_Interagency_Perimeters/FeatureServer/0',
 'floods':'https://waterservices.usgs.gov/nwis/dv/',
 'fema':'https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries',
}
CATALOG = {
 'hurricanes':('Hurricanes & Tropical Storms','NOAA NHC HURDAT2: recorded six-hourly best-track positions, Atlantic + eastern Pacific.','Recorded tracks and reported wind intensity; interpolation between observations is illustrative, not additional measurements.'),
 'tsunamis':('Historical Tsunamis','NOAA/NCEI historical tsunami source events since 1900.','Pulses mark event origins only; they are NOT physical wave propagation, travel time or inundation.'),
 'wildfires':('Wildfire History','NIFC WFIGS historical wildfire perimeter records.','Markers are derived from official perimeter geometries, not ignition locations or animated fire spread. Coverage is incomplete.'),
 'floods':('Floods & River Levels','USGS historical daily-mean streamflow at a small named network of monitoring stations.','High discharge is NOT a verified flood. Flood-stage thresholds are not inferred; sites and units are explicit.'),
 'fema':('FEMA Disaster Declarations','OpenFEMA official disaster declarations, deduplicated by disasterNumber.','Not a physical hazard animation. A chronological progression of declared events; incomplete page retrieval is flagged.'),
}

def _get(url,params=None,timeout=28):
    r=requests.get(url,params=params,headers=UA,timeout=timeout)
    r.raise_for_status()
    return r

def _num(value):
    try:
        x=float(value)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None

def _yyyy(value):
    if value is None:return None
    if isinstance(value,(int,float)) and abs(value)>1e11:
        return datetime.fromtimestamp(value/1000,tz=timezone.utc).year
    m=re.search(r'\b(19\d\d|20\d\d)\b',str(value))
    return int(m.group()) if m else None

def _safe(s):return str(s or '').replace('\x00','')[:140]

# HAZARDSCOPE_HISTORY_REGION_FILTER_V1
# bbox follows src.geo.bounds_for: (south, north, west, east); an approximate rectangle.
def _inside_bbox(lat, lon, bbox):
    if bbox is None:
        return True
    la, lo = _num(lat), _num(lon)
    if la is None or lo is None:
        return False
    south, north, west, east = map(float, bbox)
    if not (south <= la <= north):
        return False
    # Accommodate bounding rectangles that wrap at the international date line.
    return (west <= lo <= east) if west <= east else (lo >= west or lo <= east)


def filter_historical_by_bbox(category, events, bbox):
    """Coordinate matching, never a claim of actual disaster impact in a state."""
    if bbox is None:
        return list(events)
    if category == 'hurricanes':
        # At least one NOAA recorded track fix inside the broad region box.
        return [e for e in events if any(_inside_bbox(p.get('lat'), p.get('lon'), bbox)
                                         for p in e.get('path') or [])]
    if category == 'tsunamis':
        # Only a source-origin comparison; NOT a tsunami impact/runup join.
        return [e for e in events if _inside_bbox(e.get('lat'), e.get('lon'), bbox)]
    if category in ('wildfires', 'floods'):
        return [e for e in events if _inside_bbox(e.get('lat'), e.get('lon'), bbox)]
    return list(events)


def _flood_site_ids(bbox):
    """Discover a small reproducible station subset in the selected bounding box."""
    south, north, west, east = map(float, bbox)
    if west > east:
        # Legacy NWIS site inventory does not accept dateline-wrapping boxes.
        raise ValueError('This region spans the date line; flood-station discovery is not supported for this bounding box.')
    raw = _get('https://waterservices.usgs.gov/nwis/site/', {
        'format': 'rdb', 'bBox': f'{west:.5f},{south:.5f},{east:.5f},{north:.5f}',
        'siteType': 'ST', 'parameterCd': '00060', 'siteStatus': 'active',
        'hasDataTypeCd': 'dv',
    }, timeout=55).text
    content = [line for line in raw.splitlines() if line.strip() and not line.startswith('#')]
    if len(content) < 3:
        return []
    # USGS RDB has field names followed by a data-type specification row.
    reader = csv_module.DictReader([content[0]] + content[2:], delimiter='\t')
    found = []
    for row in reader:
        code = (row.get('site_no') or '').strip()
        if re.fullmatch(r'\d{8,15}', code) and code not in found:
            found.append(code)
    # A stable sample; not every station in the selected geographic region.
    return sorted(found)[:5]


def normalize_hurdat(text, min_year=2000, max_tracks=150):
    storms=[]; cur=None
    for line in text.splitlines():
        fields=[x.strip() for x in line.split(',')]
        if fields and re.fullmatch(r'(AL|EP|CP)\d{6}',fields[0]):
            if cur and len(cur['points'])>2:storms.append(cur)
            yr=int(fields[0][-4:]);cur={'id':fields[0],'name':fields[1] if len(fields)>1 else fields[0],'year':yr,'points':[]}
            continue
        if not cur or cur['year']<min_year or len(fields)<8:continue
        try:
            ymd,t=fields[0],fields[1]
            lat=float(fields[4][:-1])*(-1 if fields[4].endswith('S') else 1)
            lon=float(fields[5][:-1])*(-1 if fields[5].endswith('W') else 1)
            if not (-90<=lat<=90 and -180<=lon<=180):continue
            kt=_num(fields[6]);date=f'{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]} {t[:2]}:{t[2:4]} UTC'
            cur['points'].append({'lat':lat,'lon':lon,'date':date,'value':kt,'unit':'kt','label':_safe(fields[3])})
        except (ValueError,IndexError):continue
    if cur and len(cur['points'])>2:storms.append(cur)
    storms=sorted((s for s in storms if s['year']>=min_year),key=lambda x:(x['year'],x['id']))
    return storms[-max_tracks:]

@st.cache_data(ttl=86400,show_spinner=False)
def load_hurricanes():
    # Find current NOAA file name instead of pinning a filename that changes with revisions.
    index=_get('https://www.nhc.noaa.gov/data/hurdat/',timeout=35).text
    links=re.findall(r'href=[\'\"]([^\'\"]*hurdat2-(?:1851|nepac)[^\'\"]*?\.txt)[\'\"]',index,re.I)
    atl=sorted([s for s in links if 'hurdat2-1851-' in s]);pac=sorted([s for s in links if 'hurdat2-nepac-' in s])
    if not atl or not pac:raise ValueError('The NOAA HURDAT2 archive listing did not contain both Atlantic and Pacific data files.')
    all_storms=[]
    for ref in (atl[-1],pac[-1]):
        url=urljoin('https://www.nhc.noaa.gov/data/hurdat/',ref)
        raw=_get(url,timeout=65).text
        all_storms.extend(normalize_hurdat(raw, min_year=2015, max_tracks=100))
    if not all_storms:raise ValueError('No valid NOAA HURDAT2 tracks found in the requested period.')
    all_storms.sort(key=lambda x:(x['year'],x['id']))
    # One animation item per storm, with its actual sequence of reported fixes.
    events=[]
    for s in all_storms:
        events.append({'year':s['year'],'name':_safe(s['name']),'location':s['id'],'detail':f"{len(s['points'])} recorded six-hourly fixes · NOAA HURDAT2", 'path':s['points'],'lat':s['points'][-1]['lat'],'lon':s['points'][-1]['lon'],'value':max((p['value'] or 0 for p in s['points']),default=0),'unit':'kt'})
    return events,{'coverage':'2015–latest complete HURDAT2 season; last 100 storms per basin','note':'Selected subset of recent storm tracks; not a count of every historical cyclone','source':URLS['hurricanes']}

@st.cache_data(ttl=86400,show_spinner=False)
def load_tsunamis():
    from src import tsunami_history
    records,meta=tsunami_history.fetch_history()
    events=[{'year':x['year'],'name':_safe(x['location']),'location':_safe(x['country']),'lat':x['lat'],'lon':x['lon'], 'value':x.get('runup_m'),'unit':'m runup', 'detail':f"Cause: {x.get('cause') or 'unknown'} · Mw: {x.get('magnitude') if x.get('magnitude') is not None else 'not reported'} · Fatalities: {int(x['total_deaths']) if x.get('total_deaths') is not None else 'not reported'}"} for x in records]
    return events,{'coverage':meta.get('time_coverage','NOAA historical event sources'), 'note':'Source coordinates; runup height only where documented','source':URLS['tsunamis']}

@st.cache_data(ttl=86400, show_spinner=False)
def load_wildfires(region="US", bbox=None):
    """Historical WFIGS public wildfire polygons, displayed at perimeter-derived points.

    This is a capped 2023–2025 subset, not a national wildfire census. Polygon
    vertices are a geographic display aid, not ignition coordinates or spread.
    """
    url = URLS['wildfires'] + '/query'
    params = {
        'where': "attr_IncidentTypeCategory = 'WF' AND attr_FireDiscoveryDateTime >= DATE '2023-01-01 00:00:00' AND attr_FireDiscoveryDateTime < DATE '2026-01-01 00:00:00'",
        'outFields': 'OBJECTID,poly_IncidentName,attr_IncidentName,attr_InitialLatitude,attr_InitialLongitude,attr_FireDiscoveryDateTime,poly_GISAcres,poly_PolygonDateTime',
        'orderByFields': 'attr_FireDiscoveryDateTime ASC',
        'returnGeometry': 'true',
        'outSR': 4326,
        'geometryPrecision': 3,
        'maxAllowableOffset': 0.02,
        'f': 'json',
        'resultRecordCount': 500,
    }
    if region != 'US' and bbox is not None:
        south, north, west, east = map(float, bbox)
        if west > east:
            raise ValueError('The NIFC regional query cannot use a date-line-wrapping bounding box.')
        params.update({
            'geometry': f'{west:.5f},{south:.5f},{east:.5f},{north:.5f}',
            'geometryType': 'esriGeometryEnvelope',
            'spatialRel': 'esriSpatialRelIntersects',
            'inSR': 4326,
        })
    data = _get(url, params, timeout=55).json()
    if data.get('error'):
        raise ValueError('NIFC Full History query failed: ' + _safe(data['error'].get('message')))
    events = []
    missing_geometry = 0
    for item in data.get('features') or []:
        a = item.get('attributes') or {}
        geometry = item.get('geometry') or {}
        rings = geometry.get('rings') or []
        # Choose a representative display point from an actual public perimeter.
        # Do not silently substitute imaginary incident or ignition coordinates.
        ring = max((r for r in rings if r), key=len, default=[])
        pts = [(float(p[0]), float(p[1])) for p in ring if len(p) >= 2
               and _num(p[0]) is not None and _num(p[1]) is not None
               and -180 <= float(p[0]) <= 180 and -90 <= float(p[1]) <= 90]
        if not pts:
            missing_geometry += 1
            continue
        # Representative coordinate from polygon bounds; not a measured fire origin.
        lon = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
        lat = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
        year = _yyyy(a.get('attr_FireDiscoveryDateTime'))
        if year is None:
            continue
        acres = _num(a.get('poly_GISAcres'))
        events.append({
            'year': year,
            'name': _safe(a.get('attr_IncidentName') or a.get('poly_IncidentName') or 'Unnamed wildfire'),
            'location': f"NIFC perimeter OBJECTID {a.get('OBJECTID')}",
            'lat': lat, 'lon': lon,
            'value': acres, 'unit': 'mapped acres',
            'detail': 'Location is a perimeter-derived map marker, NOT ignition origin. Mapped acreage and historic coverage can be incomplete.',
        })
    if not events:
        raise ValueError(f'No dated wildfire perimeters with usable geometry returned for the 2023–2025 sample (missing geometry: {missing_geometry}).')
    events.sort(key=lambda e: (e['year'], e['name']))
    return events, {
        'coverage': f"NIFC 2023–2025 selected historical perimeters; {len(events)} mapped records from a maximum of 500 retrieved; {'regional bounding-box intersection' if region != 'US' else 'national'} sample, not exhaustive",
        'note': f'Perimeter-derived map points, not ignition coordinates or growth history. {missing_geometry} returned features lacked usable geometry. Some fire events lack public perimeters.',
        'source': URLS['wildfires'],
    }


@st.cache_data(ttl=86400,show_spinner=False)
def load_floods(region='US', bbox=None):
    if region != 'US' and bbox is not None:
        ids = _flood_site_ids(bbox)
        if not ids:
            raise ValueError('No eligible active USGS daily-discharge stations were found in the selected approximate region. This is not evidence of no floods.')
        sites = ','.join(ids)
    else:
        sites = '01646500,02169500,09380000,06486000,11447650' 
    data=_get(URLS['floods'],{'format':'json','sites':sites,'startDT':'2024-01-01','endDT':'2024-12-31','parameterCd':'00060','statCd':'00003'},timeout=45).json()
    tracks=[]; events=[]
    for s in data.get('value',{}).get('timeSeries',[]):
        info=s.get('sourceInfo') or {};g=(info.get('geoLocation') or {}).get('geogLocation') or {}
        lat=_num(g.get('latitude'));lon=_num(g.get('longitude'));name=_safe(info.get('siteName'))
        if lat is None or lon is None:continue
        obs=[]
        for val in s.get('values') or []:
            for v in val.get('value') or []:
                q=_num(v.get('value'));dt=str(v.get('dateTime',''))[:10]
                if q is not None and q>=0 and dt:obs.append({'date':dt,'value':q,'lat':lat,'lon':lon,'unit':'cfs'})
        if len(obs)<2:continue
        obs.sort(key=lambda x:x['date']);event={'year':2024,'name':name,'location':_safe((info.get('siteCode') or [{}])[0].get('value')),'lat':lat,'lon':lon,'value':max(x['value'] for x in obs),'unit':'cfs peak daily mean','detail':f'{len(obs)} daily mean discharge readings; not a flood designation','path':obs}
        events.append(event)
    if not events:raise ValueError('The USGS service returned no valid 2024 daily streamflow measurements for selected sites.')
    return events,{'coverage':f'2024 daily mean streamflow at {len(events)} selected USGS stations ({region}); sample, not an inventory of all gauges', 'note':'Stations are chosen from the selected approximate geographic bounding box where available. Units cfs; no flood-stage thresholds and no claim these are flood events.','source':URLS['floods']}

@st.cache_data(ttl=86400,show_spinner=False)
def load_fema(region="US"):
    url=URLS['fema'];rows=[];cap=18000
    flt = "declarationDate ge '2020-01-01T00:00:00.000Z' and declarationDate lt '2026-01-01T00:00:00.000Z'"
    if region != 'US':
        if not re.fullmatch(r'[A-Z]{2}', region):
            raise ValueError('Invalid two-letter FEMA state code.')
        flt += f" and state eq '{region}'"
    params={'$filter':flt,'$top':1000,'$orderby':'declarationDate asc'}
    while len(rows)<cap:
        params['$skip']=len(rows)
        data=_get(url,params,timeout=40).json();batch=data.get('DisasterDeclarationsSummaries')
        if not isinstance(batch,list):raise ValueError('OpenFEMA did not return DisasterDeclarationsSummaries.')
        rows.extend(batch)
        if len(batch)<1000:break
    completed=len(rows)<cap
    group={}
    for x in rows:
        code=x.get('disasterNumber');year=_yyyy(x.get('declarationDate'))
        if code is None or year is None:continue
        key=f"{_safe(x.get('state') or '')}:{code}"  # FEMA designation is state-specific; preserve state distinction
        if key not in group:group[key]={'year':year,'name':_safe(x.get('declarationTitle') or x.get('incidentType') or 'Disaster declaration'),'location':_safe(x.get('state') or 'Not specified'),'value':1,'unit':'declaration','detail':_safe(x.get('incidentType')),'lat':None,'lon':None}
    events=sorted(group.values(),key=lambda x:(x['year'],x['name']))
    if not events:raise ValueError('No FEMA declarations were returned for the selected date range.')
    return events,{'coverage':f'Declarations issued 2020–2025 in {region}, by unique (state, disasterNumber); '+('fully paginated in range' if completed else '18,000-row cap reached — incomplete sample'), 'note':'State is filtered at OpenFEMA API, not merely in the map. Deduplicated state/disaster IDs, not county designation rows. Geographic markers omitted (no official event-point coordinates).','source':url}

LOADERS={'hurricanes':load_hurricanes,'tsunamis':load_tsunamis,'wildfires':load_wildfires,'floods':load_floods,'fema':load_fema}

def _js_json(v):return json.dumps(v,separators=(',',':'),ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')

def render_history_center(region="US", bbox=None, region_name=None):
    st.subheader('Historical Disaster Intelligence')
    st.caption('Five independent official-source historical explorers. Select a category; animation starts on data load without pressing Play. Historical playback is not a live hazard forecast.')
    names=list(CATALOG)
    # HAZARDSCOPE_HISTORY_DEFAULT_HURRICANES_V1
    # Reset an existing browser session only once after this upgrade.
    if not st.session_state.get('haz_history_default_hurricanes_v1'):
        st.session_state['haz_history_category'] = 'hurricanes'
        st.session_state['haz_history_default_hurricanes_v1'] = True
    selected=st.session_state.get('haz_history_category','hurricanes')
    if selected not in names:selected='hurricanes'
    buttons=st.columns(5)
    labels={'hurricanes':'🌀 Hurricanes','tsunamis':'🌊 Tsunamis','wildfires':'🔥 Wildfires','floods':'💧 Floods','fema':'🗺️ FEMA'}
    for i,k in enumerate(names):
        if buttons[i].button(labels[k],key='hh_btn_'+k,type='primary' if selected==k else 'secondary',use_container_width=True):
            st.session_state['haz_history_category']=k
            st.rerun()
    selected=st.session_state.get('haz_history_category','hurricanes')
    title,summary,caveat=CATALOG[selected]
    display_region = region_name or (region if region != 'US' else 'United States')
    if region != 'US':
        st.caption(f'**Historical region:** {display_region} ({region}) · selected in the shared sidebar.')
        if selected == 'hurricanes':
            st.info('State selection matches NOAA storm tracks with at least one recorded position inside the approximate state bounding rectangle. This does NOT establish landfall, damage or actual storm impact.')
        elif selected == 'tsunamis':
            st.info('State selection limits historical tsunami **source epicenters** to the approximate state bounding rectangle. This does NOT identify tsunamis that reached or affected the state. Coastal impacts require separate NOAA runup observations.')
        elif selected == 'wildfires':
            st.info('Perimeters are queried by intersection with an approximate state bounding rectangle. Markers represent official perimeter-derived display points, which may fall outside the box for crossing polygons.')
        elif selected == 'floods':
            st.info('A small sample of stream-monitoring stations is discovered within the approximate state bounding rectangle. Discharge is not a verified flood or comprehensive statewide coverage.')
        else:
            st.info('Only declarations assigned to the selected state are fetched from OpenFEMA. State-specific counts do not describe physical disaster intensity.')
    st.markdown('#### '+title)
    st.write(summary)
    try:
        with st.spinner('Loading official historical records, then starting animation automatically…'):
            if selected == 'fema':
                events,meta=load_fema(region)
            elif selected == 'wildfires':
                events,meta=load_wildfires(region, bbox)
            elif selected == 'floods':
                events,meta=load_floods(region, bbox)
                if region != 'US':
                    events=filter_historical_by_bbox(selected,events,bbox)
            else:
                events,meta=LOADERS[selected]()
                if region != 'US':
                    events=filter_historical_by_bbox(selected,events,bbox)
    except Exception as e:
        st.error('The official historical source is currently unavailable or returned no valid records. No demo data have been substituted.')
        st.caption(f'Diagnostic: {type(e).__name__}: {_safe(e)}')
        st.link_button('Open official source',URLS[selected]);return
    if not events:
        st.info(f'No {title.lower()} records matched {display_region} under the current source-specific geographic rule and sampled period. This is not evidence that the state had no such disasters.')
        st.caption('Change the state to United States · broad region for the original broader historical explorer.')
        return
    events=events[:2500]
    c1,c2=st.columns(2)
    c1.metric(f'Records · {display_region}',f'{len(events):,}')
    c2.metric('Period',f"{min(x['year'] for x in events)}–{max(x['year'] for x in events)}")
    template=Path(__file__).with_name('disaster_history_canvas.html').read_text(encoding='utf-8')
    land=json.loads(Path(__file__).with_name('world_land.json').read_text(encoding='utf-8'))
    visual=template.replace('/*__EVENTS__*/',_js_json(events)).replace('/*__LAND__*/',_js_json(land)).replace('/*__CATEGORY__*/',_js_json(selected)).replace('/*__CAVEAT__*/',_js_json(caveat))
    components.html(visual,height=(820 if selected == 'floods' else 710 if selected == 'fema' else 640),scrolling=False)
    st.caption(f"**Selected region:** {display_region}. **Source:** {meta['source']} · **Coverage:** {meta['coverage']} · **Limitations:** {meta['note']} {caveat}  **Map:** geographic longitude/latitude (WGS84); FEMA uses a schematic U.S. state tile map (not geographic polygons); floods use a separate dated discharge chart. Years and dates represent records; playback timing is compressed, not actual elapsed hazard time.")
    with st.expander('Source details and selected records'):
        st.json({'source':meta['source'],'coverage':meta['coverage'],'selected_region':display_region,'data_warning':meta['note'],'displayed_records':len(events)})
        import pandas as pd
        df=pd.DataFrame([{k:v for k,v in item.items() if k!='path'} for item in events])
        st.dataframe(df,hide_index=True,use_container_width=True)
        st.download_button('Download selected historical records CSV',df.to_csv(index=False).encode(),'hazardscope_'+selected+'_historical.csv','text/csv')
    st.link_button('Official source documentation',URLS[selected])

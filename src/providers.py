"""Validated, bounded, explicit network fetchers. No fabricated results or hidden demo data."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import math
import pandas as pd
import requests

USGS_URL = 'https://earthquake.usgs.gov/fdsnws/event/1/query'
NWS_URL = 'https://api.weather.gov/alerts/active'
FEMA_URL = 'https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries'
METEO_URL = 'https://api.open-meteo.com/v1/forecast'
HEADERS = {'User-Agent': 'HazardScopeUSA/1.0 (educational visualization; contact: hazardscope-usa@users.noreply.github.com)', 'Accept': 'application/json'}
class DataSourceError(Exception): pass

def fetch_json(url, params=None, timeout=23):
    try:
        r=requests.get(url,params=params,headers=HEADERS,timeout=timeout)
        r.raise_for_status()
        ct=r.headers.get('Content-Type','').lower()
        if 'json' not in ct and 'geo+json' not in ct:
            raise DataSourceError(f'Unexpected content type from {r.url}: {ct or "unspecified"}')
        value=r.json()
        if not isinstance(value,(dict,list)):
            raise DataSourceError('Expected a JSON object or array.')
        return value
    except (requests.RequestException,ValueError) as e:
        raise DataSourceError(str(e)) from e

def usgs_earthquakes(days=7, minmag=2.5, maxdepth=700, max_events=2500, bounds=None):
    end=datetime.now(timezone.utc)
    args={'format':'geojson','starttime':(end-timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S'),
          'endtime':end.strftime('%Y-%m-%dT%H:%M:%S'),'minmagnitude':float(minmag),
          'maxdepth':float(maxdepth),'orderby':'time','limit':min(max_events,20000)}
    if bounds is not None:
        south,north,west,east=bounds
        args.update({'minlatitude':float(south),'maxlatitude':float(north),
                     'minlongitude':float(west),'maxlongitude':float(east)})
    obj=fetch_json(USGS_URL,args,timeout=35)
    if not isinstance(obj,dict) or not isinstance(obj.get('features'),list):raise DataSourceError('Invalid USGS GeoJSON features.')
    rows=[]
    for feature in obj['features']:
        props=feature.get('properties') or {}; g=feature.get('geometry') or {}; coords=g.get('coordinates') or []
        if len(coords)<3:continue
        try:
            lon,lat,depth=map(float,coords[:3]); mag=float(props.get('mag'))
            if not (-180<=lon<=180 and -90<=lat<=90) or not all(map(math.isfinite,(lon,lat,depth,mag))):continue
            dt=pd.to_datetime(props.get('time'),unit='ms',utc=True,errors='coerce')
            if pd.isna(dt):continue
            rows.append({'id':str(feature.get('id','')),'lat':lat,'lon':lon,'depth_km':depth,'magnitude':mag,'time':dt,
                         'place':str(props.get('place') or 'Unspecified location'),
                         'url':str(props.get('url') or '')})
        except (TypeError,ValueError,OverflowError):continue
    df=pd.DataFrame(rows,columns=['id','lat','lon','depth_km','magnitude','time','place','url'])
    df.attrs['truncated']=len(obj['features'])>=max_events
    return df, {'endpoint':USGS_URL,'query':args,'returned':len(rows),'fetched_utc':end.isoformat(),'truncated':len(obj['features'])>=max_events}

def nws_alerts(state='US'):
    """Fetch official NWS alerts, retaining actual geometry and time fields.

    Null geometry is expected for many zone-based NWS alerts and must not be
    geocoded or converted to guessed points.
    """
    args={'area':state} if state!='US' else {}
    obj=fetch_json(NWS_URL,args,timeout=30)
    if not isinstance(obj,dict) or not isinstance(obj.get('features'),list):
        raise DataSourceError('Invalid NWS alerts GeoJSON.')
    rows=[]
    for feat in obj['features']:
        if not isinstance(feat,dict):
            continue
        p=feat.get('properties') or {}
        if not isinstance(p,dict):
            continue
        geometry=feat.get('geometry')
        if not isinstance(geometry,dict) or geometry.get('type') not in ('Polygon','MultiPolygon'):
            geometry=None
        rows.append({'id':str(p.get('id') or feat.get('id') or ''),
                     'event':str(p.get('event') or 'Other alert'),
                     'headline':str(p.get('headline') or p.get('event') or ''),
                     'severity':str(p.get('severity') or 'Unknown'),
                     'urgency':str(p.get('urgency') or 'Unknown'),
                     'area':str(p.get('areaDesc') or ''),
                     'effective':str(p.get('effective') or ''),
                     'onset':str(p.get('onset') or ''),
                     'ends':str(p.get('ends') or ''),
                     'expires':str(p.get('expires') or ''),
                     'description':str(p.get('description') or ''),
                     'instruction':str(p.get('instruction') or ''),
                     'url':str(p.get('@id') or p.get('id') or ''),
                     'geometry':geometry,
                     'affected_zones':[u for u in (p.get('affectedZones') or []) if isinstance(u,str)]})
    columns=['id','event','headline','severity','urgency','area','effective','onset',
             'ends','expires','description','instruction','url','geometry','affected_zones']
    df=pd.DataFrame(rows,columns=columns)
    return df,{'endpoint':NWS_URL,'query':args,'returned':len(rows),
               'fetched_utc':datetime.now(timezone.utc).isoformat(),
               'geometries_present':sum(1 for r in rows if r['geometry'] is not None)}

def fema_declarations(state='US', since_year=2020, limit=1000):
    """State-level disaster declarations; rows can repeat a disaster for distinct designated places."""
    filters=[f"declarationDate ge '{int(since_year)}-01-01T00:00:00.000Z'"]
    if state!='US': filters.append(f"state eq '{state}'")
    args={'$filter':' and '.join(filters),'$select':'disasterNumber,state,incidentType,declarationDate,declarationTitle,designatedArea',
          '$top':min(int(limit),1000),'$orderby':'declarationDate desc'}
    obj=fetch_json(FEMA_URL,args,timeout=40)
    if not isinstance(obj,dict) or not isinstance(obj.get('DisasterDeclarationsSummaries'),list):
        raise DataSourceError('Invalid OpenFEMA declaration response.')
    raw=obj['DisasterDeclarationsSummaries']; rows=[]
    for v in raw:
        if not isinstance(v,dict):continue
        rows.append({'disaster_id':str(v.get('disasterNumber') or ''),'state':str(v.get('state') or ''),
            'type':str(v.get('incidentType') or 'Unknown'),'title':str(v.get('declarationTitle') or ''),
            'area':str(v.get('designatedArea') or ''),'date':pd.to_datetime(v.get('declarationDate'),utc=True,errors='coerce')})
    df=pd.DataFrame(rows,columns=['disaster_id','state','type','title','area','date'])
    return df, {'endpoint':FEMA_URL,'query':args,'returned':len(df),'fetched_utc':datetime.now(timezone.utc).isoformat(),
                'possibly_truncated':len(raw)>=args['$top']}

def weather_point(lat,lon,days=3):
    args={'latitude':round(float(lat),4),'longitude':round(float(lon),4),
          'current':'temperature_2m,relative_humidity_2m,pressure_msl,surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation',
          'hourly':'temperature_2m,pressure_msl,wind_speed_10m,wind_gusts_10m,precipitation',
          'forecast_days':int(days),'timezone':'auto'}
    obj=fetch_json(METEO_URL,args,timeout=30)
    if not isinstance(obj,dict) or not isinstance(obj.get('current'),dict) or not isinstance(obj.get('hourly'),dict):
        raise DataSourceError('Missing weather current/hourly fields.')
    hourly=obj['hourly']; times=hourly.get('time')
    if not isinstance(times,list):raise DataSourceError('Missing hourly time array.')
    fields=['temperature_2m','pressure_msl','wind_speed_10m','wind_gusts_10m','precipitation']
    if any(not isinstance(hourly.get(x),list) or len(hourly[x])!=len(times) for x in fields):
        raise DataSourceError('Incomplete hourly weather arrays.')
    df=pd.DataFrame({'time':pd.to_datetime(times,errors='coerce'),**{x:hourly[x] for x in fields}})
    df=df.dropna(subset=['time'])
    return obj['current'],df,{'endpoint':METEO_URL,'query':args,'fetched_utc':datetime.now(timezone.utc).isoformat(),
          'units':obj.get('current_units',{}),'timezone':obj.get('timezone','unspecified'),'returned':len(df)}

def wind_grid(bounds,rows=8,cols=13):
    """Collect model-derived current wind at a coarse lattice. Request explicit multi-coordinate batches."""
    import numpy as np
    south,north,west,east=bounds
    lats=np.linspace(south,north,rows); lons=np.linspace(west,east,cols)
    coords=[(float(lat),float(lon)) for lat in lats for lon in lons]
    records=[]
    for k in range(0,len(coords),24):
        group=coords[k:k+24]
        args={'latitude':','.join(f'{lat:.3f}' for lat,lon in group),
              'longitude':','.join(f'{lon:.3f}' for lat,lon in group),
              'current':'wind_speed_10m,wind_direction_10m,pressure_msl', 'wind_speed_unit':'kmh','timezone':'UTC'}
        data=fetch_json(METEO_URL,args,timeout=45)
        blocks=data if isinstance(data,list) else [data]
        if len(blocks)!=len(group):raise DataSourceError('Wind-grid coordinate response mismatch.')
        for (lat,lon),block in zip(group,blocks):
            if not isinstance(block,dict) or not isinstance(block.get('current'),dict):raise DataSourceError('Invalid wind-grid current weather.')
            cur=block['current']
            try:
                speed=float(cur['wind_speed_10m']); direction=float(cur['wind_direction_10m']); pressure=float(cur['pressure_msl'])
                if not all(math.isfinite(v) for v in (speed,direction,pressure)):raise ValueError('Nonfinite wind value')
            except (KeyError,ValueError,TypeError) as e:raise DataSourceError(f'Invalid wind-grid values: {e}') from e
            records.append({'lat':lat,'lon':lon,'speed':speed,'direction':direction,'pressure':pressure})
    return pd.DataFrame(records), {'endpoint':METEO_URL,'grid_points':len(records),'rows':rows,'cols':cols,
          'fetched_utc':datetime.now(timezone.utc).isoformat(),'method':'Current 10 m model-derived field, nearest weather model grid cells.'}

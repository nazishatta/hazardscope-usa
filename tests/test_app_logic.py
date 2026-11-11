from datetime import datetime, timezone
import numpy as np
import pandas as pd
from src.geo import STATES, bounds_for, center_for
from src.visuals import vector_components, wind_flow_figure, earthquake_map
from src.providers import DataSourceError, fetch_json, usgs_earthquakes

def test_all_states_have_valid_centers():
    assert len(STATES)>=50
    for code,(_,lat,lon) in STATES.items():
        assert -90 <= lat <= 90 and -180 <= lon <= 180
        a,b,c,d=bounds_for(code)
        assert a<b and c<d

def test_meteorological_from_direction():
    east,north=vector_components(np.array([10.,20.,5.]),np.array([270.,0.,90.]))
    assert np.allclose(east,[10.,0.,-5.],atol=1e-8)
    assert np.allclose(north,[0.,-20.,0.],atol=1e-8)

def test_wind_anim_has_real_frames_from_input_grid():
    frame=[]
    for lat in [30.,34.,38.,42.]:
        for lon in [-115.,-108.,-101.,-94.,-87.]:
            frame.append({'lat':lat,'lon':lon,'speed':25.,'direction':270.,'pressure':1012.})
    fig=wind_flow_figure(pd.DataFrame(frame),particles=12,frames_count=5)
    assert len(fig.frames)==5
    assert len(fig.data)==10
    assert fig.layout.updatemenus[0].buttons[0].label=='▶ Play'

def test_empty_earthquake_map():
    data=pd.DataFrame(columns=['lon','lat','magnitude','depth_km','time','place'])
    fig=earthquake_map(data)
    assert len(fig.data)==0

def test_usgs_parses_geojson(monkeypatch):
    payload={'features':[{'id':'test-1','geometry':{'coordinates':[-120,35,12]},'properties':{
        'mag':4.2,'time':1730000000000,'place':'Example place','url':'https://earthquake.usgs.gov/test'}}]}
    monkeypatch.setattr('src.providers.fetch_json',lambda *a,**k:payload)
    data,meta=usgs_earthquakes(days=1,minmag=2.5,bounds=(32,40,-125,-115))
    assert len(data)==1 and data.iloc[0].magnitude==4.2
    assert meta['query']['minlongitude']==-125

def test_usgs_missing_coordinates_skipped(monkeypatch):
    monkeypatch.setattr('src.providers.fetch_json',lambda *a,**k:{'features':[{'geometry':{'coordinates':[]},'properties':{}}]})
    data,_=usgs_earthquakes()
    assert data.empty

def test_reject_non_json(monkeypatch):
    class Fake:
        url='https://example.com'
        headers={'Content-Type':'text/html'}
        def raise_for_status(self):pass
    monkeypatch.setattr('src.providers.requests.get',lambda *a,**kw:Fake())
    try:
        fetch_json('https://example.com')
    except DataSourceError:
        pass
    else:
        assert False,'Must reject HTML API response'

def test_wind_surface_grid_shape():
    from src.visuals import wind_field_surface
    rows=[{'lat':lat,'lon':lon,'speed':20.,'pressure':1010.} for lat in (30.,35.,40.) for lon in (-120.,-110.,-100.)]
    fig=wind_field_surface(pd.DataFrame(rows),'pressure')
    assert len(fig.data)==1
    assert np.asarray(fig.data[0].z).shape==(3,3)

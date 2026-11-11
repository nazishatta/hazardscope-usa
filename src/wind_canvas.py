"""Efficient looping canvas wind visualization from a real sampled wind model."""
from pathlib import Path
import json
from .visuals import _trace_paths

OUTLINE = json.loads((Path(__file__).resolve().parent / 'us_outline.json').read_text())

def wind_canvas_html(field, count=95):
    paths = _trace_paths(field, n_particles=min(160,max(30,int(count))),steps=34)
    trails = []
    for pts, speed in paths:
        if len(pts) >= 4:
            trails.append({'xy': [[round(float(p[1]),4),round(float(p[0]),4)] for p in pts], 'speed':round(float(speed),2)})
    lons=field['lon'].to_numpy(); lats=field['lat'].to_numpy()
    mx=max(1.5,float(lons.max()-lons.min())*.07)
    my=max(1.0,float(lats.max()-lats.min())*.07)
    payload=json.dumps({'trails':trails,'outline':OUTLINE,'bbox':[float(lons.min()-mx),float(lats.min()-my),float(lons.max()+mx),float(lats.max()+my)]},separators=(',',':')).replace('</','<\\/')
    html=Path(__file__).with_name('wind_canvas.html').read_text()
    return html.replace('/*WIND_DATA*/',payload)

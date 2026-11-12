"""Animated, genuine DBSCAN comparison with real point coordinates.
One map; computed geometry and label-invariant group comparison; no synthetic points.
"""
from __future__ import annotations
import json
from math import comb
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st
import streamlit.components.v1 as components

COLORS = ['#33dbc8','#ffb65e','#c18afb','#65a6ff','#ff7fa0','#e6d86c','#9bdc8c','#54bfdc','#f0a0e7','#9fd7ff']
BG = '#080c15'


def membership_delta(a,b):
    a=np.asarray(a,dtype=int); b=np.asarray(b,dtype=int)
    if len(a)!=len(b): raise ValueError('The comparison requires identical observations')
    t=pd.DataFrame({'a':a,'b':b})
    common=t[(t.a>=0)&(t.b>=0)]
    shared=sum(comb(int(k),2) for k in common.groupby(['a','b']).size() if k>1)
    count_a=sum(comb(int(k),2) for k in t[t.a>=0].groupby('a').size() if k>1)
    count_b=sum(comb(int(k),2) for k in t[t.b>=0].groupby('b').size() if k>1)
    return {'new_pairs':int(count_b-shared),'separated_pairs':int(count_a-shared),
            'noise_to_cluster':int(np.sum((a<0)&(b>=0))),
            'cluster_to_noise':int(np.sum((a>=0)&(b<0))),
            'unchanged_noise':int(np.sum((a<0)&(b<0))),
            'same':bool(shared==count_a==count_b and np.array_equal(a<0,b<0))}


def convex_outline(coords):
    """Return a simple convex outer boundary (not a risk area or eps-radius circle)."""
    coords=np.unique(np.asarray(coords,dtype=float),axis=0)
    if len(coords)<3:return None
    # West-to-east longitude wrapping is not safe across antimeridian; omit in that case.
    if np.ptp(coords[:,0])>170:return None
    pts=sorted(map(tuple,coords))
    def cross(o,a,b):return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lo=[]
    for x in pts:
        while len(lo)>=2 and cross(lo[-2],lo[-1],x)<=0:lo.pop()
        lo.append(x)
    hi=[]
    for x in reversed(pts):
        while len(hi)>=2 and cross(hi[-2],hi[-1],x)<=0:hi.pop()
        hi.append(x)
    hull=lo[:-1]+hi[:-1]
    return hull if len(hull)>=3 else None


def _stats(labels):
    return {'clusters':len(set(labels.tolist())-{-1}),
            'clustered':int(np.sum(labels>=0)),'noise':int(np.sum(labels<0))}


def _map_figure(d, labels):
    """Geographic map layers: admin boundaries, optional cluster envelopes, points and noise."""
    fig=go.Figure()
    ids=sorted(set(labels.tolist())-{-1})
    for i,label in enumerate(ids):
        z=d.loc[labels==label]
        color=COLORS[i%len(COLORS)]
        hull=convex_outline(z[['lon','lat']].to_numpy())
        if hull is not None:
            lon=[v[0] for v in hull]+[hull[0][0]]
            lat=[v[1] for v in hull]+[hull[0][1]]
            fig.add_trace(go.Scattergeo(lon=lon,lat=lat,mode='lines',fill='toself',
                fillcolor='rgba('+','.join(str(int(color[k:k+2],16)) for k in (1,3,5))+',0.10)',line=dict(color=color,width=1.6,dash='dot'),
                hoverinfo='skip',showlegend=False))
    for i,label in enumerate(ids):
        z=d.loc[labels==label]
        fig.add_trace(go.Scattergeo(lat=z.lat,lon=z.lon,mode='markers',name=f'Group {i+1} ({len(z)})',
            text=z.place.astype(str),
            customdata=np.column_stack([z.magnitude,z.depth_km,z.time.dt.strftime('%Y-%m-%d %H:%M UTC')]),
            hovertemplate='%{text}<br>Magnitude %{customdata[0]:.1f}<br>Depth %{customdata[1]:.1f} km<br>%{customdata[2]}<extra></extra>',
            marker=dict(size=11,opacity=.97,color=COLORS[i%len(COLORS)],line=dict(color='#f1fcff',width=1.4))))
    z=d.loc[labels==-1]
    if not z.empty:
        fig.add_trace(go.Scattergeo(lat=z.lat,lon=z.lon,mode='markers',
            text=z.place.astype(str),name=f'Noise (−1) · {len(z)}',
            customdata=np.column_stack([z.magnitude,z.depth_km,z.time.dt.strftime('%Y-%m-%d %H:%M UTC')]),
            hovertemplate='%{text}<br>M %{customdata[0]:.1f}<br>Depth %{customdata[1]:.1f} km<br>%{customdata[2]}<br>Unclustered noise<extra></extra>',
            marker=dict(size=8,symbol='x',color='#becbdd',opacity=.88,line=dict(width=1))))
    fig.update_geos(scope='usa',projection_type='albers usa',showland=True,landcolor='#17283c',
        showsubunits=True,subunitcolor='#48617b',showcoastlines=True,coastlinecolor='#48617b',bgcolor=BG)
    fig.update_layout(height=455,margin=dict(l=0,r=5,t=0,b=0),paper_bgcolor=BG,plot_bgcolor=BG,
        font=dict(color='#e6f2ff',size=12),legend=dict(orientation='h',y=-.05,x=.03,
        bgcolor='rgba(8,12,21,.6)',font=dict(size=11)))
    return fig


def render_dbscan_motion(d, labels_a, eps, min_samples, cluster_fn, colors=None, comparison_eps=None):
    """Single attractive animated DBSCAN map, two runs, truthful summary."""
    eps_b=int(comparison_eps if comparison_eps is not None else min(500,eps*2))
    a=np.asarray(labels_a,dtype=int)
    b=np.asarray(cluster_fn(d,eps_b,min_samples),dtype=int)
    delta=membership_delta(a,b)
    sa,sb=_stats(a),_stats(b)
    plot_a=_map_figure(d,a); plot_b=_map_figure(d,b)
    config={'plots':[json.loads(pio.to_json(plot_a)),json.loads(pio.to_json(plot_b))],
        'stats':[sa,sb], 'eps':[int(eps),eps_b], 'min':int(min_samples)}
    # The Plotly bundle is embedded for offline use; never fetch images or scripts from a CDN.
    from plotly.offline import get_plotlyjs
    bundle=get_plotlyjs()
    html="""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>html,body{margin:0;background:#080c15;color:#eaf4ff;font:14px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}
    .shell{border:1px solid #2d4761;border-radius:13px;background:linear-gradient(160deg,#11263a,#080e18 60%);padding:12px 14px}
    .top{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}
    .eyebrow{font-size:11px;color:#70f0d5;letter-spacing:.09em;font-weight:700;text-transform:uppercase}
    .phase{font-size:16px;font-weight:750;margin-top:4px}.meta{color:#a8c1d5;font-size:12px;margin-top:4px}
    button{border:1px solid #456883;border-radius:7px;color:#eaf4ff;background:#172d42;padding:9px 13px;cursor:pointer;font-weight:600}
    button:focus-visible{outline:2px solid #38e2c7}
    .bar{height:5px;background:#26384e;border-radius:6px;overflow:hidden;margin-top:12px}
    .fill{height:100%;width:0%;background:linear-gradient(90deg,#29d9c6,#b88fff);border-radius:6px}
    .metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:12px}
    .metric{border:1px solid #2b465e;border-radius:8px;padding:9px;background:#12253a}
    .metric span{display:block;color:#a4bbcf;font-size:11px}.metric strong{font-size:21px}
    .map{height:460px;transition:opacity .18s ease}.foot{font-size:12px;color:#a9c2d4;margin:6px 2px}
    @media(prefers-reduced-motion:reduce){.map{transition:none}}
    </style><script>__PLOTLY__</script></head><body><section class="shell">
    <div class="top"><div><div class="eyebrow">Live clustering comparison · real USGS coordinates</div><div id="phase" class="phase">Run A · local neighborhoods</div><div class="meta" id="meta"></div></div>
    <div><button id="pause" type="button">Ⅱ Pause</button> <button id="restart" type="button">↻ Replay</button></div></div>
    <div class="bar" aria-label="Time remaining in current clustering run"><div id="progress" class="fill"></div></div>
    <div class="metrics"><div class="metric"><span>Clusters</span><strong id="clusters"></strong></div>
    <div class="metric"><span>Clustered events</span><strong id="clustered"></strong></div>
    <div class="metric"><span>Noise (−1)</span><strong id="noise"></strong></div></div>
    <div class="map" id="map" role="img" aria-label="Map of USGS earthquake cluster and noise locations"></div>
    <div class="foot">Colored points = DBSCAN groups · Gray crosses = retained noise (−1) · Dotted envelopes outline observed cluster extents, not hazard zones.</div>
    </section><script>const cfg=__DATA__; const el=id=>document.getElementById(id);
    let idx=0,playing=true,elapsed=0,last=0,busy=false,intersect=true;
    const ms=4600;const reduced=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    function present(i){if(busy)return;busy=true;idx=i;
     el('phase').textContent='Run '+(i?'B':'A')+' · eps '+cfg.eps[i]+' km · min_samples '+cfg.min;
     let s=cfg.stats[i];el('clusters').textContent=s.clusters;el('clustered').textContent=s.clustered;
     el('noise').textContent=s.noise;el('meta').textContent=(i?'Broader':'Local')+' neighborhood · same observed earthquake locations';
     let p=cfg.plots[i];Plotly.react('map',p.data,p.layout,{displaylogo:false,responsive:true,scrollZoom:false}).then(()=>busy=false).catch(()=>busy=false);
    }
    function tick(now){if(!last)last=now;let dt=Math.min(now-last,120);last=now;
      if(playing&&intersect){elapsed+=dt;if(elapsed>=ms){elapsed=0;present(1-idx)}}
      el('progress').style.width=(100*Math.min(elapsed/ms,1))+'%';window.requestAnimationFrame(tick);}
    el('pause').addEventListener('click',()=>{playing=!playing;el('pause').textContent=playing?'Ⅱ Pause':'▶ Resume'});
    el('restart').addEventListener('click',()=>{elapsed=0;present(0);playing=true;el('pause').textContent='Ⅱ Pause'});
    document.addEventListener('visibilitychange',()=>{last=0});
    if('IntersectionObserver' in window){new IntersectionObserver(a=>{intersect=!!a[0]?.isIntersecting;last=0},{threshold:.01}).observe(el('map'))}
    if(reduced){playing=false;el('pause').textContent='▶ Play animation';}
    present(0);window.requestAnimationFrame(tick);
    </script></body></html>""".replace('__PLOTLY__',bundle).replace('__DATA__',json.dumps(config,separators=(',',':')).replace('</', '<' + chr(92) + '/'))
    st.markdown('**Animated DBSCAN sensitivity · geographic cluster envelopes**')
    st.caption('Two computed DBSCAN runs alternate automatically every 4.6 seconds. Exact epicenter positions stay fixed. Pause or replay at any time.')
    components.html(html,height=675,scrolling=False)
    # HAZARDSCOPE_ASSIGNMENT_CAPTIONS_V1: immediately below animated map
    st.caption(f'**Animated DBSCAN map layers:** U.S. administrative basemap for context (Plotly Albers USA), genuine USGS epicenters colored by DBSCAN membership, dotted convex outlines around clusters with 3+ distinct non-collinear locations, and gray cross markers for retained noise (−1). Colors show arbitrary cluster IDs, not a fixed choropleth classification; number of groups varies with the selected dataset and radii. Run A: eps={int(eps)} km; Run B: eps={eps_b} km; min_samples={int(min_samples)}. Haversine distance uses point coordinates in radians; no heatmap radius. Exclusions: malformed/undated epicenters removed by cleaning before clustering, approximate region bounding rectangles, map projection may omit remote locations, and any fetched-source limit is noted in the section below. Hulls represent displayed point extents, not physical rupture, forecast or hazard zones.')
    if delta['same']:
        st.info(f'**What changed?** No change in geographic group memberships or noise classification between {int(eps)} km and {eps_b} km. This is a valid sensitivity result, not an animation fault.')
    else:
        st.info(f'**What changed, independent of cluster numbers?** Increasing eps from {int(eps)} km to {eps_b} km: **{delta["noise_to_cluster"]} former noise points joined clusters**, {delta["cluster_to_noise"]} became noise, {delta["new_pairs"]} earthquake pairs became grouped, and {delta["separated_pairs"]} pairs became separated. Pair comparisons use actual shared observations, not arbitrary cluster labels.')
    st.caption(f'**Why these parameters?** eps = {int(eps)} km defines an exploratory local-neighborhood distance; eps = {eps_b} km tests broader regional proximity. min_samples = {int(min_samples)} requires at least that many epicenters within a dense neighborhood, including the core observation. Haversine distance uses geographic coordinates in radians. Neither radius defines an actual fault boundary, earthquake risk, or future activity. Noise (−1) observations remain visible as gray crosses and are included in all counts.')

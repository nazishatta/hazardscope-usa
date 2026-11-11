"""Dark, self-contained Plotly geographic visuals with a genuinely animated wind-field rendering."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.ndimage import gaussian_filter
from scipy.interpolate import RegularGridInterpolator

BG='#080c15'; LAND='#151e30'; COAST='#4a5a76'; INK='#e9f1ff'
TEAL='#4de5c2'; YELLOW='#ffe27b'; PINK='#fa60b5'

def dark_geo(fig,title,height=600):
    fig.update_geos(scope='usa',projection_type='albers usa',showland=True,landcolor=LAND,
        showsubunits=True,subunitcolor='#364763',subunitwidth=.6,showlakes=True,lakecolor=BG,
        showcoastlines=True,coastlinecolor=COAST,bgcolor=BG)
    fig.update_layout(title={'text':title,'font':{'size':18}},height=height,paper_bgcolor=BG,
        plot_bgcolor=BG,font={'color':INK,'family':'Arial'},margin=dict(l=8,r=8,t=54,b=8),
        legend={'bgcolor':'rgba(13,20,34,0.8)'},uirevision='keep-view')
    return fig

def earthquake_map(df, marker_scale=1.0, show_density=False, blur=2.2):
    fig=go.Figure()
    if not df.empty and show_density:
        # Event concentration as a grid of translucent points; not a risk or probability field.
        xedges=np.linspace(-170,-65,100); yedges=np.linspace(17,72,67)
        counts,_,_=np.histogram2d(df.lon.to_numpy(),df.lat.to_numpy(),bins=[xedges,yedges])
        smooth=gaussian_filter(counts.astype(float),sigma=float(blur))
        xc=(xedges[:-1]+xedges[1:])/2; yc=(yedges[:-1]+yedges[1:])/2
        mask=smooth>max(float(smooth.max())*.08,1e-6)
        ix,iy=np.where(mask)
        if len(ix):
            fig.add_trace(go.Scattergeo(lon=xc[ix],lat=yc[iy],mode='markers',
              marker={'size':np.clip(6+24*(smooth[ix,iy]/smooth.max()),6,29),
                      'color':smooth[ix,iy], 'colorscale':[[0,'#145e80'],[.35,'#12c0b8'],[.7,'#f6d95b'],[1,'#ff5478']],
                      'opacity':.47,'showscale':True,'colorbar':{'title':'Smoothed<br>event count','thickness':10}},
              hoverinfo='skip',name='Event density (smoothed)'))
    if not df.empty:
        fig.add_trace(go.Scattergeo(lon=df.lon,lat=df.lat,mode='markers',name='Earthquake epicenters',
            text=df.place,customdata=list(zip(df.magnitude.astype(float),df.depth_km.astype(float),df.time.dt.strftime('%Y-%m-%d %H:%M UTC'))),
            hovertemplate='%{text}<br>Magnitude %{customdata[0]:.1f}<br>Depth %{customdata[1]:.1f} km<br>%{customdata[2]}<extra></extra>',
            marker={'size':np.clip((df.magnitude.clip(lower=0)+1)**1.55*marker_scale,4,26),
                    'color':df.depth_km,'colorscale':'Turbo','reversescale':True,'opacity':.87,
                    'line':{'color':'#07131e','width':.4},'colorbar':{'title':'Depth<br>(km)','thickness':10}}))
    return dark_geo(fig,'Earthquake epicenters · marker size = magnitude; color = depth')

def density_fig(df, blur=1.4):
    fig=go.Figure()
    if not df.empty:
        counts,xedges,yedges=np.histogram2d(df.lon,df.lat,bins=[75,50],range=[[-170,-65],[17,72]])
        values=gaussian_filter(counts.T,sigma=blur)
        fig.add_trace(go.Heatmap(z=values,x=(xedges[:-1]+xedges[1:])/2,y=(yedges[:-1]+yedges[1:])/2,
                      colorscale=[[0,'#0d1423'],[.14,'#113f78'],[.4,'#069caa'],[.70,'#c9c855'],[1,'#fff1ad']],
                      colorbar={'title':'Smoothed<br>events'},hovertemplate='Longitude %{x:.1f}°<br>Latitude %{y:.1f}°<br>Smoothed count %{z:.2f}<extra></extra>'))
    fig.update_layout(title='Earthquake event-concentration surface (not risk)',height=440,
        paper_bgcolor=BG,plot_bgcolor=BG,font={'color':INK},xaxis={'title':'Longitude','gridcolor':'#273248'},
        yaxis={'title':'Latitude','gridcolor':'#273248'},margin=dict(l=12,r=20,t=52,b=20))
    return fig

def timeline_fig(df):
    counts=df.copy()
    if len(counts):
        counts['day']=counts.time.dt.floor('D'); counts=counts.groupby('day').size().reset_index(name='events')
    fig=go.Figure(go.Bar(x=counts['day'] if len(counts) else [],y=counts['events'] if len(counts) else [],
                         marker_color=TEAL,hovertemplate='%{x}<br>%{y} earthquakes<extra></extra>'))
    fig.update_layout(title='Event counts by UTC day',height=320,paper_bgcolor=BG,plot_bgcolor=BG,
        font={'color':INK},margin=dict(l=12,r=10,t=48,b=22),xaxis={'gridcolor':'#263449'},yaxis={'gridcolor':'#263449','title':'Recorded events'})
    return fig

def depth_fig(df):
    fig=go.Figure(go.Scatter(x=df.depth_km if len(df) else [],y=df.magnitude if len(df) else [],mode='markers',
        marker={'size':7,'color':PINK,'opacity':.68},hovertemplate='Depth %{x:.1f} km<br>Magnitude %{y:.1f}<extra></extra>'))
    fig.update_layout(title='Magnitude versus depth',height=330,paper_bgcolor=BG,plot_bgcolor=BG,font={'color':INK},
        xaxis={'title':'Depth (km)','gridcolor':'#263449'},yaxis={'title':'Magnitude','gridcolor':'#263449'},margin=dict(l=12,r=10,t=48,b=30))
    return fig

def vector_components(speed, direction):
    """Meteorological FROM direction to eastward/northward vector components."""
    angle=np.deg2rad(np.asarray(direction,dtype=float))
    speed=np.asarray(speed,dtype=float)
    return -speed*np.sin(angle), -speed*np.cos(angle)

def _trace_paths(df, n_particles=130, steps=25, seed=21):
    """Advect synthetic particles through a snapshot of fetched current model wind.

    Longitude scaling compensates for shrinking east-west distance at higher latitudes.
    Particle speed and step time are stylized for legibility, not elapsed forecast time.
    """
    lats=np.sort(df.lat.unique()); lons=np.sort(df.lon.unique())
    if len(lats)<2 or len(lons)<2:return []
    ordered=df.set_index(['lat','lon']).sort_index()
    speed=ordered.speed.to_numpy().reshape(len(lats),len(lons))
    direction=ordered.direction.to_numpy().reshape(len(lats),len(lons))
    east,north=vector_components(speed,direction)
    efield=RegularGridInterpolator((lats,lons),east,bounds_error=False,fill_value=np.nan)
    nfield=RegularGridInterpolator((lats,lons),north,bounds_error=False,fill_value=np.nan)
    rng=np.random.default_rng(seed)
    paths=[]
    for _ in range(n_particles):
        lat=float(rng.uniform(lats[0]+.3*(lats[1]-lats[0]),lats[-1]-.3*(lats[1]-lats[0])))
        lon=float(rng.uniform(lons[0]+.3*(lons[1]-lons[0]),lons[-1]-.3*(lons[1]-lons[0])))
        points=[(lat,lon)]; speeds=[]
        for t in range(steps):
            u=float(efield([[lat,lon]])[0]); v=float(nfield([[lat,lon]])[0])
            if not np.isfinite(u+v):break
            mag=float(np.hypot(u,v)); speeds.append(mag)
            # Nearly uniform vector-tracing step in kilometers, with mild magnitude emphasis.
            step_km=24+18*min(mag/60,1)
            lat+=step_km*(v/max(mag,1))/111.0
            lon+=step_km*(u/max(mag,1))/(111.0*max(.22,np.cos(np.deg2rad(lat))))
            if lat<lats[0] or lat>lats[-1] or lon<lons[0] or lon>lons[-1]:break
            points.append((lat,lon))
        if len(points)>=5:paths.append((np.array(points),np.mean(speeds)))
    return paths

def wind_flow_figure(df, particles=120, frames_count=14):
    """Animated advected particles through one model field; no claim of observed wind tracks."""
    trails=_trace_paths(df,particles,steps=34)
    fig=go.Figure()
    if not trails:return dark_geo(fig,'Wind field unavailable')
    palette=['#40e3e7','#7cedc6','#ffe179','#fb74b0','#b58bff']
    max_speed=max(s for _,s in trails)
    for bucket in range(5):
        xx=[];yy=[]
        for pts,s in trails:
            b=min(4,int(5*s/(max_speed+1e-6)))
            if b==bucket:
                yy.extend(pts[:,0].tolist()+[None]);xx.extend(pts[:,1].tolist()+[None])
        fig.add_trace(go.Scattergeo(lon=xx,lat=yy,mode='lines',line={'width':1,'color':palette[bucket]},opacity=.20,
                 hoverinfo='skip',name=f'Wind band {bucket+1}',showlegend=False))
    def moving(frame):
        traces=[]
        for bucket in range(5):
            xs=[];ys=[]
            for pts,s in trails:
                b=min(4,int(5*s/(max_speed+1e-6)))
                if b!=bucket:continue
                n=len(pts); offset=(frame*2)%n
                for k in range(max(0,offset-3),min(n,offset+2)):
                    ys.append(float(pts[k,0]));xs.append(float(pts[k,1]))
                xs.append(None);ys.append(None)
            traces.append(go.Scattergeo(lon=xs,lat=ys,mode='lines',line={'width':2.2,'color':palette[bucket]},
                                       opacity=.95,hoverinfo='skip',showlegend=False))
        return traces
    for trace in moving(0):fig.add_trace(trace)
    frames=[go.Frame(name=str(i),data=moving(i),traces=list(range(5,10))) for i in range(frames_count)]
    fig.frames=frames
    fig=dark_geo(fig,'Animated wind streamlines · model-derived 10 m wind field',height=630)
    fig.update_layout(updatemenus=[{'type':'buttons','x':.02,'y':.02,'xanchor':'left','yanchor':'bottom','direction':'left',
        'bgcolor':'#202b42','font':{'color':'#eef5ff'},'buttons':[
        {'label':'▶ Play','method':'animate','args':[None,{'frame':{'duration':110,'redraw':True},'fromcurrent':True,'transition':{'duration':0}}]},
        {'label':'Ⅱ Pause','method':'animate','args':[[None],{'frame':{'duration':0,'redraw':True},'mode':'immediate'}]}]}])
    return fig

def wind_speed_map(df):
    fig=go.Figure(go.Scattergeo(lat=df.lat,lon=df.lon,mode='markers',
        customdata=np.stack((df.pressure,df.direction),axis=1),
        marker={'size':13,'color':df.speed,'colorscale':'Turbo','colorbar':{'title':'km/h'},'opacity':.85},
        hovertemplate='Wind %{marker.color:.1f} km/h<br>Pressure %{customdata[0]:.0f} hPa<br>From %{customdata[1]:.0f}°<extra></extra>'))
    return dark_geo(fig,'Current forecast-grid wind speed and pressure')


def wind_field_surface(df, field='speed'):
    """Sampled forecast-grid scalar field. Rectangular geo coordinates, not a hazard probability map."""
    label={'speed':'Wind speed (km/h)','pressure':'Mean sea-level pressure (hPa)'}[field]
    grid=df.pivot_table(index='lat',columns='lon',values=field,aggfunc='mean').sort_index()
    fig=go.Figure(go.Heatmap(x=grid.columns.to_numpy(),y=grid.index.to_numpy(),z=grid.to_numpy(),
        colorscale='Turbo' if field=='speed' else 'Viridis',
        colorbar={'title':label},hovertemplate='Longitude %{x:.2f}°<br>Latitude %{y:.2f}°<br>Value %{z:.1f}<extra></extra>'))
    fig.update_layout(title=f'Weather model sampled field · {label}',height=420,
        paper_bgcolor=BG,plot_bgcolor=BG,font={'color':INK},
        margin=dict(l=12,r=10,t=50,b=25),xaxis={'title':'Longitude','gridcolor':'#263449'},
        yaxis={'title':'Latitude','gridcolor':'#263449'})
    return fig

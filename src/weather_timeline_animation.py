"""Autoplay Open-Meteo hourly forecast presentation (no network requests or fabricated data)."""
from __future__ import annotations

import json
import math

import pandas as pd

LABELS = {
    'wind_speed_10m': ('10 m wind speed', 'km/h'),
    'pressure_msl': ('Mean sea-level pressure', 'hPa'),
    'temperature_2m': ('Air temperature', '°C'),
    'wind_gusts_10m': ('10 m wind gusts', 'km/h'),
    'precipitation': ('Hourly precipitation', 'mm'),
}


def weather_timeline_html(frame, metric: str, region_label: str = "selected region", forecast_days: int | None = None) -> str:
    """Animate sequential display of real hourly forecast points on a responsive canvas."""
    if metric not in LABELS:
        raise ValueError('Unexpected weather metric')
    if frame is None or not {'time', metric}.issubset(frame.columns):
        return '<p style="color:#ccd9e5">No valid hourly forecast data available.</p>'
    data = frame[['time', metric]].copy()
    data['time'] = pd.to_datetime(data.time, errors='coerce', utc=True)
    data[metric] = pd.to_numeric(data[metric], errors='coerce')
    data = data.dropna().sort_values('time').drop_duplicates('time')
    data = data[data[metric].apply(math.isfinite)]
    if data.empty:
        return '<p style="color:#ccd9e5">No valid hourly forecast points for this metric.</p>'
    values = [[int(row.time.timestamp() * 1000), round(float(getattr(row, metric)), 5)] for row in data.itertuples(index=False)]
    label, units = LABELS[metric]
    readings = data[metric].astype(float)
    first = float(readings.iloc[0]); last_value = float(readings.iloc[-1])
    minimum = float(readings.min()); maximum = float(readings.max())
    avg = float(readings.mean()); change = last_value - first
    min_time = data.iloc[int(readings.argmin())]['time'].strftime('%b %d, %H:%M UTC')
    max_time = data.iloc[int(readings.argmax())]['time'].strftime('%b %d, %H:%M UTC')
    time_start = data.iloc[0]['time'].strftime('%b %d, %Y %H:%M UTC')
    time_end = data.iloc[-1]['time'].strftime('%b %d, %Y %H:%M UTC')
    def fmt(number):
        return f'{number:,.2f}' if abs(number) < 1 else f'{number:,.1f}'
    if metric == 'precipitation':
        rainy = int((readings > 0).sum())
        insight = (f'The model forecasts {fmt(float(readings.sum()))} mm of accumulated precipitation across '
                   f'{len(readings)} available hourly periods, with measurable precipitation in {rainy} hours. '
                   'Hourly bars would represent amounts per hour, not a cumulative rainfall rate.')
    elif metric in ('wind_speed_10m', 'wind_gusts_10m'):
        insight = (f'Predicted {label.lower()} ranges from {fmt(minimum)} to {fmt(maximum)} {units} across the '
                   f'available period. Higher values indicate stronger modeled wind; the peak occurs at {max_time}.')
    elif metric == 'temperature_2m':
        insight = (f'Predicted air temperature ranges from {fmt(minimum)} to {fmt(maximum)} °C. '
                   f'The model reaches the warmest forecast hour at {max_time}.')
    else:
        insight = (f'Predicted mean sea-level pressure ranges from {fmt(minimum)} to {fmt(maximum)} hPa. '
                   'Pressure describes the modeled atmospheric state; it is not a direct forecast of severe-weather impacts.')
    context = (f'Location: approximate model grid/forecast point at the center of {region_label}; '
               f'{forecast_days}-day query requested. ' if forecast_days is not None
               else f'Location: approximate forecast point at the center of {region_label}. ')
    summary = (f'{context}Forecast hours: {time_start} to {time_end} ({len(readings)} valid records). '
               f'Low: {fmt(minimum)} {units} ({min_time}); high: {fmt(maximum)} {units} ({max_time}); '
               f'average: {fmt(avg)} {units}; first-to-last change: {fmt(change)} {units}.')
    payload = json.dumps({'points': values, 'label': label, 'unit': units,
                          'summary': summary, 'insight': insight,
                          'region': region_label}, separators=(',', ':')).replace('</', '<\\/')
    template = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box}html,body{margin:0;background:#080c15;color:#eaf3ff;font:13px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}
.shell{border:1px solid #2a3e57;background:linear-gradient(165deg,#101d30,#080d17 76%);border-radius:14px;padding:15px 17px;overflow:hidden}
.header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.eyebrow{color:#39ddc3;text-transform:uppercase;font-size:10px;letter-spacing:.13em;font-weight:800}.heading{font-size:17px;font-weight:700;margin-top:5px}.tools{display:flex;gap:7px}button{background:#172b42;color:#f0fbff;border:1px solid #42637c;border-radius:7px;padding:8px 12px;font-weight:650;cursor:pointer}button:focus-visible{outline:2px solid #51edd2;outline-offset:2px}.live{margin-top:10px;display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;color:#a8bad3}.live strong{color:#4fe9d0;font-size:17px;font-variant-numeric:tabular-nums}.canvas{width:100%;height:270px;display:block;touch-action:pan-y;margin-top:9px}.progress{height:5px;background:#263a50;border-radius:10px;overflow:hidden}.progress div{height:100%;width:0;background:linear-gradient(90deg,#20d5c6,#8aa9ff);border-radius:10px}.explain{margin-top:14px;border:1px solid #2c4b61;border-radius:10px;padding:12px 14px;background:#102133}.explain h3{font-size:15px;color:#59ead2;margin:0 0 7px}.explain p{font-size:12px;line-height:1.55;color:#d4e3f1;margin:6px 0}.now{font-size:12px;color:#6ce8cf;margin-top:8px;font-weight:650}.note{line-height:1.5;color:#9aafc8;font-size:11px;margin-top:10px}.legend{display:flex;gap:16px;color:#a6bad1;font-size:11px;margin-top:9px;flex-wrap:wrap}.dot{display:inline-block;background:#39dcc6;width:9px;height:9px;border-radius:50%;margin-right:5px}.line{display:inline-block;background:#6f85a8;width:17px;height:2px;vertical-align:middle;margin-right:5px}
@media(max-width:600px){.canvas{height:240px}.shell{padding:11px}.heading{font-size:15px}}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body><div class="shell">
<div class="header"><div><div class="eyebrow">Hourly weather forecast · animated progression</div><div class="heading" id="heading"></div></div><div class="tools"><button id="pause">Ⅱ Pause</button><button id="replay">↺ Replay</button></div></div>
<div class="live"><div><span>Displayed time: </span><span id="stamp">—</span></div><strong id="reading">—</strong></div>
<canvas class="canvas" id="chart" role="img" aria-label="Hourly weather forecast animated line chart with labeled axes"></canvas>
<div class="progress"><div id="fill"></div></div><div class="legend"><span><i class="dot"></i>Official forecast sample</span><span><i class="line"></i>Remaining forecast period</span></div>
<section class="explain" aria-live="off"><h3>What this forecast is telling us</h3><p id="insight"></p><p id="summary"></p><div class="now" id="currentInsight" aria-live="off"></div></section>
<div class="note">**Reading the graph:** Horizontal axis = forecast UTC time; vertical axis = the selected weather metric and its units. Bright turquoise = forecast hours revealed by the animation; gray = remaining forecast hours; dashed vertical line = highlighted hour. These are Open-Meteo model predictions at one approximate point, not observed conditions or statewide measurements. Animation plays through forecast hours faster than real time; it does not show real weather moving.</div>
</div><script>
const cfg=__PAYLOAD__,pts=cfg.points,chart=document.getElementById('chart'),ctx=chart.getContext('2d');
const el=id=>document.getElementById(id);el('heading').textContent=cfg.label+' ('+cfg.unit+')';el('summary').textContent=cfg.summary;el('insight').textContent=cfg.insight;
let elapsed=0,playing=!matchMedia('(prefers-reduced-motion: reduce)').matches,last=0,visible=true;
const duration=Math.max(8500,Math.min(18000,pts.length*140)), pad={l:58,r:22,t:28,b:54};
if(!playing)el('pause').textContent='▶ Play';
const numbers=pts.map(p=>p[1]), min=Math.min(...numbers),max=Math.max(...numbers),span=Math.max(max-min,0.1),lo=min-span*.15,hi=max+span*.2;
function niceTime(ms){return new Date(ms).toLocaleString('en-US',{timeZone:'UTC',month:'short',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})+' UTC'}
function render(){const dpr=Math.min(devicePixelRatio||1,2),w=chart.clientWidth,h=chart.clientHeight;if(chart.width!==Math.round(w*dpr)||chart.height!==Math.round(h*dpr)){chart.width=Math.round(w*dpr);chart.height=Math.round(h*dpr)}ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,w,h);const iw=Math.max(1,w-pad.l-pad.r),ih=h-pad.t-pad.b;
const x=i=>pad.l+(pts.length===1?.5:i/(pts.length-1))*iw, y=v=>pad.t+(hi-v)/(hi-lo)*ih;
ctx.font='11px system-ui';ctx.textAlign='right';ctx.textBaseline='middle';for(let j=0;j<=4;j++){let value=lo+(hi-lo)*j/4,yy=y(value);ctx.strokeStyle='#28374d';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(w-pad.r,yy);ctx.stroke();ctx.fillStyle='#a5b6cc';ctx.fillText(value.toFixed(span<4?1:0),pad.l-10,yy)}
ctx.textAlign='center';ctx.textBaseline='top';let nt=Math.min(5,pts.length);for(let j=0;j<nt;j++){let index=Math.round(j*(pts.length-1)/Math.max(1,nt-1));ctx.fillStyle='#9eb3c9';ctx.fillText(new Date(pts[index][0]).toLocaleString('en-US',{timeZone:'UTC',month:'short',day:'numeric',hour:'2-digit',hour12:false}),x(index),h-pad.b+12)}
ctx.save();ctx.translate(12,pad.t+ih/2);ctx.rotate(-Math.PI/2);ctx.textAlign='center';ctx.fillStyle='#b9cbe0';ctx.fillText(cfg.unit,0,0);ctx.restore();
// Muted complete trace provides temporal context without suggesting future samples already animated.
ctx.beginPath();pts.forEach((p,i)=>{if(i===0)ctx.moveTo(x(i),y(p[1]));else ctx.lineTo(x(i),y(p[1]))});ctx.strokeStyle='#40516c';ctx.lineWidth=1.5;ctx.stroke();
const fraction=Math.max(0,Math.min(1,elapsed/duration)),iFloat=fraction*Math.max(0,pts.length-1),whole=Math.floor(iFloat);ctx.beginPath();for(let i=0;i<=whole;i++){if(i===0)ctx.moveTo(x(i),y(pts[i][1]));else ctx.lineTo(x(i),y(pts[i][1]))}if(whole<pts.length-1){let p=pts[whole],q=pts[whole+1],ratio=iFloat-whole;ctx.lineTo(x(whole)+ratio*(x(whole+1)-x(whole)),y(p[1])+ratio*(y(q[1])-y(p[1])))}ctx.strokeStyle='#30ddc7';ctx.lineWidth=3;ctx.lineJoin='round';ctx.lineCap='round';ctx.stroke();
for(let i=0;i<=whole;i++){ctx.beginPath();ctx.arc(x(i),y(pts[i][1]),2.8,0,Math.PI*2);ctx.fillStyle='#67fae4';ctx.fill()}
const markerIndex=Math.min(pts.length-1,Math.round(iFloat)),mp=pts[markerIndex];ctx.strokeStyle='#79c4db';ctx.setLineDash([4,5]);ctx.beginPath();ctx.moveTo(x(markerIndex),pad.t);ctx.lineTo(x(markerIndex),pad.t+ih);ctx.stroke();ctx.setLineDash([]);ctx.beginPath();ctx.arc(x(markerIndex),y(mp[1]),6,0,Math.PI*2);ctx.fillStyle='#52f9db';ctx.fill();ctx.strokeStyle='#0b2430';ctx.lineWidth=2;ctx.stroke();
const prior=markerIndex>0?pts[markerIndex-1][1]:null;const delta=prior===null?'first available forecast hour':((mp[1]-prior)>=0?'+':'')+(mp[1]-prior).toFixed(2)+' '+cfg.unit+' versus previous forecast hour';el('currentInsight').textContent='At '+niceTime(mp[0])+': '+mp[1].toFixed(span<5?2:1)+' '+cfg.unit+' · '+delta+'.';el('stamp').textContent=niceTime(mp[0]);el('reading').textContent=mp[1].toFixed(span<5?2:1)+' '+cfg.unit;el('fill').style.width=(fraction*100).toFixed(2)+'%';}
function tick(now){if(!last)last=now;let dt=Math.min(100,now-last);last=now;if(playing&&visible){elapsed+=dt;if(elapsed>=duration)elapsed=0}render();requestAnimationFrame(tick)}
el('pause').onclick=()=>{playing=!playing;el('pause').textContent=playing?'Ⅱ Pause':'▶ Resume'};
el('replay').onclick=()=>{elapsed=0;playing=true;el('pause').textContent='Ⅱ Pause';render()};
document.addEventListener('visibilitychange',()=>{visible=!document.hidden;last=0});
if('IntersectionObserver' in window){new IntersectionObserver(entries=>{visible=entries[0]?.isIntersecting??true;last=0},{threshold:0}).observe(chart)}
window.addEventListener('resize',render);render();requestAnimationFrame(tick);
</script></body></html>'''
    return template.replace('__PAYLOAD__', payload)

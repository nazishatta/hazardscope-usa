"""Continuous wind animation player using Plotly frames inside a Streamlit HTML component.

Visual particles move through the last sampled model-derived wind field. This is
NOT a real-time observation feed or continuous weather-model update.
"""
from html import escape


def looping_wind_html(fig):
    # The JS bundle is inlined so the animation works without fetching from a CDN.
    # Each Streamlit component frame has its own document and animation controls.
    html = fig.to_html(
        full_html=False,
        include_plotlyjs=True,
        auto_play=False,
        div_id="hazardscope_wind_animation",
        config={"displayModeBar": False, "responsive": True},
    )
    controls = """
    <style>
      html,body {margin:0;background:#090e19;color:#e7f3fa;font-family:system-ui,Arial,sans-serif;}
      .controls {display:flex;gap:9px;align-items:center;padding:8px 18px;flex-wrap:wrap;}
      .controls button {border:1px solid #587083;border-radius:6px;background:#1b2b3b;color:#f0faff;
        padding:8px 16px;cursor:pointer;font-size:14px;}
      .controls button:focus-visible {outline:3px solid #59d5cc;}
      #wind-note {font-size:12px;color:#9fb5c8;}
      #hazardscope_wind_animation {width:100%;height:620px;}
    </style>
    <div class="controls">
      <button id="hs-play" type="button">▶ Play / Resume</button>
      <button id="hs-pause" type="button">Ⅱ Pause</button>
      <span id="wind-note">Continuous animation · sampled model wind, not a live sensor stream</span>
    </div>
    <script>
      (function () {
        var chart = document.getElementById('hazardscope_wind_animation');
        var active = true;
        var replayTimer = null;
        var ready = function() {
          if (!chart || !chart.on || !window.Plotly || !chart._fullLayout) {
            window.setTimeout(ready, 150); return;
          }
          // Hide the original one-shot Plotly controls; custom controls below loop playback.
          window.Plotly.relayout(chart, {'updatemenus[0].visible': false});
          function start() {
            if (!active) return;
            if (replayTimer !== null) {clearTimeout(replayTimer); replayTimer = null;}
            window.Plotly.animate(chart, null, {
              mode:'immediate',fromcurrent:false,
              frame:{duration:110,redraw:true},transition:{duration:0}
            });
          }
          chart.on('plotly_animated', function() {
            if (active) replayTimer = window.setTimeout(start, 80);
          });
          document.getElementById('hs-play').addEventListener('click', function() {
            active = true; start();
          });
          document.getElementById('hs-pause').addEventListener('click', function() {
            active = false;
            if (replayTimer !== null) {clearTimeout(replayTimer); replayTimer=null;}
            window.Plotly.animate(chart, [null], {
              mode:'immediate',frame:{duration:0,redraw:false},transition:{duration:0}
            });
          });
          start();
        };
        ready();
      })();
    </script>
    """
    return html + controls

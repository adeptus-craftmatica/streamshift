/* ── Scene Overlay Shared JS ──────────────────────────────────────────── */
(function(){
  function param(k,d){var m=location.search.match(new RegExp('[?&]'+k+'=([^&]*)'));return m?decodeURIComponent(m[1]):d;}
  function hexRgb(h){h=h.replace('#','');if(h.length===3)h=h[0]+h[0]+h[1]+h[1]+h[2]+h[2];var n=parseInt(h,16);return[(n>>16)&255,(n>>8)&255,n&255].join(',');}

  function applyTheme(){
    var R=document.documentElement;
    var accent=param('accent','7c3aed'), bg=param('bg','0d0d0f'), txt=param('text','f0f0ff');
    var opacity=(parseInt(param('opacity','92'))/100).toFixed(2);
    R.style.setProperty('--accent','#'+accent);
    R.style.setProperty('--accent-rgb',hexRgb(accent));
    R.style.setProperty('--bg','#'+bg);
    R.style.setProperty('--bg-rgb',hexRgb(bg));
    R.style.setProperty('--bg-opacity',opacity);
    R.style.setProperty('--text-hi','#'+txt);
    R.style.setProperty('--text-lo','rgba('+hexRgb(txt)+',0.55)');
  }

  var _apiBase  = location.protocol+'//'+location.host;
  var _interval = parseInt(param('interval','800'));
  var _lastScene = null;
  var _callbacks = {};

  function fetchState(cb){
    fetch(_apiBase+'/api/state')
      .then(function(r){return r.json();})
      .then(cb).catch(function(){});
  }

  function startScene(opts){
    opts=opts||{};
    _callbacks=opts;
    applyTheme();
    setInterval(function(){
      fetchState(function(s){
        var changed = _lastScene !== s.current_scene;
        _lastScene = s.current_scene;
        if(opts.onUpdate) opts.onUpdate(s, changed);
      });
    },_interval);
    fetchState(function(s){_lastScene=s.current_scene; if(opts.onUpdate)opts.onUpdate(s,false);});
  }

  window.startScene = startScene;
  window.sceneParam = param;
})();

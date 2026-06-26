/* Stream Stats overlay JS — polls /api/state every 2 s */
(function(){
  var _state = null;

  function fmt(n){ return (n||0).toLocaleString(); }

  function poll(){
    fetch('/api/state')
      .then(function(r){ return r.json(); })
      .then(function(s){
        if(window.onStatsUpdate) window.onStatsUpdate(s, _state);
        _state = s;
      })
      .catch(function(){});
    setTimeout(poll, 2000);
  }

  document.addEventListener('DOMContentLoaded', function(){
    poll();
  });

  window.statsFmt = fmt;
})();

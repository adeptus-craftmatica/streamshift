/* Stream Stats overlay JS — polls /api/state every 2 s */
(function(){
  var _state     = null;
  var _failCount = 0;
  var _reloading = false;

  function fmt(n){ return (n||0).toLocaleString(); }

  function poll(){
    fetch('/api/state')
      .then(function(r){ return r.json(); })
      .then(function(s){
        _failCount = 0;
        if(window.onStatsUpdate) window.onStatsUpdate(s, _state);
        _state = s;
      })
      .catch(function(){
        _failCount++;
        if (_failCount >= 6 && !_reloading) {
          _reloading = true;
          setTimeout(function(){ window.location.reload(); }, 3000);
        }
      });
    setTimeout(poll, 2000);
  }

  document.addEventListener('DOMContentLoaded', function(){
    // Startup probe — if server is down, prime counter so reload fires fast.
    fetch('/api/state').catch(function(){ _failCount = 4; });
    poll();
  });

  window.statsFmt = fmt;
})();

/* 每日英語 Service Worker
   - HTML：網路優先（有網路就拿到最新版），離線時退回快取
   - 圖示／字型：快取優先
   - Gemini API：一律走網路，不快取
   改版時把 CACHE 的版本號 +1，舊快取會在啟用時清掉。 */
var CACHE = 'daily-english-v29';
// 發音包放在不帶版本號的快取，改版時不會被清掉、也不用重抓
var AUDIO_CACHE = 'daily-english-audio';
var ENTRY = './index.html';          // 部署入口檔名
var CORE_REQUIRED = ['./', ENTRY];   // 缺這兩個就沒有離線可言
var CORE_OPTIONAL = [
  './manifest.webmanifest',
  './icon-180.png',
  './icon-192.png',
  './icon-512.png',
  './audio/index.json'
];

// 內建發音包：安裝時抓下來，之後完全離線可用。
// 檔案已經很多（數百個），所以：只抓還沒有的、一次最多 6 個、放進不帶版本號的快取。
function cacheAudioPack() {
  return Promise.all([caches.open(AUDIO_CACHE), fetch('./audio/index.json', { cache: 'reload' })])
    .then(function(a){
      var cache = a[0], r = a[1];
      if (!r.ok) return;
      return r.json().then(function(idx){
        var files = Object.keys(idx).map(function(k){ return './audio/' + idx[k]; });
        return fetchMissing(cache, files, 6);
      });
    })
    .catch(function(err){ console.warn('[sw] 發音包快取略過:', err && err.message); });
}

// 限制同時進行的請求數，避免一次送出幾百個 fetch 把手機網路塞爆
function fetchMissing(cache, urls, conc) {
  var i = 0;
  function worker() {
    if (i >= urls.length) return Promise.resolve();
    var u = urls[i++];
    return cache.match(u).then(function(hit){
      if (hit) return;                       // 已經有了就不用再抓
      return fetch(u, { cache: 'reload' }).then(function(res){
        if (res && res.ok) return cache.put(u, res);
      }).catch(function(){});
    }).then(worker);
  }
  var ws = [];
  for (var k = 0; k < Math.min(conc, urls.length); k++) ws.push(worker());
  return Promise.all(ws);
}

// 逐檔快取：可選檔案失敗不會讓整個安裝失敗（addAll 是全有全無）
function cacheAll(cache, urls, required) {
  return Promise.all(urls.map(function(u) {
    return fetch(u, { cache: 'reload' }).then(function(res) {
      if (!res || !res.ok) throw new Error('bad response for ' + u);
      return cache.put(u, res);
    }).catch(function(err) {
      if (required) throw err;
      console.warn('[sw] 略過無法快取的檔案:', u, err && err.message);
    });
  }));
}

self.addEventListener('install', function(e) {
  e.waitUntil(
    caches.open(CACHE)
      .then(function(c) {
        return cacheAll(c, CORE_REQUIRED, true)
          .then(function() { return cacheAll(c, CORE_OPTIONAL, false); })
          .then(function() { return cacheAudioPack(); });
      })
      .then(function() { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.map(function(k) {
        return (k === CACHE || k === AUDIO_CACHE) ? null : caches.delete(k);
      }));
    }).then(function() { return self.clients.claim(); })
  );
});

self.addEventListener('fetch', function(e) {
  var req = e.request;
  if (req.method !== 'GET') return;

  var url;
  try { url = new URL(req.url); } catch (err) { return; }

  // Gemini（generativelanguage.googleapis.com）等 API 不攔截
  if (url.hostname.indexOf('googleapis.com') > -1 && url.hostname.indexOf('fonts') < 0) return;

  var isHTML = req.mode === 'navigate' ||
               (req.headers.get('accept') || '').indexOf('text/html') > -1;

  if (isHTML) {
    e.respondWith(
      fetch(req).then(function(res) {
        var copy = res.clone();
        caches.open(CACHE).then(function(c) { c.put(ENTRY, copy); });
        return res;
      }).catch(function() {
        // 離線：先找實際請求的網址，再退回入口檔，最後退回根路徑
        return caches.match(req).then(function(hit) {
          return hit || caches.match(ENTRY).then(function(r) {
            return r || caches.match('./');
          });
        });
      })
    );
    return;
  }

  e.respondWith(
    caches.match(req).then(function(hit) {
      if (hit) return hit;
      var isAudio = url.pathname.indexOf('/audio/') > -1;
      return fetch(req).then(function(res) {
        if (res && (res.ok || res.type === 'opaque')) {
          var copy = res.clone();
          caches.open(isAudio ? AUDIO_CACHE : CACHE).then(function(c) { c.put(req, copy); });
        }
        return res;
      }).catch(function() { return hit; });
    })
  );
});

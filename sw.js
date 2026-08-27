/* 每日英語 Service Worker
   - HTML：網路優先（有網路就拿到最新版），離線時退回快取
   - 圖示／字型：快取優先
   - Gemini API：一律走網路，不快取
   改版時把 CACHE 的版本號 +1，舊快取會在啟用時清掉。 */
var CACHE = 'daily-english-v25';
var ENTRY = './index.html';          // 部署入口檔名
var CORE_REQUIRED = ['./', ENTRY];   // 缺這兩個就沒有離線可言
var CORE_OPTIONAL = [
  './manifest.webmanifest',
  './icon-180.png',
  './icon-192.png',
  './icon-512.png',
  './audio/index.json'
];

// 內建發音包：安裝時一併抓下來，之後完全離線可用
function cacheAudioPack(cache) {
  return fetch('./audio/index.json', { cache: 'reload' })
    .then(function(r){ return r.ok ? r.json() : null; })
    .then(function(idx){
      if (!idx) return;
      var files = Object.keys(idx).map(function(k){ return './audio/' + idx[k]; });
      return cacheAll(cache, files, false);
    })
    .catch(function(err){ console.warn('[sw] 發音包快取略過:', err && err.message); });
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
          .then(function() { return cacheAudioPack(c); });
      })
      .then(function() { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.map(function(k) {
        return k === CACHE ? null : caches.delete(k);
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
      return fetch(req).then(function(res) {
        if (res && (res.ok || res.type === 'opaque')) {
          var copy = res.clone();
          caches.open(CACHE).then(function(c) { c.put(req, copy); });
        }
        return res;
      }).catch(function() { return hit; });
    })
  );
});

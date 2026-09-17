/* 每日英語 Service Worker
   - HTML：網路優先（有網路就拿到最新版），離線時退回快取
   - 圖示／字型：快取優先
   - Gemini API：一律走網路，不快取
   改版時把 CACHE 的版本號 +1，舊快取會在啟用時清掉。 */
var CACHE = 'daily-english-v42';
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

// 發音包不在安裝時整包抓（全部做完會有數百 MB）。
// 播到哪一個字才下載哪一個，下載後存進不帶版本號的快取、永久保留。
// App 端會另外預抓接下來幾課（見 index.html 的 prefetchLessons）。

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
          ;
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
    }).then(function() {
      // 舊版本可能把 index.json 存進了永久快取，會導致之後新增的發音一直讀不到；
      // 發音包已全面改成 .mp3，手機裡留著的舊 .wav 都用不到了，一併刪掉釋放空間
      return caches.open(AUDIO_CACHE).then(function(c) {
        return c.keys().then(function(reqs) {
          return Promise.all(reqs.map(function(r) {
            var u = r.url || '';
            if (/\/audio\/index\.json/.test(u) || /\.wav(\?|$)/.test(u)) return c.delete(r);
          }));
        });
      }).catch(function(){});
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

  // 發音清單：有網路一律拿最新的（沒變動時伺服器回 304，幾乎不花流量），離線才用快取。
  // 不能先給舊的：音檔改過檔名時（例如 .wav → .mp3），舊清單會指向已經刪掉的檔案而沒聲音
  if (url.pathname.indexOf('/audio/index.json') > -1) {
    e.respondWith(
      caches.open(CACHE).then(function(c) {
        return fetch(req, { cache: 'no-cache' }).then(function(res) {
          if (res && res.ok) c.put(req, res.clone());
          return res;
        }).catch(function() {
          return c.match(req).then(function(hit) {
            return hit || new Response('{}', { headers: { 'Content-Type': 'application/json' } });
          });
        });
      })
    );
    return;
  }

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
      var isAudio = url.pathname.indexOf('/audio/') > -1 &&
                    url.pathname.indexOf('index.json') < 0;
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

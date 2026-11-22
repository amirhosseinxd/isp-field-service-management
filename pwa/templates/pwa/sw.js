// QGS service worker.
//   1. Push notifications (same behaviour as before).
//   2. A small version-named cache for static files only.
//   3. A friendly offline page, shown only when the network cannot be reached.
// It never stores HTML pages, notification data, photos, videos or anything that depends on who is logged in.

var VERSION = '{{ version|escapejs }}';
var CACHE_PREFIX = 'qgs-';
var CACHE = CACHE_PREFIX + VERSION;
var OFFLINE_URL = '{{ offline_url|escapejs }}';
var STATIC_URL = new URL('{{ static_url|escapejs }}', self.location.origin);

self.addEventListener('install', function (event) {
  event.waitUntil(
    caches.open(CACHE)
      .then(function (cache) { return cache.add(new Request(OFFLINE_URL, { cache: 'reload' })); })
      .catch(function () {})                       // a failed pre-cache must never block an update
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('activate', function (event) {
  event.waitUntil(
    caches.keys().then(function (names) {
      // Delete every older QGS cache. Only the cache of the current version survives.
      return Promise.all(names
        .filter(function (name) { return name.indexOf(CACHE_PREFIX) === 0 && name !== CACHE; })
        .map(function (name) { return caches.delete(name); }));
    }).then(function () { return self.clients.claim(); })
  );
});

function isStaticFile(url) {
  var isStatic = url.origin === STATIC_URL.origin && url.pathname.indexOf(STATIC_URL.pathname) === 0;
  var isIcon = url.pathname.indexOf('/pwa/icon-') === 0;
  return isStatic || isIcon;
}

// Show the saved copy immediately, and quietly refresh it for next time.
function staleWhileRevalidate(event) {
  var request = event.request;
  return caches.open(CACHE).then(function (cache) {
    return cache.match(request).then(function (cached) {
      var refresh = fetch(request).then(function (response) {
        if (response && response.status === 200 && response.type === 'basic') {
          cache.put(request, response.clone());
        }
        return response;
      });
      if (cached) {
        event.waitUntil(refresh.catch(function () {}));   // keep the worker alive; ignore failures
        return cached;
      }
      return refresh;
    });
  });
}

self.addEventListener('fetch', function (event) {
  var request = event.request;

  // Only plain GET requests are ever handled. Form submissions (POST), login, logout and
  // everything else go straight to the server, exactly as if there were no service worker.
  if (request.method !== 'GET') { return; }
  if (request.headers.has('range')) { return; }          // video playback needs the browser's own handling

  var url = new URL(request.url);
  if (url.origin !== self.location.origin) { return; }   // third-party files are left to the browser

  // 1. Pages: always from the network. The offline page appears only if the network is unreachable
  //    (a server error such as 500 is NOT replaced; fetch() only fails when there is no connection).
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(function () {
        return caches.match(OFFLINE_URL, { cacheName: CACHE }).then(function (page) {
          return page || Response.error();
        });
      })
    );
    return;
  }

  // 2. Static files and app icons: safe to keep.
  if (isStaticFile(url)) {
    event.respondWith(staleWhileRevalidate(event));
  }

  // 3. Anything else (notification panel, photos, videos, exports ...): not touched.
});

// ---- Push notifications (unchanged) ----
self.addEventListener('push', function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }
  var title = data.title || 'QGS';
  event.waitUntil(self.registration.showNotification(title, {
    body: data.body || '',
    data: { url: data.url || '/' },
    dir: 'rtl',
    lang: 'fa'
  }));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var target = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
      for (var i = 0; i < list.length; i++) {
        if ('focus' in list[i]) {
          list[i].navigate(target);
          return list[i].focus();
        }
      }
      return self.clients.openWindow(target);
    })
  );
});
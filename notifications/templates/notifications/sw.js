// Runs in the background, even when no page of the site is open.
self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (event) { event.waitUntil(self.clients.claim()); });

self.addEventListener('push', function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = {}; }

  var options = {
    body: data.body || '',
    tag: data.tag,
    renotify: !!data.tag,
    dir: 'rtl',
    lang: 'fa',
    data: { url: data.url || '/' }
  };

  event.waitUntil(Promise.all([
    self.registration.showNotification(data.title || 'اعلان جدید', options),
    // Any open page refreshes its bell right away
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
      list.forEach(function (client) { client.postMessage({ type: 'notification-pushed' }); });
    })
  ]));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var target = new URL(event.notification.data.url, self.location.origin).href;
  event.waitUntil(self.clients.openWindow(target));
});
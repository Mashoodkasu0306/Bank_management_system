{% load static %}
/* Apex Core Banking service worker.
   It keeps only the CSS, JS and icons, plus one public offline page.
   It never stores pages, balances, transactions or uploaded documents. */
var CACHE = "apex-static-v1";
var DEV = {% if dev %}true{% else %}false{% endif %};
var OFFLINE_URL = "{% url 'pwa_offline' %}";
var STATIC_PREFIX = "{% static '' %}";
var PRECACHE = [
    OFFLINE_URL,
    "{% static 'css/app.css' %}",
    "{% static 'js/app.js' %}",
    "{% static 'pwa/icon-192.png' %}",
    "{% static 'pwa/icon-512.png' %}"
];

self.addEventListener("install", function (event) {
    event.waitUntil(
        caches.open(CACHE)
            .then(function (cache) { return cache.addAll(PRECACHE); })
            .then(function () { return self.skipWaiting(); })
    );
});

self.addEventListener("activate", function (event) {
    event.waitUntil(
        caches.keys()
            .then(function (keys) {
                return Promise.all(keys.filter(function (key) { return key !== CACHE; })
                    .map(function (key) { return caches.delete(key); }));
            })
            .then(function () { return self.clients.claim(); })
    );
});

self.addEventListener("fetch", function (event) {
    var request = event.request;
    if (request.method !== "GET") { return; }

    var url = new URL(request.url);
    if (url.origin !== self.location.origin) { return; }
    // Uploaded documents are private: never touch them.
    if (url.pathname.indexOf("/media/") === 0) { return; }

    // Pages always come from the server. Offline, show the public offline page.
    if (request.mode === "navigate") {
        event.respondWith(fetch(request).catch(function () { return caches.match(OFFLINE_URL); }));
        return;
    }

    if (url.pathname.indexOf(STATIC_PREFIX) !== 0) { return; }

    event.respondWith(caches.open(CACHE).then(function (cache) {
        if (DEV) {
            // While developing, always try the network first so edits show straight away.
            return fetch(request).then(function (response) {
                if (response && response.status === 200) { cache.put(request, response.clone()); }
                return response;
            }).catch(function () { return cache.match(request); });
        }
        return cache.match(request).then(function (cached) {
            var network = fetch(request).then(function (response) {
                if (response && response.status === 200) { cache.put(request, response.clone()); }
                return response;
            }).catch(function () { return cached; });
            return cached || network;
        });
    }));
});
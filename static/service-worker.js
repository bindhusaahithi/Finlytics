const CACHE_NAME = "finlytics-shell-v2";
const APP_SHELL = [
    "/",
    "/login",
    "/register",
    "/static/style.css",
    "/static/dashboard.css",
    "/static/app.js",
    "/static/manifest.json",
    "/static/app-icon.svg"
];

self.addEventListener("install", function(event) {
    self.skipWaiting();

    event.waitUntil(
        caches.open(CACHE_NAME).then(function(cache) {
            return cache.addAll(APP_SHELL);
        })
    );
});

self.addEventListener("activate", function(event) {
    event.waitUntil(
        caches.keys().then(function(keys) {
            return Promise.all(
                keys.map(function(key) {
                    if (key !== CACHE_NAME) {
                        return caches.delete(key);
                    }
                })
            );
        }).then(function() {
            return self.clients.claim();
        })
    );
});

self.addEventListener("fetch", function(event) {
    if (event.request.method !== "GET") {
        return;
    }

    event.respondWith(
        fetch(event.request).then(function(networkResponse) {
            if (
                event.request.url.startsWith(self.location.origin) &&
                event.request.method === "GET"
            ) {
                const responseClone = networkResponse.clone();

                caches.open(CACHE_NAME).then(function(cache) {
                    cache.put(event.request, responseClone);
                });
            }

            return networkResponse;
        }).catch(function() {
            return caches.match(event.request);
        })
    );
});

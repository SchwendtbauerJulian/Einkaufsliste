/* Service Worker: hält die App-Dateien vor, damit die App auch ohne Verbindung startet. */

const CACHE = "einkaufsliste-app-v3";
const ASSETS = ["index.html", "app.js", "app.css", "manifest.json", "icon-192.png", "icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// App-Dateien: sofort aus dem Cache, im Hintergrund aktualisieren.
// API-Aufrufe gehen nicht durch den Cache – die App merkt selbst, wenn sie offline ist.
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  const scope = new URL(self.registration.scope);
  if (event.request.method !== "GET" || url.origin !== scope.origin || !url.pathname.startsWith(scope.pathname)) {
    return;
  }
  const isPage = event.request.mode === "navigate";
  event.respondWith(
    caches.open(CACHE).then(async (cache) => {
      const key = isPage ? "index.html" : event.request;
      const cached = await cache.match(key, { ignoreSearch: true });
      const network = fetch(event.request)
        .then((response) => {
          if (response.ok) cache.put(key, response.clone());
          return response;
        })
        .catch(() => cached);
      if (cached) {
        event.waitUntil(network);
        return cached;
      }
      return network;
    })
  );
});

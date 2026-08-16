/* Priors service worker.
 * Shell: cache-first (bumped via VERSION).
 * data/index.json: network-first so the newest issue always appears.
 * data/<week>.json + images: stale-while-revalidate — visited issues read offline.
 */

const VERSION = "priors-v1";
const SHELL = ["./", "index.html", "style.css", "app.js", "manifest.webmanifest",
               "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET") return;

  // Latest-issue pointer: network first, cache fallback.
  if (url.pathname.endsWith("data/index.json")) {
    event.respondWith(
      fetch(event.request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(VERSION).then((c) => c.put(event.request, copy));
          return resp;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Same-origin everything else: cache first, refresh in background.
  if (url.origin === location.origin) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        const fetched = fetch(event.request)
          .then((resp) => {
            if (resp.ok) {
              const copy = resp.clone();
              caches.open(VERSION).then((c) => c.put(event.request, copy));
            }
            return resp;
          })
          .catch(() => cached);
        return cached || fetched;
      })
    );
  }
});

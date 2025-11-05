const CACHE_VERSION = "v1";
const CACHE_NAME = `mein-test-${CACHE_VERSION}`;
const CORE_ASSETS = [
  "index.html",
  "styles.css",
  "app.js",
  "cover-image.png",
  "manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_NAME);
    await cache.addAll(CORE_ASSETS);
    await cacheQuestionsAndImages(cache);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const cacheNames = await caches.keys();
    await Promise.all(
      cacheNames
        .filter((name) => name !== CACHE_NAME)
        .map((name) => caches.delete(name)),
    );
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const { request } = event;

  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  if (request.mode === "navigate") {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE_NAME);
        const cached = await cache.match("index.html");
        if (cached) {
          return cached;
        }
        return fetch(request);
      })(),
    );
    return;
  }

  if (url.origin !== self.location.origin) {
    return;
  }

  if (url.pathname === "/data/questions.json") {
    event.respondWith(networkFirst(request));
    return;
  }

  event.respondWith(
    cacheFirst(request),
  );
});

async function cacheQuestionsAndImages(cache) {
  const request = new Request("data/questions.json", { cache: "reload" });
  let response;
  try {
    response = await fetch(request);
  } catch (error) {
    console.warn("SW: Failed to fetch questions.json for caching", error);
    return;
  }

  if (!response || !response.ok) {
    return;
  }

  await cache.put(request, response.clone());

  let payload;
  try {
    payload = await response.clone().json();
  } catch (error) {
    console.warn("SW: Unable to parse questions.json", error);
    return;
  }

  const imagePaths = new Set();
  for (const question of payload.questions || []) {
    for (const relativePath of question.images || []) {
      imagePaths.add(`data/${relativePath}`);
    }
  }

  await Promise.all(
    Array.from(imagePaths).map(async (path) => {
      try {
        await cache.add(path);
      } catch (error) {
        console.warn("SW: Failed to cache", path, error);
      }
    }),
  );
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE_NAME);

  try {
    const response = await fetch(request);
    if (response && response.ok) {
      cache.put(request, response.clone()).catch(() => {});
    }
    return response;
  } catch (error) {
    const cached = await cache.match(request);
    if (cached) {
      return cached;
    }
    throw error;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request);
  if (cached) {
    return cached;
  }

  try {
    const response = await fetch(request);
    if (response && response.status === 200 && response.type === "basic") {
      cache.put(request, response.clone()).catch(() => {});
    }
    return response;
  } catch (error) {
    if (request.destination === "document") {
      const fallback = await cache.match("index.html");
      if (fallback) {
        return fallback;
      }
    }
    throw error;
  }
}

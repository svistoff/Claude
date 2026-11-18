/* Service worker AI Coder.
   Задача — чтобы приложение ставилось на рабочий стол и открывалось мгновенно,
   даже при плохой связи. Данные агента НЕ кэшируем: чат и история всегда свежие.

   {{V}} подставляет сервер (версия статики). Меняется фронт — меняется sw.js —
   браузер ставит новый воркер и выбрасывает старый кэш. */

const CACHE = "aicoder-{{V}}";
const SHELL = [
  "/",
  "/static/app.js?v={{V}}",
  "/static/styles.css?v={{V}}",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // Один недоступный файл не должен ломать установку целиком.
    await Promise.allSettled(SHELL.map((url) => cache.add(new Request(url, { cache: "reload" }))));
    self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("message", (event) => {
  if (event.data === "skip-waiting") self.skipWaiting();
});

const isApi = (url) => url.pathname.startsWith("/api/");
const isStatic = (url) => url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest";

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;                 // отправка задач — только сеть
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;  // чужой сервер (локальный режим) — не мешаем
  if (isApi(url)) return;                           // данные агента всегда с сервера

  // Открытие приложения: сначала сеть (чтобы подхватить новый код), иначе — оболочка.
  if (req.mode === "navigate") {
    event.respondWith((async () => {
      try {
        const fresh = await fetch(req);
        const cache = await caches.open(CACHE);
        cache.put("/", fresh.clone());
        return fresh;
      } catch (e) {
        const cached = await caches.match("/");
        if (cached) return cached;
        return new Response(
          "<!doctype html><meta charset=utf-8><title>Нет связи</title>" +
          "<body style=\"font:16px system-ui;padding:24px;background:#f0eee6;color:#141413\">" +
          "<h1>Нет связи</h1><p>Сервер не отвечает. Проверьте интернет и откройте приложение снова.</p>",
          { headers: { "Content-Type": "text/html; charset=utf-8" } });
      }
    })());
    return;
  }

  if (isStatic(url)) {
    // Статика: отдаём из кэша сразу, в фоне обновляем.
    event.respondWith((async () => {
      const cache = await caches.open(CACHE);
      const cached = await cache.match(req);
      const network = fetch(req).then((resp) => {
        if (resp && resp.ok) cache.put(req, resp.clone());
        return resp;
      }).catch(() => null);
      return cached || (await network) || Response.error();
    })());
  }
});

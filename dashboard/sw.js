// 서울 상권 펄스 PWA 서비스 워커.
// 화면(앱 셸)과 three.js·폰트는 저장해 두고 오프라인에서도 연다. B 분석 API(ngrok 등)와 /api, /health 는 건드리지 않는다.
const VERSION = 'pulse-v9';
const SHELL = ['./', './index.html', './manifest.webmanifest', './icon-192.png', './icon-512.png', './apple-touch-icon.png'];
const LIBS = [
  'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js',
  'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/shaders/CopyShader.js',
  'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/shaders/LuminosityHighPassShader.js',
  'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/EffectComposer.js',
  'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/RenderPass.js',
  'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/ShaderPass.js',
  'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/postprocessing/UnrealBloomPass.js',
  'https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/GLTFLoader.js',
];
const STATIC_HOSTS = ['cdnjs.cloudflare.com', 'cdn.jsdelivr.net', 'fonts.googleapis.com', 'fonts.gstatic.com'];

self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(VERSION);
    await c.addAll(SHELL);
    await Promise.all(LIBS.map((u) => c.add(u).catch(() => {}))); // 라이브러리는 실패해도 설치는 계속
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k !== VERSION) await caches.delete(k);
    await self.clients.claim();
  })());
});

async function fromNetwork(req, c) {
  const res = await fetch(req);
  if (res && (res.ok || res.type === 'opaque')) c.put(req, res.clone());
  return res;
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const same = url.origin === self.location.origin;
  if (same && (url.pathname.startsWith('/api') || url.pathname === '/health')) return;

  if (same && req.mode === 'navigate') { // 화면: 새 버전 우선, 오프라인이면 저장본
    e.respondWith((async () => {
      const c = await caches.open(VERSION);
      try { return await fromNetwork(req, c); }
      catch { return (await c.match(req, { ignoreSearch: true })) || (await c.match('./index.html')); }
    })());
    return;
  }
  if (same || STATIC_HOSTS.includes(url.hostname)) { // 정적 파일: 저장본 먼저, 뒤에서 갱신
    e.respondWith((async () => {
      const c = await caches.open(VERSION);
      const hit = await c.match(req);
      const net = fromNetwork(req, c).catch(() => hit);
      return hit || net;
    })());
  }
  // 그 밖의 주소(B 분석 API 등)는 그대로 네트워크로 보낸다
});

/* Ajudante do app (service worker) do painel do Diagnóstico da EEQ.

   Regra única: "internet primeiro, cópia guardada como reserva".
   - Com internet: busca a versão mais nova (os dados mudam 3x por dia e a cada
     resposta do formulário) e guarda uma cópia.
   - Sem internet: abre a última cópia guardada, para o painel funcionar em
     lugares com sinal fraco.
   Só guarda a própria página e as bibliotecas de gráfico e mapa; os pedaços do
   mapa (fundo) e o VLibras precisam de internet. */
const CACHE = 'painel-eeq-v1';
const BIBLIOTECAS = ['cdn.jsdelivr.net', 'cdnjs.cloudflare.com'];

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(
  caches.keys()
    .then(nomes => Promise.all(nomes.filter(n => n !== CACHE).map(n => caches.delete(n))))
    .then(() => self.clients.claim())
));

self.addEventListener('fetch', e => {
  const pedido = e.request;
  if (pedido.method !== 'GET') return;
  const url = new URL(pedido.url);
  if (url.origin !== self.location.origin && !BIBLIOTECAS.includes(url.hostname)) return;
  const ehPagina = pedido.mode === 'navigate';
  const chave = ehPagina ? new Request(self.registration.scope) : pedido;

  e.respondWith(
    fetch(pedido)
      .then(resposta => {
        // as bibliotecas vêm de outro endereço e chegam "opacas" (o navegador
        // não deixa ler o conteúdo, mas deixa guardar e reusar)
        if (resposta.ok || resposta.type === 'opaque') {
          const copia = resposta.clone();
          caches.open(CACHE).then(c => c.put(chave, copia));
        }
        return resposta;
      })
      .catch(() => caches.match(chave).then(guardada => guardada || Response.error()))
  );
});

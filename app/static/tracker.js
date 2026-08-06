(() => {
  // HttpOnly session cookies are intentionally invisible to JavaScript.
  const queue = [], started = performance.now();
  const add = (event_type, data={}) => queue.push({event_id: crypto.randomUUID(), event_type, occurred_at: new Date().toISOString(), metadata: {}, ...data});
  const flush = () => {
    if (!queue.length) return;
    const body = JSON.stringify({events: queue.splice(0, 50)});
    fetch('/api/events', {method:'POST', headers:{'Content-Type':'application/json'}, body, keepalive:true}).catch(() => {});
  };

  const filterCatalog = (query) => {
    const q = (query || '').trim().toLowerCase();
    document.querySelectorAll('[data-product-id]').forEach(card => {
      const hay = `${card.dataset.searchText || card.textContent || ''}`.toLowerCase();
      card.hidden = Boolean(q) && !hay.includes(q);
    });
  };

  add('page_view', {metadata:{path: location.pathname}});
  document.querySelectorAll('[data-product-id]').forEach(card => {
    const id = Number(card.dataset.productId);
    if (!card.dataset.searchText) {
      card.dataset.searchText = card.textContent || '';
    }
    new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) add('product_view', {product_id:id}); }, {threshold:.6}).observe(card);
    card.querySelector('.view-product')?.addEventListener('click', () => add('product_click', {product_id:id}));
  });

  const searchForm = document.querySelector('#search');
  const searchInput = document.querySelector('#search-input');
  searchForm?.addEventListener('submit', e => {
    e.preventDefault();
    const query = (searchInput?.value || '').trim();
    if (query) add('search', {query});
    filterCatalog(query);
    flush();
  });
  searchInput?.addEventListener('input', () => filterCatalog(searchInput.value));

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      add('dwell', {dwell_ms: Math.round(performance.now() - started), metadata:{path: location.pathname}});
      flush();
    }
  });
  setInterval(() => {
    flush();
    fetch('/api/recommendations/refresh', {method:'POST'}).catch(() => {});
  }, 15000);
  addEventListener('pagehide', flush);
})();

// ============================================================
// tool-history.js — saved items for the Jackson AI tools
// (lesson plans, schemes of work, exams, summary notes)
//
// Every item a teacher generates is saved under their account (email) on the device
// and synced to the cloud, so "My saved ..." shows the same list on phone and computer.
//
// Use on a tool page:
//   <script src="tool-history.js"></script>
//   var H = JaiHistory.attach({ kind, label, title(data), restore(data) });
//   H.save(holderObject, data)   // holderObject keeps a hidden id so edits update the same item
// ============================================================
(function () {
  var CLOUD = 'https://chem-payment.hajackson2020.workers.dev/chats';

  function token() { try { return localStorage.getItem('teacher_token') || ''; } catch (e) { return ''; } }
  function who() {
    try {
      var w = (localStorage.getItem('teacher_email') || localStorage.getItem('teacher_name') || 'guest').trim().toLowerCase();
      return (w.replace(/[^a-z0-9@._-]+/g, '_').slice(0, 60)) || 'guest';
    } catch (e) { return 'guest'; }
  }
  function newId() { return 'h_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8); }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function byNewest(a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); }

  var cssDone = false;
  function addCss() {
    if (cssDone) return; cssDone = true;
    var s = document.createElement('style');
    s.textContent =
      '.jh-bar{margin:0 0 14px;display:flex;justify-content:flex-end}' +
      '.jh-open{background:#161b22;color:#e6edf3;border:1px solid #30363d;border-radius:10px;padding:10px 16px;font-size:.88rem;font-weight:600;cursor:pointer;font-family:inherit}' +
      '.jh-open:hover{border-color:#38bdf8;color:#38bdf8}' +
      '.jh-ov{position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:10000;display:none;align-items:center;justify-content:center;padding:16px}' +
      '.jh-ov.on{display:flex}' +
      '.jh-box{background:#161b22;border:1px solid #30363d;border-radius:14px;width:100%;max-width:560px;max-height:84vh;display:flex;flex-direction:column;color:#e6edf3;font-family:Arial,sans-serif}' +
      '.jh-hd{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;border-bottom:1px solid #30363d}' +
      '.jh-hd h3{font-size:1.02rem;margin:0}' +
      '.jh-x{background:none;border:none;color:#8b949e;font-size:1.3rem;cursor:pointer;line-height:1}' +
      '.jh-list{overflow:auto;padding:10px 12px 14px}' +
      '.jh-empty{color:#8b949e;font-size:.88rem;text-align:center;padding:26px 10px;line-height:1.6}' +
      '.jh-row{display:flex;align-items:center;gap:10px;padding:11px 10px;border-radius:10px;border:1px solid #30363d;margin-bottom:8px;background:#1c2333}' +
      '.jh-info{flex:1;min-width:0;cursor:pointer}' +
      '.jh-t{font-size:.9rem;font-weight:600;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}' +
      '.jh-d{font-size:.74rem;color:#8b949e;margin-top:2px}' +
      '.jh-go{background:#38bdf8;color:#0d1117;border:none;border-radius:8px;padding:7px 13px;font-weight:700;font-size:.8rem;cursor:pointer}' +
      '.jh-del{background:none;border:1px solid #30363d;color:#f87171;border-radius:8px;padding:6px 9px;font-size:.8rem;cursor:pointer}';
    document.head.appendChild(s);
  }

  window.JaiHistory = {
    attach: function (cfg) {
      // keys are worked out at the moment of use, because a teacher can sign in after the page has loaded
      function K() { return 'jai_hist_' + cfg.kind + '_' + who(); }
      function DK() { return K() + '_deleted'; }
      var restoring = false, timer = null, syncing = false, again = false, btn = null, ov = null, list = null;

      function read() { try { var a = JSON.parse(localStorage.getItem(K()) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; } }
      function write(arr) { try { localStorage.setItem(K(), JSON.stringify(arr)); return true; } catch (e) { return false; } }
      function readDel() {
        try {
          var o = JSON.parse(localStorage.getItem(DK()) || '{}'), cut = Date.now() - 30 * 86400000;
          Object.keys(o).forEach(function (k) { if (o[k] < cut) delete o[k]; });
          return o;
        } catch (e) { return {}; }
      }
      function markDel(ids) {
        var o = readDel(), now = Date.now();
        ids.forEach(function (id) { o[id] = now; });
        try { localStorage.setItem(DK(), JSON.stringify(o)); } catch (e) {}
        schedule(400);
      }

      function save(holder, data) {
        if (restoring || !holder || typeof holder !== 'object') return;
        var id = holder._hid;
        if (!id || readDel()[id]) { id = newId(); holder._hid = id; } // new item, or the old one was deleted: start a new record
        var title = '';
        try { title = cfg.title(data) || ''; } catch (e) {}
        title = String(title || 'Saved item').replace(/\s+/g, ' ').trim().slice(0, 120);
        var rec;
        try { rec = { id: id, title: title, updatedAt: Date.now(), data: JSON.parse(JSON.stringify(data)) }; } catch (e) { return; }
        var items = read(), i = items.findIndex(function (x) { return x.id === id; });
        if (i >= 0) items[i] = rec; else items.unshift(rec);
        items.sort(byNewest);
        items = items.slice(0, 100);
        while (!write(items) && items.length > 3) items = items.slice(0, Math.floor(items.length * 0.8)); // device storage full: keep the newest
        refresh();
        schedule(2000);
      }

      // ---- screen: a button above the form + a list of saved items ----
      function build() {
        var host = document.getElementById('form-wrap');
        if (!host || btn) return;
        addCss();
        var bar = document.createElement('div');
        bar.className = 'jh-bar';
        btn = document.createElement('button');
        btn.type = 'button'; btn.className = 'jh-open';
        btn.addEventListener('click', openList);
        bar.appendChild(btn);
        host.insertBefore(bar, host.firstChild);

        ov = document.createElement('div');
        ov.className = 'jh-ov';
        ov.innerHTML = '<div class="jh-box"><div class="jh-hd"><h3></h3><button type="button" class="jh-x" aria-label="Close">&times;</button></div><div class="jh-list"></div></div>';
        document.body.appendChild(ov);
        list = ov.querySelector('.jh-list');
        ov.querySelector('h3').textContent = 'My saved ' + cfg.label;
        ov.querySelector('.jh-x').addEventListener('click', closeList);
        ov.addEventListener('click', function (e) { if (e.target === ov) closeList(); });
        refresh();
      }
      function refresh() {
        if (btn) btn.textContent = '📚 My saved ' + cfg.label + ' (' + read().length + ')';
        if (ov && ov.classList.contains('on')) renderList();
      }
      function when(ts) {
        var d = new Date(ts);
        return d.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' }) + ' · ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      }
      function renderList() {
        var items = read().sort(byNewest);
        if (!items.length) {
          list.innerHTML = '<div class="jh-empty">Nothing saved yet.<br>Every ' + esc(cfg.single || 'item') + ' you generate is saved here automatically, and shows on any phone or computer where you sign in with the same email.</div>';
          return;
        }
        list.innerHTML = '';
        items.forEach(function (it) {
          var row = document.createElement('div'); row.className = 'jh-row';
          var info = document.createElement('div'); info.className = 'jh-info';
          info.innerHTML = '<div class="jh-t">' + esc(it.title) + '</div><div class="jh-d">' + esc(when(it.updatedAt)) + '</div>';
          info.addEventListener('click', function () { openItem(it.id); });
          var go = document.createElement('button'); go.type = 'button'; go.className = 'jh-go'; go.textContent = 'Open';
          go.addEventListener('click', function () { openItem(it.id); });
          var del = document.createElement('button'); del.type = 'button'; del.className = 'jh-del'; del.textContent = '✕'; del.setAttribute('aria-label', 'Delete');
          del.addEventListener('click', function () {
            if (!confirm('Delete this saved ' + (cfg.single || 'item') + (token() ? ' from your account on all devices' : '') + '?')) return;
            markDel([it.id]);
            write(read().filter(function (x) { return x.id !== it.id; }));
            refresh();
          });
          row.appendChild(info); row.appendChild(go); row.appendChild(del);
          list.appendChild(row);
        });
      }
      function openList() { renderList(); ov.classList.add('on'); sync(); }
      function closeList() { ov.classList.remove('on'); }
      function openItem(id) {
        var it = read().find(function (x) { return x.id === id; });
        if (!it) return;
        restoring = true; // showing an old item must not count as a new save
        try {
          cfg.restore(JSON.parse(JSON.stringify(it.data)));
          var f = document.getElementById('form-wrap'), o = document.getElementById('out-wrap');
          if (f) f.style.display = 'none';
          if (o) o.style.display = 'block';
        } catch (e) {
          alert('Sorry, this saved ' + (cfg.single || 'item') + ' could not be opened.');
        } finally { restoring = false; }
        closeList();
        window.scrollTo(0, 0);
      }

      // ---- cloud sync ----
      function schedule(delay) {
        if (!token()) return;
        clearTimeout(timer);
        timer = setTimeout(sync, delay === undefined ? 2000 : delay);
      }
      function sync() {
        if (!token()) return Promise.resolve();
        if (syncing) { again = true; return Promise.resolve(); }
        syncing = true;
        var del = readDel();
        return fetch(CLOUD, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Teacher-Token': token() },
          body: JSON.stringify({ kind: cfg.kind, chats: read().filter(function (x) { return !del[x.id]; }), deleted: Object.keys(del) })
        }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
          if (!d || !Array.isArray(d.chats)) return; // cloud not ready or signed out: everything stays on this device
          if (Array.isArray(d.deleted) && d.deleted.length) {
            var o = readDel(), now = Date.now();
            d.deleted.forEach(function (id) { if (typeof id === 'string' && !o[id]) o[id] = now; });
            try { localStorage.setItem(DK(), JSON.stringify(o)); } catch (e) {}
          }
          var nowDel = readDel(), map = {};
          read().forEach(function (x) { if (!nowDel[x.id]) map[x.id] = x; });
          d.chats.forEach(function (c) {
            if (!c || !c.id || !c.data || nowDel[c.id]) return;
            if (!map[c.id] || (c.updatedAt || 0) > (map[c.id].updatedAt || 0)) map[c.id] = c;
          });
          write(Object.keys(map).map(function (k) { return map[k]; }).sort(byNewest).slice(0, 100));
          refresh();
        }).catch(function () { /* offline: tries again on the next save */ })
          .then(function () { syncing = false; if (again) { again = false; schedule(500); } });
      }

      build();
      sync();
      document.addEventListener('visibilitychange', function () { if (document.visibilityState === 'visible') sync(); });
      // right after the email login the list switches to that account's items
      window.addEventListener('jai-login', function () { refresh(); sync(); });

      return { save: save, open: openItem, sync: sync };
    }
  };
})();

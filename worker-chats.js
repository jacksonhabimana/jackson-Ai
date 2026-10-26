// ============================================================
// worker-chats.js — cloud storage for Jackson AI: chat history AND saved tool items
// (lesson plans, schemes of work, exams, summary notes)
//
// Add this to the chem-payment Worker (Cloudflare dashboard → Workers & Pages →
// chem-payment → Edit code), then:
//   1. Create a KV namespace (Storage & Databases → KV → Create, name it JAI_CHATS)
//   2. Worker → Settings → Bindings → Add → KV namespace → variable name: JAI_CHATS
//   3. Inside the Worker's fetch handler, add near the other routes:
//        if (path === '/chats') return handleChats(request, env);
//      (and make sure the OPTIONS/CORS reply allows the X-Teacher-Token header —
//       the lesson-plan and scheme pages already send it, so it probably does)
//
// The browser sends: POST /chats  { kind, chats:[...], deleted:[ids] }
//   kind = 'chat' (Jackson AI chat) or 'lesson-plan' | 'scheme' | 'exam' | 'notes'
// and receives the merged list: { chats:[...], deleted:[ids] }.
// Each account has ONE record per kind, found from the login token — a person can
// never read another person's items.
// ============================================================

const CHATS_MAX = 300;            // items kept per account and kind
const CHATS_MAX_BYTES = 20 * 1024 * 1024; // KV values can be up to 25 MB
const TOMBSTONE_DAYS = 60;        // how long a deleted id is remembered so other devices can drop it

// TODO: must return the account's email/username for a valid login token, or null.
// Use exactly the same check the Worker already uses for /teachers/* and the generators
// (the X-Teacher-Token header). Until this is filled in, /chats answers 401 and
// everything simply stays on the device — nothing breaks.
async function chatUserFromToken(token, env) {
  return null;
}

function chatsJson(data, status, request) {
  return new Response(JSON.stringify(data), {
    status: status || 200,
    headers: {
      'Content-Type': 'application/json',
      'Access-Control-Allow-Origin': request.headers.get('Origin') || '*',
      'Access-Control-Allow-Headers': 'Content-Type, X-Teacher-Token',
      'Access-Control-Allow-Methods': 'POST, OPTIONS',
      'Vary': 'Origin'
    }
  });
}

async function handleChats(request, env) {
  if (request.method === 'OPTIONS') return chatsJson({}, 204, request);
  if (request.method !== 'POST') return chatsJson({ error: 'method' }, 405, request);

  const user = await chatUserFromToken(request.headers.get('X-Teacher-Token') || '', env);
  if (!user) return chatsJson({ error: 'auth' }, 401, request);

  let body;
  try { body = await request.json(); } catch (e) { return chatsJson({ error: 'bad json' }, 400, request); }
  const kind = body.kind === undefined ? 'chat' : String(body.kind);
  if (!/^[a-z][a-z-]{0,29}$/.test(kind)) return chatsJson({ error: 'bad kind' }, 400, request);
  const isChat = kind === 'chat';
  const incoming = Array.isArray(body.chats) ? body.chats : [];
  const incomingDeleted = Array.isArray(body.deleted) ? body.deleted.filter(x => typeof x === 'string').slice(0, 2000) : [];

  const key = (isChat ? 'chats:' : 'hist:' + kind + ':') + String(user).trim().toLowerCase();
  let rec = { chats: [], deleted: {} };
  try { const raw = await env.JAI_CHATS.get(key); if (raw) rec = JSON.parse(raw); } catch (e) {}
  if (!Array.isArray(rec.chats)) rec.chats = [];
  if (!rec.deleted || typeof rec.deleted !== 'object') rec.deleted = {};

  const now = Date.now();
  incomingDeleted.forEach(id => { if (!rec.deleted[id]) rec.deleted[id] = now; });
  Object.keys(rec.deleted).forEach(id => { if (now - rec.deleted[id] > TOMBSTONE_DAYS * 86400000) delete rec.deleted[id]; });

  const byId = new Map();
  rec.chats.forEach(c => { if (c && c.id && !rec.deleted[c.id]) byId.set(c.id, c); });
  incoming.forEach(c => {
    if (!c || typeof c.id !== 'string' || rec.deleted[c.id]) return;
    if (isChat ? !Array.isArray(c.messages) : (!c.data || typeof c.data !== 'object')) return;
    const mine = byId.get(c.id);
    if (!mine || (c.updatedAt || 0) > (mine.updatedAt || 0)) {
      const item = { id: c.id, title: String(c.title || (isChat ? 'New chat' : 'Saved item')).slice(0, 120), updatedAt: Number(c.updatedAt) || now };
      if (isChat) item.messages = c.messages; else item.data = c.data;
      byId.set(c.id, item);
    }
  });

  let chats = Array.from(byId.values()).sort((a, b) => b.updatedAt - a.updatedAt).slice(0, CHATS_MAX);
  let out = JSON.stringify({ chats, deleted: rec.deleted });
  while (out.length > CHATS_MAX_BYTES && chats.length > 1) { // too big: drop the oldest items
    chats = chats.slice(0, Math.floor(chats.length * 0.9));
    out = JSON.stringify({ chats, deleted: rec.deleted });
  }
  await env.JAI_CHATS.put(key, out);
  return chatsJson({ chats, deleted: Object.keys(rec.deleted) }, 200, request);
}

/* work.js — Work Map: cây rẽ nhánh việc đang mở (/work).
   Nguồn chân lý + luật phân loại nằm trong vault (Vault Operation/Work Map);
   module này CHỈ vẽ — không tự suy diễn thứ tự, không hard-code danh sách việc.
   Bố cục: mỗi nhóm đọc từ trên xuống, chỉ vẽ các tầng còn việc đang hiển thị.
   Node là HTML (CSS lo wrap/scroll), mũi tên vẽ bằng SVG SAU khi
   layout xong — đo bằng getBoundingClientRect nên phải chờ 1 khung hình. */
import { $, esc, byId, focusInto, restoreFocus } from './state.js';
import { tr } from './i18n.js';
import { wsOpen } from './workspace.js';

let DB = null;              // dữ liệu /work lần fetch gần nhất
let readyOnly = false;      // bộ lọc "chỉ việc làm ngay được"

const BUCKET_LABEL = {
  ready: 'work.ready',
  waiting_dep: 'work.waiting',
  waiting_gate: 'work.blocked',
  closed: 'work.closed',
};

/* Note nguồn của một việc -> node trên graph (mở được bằng Reader).
   byId khoá theo đường dẫn; vault đổi cấu trúc thì fallback so stem. */
function nodeForNote(p) {
  if (!p) return null;
  const direct = byId.get(p);
  if (direct) return direct;
  const stem = p.split('/').pop().replace(/\.md$/i, '');
  for (const node of byId.values()) {
    if (node.kind === 'note' && node.stem === stem) return node;
  }
  return null;
}

function gateText(d) {
  return (d.blocking_gates || [])
    .map(g => (DB.gates[g] || {}).desc || g).join(' · ');
}

function nodeHtml(d) {
  const bits = [];
  if (d.unblocks) bits.push(tr('work.unblocks', { n: d.unblocks }));
  if (d.bucket === 'waiting_dep') bits.push(tr('work.needs', { list: (d.unmet_codes || d.unmet).join(', ') }));
  if (d.bucket === 'waiting_gate') bits.push(gateText(d));
  const agent = d.agent_label || d.agent || '—';
  bits.unshift(`Agent: ${agent}`);
  // Mã ngắn là thứ người dùng gọi tên khi giao việc — cho vào tooltip luôn
  const tip = [`${d.code || ''} · ${d.priority || 'P?'}`, d.why || '', bits.join(' · ')]
    .filter(Boolean).join('\n');
  const note = (d.source || {}).note || '';
  return `<button class="wm-node b-${d.bucket}" data-id="${esc(d.id)}" data-note="${esc(note)}"
      title="${esc(tip)}">
    <span class="wm-code">${esc(d.code || '—')}</span>
    <span class="wm-p">${esc(d.priority || 'P?')}</span>
    <span class="wm-p wm-agent" title="Agent">${esc(agent)}</span>
    <span class="wm-t">${esc(d.title)}</span>
    ${d.unblocks ? `<span class="wm-u" title="${tr('work.unblocks.tip', { n: d.unblocks })}">⛓${d.unblocks}</span>` : ''}
  </button>`;
}

function render() {
  const shown = DB.items.filter(d => d.bucket !== 'closed' && (!readyOnly || d.bucket === 'ready'));
  const c = DB.counts || {};
  $('wm-sum').innerHTML =
    tr('work.total', { n: `<b>${(c.ready || 0) + (c.waiting_dep || 0) + (c.waiting_gate || 0)}</b>` }) + ' · ' +
    `<span class="b-ready">${c.ready || 0} ${tr('work.ready')}</span> · ` +
    `<span class="b-waiting_dep">${c.waiting_dep || 0} ${tr('work.waiting')}</span> · ` +
    `<span class="b-waiting_gate">${c.waiting_gate || 0} ${tr('work.blocked')}</span> · ` +
    `${c.closed || 0} ${tr('work.closed')} · 🖥 ${esc(DB.host || '')}`;

  let html = '';
  for (const g of DB.groups) {
    const mine = shown.filter(d => d.group === g.id);
    if (!mine.length) continue;
    html += `<div class="wm-band"><div class="wm-bh">${esc(g.title)}</div><div class="wm-cols">`;
    // Closed ancestors may give the first visible task a high layer. Never
    // reserve blank space for hidden tasks, including in the ready-only view.
    const layers = [...new Set(mine.map(d => d.layer || 0))].sort((a, b) => a - b);
    for (const L of layers) {
      const col = mine.filter(d => (d.layer || 0) === L);
      html += `<div class="wm-col">${col.map(nodeHtml).join('')}</div>`;
    }
    html += '</div></div>';
  }
  if (!html) html = `<div class="wm-empty">${tr('work.filter.empty')}</div>`;
  $('wm-graph').innerHTML = `<svg id="wm-edges"></svg>${html}`;

  $('wm-graph').querySelectorAll('.wm-node').forEach(el => {
    el.onclick = () => {
      const node = nodeForNote(el.dataset.note);
      if (!node) return;
      closeWorkMap();
      wsOpen(node);
    };
  });
  // Layout xong mới đo được toạ độ — vẽ mũi tên ở nhịp kế tiếp.
  // Tab/pane ẩn thì rAF DỪNG HẲN (không phải chậm) → mũi tên sẽ không bao giờ vẽ;
  // setTimeout vẫn chạy, và getBoundingClientRect lúc ẩn vẫn trả layout đúng.
  if (document.hidden) setTimeout(drawEdges, 0);
  else requestAnimationFrame(drawEdges);
}

function drawEdges() {
  const svg = document.getElementById('wm-edges');
  const wrap = $('wm-graph');
  if (!svg || !wrap) return;
  const base = wrap.getBoundingClientRect();
  const pos = new Map();
  wrap.querySelectorAll('.wm-node').forEach(el => {
    const r = el.getBoundingClientRect();
    pos.set(el.dataset.id, {
      x: r.left - base.left + wrap.scrollLeft + r.width / 2,
      y1: r.top - base.top + wrap.scrollTop,
      y2: r.bottom - base.top + wrap.scrollTop,
    });
  });
  const paths = [];
  for (const d of DB.items) {
    const to = pos.get(d.id);
    if (!to) continue;
    for (const dep of d.depends || []) {
      const from = pos.get(dep);
      if (!from) continue;
      const my = (from.y2 + to.y1) / 2;
      paths.push(`<path d="M${from.x} ${from.y2} C${from.x} ${my} ${to.x} ${my} ${to.x} ${to.y1}"/>`);
    }
  }
  // Reset old SVG dimensions before measuring: a previous wide/tall layout
  // must not keep its own scroll extent alive after resize or filtering.
  svg.innerHTML = '';
  svg.setAttribute('width', '0');
  svg.setAttribute('height', '0');
  svg.setAttribute('width', wrap.clientWidth);
  svg.setAttribute('height', wrap.scrollHeight);
  svg.innerHTML =
    '<defs><marker id="wm-ar" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">' +
    '<path d="M0 0 L8 4 L0 8 z" fill="var(--cyan)"/></marker></defs>' + paths.join('');
}

export async function openWorkMap() {
  $('workmap').classList.add('show');
  focusInto($('wm-box'), '#wm-ready');
  if (!DB) $('wm-graph').innerHTML = `<div class="wm-empty">${tr('work.loading2')}</div>`;
  try {
    const r = await fetch('/work', { cache: 'no-store' });
    if (r.status === 404) {
      $('wm-sum').textContent = '';
      $('wm-graph').innerHTML = `<div class="wm-empty">${tr('work.none.long')} ` +
        `(<code>Vault Operation/Work Map</code>).</div>`;
      return;
    }
    if (!r.ok) throw new Error('HTTP ' + r.status);
    DB = await r.json();
    render();
  } catch (e) {
    $('wm-graph').innerHTML = `<div class="wm-empty">${tr('work.err', { e: esc(String(e)) })}</div>`;
  }
}

export function closeWorkMap() { $('workmap').classList.remove('show'); restoreFocus(); }

export function initWorkMap() {
  $('wm-open').onclick = () => openWorkMap();
  $('wm-x').onclick = closeWorkMap;
  $('workmap').onclick = ev => { if (ev.target === $('workmap')) closeWorkMap(); };  // click nền mờ = đóng
  $('wm-ready').onclick = () => {
    readyOnly = !readyOnly;
    $('wm-ready').classList.toggle('on', readyOnly);
    if (DB) render();
  };
  // Esc bắt ở pha capture: modal chồng modal (switcher/dash) không cướp phím
  document.addEventListener('keydown', ev => {
    if (ev.key === 'Escape' && $('workmap').classList.contains('show')) {
      ev.stopPropagation();
      closeWorkMap();
    }
  }, true);
  window.addEventListener('resize', () => { if (DB && $('workmap').classList.contains('show')) drawEdges(); });
}

/* Số tóm tắt cho section trong panel — gọi lúc boot, không mở overlay. */
export async function pollWorkCount() {
  try {
    const r = await fetch('/work', { cache: 'no-store' });
    if (!r.ok) { $('wm-mini').textContent = tr('work.none'); return; }
    DB = await r.json();
    const c = DB.counts || {};
    $('wm-mini').innerHTML = tr('work.mini', { n: `<b>${c.ready || 0}</b>` }) + ' · ' +
      tr('work.mini.waiting', { n: (c.waiting_dep || 0) + (c.waiting_gate || 0) });
  } catch (e) {
    $('wm-mini').textContent = tr('work.mini.err');
  }
}

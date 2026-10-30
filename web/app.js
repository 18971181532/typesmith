/* TypeSmith 工作台前端。
 *
 * 没有框架、没有打包器：状态就是一个对象，改了就重画当前面板。
 * 所有像素都由服务端那套引擎画出来，浏览器只负责显示和收集参数——
 * 这样才能保证"网页里看到的"和"命令行导出的"是同一张图。
 */

(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const $$ = (sel) => Array.from(document.querySelectorAll(sel));

  const state = {
    tab: 'specimen',
    width: 900,
    height: 1180,
    size: 15,
    leading: 1.6,
    measure: 380,
    tolerance: 4,
    margin: 84,
    justify: true,
    page: 0,
    pages: 1,
    font: '',
    text: '',
  };

  const DEFAULT_TEXT = [
    'Typographic quality is mostly invisible. Nobody notices a page that breaks well,',
    'but everybody feels a page that breaks badly: a line stretched until the words',
    'float apart, a paragraph with a single orphan word at the top, a column where one',
    'gap is three times wider than its neighbours. TypeSmith keeps every feasible',
    'breakpoint, scores each line with a cubic badness, and picks the whole paragraph',
    'by total demerits instead of by a greedy scan.',
    '',
    '# 断行不是把字塞进框里',
    '',
    '汉字之间没有空格，断行只能落在字与字之间；标点不能出现在行首，前引号不能留在行尾。',
    '把这些规则做成字符集合，在生成段落项流时就把不合法的断点抹掉，而不是先断行再回退修补。',
    '',
    'Knuth–Plass 把整段当成一张图：每个可行断点是节点，行内胶的伸缩量是边的代价，',
    '求一次最短路就得到全局最省的一组断点。',
  ].join('\n');

  /* ------------------------------------------------------------- 工具 */

  const statusEl = $('status');
  let busy = 0;

  function setStatus(text, isBusy) {
    statusEl.textContent = text;
    statusEl.classList.toggle('busy', !!isBusy);
  }

  function begin(text) {
    busy += 1;
    setStatus(text, true);
  }

  function end(text) {
    busy = Math.max(0, busy - 1);
    if (busy === 0) setStatus(text || '就绪', false);
  }

  function debounce(fn, ms) {
    let timer = 0;
    return (...args) => {
      clearTimeout(timer);
      timer = setTimeout(() => fn(...args), ms);
    };
  }

  const fmt = (n) => Number(n).toLocaleString('en-US');

  async function post(path, body, signal) {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    });
    if (!res.ok) {
      let msg = res.statusText;
      try {
        const data = await res.json();
        if (data && data.error) msg = data.error;
      } catch (_) { /* 非 JSON 错误就沿用状态文本 */ }
      throw new Error(msg);
    }
    return res;
  }

  /* 图片请求：同一个 <img> 上一个 blob 必须释放，否则拖滑块会把内存吃干 */
  const views = new Map();

  async function loadImage(imgEl, path, body, key) {
    const prev = views.get(key);
    const ctrl = new AbortController();
    if (prev && prev.ctrl) prev.ctrl.abort();
    views.set(key, { ctrl, url: prev ? prev.url : null });
    try {
      const res = await post(path, body, ctrl.signal);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const old = views.get(key);
      imgEl.src = url;
      imgEl.dataset.url = url;
      if (old && old.url) URL.revokeObjectURL(old.url);
      views.set(key, { ctrl: null, url });
      return { url, size: blob.size };
    } catch (err) {
      if (err.name === 'AbortError') return null;
      throw err;
    }
  }

  /* --------------------------------------------------------- 参数收集 */

  function payload(extra) {
    const body = Object.assign({
      text: state.text,
      size: state.size,
      leading: state.leading,
      measure: state.tab === 'pages' ? 0 : state.measure,
      margin: state.margin,
      align: state.justify ? 'justify' : 'left',
      tolerance: state.tolerance,
      pageWidth: state.width,
      pageHeight: state.height,
      page: state.page,
    }, extra || {});
    if (state.font) body.font = state.font;
    return body;
  }

  /* ------------------------------------------------------------ 渲染 */

  async function drawSpecimen() {
    begin('栅格化样张…');
    try {
      const out = await loadImage($('img-specimen'), '/api/specimen',
        { width: state.width, height: state.height, font: state.font }, 'specimen');
      if (out) {
        setStatus(`样张 ${state.width}×${state.height} · ${(out.size / 1024).toFixed(0)} kB`);
      }
    } catch (err) {
      setStatus('样张失败：' + err.message);
    } finally {
      end();
    }
  }

  function ratioClass(r) {
    const abs = Math.abs(r);
    if (abs > 1.6) return 'bad';
    if (abs > 0.75) return 'loose';
    if (r < -0.15) return 'tight';
    return 'ok';
  }

  async function drawBreaks() {
    begin('求解最短路…');
    try {
      const res = await post('/api/layout', payload());
      const data = await res.json();
      const t = data.totals;
      const drop = t.greedy_demerits > 0
        ? (1 - t.demerits / t.greedy_demerits) * 100 : 0;

      $('totals').innerHTML = [
        ['行数', fmt(t.lines), ''],
        ['总 demerits', fmt(Math.round(t.demerits)), ''],
        ['贪心 demerits', fmt(Math.round(t.greedy_demerits)), ''],
        ['降低', drop.toFixed(1) + '%', drop > 0 ? 'good' : ''],
        ['最松 ratio', t.max_ratio.toFixed(2), t.max_ratio > 1.6 ? 'bad' : ''],
        ['超松行', String(t.loose), t.loose ? 'bad' : 'good'],
      ].map(([k, v, cls]) =>
        `<div class="cell"><span class="k">${k}</span><span class="v ${cls}">${v}</span></div>`
      ).join('');

      const scale = Math.max(2.4, t.max_ratio);
      $('lines').innerHTML = data.lines.map((ln) => {
        const cls = ratioClass(ln.ratio);
        const w = Math.min(100, (Math.abs(ln.ratio) / scale) * 100);
        const text = ln.text.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
        return `<div class="line ${cls}">
          <span class="no">${ln.i}</span>
          <span class="ratio">${ln.ratio >= 0 ? '+' : ''}${ln.ratio.toFixed(2)}</span>
          <span class="body"><span class="txt" title="${text}">${text}</span>
            <span class="bar"><i style="width:${w.toFixed(1)}%"></i></span></span>
        </div>`;
      }).join('');

      setStatus(`${data.font} · ${t.lines} 行 · 版心 ${Math.round(data.measure)} px`);
    } catch (err) {
      setStatus('断行失败：' + err.message);
    } finally {
      end();
    }
  }

  async function drawPage() {
    begin('排版并分页…');
    try {
      const info = await (await post('/api/doc', payload())).json();
      state.pages = Math.max(1, info.pages);
      if (state.page > state.pages - 1) state.page = state.pages - 1;
      $('page-no').textContent = `${state.page + 1} / ${state.pages}`;
      $('page-prev').disabled = state.page <= 0;
      $('page-next').disabled = state.page >= state.pages - 1;

      const out = await loadImage($('img-page'), '/api/render', payload(), 'page');
      if (out) {
        setStatus(`${state.pages} 页 · ${info.lines} 行 · 版心 ${info.measure.toFixed(0)} px`);
      }
    } catch (err) {
      setStatus('分页失败：' + err.message);
    } finally {
      end();
    }
  }

  async function drawCompare() {
    begin('两种断行各排一遍…');
    try {
      const text = state.text.split(/\n\s*\n/)[0].replace(/\n/g, ' ');
      const out = await loadImage($('img-compare'), '/api/compare',
        { text, size: Math.max(9, Math.min(28, state.size)), measure: state.measure, font: state.font },
        'compare');
      if (out) setStatus(`对照图 ${(out.size / 1024).toFixed(0)} kB`);
    } catch (err) {
      setStatus('对照失败：' + err.message);
    } finally {
      end();
    }
  }

  const redraw = {
    specimen: drawSpecimen,
    breaks: drawBreaks,
    pages: drawPage,
    compare: drawCompare,
  };

  function refresh() {
    const fn = redraw[state.tab];
    if (fn) fn();
  }

  const refreshSoon = debounce(refresh, 180);

  /* ------------------------------------------------------------ 面板 */

  const TITLES = {
    specimen: ['字体样张', '一页里压进字距、曲线、断行、避头尾与字形覆盖'],
    breaks: ['断行诊断', '每一行的胶伸缩比例、badness 与松紧等级'],
    pages: ['分页预览', '标记文本 → 断行 → 分页 → 栅格化'],
    compare: ['断行对照', '同一段文字、同一行宽，贪心与 Knuth–Plass 并排'],
  };

  const FIELD_TABS = {
    size: ['breaks', 'pages', 'compare'],
    leading: ['breaks', 'pages'],
    measure: ['breaks', 'compare'],
    tolerance: ['breaks'],
    margin: ['pages'],
    justify: ['pages'],
  };

  function applyLayout() {
    const tab = state.tab;
    $('stage-title').textContent = TITLES[tab][0];
    $('stage-sub').textContent = TITLES[tab][1];

    $$('.view').forEach((el) => {
      el.hidden = el.id !== 'view-' + tab;
    });

    $('group-specimen').style.display = tab === 'specimen' ? '' : 'none';
    $('group-text').style.display = tab === 'specimen' ? 'none' : '';
    $('group-page').style.display = tab === 'pages' ? '' : 'none';
    $('group-font').style.display = tab === 'pages' ? 'none' : '';

    Object.entries(FIELD_TABS).forEach(([id, tabs]) => {
      const input = $(id);
      if (!input) return;
      const field = input.closest('.field');
      if (field) field.style.display = tabs.includes(tab) ? '' : 'none';
    });

    $('group-type').style.display =
      tab === 'specimen' ? 'none' : '';
  }

  /* ------------------------------------------------------------ 事件 */

  function bindRange(id, key, digits) {
    const el = $(id);
    const out = $('v-' + id);
    const sync = () => {
      const value = parseFloat(el.value);
      state[key] = value;
      if (out) out.textContent = digits ? value.toFixed(digits) : String(value);
      refreshSoon();
    };
    el.addEventListener('input', sync);
    sync();
  }

  function bindFonts(data) {
    const select = $('font-select');
    const fonts = data.fonts || [];
    const chosen = new Set((data.roles || []).map((r) => r.path));
    const options = [];
    const seen = new Set();
    fonts.forEach((f) => {
      if (!f.path || seen.has(f.path)) return;
      seen.add(f.path);
      const label = `${f.family} ${f.style}`.trim();
      options.push(`<option value="${f.path}">${label} · ${f.glyphs} 字形</option>`);
    });
    select.innerHTML = options.join('');
    const serif = (data.roles || []).find((r) => r.role === 'serif');
    if (serif && serif.path) {
      select.value = serif.path;
      state.font = serif.path;
      $('font-hint').textContent = `${serif.full_name} · ${fmt(serif.glyphs)} 字形 · upem ${serif.units_per_em}`;
    } else {
      state.font = fonts.length ? fonts[0].path : '';
    }

    $('roles').innerHTML = (data.roles || []).map((r) =>
      `<li><span class="role">${r.role}</span><span class="family">${r.family}</span></li>`
    ).join('');

    if (data.version) $('version').textContent = data.version;
    select.addEventListener('change', () => {
      state.font = select.value;
      const hit = fonts.find((f) => f.path === select.value);
      if (hit) {
        $('font-hint').textContent = `${hit.family} ${hit.style} · ${fmt(hit.glyphs)} 字形 · upem ${hit.upem}`;
      }
      refresh();
    });
  }

  function bindTabs() {
    $('tabs').addEventListener('click', (ev) => {
      const btn = ev.target.closest('button[data-tab]');
      if (!btn) return;
      $$('#tabs button').forEach((b) => b.classList.toggle('active', b === btn));
      state.tab = btn.dataset.tab;
      applyLayout();
      refresh();
    });
  }

  function bindText() {
    const el = $('text');
    el.value = DEFAULT_TEXT;
    state.text = DEFAULT_TEXT;
    el.addEventListener('input', () => {
      state.text = el.value;
      refreshSoon();
    });
  }

  function bindPager() {
    $('page-prev').addEventListener('click', () => {
      if (state.page > 0) { state.page -= 1; drawPage(); }
    });
    $('page-next').addEventListener('click', () => {
      if (state.page < state.pages - 1) { state.page += 1; drawPage(); }
    });
  }

  function saveBlob(blob, name) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 4000);
  }

  function currentImage() {
    const map = { specimen: 'img-specimen', pages: 'img-page', compare: 'img-compare' };
    const id = map[state.tab];
    return id ? $(id) : null;
  }

  function bindDownload() {
    $('download').addEventListener('click', async () => {
      try {
        let name = 'typesmith';
        let url = null;

        if (state.tab === 'breaks') {
          const res = await post('/api/render', payload());
          saveBlob(await res.blob(), 'typesmith-page1.png');
          return;
        }
        const img = currentImage();
        if (!img || !img.src) return;
        if (state.tab === 'specimen') name = `specimen-${state.width}x${state.height}`;
        if (state.tab === 'pages') name = `page${state.page + 1}`;
        if (state.tab === 'compare') name = 'greedy-vs-knuth';
        url = img.src;
        const blob = await (await fetch(url)).blob();
        saveBlob(blob, `typesmith-${name}.png`);
      } catch (err) {
        setStatus('下载失败：' + err.message);
      }
    });

    $('download-svg').addEventListener('click', async () => {
      try {
        const res = await post('/api/render.svg', payload());
        const text = await res.text();
        saveBlob(new Blob([text], { type: 'image/svg+xml' }), 'typesmith-page1.svg');
      } catch (err) {
        setStatus('导出 SVG 失败：' + err.message);
      }
    });
  }

  /* ------------------------------------------------------------ 启动 */

  async function boot() {
    bindTabs();
    bindText();
    bindPager();
    bindDownload();
    bindRange('size', 'size', 0);
    bindRange('leading', 'leading', 2);
    bindRange('measure', 'measure', 0);
    bindRange('tolerance', 'tolerance', 1);
    bindRange('margin', 'margin', 0);
    bindRange('width', 'width', 0);
    bindRange('height', 'height', 0);

    $('justify').addEventListener('change', (ev) => {
      state.justify = ev.target.checked;
      refreshSoon();
    });

    try {
      const res = await fetch('/api/fonts');
      bindFonts(await res.json());
    } catch (err) {
      setStatus('无法读取字体列表：' + err.message);
    }

    applyLayout();
    await drawSpecimen();
  }

  document.addEventListener('DOMContentLoaded', boot);
})();

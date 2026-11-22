const PAGE_SIZE = 100;
const state = { items: [], selected: new Set(), view: "grid",
                coverPaused: false, page: 1, arch: "hide",
                month: "all", cat: "all", sort: "fav_seq", asc: false };

function sortList(list) {
  const dir = state.asc ? 1 : -1;
  const keyOf = state.sort === "duration" ? (i => i.duration || 0)
    : state.sort === "author_name" ? (i => i.author_name || "")
    : state.sort === "fav_seq" ? (i => i.fav_seq || 0)
    : (i => i.first_seen || "");
  return list.slice().sort((a, b) => {
    const va = keyOf(a), vb = keyOf(b);
    if (typeof va === "string") return dir * va.localeCompare(vb, "zh");
    return dir * (va - vb);
  });
}

function pubMonth(it) {
  if (!it.create_time) return "";
  const d = new Date(it.create_time * 1000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function filteredItems() {
  let list = state.items;
  if (state.arch === "missing") list = list.filter(i => i.status === "missing");
  else if (state.arch === "only")
    list = list.filter(i => i.status !== "missing" && i.archived);
  else if (state.arch === "hide")
    list = list.filter(i => i.status !== "missing" && !i.archived);
  else list = list.filter(i => i.status !== "missing");
  if (state.month !== "all") {
    const [kind, ym] = state.month.split(":");
    list = list.filter(i => (kind === "pub" ? pubMonth(i)
                            : (i.first_seen || "").slice(0, 7)) === ym);
  }
  if (state.cat !== "all") {
    list = list.filter(i => (i.category || "未分类") === state.cat);
  }
  const sorted = sortList(list);
  // 没有收藏顺序的条目（上次完整重扫时已不在收藏列表里）统一排到最后
  if (state.sort === "fav_seq") {
    return sorted.filter(i => i.fav_seq != null)
                  .concat(sorted.filter(i => i.fav_seq == null));
  }
  return sorted;
}

function pageSlice() {
  const all = filteredItems();
  const total = all.length;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (state.page > pages) state.page = pages;
  if (state.page < 1) state.page = 1;
  const start = (state.page - 1) * PAGE_SIZE;
  return { items: all.slice(start, start + PAGE_SIZE), total, pages, start };
}

function pageIds() { return pageSlice().items.map(i => i.aweme_id); }

function buildMonthOptions() {
  const sel = document.getElementById("month");
  const keep = sel.value;
  const of = fn => [...new Set(state.items.map(fn).filter(Boolean))].sort().reverse();
  const label = m => `${m.slice(0, 4)} 年 ${m.slice(5)} 月`;
  const inMonths = of(i => (i.first_seen || "").slice(0, 7));
  const pubMonths = of(pubMonth);
  sel.innerHTML = `<option value="all">全部时间</option>` +
    `<optgroup label="按入库月份">` +
    inMonths.map(m => `<option value="in:${m}">${label(m)}</option>`).join("") +
    `</optgroup>` +
    (pubMonths.length ? `<optgroup label="按发布月份">` +
      pubMonths.map(m => `<option value="pub:${m}">${label(m)}</option>`).join("") +
      `</optgroup>` : "");
  const vals = [...sel.options].map(o => o.value);
  sel.value = vals.includes(keep) ? keep : "all";
  state.month = sel.value;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 2400);
}

function esc(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function fmtDur(ms) {
  if (!ms) return "";
  const s = Math.round(ms / 1000);
  const m = Math.floor(s / 60), r = s % 60;
  return m ? `${m}:${String(r).padStart(2, "0")}` : `0:${String(r).padStart(2, "0")}`;
}

function linkOf(id) { return `https://www.douyin.com/video/${id}`; }

async function loadStats() {
  const s = await api("/api/stats");
  const hours = Math.round((s.duration_ms / 3600000) * 10) / 10;
  document.getElementById("stats").innerHTML = `
    <div class="stat"><b>${s.total}</b>收藏视频</div>
    <div class="stat"><b>${s.authors}</b>创作者</div>
    <div class="stat"><b>${hours}</b>小时总时长</div>
    <div class="stat"><b>${s.archived || 0}</b>已归档</div>
    ${s.missing ? `<div class="stat"><b class="bad">${s.missing}</b>已失效</div>` : ""}`;
  const catSel = document.getElementById("cat");
  const keep = catSel.value;
  catSel.innerHTML = `<option value="all">全部大类</option>` +
    (s.categories || []).map(c =>
      `<option value="${esc(c.name)}">${esc(c.name)} (${c.c})</option>`).join("");
  if ([...catSel.options].some(o => o.value === keep)) catSel.value = keep;

  const archSel = document.getElementById("arch");
  const missOpt = archSel.querySelector('option[value="missing"]');
  if (missOpt) missOpt.textContent = s.missing ? `已失效 (${s.missing})` : "已失效";

  const notice = document.getElementById("missingNotice");
  if (!notice) return;
  if (s.missing && !state.noticeOff && state.arch !== "missing") {
    notice.classList.remove("hidden");
    notice.innerHTML =
      `<span>有 <b>${s.missing}</b> 条视频已不在你的收藏列表（可能已取消收藏或被作者删除）。</span>` +
      `<button class="btn" id="missKeep">单独放出来</button>` +
      `<button class="btn danger" id="missPurge">直接删除</button>` +
      `<button class="btn ghost" id="missLater">稍后再说</button>`;
    notice.querySelector("#missKeep").onclick = () => {
      archSel.value = "missing";
      state.arch = "missing";
      state.page = 1;
      notice.classList.add("hidden");
      syncArchBtn();
      render();
    };
    notice.querySelector("#missPurge").onclick = async () => {
      if (!confirm(`确定彻底删除这 ${s.missing} 条本地记录？平台收藏不受影响。`)) return;
      const r = await api("/api/purge", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "missing" }) });
      toast(`已删除 ${r.count} 条失效记录`);
      notice.classList.add("hidden");
      await loadItems(false);
      await loadStats();
    };
    notice.querySelector("#missLater").onclick = () => {
      state.noticeOff = true;
      notice.classList.add("hidden");
    };
  } else {
    notice.classList.add("hidden");
  }
}

async function loadAuthors() {
  const d = await api("/api/authors");
  const sel = document.getElementById("author");
  const keep = sel.value;
  sel.innerHTML = `<option value="">全部作者</option>` +
    d.authors.map(a => `<option value="${esc(a.name)}">${esc(a.name)} (${a.c})</option>`).join("");
  sel.value = keep;
}

async function loadItems(resetPage = true) {
  const q = document.getElementById("q").value.trim();
  const author = document.getElementById("author").value;
  state.arch = document.getElementById("arch").value;
  state.month = document.getElementById("month").value;
  state.cat = document.getElementById("cat").value;
  state.sort = document.getElementById("sort").value.split(":")[0];
  state.asc = document.getElementById("sort").value.split(":")[1] === "asc";
  // 一次性取全部（含已归档、已失效），其余筛选/排序都在前端本地做：切条件毫秒级
  const d = await api(`/api/items?q=${encodeURIComponent(q)}&author=${encodeURIComponent(author)}` +
                      `&sort=first_seen&order=desc&archive=every`);
  state.items = d.items;
  if (resetPage) state.page = 1;
  buildMonthOptions();
  state.selected = new Set([...state.selected].filter(id => d.items.some(i => i.aweme_id === id)));
  syncArchBtn();
  render();
}

function syncSelection() {
  const n = state.selected.size;
  document.getElementById("selCount").textContent = n;
  document.getElementById("selCount2").textContent = n;
  document.getElementById("actionbar").classList.toggle("empty", n === 0);
  const ids = pageIds();
  document.getElementById("selAll").checked =
    ids.length > 0 && ids.every(id => state.selected.has(id));
}

function render() {
  const grid = document.getElementById("grid");
  const tableWrap = document.getElementById("tableWrap");
  const vis = pageSlice();
  if (!vis.total) {
    grid.classList.remove("hidden");
    tableWrap.classList.add("hidden");
    document.getElementById("pager").innerHTML = "";
    const hasAny = state.items.length > 0;
    grid.innerHTML = `<div class="empty-state">
      <h2>${hasAny ? "当前视图下没有条目" : "这儿的清单是空的"}</h2>
      ${hasAny
        ? "这一页没有匹配的条目，试试切换「未归档 / 已归档 / 全部」或清空搜索词。"
        : "还没数据就先点右上角「抓取 / 更新收藏」。"}
    </div>`;
    syncSelection();
    return;
  }
  if (state.view === "grid") {
    tableWrap.classList.add("hidden");
    grid.classList.remove("hidden");
    grid.innerHTML = vis.items.map(it => {
      const sel = state.selected.has(it.aweme_id) ? " sel" : "";
      const cover = state.coverPaused
        ? `<div class="none">采集结束后加载封面</div>`
        : `<div class="none">加载中…</div>
        <img loading="lazy" src="/cover/${it.aweme_id}" alt=""
             onload="this.previousElementSibling.remove()"
             onerror="this.style.opacity=0;this.previousElementSibling.textContent='封面不可用'">`;
      return `<div class="card${sel}" data-id="${it.aweme_id}">
        <div class="thumb">${cover}
          <div class="tick">✓</div>
          <div class="dur">${fmtDur(it.duration)}</div>
          <div class="hoverbar">
            <button data-act="copy">复制链接</button>
            <a href="${linkOf(it.aweme_id)}" target="_blank" rel="noopener">原片</a>
          </div>
        </div>
        <div class="body">
          <p class="desc">${esc(it.desc) || '<span style="color:#a9a49d">（无简介）</span>'}</p>
          <div class="meta">
            <span class="au">@${esc(it.author_name) || "未知"}</span>
            ${it.status === "missing" ? '<span class="cat cat-bad">已失效</span>' :
              `<span class="cat">${esc(it.category || "未分类")}</span>`}
            <span>${esc((it.first_seen || "").slice(5, 16).replace("T", " "))}</span>
          </div>
        </div>
      </div>`;
    }).join("");
  } else {
    grid.classList.add("hidden");
    tableWrap.classList.remove("hidden");
    tableWrap.innerHTML = `<table>
      <thead><tr><th></th><th>封面</th><th>简介</th><th>作者</th><th>类目</th><th>时长</th><th>链接</th></tr></thead>
      <tbody>${vis.items.map(it => `
        <tr data-id="${it.aweme_id}">
          <td><input type="checkbox" class="rowsel" ${state.selected.has(it.aweme_id) ? "checked" : ""}></td>
          <td>${state.coverPaused ? "" : `<img class="mini" loading="lazy" src="/cover/${it.aweme_id}" onerror="this.style.opacity=0">`}</td>
          <td>${esc(it.desc) || "（无简介）"}</td>
          <td>${esc(it.author_name)}</td>
          <td>${it.status === "missing" ? '<span class="cat cat-bad">已失效</span>' : esc(it.category || "未分类")}</td>
          <td>${fmtDur(it.duration)}</td>
          <td><a href="${linkOf(it.aweme_id)}" target="_blank" rel="noopener">打开</a></td>
        </tr>`).join("")}</tbody>
    </table>`;
  }
  renderPager(vis);
  syncSelection();
}

function renderPager(vis) {
  const el = document.getElementById("pager");
  if (!vis) { el.innerHTML = ""; return; }
  const { total, pages, start } = vis;
  const end = Math.min(start + PAGE_SIZE, total);
  el.innerHTML = `
    <button class="btn" id="pgPrev" ${state.page <= 1 ? "disabled" : ""}>上一页</button>
    <span class="pginfo">第 <b>${state.page}</b> / ${pages} 页 · 本页 ${start + 1}-${end} · 共 ${total} 条</span>
    <button class="btn" id="pgNext" ${state.page >= pages ? "disabled" : ""}>下一页</button>`;
  document.getElementById("pgPrev").onclick = () => { state.page -= 1; render(); window.scrollTo({ top: 0 }); };
  document.getElementById("pgNext").onclick = () => { state.page += 1; render(); window.scrollTo({ top: 0 }); };
}

document.getElementById("grid").addEventListener("click", e => {
  const card = e.target.closest(".card");
  if (!card) return;
  if (e.target.closest("[data-act='copy']")) {
    navigator.clipboard.writeText(linkOf(card.dataset.id)).then(() => toast("链接已复制"));
    return;
  }
  if (e.target.closest("a")) return;
  toggle(card.dataset.id);
});

document.getElementById("tableWrap").addEventListener("change", e => {
  const tr = e.target.closest("tr");
  if (tr && e.target.classList.contains("rowsel")) toggle(tr.dataset.id);
});

function toggle(id) {
  if (state.selected.has(id)) state.selected.delete(id);
  else state.selected.add(id);
  // 只改这一张的样式，不重建整页：1791 条时重建一次约 1~2 秒，就是「点选有延迟」的根因
  const card = document.querySelector(`.card[data-id="${id}"]`);
  if (card) card.classList.toggle("sel");
  const tr = document.querySelector(`tr[data-id="${id}"]`);
  if (tr) {
    const cb = tr.querySelector(".rowsel");
    if (cb) cb.checked = state.selected.has(id);
  }
  syncSelection();
}

document.getElementById("selAll").addEventListener("change", e => {
  const ids = pageIds();
  if (e.target.checked) ids.forEach(id => state.selected.add(id));
  else ids.forEach(id => state.selected.delete(id));
  render();
});

document.getElementById("viewGrid").addEventListener("click", () => {
  state.view = "grid";
  document.getElementById("viewGrid").classList.add("on");
  document.getElementById("viewTable").classList.remove("on");
  render();
});

document.getElementById("viewTable").addEventListener("click", () => {
  state.view = "table";
  document.getElementById("viewTable").classList.add("on");
  document.getElementById("viewGrid").classList.remove("on");
  render();
});

document.getElementById("q").addEventListener("input", debounce(loadItems, 300));
document.getElementById("author").addEventListener("change", loadItems);
document.getElementById("refresh").addEventListener("click", async () => {
  await Promise.all([loadStats(), loadAuthors(), loadItems()]);
  toast("已刷新");
});

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

async function doExport(fmt) {
  if (!state.selected.size) return;
  try {
    const r = await api("/api/export/links", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: [...state.selected], fmt })
    });
    toast(`已导出 ${r.count} 条：${r.file}`);
    window.open(r.url, "_blank");
  } catch (e) {
    toast("导出失败：" + e.message);
  }
}

document.getElementById("expCsv").addEventListener("click", () => doExport("csv"));
document.getElementById("expMd").addEventListener("click", () => doExport("md"));

document.getElementById("copyLinks").addEventListener("click", () => {
  const text = [...state.selected].map(linkOf).join("\n");
  navigator.clipboard.writeText(text).then(() => toast(`已复制 ${state.selected.size} 条链接`));
});

document.getElementById("dlBtn").addEventListener("click", async () => {
  const r = await fetch("/api/download", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: "{}"
  });
  toast((await r.json()).reason);
});

function syncArchBtn() {
  const view = document.getElementById("arch").value;
  const btn = document.getElementById("archBtn");
  if (view === "missing") {
    btn.textContent = "彻底删除选中";
    btn.classList.add("danger");
  } else {
    btn.textContent = view === "only" ? "取消归档" : "归档选中";
    btn.classList.remove("danger");
  }
}

document.getElementById("arch").addEventListener("change", async () => {
  state.arch = document.getElementById("arch").value;
  state.page = 1;
  syncArchBtn();
  render();
  await loadStats();     // 进出「失效」视图时重新判断提示条
});

function reRender() {
  state.month = document.getElementById("month").value;
  state.cat = document.getElementById("cat").value;
  state.sort = document.getElementById("sort").value.split(":")[0];
  state.asc = document.getElementById("sort").value.split(":")[1] === "asc";
  state.page = 1;
  render();
}

["month", "cat", "sort"].forEach(id =>
  document.getElementById(id).addEventListener("change", reRender));

document.getElementById("archBtn").addEventListener("click", async () => {
  if (!state.selected.size) { toast("先选几条再操作"); return; }
  if (document.getElementById("arch").value === "missing") {
    if (!confirm(`彻底删除选中的 ${state.selected.size} 条本地记录？平台收藏不受影响。`)) return;
    try {
      const r = await api("/api/purge", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: [...state.selected] })
      });
      toast(`已彻底删除 ${r.count} 条`);
      state.selected.clear();
      await Promise.all([loadStats(), loadItems(false)]);
    } catch (e) {
      toast("删除失败：" + e.message);
    }
    return;
  }
  const archiving = document.getElementById("arch").value !== "only";
  try {
    const r = await api("/api/archive", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: [...state.selected], archived: archiving })
    });
    toast(`${archiving ? "已归档" : "已取消归档"} ${r.count} 条（平台收藏未变动）`);
    state.selected.clear();
    await Promise.all([loadStats(), loadItems(false)]);
  } catch (e) {
    toast("归档失败：" + e.message);
  }
});

let pollTimer = null;
let wasBusy = false;

async function checkStatus() {
  let s;
  try { s = await api("/api/collect/status"); } catch (e) { return; }
  const el = document.getElementById("collectStatus");
  const busy = ["starting", "waiting_login", "collecting"].includes(s.state);
  el.textContent = busy ? (s.msg || "处理中…") : "";
  el.classList.toggle("busy", busy);
  document.getElementById("collectBtn").disabled = busy;
  // 采集期间不再按需拉封面：两个浏览器的渲染/IO 峰值错开，避免滚动发涩
  if (busy && !state.coverPaused) {
    state.coverPaused = true;
    render();
  }
  if (busy) wasBusy = true;
  if (!busy && wasBusy) {
    wasBusy = false;
    state.coverPaused = false;
    if (s.state === "done" || s.state === "empty") {
      toast(s.msg || "抓取完成");
      await Promise.all([loadStats(), loadAuthors(), loadItems()]);
    } else if (s.state === "error") {
      toast("抓取失败：" + (s.msg || "未知原因"));
    }
  }
  if (busy) startPolling();
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(checkStatus, 2000);
}

document.getElementById("collectBtn").addEventListener("click", async () => {
  const sel = document.getElementById("collectTarget");
  const v = Number(sel.value);
  const body = v < 0 ? { target: 0, full: true } : { target: v, full: false };
  try {
    await api("/api/collect", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const label = v < 0 ? "完整重扫" : (v === 100 ? "常规增量（100 条）" : `只取最新 ${v} 条`);
    toast(`已启动（${label}），浏览器窗口即将弹出；首次需要扫码登录`);
    wasBusy = true;
    state.coverPaused = true;
    render();
    document.getElementById("collectStatus").textContent = "正在启动…";
    startPolling();
  } catch (e) {
    toast("启动失败：" + e.message);
  }
});

(async function init() {
  await Promise.all([loadStats(), loadAuthors(), loadItems()]);
  checkStatus();
  // 常驻轻量轮询：不管采集是谁启动的（页面按钮 / 命令行 / 另一个窗口），
  // 页面都能立刻进入「采集期暂停封面」状态，采集结束自动恢复。
  startPolling();
})();

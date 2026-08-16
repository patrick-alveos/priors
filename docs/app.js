/* Priors reader.
 * - Opens on the latest issue (data/index.json, newest first).
 * - One full-height, vertically scrolling panel per topic; horizontal
 *   scroll-snap between topics (native swipe on touch devices).
 * - A story is marked read when you scroll past its end (or tap its card
 *   twice); read state persists per issue in localStorage.
 * - Archive sheet lists past issues; #hash deep-links a week.
 */

const $ = (id) => document.getElementById(id);
const pager = $("pager");
const tabsEl = $("tabs");

let issueIndex = [];
let currentWeek = null;
let readState = {}; // storyId -> true

const fmtDate = (iso) =>
  new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short" });
const fmtRange = (a, b) => `${fmtDate(a)} – ${fmtDate(b)}, ${a.slice(0, 4)}`;

// ---- read state -------------------------------------------------------------

function readKey(week) {
  return `priors-read-${week}`;
}
function loadReadState(week) {
  try {
    readState = JSON.parse(localStorage.getItem(readKey(week))) || {};
  } catch {
    readState = {};
  }
}
function markRead(storyId, el) {
  if (readState[storyId]) return;
  readState[storyId] = true;
  localStorage.setItem(readKey(currentWeek), JSON.stringify(readState));
  el.classList.add("read");
  updateTabCounts();
}

// A story id that survives re-renders: week + headline.
function storyId(story) {
  return story.headline.slice(0, 80);
}

// ---- rendering --------------------------------------------------------------

function el(tag, cls, html) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (html !== undefined) node.innerHTML = html;
  return node;
}

const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function deltaText(f) {
  if (f.delta_pp === null || f.delta_pp === undefined) return "";
  const arrow = f.delta_pp > 0 ? "↑" : "↓";
  return ` (${arrow}${Math.abs(f.delta_pp)}pp ${esc(f.delta_label)})`;
}

function renderOdds(story) {
  if (!story.forecasts?.length && !story.no_market_note) return "";
  let inner = `<div class="label">Updating the priors</div>`;
  if (story.forecasts?.length) {
    inner += story.forecasts
      .map(
        (f) =>
          `<p><a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(
            f.platform[0].toUpperCase() + f.platform.slice(1)
          )}</a> puts &ldquo;${esc(f.question)}&rdquo; at <strong>${Math.round(
            f.probability * 100
          )}%</strong>${deltaText(f)}</p>`
      )
      .join("");
  } else {
    inner += `<p class="none">No liquid prediction market covers this yet.</p>`;
  }
  return `<div class="odds">${inner}</div>`;
}

function renderStory(story) {
  const card = el("article", "story");
  const id = storyId(story);
  card.dataset.storyId = id;
  let html = "";
  if (story.image?.kind === "og" && story.image.url) {
    html += `<img class="hero" src="${esc(story.image.url)}" alt="" loading="lazy">`;
  }
  html += `<span class="read-chip">✓ Read</span>`;
  html += `<h2>${esc(story.headline)}</h2>`;
  html += `<p>${esc(story.what_happened)}</p>`;
  html += `<div class="label">Potential implications</div><p>${esc(story.potential_implications)}</p>`;
  if (story.takes?.length) {
    html += `<div class="label">The takes</div>`;
    html += story.takes
      .map(
        (t) =>
          `<div class="take"><a href="${esc(t.source_url)}" target="_blank" rel="noopener">${esc(
            t.source
          )}</a> ${esc(t.text)}</div>`
      )
      .join("");
  }
  html += renderOdds(story);
  card.innerHTML += html;
  if (readState[id]) card.classList.add("read");

  // Double-tap toggles read manually.
  card.addEventListener("dblclick", () => markRead(id, card));
  return card;
}

// A story is read once you've scrolled its end into view.
function checkPanelRead(panel) {
  const fold = panel.scrollTop + panel.clientHeight;
  for (const card of panel.querySelectorAll(".story[data-story-id]:not(.read)")) {
    if (card.offsetTop + card.offsetHeight <= fold + 8) {
      markRead(card.dataset.storyId, card);
    }
  }
}

function watchPanelScroll(panel) {
  let pending = false;
  panel.addEventListener(
    "scroll",
    () => {
      if (pending) return;
      pending = true;
      setTimeout(() => {
        pending = false;
        checkPanelRead(panel);
      }, 200);
    },
    { passive: true }
  );
}

function buildPanels(issue) {
  pager.innerHTML = "";
  tabsEl.innerHTML = "";

  const panels = [];

  for (const section of issue.sections) {
    if (!section.stories?.length) continue;
    const panel = el("section", "panel");
    panel.dataset.title = section.title;
    section.stories.forEach((s) => panel.appendChild(renderStory(s)));
    panels.push(panel);
  }

  // Markets moved
  if (issue.markets_moved?.length) {
    const panel = el("section", "panel");
    panel.dataset.title = "Markets moved";
    const card = el("article", "story");
    card.innerHTML =
      `<h2>Markets moved</h2>` +
      issue.markets_moved
        .map(
          (m) =>
            `<p><a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(
              m.platform[0].toUpperCase() + m.platform.slice(1)
            )}</a>: &ldquo;${esc(m.question)}&rdquo; — <strong>${Math.round(
              m.probability * 100
            )}%</strong>${deltaText(m)}</p>`
        )
        .join("");
    panel.appendChild(card);
    panels.push(panel);
  }

  // Sunday: human story + photo
  if (issue.human_story || issue.photo) {
    const panel = el("section", "panel");
    panel.dataset.title = "Sunday";
    if (issue.human_story) {
      const hs = issue.human_story;
      const card = el("article", "story");
      let html = "";
      if (hs.image?.url) html += `<img class="hero" src="${esc(hs.image.url)}" alt="" loading="lazy">`;
      html += `<div class="label">Human story of the week</div>`;
      html += `<h2>${esc(hs.headline)}</h2><p>${esc(hs.text)}</p>`;
      html += `<p class="via">Via <a href="${esc(hs.source_url)}" target="_blank" rel="noopener">${esc(hs.source)}</a></p>`;
      card.innerHTML = html;
      panel.appendChild(card);
    }
    if (issue.photo) {
      const p = issue.photo;
      const card = el("article", "story");
      let html = `<img class="hero" src="${esc(p.image_url)}" alt="${esc(p.title)}" loading="lazy">`;
      html += `<div class="label">Photo of the week</div>`;
      if (p.description) html += `<p class="caption">${esc(p.description)}</p>`;
      html += `<p class="photo-credit"><a href="${esc(p.link)}" target="_blank" rel="noopener">${esc(
        p.attribution
      )}</a> · Wikimedia Commons</p>`;
      html += `<p class="signoff">Have a good week. Same time next Saturday.</p>`;
      card.innerHTML = html;
      panel.appendChild(card);
    }
    panels.push(panel);
  }

  panels.forEach((panel, i) => {
    pager.appendChild(panel);
    watchPanelScroll(panel);
    const tab = el("button", "tab", esc(panel.dataset.title));
    tab.addEventListener("click", () =>
      pager.scrollTo({ left: i * pager.clientWidth, behavior: "smooth" })
    );
    tabsEl.appendChild(tab);
  });

  updateTabCounts();
  setActiveTab(0);
  pager.scrollTo({ left: 0 });
}

function updateTabCounts() {
  [...pager.children].forEach((panel, i) => {
    const tab = tabsEl.children[i];
    if (!tab) return;
    const stories = panel.querySelectorAll(".story[data-story-id]");
    const unread = [...stories].filter((s) => !s.classList.contains("read")).length;
    const base = esc(panel.dataset.title);
    tab.innerHTML = stories.length && unread ? `${base}<span class="count">${unread}</span>` : base;
  });
}

function setActiveTab(index) {
  [...tabsEl.children].forEach((t, i) => t.classList.toggle("active", i === index));
  tabsEl.children[index]?.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
}

pager.addEventListener("scroll", () => {
  const index = Math.round(pager.scrollLeft / pager.clientWidth);
  setActiveTab(index);
});

// ---- issue loading ----------------------------------------------------------

async function loadIssue(week) {
  pager.innerHTML = `<div class="loading">Loading ${week}…</div>`;
  const resp = await fetch(`data/${week}.json`);
  const issue = await resp.json();
  currentWeek = week;
  loadReadState(week);
  $("issueDate").textContent = fmtRange(issue.period_start, issue.period_end);
  location.hash = week;
  buildPanels(issue);
}

async function boot() {
  try {
    const resp = await fetch("data/index.json");
    issueIndex = (await resp.json()).issues;
  } catch {
    pager.innerHTML = `<div class="loading">Couldn't load issues — are you offline before the first visit?</div>`;
    return;
  }
  buildArchiveList();
  const hashWeek = location.hash.replace("#", "");
  const week = issueIndex.some((i) => i.week === hashWeek) ? hashWeek : issueIndex[0]?.week;
  if (week) await loadIssue(week);
}

// ---- archive sheet ----------------------------------------------------------

function buildArchiveList() {
  const list = $("archiveList");
  list.innerHTML = "";
  for (const entry of issueIndex) {
    const li = el("li", entry.week === currentWeek ? "current" : "");
    const btn = el(
      "button",
      "",
      `<span>${esc(entry.week)}</span><span class="week-range">${fmtRange(
        entry.period_start,
        entry.period_end
      )}</span>`
    );
    btn.addEventListener("click", async () => {
      toggleArchive(false);
      await loadIssue(entry.week);
      buildArchiveList();
    });
    li.appendChild(btn);
    list.appendChild(li);
  }
}

function toggleArchive(show) {
  $("archiveSheet").hidden = !show;
}
$("archiveBtn").addEventListener("click", () => toggleArchive(true));
$("archiveBackdrop").addEventListener("click", () => toggleArchive(false));

// ---- service worker ---------------------------------------------------------

// Offline support in production only — a live-reload dev loop and a
// cache-first service worker are natural enemies.
const isLocal = ["localhost", "127.0.0.1"].includes(location.hostname);
if ("serviceWorker" in navigator && !isLocal) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

boot();

// smalldocs: the behaviour of the page. Search, copy buttons, anchors, the table of contents, the theme toggle, listings.
(() => {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const offset = ($('meta[name="smalldocs:offset"]') || { content: "./" }).content;
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } },
  };

  // ---- the header's height, for sticky sidebars and anchor scrolling
  const header = $("#quarto-header");
  const setHeader = () => {
    const h = header ? header.offsetHeight : 0;
    document.documentElement.style.setProperty("--sd-header-height", h + "px");
    document.documentElement.style.scrollPaddingTop = h + 16 + "px";
  };
  setHeader();
  if (header && window.ResizeObserver) new ResizeObserver(setHeader).observe(header);

  // ---- light or dark: the theme decides; we read its background for the code colours
  const markDark = () => {
    const bg = getComputedStyle(document.body).backgroundColor.match(/\d+(\.\d+)?/g);
    if (!bg) return;
    const [r, g, b] = bg.map(Number);
    const dark = 0.299 * r + 0.587 * g + 0.114 * b < 128;
    document.documentElement.classList.toggle("quarto-dark", dark);
    $$(".sd-navbar-default").forEach((n) => { n.dataset.bsTheme = dark ? "dark" : "light"; });
  };
  const applyScheme = () => {
    const alt = document.documentElement.dataset.scheme === "alternate";
    $$("link.quarto-color-scheme").forEach((l) => { l.disabled = l.classList.contains("quarto-color-alternate") ? !alt : alt; });
    setTimeout(markDark, 50);
  };
  window.smalldocsToggleScheme = () => {
    const alt = document.documentElement.dataset.scheme !== "alternate";
    if (alt) document.documentElement.dataset.scheme = "alternate"; else delete document.documentElement.dataset.scheme;
    store.set("smalldocs-scheme", alt ? "alternate" : "default");
    applyScheme();
  };
  if ($$("link.quarto-color-scheme").length > 1) applyScheme(); else markDark();
  window.addEventListener("load", markDark);

  // ---- the sidebar on narrow screens
  const sidebar = $("#quarto-sidebar"), glass = $("#quarto-sidebar-glass");
  const toggleSidebar = (open) => {
    if (!sidebar) return;
    const show = open === undefined ? !sidebar.classList.contains("show") : open;
    sidebar.classList.toggle("show", show);
    if (glass) glass.classList.toggle("show", show);
  };
  $$(".quarto-btn-toggle").forEach((b) => b.addEventListener("click", () => toggleSidebar()));
  if (glass) glass.addEventListener("click", () => toggleSidebar(false));

  // ---- copy buttons
  $$(".code-copy-button").forEach((btn) => btn.addEventListener("click", async () => {
    const code = btn.parentElement.querySelector("pre code");
    if (!code) return;
    try { await navigator.clipboard.writeText(code.innerText); } catch (e) { return; }
    btn.classList.add("code-copy-button-checked");
    btn.title = "Copied!";
    setTimeout(() => { btn.classList.remove("code-copy-button-checked"); btn.title = "Copy to Clipboard"; }, 1500);
  }));

  // ---- anchors on headings
  $$("main .anchored[data-anchor-id]").forEach((h) => {
    if (h.classList.contains("no-anchor") || h.closest(".quarto-listing")) return;
    const a = document.createElement("a");
    a.className = "anchorjs-link";
    a.href = "#" + h.dataset.anchorId;
    a.setAttribute("aria-label", "Anchor");
    h.appendChild(a);
  });

  // ---- the table of contents follows the reader
  const tocLinks = $$("#TOC a.nav-link");
  if (tocLinks.length) {
    const targets = tocLinks.map((a) => document.getElementById(decodeURIComponent(a.getAttribute("href").slice(1)))).filter(Boolean);
    const spy = () => {
      const top = (header ? header.offsetHeight : 0) + 24;
      let current = 0;
      targets.forEach((t, i) => { if (t.getBoundingClientRect().top - top <= 0) current = i; });
      if (window.innerHeight + window.scrollY >= document.body.scrollHeight - 2) current = targets.length - 1;
      tocLinks.forEach((a, i) => a.classList.toggle("active", i === current));
    };
    document.addEventListener("scroll", spy, { passive: true });
    spy();
  }

  // ---- maths, when KaTeX has loaded
  window.smalldocsMath = () => {
    if (!window.renderMathInElement) return;
    window.renderMathInElement(document.body, {
      delimiters: [{ left: "\\[", right: "\\]", display: true }, { left: "\\(", right: "\\)", display: false }],
      throwOnError: false,
    });
  };
  window.smalldocsMath();  // deferred scripts run in order, so KaTeX, when the page has maths, has loaded

  // ---- search
  let index = null, fuse = null;
  const loadIndex = async () => {
    if (index) return;
    try {
      const r = await fetch(offset + "search.json");
      index = await r.json();
    } catch (e) { index = []; }
    if (window.Fuse) {
      fuse = new window.Fuse(index, {
        keys: [{ name: "title", weight: 2 }, { name: "section", weight: 2 }, { name: "text", weight: 1 }],
        ignoreLocation: true, threshold: 0.3, minMatchCharLength: 2, includeMatches: false,
      });
    }
  };
  const escapeHtml = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const snippet = (text, q) => {
    const i = text.toLowerCase().indexOf(q.toLowerCase().split(/\s+/)[0] || "");
    const start = Math.max(0, i - 60);
    let s = escapeHtml(text.slice(start, start + 200));
    q.split(/\s+/).filter((w) => w.length > 1).forEach((w) => {
      s = s.replace(new RegExp("(" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"), "<mark>$1</mark>");
    });
    return (start ? "…" : "") + s;
  };
  $$(".smalldocs-search").forEach((box) => {
    const input = $("input", box), results = $(".smalldocs-search-results", box);
    let active = -1;
    const show = (html) => { results.innerHTML = html; results.classList.add("show"); active = -1; };
    const hide = () => results.classList.remove("show");
    const run = async () => {
      const q = input.value.trim();
      if (q.length < 2) { hide(); return; }
      await loadIndex();
      const hits = fuse ? fuse.search(q, { limit: 20 }).map((h) => h.item)
        : index.filter((e) => (e.title + " " + e.section + " " + e.text).toLowerCase().includes(q.toLowerCase())).slice(0, 20);
      if (!hits.length) { show('<div class="search-none">No results</div>'); return; }
      show(hits.map((e) => `<a class="search-result" href="${offset}${e.href}">` +
        `<div class="search-result-title">${escapeHtml(e.title)}</div>` +
        (e.section ? `<div class="search-result-section">${escapeHtml(e.section)}</div>` : "") +
        `<div class="search-result-text">${snippet(e.text, q)}</div></a>`).join(""));
    };
    let timer = null;
    input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(run, 120); });
    input.addEventListener("focus", () => { loadIndex(); if (input.value.trim().length > 1) run(); });
    input.addEventListener("keydown", (ev) => {
      const items = $$(".search-result", results);
      if (ev.key === "Escape") { hide(); input.blur(); return; }
      if (!items.length) return;
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        active = (active + (ev.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
        items.forEach((it, i) => it.classList.toggle("active", i === active));
        items[active].scrollIntoView({ block: "nearest" });
      } else if (ev.key === "Enter") {
        ev.preventDefault();
        (items[active] || items[0]).click();
      }
    });
    document.addEventListener("click", (ev) => { if (!box.contains(ev.target)) hide(); });
  });
  document.addEventListener("keydown", (ev) => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
    if ((ev.key === "/" && !typing) || ((ev.metaKey || ev.ctrlKey) && ev.key === "k")) {
      const input = $$(".smalldocs-search input").find((i) => i.offsetParent !== null);
      if (input) { ev.preventDefault(); input.focus(); }
    }
  });

  // ---- listings: categories, filter, sort and pages
  const listings = $$(".quarto-listing");
  const categoryFromHash = () => {
    const m = location.hash.match(/^#category=(.*)$/);
    return m ? decodeURIComponent(m[1]) : "";
  };
  const state = new Map();
  const refresh = (listing) => {
    const st = state.get(listing);
    const items = $$("[data-index]", listing);
    const cat = categoryFromHash();
    const q = st.filter.toLowerCase();
    let shown = items.filter((it) => {
      const cats = JSON.parse(it.dataset.categories || "[]");
      return (!cat || cats.includes(cat)) && (!q || (it.dataset.text || "").includes(q));
    });
    if (st.sort) {
      const [field, way] = st.sort.split(":");
      const val = (it) => JSON.parse(it.dataset.sort || "{}")[field];
      shown.sort((a, b) => {
        const x = val(a), y = val(b);
        if (x === undefined) return 1;
        if (y === undefined) return -1;
        return (x < y ? -1 : x > y ? 1 : 0) * (way === "desc" ? -1 : 1);
      });
    } else {
      shown.sort((a, b) => a.dataset.index - b.dataset.index);
    }
    const parent = items.length ? items[0].parentElement : null;
    const size = Math.max(1, parseInt(listing.dataset.pageSize, 10) || 50);
    const pages = Math.max(1, Math.ceil(shown.length / size));
    st.page = Math.min(st.page, pages - 1);
    items.forEach((it) => { it.hidden = true; });
    shown.forEach((it, i) => {
      if (parent) parent.appendChild(it);
      it.hidden = Math.floor(i / size) !== st.page;
    });
    const none = $(".listing-no-matching", listing);
    if (none) none.classList.toggle("d-none", shown.length > 0);
    const nav = $(".listing-pagination", listing);
    if (nav) {
      nav.innerHTML = pages < 2 ? "" : Array.from({ length: pages }, (_, i) =>
        `<button type="button" class="btn btn-sm ${i === st.page ? "btn-primary" : "btn-outline-secondary"}" data-page="${i}">${i + 1}</button>`).join("");
    }
    $$(".quarto-listing-category .category").forEach((c) => c.classList.toggle("active", (c.dataset.category || "") === cat));
  };
  listings.forEach((listing) => {
    state.set(listing, { filter: "", sort: "", page: 0 });
    const f = $(".listing-filter", listing), s = $(".listing-sort", listing), nav = $(".listing-pagination", listing);
    if (f) f.addEventListener("input", () => { state.get(listing).filter = f.value; state.get(listing).page = 0; refresh(listing); });
    if (s) s.addEventListener("change", () => { state.get(listing).sort = s.value; refresh(listing); });
    if (nav) nav.addEventListener("click", (ev) => {
      const b = ev.target.closest("[data-page]");
      if (!b) return;
      state.get(listing).page = parseInt(b.dataset.page, 10);
      refresh(listing);
      listing.scrollIntoView({ block: "start" });
    });
    refresh(listing);
  });
  const setCategory = (cat) => {
    history.replaceState(null, "", cat ? "#category=" + encodeURIComponent(cat) : location.pathname + location.search);
    listings.forEach((l) => { state.get(l).page = 0; refresh(l); });
  };
  document.addEventListener("click", (ev) => {
    const c = ev.target.closest(".listing-category, .quarto-listing-category .category");
    if (!c || !listings.length) return;
    ev.preventDefault();
    const cat = c.dataset.category || "";
    setCategory(cat === categoryFromHash() && c.classList.contains("listing-category") ? "" : cat);
  });
  window.addEventListener("hashchange", () => listings.forEach(refresh));
})();

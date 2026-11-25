/* Follow-up Imaging Legislation Tracker: reads data/site.json and renders map, feed, detail and table. */
const FIPS = {"01":"AL","02":"AK","04":"AZ","05":"AR","06":"CA","08":"CO","09":"CT","10":"DE","11":"DC","12":"FL","13":"GA","15":"HI","16":"ID","17":"IL","18":"IN","19":"IA","20":"KS","21":"KY","22":"LA","23":"ME","24":"MD","25":"MA","26":"MI","27":"MN","28":"MS","29":"MO","30":"MT","31":"NE","32":"NV","33":"NH","34":"NJ","35":"NM","36":"NY","37":"NC","38":"ND","39":"OH","40":"OK","41":"OR","42":"PA","44":"RI","45":"SC","46":"SD","47":"TN","48":"TX","49":"UT","50":"VT","51":"VA","53":"WA","54":"WV","55":"WI","56":"WY"};
const SMALL = ["VT","NH","MA","RI","CT","NJ","DE","MD","DC"];
const STATUS = {
  enacted: {label: "Enacted", long: "Law enacted"},
  partial: {label: "Partial mandate", long: "Partial mandate (public plans only)"},
  pending: {label: "Pending", long: "Bill pending"},
  supplemental: {label: "Screening law only", long: "Supplemental screening law only"},
  died: {label: "Bill died", long: "Bill introduced but died"},
  none: {label: "None found", long: "No legislation found"},
};
const TILES = {AK:[0,0],ME:[11,0],VT:[10,1],NH:[11,1],WA:[1,2],ID:[2,2],MT:[3,2],ND:[4,2],MN:[5,2],IL:[6,2],WI:[7,2],MI:[8,2],NY:[9,2],RI:[10,2],MA:[11,2],
  OR:[1,3],NV:[2,3],WY:[3,3],SD:[4,3],IA:[5,3],IN:[6,3],OH:[7,3],PA:[8,3],NJ:[9,3],CT:[10,3],CA:[1,4],UT:[2,4],CO:[3,4],NE:[4,4],MO:[5,4],KY:[6,4],WV:[7,4],VA:[8,4],MD:[9,4],DE:[10,4],
  AZ:[2,5],NM:[3,5],KS:[4,5],AR:[5,5],TN:[6,5],NC:[7,5],SC:[8,5],DC:[9,5],OK:[4,6],LA:[5,6],MS:[6,6],AL:[7,6],GA:[8,6],HI:[0,7],TX:[4,7],FL:[9,7]};
const ORDER = ["enacted", "partial", "pending", "supplemental", "died", "none"];
const SCOPE_TAG = {partial: "Partial: Medicaid or public plans only", enhancement: "Strengthens an existing law"};
const VIEW_NAME = {combined: "breast or lung", breast: "breast", lung: "lung"};
let DATA, view = "combined", selected = null, keyOnly = false;

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const safeUrl = (u) => /^https?:\/\//i.test(u || "") ? u : "#";
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return "source"; } };
const fmtDate = (d) => { const t = new Date(d + "T12:00:00"); return isNaN(t) ? d : t.toLocaleDateString("en-US", {year: "numeric", month: "short", day: "numeric"}); };
const srcLink = (u, label) => `<a href="${esc(safeUrl(u))}" target="_blank" rel="noopener">${esc(label || host(u))} ↗</a>`;
const pill = (st) => `<span class="pill"><i class="sw ${st}"></i>${STATUS[st].label}</span>`;
const stOf = (ab) => DATA.states[ab][view].status;
// Combined view: shaded by composite FIPI (0-10) in fixed bins; breast/lung views keep status colors.
const FIPI_BINS = [{k: "fipi0", min: 0, max: 0, label: "0", long: "No qualifying law"},
  {k: "fipi1", min: 1, max: 2, label: "1–2"}, {k: "fipi2", min: 3, max: 4, label: "3–4"},
  {k: "fipi3", min: 5, max: 6, label: "5–6"}, {k: "fipi4", min: 7, max: 10, label: "7–10"}];
const DOTKEY = (txt) => {
  const n = Object.keys(DATA.states).filter(hasDot).length, on = hiBin === "dot";
  return `<button type="button" class="tile tilebtn dotkey${on ? " on" : ""}" data-bin="dot" aria-pressed="${on}" title="A bill is still moving through the legislature and is not yet law. Click to highlight these states; click again to clear"><i class="keydot"></i><b>${n}</b><span>${txt}</span></button>`;
};
let hiBin = null; // legend bin currently lit up on the combined map (null = none)
const binOf = (n) => FIPI_BINS.find((b) => n >= b.min && n <= b.max) || FIPI_BINS[FIPI_BINS.length - 1];
const keyOf = (ab) => view === "combined" ? binOf(DATA.states[ab].fipi_current.composite).k : stOf(ab);
const hasDot = (ab) => { const v = DATA.states[ab][view]; return v.has_pending && (view === "combined" || ["enacted", "partial"].includes(v.status)); };
const fipiLine = (s) => `FIPI ${s.fipi_current.composite}/10 (breast ${s.fipi_current.breast}, lung ${s.fipi_current.lung})`;
function textOn(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || ""); if (!m) return "#ffffff";
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16) / 255).map((c) => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.3 ? "#1c1c1c" : "#ffffff";
}

async function init() {
  const [site, topo] = await Promise.all([
    fetch("data/site.json", {cache: "no-store"}).then((r) => r.json()),
    fetch("https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-albers-10m.json").then((r) => r.json()).catch(() => null),
  ]);
  DATA = site;
  $("#stamp").textContent = "Last checked " + new Date(site.generated).toLocaleString("en-US", {dateStyle: "medium", timeStyle: "short"});
  $("#asof").textContent = fmtDate(site.baseline_as_of);
  drawTiles();
  if (topo) drawMap(topo); else $("#map").innerHTML = '<p class="muted">The map could not be loaded. Use the table below.</p>';
  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
    view = b.dataset.view; hiBin = null;
    document.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-selected", x === b));
    render();
  }));
  $("#tiles").addEventListener("click", (e) => {
    const t = e.target.closest(".tilebtn"); if (!t) return;
    hiBin = hiBin === t.dataset.bin ? null : t.dataset.bin;
    render();
  });
  const pick = $("#statepick");
  $("#statelist").innerHTML = Object.values(DATA.states).sort((a, b) => a.name.localeCompare(b.name)).map((x) => `<option value="${esc(x.name)}">`).join("");
  const go = () => {
    const q = pick.value.trim().toLowerCase();
    const st = Object.values(DATA.states).find((x) => x.name.toLowerCase() === q || x.abbr.toLowerCase() === q);
    if (st && selected !== st.abbr) { select(st.abbr); pick.blur(); }
  };
  pick.addEventListener("change", go);
  pick.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  pick.addEventListener("focus", () => pick.select());
  $("#keyonly").addEventListener("change", (e) => { keyOnly = e.target.checked; renderFeed(); });
  const h = location.hash.slice(1).toUpperCase();
  if (DATA.states[h]) selected = h;
  render();
}

function drawMap(topo) {
  const svg = d3.select("#map").append("svg").attr("viewBox", "0 0 975 610").attr("role", "img")
    .attr("aria-label", "Map of the United States colored by legislation status or FIPI score");
  const path = d3.geoPath();
  const pat = svg.append("defs").append("pattern").attr("id", "stripe").attr("width", 9).attr("height", 9)
    .attr("patternUnits", "userSpaceOnUse").attr("patternTransform", "rotate(45)");
  pat.append("rect").attr("width", 9).attr("height", 9).attr("class", "stripe-bg");
  pat.append("rect").attr("width", 4.5).attr("height", 9).attr("class", "stripe-fg");
  const feats = topojson.feature(topo, topo.objects.states).features.filter((f) => FIPS[f.id]);
  const tip = $("#tip");
  svg.append("g").selectAll("path").data(feats).join("path")
    .attr("class", "state").attr("d", path).attr("data-ab", (d) => FIPS[d.id])
    .attr("tabindex", 0)
    .on("click", (e, d) => select(FIPS[d.id]))
    .on("keydown", (e, d) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(FIPS[d.id]); } })
    .on("mousemove", (e, d) => {
      const ab = FIPS[d.id], s = DATA.states[ab], v = s[view];
      const ids = view === "combined" ? [...s.breast.bills, ...s.lung.bills] : v.bills;
      const bc = billCount(ids), line = bc.n ? `<br>${bc.n} bill${bc.n > 1 ? "s" : ""}${bc.pending ? ` (${bc.pending} pending)` : ""}` : "";
      tip.innerHTML = view === "combined"
        ? `<b>${esc(s.name)}</b>${fipiLine(s)}` + (v.has_pending ? "<br>Bill pending" : "") + line
        : `<b>${esc(s.name)}</b>${STATUS[v.status].long} (${VIEW_NAME[view]})` +
          (v.has_pending && ["enacted", "partial"].includes(v.status) ? "<br>Another bill is pending" : "") +
          `<br>FIPI score ${s.fipi_current.composite}/10` + line;
      tip.hidden = false;
      tip.style.left = Math.min(e.clientX + 14, innerWidth - 270) + "px";
      tip.style.top = e.clientY + 14 + "px";
    })
    .on("mouseleave", () => { tip.hidden = true; });
  const lab = svg.append("g");
  feats.forEach((f) => {
    const ab = FIPS[f.id];
    if (SMALL.includes(ab)) return;
    const [x, y] = path.centroid(f);
    const off = {FL: [14, 0], LA: [-10, 0], MI: [12, 22], HI: [0, 0], ID: [0, 12], CA: [-8, 0], KY: [6, 2], WV: [-4, 4]}[ab] || [0, 0];
    lab.append("text").attr("class", "slabel").attr("data-ab", ab).attr("x", x + off[0]).attr("y", y + off[1]).text(ab);
    lab.append("circle").attr("class", "pdot").attr("data-dot", ab).attr("cx", x + off[0] + 13).attr("cy", y + off[1] - 9).attr("r", 4.5);
  });
}

function drawTiles() {
  const svg = $("#tilemap");
  if (!svg) return;
  svg.innerHTML = '<defs><pattern id="tstripe" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">' +
    '<rect width="6" height="6" class="stripe-bg"/><rect width="3" height="6" class="stripe-fg"/></pattern></defs>' +
    Object.entries(TILES).filter(([ab]) => DATA.states[ab]).map(([ab, [x, y]]) =>
      `<rect x="${x * 21}" y="${y * 21}" width="18" height="18" rx="3" data-ab="${ab}"><title>${esc(DATA.states[ab].name)}</title></rect>`).join("");
  svg.addEventListener("click", (e) => { const ab = e.target.closest("rect[data-ab]")?.dataset.ab; if (ab) select(ab); });
}

function render() {
  const css = getComputedStyle(document.documentElement);
  const combined = view === "combined";
  const keys = combined ? FIPI_BINS.map((b) => b.k) : ORDER;
  const col = Object.fromEntries(keys.map((k) => [k, css.getPropertyValue("--" + k).trim()]));
  const fill = (ab, stripe) => { const k = keyOf(ab); return k === "partial" ? `url(#${stripe})` : col[k]; };
  const label = (ab) => { const s = DATA.states[ab]; return combined ? `${s.name}: ${fipiLine(s)}` : `${s.name}: ${STATUS[s[view].status].long}`; };
  d3.selectAll(".state").attr("fill", function () { return fill(this.dataset.ab, "stripe"); })
    .classed("sel", function () { return this.dataset.ab === selected; })
    .attr("aria-label", function () { return label(this.dataset.ab); });
  document.querySelectorAll("#tilemap rect[data-ab]").forEach((r) => {
    r.setAttribute("fill", fill(r.dataset.ab, "tstripe"));
    r.classList.toggle("sel", r.dataset.ab === selected);
  });
  d3.selectAll(".slabel").attr("fill", function () {
    const k = keyOf(this.dataset.ab);
    return combined ? textOn(col[k]) : (["pending", "partial"].includes(k) ? "#1c1c1c" : "#ffffff");
  });
  const dimmed = (ab) => hiBin && (hiBin === "dot" ? !hasDot(ab) : keyOf(ab) !== hiBin);
  d3.selectAll(".state").classed("dim", function () { return dimmed(this.dataset.ab); });
  d3.selectAll(".slabel, .pdot").classed("dim", function () { return dimmed(this.dataset.ab || this.dataset.dot); });
  document.querySelectorAll("#tilemap rect[data-ab], .chip").forEach((r) => r.classList.toggle("dim", dimmed(r.dataset.ab)));
  d3.selectAll(".pdot").attr("display", function () { return hasDot(this.dataset.dot) ? null : "none"; });
  $("#chips").innerHTML = SMALL.map((ab) =>
    `<button class="chip${ab === selected ? " sel" : ""}" data-ab="${ab}" title="${esc(label(ab))}">` +
    `<i class="sw ${keyOf(ab)}"></i>${ab}${hasDot(ab) ? " •" : ""}</button>`).join("");
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => select(c.dataset.ab)));
  if (combined) {
    const scores = Object.values(DATA.states).map((s) => s.fipi_current.composite);
    $("#tiles").innerHTML = `<span class="legendlabel">Protection score (FIPI), 0–10 <a class="legendhelp" href="why.html#fipi-h" title="What is FIPI?">What's this?</a><small>Higher = more state protection for follow-up imaging coverage</small></span>` + FIPI_BINS.map((b) =>
      `<button type="button" class="tile tilebtn${hiBin === b.k ? " on" : ""}" data-bin="${b.k}" aria-pressed="${hiBin === b.k}" title="Click to highlight these states; click again to clear"><i class="sw ${b.k}"></i><b>${scores.filter((n) => binOf(n) === b).length}</b><span>${b.label}${b.long ? " · " + b.long : ""}</span></button>`).join("") + DOTKEY("Bill pending, not yet law");
  } else {
    const c = DATA.counts[view];
    $("#tiles").innerHTML = ORDER.map((k) => `<button type="button" class="tile tilebtn${hiBin === k ? " on" : ""}" data-bin="${k}" aria-pressed="${hiBin === k}" title="Click to highlight these states; click again to clear"><i class="sw ${k}"></i><b>${c[k]}</b><span>${STATUS[k].long}</span></button>`).join("") + DOTKEY("Also has a bill pending");
  }
  document.querySelectorAll(".statusbar").forEach((bar) => {
    bar.innerHTML = (combined ? keys : ["enacted", "pending", "died", "none"]).map((k) => `<span class="${k}"></span>`).join("");
  });
  $("#mapnote").textContent = combined
    ? "FIPI (Follow-up Imaging Policy Index) rates how well a state's insurance law covers follow-up imaging after an abnormal breast or lung screening, 0–10. Darker means more protection. A yellow dot means a bill is pending: proposed, not yet law, so the shading doesn't change unless it passes. Click a state for details, or switch to Breast or Lung for law status. 50 states and DC."
    : `Showing ${VIEW_NAME[view]} follow-up imaging. 50 states and DC.`;
  const pk = $("#statepick");
  if (pk && document.activeElement !== pk) pk.value = selected ? DATA.states[selected].name : "";
  renderFeed(); renderDetail(); renderTable(); renderFederal();
}

function select(ab) {
  selected = selected === ab ? null : ab;
  history.replaceState(null, "", selected ? "#" + selected : location.pathname);
  render();
  if (selected) $("#detail").scrollIntoView({behavior: "smooth", block: "nearest"});
}

function renderFeed() {
  let ups = DATA.updates.filter((u) => view === "combined" || u.organs.includes(view));
  if (selected) ups = ups.filter((u) => u.state === selected);
  if (keyOnly) ups = ups.filter((u) => u.major);
  $("#filterline").innerHTML = selected
    ? `Showing ${esc(DATA.states[selected].name)} only. <button id="clearsel">Show all states</button>` : "";
  const cl = $("#clearsel"); if (cl) cl.addEventListener("click", () => select(selected));
  $("#updates").innerHTML = ups.length ? ups.slice(0, 150).map((u) => `
    <li><div class="udate">${fmtDate(u.date)} · <span class="organ">${u.organs.join(" + ")}</span></div>
      <div><button class="linkbtn ubill" data-ab="${esc(u.state)}">${esc(u.state)} ${esc(u.number)}</button></div>
      <div class="utext">${esc(u.text)}</div>
      <div class="usrc">Source: ${srcLink(u.url)}</div></li>`).join("")
    : `<li class="muted">No updates to show${selected ? " for this state" : ""} yet. Updates appear once a bill has been reviewed and approved for tracking.</li>`;
  document.querySelectorAll("#updates .ubill").forEach((b) => b.addEventListener("click", () => {
    if (DATA.states[b.dataset.ab] && selected !== b.dataset.ab) select(b.dataset.ab);
    else if (b.dataset.ab === "US") $("#federalcard").scrollIntoView({behavior: "smooth"});
  }));
}

const ROLE = {primary: "Primary law", secondary: "Secondary law", would_establish: "Would establish coverage", would_expand: "Would expand existing law"};
const dom = (d) => `coverage ${d.coverage}/1, modality breadth ${d.modality}/2, prior authorization ban ${d.prior_auth}/1, biopsy ${d.biopsy}/1`;

function roleLine(b, o) {
  const r = (b.roles || {})[o || b.organs[0]];
  if (!r) return "";
  const enacted = b.status === "enacted";
  const adds = r.adds_text && r.adds_text.length
    ? `${enacted ? "Adds" : "Would add"}: ${esc(r.adds_text.join(", "))} · <b>FIPI ${r.score_after}/5</b>${enacted ? "" : " if enacted"}`
    : (r.reach === "partial" ? "No FIPI points (public plans only)" : (enacted ? "No change in FIPI score" : "No change in FIPI score if enacted"));
  const detail = r.detail ? `; ${esc(r.detail)}` : "";
  return `<div class="kv"><span class="tag role ${r.role}">${ROLE[r.role]}</span>${r.reach === "partial" ? '<span class="tag">Partial: Medicaid or public plans only</span>' : ""} ${adds}${detail}</div>`;
}

const members = (b) => (b.companions || [b.bill_id + ""]).map((i) => DATA.bills[i]).filter(Boolean);
const numOf = (b) => members(b).map((m) => m.number).join(" / ");

function companionBlock(b) {
  const ms = members(b);
  if (ms.length < 2) return "";
  return `<div class="kv"><b>Companion bills</b> (House and Senate versions with the same provisions)</div><ul class="timeline prov">` +
    ms.map((m) => `<li>${srcLink(m.official_url || m.legiscan_url, m.number)} ${pill(m.status)} ${esc(m.stage)} · last action ${fmtDate(m.last_action_date)}, ${esc(m.last_action)}
      ${m.sponsors.length ? `<br><span class="muted">Sponsors (${m.sponsors.length}): ${esc(m.sponsors.slice(0, 5).join("; "))}${m.sponsors.length > 5 ? "; and others" : ""}</span>` : ""}
      <details><summary>${esc(m.number)} history (${m.events.length})</summary><ul class="timeline">${m.events.slice().reverse().map((e) => `<li>${fmtDate(e.date)}: ${esc(e.text)} ${srcLink(e.url, "source")}</li>`).join("")}</ul></details></li>`).join("") + `</ul>`;
}

function relatedBlock(b, o) {
  const rel = (b.related || {})[o || b.organs[0]];
  if (!rel || !rel.length) return "";
  return `<div class="kv"><b>Related bills this session</b> (same title, tracked separately)</div><ul class="timeline prov">` +
    rel.map((r) => { const x = DATA.bills[r.id]; return `<li>${members(x).map((m) => srcLink(m.official_url || m.legiscan_url, m.number)).join(" / ")} ${pill(r.status)} FIPI ${r.score}/5 · ${esc(r.note)}</li>`; }).join("") + `</ul>`;
}

function modLine(b, o) {
  const r = (b.roles || {})[o || b.organs[0]];
  if (!r || r.reach === "partial") return "";
  return `<div class="kv"><b>Modalities named:</b> ${r.modalities && r.modalities.length ? esc(r.modalities.join(", ")) : "none named in the bill"}</div>`;
}

function billCard(id, o) {
  const b = DATA.bills[id];
  const grouped = members(b).length > 1;
  const ev = [];
  for (const k of b.organs) for (const q of (b.classification[k].evidence || [])) ev.push(q);
  const tl = b.events.slice().reverse().map((e) =>
    `<li>${fmtDate(e.date)}: ${esc(e.text)} ${srcLink(e.url, "source")}</li>`).join("");
  return `<div class="bill">
    <h4>${esc(b.state)} ${esc(numOf(b))} ${pill(b.status)} <span class="organ">${b.organs.join(" + ")}</span></h4>
    ${roleLine(b, o)}
    <div class="kv">${esc(b.title)}</div>
    ${modLine(b, o)}
    ${grouped ? companionBlock(b) : `<div class="kv"><b>Stage:</b> ${esc(b.stage)}${b.committee ? " · " + esc(b.committee) : ""}</div>
    <div class="kv"><b>Last action:</b> ${fmtDate(b.last_action_date)}, ${esc(b.last_action)}</div>
    ${b.sponsors.length ? `<div class="kv"><b>Sponsors (${b.sponsors.length}):</b> ${esc(b.sponsors.slice(0, 8).join("; "))}${b.sponsors.length > 8 ? "; and others" : ""}</div>` : ""}
    <div class="kv"><b>Official record:</b> ${srcLink(b.official_url || b.legiscan_url)}${b.text_url ? " · " + srcLink(b.text_url, "bill text") : ""}</div>`}
    ${b.note ? `<div class="kv"><b>Note:</b> ${esc(b.note)}</div>` : ""}
    ${relatedBlock(b, o)}
    ${b.summary ? `<div class="kv">${esc(b.summary)}</div>` : ""}
    ${ev.length ? `<details><summary>Bill language that meets the criteria</summary>${ev.map((q) => `<blockquote>${esc(q)}</blockquote>`).join("")}</details>` : ""}
    ${grouped ? "" : `<details><summary>Full history (${b.events.length})</summary><ul class="timeline">${tl}</ul></details>`}
  </div>`;
}

function organBlock(s, o) {
  const v = s[o];
  let h = `<div><h3>${o === "breast" ? "Breast" : "Lung"} follow-up imaging ${pill(v.status)}</h3>`;
  const corr = v.correction ? `<div class="kv"><b>Related law, not counted:</b> ${esc(v.correction.label)}.</div>
      <div class="kv">${esc(v.correction.reason)}</div>
      <div class="kv"><b>Source:</b> ${v.correction.links.map((l) => srcLink(l.url, l.label) + (l.official ? "" : '<span class="tag">non-official source</span>')).join(" · ") || "not recorded"} · reviewed ${fmtDate(v.correction.date)}</div>
      ${v.correction.text ? `<details><summary>Statutory text</summary><div class="lawtext">${esc(v.correction.text)}</div></details>` : ""}` : "";
  if (!v.law && !v.bills.length) return h + `<p class="muted">No qualifying law or bill found.</p>${corr}</div>`;
  h += corr;
  h += `<div class="kv"><b>FIPI ${o} score:</b> ${v.score}/5 — ${dom(v.domains)}</div>`;
  const steps = v.timeline.map((t) => {
    const b = DATA.bills[t.id];
    return `<li><span class="tag role ${t.role}">${ROLE[t.role]}</span>${t.reach === "partial" ? '<span class="tag">partial</span>' : ""}
      ${srcLink(b.official_url || b.legiscan_url, `${t.number}`)} · enacted ${fmtDate(t.date)} ·
      ${t.adds_text.length ? esc(t.adds_text.join(", ")) : "no change in FIPI score"}${t.detail ? "; " + esc(t.detail) : ""} · score ${t.score_after}/5</li>`;
  });
  if (v.law && !v.has_tracked_primary) steps.unshift(`<li><span class="tag role primary">Primary law</span> Identified in the study's review of the statute; the establishing bill has not been matched yet.</li>`);
  if (v.study_gap.length && v.has_tracked_primary) steps.push(`<li><span class="tag">Study review</span> ${esc(v.study_gap.join(", "))} from the study's hand scoring of the statute, not attributed to a tracked bill.</li>`);
  if (steps.length) h += `<div class="kv"><b>How the score was earned</b></div><ul class="timeline prov">${steps.join("")}</ul>`;
  if (v.law) {
    h += `<details><summary>Statute reviewed in the study (score ${s.fipi[o]}/5)</summary>
      <div class="kv">${dom(v.law.domains)}</div>
      ${v.law.modalities.length ? `<div class="kv"><b>Modalities named:</b> ${esc(v.law.modalities.join(", "))}</div>` : ""}
      ${v.law.notes ? `<div class="kv"><b>Note:</b> ${esc(v.law.notes)}</div>` : ""}
      <div class="kv"><b>Source:</b> ${v.law.links.map((l) => srcLink(l.url, l.label) + (l.official ? "" : '<span class="tag">non-official source</span>')).join(" · ") || "see the official records of the laws listed above"}</div>
      ${v.law.text ? `<div class="lawtext">${esc(v.law.text)}</div>` : ""}</details>`;
  }
  const isPub = (id) => ((DATA.bills[id].roles || {})[o] || {}).reach === "partial";
  const when = (id) => (v.timeline.find((t) => t.id === id) || {}).date || DATA.bills[id].status_date || "";
  const laws = v.bills.filter((id) => DATA.bills[id].status === "enacted" && !isPub(id)).sort((a, b) => when(a).localeCompare(when(b)));
  const pub = v.bills.filter(isPub).sort((a, b) => when(a).localeCompare(when(b)));
  const current = v.bills.filter((id) => DATA.bills[id].status === "pending" && !isPub(id));
  const past = v.bills.filter((id) => DATA.bills[id].status === "died" && !isPub(id))
    .sort((a, b) => ((DATA.bills[b].roles || {})[o] || {}).score_after - ((DATA.bills[a].roles || {})[o] || {}).score_after
      || (DATA.bills[b].last_action_date || "").localeCompare(DATA.bills[a].last_action_date || ""));
  if (laws.length) h += `<div class="kv"><b>Enacted laws</b> (oldest first)</div>` + laws.map((id) => billCard(id, o)).join("");
  if (current.length) h += `<div class="kv curbills"><b>Current bills</b></div>` + current.map((id) => billCard(id, o)).join("");
  if (past.length) {
    h += `<div class="kv"><b>Past efforts (${past.length})</b></div><ul class="timeline prov">` + past.map((id) => {
      const b = DATA.bills[id];
      const r = (b.roles || {})[o];
      return `<li>${members(b).map((m) => srcLink(m.official_url || m.legiscan_url, m.number)).join(" / ")} · ${esc(b.session)} · <b>${esc(b.stage)}</b>, ${fmtDate(b.last_action_date)}${r ? ` · would have scored ${r.score_after}/5` : ""}</li>`;
    }).join("") + `</ul><details><summary>Details of past efforts</summary>${past.map((id) => billCard(id, o)).join("")}</details>`;
  }
  if (pub.length) h += `<div class="kv"><b>Public-plan measures*</b></div><p class="muted">*Apply only to Medicaid, another public program or public-employee plans. They are not counted in the FIPI score.</p>
    <details><summary>${pub.length} public-plan measure${pub.length > 1 ? "s" : ""}: ${pub.map((id) => esc(numOf(DATA.bills[id])) + " (" + STATUS[DATA.bills[id].status].label.toLowerCase() + ")").join(", ")}</summary>${pub.map((id) => billCard(id, o)).join("")}</details>`;
  return h + "</div>";
}

function organSummary(o, v) {
  const nm = o === "breast" ? "breast" : "lung";
  if (v.score > 0) {
    const d = v.domains, parts = [];
    if (d.coverage) parts.push("requires follow-up imaging to be covered with no deductible or copay");
    if (d.modality) parts.push(d.modality === 2 ? "names a broad range of scans" : "names some of the scans patients may need");
    if (d.prior_auth) parts.push("bans prior authorization");
    if (d.biopsy) parts.push("covers biopsy without cost-sharing");
    const list = parts.length > 1 ? parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1] : parts[0];
    return `for ${nm} imaging, state law ${list}`;
  }
  if (v.status === "partial") return `${nm} protections apply only to public plans such as Medicaid`;
  if (v.status === "supplemental") return `${nm} law covers screening only, not follow-up imaging`;
  return `no qualifying ${nm} follow-up imaging law was found`;
}
function stateSummary(s, organs) {
  const parts = organs.map((o) => organSummary(o, s[o]));
  const pend = organs.some((o) => s[o].has_pending);
  const body = organs.length === 2 ? `${esc(s.name)}: ${esc(parts[0])}; ${esc(parts[1])}.` : `${esc(s.name)}: ${esc(parts[0])}.`;
  return `<p class="plain">${body}${pend ? ` A bill that could change this is pending. <button type="button" class="linkbtn" data-jump="bills">See pending bill details</button>` : ""}</p>`;
}
function whyBlock(s, organs) {
  const mark = (got, max) => got >= max ? ["yes", "✓", "met"] : got > 0 ? ["part", "◐", "partly met"] : ["no", "✗", "not met"];
  const rows = [["coverage", "No-cost coverage", 1], ["modality", "Range of scans named", 2], ["prior_auth", "No prior authorization", 1], ["biopsy", "Biopsy covered", 1]];
  const cols = organs.map((o) => `<div><h4>${o === "breast" ? "Breast" : "Lung"}: ${s[o].score}/5</h4><ul class="checks">` + rows.map(([k, lab, max]) => {
    const g = s[o].domains[k], [c, sym, w] = mark(g, max);
    return `<li class="${c}"><span aria-hidden="true">${sym}</span> ${lab} <span class="muted">${g}/${max}, ${w}</span></li>`;
  }).join("") + `</ul></div>`).join("");
  const head = view === "combined"
    ? `Why is ${esc(s.name)} ${esc(binOf(s.fipi_current.composite).label === "0" ? "gray" : "this color")}? Breast and lung scores add up to ${s.fipi_current.composite}/10 (shade ${esc(binOf(s.fipi_current.composite).label)}).`
    : `How ${esc(s.name)}'s FIPI score is built`;
  return `<div class="why"><h3>${head}</h3><div class="cols">${cols}</div>
    <p class="muted">Each cancer scores up to 5 points. <a href="why.html#fipi-h">How FIPI works</a></p></div>`;
}

function renderDetail() {
  const el = $("#detail");
  if (!selected) { el.innerHTML = '<p class="muted">Select a state on the map or in the table to see its laws, bills and sources.</p>'; return; }
  const s = DATA.states[selected];
  const organs = view === "combined" ? ["breast", "lung"] : [view];
  el.innerHTML = `<h2>${esc(s.name)}</h2><div class="kv">Current FIPI score <b>${s.fipi_current.composite}/10</b> (breast ${s.fipi_current.breast}/5, lung ${s.fipi_current.lung}/5)${s.fipi_current.composite !== s.fipi.composite ? `; ${s.fipi.composite}/10 in the original study` : ""}</div>
    ${stateSummary(s, organs)}${whyBlock(s, organs)}
    <div class="cols">${organs.map((o) => organBlock(s, o)).join("")}</div>`;
  el.querySelectorAll("[data-jump]").forEach((b) => b.addEventListener("click", () => {
    const t = el.querySelector(".curbills") || el.querySelector(".bill"); if (t) t.scrollIntoView({behavior: "smooth", block: "start"});
  }));
}

// Bills on record for a state (enacted, died and pending); only pending ones are still moving.
function billCount(ids) {
  const uniq = [...new Set(ids.map(String))];
  return {n: uniq.length, pending: uniq.filter((id) => (DATA.bills[id] || {}).status === "pending").length};
}

function renderTable() {
  const rows = Object.values(DATA.states).sort((a, b) => a.name.localeCompare(b.name));
  $("#table tbody").innerHTML = rows.map((s) => {
    const {n, pending} = billCount([...s.breast.bills, ...s.lung.bills]);
    const cell = n + (pending ? ` <span class="muted">(${pending} pending)</span>` : "");
    return `<tr data-ab="${s.abbr}"><td>${esc(s.name)}</td><td>${pill(s.breast.status)}</td><td>${pill(s.lung.status)}</td><td class="num">${s.fipi_current.composite}</td><td class="num">${cell}</td></tr>`;
  }).join("");
  document.querySelectorAll("#table tbody tr").forEach((r) => r.addEventListener("click", () => { if (selected !== r.dataset.ab) select(r.dataset.ab); }));
}

function renderFederal() {
  const ids = DATA.federal.filter((id) => view === "combined" || DATA.bills[id].organs.includes(view));
  $("#federal").innerHTML = ids.length ? ids.map((id) => billCard(id)).join("")
    : '<p class="muted">No qualifying federal bill is being tracked. Federal sources link to congress.gov.</p>';
  if (ids.length) $("#federal").insertAdjacentHTML("afterbegin", '<p class="muted">Scores show what each bill would earn on the FIPI rubric if enacted. A federal law would apply in every state; state scores on the map do not include pending federal bills.</p>');
}

matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => DATA && render());
init().catch((e) => { document.querySelector("main").insertAdjacentHTML("afterbegin", `<p class="card wide">Could not load tracker data: ${esc(e.message)}</p>`); });

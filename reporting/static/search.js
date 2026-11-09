// The search box (SPEC Milestone 9, section 0). No libraries and no requests. Rows come from the
// JSON block #search-data, where Python has already worked out each row's keys with
// tracker.search_key. This script normalizes only the typed text, the same way. Everything is
// drawn with createElement and textContent: tracker text is never parsed as HTML.
"use strict";

var SHARP_S = String.fromCharCode(0xdf), FINAL_SIGMA = String.fromCharCode(0x3c2);
var SIGMA = String.fromCharCode(0x3c3);
var MIN_CHARS = 2, COMPANIES_SHOWN = 5, TOP_SHOWN = 3;

// tracker.search_key: casefold, anything but letters, digits and _ as spaces, trailing company
// suffixes dropped (a name that is only a suffix stays).
function normalize(text, suffixes) {
  var words = String(text || "").toLowerCase().split(SHARP_S).join("ss").split(FINAL_SIGMA).join(SIGMA)
    .replace(/[^\p{L}\p{N}_]+/gu, " ").trim().split(" ").filter(Boolean);
  while (words.length > 1 && suffixes.indexOf(words[words.length - 1]) >= 0) words.pop();
  return words.join(" ");
}

function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }

function sortable(applied) { // "10/27/2026" -> 20261027; no date -> 0
  var p = applied.split("/");
  return p.length === 3 ? Number(p[2] + p[0] + p[1]) : 0;
}

function el(tag, cls, text) {
  var node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function pill(cls, text) { return el("span", "pill " + cls, text); }

function counts(rows) {
  var r = 0, x = 0, k = 0;
  rows.forEach(function (row) {
    if (row.stage) r++;
    if (row.outcome === "Rejected") x++;
    if (!row.stage && row.outcome !== "Rejected") k++;
  });
  return { n: rows.length, responses: r, rejected: x, noReply: k };
}

// Rows in a collapsed table. Columns: [header, function(row) -> text or node].
function rowsTable(rows, columns) {
  var details = el("details"), table = el("table"), head = el("tr"), body = el("tbody");
  details.appendChild(el("summary", "", "Show " + plural(rows.length, "row")));
  columns.forEach(function (c) { head.appendChild(el("th", "", c[0])); });
  table.appendChild(el("thead")).appendChild(head);
  rows.forEach(function (row) {
    var tr = el("tr");
    columns.forEach(function (c) {
      var td = el("td"), value = c[1](row);
      if (typeof value === "string") td.textContent = value; else if (value) td.appendChild(value);
      tr.appendChild(td);
    });
    body.appendChild(tr);
    if (row.remarks.length) body.appendChild(remarkRow(row.remarks, columns.length));
  });
  table.appendChild(body);
  var wrap = el("div", "table-wrap");
  wrap.appendChild(table);
  details.appendChild(wrap);
  return details;
}

// A closed "Remarks" toggle under a row, one note per line.
function remarkRow(lines, span) {
  var tr = el("tr", "remark-row"), td = el("td"), details = el("details");
  td.colSpan = span;
  details.appendChild(el("summary", "", "Remarks"));
  lines.forEach(function (line) { details.appendChild(el("div", "remark", line)); });
  td.appendChild(details);
  tr.appendChild(td);
  return tr;
}

function outcomeCell(row) { return pill(row.outcome_cls, row.outcome); }
function stageCell(row) { return row.stage ? pill("stage", row.stage) : null; }
function linkCell(row) {
  if (!/^https?:\/\//.test(row.href)) return null;
  var a = el("a", "", row.domain);
  a.href = row.href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

function companyCard(rows) {
  var c = counts(rows), card = el("article", "card search-card"), line = el("p", "search-line");
  line.appendChild(el("strong", "", rows[0].company));
  line.appendChild(document.createTextNode(" · " + plural(c.n, "application") + " · " +
    plural(c.responses, "response") + " · " + c.rejected + " rejected · " + c.noReply + " no reply"));
  card.appendChild(line);
  card.appendChild(el("p", "note", "Last applied " + (rows[0].applied || "unknown")));
  card.appendChild(rowsTable(rows, [["Position", function (r) { return r.position; }],
    ["Applied", function (r) { return r.applied; }], ["Outcome", outcomeCell], ["Stage", stageCell],
    ["Link", linkCell]]));
  return card;
}

function titleCard(text, rows) {
  var c = counts(rows), card = el("article", "card search-card"), line = el("p", "search-line");
  line.appendChild(el("strong", "", "\"" + text + "\" in title"));
  line.appendChild(document.createTextNode(" · " + plural(c.n, "application") + " · " +
    plural(c.responses, "response") + " · " + c.rejected + " rejected"));
  card.appendChild(line);
  var top = groups(rows).slice(0, TOP_SHOWN).map(function (g) { return g[0].company + " " + g.length; });
  card.appendChild(el("p", "note", "Top companies: " + top.join(" · ")));
  card.appendChild(rowsTable(rows, [["Company", function (r) { return r.company; }],
    ["Position", function (r) { return r.position; }], ["Applied", function (r) { return r.applied; }],
    ["Outcome", outcomeCell], ["Stage", stageCell]]));
  return card;
}

// Rows by company key, most applications first; ties: most recent application, then name (as Top 10).
// Rows arrive newest first, so each group's first row is its newest.
function groups(rows) {
  var byKey = {}, order = [];
  rows.forEach(function (row) {
    if (!row.company_key) return;
    if (!byKey[row.company_key]) { byKey[row.company_key] = []; order.push(row.company_key); }
    byKey[row.company_key].push(row);
  });
  return order.map(function (k) { return byKey[k]; }).sort(function (a, b) {
    return b.length - a.length || sortable(b[0].applied) - sortable(a[0].applied) ||
      (a[0].company < b[0].company ? -1 : a[0].company > b[0].company ? 1 : 0);
  });
}

function search(data, typed) {
  var key = normalize(typed, data.suffixes), out = [];
  if (key.length < MIN_CHARS) return out;
  var text = typed.trim();
  var companies = groups(data.rows.filter(function (r) { return r.company_key.indexOf(key) >= 0; }));
  var titled = data.rows.filter(function (r) { return r.position_key.indexOf(key) >= 0; });
  companies.slice(0, COMPANIES_SHOWN).forEach(function (g) { out.push(companyCard(g)); });
  if (companies.length > COMPANIES_SHOWN) out.push(el("p", "note", "+" + (companies.length - COMPANIES_SHOWN) + " more"));
  if (titled.length) out.push(titleCard(text, titled));
  if (!out.length) out.push(el("p", "calm", "No applications match \"" + text + "\"."));
  return out;
}

if (typeof document !== "undefined") {
  (function () {
    var section = document.getElementById("search"), box = document.getElementById("search-box");
    var results = document.getElementById("search-results");
    var data = JSON.parse(document.getElementById("search-data").textContent);
    function show() {
      results.replaceChildren.apply(results, search(data, box.value));
    }
    box.addEventListener("input", show);
    box.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { box.value = ""; show(); }
    });
    section.hidden = false;
  })();
}

if (typeof module !== "undefined") module.exports = { normalize: normalize };

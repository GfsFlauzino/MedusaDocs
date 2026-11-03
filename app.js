"use strict";
/* Aplicação única (leitura + edição) com login e perfis:
   Visualizador → playbooks em Homologação e Produção, só leitura
   Editor       → todos os playbooks, criação, edição e mudança de status
   Administrador→ tudo do editor + usuários, auditoria e exclusão de playbooks
   As permissões valem no servidor; aqui só escondemos o que o perfil não pode usar. */
const App = { data: null, user: null };
/* PBS: resumos de todos os playbooks visíveis (lista leve de /api/library: nome, status, versão, contagens).
   DETAIL: documentos completos já abertos (/api/doc/{id}), buscados sob demanda ao abrir um playbook. */
let PBS = [], TEAMS = {};
const DETAIL = new Map();
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pbBy = slug => PBS.find(p => p.slug === slug);
const norm = s => String(s || "").normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
const TEAM_COLOR = n => (TEAMS[n] && TEAMS[n].color) || "#5B6673";
const TEAM_ORDER = ["SOC N1", "SOC N2", "CSIRT"];
/* permissões da role do usuário ("área.ação", ex.: playbook.edit); o servidor confere de novo em cada chamada */
const can = p => !!App.user && (App.user.permissions || []).includes(p);
const canAny = (...ps) => ps.some(can);
const ADMIN_PERMS = ["users.manage", "roles.manage", "audit.view", "logs.manage", "sso.manage", "branding.edit", "app.reset"];
const canAdmin = () => canAny(...ADMIN_PERMS);
const STATUS_CLS = { "Desenvolvimento": "dev", "Homologação": "hml", "Produção": "prd" };
/* tipos de documento (o servidor manda o registro em /api/bootstrap); rota da biblioteca de cada um */
const TYPE_ROUTE = { playbook: "", runbook: "runbooks", doc: "documentos" };
const ROUTE_TYPE = { runbooks: "runbook", documentos: "doc" };
const typeInfo = t => (App.data && App.data.types && App.data.types[t]) || { label: "Playbook", plural: "Playbooks", flow: "required", steps: true, ramos: true, approval: true, folders: false };
const typeOfId = id => /^RB-/i.test(id) ? "runbook" : /^DOC-/i.test(id) ? "doc" : "playbook";
const statusPill = (st, t) => `<span class="status ${STATUS_CLS[st] || "dev"}">${esc(statusLabel(t, st))}</span>`;

/* ───────── API ───────── */
class ApiError extends Error { constructor(msg, status) { super(msg); this.status = status; } }
async function api(method, url, body, opts = {}) {
  const r = await fetch(url, {
    method, credentials: "same-origin", signal: opts.signal,
    headers: { "Content-Type": "application/json", "X-Requested-With": "playbooks" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  /* sessão vencida no meio da edição: o rascunho é guardado antes de fechar o editor (volta depois do login) */
  if (r.status === 401 && App.user && !url.endsWith("api/login")) {
    Editor.stash(); const kept = Editor.hasDraft(); Editor.dirty = false; Editor.unmount();
    showLogin(`Sua sessão expirou. Entre de novo para continuar de onde parou${kept ? "; as alterações não salvas foram guardadas e voltam ao abrir o editor" : ""}.`);
  }
  if (r.status === 403 && /senha temporária/.test(j.error || "")) forcePassword();
  if (!r.ok) throw new ApiError(j.error || `Erro ${r.status}`, r.status);
  return j;
}

/* dados de abertura (/api/bootstrap): catálogo do fluxograma, status e times; a lista vem de refreshIndex() */
function setData(d) {
  App.data = { catalog: d.catalog, statuses: d.statuses, teams: d.teams, types: d.types, enabledTypes: d.enabledTypes || ["playbook"] }; TEAMS = d.teams;
  Flow.setCatalog(d.catalog); buildRefRegex();
}
const byId = (a, b) => a.id.localeCompare(b.id, undefined, { numeric: true });
/* resumo montado no navegador a partir do documento completo (mesmos campos de /api/library) */
function summaryOf(v) {
  const g = v.gov, props = v.props || {};
  return { id: v.id, type: v.type || "playbook", slug: v.slug, name: v.name, status: g.status, version: (props["Versão"] || "").split(" ")[0],
    hasFlow: v.hasFlow !== false, fields: (PBS.find(p => p.id === v.id) || {}).fields || {},
    templateKey: v.templateKey, templateName: v.templateName, reviewed: g.reviewed || "", reviewer: g.reviewer || "", approver: g.approver || "",
    gov: g, ramos: v.ramos.length, steps: v.steps.length, rev: v.rev, subtitle: props["Tática MITRE principal"] || props["Fase NIST"] || "",
    mitre: props["Tática MITRE principal"] || "", teams: teamsOf(v.flow) };
}
/* times (raias de time) com ao menos uma caixa no fluxograma, como em library.teams_of */
const teamsOf = flow => !flow ? [] : (flow.lanes || []).filter(l => l.kind === "team" && (flow.nodes || []).some(n => n.lane === l.key))
  .map(l => ({ name: l.team || l.label, color: l.color }));
/* lista leve completa (paginada no servidor; o navegador revalida com ETag e recebe 304 quando nada mudou) */
async function refreshIndex() {
  let all = [], cursor = "";
  do {
    const r = await api("GET", `api/library?limit=500${cursor ? "&cursor=" + cursor : ""}`);
    all = all.concat(r.items); cursor = r.nextCursor;
  } while (cursor);
  PBS = all;
  for (const id of [...DETAIL.keys()]) if (!PBS.some(p => p.id === id)) DETAIL.delete(id);
}
/* documento completo; reaproveita o já aberto se a revisão for a mesma do resumo */
async function ensureDetail(slug) {
  const s = pbBy(slug); if (!s) return null;
  const d = DETAIL.get(s.id);
  if (d && d.rev === s.rev) return d;
  const r = await api("GET", `api/doc/${s.id}`);
  replacePlaybook(r.playbook);
  return r.playbook;
}
function replacePlaybook(pb) {
  DETAIL.set(pb.id, pb);
  const sm = summaryOf(pb), i = PBS.findIndex(p => p.id === pb.id);
  if (i >= 0) PBS[i] = sm; else { PBS.push(sm); PBS.sort(byId); }
}
function removePlaybook(id) { PBS = PBS.filter(p => p.id !== id); DETAIL.delete(id); }
function setTeams(t) { TEAMS = t; App.data.teams = t; buildRefRegex(); }
/* times do playbook = times do template dele (prevalecem) + os dos demais templates */
function useTeams(pb) { TEAMS = Object.assign({}, App.data.teams, (pb && pb.teams) || {}); buildRefRegex(); }
async function refreshData() { try { DETAIL.clear(); await refreshIndex(); } catch { } route(); }

function toast(msg, kind = "ok") {
  const t = document.createElement("div");
  t.className = "toast " + kind; t.textContent = msg;
  document.body.append(t);
  setTimeout(() => t.classList.add("out"), 3200);
  setTimeout(() => t.remove(), 3700);
}

/* ───────── marca (nome do workspace e logo) e tema ───────── */
/* O visual é fixo (tema claro ou escuro, escolhido por cada usuário). O administrador muda só o nome do workspace
   e a logo. Cores e textos de marca antigos que estejam no banco são ignorados. */
const Brand = (() => {
  const DEFAULT = { name: "Medusa Docs", logo: null, contact: "" };
  let cur = { ...DEFAULT };
  const markHtml = b => b.logo ? `<img src="api/branding/logo?v=${encodeURIComponent(b.logo)}" alt="">` : "";
  function paint(b) {
    document.title = b.name;
    $("#brandName").textContent = b.name;
    $("#brand").title = `${b.name} · página inicial`;   // nome longo truncado continua legível
    const mark = $("#brandMark");
    mark.className = "brand-mark " + (b.logo ? "has-logo" : "default");
    mark.innerHTML = markHtml(b);
    /* com logo: a logo sozinha em cima e o nome do workspace embaixo (logos têm proporções variadas e não alinham
       bem com texto ao lado); sem logo: símbolo padrão e nome na mesma linha */
    $("#brand").classList.toggle("with-logo", !!b.logo);
    document.querySelectorAll(".login-brand").forEach(n => { n.innerHTML = loginBrand(); n.classList.toggle("with-logo", !!b.logo); });
  }
  const loginBrand = () => `<span class="brand-mark ${cur.logo ? "has-logo" : "default"}">${markHtml(cur)}</span><span class="bname">${esc(cur.name)}</span>`;
  function apply(b) {
    cur = { ...DEFAULT, name: (b && b.name) || DEFAULT.name, logo: (b && b.logo) || null, contact: (b && b.contact) || "", appVersion: b && b.appVersion };
    paint(cur);
    try { localStorage.setItem("medusa-brand", JSON.stringify({ name: cur.name })); } catch { }
  }
  async function load() { try { apply(await api("GET", "api/branding")); } catch { apply(cur); } }
  return { load, apply, get: () => cur, DEFAULT, loginBrand };
})();
$("#themeTgl").onclick = () => {
  const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("medusa-theme", t); } catch { }
};

/* ───────── modal ───────── */
let modalSeq = 0;
function modal({ title, html, wide, onMount, onClose, dismissable = true }) {
  const bg = document.createElement("div"), tid = `mt${++modalSeq}`, opener = document.activeElement;
  bg.className = "modal-bg";
  bg.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="${tid}"><div class="mhead"><b id="${tid}">${title}</b>${dismissable ? `<button class="mclose" title="Fechar" aria-label="Fechar">${ic("close")}</button>` : ""}</div><div class="mbody">${html}</div></div>`;
  document.body.append(bg);
  /* ao fechar, o foco volta para quem abriu (se ele ainda existe); Tab fica preso dentro do diálogo */
  const close = () => {
    if (!bg.isConnected) return; bg.remove(); document.removeEventListener("keydown", onKey); if (onClose) onClose();
    if (opener && opener.isConnected && opener.focus) opener.focus();
  };
  const onKey = e => {
    if (e.key === "Escape" && dismissable && bg === [...document.querySelectorAll(".modal-bg")].pop()) close();
    if (e.key !== "Tab" || !bg.contains(document.activeElement)) return;
    const f = [...bg.querySelectorAll("button, a[href], input, select, textarea, [tabindex]:not([tabindex='-1'])")].filter(x => !x.disabled && !x.hidden && x.offsetParent);
    if (!f.length) return;
    if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  };
  document.addEventListener("keydown", onKey);
  if (dismissable) { bg.querySelector(".mclose").onclick = close; bg.addEventListener("mousedown", e => { if (e.target === bg) close(); }); }
  const first = bg.querySelector("input, select, textarea, button.btn"); if (first) setTimeout(() => first.focus(), 30);
  if (onMount) onMount(bg.querySelector(".mbody"), close);
  return close;
}

/* Confirmação dentro da aplicação. Substitui o confirm() do navegador, que em alguns navegadores embutidos
   não aparece e responde "Cancelar" sozinho (o botão parecia não funcionar). Retorna uma Promise<boolean>. */
function ask(message, { title = "Confirmar", ok = "Confirmar", cancel = "Cancelar", danger = false } = {}) {
  return new Promise(resolve => {
    let answered = false;
    const done = v => { if (!answered) { answered = true; resolve(v); } };
    modal({ title, html: `<div class="ask-msg">${esc(message).replace(/\n/g, "<br>")}</div>
      <div class="create-actions"><button type="button" class="btn ghost" data-no>${esc(cancel)}</button><button type="button" class="btn ${danger ? "danger solid" : "primary"}" data-yes>${esc(ok)}</button></div>`,
      onClose: () => done(false),
      onMount: (b, close) => {
        b.querySelector("[data-no]").onclick = () => close();
        b.querySelector("[data-yes]").onclick = () => { done(true); close(); };
        /* em ação perigosa, Enter não pode confirmar sem querer: o foco começa em Cancelar */
        setTimeout(() => b.querySelector(danger ? "[data-no]" : "[data-yes]").focus(), 40);
      } });
  });
}

/* imagens do documento: clique amplia */
function lightbox(img) {
  const cap = img.closest("figure") && img.closest("figure").querySelector("figcaption");
  const bg = document.createElement("div");
  bg.className = "lightbox"; bg.setAttribute("role", "dialog"); bg.setAttribute("aria-modal", "true");
  bg.innerHTML = `<figure><img src="${esc(img.getAttribute("src"))}" alt="${esc(img.alt)}">${cap ? `<figcaption>${esc(cap.textContent)}</figcaption>` : ""}</figure><button class="mclose" title="Fechar (Esc)" aria-label="Fechar">${ic("close")}</button>`;
  const close = () => { bg.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = e => { if (e.key === "Escape") close(); };
  bg.onclick = close; document.addEventListener("keydown", onKey);
  document.body.append(bg);
}
document.addEventListener("click", e => { const im = e.target.closest(".docimg img"); if (im) { e.preventDefault(); lightbox(im); } });

/* ───────── refs clicáveis em texto ───────── */
let REF_SRC = "", REF_TEST = /$^/;
function buildRefRegex() {
  const names = Object.keys(TEAMS).sort((a, b) => b.length - a.length).map(n => n.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&"));
  REF_SRC = `(?<![\\w/])(ER\\d+|[TAICPH]\\d+|R\\d+|E[1-5]|(?:PB|RB|DOC)-\\d+|${names.concat(["N1", "N2"]).join("|")})(?![\\w/])`;
  REF_TEST = new RegExp(REF_SRC);
}

function classify(tok, pb) {
  if (/^(PB|RB|DOC)-\d+$/.test(tok)) return { kind: "pb", id: tok };
  if (TEAMS[tok]) return { kind: "team", id: tok };
  if (tok === "N1" || tok === "N2") return { kind: "team", id: "SOC " + tok };
  if (!pb) return null;
  if (/^R\d+$/.test(tok)) return pb.ramos.some(r => r.id === tok) ? { kind: "ramo", id: tok } : null;
  if (/^E[1-5]$/.test(tok)) return pb.states.some(s => s.id === tok) ? { kind: "state", id: tok } : null;
  return pb.steps.some(s => s.id === tok) ? { kind: "step", id: tok } : null;
}

function linkify(root, pb) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      for (let p = n.parentNode; p && p !== root; p = p.parentNode)
        if (/^(BUTTON|A|CODE|PRE|SCRIPT|svg|TEXTAREA|INPUT)$/i.test(p.nodeName) || (p.classList && (p.classList.contains("ref") || p.classList.contains("sid") || p.classList.contains("nolink")))) return NodeFilter.FILTER_REJECT;
      return REF_TEST.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    }
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const n of nodes) {
    const txt = n.nodeValue, frag = document.createDocumentFragment();
    let last = 0;
    txt.replace(new RegExp(REF_SRC, "g"), (tok, _g, off) => {
      const info = classify(tok, pb);
      if (!info || (info.kind === "pb" && pb && info.id === pb.id)) return tok;
      frag.append(txt.slice(last, off));
      const b = document.createElement("button");
      b.className = "ref " + info.kind; b.textContent = tok;
      b.dataset.kind = info.kind; b.dataset.id = info.id;
      if (info.kind === "pb" && !PBS.some(p => p.id === info.id)) { b.classList.add("dead"); b.title = "Documento não disponível para a sua role ou ainda não criado"; }
      frag.append(b); last = off + tok.length; return tok;
    });
    frag.append(txt.slice(last));
    n.replaceWith(frag);
  }
}

/* blocos de código: botão Copiar (leitura, versões e prévias) */
document.addEventListener("click", e => {
  const b = e.target.closest(".code-copy"); if (!b) return;
  const pre = b.parentNode.querySelector("pre"); if (!pre) return;
  navigator.clipboard.writeText(pre.innerText).then(() => { b.textContent = "Copiado"; setTimeout(() => { b.textContent = "Copiar"; }, 1500); },
    () => toast("Selecione o código e copie manualmente", "warn"));
});

document.addEventListener("click", e => {
  const b = e.target.closest("button.ref");
  if (!b) return;
  const pb = currentPb();
  const { kind, id } = b.dataset;
  if (kind === "pb") {
    const t = PBS.find(p => p.id === id);
    if (t) { closeDrawer(); location.hash = `#/${t.slug}/${t.type === "playbook" ? "fluxo" : "doc"}`; }
    return;
  }
  if (kind === "team") return showTeam(pb, id, true);
  if (pb) showRefs(pb, [id], id, true);
});

/* ───────── gaveta ───────── */
const drawer = $("#drawer"), scrim = $("#scrim"), dbody = $("#dbody"), dtitle = $("#dtitle");
let stack = [];
function pushView(title, html, pb, after) { stack.push({ title, html, pb, after }); paintDrawer(); }
function paintDrawer() {
  const v = stack[stack.length - 1];
  if (!v) return closeDrawer();
  drawer.hidden = scrim.hidden = false;
  dtitle.innerHTML = v.title;
  dbody.innerHTML = v.html; dbody.scrollTop = 0;
  linkify(dbody, v.pb);
  if (v.after) v.after(dbody);
  $("#dback").disabled = stack.length < 2;
}
function closeDrawer() {
  stack = [];
  drawer.hidden = scrim.hidden = true;
  document.querySelectorAll(".viewer svg .node.sel").forEach(n => n.classList.remove("sel"));
}
$("#dclose").onclick = closeDrawer;
scrim.onclick = closeDrawer;
$("#dback").onclick = () => { stack.pop(); paintDrawer(); };

function teamChip(name) {
  if (!name) return "";
  return `<button class="chip team" style="background:${TEAM_COLOR(name)}" data-team="${esc(name)}">${esc(name)}</button>`;
}
document.addEventListener("click", e => {
  const b = e.target.closest("[data-team]");
  if (!b || b.closest(".node") || b.closest(".fe-canvas") || b.closest(".modal")) return;
  showTeam(currentPb(), b.dataset.team, !b.closest("svg"));
});

function stepCard(s) {
  return `<div class="dcard"><div class="sub"><span class="sid">${esc(s.id)}</span>${esc(s.phase)} ${teamChip(s.team)}</div>
    <div class="lbl">Ação</div><div>${esc(s.action)}</div>
    <div class="lbl">Critério de saída</div><div>${esc(s.exit)}</div></div>`;
}
function stateCard(st) {
  return `<div class="dcard"><div class="sub"><span class="sid st">${st.id}</span>${esc(st.name)}</div>
    <div class="lbl">Definição</div><div>${esc(st.def)}</div>
    <div class="lbl">Destino</div><div>${esc(st.dest)}</div>
    <div class="lbl">Prioridade</div><div>${esc(st.prio)}</div></div>`;
}
const findSection = (pb, id) => pb.sections.find(s => s.id === id);

function refHtml(pb, ref) {
  if (ref.startsWith("sec:")) {
    const s = findSection(pb, ref.slice(4));
    return s ? `<div class="dcard md"><b>${esc(s.title)}</b>${s.html}</div>` : "";
  }
  const step = pb.steps.find(s => s.id === ref);
  if (step) return stepCard(step);
  const ramo = pb.ramos.find(r => r.id === ref);
  if (ramo) return `<div class="md">${ramo.html}</div>`;
  const st = pb.states.find(s => s.id === ref);
  if (st) return stateCard(st);
  return `<div class="empty">Referência <b>${esc(ref)}</b> não encontrada no documento.</div>`;
}
function showRefs(pb, refs, title, keep) {
  if (!keep) stack = [];
  const ramo = pb.ramos.find(x => x.id === refs[0]);
  let t = title;
  if (ramo) t = `<span class="chip" style="margin-right:6px">${pb.id}</span>${esc(ramo.title)}`;
  else if (pb.steps.some(s => s.id === refs[0]) && refs.length === 1) t = `Passo ${esc(refs[0])}`;
  else if (pb.states.some(s => s.id === refs[0]) && refs.length === 1) t = `Estado ${esc(refs[0])}`;
  pushView(t, refs.map(r => refHtml(pb, r)).join(""), pb);
}

const listStr = a => a && a.length ? "<ul>" + a.map(x => `<li>${esc(x)}</li>`).join("") + "</ul>" : "";
function showTeam(pb, name, keep) {
  if (!keep) stack = [];
  const t = TEAMS[name]; if (!t) return;
  let h = `<div class="teamhero" style="border-color:${t.color}"><div class="kind">${esc(t.kind)}</div><p style="margin:6px 0 0">${esc(t.summary)}</p></div>`;
  if (can("templates.edit") && pb && pb.templateKey) h += `<button class="btn ghost sm" id="editTeam" title="Edita o time no template deste playbook">${ic("edit")}Editar time</button>`;
  if (t.does && t.does.length) h += `<h4>Responsabilidades</h4><div class="does">${listStr(t.does)}</div>`;
  if (t.never && t.never.length) h += `<h4>O que não faz</h4><div class="never">${listStr(t.never)}</div>`;
  if (pb) {
    const own = pb.steps.filter(s => s.team === name);
    if (own.length) {
      h += `<h4>Passos do ${pb.id} atribuídos ao time</h4>`;
      let phase = "";
      for (const s of own) {
        if (s.phase !== phase) { phase = s.phase; h += `<div class="phase-lbl">${esc(phase)}</div>`; }
        h += `<div class="snip"><button class="ref step" data-kind="step" data-id="${esc(s.id)}">${esc(s.id)}</button> ${esc(s.action)}</div>`;
      }
    }
    const c = pb.closing[name];
    if (c) h += `<h4>Critérios de encerramento</h4><div class="dcard"><div class="lbl" style="margin-top:0">Encerra quando</div>${esc(c.closes)}<div class="lbl">Nunca encerra quando</div>${esc(c.never)}</div>`;
    const m = (pb.mentions[name] || []).filter(x => !own.length || !/^Fluxo de resposta/.test(x.section));
    if (m.length) {
      h += `<h4>Onde o documento cita o time (${pb.id})</h4>` +
        m.slice(0, 14).map(x => `<div class="snip">${esc(x.text)}<small>${esc(x.section)}</small></div>`).join("") +
        (m.length > 14 ? `<div class="empty">+ ${m.length - 14} trechos no documento completo</div>` : "");
    }
  }
  pushView(`<span class="chip team" style="background:${t.color}">${esc(name)}</span>`, h, pb,
    body => { const b = $("#editTeam", body); if (b) b.onclick = () => { closeDrawer(); teamDialog({ tpl: pb.templateKey }, name); }; });
}

/* ───────── sessão e usuário ───────── */
/* erros do SSO chegam como código em /?sso_error=…; o texto é sempre este (nada da URL vai para a tela) */
const SSO_ERRORS = {
  desativado: "O login pelo SSO está desativado nesta instalação.",
  indisponivel: "O provedor de SSO não respondeu. Tente de novo em instantes.",
  recusado: "O provedor de SSO recusou o login.",
  expirado: "O login pelo SSO demorou demais e expirou. Tente de novo.",
  conta: "Sua conta não está liberada para entrar pelo SSO.",
  inativo: "Seu usuário está desativado.",
  tecnico: "Não foi possível validar o login com o provedor de SSO. O motivo fica registrado na auditoria.",
};
async function showLogin(msg) {
  App.user = null;
  document.body.classList.remove("editing", "viewer-role", "side-open"); document.body.classList.add("auth");
  closeDrawer();
  // erro devolvido pelo SSO (/?sso_error=código): mostra e limpa da barra de endereço
  const ssoErr = new URLSearchParams(location.search).get("sso_error");
  let msgErr = false;
  if (ssoErr) {
    msg = SSO_ERRORS[ssoErr] || "O login pelo SSO não foi concluído.";
    if (ssoErr === "conta" || ssoErr === "inativo") msg += " Fale com quem administra o acesso (abaixo).";
    msgErr = true; history.replaceState(null, "", location.pathname + location.hash);
  }
  let ssoSt = { enabled: false };
  try { ssoSt = await api("GET", "api/sso/status"); } catch { }
  const contact = Brand.get().contact;
  view.innerHTML = `<div class="login-wrap"><form class="login" id="loginForm" autocomplete="on" novalidate>
      <h1 class="login-brand">${Brand.loginBrand()}</h1>
      ${msg ? `<div class="login-msg ${msgErr ? "bad" : ""}" role="status">${esc(msg)}</div>` : ""}
      ${ssoSt.enabled ? `<a class="btn primary block sso-btn" href="api/sso/login">${ic("sso")}${esc(ssoSt.label)}</a>
        <div class="login-or"><span>${ssoSt.localLogin === "admins" ? "acesso de emergência (administradores)" : "ou com usuário e senha"}</span></div>` : ""}
      <label>Usuário<input class="in" name="login" autocomplete="username" autocapitalize="none" spellcheck="false" aria-describedby="lerr"></label>
      <label>Senha<input class="in" name="password" type="password" autocomplete="current-password" aria-describedby="lerr lcaps"></label>
      <p class="login-caps" id="lcaps" aria-live="polite"></p>
      <div class="err" id="lerr" role="alert" hidden></div>
      <button class="btn ${ssoSt.enabled ? "ghost" : "primary"} block" type="submit">Entrar${ssoSt.enabled ? " com senha" : ""}</button>
      <p class="login-help">Sem acesso ou com problema para entrar? ${contact ? `<b>${esc(contact)}</b>` : "Fale com um administrador do workspace."}</p>
    </form></div>`;
  const form = $("#loginForm"), btn = form.querySelector("button[type=submit]"), lerr = $("#lerr"), caps = $("#lcaps");
  const user = form.elements.login, pass = form.elements.password;
  const setErr = (text, fields = []) => {
    lerr.textContent = text; lerr.hidden = !text;
    [user, pass].forEach(i => i.toggleAttribute("aria-invalid", fields.includes(i)));
  };
  [user, pass].forEach(i => i.addEventListener("input", () => { if (i.hasAttribute("aria-invalid")) i.removeAttribute("aria-invalid"); }));
  /* Caps Lock: o motivo mais comum de senha "errada" digitada às pressas */
  const capsCheck = e => { if (e.getModifierState) caps.textContent = e.getModifierState("CapsLock") ? "Caps Lock ativado." : ""; };
  pass.addEventListener("keydown", capsCheck); pass.addEventListener("keyup", capsCheck); pass.addEventListener("blur", () => { caps.textContent = ""; });
  (user.value ? pass : user).focus();
  form.onsubmit = async e => {
    e.preventDefault();
    if (!user.value.trim()) { setErr("Informe o usuário.", [user]); return user.focus(); }
    if (!pass.value) { setErr("Informe a senha.", [pass]); return pass.focus(); }
    setErr(""); btn.disabled = true; btn.setAttribute("aria-busy", "true"); btn.textContent = "Entrando…";
    try {
      const r = await api("POST", "api/login", { login: user.value, password: pass.value });
      App.user = r.user;
      if (App.user.mustChange) return forcePassword();
      await start();
    } catch (err) {
      const locked = err.status === 429;
      setErr(err.message + (locked ? (ssoSt.enabled ? " Você ainda pode entrar pelo SSO." : " Se for urgente, use o contato abaixo.") : ""), locked ? [] : [user, pass]);
      btn.disabled = false; btn.removeAttribute("aria-busy"); btn.textContent = "Entrar" + (ssoSt.enabled ? " com senha" : "");
      if (!locked) { pass.focus(); pass.select(); }
    }
  };
}

function passwordForm(forced) {
  return `<form id="pwForm" class="tform">
    ${forced ? `<div class="notice">Você entrou com uma senha temporária. Defina uma senha pessoal para continuar.</div>` : ""}
    <label>Senha atual${forced ? " (temporária)" : ""}<input class="in" type="password" name="current" autocomplete="current-password" required></label>
    <label>Nova senha <small>(mínimo 10 caracteres, com letras e números)</small><input class="in" type="password" name="new" autocomplete="new-password" minlength="10" required></label>
    <label>Repita a nova senha<input class="in" type="password" name="new2" autocomplete="new-password" required></label>
    <div class="err" id="pwerr" hidden></div>
    <div class="create-actions"><button class="btn primary" type="submit">Salvar senha</button></div></form>`;
}
function bindPasswordForm(root, done) {
  $("#pwForm", root).onsubmit = async e => {
    e.preventDefault();
    const f = new FormData(e.target), err = $("#pwerr", root);
    if (f.get("new") !== f.get("new2")) { err.textContent = "As senhas não conferem"; err.hidden = false; return; }
    try {
      const r = await api("POST", "api/me/password", { current: f.get("current"), new: f.get("new") });
      App.user = r.user; toast("Senha alterada"); done();
    } catch (x) { err.textContent = x.message; err.hidden = false; }
  };
}
function forcePassword() {
  if ($("#pwForm")) return;
  document.body.classList.remove("editing", "viewer-role", "side-open"); document.body.classList.add("auth");
  view.innerHTML = `<div class="login-wrap"><div class="login"><div class="login-brand">${Brand.loginBrand()}</div><h1>Defina sua senha</h1>${passwordForm(true)}
    <button class="btn ghost block" id="lo2" style="margin-top:8px">Sair</button></div></div>`;
  bindPasswordForm(view, () => start());
  $("#lo2").onclick = logout;
}
async function logout() {
  if ((Editor.dirty || Editor.hasDraft()) && !(await ask("Há alterações não salvas nos editores. Sair mesmo assim e descartá-las?", { title: "Sair", ok: "Sair e descartar", danger: true }))) return;
  Editor.dirty = false; Editor.unmount(); Editor.dropDrafts();
  await api("POST", "api/logout").catch(() => {});
  location.hash = "#/"; showLogin();
}

/* barra lateral: navegação principal (o item da página atual fica marcado) */
function renderSide() {
  const key = (hashPath().split("/")[0] || "").toLowerCase();
  const on = k => (k === "home" ? (!key || /^pb-\d+$/.test(key) || key === "novo") : k === "runbooks" ? (key === k || /^rb-\d+$/.test(key))
    : k === "documentos" ? (key === k || /^doc-\d+$/.test(key)) : key === k) ? "on" : "";
  const count = t => PBS.filter(p => p.type === t).length;
  /* o title vira a dica de cada ícone quando o menu está recolhido (só os ícones aparecem) */
  const link = (k, href, icon, label, n) => `<a href="${href}" class="${on(k)}"${on(k) ? ` aria-current="page"` : ""} title="${label}">${ic(icon)}<span>${label}</span>${n === undefined ? "" : `<small aria-label="${n} ${n === 1 ? "item" : "itens"}">${n}</small>`}</a>`;
  /* conteúdo (o que o analista lê) separado da configuração */
  const cfg = [can("templates.view") ? link("templates", "#/templates", "templates", "Templates") : "", canAdmin() ? link("admin", "#/admin", "settings", "Administração") : "",
    link("ajuda", "#/ajuda", "docs", "Ajuda")].join("");
  $("#sideNav").innerHTML = !App.user ? "" : `<div class="nav-grp">${link("home", "#/", "playbooks", "Playbooks", count("playbook"))}
    ${can("runbook.view") ? link("runbooks", "#/runbooks", "pageEdit", "Runbooks", count("runbook")) : ""}
    ${can("doc.view") ? link("documentos", "#/documentos", "page", "Documentos", count("doc")) : ""}</div>
    <div class="nav-grp nav-cfg">${cfg}</div>`;
}
/* Menu lateral. Desktop (> 900 px): o botão recolhe/expande (body.side-collapsed), estado salvo no navegador; atalho [.
   Telas estreitas: o menu vira gaveta (body.side-open) com fundo escurecido; Esc ou o botão de fechar fecham e o foco
   volta ao botão do menu; o conteúdo atrás fica inerte enquanto ela está aberta. */
const narrow = matchMedia("(max-width: 900px)");
const SIDE_KEY = "medusa-side";
function syncSideAria() {
  const b = $("#sideToggle"); if (!b) return;
  const open = narrow.matches ? document.body.classList.contains("side-open") : !document.body.classList.contains("side-collapsed");
  b.setAttribute("aria-expanded", String(open));
  b.title = (open ? "Ocultar menu" : "Mostrar menu") + (narrow.matches ? "" : " ( [ )");
}
function setCollapsed(v) {
  document.body.classList.toggle("side-collapsed", v);
  try { localStorage.setItem(SIDE_KEY, v ? "recolhido" : "aberto"); } catch { }
  syncSideAria();
}
function sideOpen(v, refocus = false) {
  const was = document.body.classList.contains("side-open");
  document.body.classList.toggle("side-open", v); $("#sideScrim").hidden = !v;
  $(".shell").inert = v;
  /* aberta, a gaveta é um diálogo; o foco vai para o botão de fechar (focar a busca abria o teclado do celular por
     cima do menu) depois que a transição a torna visível */
  const side = $("#side");
  if (v) { side.setAttribute("role", "dialog"); side.setAttribute("aria-modal", "true"); } else { side.removeAttribute("role"); side.removeAttribute("aria-modal"); }
  if (v && !was) {
    const f = () => { if (document.body.classList.contains("side-open") && !side.contains(document.activeElement)) $("#sideClose").focus(); };
    side.addEventListener("transitionend", f, { once: true }); setTimeout(f, 260);
  }
  if (!v && was && refocus) { const b = $("#sideToggle"); if (b) b.focus(); }
  syncSideAria();
}
const toggleSide = () => narrow.matches ? sideOpen(!document.body.classList.contains("side-open")) : setCollapsed(!document.body.classList.contains("side-collapsed"));
try { document.body.classList.toggle("side-collapsed", localStorage.getItem(SIDE_KEY) === "recolhido"); } catch { }
/* alargar a janela com a gaveta aberta: fecha a gaveta (nada fica inerte nem escondido) */
narrow.addEventListener("change", () => { if (!narrow.matches) sideOpen(false); syncSideAria(); });
$("#sideScrim").onclick = () => sideOpen(false, true);
$("#sideClose").onclick = () => sideOpen(false, true);
document.addEventListener("click", e => { if (e.target.closest("#sideToggle")) toggleSide(); });
document.addEventListener("keydown", e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
  if (e.key === "Escape" && document.body.classList.contains("side-open")) sideOpen(false, true);
  else if (e.key === "[" && !typing && !e.ctrlKey && !e.metaKey && !e.altKey && App.user && !document.querySelector(".modal-bg")) { e.preventDefault(); toggleSide(); }
});

function renderUserMenu() {
  const u = App.user, box = $("#usermenu");
  if (!u) { box.innerHTML = ""; return; }
  const ini = (u.name || u.login).split(/\s+/).map(x => x[0]).slice(0, 2).join("").toUpperCase();
  box.innerHTML = `<button class="ubtn" id="ubtn" title="${esc(u.name)} · ${esc(u.roleName)}" aria-label="Conta de ${esc(u.name)} (${esc(u.roleName)})" aria-haspopup="menu" aria-expanded="false" aria-controls="umenu"><span class="avatar" aria-hidden="true">${esc(ini)}</span><span class="uname" aria-hidden="true">${esc(u.name)}<small>${esc(u.roleName)}</small></span></button>
    <div class="umenu" id="umenu" role="menu" aria-label="Conta" hidden>
      <div class="uhead" role="presentation"><b>${esc(u.name)}</b><span>${esc(u.login)} · ${esc(u.roleName)}</span></div>
      <button class="uitem" role="menuitem" id="uPw">${ic("key")}Trocar senha</button>
      <button class="uitem" role="menuitem" id="uOut">${ic("logout")}Sair</button></div>`;
  /* botão de menu: Enter/Espaço ou ↓ abrem e focam o primeiro item; ↑ ↓ andam; Esc fecha e volta ao botão */
  const btn = $("#ubtn"), menu = $("#umenu"), items = () => [...menu.querySelectorAll("[role=menuitem]")];
  const show = (v, focusFirst) => { menu.hidden = !v; btn.setAttribute("aria-expanded", String(v)); if (v && focusFirst) items()[0].focus(); };
  btn.onclick = e => { e.stopPropagation(); show(menu.hidden, e.detail === 0); };
  btn.onkeydown = e => { if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); show(true, false); (e.key === "ArrowDown" ? items()[0] : items().at(-1)).focus(); } };
  menu.onkeydown = e => {
    const all = items(), i = all.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); show(false); btn.focus(); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); all[(i + (e.key === "ArrowDown" ? 1 : all.length - 1)) % all.length].focus(); }
    else if (e.key === "Tab") show(false);
  };
  menu.addEventListener("click", e => { if (e.target.closest(".uitem")) show(false); });   // escolher uma opção fecha o menu
  $("#uPw").onclick = () => { show(false); modal({ title: "Trocar senha", html: passwordForm(false), onMount: (b, close) => bindPasswordForm(b, close) }); };
  $("#uOut").onclick = logout;
}
document.addEventListener("click", e => {
  const m = $("#umenu"); if (m && !m.hidden && !e.target.closest("#usermenu")) { m.hidden = true; $("#ubtn").setAttribute("aria-expanded", "false"); }
  const x = $("#expMenu"); if (x && !e.target.closest(".menu-wrap")) x.hidden = true;
});

/* ───────── rotas ───────── */
/* playbook aberto na página atual (documento completo) */
const currentPb = () => { const m = location.hash.match(/^#\/((?:pb|rb|doc)-\d+)/i), s = m && pbBy(m[1].toLowerCase()); return s ? DETAIL.get(s.id) || null : null; };
/* abas de leitura e de edição de cada tipo: runbook mostra Fluxograma só se tiver; documento não tem */
function pbTabs(pb) {
  const t = pb.type || "playbook";
  if (t === "playbook") return { read: TABS, edit: EDIT_TABS, first: "fluxo" };
  const read = [["doc", "Documentação"]].concat(pb.hasFlow ? [["fluxo", "Fluxograma"]] : []).concat([["versoes", "Versões"]]);
  const edit = [["editar", "Editar documento"]].concat(typeInfo(t).flow === "none" ? [] : [["editar-fluxo", pb.hasFlow ? "Editar fluxograma" : "Adicionar fluxograma"]]);
  return { read, edit, first: "doc" };
}
let routeSeq = 0;
/* playbook: duas visualizações (fluxograma e documentação, que já traz fases, passos e ramos), o histórico e os editores */
const TABS = [["fluxo", "Fluxograma"], ["doc", "Documentação"], ["versoes", "Versões"]];
const EDIT_TABS = [["editar", "Editar documento"], ["editar-fluxo", "Editar fluxograma"]];
const view = $("#view");
let lastHash = location.hash;

/* Abas como num navegador: cada playbook (ou página) aberto vira uma aba que pode ser fechada.
   A lista fica salva no navegador, por usuário. Cada aba lembra a sub-aba em que estava. */
const Tabs = (() => {
  let list = [], activeKey = null;
  const storeKey = () => "medusa-tabs:" + (App.user ? App.user.login : "");
  function load() {
    try { list = JSON.parse(localStorage.getItem(storeKey()) || "[]").filter(t => t && t.key && t.path); } catch { list = []; }
  }
  const save = () => { try { localStorage.setItem(storeKey(), JSON.stringify(list)); } catch { } };
  const keyOf = hash => (hashPath(hash).split("/").filter(Boolean)[0] || "").toLowerCase() || null;
  function info(key) {
    if (key === "novo") return can("playbook.create") && { title: "Novo playbook", icon: "plus" };
    if (key === "admin") return canAdmin() && { title: "Administração", icon: "settings" };
    if (key === "templates") return can("templates.view") && { title: TemplatesPage.tabTitle(), icon: "templates" };
    if (key === "ajuda") return { title: "Ajuda", icon: "docs" };
    if (ROUTE_TYPE[key]) return can(`${ROUTE_TYPE[key]}.view`) && { title: typeInfo(ROUTE_TYPE[key]).plural, icon: key === "runbooks" ? "pageEdit" : "page" };
    const pb = pbBy(key);
    return pb && { title: `${pb.id} · ${pb.name}`, dot: STATUS_CLS[pb.gov.status] };
  }
  function sync() {
    const key = keyOf(location.hash);
    list = list.filter(t => info(t.key));
    if (key && info(key)) {
      const t = list.find(x => x.key === key);
      if (t) t.path = location.hash;
      else { const i = list.findIndex(x => x.key === activeKey); list.splice(i >= 0 ? i + 1 : list.length, 0, { key, path: location.hash }); }
    }
    activeKey = key; save(); render();
  }
  function render() {
    list = list.filter(t => info(t.key));
    $("#tabbar").innerHTML = `<button class="side-toggle" id="sideToggle" aria-label="Menu" aria-controls="side" aria-expanded="true">${ic("menu")}</button><a class="tab home ${!activeKey ? "on" : ""}" href="#/" title="Playbooks">${ic("playbooks")}Playbooks</a>` +
      list.map(t => {
        const i = info(t.key);
        return `<div class="tab ${t.key === activeKey ? "on" : ""}" data-k="${esc(t.key)}"><a class="tab-a" href="${esc(t.path)}" title="${esc(i.title)}"${t.key === activeKey ? ` aria-current="page"` : ""}>${i.dot ? `<i class="dot ${i.dot}"></i>` : ic(i.icon)}<span class="ttl">${esc(i.title)}</span>${Editor.hasDraft(t.key) ? `<i class="draft-dot" title="Alterações não salvas"></i>` : ""}</a><button class="tx" data-close="${esc(t.key)}" title="Fechar aba" aria-label="Fechar aba ${esc(i.title)}">${ic("close")}</button></div>`;
      }).join("") + `<button class="tab-new" id="tabNew" title="Nova aba (página inicial)" aria-label="Nova aba">${ic("plus")}</button>`;
    syncSideAria();
    const on = $("#tabbar .tab.on"); if (on) on.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  async function close(key) {
    const i = list.findIndex(t => t.key === key); if (i < 0) return;
    const wasActive = key === activeKey;
    if (wasActive) Editor.stash();
    if (Editor.hasDraft(key) && !(await ask("Esta aba tem alterações não salvas. Fechar e descartar as alterações?", { title: "Fechar aba", ok: "Fechar e descartar", danger: true }))) { if (wasActive) route(); return; }
    Editor.dropDrafts(key);
    list.splice(i, 1); save();
    if (wasActive) { const n = list[i] || list[i - 1]; location.hash = n ? n.path : "#/"; }
    else render();
  }
  $("#tabbar").addEventListener("click", e => {
    const x = e.target.closest("[data-close]");
    if (x) { e.preventDefault(); e.stopPropagation(); return close(x.dataset.close); }
    if (e.target.closest("#tabNew")) location.hash = "#/";
  });
  $("#tabbar").addEventListener("auxclick", e => { const t = e.target.closest(".tab[data-k]"); if (t && e.button === 1) { e.preventDefault(); close(t.dataset.k); } });
  const drop = key => { list = list.filter(t => t.key !== key); save(); };
  return { load, sync, render, close, drop };
})();
const renderNav = () => Tabs.render();

function route() {
  if (!App.user) return;
  if (location.hash !== lastHash && Unsaved.dirty()) {
    const to = location.hash;
    history.replaceState(null, "", lastHash);
    ask("Sair sem salvar? As alterações desta página serão descartadas.", { title: "Alterações não salvas", ok: "Sair sem salvar", danger: true })
      .then(ok => { if (ok) { Unsaved.check = null; location.hash = to; } });
    return;
  }
  Unsaved.check = null;
  /* trocar de aba ou de página não perde o que está sendo editado: o editor guarda um rascunho, que volta
     ao reabrir o editor (a aba mostra um ponto); só fechar a aba ou descartar apagam o rascunho */
  Editor.stash(); Editor.unmount();
  const um = $("#umenu"); if (um && !um.hidden) { um.hidden = true; $("#ubtn").setAttribute("aria-expanded", "false"); }
  sideOpen(false); renderSide();
  lastHash = location.hash;
  if (App.data) useTeams(null);
  closeDrawer();
  const parts = hashPath().split("/").filter(Boolean);
  Tabs.sync();
  document.title = $("#brandName").textContent;
  window.scrollTo(0, 0);
  /* classes da página (o estado do menu lateral, side-collapsed, é preservado) */
  document.body.classList.remove("auth", "editing");
  document.body.classList.toggle("viewer-role", !can("playbook.edit"));
  if (parts[0] === "novo") return can("playbook.create") ? Editor.createForm(view) : notFound();
  if (parts[0] === "admin") return canAdmin() ? Admin.render(view, parts[1], parts[2]) : notFound();
  if (parts[0] === "times" || (parts[0] === "templates" && parts[1] === "@times")) { location.replace("#/templates"); return; }
  /* a ajuda da plataforma era "Documentação" (#/docs) até a 2.x; o endereço antigo continua valendo */
  if (parts[0] === "docs") { location.replace("#/ajuda" + (parts[1] ? "/" + parts[1] : "")); return; }
  if (parts[0] === "ajuda") return Docs.render(view, parts[1]);
  if (ROUTE_TYPE[parts[0]]) {
    const t = ROUTE_TYPE[parts[0]];
    if (!can(`${t}.view`)) return notFound();
    if (parts[1] === "novo") return can(`${t}.create`) ? DocCreate.render(view, t, parts[2]) : notFound();
    return LibraryPage.render(view, t, parts[1] === "p" ? parts[2] : "");
  }
  if (parts[0] === "templates") return can("templates.view") ? TemplatesPage.render(view, parts[1], parts[2]) : notFound();
  if (!parts.length) return LibraryPage.render(view, "playbook", "");
  const s = pbBy(parts[0].toLowerCase());
  if (!s) return notFound();
  if (parts[1] === "fases" || parts[1] === "ramos") { location.replace(`#/${s.slug}/doc${parts[2] ? "/" + parts[2] : ""}`); return; }
  const show = pb => {
    const tb = pbTabs(pb), all = tb.read.concat(can(`${pb.type || "playbook"}.edit`) ? tb.edit : []);
    renderPb(pb, all.some(t => t[0] === parts[1]) ? parts[1] : tb.first, parts[2], parts.slice(3));
  };
  const ready = DETAIL.get(s.id);
  if (ready && ready.rev === s.rev) return show(ready);
  /* detalhe sob demanda: só o playbook aberto trafega inteiro */
  const seq = ++routeSeq;
  view.innerHTML = `<div class="wrap"><div class="empty">Carregando…</div></div>`;
  ensureDetail(s.slug).then(pb => { if (seq === routeSeq) pb ? show(pb) : notFound(); })
    .catch(e => { if (seq === routeSeq && e.status !== 401) e.status === 404 ? notFound() : view.innerHTML = `<div class="wrap"><div class="err">${esc(e.message)}</div></div>`; });
}
window.addEventListener("hashchange", route);
window.addEventListener("beforeunload", e => { if (Editor.dirty || Editor.hasDraft() || Unsaved.dirty()) { e.preventDefault(); e.returnValue = ""; } });

function notFound() {
  view.innerHTML = `<div class="wrap"><div class="ecard"><h2 style="margin-top:0">Página não encontrada</h2><p class="muted">O playbook não existe ou não está disponível para o seu perfil.</p><a class="btn ghost" href="#/">Voltar ao início</a></div></div>`;
}

/* ───────── biblioteca: o que é comum aos três tipos ─────────
   Playbooks, Runbooks e Documentos usam a mesma página (LibraryPage): cabeçalho, barra de filtros, três formas de
   ver a lista e os mesmos estados vazios. Status, texto e campos ficam no endereço (#/runbooks?status=Produção&q=edr),
   para recarregar, voltar e compartilhar a mesma visão. */
const hashPath = (h = location.hash) => h.replace(/^#\/?/, "").split("?")[0];
const hashQuery = () => new URLSearchParams(location.hash.split("?")[1] || "");
/* troca só a parte de filtros do endereço, sem recarregar a página (push: o Voltar desfaz a escolha) */
function setHashQuery(params, push) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v)).toString();
  const h = "#/" + hashPath() + (qs ? "?" + qs : "");
  if (h === location.hash) return;
  history[push ? "pushState" : "replaceState"](null, "", h);
  lastHash = location.hash; Tabs.sync();
}
/* Três formas de ver a lista, as mesmas nos três tipos; a escolhida fica salva no navegador, por usuário */
const LIB_VIEWS = [
  ["cards", "Cartões", `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="1.5" width="5.5" height="5.5" rx="1.3"/><rect x="9" y="1.5" width="5.5" height="5.5" rx="1.3"/><rect x="1.5" y="9" width="5.5" height="5.5" rx="1.3"/><rect x="9" y="9" width="5.5" height="5.5" rx="1.3"/></svg>`],
  ["lg", "Lista grande", `<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="1.5" y="1.75" width="13" height="5.25" rx="1.3"/><rect x="1.5" y="9" width="13" height="5.25" rx="1.3"/></svg>`],
  ["sm", "Lista pequena", `<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 3.25h12M2 6.42h12M2 9.58h12M2 12.75h12"/></svg>`],
];
const whoKey = () => App.user ? App.user.login : "";
function libView() {
  let v = null;
  try { v = localStorage.getItem("medusa-lib-view:" + whoKey()) || localStorage.getItem("medusa-home-view:" + whoKey()); } catch { }
  return LIB_VIEWS.some(x => x[0] === v) ? v : "cards";
}
const setLibView = v => { try { localStorage.setItem("medusa-lib-view:" + whoKey(), v); } catch { } };
/* status visíveis para a role (Desenvolvimento só para quem vê rascunhos) */
const libStatuses = t => App.data.statuses.filter(s => can(`${t}.view_drafts`) || s !== "Desenvolvimento");
const statusKey = t => `medusa-lib-status:${t}:` + whoKey();
/* status pedido: o do endereço; senão o último escolhido; senão Produção para quem só lê e Todos para quem edita */
function libStatus(t) {
  const pick = v => v === "todos" ? "" : libStatuses(t).includes(v) ? v : "";
  const q = hashQuery().get("status");
  if (q) return pick(q);
  let v = null; try { v = localStorage.getItem(statusKey(t)); } catch { }
  if (v) return pick(v);
  return can(`${t}.edit`) ? "" : "Produção";
}
const docHref = p => `#/${p.slug}/${p.type === "playbook" ? "fluxo" : "doc"}`;
const sugChip = (p, t) => p.suggestions && can(`${t}.edit`) ? `<span class="chip sg-chip">${p.suggestions} sugest${p.suggestions > 1 ? "ões" : "ão"}</span>` : "";
/* a pista do cartão: em playbooks, os times que agem no fluxograma e a tática MITRE; nos demais, os campos do template */
function docTags(p, t) {
  if (t === "playbook") {
    const teams = (p.teams || []).map(x => `<span class="team-tag"><i style="background:${esc(x.color || TEAM_COLOR(x.name))}"></i>${esc(x.name)}</span>`).join("");
    const mitre = p.mitre ? `<span class="mitre-tag" title="Tática MITRE principal">${esc(p.mitre)}</span>` : "";
    return teams || mitre ? `<div class="doc-tags">${teams}${mitre}</div>` : "";
  }
  const vals = Object.values(p.fields || {}).flatMap(v => Array.isArray(v) ? v : [v]).filter(Boolean).slice(0, 4);
  const tags = vals.map(v => `<span class="chip">${esc(v)}</span>`).join("") + (p.hasFlow && t !== "doc" ? `<span class="chip">fluxograma</span>` : "");
  return tags ? `<div class="doc-tags">${tags}</div>` : "";
}
const docCounts = (p, t) => t === "playbook" ? `<span class="doc-counts">${p.ramos} ramos · ${p.steps} passos</span>` : "";
const dragAttr = (p, t) => typeInfo(t).folders ? ` draggable="true" data-doc="${p.id}"` : "";

function libCards(items, t) {
  return `<div class="cards">${items.map(p => {
    const gov = govLine(p.gov), foot = docCounts(p, t) + sugChip(p, t);
    return `<a class="card st-${STATUS_CLS[p.status]}" href="${docHref(p)}"${dragAttr(p, t)}>
      <div class="card-top"><span class="id">${p.id} · v${esc(p.version)}</span>${statusPill(p.status, t)}</div><h3>${esc(p.name)}</h3>
      ${docTags(p, t)}${foot ? `<div class="meta">${foot}</div>` : ""}${gov ? `<div class="govline">${gov}</div>` : ""}</a>`;
  }).join("")}</div>`;
}
function libLarge(items, t) {
  return `<div class="plist">${items.map(p => {
    const gov = govLine(p.gov);
    return `<a class="prow st-${STATUS_CLS[p.status]}" href="${docHref(p)}"${dragAttr(p, t)}>
      <div class="pr-main">
        <div class="pr-top"><span class="id">${p.id}</span><span class="pr-ver">v${esc(p.version)}</span>${p.templateName ? `<span class="pr-tpl" title="Template">${esc(p.templateName)}</span>` : ""}${sugChip(p, t)}</div>
        <h3>${esc(p.name)}</h3>${docTags(p, t)}${gov ? `<div class="pr-gov">${gov}</div>` : ""}</div>
      <div class="pr-stats">${t === "playbook" ? `<div><b>${p.ramos}</b><span>ramos</span></div><div><b>${p.steps}</b><span>passos</span></div>` : ""}</div>
      <div class="pr-status">${statusPill(p.status, t)}</div></a>`;
  }).join("")}</div>`;
}
function libSmall(items, t, plural) {
  const pb = t === "playbook", h = l => `<span role="columnheader">${l}</span>`;
  return `<div class="ptable${pb ? "" : " lib-table"}" role="table" aria-label="${esc(plural)}">
      <div class="pt-row pt-head" role="row">${h("ID")}${h("Nome")}${h("Status")}${h("Versão")}${pb ? `<span role="columnheader" class="pt-num">Ramos</span><span role="columnheader" class="pt-num">Passos</span>` : ""}<span role="columnheader" class="pt-rev">Última revisão</span></div>
      ${items.map(p => `<a class="pt-row st-${STATUS_CLS[p.status]}" role="row" href="${docHref(p)}"${dragAttr(p, t)}>
        <span class="pt-id" role="cell">${p.id}</span><span class="pt-name" role="cell" title="${esc(p.name)}">${esc(p.name)}</span>
        <span role="cell"><span class="pt-st" title="${esc(statusLabel(t, p.status))}"><i class="dot ${STATUS_CLS[p.status]}"></i><span class="pt-st-l">${esc(statusLabel(t, p.status))}</span></span></span><span role="cell" class="pt-ver">v${esc(p.version)}</span>
        ${pb ? `<span role="cell" class="pt-num">${p.ramos}</span><span role="cell" class="pt-num">${p.steps}</span>` : ""}
        <span role="cell" class="pt-rev">${p.gov.reviewed ? esc(p.gov.reviewed) + (p.gov.reviewer ? ` · ${esc(p.gov.reviewer)}` : "") : `<span class="muted">—</span>`}</span></a>`).join("")}</div>`;
}
const newHref = (t, folder) => t === "playbook" ? "#/novo" : `#/${TYPE_ROUTE[t]}/novo${folder && folder !== "none" ? "/" + folder : ""}`;
/* lista vazia: diz o motivo (filtro, pasta vazia, nada publicado) e oferece a saída certa para cada caso */
function libEmpty(t, { status, filtered, folder }) {
  const ti = typeInfo(t), one = ti.label.toLowerCase(), many = ti.plural.toLowerCase();
  const create = can(`${t}.create`) ? `<a class="btn primary sm" href="${newHref(t, folder)}">${ic("plus")}Criar ${esc(one)}</a>` : "";
  let msg, act;
  if (filtered) { msg = `Nenhum ${esc(one)} com estes filtros.`; act = `<button class="btn ghost sm" data-clear>Limpar filtros</button>`; }
  else if (status) { msg = `Nenhum ${esc(one)} em ${esc(statusLabel(t, status))}.`; act = `<button class="btn ghost sm" data-clear>Ver todos os status</button>`; }
  else if (folder) { msg = folder === "none" ? `Todos os ${esc(many)} estão em alguma pasta.` : "Esta pasta está vazia."; act = folder === "none" ? "" : create; }
  else if (can(`${t}.create`)) { msg = `Ainda não há ${esc(many)}. ${t === "playbook" ? "Preencha o essencial e a ferramenta gera o documento no padrão e o fluxograma inicial." : "Comece por um template."}`; act = create; }
  else { msg = `Ainda não há ${esc(many)} disponíveis para o seu perfil. Se esperava ver algum aqui, fale com o time de segurança.`; act = ""; }
  return `<div class="lib-empty" role="status"><p>${msg}</p>${act}</div>`;
}
/* erro ao carregar: a mensagem e um "Tentar de novo" que refaz a rota atual */
function loadError(root, e) {
  root.innerHTML = `<div class="wrap"><div class="err load-err" role="alert"><span>Não foi possível carregar: ${esc(e.message)}</span><button class="btn ghost xs" data-retry>Tentar de novo</button></div></div>`;
  root.querySelector("[data-retry]").onclick = () => route();
}
/* menu "Mais" do cabeçalho: importar e exportar ficam fora do caminho de quem só lê */
function actionsMenu(anchor, items) {
  document.querySelectorAll(".fmenu").forEach(m => m.remove());
  const r = anchor.getBoundingClientRect(), m = document.createElement("div");
  m.className = "dmenu fmenu acts-menu"; m.setAttribute("role", "menu");
  m.style.cssText = `position:fixed;left:${Math.max(8, Math.min(r.right - 240, innerWidth - 248))}px;top:${r.bottom + 4}px;z-index:80`;
  m.innerHTML = items.map((x, i) => x.href ? `<a role="menuitem" href="${x.href}" download data-i="${i}">${ic(x.icon)}${esc(x.label)}<small>${esc(x.hint)}</small></a>`
    : `<button role="menuitem" data-i="${i}">${ic(x.icon)}${esc(x.label)}<small>${esc(x.hint)}</small></button>`).join("");
  document.body.append(m); anchor.setAttribute("aria-expanded", "true");
  const close = (refocus) => { m.remove(); anchor.setAttribute("aria-expanded", "false"); document.removeEventListener("mousedown", out, true); if (refocus) anchor.focus(); };
  const out = e => { if (!m.contains(e.target) && e.target !== anchor) close(); };
  setTimeout(() => document.addEventListener("mousedown", out, true), 0);
  m.onkeydown = e => {
    const all = [...m.querySelectorAll("[role=menuitem]")], i = all.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); close(true); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); all[(i + (e.key === "ArrowDown" ? 1 : all.length - 1)) % all.length].focus(); }
  };
  m.onclick = e => { const b = e.target.closest("[data-i]"); if (!b) return; const x = items[+b.dataset.i]; close(true); if (x.run) x.run(); };
  m.querySelector("[role=menuitem]").focus();
}
function govLine(g) {
  const parts = [];
  if (g.status === "Produção" && g.approver) parts.push(`Aprovado por <b>${esc(g.approver)}</b>`);
  if (g.reviewer) parts.push(`Revisado por <b>${esc(g.reviewer)}</b>${g.reviewed ? ` em ${esc(g.reviewed)}` : ""}`);
  return parts.join(" · ");
}

/* ───────── página do playbook ───────── */
function renderPb(pb, tab, extra, rest) {
  useTeams(pb);
  const props = pb.props, g = pb.gov, T = pb.type || "playbook", ti = typeInfo(T), tb = pbTabs(pb);
  const all = tb.read.concat(can(`${T}.edit`) ? tb.edit : []);
  const flowExp = pb.hasFlow !== false;
  view.innerHTML = `<div class="pbbar"><div class="wrap">
    <div class="pbhead"><span class="pbid">${pb.id}</span><h1>${esc(pb.name)}</h1>${statusPill(g.status, T)}
      <div class="pbactions"><div class="menu-wrap"><button class="btn ghost sm" id="expBtn" aria-haspopup="true">${ic("download")}Exportar${ic("caret", "caret")}</button>
        <div class="dmenu" id="expMenu" hidden>
          <div class="dm-h">Documento</div>
          <a href="api/pb/${pb.id}/export?fmt=md" download><b>Markdown</b><small>.md · Confluence, Git, qualquer editor (.zip se tiver imagens)</small></a>
          <button data-exp="html"><b>HTML${flowExp ? " com fluxograma" : ""}</b><small>.html · abre em qualquer navegador ou no Word</small></button>
          <button data-exp="print"><b>Imprimir / salvar PDF</b><small>documento completo${flowExp ? " com o fluxograma" : ""}</small></button>
          ${flowExp ? `<div class="dm-h">Fluxograma</div>
          <a href="api/pb/${pb.id}/export?fmt=drawio" download><b>draw.io</b><small>.drawio · editável no draw.io e no Confluence</small></a>
          <a href="api/pb/${pb.id}/export?fmt=mmd" download><b>Mermaid</b><small>.mmd · GitHub, GitLab, mermaid.live</small></a>
          <button data-exp="svg"><b>Imagem SVG</b><small>.svg · vetorial, para wikis</small></button>
          <button data-exp="jpeg"><b>Imagem JPEG</b><small>.jpg · apresentações, e-mail e tickets</small></button>` : ""}
          <div class="dm-h">Pacote completo</div>
          <a href="api/pb/${pb.id}/export?fmt=medusa" download><b>Medusa</b><small>.medusa.md · ${flowExp ? "documento + fluxograma" : "documento, pasta e campos"}, reimportável</small></a>
        </div></div>
        ${canAny(`${T}.suggest`, `${T}.edit`) ? `<button class="btn ghost sm" id="sgBtn" title="Sugestões de alteração">${ic("edit")}Sugestões<span class="sg-n">${(PBS.find(p => p.id === pb.id) || {}).suggestions ? " " + PBS.find(p => p.id === pb.id).suggestions : ""}</span></button>` : ""}
        ${ti.folders && can(`${T}.edit`) ? `<button class="btn ghost sm" id="mvBtn">${ic("swap")}Mover</button>` : ""}
        ${can(`${T}.status`) ? `<button class="btn ghost sm" id="stBtn">${ic("swap")}Alterar status</button>` : ""}${can(`${T}.delete`) ? `<button class="btn danger sm" id="delBtn" title="Excluir">${ic("trash")}Excluir</button>` : ""}</div></div>
    ${fieldChips(pb)}${govHtml(pb)}<button type="button" class="gov-more" id="govMore" aria-expanded="false">Ver detalhes do documento</button>
    <nav class="tabs">${all.map(([k, l]) => `<a href="#/${pb.slug}/${k}" class="${k === tab ? "on" : ""} ${k.startsWith("editar") ? "edit" : ""}">${k.startsWith("editar") ? ic("edit") : ""}${l}${Editor.hasDraft(pb.id.toLowerCase() + (k === "editar" ? ":doc" : ":flow")) && k.startsWith("editar") ? `<i class="draft-dot" title="Alterações não salvas"></i>` : ""}</a>`).join("")}</nav></div></div>
    <div class="wrap" id="tabview"></div>`;
  $("#govMore").onclick = e => { const g = $(".pbbar .gov"), on = g.classList.toggle("open"); e.currentTarget.setAttribute("aria-expanded", on); e.currentTarget.textContent = on ? "Ocultar detalhes" : "Ver detalhes do documento"; };
  ctxBar(pb);
  if ($("#stBtn")) $("#stBtn").onclick = () => statusDialog(currentPb());
  $("#expBtn").onclick = e => { e.stopPropagation(); $("#expMenu").hidden = !$("#expMenu").hidden; };
  $("#expMenu").onclick = e => { const b = e.target.closest("[data-exp]"); $("#expMenu").hidden = true; if (b) Exporter[b.dataset.exp](currentPb()); };
  if ($("#delBtn")) $("#delBtn").onclick = () => deleteDialog(currentPb());
  if ($("#mvBtn")) $("#mvBtn").onclick = () => moveDialog(currentPb());
  if ($("#sgBtn")) $("#sgBtn").onclick = () => Suggest.panel(currentPb());
  if (can(`${T}.edit`)) lintBadge(pb);
  const tv = $("#tabview");
  if (tab === "editar") return Editor.docEditor(tv, pb);
  if (tab === "editar-fluxo") {
    document.body.classList.add("editing");
    /* runbook sem fluxograma: o editor abre com uma raia; ao salvar, o .drawio é criado */
    const start = pb.hasFlow === false ? Object.assign({}, pb, { flow: { subtitle: "", lanes: [JSON.parse(JSON.stringify(App.data.catalog.defaultLanes[0]))], nodes: [], edges: [] }, refs: {} }) : pb;
    return Editor.flowEditor(tv, start);
  }
  if (tab === "versoes") Versions.render(pb, tv, extra, rest || []);
  else { ({ fluxo: tabFlow, doc: tabDoc })[tab](pb, tv, extra); linkify(tv, pb); }
  const pend = [["editar", "Editar documento", ":doc"], ["editar-fluxo", "Editar fluxograma", ":flow"]].filter(([, , k]) => Editor.hasDraft(pb.id.toLowerCase() + k));
  if (pend.length) tv.insertAdjacentHTML("afterbegin", `<div class="notice draft-note">${ic("warn")}<span>Alterações não salvas em ${pend.map(([k, l]) => `<a href="#/${pb.slug}/${k}">${l}</a>`).join(" e ")}. Elas ficam guardadas enquanto a aba estiver aberta.</span></div>`);
}

/* faixa fina que aparece quando o título sai da tela: ID, nome e a seção em que o leitor está */
let ctxObs = null, ctxSec = null;
function ctxBar(pb) {
  if (ctxObs) ctxObs.disconnect();
  if (ctxSec) document.removeEventListener("medusa:section", ctxSec);
  document.getElementById("ctxbar")?.remove();
  const head = $(".pbbar .pbhead"); if (!head || !("IntersectionObserver" in window)) return;
  const bar = document.createElement("div"); bar.id = "ctxbar"; bar.className = "ctxbar"; bar.hidden = true;
  bar.innerHTML = `<span class="pbid">${esc(pb.id)}</span><b>${esc(pb.name)}</b><span class="ctx-sec muted"></span>`;
  document.body.appendChild(bar);
  const sec = bar.querySelector(".ctx-sec");
  ctxSec = e => { sec.textContent = e.detail ? "· " + e.detail : ""; };
  document.addEventListener("medusa:section", ctxSec);
  ctxObs = new IntersectionObserver(([en]) => { bar.hidden = en.isIntersecting || !document.contains(head); }, { rootMargin: "-56px 0px 0px 0px" });
  ctxObs.observe(head);
  window.addEventListener("hashchange", () => bar.remove(), { once: true });
}

/* campos do template (runbook e documento) como chips abaixo do título */
function fieldChips(pb) {
  const s = PBS.find(p => p.id === pb.id), f = (s && s.fields) || {};
  const vals = Object.entries(f).flatMap(([k, v]) => (Array.isArray(v) ? v : [v]).filter(Boolean).map(x => [k, x]));
  return vals.length ? `<div class="field-chips">${vals.map(([k, v]) => `<span class="chip" title="${esc(k)}">${esc(v)}</span>`).join("")}</div>` : "";
}
function govHtml(pb) {
  const g = pb.gov, props = pb.props, approval = typeInfo(pb.type || "playbook").approval;
  return `<div class="gov">
      <div><span>Status</span><b>${esc(statusLabel(pb.type, g.status))}</b></div>
      ${approval ? `<div><span>Aprovador${g.approver && g.status !== "Produção" ? " (últ. publicação)" : ""}</span><b>${esc(g.approver || "—")}</b></div>` : ""}
      <div><span>Último revisor</span><b>${esc(g.reviewer || "—")}</b></div>
      <div><span>Data de revisão</span><b>${esc(g.reviewed || "—")}</b></div>
      <div><span>Versão</span><b>${esc((props["Versão"] || "—").split(" ")[0])}</b></div>
      <div><span>Owner</span><b>${esc(props["Owner do documento"] || "—")}</b></div>
      ${pb.templateName ? `<div><span>Template</span><b>${esc(pb.templateName)}</b></div>` : ""}
    </div>`;
}
function updateHeader(pb) {
  const g = $(".pbbar .gov"); if (g) g.outerHTML = govHtml(pb);
  const sp = $(".pbhead > .status"); if (sp) sp.outerHTML = statusPill(pb.gov.status, pb.type);
}

/* ── ciclo de vida ── */
async function statusDialog(pb) {
  if (Editor.dirty || Editor.hasDraft(pb.id.toLowerCase())) return toast("Salve ou descarte as alterações dos editores deste playbook antes de mudar o status", "warn");
  const T = pb.type || "playbook", needAp = typeInfo(T).approval;
  let ap = { approvers: [], distinct: false };
  if (needAp) try { ap = await api("GET", `api/approvers?type=${T}&pid=${encodeURIComponent(pb.id)}`); } catch (e) { return toast(e.message, "err"); }
  /* só quem pode aprovar agora: a regra do aprovador diferente tira quem publica e quem fez a última alteração */
  const approvers = ap.approvers.filter(a => !a.excluded);
  const out = ap.approvers.filter(a => a.excluded);
  const apNote = !approvers.length ? `<div class="notice warn small">Ninguém pode aprovar agora${out.length ? `: ${out.map(a => `${esc(a.name)} ${esc(a.excluded)}`).join("; ")}` : ""}. Peça a um administrador para cadastrar outro aprovador${ap.distinct ? " ou para revisar a regra de governança" : ""}.</div>`
    : ap.distinct && out.length ? `<p class="muted small">Não aparece${out.length > 1 ? "m" : ""} ${out.map(a => a.login === App.user.login ? "você" : `${esc(a.name)} (${a.excluded})`).join(" nem ")}.</p>` : "";
  const cur = pb.gov.status, sts = App.data.statuses;
  const desc = { "Desenvolvimento": "Rascunho em elaboração. Visível só para quem pode ver rascunhos.",
    "Homologação": "Em validação com o time. Visualizadores já podem ler.",
    "Produção": needAp ? "Versão oficial em uso pelo SOC. Exige aprovador." : "Versão oficial, publicada para todos." };
  modal({
    title: `Status do ${pb.id}`, html: `<form id="stForm" class="tform">
      <div class="stepper">${sts.map((s, i) => `<label class="stp ${STATUS_CLS[s]} ${s === cur ? "cur" : ""}"><input type="radio" name="status" value="${esc(s)}" ${s === cur ? "disabled" : ""} ${i === sts.indexOf(cur) + 1 ? "checked" : ""}>
        <span class="n">${i + 1}</span><b>${esc(statusLabel(T, s))}</b><small>${desc[s]}</small>${s === cur ? `<em>atual</em>` : ""}</label>`).join("")}</div>
      <div id="apBox" ${needAp ? "" : "hidden"}><label>Aprovador<select class="in" name="approver"><option value="">Selecione…</option>${approvers.map(a => `<option value="${esc(a.login)}" ${a.login === App.user.login || approvers.length === 1 ? "selected" : ""}>${esc(a.name)} (${esc(a.roleName)})</option>`).join("")}</select></label>${apNote}</div>
      <label>Observação <small>(vai para a auditoria)</small><textarea class="in" name="note" rows="2" placeholder="ex.: validado com o SOC em reunião de 03/10"></textarea></label>
      <div class="err" id="sterr" hidden></div>
      <div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" type="submit">Confirmar mudança</button></div></form>`,
    onMount: (b, close) => {
      const form = $("#stForm", b);
      if (!form.querySelector("input[name=status]:checked")) { const f = form.querySelector("input[name=status]:not(:disabled)"); if (f) f.checked = true; }
      const sync = () => { $("#apBox", b).hidden = !needAp || form.status.value !== "Produção"; };
      form.addEventListener("change", sync); sync();
      form.querySelector("[data-cancel]").onclick = close;
      form.onsubmit = async e => {
        e.preventDefault();
        const f = new FormData(form), status = f.get("status");
        try {
          const r = await api("PUT", `api/pb/${pb.id}/status`, { status, approver: f.get("approver"), note: f.get("note"), rev: pb.rev });
          replacePlaybook(r.playbook); close(); toast(`${pb.id} agora está em ${statusLabel(T, status)}`); route();
        } catch (x) { $("#sterr", b).textContent = x.message; $("#sterr", b).hidden = false; }
      };
    }
  });
}
/* pendências do documento (referências quebradas; no playbook, caixas sem "ao clicar", passos sem caixa, IDs de passo
   repetidos e ramos só de um lado): selo no topo, para quem pode editar; o clique lista e leva ao trecho */
async function lintBadge(pb) {
  let d; try { d = await api("GET", `api/doc/${pb.id}/lint`); } catch { return; }
  const acts = $(".pbhead .pbactions");
  if (!d.count || !acts || !location.hash.toLowerCase().startsWith(`#/${pb.slug}`)) return;
  acts.insertAdjacentHTML("afterbegin", `<button class="btn ghost sm lint-badge" id="lintBtn" title="Pendências encontradas na verificação">${ic("warn")}${d.count} pendência${d.count > 1 ? "s" : ""}</button>`);
  $("#lintBtn").onclick = () => {
    const go = i => i.kind === "node-norefs" ? `#/${pb.slug}/editar-fluxo` : /^(step|ramo)/.test(i.kind) ? `#/${pb.slug}/doc/${encodeURIComponent(i.ref)}` : "";
    pushView(`${ic("warn")} Pendências de ${esc(pb.id)}`, `<ul class="lint-list">${d.issues.map(i => `<li>${go(i) ? `<a href="${go(i)}">${esc(i.message)}</a>` : esc(i.message)}</li>`).join("")}</ul>
      <p class="muted small">Verificação automática: não impede salvar nem publicar.</p>`, pb);
  };
}
/* mover para outra pasta (runbook e documento): só muda a organização, sem gerar versão */
async function moveDialog(pb) {
  let d; try { d = await api("GET", `api/folders?type=${pb.type}`); } catch (e) { return toast(e.message, "err"); }
  const s = PBS.find(p => p.id === pb.id) || {};
  modal({ title: `Mover ${esc(pb.id)}`, html: `<form class="tform" id="mvForm"><label>Pasta<select class="in" name="folder">${folderOptions(d.folders, s.folderId)}</select></label>
      <div class="err" id="mvErr" hidden></div><div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" type="submit">Mover</button></div></form>`,
    onMount: (b, close) => {
      const f = $("#mvForm", b); f.querySelector("[data-cancel]").onclick = close;
      f.onsubmit = async e => {
        e.preventDefault();
        try { await api("PUT", `api/doc/${pb.id}/folder`, { folder_id: f.folder.value || null }); close(); toast("Movido"); await refreshIndex(); route(); }
        catch (x) { $("#mvErr", b).textContent = x.message; $("#mvErr", b).hidden = false; }
      };
    } });
}
/* <option> de pastas em árvore (recuo por nível); "" = Sem pasta */
function folderOptions(folders, sel, none = "Sem pasta") {
  const kids = {}; folders.forEach(f => (kids[f.parentId ?? "root"] = kids[f.parentId ?? "root"] || []).push(f));
  const out = [`<option value="" ${sel == null ? "selected" : ""}>${esc(none)}</option>`];
  const walk = (pid, depth) => (kids[pid] || []).forEach(f => { out.push(`<option value="${f.id}" ${f.id === sel ? "selected" : ""}>${"  ".repeat(depth)}${depth ? "└ " : ""}${esc(f.name)}</option>`); walk(f.id, depth + 1); });
  walk("root", 0);
  return out.join("");
}
/* rótulos de status por tipo (só interface; o valor gravado é sempre o mesmo) */
const STATUS_LABELS = { doc: { "Desenvolvimento": "Rascunho", "Homologação": "Em revisão", "Produção": "Publicado" } };
const statusLabel = (t, st) => ((STATUS_LABELS[t] || {})[st]) || st;

function deleteDialog(pb) {
  if (Editor.dirty) return toast("Salve ou descarte as alterações antes", "warn");
  modal({
    title: `Excluir ${pb.id}`, html: `<form id="delForm" class="tform">
      <div class="notice danger">O documento <b>${esc(pb.id)} — ${esc(pb.name)}</b> (${esc(pb.gov.status)}) sai da ferramenta para todos os usuários.
        Os arquivos vão para a lixeira do servidor (<code>data/lixeira</code>) e podem ser restaurados por quem administra o servidor.</div>
      <label>Para confirmar, digite <b>${esc(pb.id)}</b><input class="in" name="confirm" autocomplete="off"></label>
      <div class="err" id="delerr" hidden></div>
      <div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn danger" type="submit" disabled>Excluir</button></div></form>`,
    onMount: (b, close) => {
      const form = $("#delForm", b), btn = form.querySelector("[type=submit]");
      form.confirm.oninput = () => { btn.disabled = form.confirm.value.trim().toUpperCase() !== pb.id; };
      form.querySelector("[data-cancel]").onclick = close;
      form.onsubmit = async e => {
        e.preventDefault();
        try {
          await api("DELETE", `api/pb/${pb.id}`, { confirm: form.confirm.value.trim().toUpperCase() });
          removePlaybook(pb.id); Editor.dropDrafts(pb.id.toLowerCase()); close(); toast(`${pb.id} excluído (movido para a lixeira)`); location.hash = "#/";
        } catch (x) { $("#delerr", b).textContent = x.message; $("#delerr", b).hidden = false; }
      };
    }
  });
}

/* ── fluxograma (leitura) ── */
let zoom = 1;
function badgesFor(pb) {
  const out = {};
  for (const n of pb.flow.nodes) {
    const ids = (pb.refs[n.id] || []).filter(r => pb.steps.some(x => x.id === r));
    if (ids.length) out[n.id] = ids.length <= 2 ? ids.join(" ") : ids[0] + "–" + ids[ids.length - 1];
  }
  return out;
}
function tabFlow(pb, el) {
  zoom = 1;
  el.innerHTML = `<div class="flowbar"><div class="legend"><span><i style="color:#B25E09"></i>handoff ao N2</span><span><i style="color:#C0272D"></i>escalonamento ao CSIRT</span><span><i style="color:#7A3E9D"></i>outro playbook</span><span><i style="color:#5B6673"></i>time de apoio</span></div>
    <div class="zoom"><button data-z="-1" title="Diminuir" aria-label="Diminuir">${ic("zoomOut")}</button><button data-z="0" title="Ajustar à largura" aria-label="Ajustar à largura">${ic("fit")}</button><button data-z="1" title="Aumentar" aria-label="Aumentar">${ic("zoomIn")}</button></div></div>
    <div class="flowbox viewer" id="flowbox" title="Clique numa caixa para ler o trecho da documentação, ou no nome de um time para ver as responsabilidades"></div>`;
  const live = n => (pb.refs[n.id] || []).length || n.team;
  const { svg, vb } = Flow.svg(pb.flow, { badges: badgesFor(pb), nodeClass: n => live(n) ? "" : "static" });
  const box = $("#flowbox");
  box.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb.join(" ")}" width="${vb[2]}" height="${vb[3]}">${svg}</svg>`;
  const svgEl = $("svg", box);
  const apply = () => { svgEl.setAttribute("width", vb[2] * zoom); svgEl.setAttribute("height", vb[3] * zoom); };
  const fit = () => { zoom = Math.min(1.4, (box.clientWidth - 4) / vb[2]); apply(); };
  fit();
  el.querySelector(".zoom").onclick = e => {
    const zb = e.target.closest("[data-z]"); if (!zb) return; const z = zb.dataset.z;
    if (z === "0") fit(); else { zoom = Math.max(.4, Math.min(2.5, zoom * (z === "1" ? 1.2 : 1 / 1.2))); apply(); }
  };
  const openNode = node => {
    svgEl.querySelectorAll(".node.sel").forEach(n => n.classList.remove("sel"));
    node.classList.add("sel");
    if (node.dataset.team) return showTeam(pb, node.dataset.team);
    const n = pb.flow.nodes.find(x => x.id === node.dataset.node);
    showRefs(pb, pb.refs[n.id], esc((n.lines || []).map(l => l.t).join(" ")), false);
  };
  svgEl.addEventListener("click", e => {
    const node = e.target.closest(".node");
    if (!node || node.classList.contains("static")) return;
    openNode(node);
  });
  /* teclado: Enter/Espaço abre o trecho; setas vão à caixa mais próxima naquela direção */
  svgEl.addEventListener("keydown", e => {
    const node = e.target.closest && e.target.closest(".node[tabindex]"); if (!node) return;
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); return openNode(node); }
    const dir = { ArrowRight: [1, 0], ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1] }[e.key]; if (!dir) return;
    const c = r => [r.left + r.width / 2, r.top + r.height / 2], me = c(node.getBoundingClientRect());
    let best = null, bd = Infinity;
    for (const o of svgEl.querySelectorAll(".node[tabindex]")) {
      if (o === node) continue;
      const q = c(o.getBoundingClientRect()), dx = q[0] - me[0], dy = q[1] - me[1], along = dx * dir[0] + dy * dir[1];
      if (along <= 4) continue;
      const d = along + Math.abs(dir[0] ? dy : dx) * 2; if (d < bd) { bd = d; best = o; }
    }
    if (best) { e.preventDefault(); best.focus(); best.scrollIntoView({ block: "nearest", inline: "nearest" }); }
  });
  flowList(pb, el, openNode, svgEl);
}
/* o mesmo fluxo como lista por raia: alternativa para leitor de tela, teclado e telas estreitas */
function flowList(pb, el, openNode, svgEl) {
  const live = n => (pb.refs[n.id] || []).length || n.team;
  const lanes = (pb.flow.lanes || []).map(l => ({ l, ns: pb.flow.nodes.filter(n => n.lane === l.key && live(n)) })).filter(x => x.ns.length);
  if (!lanes.length) return;
  const bd = badgesFor(pb);
  const d = document.createElement("details"); d.className = "flowlist";
  d.open = window.matchMedia("(max-width:640px)").matches;
  d.innerHTML = `<summary>Ver o fluxo como lista, por time</summary>${lanes.map(({ l, ns }) => `<section class="fl-lane"><h3>${esc(l.label || l.key)}</h3><ul>${ns.map(n => `<li><button type="button" class="fl-node" data-n="${esc(n.id)}">${bd[n.id] ? `<b class="fl-b">${esc(bd[n.id])}</b>` : ""}<span>${esc((n.lines || []).map(x => x.t).join(" ") || n.id)}</span></button></li>`).join("")}</ul></section>`).join("")}`;
  d.onclick = e => { const b = e.target.closest("[data-n]"); if (!b) return; const node = svgEl.querySelector(`.node[data-node="${CSS.escape(b.dataset.n)}"]`); if (node) openNode(node); };
  el.appendChild(d);
}

/* ── documento completo ── */
/* leitura: linhas e tabelas sem nenhum texto não viram ruído; a seção sem nada vira uma linha discreta */
function pruneEmpty(root) {
  root.querySelectorAll("tbody tr").forEach(tr => { if (![...tr.cells].some(c => c.textContent.trim() || c.querySelector("img,.codeblock"))) tr.remove(); });
  root.querySelectorAll("table").forEach(t => { if (!t.querySelector("tbody tr")) t.remove(); });
  root.querySelectorAll("section.md:not(.intro):not(.props)").forEach(sec => {
    if ([...sec.children].some(c => !/^H[23]$/.test(c.tagName) && (c.textContent.trim() || c.querySelector("img,.codeblock")))) return;
    sec.classList.add("blank");
    sec.insertAdjacentHTML("beforeend", `<p class="muted small blank-note">Ainda sem conteúdo.</p>`);
  });
}
/* "marcar como feito": só neste navegador e nesta sessão, para quem executa o procedimento */
function stepChecks(pb, root) {
  const key = `done:${pb.id}`; let done = new Set();
  try { done = new Set(JSON.parse(sessionStorage.getItem(key) || "[]")); } catch {}
  root.querySelectorAll(".doc tbody tr").forEach(tr => {
    const c = tr.cells[0]; const id = c && c.textContent.trim().split(/\s/)[0];
    if (!id || !/^[A-Z]{1,2}\d{1,2}$/.test(id) || c.querySelector(".stepdone")) return;
    const b = document.createElement("button"); b.type = "button"; b.className = "stepdone";
    const sync = () => { const on = done.has(id); b.setAttribute("aria-pressed", on); b.setAttribute("aria-label", `Marcar ${id} como feito`); b.title = on ? "Feito (desmarcar)" : "Marcar como feito"; tr.classList.toggle("is-done", on); };
    b.onclick = () => { done.has(id) ? done.delete(id) : done.add(id); try { sessionStorage.setItem(key, JSON.stringify([...done])); } catch {} sync(); };
    c.prepend(b); sync();
  });
}
function tabDoc(pb, el, focus) {
  const secs = pb.sections.filter(s => !/^Fluxograma/.test(s.title));
  const isProps = s => /^Propriedades/i.test(s.title);
  const sec = s => isProps(s)
    ? `<section id="sec-${s.id}" class="md props"><details><summary><h2>${esc(s.title)}</h2></summary>${s.html}${s.subs.map(x => `<h3 id="sub-${x.id}">${esc(x.title)}</h3>${x.html}`).join("")}</details></section>`
    : `<section id="sec-${s.id}" class="md"><h2>${esc(s.title)}</h2>${s.html}${s.subs.map(x => `<h3 id="sub-${x.id}">${esc(x.title)}</h3>${x.html}`).join("")}</section>`;
  const tail = (secs.concat([])).filter(isProps), main = secs.filter(s => !isProps(s));
  el.innerHTML = `<div class="docgrid"><nav class="toc" aria-label="Neste documento">${main.concat(tail).map(s => `<a href="#" data-go="${s.id}">${esc(s.title)}</a>
      ${s.subs.length && s.subs.length <= 24 && !isProps(s) ? `<div class="toc-subs">${s.subs.map(x => `<a href="#" data-sub="${x.id}">${esc(x.title)}</a>`).join("")}</div>` : ""}`).join("")}</nav>
    <div class="doc">${pb.intro ? `<section class="md intro">${pb.intro}</section>` : ""}${main.concat(tail).map(sec).join("")}</div></div>`;
  const toc = el.querySelector(".toc");
  toc.onclick = e => {
    const a = e.target.closest("[data-go], [data-sub]"); if (!a) return;
    e.preventDefault();
    const t = document.getElementById(a.dataset.go ? "sec-" + a.dataset.go : "sub-" + a.dataset.sub);
    const d = t.querySelector("details"); if (d) d.open = true;
    t.scrollIntoView();
  };
  pruneEmpty(el.querySelector(".doc")); stepChecks(pb, el);
  spyToc(el);
  if (focus) setTimeout(() => focusInDoc(el, pb, decodeURIComponent(focus)), 30);
  citations(pb, el.querySelector(".doc"));
  Suggest.bindDoc(pb, el);
}
/* destaca no índice a seção que está sob o topo da janela e informa o nome dela à faixa de contexto */
function spyToc(el) {
  const links = [...el.querySelectorAll(".toc a[data-go]")], secs = links.map(a => document.getElementById("sec-" + a.dataset.go)).filter(Boolean);
  if (!secs.length) return;
  let last = null;
  const upd = () => {
    if (!document.contains(el)) return window.removeEventListener("scroll", upd);
    let cur = secs[0]; for (const sc of secs) if (sc.getBoundingClientRect().top <= 120) cur = sc;
    if (cur === last) return; last = cur;
    links.forEach(a => { const on = "sec-" + a.dataset.go === cur.id; a.classList.toggle("on", on); on ? a.setAttribute("aria-current", "location") : a.removeAttribute("aria-current"); });
    const h = cur.querySelector("h2"); document.dispatchEvent(new CustomEvent("medusa:section", { detail: h ? h.textContent : "" }));
  };
  window.addEventListener("scroll", upd, { passive: true }); upd();
}
/* "Referenciado por" e "Cita": documentos ligados a este pelo ID no texto (só os que você pode ver) */
async function citations(pb, box) {
  let d; try { d = await api("GET", `api/doc/${pb.id}/links`); } catch { return; }
  if (!document.contains(box) || (!d.in.length && !d.out.length)) return;
  const item = x => x.missing ? `<li class="muted">${esc(x.id)} <small>(não existe)</small></li>`
    : `<li><a href="#/${esc(x.slug)}/${x.type === "playbook" ? "fluxo" : "doc"}"><b>${esc(x.id)}</b> ${esc(x.name)}</a> ${statusPill(x.status, x.type)}</li>`;
  box.insertAdjacentHTML("beforeend", `<section class="md cites"><h2>Ligações</h2>
    ${d.in.length ? `<h3>Referenciado por</h3><ul class="cite-list">${d.in.map(item).join("")}</ul>` : ""}
    ${d.out.length ? `<h3>Cita</h3><ul class="cite-list">${d.out.map(item).join("")}</ul>` : ""}</section>`);
}
/* leva ao trecho: R2 → subseção do ramo; T3, A1, E4… → linha da tabela que começa com o ID */
function focusInDoc(el, pb, id) {
  let t = null;
  const ramo = pb.ramos.find(r => r.id === id);
  if (ramo) t = el.querySelector(`#sub-${CSS.escape(pb.sections.flatMap(s => s.subs).find(x => x.title === ramo.title)?.id || "")}`);
  if (!t) t = [...el.querySelectorAll(".doc tr")].find(tr => { const c = tr.querySelector("td"); return c && (c.textContent.trim() === id || c.textContent.trim().startsWith(id + " ")); });
  if (!t) return;
  t.scrollIntoView({ block: "center" }); t.classList.add("flash"); setTimeout(() => t.classList.remove("flash"), 2500);
}

/* Formulário com alteração não salva fora dos editores (Administração, Templates): a página registra em
   Unsaved.check uma função que diz se há mudança; a navegação e o fechamento da janela perguntam antes de descartar. */
const Unsaved = { check: null, dirty() { return !!(this.check && this.check()); } };

/* ───────── administração ───────── */
const Admin = (() => {
  const ACTIONS = { login: "Entrou", logout: "Saiu", login_falhou: "Falha de login", senha_alterada: "Trocou a senha", senha_redefinida: "Senha redefinida",
    usuario_criado: "Usuário criado", usuario_alterado: "Usuário alterado", usuario_excluido: "Usuário excluído", usuario_cli: "Usuário via linha de comando",
    documento_salvo: "Documento salvo", fluxograma_salvo: "Fluxograma salvo", status_alterado: "Status alterado", playbook_criado: "Playbook criado",
    playbook_excluido: "Playbook excluído", times_salvos: "Times editados", sessoes_encerradas: "Sessões encerradas",
    playbook_exportado: "Playbook exportado", playbooks_exportados: "Todos exportados", playbook_importado: "Playbook importado",
    marca_alterada: "Marca alterada", logo_alterada: "Logo alterada", logo_removida: "Logo removida",
    template_criado: "Template criado", template_alterado: "Template alterado", template_documento_salvo: "Documento do template salvo",
    template_fluxograma_salvo: "Fluxograma do template salvo", template_excluido: "Template excluído", template_exportado: "Template exportado",
    template_importado: "Template importado", template_times_salvos: "Times do template salvos", template_ramos_adicionados: "Ramos adicionados ao template",
    ramo_criado: "Ramo criado", ramo_excluido: "Ramo excluído", versao_restaurada: "Versão restaurada", admin_inicial: "Administrador inicial",
    logs_configurados: "Logs configurados", logs_testados: "Teste de envio de logs", auditoria_exportada: "Auditoria exportada",
    governanca_alterada: "Governança alterada", papel_criado: "Role criada", papel_alterado: "Role alterada", papel_excluido: "Role excluída",
    sugestao_criada: "Sugestão criada", sugestao_aceita: "Sugestão aceita", sugestao_recusada: "Sugestão recusada", sugestao_retirada: "Sugestão retirada",
    pasta_criada: "Pasta criada", pasta_renomeada: "Pasta renomeada", pasta_movida: "Pasta movida", pasta_excluida: "Pasta excluída",
    documento_movido: "Documento movido", pastas_do_template: "Pastas do template criadas", sso_configurado: "SSO configurado", sso_falhou: "Falha no SSO", imagem_enviada: "Imagem enviada", aplicacao_resetada: "Aplicação resetada" };
  const fmtTs = t => t ? new Date(t).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";

  function showTemp(user, pw, what) {
    modal({ title: what, html: `<p>Senha temporária de <b>${esc(user.name)}</b> (<code>${esc(user.login)}</code>):</p>
      <div class="temp-pw"><code id="tpw">${esc(pw)}</code><button class="btn ghost sm" id="cpy">Copiar</button></div>
      <p class="muted small">Ela aparece só agora. Entregue por um canal seguro; no primeiro acesso o usuário é obrigado a trocá-la.</p>
      <div class="create-actions"><button class="btn primary" data-ok>Entendi</button></div>`,
      onMount: (b, close) => {
        $("#cpy", b).onclick = () => navigator.clipboard.writeText(pw).then(() => toast("Copiada"), () => toast("Selecione e copie manualmente", "warn"));
        b.querySelector("[data-ok]").onclick = close;
      } });
  }

  /* Usuários: a tabela ocupa a largura toda e criar usuário abre um diálogo. Dar mais acesso, desativar e excluir
     pedem confirmação; depois de cada mudança a tabela é refeita e o foco volta ao mesmo controle. */
  let userFilter = "";
  async function users(el, focusSel) {
    let data;
    try { data = await api("GET", "api/users"); } catch (e) { el.innerHTML = `<div class="err" role="alert">${esc(e.message)}</div>`; return; }
    const me = App.user.login, role = k => data.roleList.find(r => r.key === k) || { key: k, name: k, priority: 0 };
    const byLogin = lg => data.users.find(u => u.login === lg);
    const sel = (attr, lg) => `[${attr}="${CSS.escape(lg)}"]`;
    const inactive = data.users.filter(u => !u.active).length;
    const roleSel = u => `<select class="in sm" data-role="${esc(u.login)}" aria-label="Role de ${esc(u.name)}" ${u.login === me ? "disabled title='Você não pode alterar a própria role'" : ""}>${data.roleList.map(r => `<option value="${esc(r.key)}" ${r.key === u.roleId ? "selected" : ""}>${esc(r.name)}</option>`).join("")}${data.roleList.some(r => r.key === u.roleId) ? "" : `<option selected disabled>${esc(u.roleName)}</option>`}</select>`;
    const authSel = u => `<select class="in sm" data-auth="${esc(u.login)}" aria-label="Autenticação de ${esc(u.name)}" ${u.login === me ? "disabled title='Você não pode alterar a própria forma de autenticação'" : ""}>
        <option value="local" ${u.auth !== "sso" ? "selected" : ""}>Senha local</option><option value="sso" ${u.auth === "sso" ? "selected" : ""}>SSO</option></select>`;
    const row = u => {
      const self = u.login === me;
      const tags = (self ? `<span class="tag">você</span>` : "") + (u.mustChange ? `<span class="tag warn">senha temporária</span>` : "")
        + (u.auth === "sso" && !u.ssoLinked ? `<span class="tag">aguardando 1º login</span>` : "");
      return `<tr class="${u.active ? "" : "off"}" data-q="${esc((u.name + " " + u.login + " " + u.roleName).toLowerCase())}">
        <td data-l="Usuário"><div class="ucell"><b>${esc(u.name)}</b><code>${esc(u.login)}</code>${tags ? `<span class="utags">${tags}</span>` : ""}</div></td>
        <td data-l="Autenticação">${authSel(u)}</td>
        <td data-l="Role">${roleSel(u)}</td>
        <td data-l="Acesso"><label class="switch"><input type="checkbox" data-active="${esc(u.login)}" aria-label="Acesso de ${esc(u.name)}" ${u.active ? "checked" : ""} ${self ? "disabled" : ""}><span>${u.active ? "Ativo" : "Inativo"}</span></label></td>
        <td data-l="Último acesso" class="small num">${fmtTs(u.lastLogin)}</td>
        <td data-l="Sessões">${u.sessions ? `<span class="tag">${u.sessions} ativa${u.sessions > 1 ? "s" : ""}</span>` : `<span class="muted small">—</span>`}</td>
        <td class="ucell-actions">${self ? "" : `<button class="btn ghost icon" data-more="${esc(u.login)}" aria-haspopup="menu" aria-label="Mais ações para ${esc(u.name)}" title="Mais ações">${ic("more")}</button>`}</td></tr>`;
    };
    el.innerHTML = `<section class="ecard ucard"><div class="ecard-h"><h2>Usuários</h2>
        <span class="muted small">${data.users.length} cadastrados${inactive ? ` · ${inactive} inativo${inactive > 1 ? "s" : ""}` : ""}</span>
        <div class="ecard-tools"><input class="in sm" type="search" id="ufilter" value="${esc(userFilter)}" placeholder="Filtrar usuários" aria-label="Filtrar usuários por nome, login ou role" title="Filtra por nome, login ou role">
          <button class="btn primary sm" id="newUserBtn">${ic("plus")}Novo usuário</button></div></div>
      <div class="tw"><table class="utable"><thead><tr><th>Usuário</th><th>Autenticação</th><th>Role</th><th>Acesso</th><th>Último acesso</th><th>Sessões</th><th><span class="sr-only">Ações</span></th></tr></thead>
        <tbody>${data.users.map(row).join("")}</tbody></table></div>
      <p class="empty small" id="unone" hidden>Nenhum usuário encontrado com esse filtro.</p>
      <p class="muted small ufoot">O que cada role pode fazer está em ${can("roles.manage") ? `<a href="#/admin/roles">Roles</a>` : "Roles"}. Para bloquear o acesso de alguém sem perder o histórico, desative em vez de excluir.</p></section>`;
    const filter = () => {
      const v = userFilter.trim().toLowerCase(); let shown = 0;
      el.querySelectorAll("tbody tr").forEach(tr => { tr.hidden = !!v && !tr.dataset.q.includes(v); if (!tr.hidden) shown++; });
      $("#unone", el).hidden = shown > 0;
    };
    $("#ufilter", el).oninput = e => { userFilter = e.target.value; filter(); };
    filter();
    const again = f => users(el, f);
    const upd = async (login, body, msg, f) => { try { await api("PUT", `api/users/${encodeURIComponent(login)}`, body); toast(msg); } catch (e) { toast(e.message, "err"); } again(f); };
    el.querySelectorAll("[data-role]").forEach(s => s.onchange = async () => {
      const u = byLogin(s.dataset.role), to = role(s.value), from = role(u.roleId);
      /* só a mudança que dá mais acesso pede confirmação: um select mudado sem querer não pode criar um administrador */
      if (to.priority > from.priority && !(await ask(`Mudar ${u.name} de ${from.name} para ${to.name}? A nova role tem mais permissões${to.key === "admin" ? ", inclusive usuários, roles e configurações" : ""}. Vale a partir da próxima ação da pessoa no sistema.`,
        { title: "Dar mais acesso", ok: `Mudar para ${to.name}`, danger: to.key === "admin" }))) { s.value = u.roleId; return; }
      upd(u.login, { role: to.key }, `${u.name}: ${to.name}`, sel("data-role", u.login));
    });
    el.querySelectorAll("[data-auth]").forEach(s => s.onchange = async () => {
      const u = byLogin(s.dataset.auth), to = s.value;
      if (!(await ask(to === "sso" ? `Converter ${u.name} para SSO? A senha local deixa de funcionar e as sessões abertas são encerradas. O login (${u.login}) precisa ser igual ao enviado pelo provedor.`
        : `Voltar ${u.name} para senha local? Uma senha temporária será gerada.`, { title: "Forma de autenticação", ok: "Alterar" }))) { s.value = to === "sso" ? "local" : "sso"; return; }
      try { const r = await api("PUT", `api/users/${encodeURIComponent(u.login)}`, { auth: to }); toast("Autenticação alterada"); if (r.tempPassword) showTemp(r.user, r.tempPassword, "Senha local gerada"); }
      catch (e) { toast(e.message, "err"); }
      again(sel("data-auth", u.login));
    });
    el.querySelectorAll("[data-active]").forEach(c => c.onchange = async () => {
      const u = byLogin(c.dataset.active);
      if (!c.checked && !(await ask(`Desativar ${u.name}? A pessoa não consegue mais entrar${u.sessions ? ` e ${u.sessions === 1 ? "a sessão aberta é encerrada" : `as ${u.sessions} sessões abertas são encerradas`}` : ""}. Dá para reativar a qualquer momento, sem perder nada.`,
        { title: "Desativar usuário", ok: "Desativar", danger: true }))) { c.checked = true; return; }
      upd(u.login, { active: c.checked }, c.checked ? `${u.name} reativado` : `${u.name} desativado`, sel("data-active", u.login));
    });
    const resetPw = async u => {
      if (!(await ask(`Gerar nova senha temporária para ${u.name}? As sessões abertas são encerradas e a senha atual deixa de funcionar.`, { title: "Redefinir senha", ok: "Gerar senha" }))) return;
      try { const r = await api("POST", `api/users/${encodeURIComponent(u.login)}/reset`); showTemp(r.user, r.tempPassword, "Senha redefinida"); again(sel("data-more", u.login)); } catch (e) { toast(e.message, "err"); }
    };
    const kick = async u => {
      try { const r = await api("POST", `api/users/${encodeURIComponent(u.login)}/logout`); toast(`${r.closed} sessão(ões) encerrada(s)`); } catch (e) { toast(e.message, "err"); }
      again(sel("data-more", u.login));
    };
    const del = async u => {
      if (!(await ask(`Excluir ${u.name} (${u.login})? A conta sai da lista e não pode ser recuperada; a auditoria continua registrando o login. Para só bloquear o acesso, desative.`,
        { title: "Excluir usuário", ok: "Excluir usuário", danger: true }))) return;
      try { await api("DELETE", `api/users/${encodeURIComponent(u.login)}`); toast(`${u.name} excluído`); } catch (e) { toast(e.message, "err"); }
      again("#ufilter");
    };
    el.querySelectorAll("[data-more]").forEach(b => b.onclick = () => {
      const u = byLogin(b.dataset.more);
      actionsMenu(b, [
        ...(u.auth === "sso" ? [] : [{ icon: "key", label: "Redefinir senha", hint: "Gera uma senha temporária e encerra as sessões", run: () => resetPw(u) }]),
        ...(u.sessions ? [{ icon: "logout", label: "Encerrar sessões", hint: `Desconecta de ${u.sessions === 1 ? "1 navegador" : `${u.sessions} navegadores`}`, run: () => kick(u) }] : []),
        { icon: "trash", label: "Excluir usuário", hint: "Remove a conta; para bloquear, prefira desativar", run: () => del(u) }]);
    });
    $("#newUserBtn", el).onclick = () => newUserDialog(data, login => again(sel("data-more", login)));
    const f = focusSel && el.querySelector(focusSel);
    if (f) f.focus();
  }

  function newUserDialog(data, done) {
    modal({ title: "Novo usuário", html: `<form id="newUser" class="tform" autocomplete="off">
        <label>Nome<input class="in" name="name" required maxlength="80" placeholder="Nome e sobrenome"></label>
        <label>Login<input class="in" name="login" required maxlength="80" pattern="[a-z0-9._@\\-]{3,80}" autocapitalize="off" spellcheck="false" aria-describedby="nuLoginHelp" placeholder="ex.: maria.souza ou maria@empresa.com"></label>
        <p class="muted small" id="nuLoginHelp">3 a 80 caracteres: letras minúsculas, números, ponto, hífen, sublinhado ou @. No SSO, igual ao login enviado pelo provedor.</p>
        <label>Autenticação<select class="in" name="auth"><option value="local">Senha local (senha temporária gerada agora)</option><option value="sso">SSO (entra pelo provedor com este login)</option></select></label>
        <label>Role<select class="in" name="role">${data.roleList.map(r => `<option value="${esc(r.key)}" ${r.key === "viewer" ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select></label>
        <p class="muted small">O que cada role pode fazer está em Administração → Roles.</p>
        <div class="err" id="nuerr" role="alert" hidden></div>
        <div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" type="submit">Criar usuário</button></div></form>`,
      onMount: (b, close) => {
        const form = $("#newUser", b), login = form.login, err = $("#nuerr", b);
        /* o login é sempre minúsculo: converte enquanto digita, em vez de recusar no fim */
        login.oninput = () => { const p = login.selectionStart; login.value = login.value.toLowerCase(); login.setSelectionRange(p, p); login.removeAttribute("aria-invalid"); };
        form.querySelector("[data-cancel]").onclick = close;
        form.onsubmit = async e => {
          e.preventDefault();
          const f = new FormData(form), btn = form.querySelector("[type=submit]");
          btn.disabled = true;
          try {
            const r = await api("POST", "api/users", { name: f.get("name"), login: f.get("login").trim().toLowerCase(), role: f.get("role"), auth: f.get("auth") });
            close();
            if (r.tempPassword) showTemp(r.user, r.tempPassword, "Usuário criado"); else toast("Usuário SSO pré-cadastrado: entra pelo botão de SSO");
            done(r.user.login);
          } catch (x) {
            err.textContent = x.message; err.hidden = false; btn.disabled = false;
            if (/login/i.test(x.message)) { login.setAttribute("aria-invalid", "true"); login.focus(); }
          }
        };
      } });
  }

  /* Auditoria: a trilha de evidência. Os filtros (período, tipo de ação, usuário e texto, que procura também nos
     detalhes, como o IP) rodam no servidor; a tela mostra até 500 eventos e diz quantos existem no recorte, que pode
     ser exportado. Horários do servidor, com segundos. */
  const CATS = [["acesso", "Acesso e sessões", /^(login|logout|senha_alterada|sessoes_|sso_falhou)/],
    ["pessoas", "Usuários, roles e governança", /^(usuario_|papel_|governanca_|admin_inicial|senha_redefinida)/],
    ["docs", "Documentos", /^(documento_|fluxograma_|status_|playbook|ramo_|versao_|sugestao_|pasta_|imagem_|times_salvos)/],
    ["templates", "Templates", /^(template_|pastas_do_template)/],
    ["config", "Configuração e exportações", /^(logs_|sso_configurado|marca_|logo_|aplicacao_|auditoria_)/]];
  const ALERT = /excluid|falhou|papel_|sso_configurado|aplicacao_resetada|governanca_|senha_redefinida|sessoes_encerradas/;
  const DETAIL_LBL = { ip: "IP", papel: "role", autenticacao: "autenticação", retencao_dias: "retenção (dias)", http: "HTTP", arquivo: "arquivo",
    configuracoes: "configurações", usuarios: "usuários", permissoes: "permissões", copia_de: "cópia de", realocados_para: "realocados para",
    aprovador_diferente: "aprovador diferente", versao: "versão", sugestao: "sugestão", secao: "seção", tem_texto: "com texto",
    documentos_movidos: "documentos movidos", subpastas_movidas: "subpastas movidas", usuario: "usuário", acoes: "ações" };
  const auditTs = t => t ? esc(String(t).replace("T", " ")) : "—";
  const yes = v => v === true || v === "sim" ? "Sim" : v === false || v === "não" ? "Não" : v;
  function auditDetail(e) {
    return Object.entries(e).filter(([k]) => !["ts", "user", "action", "target"].includes(k)).map(([k, v]) => {
      if ((k === "adicionadas" || k === "removidas") && v) return String(v).split(", ").map(p => `<span class="perm-chg ${k === "adicionadas" ? "add" : "rm"}">${k === "adicionadas" ? "+" : "−"} ${esc(p)}</span>`).join(" ");
      if ((k === "adicionadas" || k === "removidas")) return "";
      return `${esc(DETAIL_LBL[k] || k.replace(/_/g, " "))}: <b>${esc(yes(v))}</b>`;
    }).filter(Boolean).join(" · ");
  }
  const auditTarget = t => esc(String(t || "").replace(/^papel:/, "role ").replace(/^pasta:/, "pasta "));
  let auditF = { days: "0", cat: "", user: "", q: "" }, auditCtl = null;
  async function auditLog(el) {
    el.innerHTML = `<section class="ecard"><div class="ecard-h"><h2>Auditoria</h2><span class="muted small" id="acount" role="status" aria-live="polite"></span></div>
      <form class="audit-bar" id="aform" role="search" aria-label="Filtrar a auditoria">
        <label>Período<select class="in sm" name="days">${[["1", "Últimas 24 horas"], ["7", "Últimos 7 dias"], ["30", "Últimos 30 dias"], ["0", "Todo o período guardado"]].map(([v, l]) => `<option value="${v}" ${auditF.days === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label>Tipo de ação<select class="in sm" name="cat"><option value="">Todas</option>${CATS.map(([k, l]) => `<option value="${k}" ${auditF.cat === k ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label>Usuário<input class="in sm" name="user" value="${esc(auditF.user)}" list="auserList" placeholder="login exato" autocomplete="off" spellcheck="false"></label>
        <label class="grow">Buscar<input class="in sm" type="search" name="q" value="${esc(auditF.q)}" placeholder="Alvo, ação, IP ou detalhe" spellcheck="false"></label>
        <a class="btn ghost sm" id="aexp" download>${ic("download")}Exportar recorte</a>
        <datalist id="auserList"></datalist></form>
      <p class="muted small audit-note">Horários do servidor, com segundos. A tela mostra até 500 eventos, os mais recentes primeiro; para mais, refine o filtro ou exporte o recorte (JSON Lines).</p>
      <div class="tw"><table class="utable audit"><caption class="sr-only">Eventos de auditoria</caption>
        <thead><tr><th scope="col">Quando</th><th scope="col">Quem</th><th scope="col">Ação</th><th scope="col">Alvo</th><th scope="col">Detalhes</th></tr></thead><tbody id="arows"></tbody></table></div>
      <div class="lib-empty" id="aempty" hidden><p>Nenhum evento neste recorte.</p><button type="button" class="btn ghost sm" id="aclear">Limpar filtros</button></div>
      <div class="err" id="aerr" role="alert" hidden></div></section>`;
    const form = $("#aform", el), users = new Set();
    const params = () => {
      const p = new URLSearchParams({ days: auditF.days, limit: "500" });
      if (auditF.q.trim()) p.set("q", auditF.q.trim());
      if (auditF.user.trim()) p.set("user", auditF.user.trim().toLowerCase());
      const cat = CATS.find(c => c[0] === auditF.cat);
      if (cat) p.set("actions", Object.keys(ACTIONS).filter(a => cat[2].test(a)).join(","));
      return p;
    };
    const load = async () => {
      if (auditCtl) auditCtl.abort();
      auditCtl = new AbortController();
      const p = params();
      const ex = new URLSearchParams(p); ex.delete("limit"); if (ex.get("days") === "0") ex.set("days", "3650");
      $("#aexp", el).href = `api/audit/export?${ex}`;
      let d;
      try { d = await api("GET", `api/audit?${p}`, undefined, { signal: auditCtl.signal }); }
      catch (e) { if (e.name === "AbortError") return; $("#aerr", el).textContent = e.message; $("#aerr", el).hidden = false; return; }
      $("#aerr", el).hidden = true;
      d.entries.forEach(e => users.add(e.user));
      $("#auserList", el).innerHTML = [...users].sort().map(u => `<option value="${esc(u)}">`).join("");
      $("#arows", el).innerHTML = d.entries.map(e => `<tr><td data-l="Quando" class="small num mono-ts"><time datetime="${esc(e.ts)}">${auditTs(e.ts)}</time></td>
        <td data-l="Quem"><code>${esc(e.user)}</code></td>
        <td data-l="Ação"><span class="tag ${ALERT.test(e.action) ? "warn" : ""}">${esc(ACTIONS[e.action] || e.action.replace(/_/g, " "))}</span></td>
        <td data-l="Alvo">${auditTarget(e.target) || `<span class="muted">—</span>`}</td><td data-l="Detalhes" class="small">${auditDetail(e) || `<span class="muted">—</span>`}</td></tr>`).join("");
      const n = d.entries.length, filtered = auditF.q.trim() || auditF.user.trim() || auditF.cat || auditF.days !== "0";
      $("#acount", el).textContent = !d.total ? "nenhum evento" : n < d.total ? `${n.toLocaleString("pt-BR")} mais recentes de ${d.total.toLocaleString("pt-BR")} eventos` : `${d.total.toLocaleString("pt-BR")} evento${d.total > 1 ? "s" : ""}${filtered ? " no recorte" : ""}`;
      $("#aempty", el).hidden = n > 0; $("#aclear", el).hidden = !filtered;
      el.querySelector(".tw").hidden = n === 0;
    };
    let t = null;
    form.oninput = e => { auditF[e.target.name] = e.target.value; clearTimeout(t); t = setTimeout(load, e.target.tagName === "SELECT" ? 0 : 250); };
    form.onsubmit = e => { e.preventDefault(); load(); };
    $("#aclear", el).onclick = () => { auditF = { days: "0", cat: "", user: "", q: "" }; auditLog(el); };
    load();
  }

  /* Governança: regras que valem para a instalação inteira e, por último, a zona de perigo com o reset */
  async function governanceTab(el) {
    let g;
    try { g = (await api("GET", "api/governance")).governance; } catch (e) { el.innerHTML = `<div class="err" role="alert">${esc(e.message)}</div>`; return; }
    el.innerHTML = `<div class="gov-page">
      <section class="ecard"><div class="ecard-h"><h2>Aprovação para Produção</h2></div>
        <label class="switch"><input type="checkbox" id="govDistinct" ${g.require_distinct_approver ? "checked" : ""}><span>Aprovador diferente de quem edita</span></label>
        <p class="muted small">Ao publicar em Produção, o aprovador não pode ser quem está publicando nem quem fez a última alteração do conteúdo. Recomendado: desligue só em instalações com uma única pessoa editando. A mudança vale na hora.</p></section>
      ${can("app.reset") ? `<section class="ecard danger-zone"><div class="ecard-h"><h2>Zona de perigo</h2></div>
        <div class="dz-row"><div><b>Resetar aplicação</b>
          <p class="muted small">Volta a instalação ao estado de recém-instalada para todos os usuários. Antes de confirmar, você vê o que sai; uma cópia de tudo vai para a lixeira do servidor.</p></div>
          <button class="btn danger" id="resetBtn">Resetar aplicação…</button></div></section>` : ""}</div>`;
    $("#govDistinct", el).onchange = async e => {
      const on = e.target.checked;
      if (!on && !(await ask("Desligar a regra? Quem edita um playbook poderá também aprová-lo para Produção.", { title: "Governança", ok: "Desligar", danger: true }))) { e.target.checked = true; return; }
      try { await api("PUT", "api/governance", { require_distinct_approver: on }); toast(on ? "Regra do aprovador ligada" : "Regra do aprovador desligada"); }
      catch (x) { toast(x.message, "err"); e.target.checked = !on; }
    };
    if ($("#resetBtn", el)) $("#resetBtn", el).onclick = resetDialog;
  }

  /* Aparência: o nome do workspace, o contato e a logo. O tema (claro/escuro) é escolha de cada usuário, na barra lateral. */
  function appearance(el) {
    const b = Brand.get();
    const logoImg = b.logo ? `<img src="api/branding/logo?v=${esc(b.logo)}" alt="Logo atual">` : "";
    el.innerHTML = `<div class="appearance">
      <section class="ecard ap-card"><header class="ap-h"><h2>Workspace</h2></header>
        <div class="ap-body"><label>Nome<input class="in" id="apName" maxlength="40" value="${esc(b.name)}" placeholder="${esc(Brand.DEFAULT.name)}" aria-describedby="apNameHelp"></label>
          <p class="muted small" id="apNameHelp">Aparece na barra lateral, no login e na aba do navegador.</p>
          <label>Contato para acesso<input class="in" id="apContact" maxlength="120" value="${esc(b.contact || "")}" placeholder="ex.: Plantão SOC · ramal 4400 · #soc-acesso" aria-describedby="apContactHelp"></label>
          <p class="muted small" id="apContactHelp">Aparece no login para quem está sem acesso ou bloqueado. Em branco, o login diz para falar com um administrador do workspace.</p><div class="err" id="aperr" role="alert" hidden></div></div>
        <footer class="ap-foot"><span class="ap-dirty" id="apDirty" hidden>Alterações não salvas</span><button class="btn ghost" id="apReset" title="Preenche com o nome padrão e esvazia o contato; nada muda até salvar">Restaurar padrão</button><button class="btn primary" id="apSave" disabled>Salvar</button></footer></section>
      <section class="ecard ap-card"><header class="ap-h"><h2>Logo</h2></header>
        <div class="ap-body"><div class="logo-cur"><div class="lg">${logoImg || `<span class="small">sem logo</span>`}</div>
            <div class="lg dark" title="Como fica no tema escuro">${logoImg || `<span class="small">sem logo</span>`}</div></div>
          <label class="logo-drop" id="lgDrop" tabindex="0" role="button" aria-describedby="lgHelp">${ic("upload")}<span>${b.logo ? "Trocar logo:" : "Enviar logo:"} arraste a imagem ou clique para escolher</span><input type="file" id="lgFile" accept="image/png,image/jpeg,image/svg+xml,image/webp" hidden></label>
          <p class="muted small" id="lgHelp">PNG, SVG, JPG ou WEBP até 512 KB. Prefira fundo transparente; a prévia mostra os dois temas. Envia na hora.</p></div>
        <footer class="ap-foot"><button class="btn ghost" id="lgDel" ${b.logo ? "" : "disabled"}>Remover logo</button></footer></section></div>`;
    const name = $("#apName", el), contact = $("#apContact", el), save = $("#apSave", el);
    let base = [b.name, b.contact || ""];
    const changed = () => name.value.trim() !== base[0] || contact.value.trim() !== base[1];
    const mark = () => { const d = changed(); save.disabled = !d; $("#apDirty", el).hidden = !d; };
    Unsaved.check = () => el.isConnected && !!$("#apName", el) && changed();
    name.oninput = contact.oninput = mark;
    $("#apReset", el).onclick = () => { name.value = Brand.DEFAULT.name; contact.value = ""; mark(); name.focus(); };
    save.onclick = async () => {
      try {
        Brand.apply(await api("PUT", "api/branding", { name: name.value.trim(), contact: contact.value.trim() }));
        base = [name.value.trim(), contact.value.trim()]; $("#aperr", el).hidden = true; mark(); toast("Workspace salvo");
      } catch (x) { $("#aperr", el).textContent = x.message; $("#aperr", el).hidden = false; }
    };
    const upload = file => {
      if (!file) return;
      if (file.size > 512 * 1024) return toast("Logo grande demais (máx. 512 KB)", "err");
      const rd = new FileReader();
      rd.onload = async () => {
        try { Brand.apply(await api("PUT", "api/branding/logo", { dataUrl: rd.result })); toast("Logo atualizada"); appearance(el); $("#lgDrop", el).focus(); }
        catch (x) { toast(x.message, "err"); }
      };
      rd.readAsDataURL(file);
    };
    $("#lgFile", el).onchange = e => upload(e.target.files[0]);
    const drop = $("#lgDrop", el);
    drop.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("#lgFile", el).click(); } };
    drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
    drop.ondragleave = () => drop.classList.remove("over");
    drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); upload(e.dataTransfer.files[0]); };
    $("#lgDel", el).onclick = async () => {
      if (!(await ask("Remover a logo? A barra lateral volta a mostrar o símbolo padrão.", { title: "Remover logo", ok: "Remover", danger: true }))) return;
      try { Brand.apply(await api("DELETE", "api/branding/logo")); toast("Logo removida"); appearance(el); $("#lgDrop", el).focus(); } catch (x) { toast(x.message, "err"); }
    };
  }

  /* ── roles: lista à esquerda; à direita, o editor com a matriz ação × tipo de documento e as permissões da
     plataforma, agrupadas por risco. Permissões que a sua role não tem aparecem desabilitadas (não dá para conceder o
     que não se tem). Alteração não salva protege a navegação; mexer em permissões críticas de uma role em uso pede
     confirmação. ── */
  const GLOBAL_GROUPS = [["Templates", ["templates.view", "templates.edit", "templates.delete"]],
    ["Pessoas e acesso", ["users.manage", "roles.manage", "sso.manage"]],
    ["Auditoria e integrações", ["audit.view", "logs.manage"]],
    ["Instalação", ["branding.edit", "app.reset"]]];
  const PERM_HINT = { "users.manage": "cria contas, troca roles e redefine senhas", "roles.manage": "define o que cada role pode fazer",
    "sso.manage": "muda como todos entram", "logs.manage": "muda a retenção e para onde a auditoria vai", "app.reset": "apaga o conteúdo da instalação e muda a governança" };
  const CRITICAL = ["users.manage", "roles.manage", "sso.manage", "app.reset"];
  async function roles(el, key) {
    let d; try { d = await api("GET", "api/roles"); } catch (e) { el.innerHTML = `<div class="err" role="alert">${esc(e.message)}</div>`; return; }
    const cat = d.catalog, mine = new Set(d.mine), n = (v, one, many) => `${v} ${v === 1 ? one : many}`;
    const isNew = key === "novo", cur = isNew ? null : d.roles.find(r => r.key === key) || d.roles[0];
    const all = cur && cur.permissions === "*";
    const has = p => all || (cur && cur.permissions.includes(p));
    const locked = cur && !cur.editable;
    const off = p => locked || (!d.isAdmin && !mine.has(p));
    const label = g => (cat.global.find(x => x.key === g) || { label: g }).label;
    const box = (p, lbl) => `<input type="checkbox" data-perm="${esc(p)}" ${has(p) ? "checked" : ""} ${off(p) ? "disabled" : ""} aria-label="${esc(lbl)}">`;
    const matrix = `<div class="tw"><table class="perm-matrix"><caption class="sr-only">Permissões por tipo de documento</caption>
      <thead><tr><th scope="col"><span class="sr-only">Ação</span></th>${cat.types.map(t => `<th scope="col"><button type="button" class="linkish" data-col="${esc(t.key)}" aria-label="Marcar ou desmarcar a coluna ${esc(t.label)}" title="Marcar ou desmarcar a coluna">${esc(t.label)}</button></th>`).join("")}</tr></thead><tbody>
      ${cat.actions.map(a => `<tr><th scope="row"><button type="button" class="linkish" data-row="${esc(a.key)}" aria-label="Marcar ou desmarcar a linha ${esc(a.label)}">${esc(a.label)}</button><small>${esc(a.help)}</small></th>
        ${cat.types.map(t => t.perms.includes(`${t.key}.${a.key}`) ? `<td><label class="perm-cell">${box(`${t.key}.${a.key}`, `${a.label} · ${t.label}`)}</label></td>` : `<td class="na"><span aria-label="não se aplica">—</span></td>`).join("")}</tr>`).join("")}
      </tbody></table></div>`;
    const globals = GLOBAL_GROUPS.map(([h, keys]) => `<fieldset class="perm-grp ${keys.includes("app.reset") ? "crit" : ""}"><legend>${h}</legend>
      ${keys.filter(k => cat.global.some(g => g.key === k)).map(k => `<label class="chk-inline perm-g">${box(k, label(k))}<span>${esc(label(k))}${PERM_HINT[k] ? `<small>${esc(PERM_HINT[k])}</small>` : ""}</span></label>`).join("")}</fieldset>`).join("");
    const others = d.roles.filter(r => r.permissions !== "*");
    el.innerHTML = `<div class="roles-grid">
      <aside class="ecard role-list"><div class="ecard-h"><h2>Roles</h2><a class="btn ghost xs" href="#/admin/roles/novo" style="margin-left:auto"${isNew ? ` aria-current="page"` : ""}>${ic("plus")}Nova role</a></div>
        ${d.roles.map(r => { const on = cur && r.key === cur.key; return `<a class="role-item ${on ? "on" : ""}" href="#/admin/roles/${esc(r.key)}"${on ? ` aria-current="page"` : ""}><b>${esc(r.name)}</b>${r.system ? `<span class="tag">sistema</span>` : ""}
          <small>${esc(r.description || "")}</small><span class="role-users">${n(r.users, "usuário", "usuários")}</span></a>`; }).join("")}</aside>
      <form class="ecard role-edit" id="roleForm" autocomplete="off" novalidate>
        <div class="ecard-h"><h2>${isNew ? "Nova role" : esc(cur.name)}</h2>${cur && !isNew ? `<span class="muted small">${n(cur.users, "usuário usa", "usuários usam")} esta role</span>` : ""}</div>
        ${locked ? `<div class="notice">Tem <b>todas as permissões, inclusive as futuras</b>, e não pode ser alterada. Para uma role parecida com limites, use <b>Duplicar</b>.</div>` : ""}
        <div class="pp-row role-fields"><label>Nome<input class="in" name="name" maxlength="40" required value="${esc(isNew ? "" : cur.name)}" ${locked ? "disabled" : ""}></label>
          <label class="prio">Prioridade<input class="in" type="number" name="priority" min="1" max="99" value="${isNew ? 20 : cur.priority}" ${locked ? "disabled" : ""} aria-describedby="prioHelp"></label></div>
        <p class="muted small" id="prioHelp">A prioridade só importa no SSO: quando a pessoa está em grupos de várias roles, vale a de maior prioridade.</p>
        <label>Descrição<input class="in" name="description" maxlength="200" value="${esc(isNew ? "" : cur.description)}" ${locked ? "disabled" : ""}></label>
        ${isNew ? `<label>Começar com as permissões de<select class="in" id="rlBase"><option value="">Nenhuma (marcar à mão)</option>${others.map(r => `<option value="${esc(r.key)}">${esc(r.name)}</option>`).join("")}</select></label>` : ""}
        ${locked ? `<details class="perm-locked"><summary>Ver a matriz de permissões</summary>` : ""}
        <h3 class="pp-lbl">Documentos</h3>${matrix}
        <h3 class="pp-lbl">Plataforma</h3><div class="perm-groups">${globals}</div>
        ${locked ? `</details>` : ""}
        <div class="err" id="rlErr" role="alert" hidden></div>
        <div class="create-actions role-actions">
          <span class="ap-dirty" id="rlDirty" hidden>Alterações não salvas</span>
          ${!isNew && cur.deletable ? `<button type="button" class="btn danger" id="rlDel">Excluir</button>` : ""}
          ${!isNew && cur.system && cur.editable ? `<button type="button" class="btn ghost" id="rlReset">Restaurar padrão</button>` : ""}
          ${!isNew ? `<button type="button" class="btn ghost" id="rlDup">Duplicar</button>` : `<a class="btn ghost" href="#/admin/roles">Cancelar</a>`}
          ${locked ? "" : `<button class="btn primary" type="submit">${isNew ? "Criar role" : "Salvar"}</button>`}</div></form></div>`;
    const form = $("#roleForm", el), err = $("#rlErr", el);
    const fail = x => {
      err.textContent = x.message; err.hidden = false;
      if (/nome/i.test(x.message) && !form.name.disabled) { form.name.setAttribute("aria-invalid", "true"); form.name.focus(); } else err.scrollIntoView({ block: "nearest" });
    };
    const boxes = sel => [...form.querySelectorAll(`input[data-perm]${sel}`)].filter(b => !b.disabled);
    const flip = list => { const on = !list.every(b => b.checked); list.forEach(b => b.checked = on); mark(); };
    const collect = () => [...form.querySelectorAll("input[data-perm]:checked")].map(b => b.dataset.perm);
    const state = () => JSON.stringify([form.name.value, form.description.value, form.priority.value, collect()]);
    const base = state(), changed = () => !locked && state() !== base;
    const mark = () => { $("#rlDirty", el).hidden = !changed(); };
    Unsaved.check = () => form.isConnected && changed();
    form.addEventListener("input", mark); form.addEventListener("change", mark);
    form.name.addEventListener("input", () => form.name.removeAttribute("aria-invalid"));
    form.querySelectorAll("[data-col]").forEach(b => b.onclick = () => flip(boxes(`[data-perm^="${b.dataset.col}."]`)));
    form.querySelectorAll("[data-row]").forEach(b => b.onclick = () => flip(boxes(`[data-perm$=".${b.dataset.row}"]`)));
    if ($("#rlBase", el)) $("#rlBase", el).onchange = e => {
      const src = d.roles.find(r => r.key === e.target.value);
      boxes("").forEach(b => { b.checked = !!src && (src.permissions === "*" || src.permissions.includes(b.dataset.perm)); }); mark();
    };
    form.onsubmit = async e => {
      e.preventDefault();
      if (!form.name.value.trim()) return fail({ message: "Informe o nome da role" });
      const perms = collect(), body = { name: form.name.value.trim(), description: form.description.value.trim(), priority: +form.priority.value, permissions: perms };
      /* role em uso: ganhar ou perder poder sobre pessoas, acesso ou a instalação pede confirmação */
      if (!isNew && cur.users) {
        const before = new Set(all ? CRITICAL : cur.permissions), now = new Set(perms);
        const gained = CRITICAL.filter(p => now.has(p) && !before.has(p)), lost = CRITICAL.filter(p => before.has(p) && !now.has(p));
        if ((gained.length || lost.length) && !(await ask(`Esta mudança vale para ${n(cur.users, "usuário", "usuários")} na próxima ação no sistema:\n${gained.map(p => `• passam a poder: ${label(p)}`).concat(lost.map(p => `• deixam de poder: ${label(p)}`)).join("\n")}`,
          { title: "Permissões críticas", ok: "Salvar mesmo assim", danger: true }))) return;
      }
      try {
        const r = isNew ? await api("POST", "api/roles", body) : await api("PUT", `api/roles/${encodeURIComponent(cur.key)}`, body);
        Unsaved.check = null; toast(isNew ? "Role criada" : `Role salva${cur.users ? ` · vale para ${n(cur.users, "usuário", "usuários")}` : ""}`);
        location.hash = `#/admin/roles/${r.role.key}`; if (!isNew) roles(el, r.role.key);
      } catch (x) { fail(x); }
    };
    if ($("#rlDup", el)) $("#rlDup", el).onclick = () => modal({ title: `Duplicar ${esc(cur.name)}`, html: `<form class="tform" id="dupForm">
        <label>Nome da nova role<input class="in" name="name" maxlength="40" required value="${esc(`${cur.name} (cópia)`.slice(0, 40))}"></label>
        <p class="muted small">Começa com as mesmas permissões${all ? " que você pode conceder" : ""}; ajuste depois de criar.</p>
        <div class="err" id="dupErr" role="alert" hidden></div>
        <div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" type="submit">Duplicar</button></div></form>`,
      onMount: (b, close) => {
        const f = $("#dupForm", b); f.querySelector("[data-cancel]").onclick = close; f.name.select();
        f.onsubmit = async e => {
          e.preventDefault();
          try { const r = await api("POST", "api/roles", { name: f.name.value.trim(), description: cur.description, priority: Math.min(99, cur.priority), from: cur.key }); close(); Unsaved.check = null; toast("Role duplicada"); location.hash = `#/admin/roles/${r.role.key}`; }
          catch (x) { $("#dupErr", b).textContent = x.message; $("#dupErr", b).hidden = false; }
        };
      } });
    if ($("#rlReset", el)) $("#rlReset", el).onclick = async () => {
      if (!(await ask(`Voltar a role ${cur.name} às permissões padrão? As permissões personalizadas dela se perdem${cur.users ? ` e a mudança vale para ${n(cur.users, "usuário", "usuários")}` : ""}.`, { title: "Restaurar padrão", ok: "Restaurar", danger: true }))) return;
      try { await api("PUT", `api/roles/${cur.key}`, { reset: true }); Unsaved.check = null; toast("Permissões padrão restauradas"); roles(el, cur.key); } catch (x) { fail(x); }
    };
    if ($("#rlDel", el)) $("#rlDel", el).onclick = () => {
      const others = d.roles.filter(r => r.key !== cur.key && r.key !== "admin");
      modal({ title: `Excluir a role ${esc(cur.name)}`, html: `<form class="tform" id="rdForm">
          ${cur.users ? `<p>${cur.users} usuário${cur.users === 1 ? " usa" : "s usam"} esta role. Para onde ${cur.users === 1 ? "ele vai" : "eles vão"}?</p>
            <label>Nova role<select class="in" name="reassign">${others.map(r => `<option value="${esc(r.key)}" ${r.key === "viewer" ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select></label>`
            : `<p>Nenhum usuário usa esta role.</p>`}
          <div class="err" id="rdErr" role="alert" hidden></div>
          <div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn danger" type="submit">Excluir role</button></div></form>`,
        onMount: (b, close) => {
          const f = $("#rdForm", b);
          f.querySelector("[data-cancel]").onclick = close;
          f.onsubmit = async e => {
            e.preventDefault();
            try { await api("DELETE", `api/roles/${cur.key}`, cur.users ? { reassign: f.reassign.value } : {}); close(); Unsaved.check = null; toast("Role excluída"); location.hash = "#/admin/roles"; }
            catch (x) { $("#rdErr", b).textContent = x.message; $("#rdErr", b).hidden = false; }
          };
        } });
    };
  }

  /* ── reset da aplicação (só administrador), com a mesma confirmação da exclusão de playbook ── */
  async function resetDialog() {
    if (Editor.dirty || Editor.hasDraft()) return toast("Salve ou descarte as alterações dos editores antes", "warn");
    let s;
    try { s = await api("GET", "api/admin/summary"); } catch (e) { return toast(e.message, "err"); }
    const sso = App.user.auth === "sso", n = (v, one, many) => `${v} ${v === 1 ? one : many}`;
    modal({
      title: "Resetar aplicação", html: `<form id="rsForm" class="tform">
        <div class="notice danger">A aplicação volta ao estado de recém-instalada para <b>todos os usuários</b>: saem
          <b>${n(s.playbooks, "playbook", "playbooks")}</b>, <b>${n((s.documents || {}).runbook || 0, "runbook", "runbooks")}</b>,
          <b>${n((s.documents || {}).doc || 0, "documento", "documentos")}</b>, <b>${n(s.templates, "template", "templates")}</b> (o template Padrão é recriado)
          e <b>${n(s.versions, "versão", "versões")}</b> do histórico.<br>Nada é apagado de vez: o conteúdo e uma cópia do banco vão para a lixeira do
          servidor (<code>data/lixeira/reset__…</code>) e podem ser restaurados por quem administra o servidor.</div>
        <div class="pp-lbl">Também voltar ao padrão</div>
        <label class="opt-row ${sso ? "off" : ""}"><input type="checkbox" name="settings" ${sso ? "disabled" : "checked"}><span><b>Configurações</b>
          <small>${sso ? "Indisponível: sua conta entra pelo SSO, que seria desligado." : "Aparência (nome, contato e logo), governança, logs e SSO."}</small></span></label>
        <label class="opt-row"><input type="checkbox" name="users"><span><b>Usuários</b><small>Exclui ${n(Math.max(0, s.users - 1), "outro usuário", "outros usuários")}; fica só a sua conta.</small></span></label>
        <label class="opt-row"><input type="checkbox" name="audit"><span><b>Auditoria</b><small>Apaga ${n(s.audit, "evento", "eventos")} e os arquivos de log. O próprio reset fica registrado.</small></span></label>
        <label>Para confirmar, digite <b>${esc(s.word)}</b><input class="in" name="confirm" autocomplete="off" spellcheck="false"></label>
        <div class="err" id="rserr" hidden></div>
        <div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn danger" type="submit" disabled>Resetar aplicação</button></div></form>`,
      onMount: (bx, close) => {
        const form = $("#rsForm", bx), btn = form.querySelector("[type=submit]");
        form.confirm.oninput = () => { btn.disabled = form.confirm.value.trim().toUpperCase() !== s.word; };
        form.querySelector("[data-cancel]").onclick = close;
        form.onsubmit = async e => {
          e.preventDefault();
          btn.disabled = true; btn.textContent = "Resetando…";
          try {
            const r = await api("POST", "api/admin/reset", { confirm: form.confirm.value.trim().toUpperCase(),
              settings: form.settings.checked, users: form.users.checked, audit: form.audit.checked });
            close(); toast(`Aplicação resetada · cópia em data/lixeira/${r.archive}`);
            setTimeout(() => { location.hash = "#/"; location.reload(); }, 900);
          } catch (x) { $("#rserr", bx).textContent = x.message; $("#rserr", bx).hidden = false; btn.disabled = false; btn.textContent = "Resetar aplicação"; }
        };
      }
    });
  }

  /* ── logs: encaminhamento em JSON e retenção. Reduzir a retenção ou desligar um destino pede confirmação, com o que
     será apagado agora; destinos desligados escondem os campos. ── */
  async function logs(el) {
    let d;
    try { d = await api("GET", "api/logs"); } catch (e) { el.innerHTML = `<div class="err" role="alert">${esc(e.message)}</div>`; return; }
    const c = d.config, st = d.status.destinations, n = (v, one, many) => `${v} ${v === 1 ? one : many}`;
    const stat = k => { const x = st[k]; return `<div class="fwd-st"><span>Enviados <b>${x.sent}</b></span><span class="${x.failed ? "bad" : ""}">Falhas <b>${x.failed}</b></span>
      ${x.last_ok ? `<span>Último envio ${esc(fmtTs(x.last_ok))}</span>` : ""}${x.last_error ? `<span class="bad" title="${esc(x.last_error)}">Último erro: ${esc(x.last_error.split(" · ").slice(1).join(" · ").slice(0, 90))}</span>` : ""}</div>`; };
    const dest = (k, label, body) => `<fieldset class="fwd ${c[k].enabled ? "" : "off"}"><legend><label class="switch"><input type="checkbox" name="${k}.enabled" ${c[k].enabled ? "checked" : ""} aria-controls="fwd-${k}"><span>${label}</span></label></legend>
        <div class="fwd-body" id="fwd-${k}" ${c[k].enabled ? "" : "hidden"}>${body}
          <div class="row-btns"><button type="button" class="btn ghost xs" data-test="${k}">${k === "file" ? "Gravar" : "Enviar"} evento de teste</button></div>${stat(k)}</div></fieldset>`;
    el.innerHTML = `<form id="lgForm" class="admin-grid logs-grid" novalidate>
      <section class="ecard"><div class="ecard-h"><h2>Retenção</h2></div>
        <label>Guardar a auditoria por<div class="inline-in"><input class="in" type="number" name="retention_days" min="1" max="3650" value="${c.retention_days}" aria-describedby="lgRetHelp"> dias</div></label>
        <p class="muted small" id="lgRetHelp">Eventos e arquivos de log mais antigos são apagados automaticamente (verificação a cada 6 horas e ao salvar). Padrão: 30 dias. O histórico de versões dos documentos não é afetado.</p>
        <div class="pp-lbl">Exportar</div>
        <div class="row-btns"><a class="btn ghost sm" href="api/audit/export?days=${c.retention_days}" download>${ic("download")}Baixar auditoria (JSON Lines)</a></div>
        <details class="json-det"><summary>Formato de cada evento</summary>
          <pre class="json-sample">${esc(JSON.stringify(d.sample, null, 2))}</pre>
          <p class="muted small">Campos no padrão Elastic Common Schema (ECS): funciona direto em Elastic, OpenSearch, Splunk, Sentinel, Graylog e Wazuh.</p></details></section>
      <section class="ecard"><div class="ecard-h"><h2>Encaminhamento</h2><span class="muted small">fila na memória: ${d.status.queue}${d.status.dropped ? ` · descartados ${d.status.dropped}` : ""}</span></div>
        ${dest("http", "HTTP / HTTPS (SIEM, coletor, webhook)", `
          <label>URL<input class="in" name="http.url" value="${esc(c.http.url)}" placeholder="https://siem.empresa.com/api/ingest" inputmode="url" spellcheck="false"></label>
          <div class="auth-row"><label>Cabeçalho de autenticação<input class="in" name="http.auth_header" value="${esc(c.http.auth_header)}" placeholder="Authorization" spellcheck="false"></label>
            <label>Valor<input class="in" name="http.auth_value" type="password" autocomplete="new-password" placeholder="${c.http.auth_value_set ? "•••••••• (definido; preencha para trocar)" : "ex.: Bearer token, ApiKey …"}"></label></div>
          ${c.http.auth_value_set ? `<label class="chk-inline"><input type="checkbox" name="http.clear_auth"> remover o valor salvo</label>` : ""}
          <p class="muted small">POST com um array JSON por lote (até 200 eventos). Até 3 tentativas por lote.</p>`)}
        ${dest("syslog", "Syslog (RFC 5424, mensagem em JSON)", `
          <div class="sys-row"><label class="sys-host">Host<input class="in" name="syslog.host" value="${esc(c.syslog.host)}" placeholder="syslog.empresa.com" spellcheck="false"></label>
            <label>Porta<input class="in" type="number" name="syslog.port" min="1" max="65535" value="${c.syslog.port}"></label>
            <label>Protocolo<select class="in" name="syslog.proto"><option value="udp" ${c.syslog.proto !== "tcp" ? "selected" : ""}>UDP</option><option value="tcp" ${c.syslog.proto === "tcp" ? "selected" : ""}>TCP</option></select></label>
            <label>Facility<select class="in" name="syslog.facility">${[16, 17, 18, 19, 20, 21, 22, 23, 13, 4, 10].map(f => `<option value="${f}" ${+c.syslog.facility === f ? "selected" : ""}>${f >= 16 ? "local" + (f - 16) : f === 13 ? "log audit" : f === 4 ? "auth" : "authpriv"}</option>`).join("")}</select></label></div>`)}
        ${dest("file", "Arquivo JSON Lines (para Filebeat, Fluent Bit, agentes)", `
          <p class="muted small">Um arquivo por dia em <code>${esc(d.logDir)}/audit-AAAA-MM-DD.jsonl</code>, apagado conforme a retenção.</p>`)}
        <div class="err" id="lgErr" role="alert" hidden></div>
        <div class="create-actions"><span class="ap-dirty" id="lgDirty" hidden>Alterações não salvas</span><button class="btn primary" type="submit">Salvar configuração de logs</button></div></section></form>`;
    const form = $("#lgForm", el), err = $("#lgErr", el);
    const collect = () => {
      const o = { http: {}, syslog: {}, file: {} };
      form.querySelectorAll("[name]").forEach(i => {
        const v = i.type === "checkbox" ? i.checked : i.value; const [a, b] = i.name.split(".");
        if (b) o[a][b] = v; else o[a] = v;
      });
      return o;
    };
    const base = JSON.stringify(collect());
    const changed = () => JSON.stringify(collect()) !== base;
    Unsaved.check = () => form.isConnected && changed();
    form.addEventListener("input", () => { $("#lgDirty", el).hidden = !changed(); });
    form.querySelectorAll("[name$='.enabled']").forEach(cb => cb.addEventListener("change", () => { const b = $(`#fwd-${cb.name.split(".")[0]}`, el); b.hidden = !cb.checked; b.closest("fieldset").classList.toggle("off", !cb.checked); }));
    /* erro do servidor: a mensagem fica perto do Salvar e o campo culpado é marcado e recebe o foco */
    const FIELD = [[/URL/i, "http.url"], [/cabeçalho/i, "http.auth_header"], [/porta/i, "syslog.port"], [/host/i, "syslog.host"], [/reten/i, "retention_days"]];
    const fail = x => {
      err.textContent = x.message; err.hidden = false;
      form.querySelectorAll("[aria-invalid]").forEach(i => { i.removeAttribute("aria-invalid"); i.removeAttribute("aria-errormessage"); });
      const hit = FIELD.find(([re]) => re.test(x.message)), i = hit && form.elements[hit[1]];
      if (i && i.offsetParent) { i.setAttribute("aria-invalid", "true"); i.setAttribute("aria-errormessage", "lgErr"); i.focus(); } else err.scrollIntoView({ block: "nearest" });
    };
    form.onsubmit = async e => {
      e.preventDefault();
      const o = collect(), days = Math.round(+o.retention_days), lost = [];
      let erases = false;
      if (days >= 1 && days < c.retention_days) {
        let p; try { p = await api("GET", `api/logs/retention-preview?days=${days}`); } catch (x) { return fail(x); }
        if (p.events || p.files) {
          erases = true;
          lost.push(`a retenção cai de ${c.retention_days} para ${days} dias e ${n(p.events, "evento", "eventos")} de auditoria${p.files ? ` e ${n(p.files, "arquivo", "arquivos")} de log` : ""} ${p.events + p.files === 1 ? "é apagado" : "são apagados"} agora;`);
        }
      }
      [["http", "HTTP"], ["syslog", "Syslog"], ["file", "Arquivo JSON Lines"]].forEach(([k, l]) => { if (c[k].enabled && !o[k].enabled) lost.push(`o envio para ${l} é desligado;`); });
      if (lost.length && !(await ask(`Ao salvar:\n${lost.map(x => "• " + x).join("\n")}${erases ? "\n\nO que for apagado não volta. Se precisar desses eventos, baixe a auditoria antes." : ""}`,
        { title: "Confirmar configuração de logs", ok: erases ? "Apagar e salvar" : "Salvar", danger: erases }))) return;
      try { await api("PUT", "api/logs", o); Unsaved.check = null; toast("Configuração de logs salva"); logs(el); }
      catch (x) { fail(x); }
    };
    form.querySelectorAll("[data-test]").forEach(b => b.onclick = async () => {
      const label = b.textContent;
      b.disabled = true; b.textContent = "Enviando…";
      try { const r = await api("POST", "api/logs/test", { dest: b.dataset.test, config: collect() }); toast(r.ok ? r.message : `Falhou: ${r.message}`, r.ok ? "ok" : "err"); }
      catch (x) { toast(x.message, "err"); }
      b.disabled = false; b.textContent = label;
    });
  }

  /* ── SSO (OpenID Connect). Os campos seguem a ordem do cadastro no provedor; ligar o SSO fica no fim, junto do
     Salvar, e salvar com ele ligado (ou restringindo o login por senha) mostra antes quem entra e como. ── */
  async function ssoAdmin(el) {
    let d;
    try { d = await api("GET", "api/sso/config"); } catch (e) { el.innerHTML = `<div class="err" role="alert">${esc(e.message)}</div>`; return; }
    const c = d.config, roleName = k => (d.roles.find(r => r.key === k) || { name: k }).name;
    const ph = k => k === "admin" ? "sec-admins" : k === "editor" ? "csirt, soc-n2" : k === "viewer" ? "soc-n1" : "grupo-do-provedor";
    el.innerHTML = `<form id="ssoForm" class="admin-grid sso-grid" novalidate>
      <section class="ecard"><div class="ecard-h"><h2>Provedor (OpenID Connect)</h2><span class="tag ${c.enabled ? "ok" : ""}">${c.enabled ? "SSO ligado" : "SSO desligado"}</span></div>
        <p class="muted small" style="margin-top:0">Opcional. Funciona com Microsoft Entra ID, Okta, Keycloak, Google, Auth0, Authentik, ADFS e outros provedores OIDC.</p>
        <details class="sso-tech"><summary>Detalhes técnicos</summary><p class="muted small">Fluxo authorization code + PKCE; o token é validado pela assinatura (RS256), emissor, audiência, validade e nonce.</p></details>
        <label>Emissor (issuer)<div class="inline-in"><input class="in" name="issuer" value="${esc(c.issuer)}" placeholder="https://login.microsoftonline.com/&lt;tenant&gt;/v2.0" spellcheck="false"><button type="button" class="btn ghost sm" id="ssoTest">Verificar emissor</button></div></label>
        <div id="ssoDisc" role="status" aria-live="polite"></div>
        <div class="pp-row"><label>Client ID<input class="in" name="client_id" value="${esc(c.client_id)}" spellcheck="false"></label>
          <label>Client secret<input class="in" name="client_secret" type="password" autocomplete="new-password" placeholder="${c.client_secret_set ? "•••••••• (definido; preencha para trocar)" : "segredo do aplicativo"}"></label></div>
        ${c.client_secret_set ? `<label class="chk-inline"><input type="checkbox" name="clear_secret"> remover o client secret salvo</label>` : ""}
        <label>URL pública da aplicação<input class="in" name="public_url" value="${esc(c.public_url)}" placeholder="https://playbooks.empresa.com" spellcheck="false"></label>
        <div class="notice small">Cadastre no provedor esta <b>URL de redirecionamento</b>: <code id="ssoRedir">${esc(d.redirectUri || "(informe a URL pública)")}</code></div>
        <div class="pp-row"><label>Escopos<input class="in" name="scopes" value="${esc(c.scopes)}" spellcheck="false"></label>
          <label>Texto do botão no login<input class="in" name="label" value="${esc(c.label)}" maxlength="60"></label></div></section>
      <section class="ecard"><div class="ecard-h"><h2>Quem entra e com qual role</h2></div>
        <div class="pp-row sso-claims"><label>Claim do login<input class="in" name="login_claim" value="${esc(c.login_claim)}" placeholder="preferred_username" spellcheck="false"></label>
          <label>Claim do nome<input class="in" name="name_claim" value="${esc(c.name_claim)}" spellcheck="false"></label>
          <label>Claim do e-mail<input class="in" name="email_claim" value="${esc(c.email_claim)}" spellcheck="false"></label></div>
        <label>Domínios de e-mail permitidos<input class="in" name="allowed_domains" value="${esc(c.allowed_domains)}" placeholder="empresa.com, empresa.com.br" aria-describedby="ssoDomHelp" spellcheck="false"></label>
        <p class="muted small" id="ssoDomHelp">Separados por vírgula; em branco, qualquer domínio.</p>
        <label>Claim de grupos ou roles<input class="in" name="role_claim" value="${esc(c.role_claim)}" placeholder="groups, roles ou realm_access.roles" spellcheck="false"></label>
        <h3 class="pp-lbl">Grupos do provedor → role</h3>
        <p class="muted small" style="margin-top:0">Grupos separados por vírgula. A cada login, vale a role de maior prioridade entre as que combinam.</p>
        ${d.roles.map(r => `<label>${esc(r.name)}<input class="in" name="role_map.${esc(r.key)}" value="${esc((c.role_map || {})[r.key] || "")}" placeholder="ex.: ${ph(r.key)}" spellcheck="false"></label>`).join("")}
        <div class="pp-row"><label>Sem grupo correspondente<select class="in" name="default_role">${d.roles.filter(r => r.key !== "admin").map(r => `<option value="${esc(r.key)}" ${c.default_role === r.key ? "selected" : ""}>Entra como ${esc(r.name)}</option>`).join("")}<option value="" ${!c.default_role ? "selected" : ""}>Acesso negado</option></select></label>
          <label>Usuário novo<select class="in" name="auto_create"><option value="1" ${c.auto_create ? "selected" : ""}>Criar no primeiro login</option><option value="" ${!c.auto_create ? "selected" : ""}>Só pré-cadastrados (Usuários → SSO)</option></select></label></div>
        <label>Login por senha<select class="in" name="local_login"><option value="all" ${c.local_login !== "admins" ? "selected" : ""}>Continua disponível para todos</option><option value="admins" ${c.local_login === "admins" ? "selected" : ""}>Só administradores (acesso de emergência)</option></select></label>
        <p class="muted small">Contas locais existentes não são vinculadas automaticamente a uma identidade do SSO: converta-as em <b>Usuários</b> (coluna de autenticação) com o mesmo login enviado pelo provedor.</p>
        <div class="err" id="ssoErr" role="alert" hidden></div>
        <div class="create-actions sso-actions"><label class="switch sso-on"><input type="checkbox" name="enabled" ${c.enabled ? "checked" : ""}><span id="ssoOnLbl">${c.enabled ? "SSO ligado" : "SSO desligado"}</span></label>
          <span class="ap-dirty" id="ssoDirty" hidden>Alterações não salvas</span><button class="btn primary" type="submit">Salvar SSO</button></div></section></form>`;
    const form = $("#ssoForm", el), err = $("#ssoErr", el);
    const collect = () => {
      const f = new FormData(form), o = { role_map: {} };
      for (const [k, v] of f.entries()) { if (k.startsWith("role_map.")) o.role_map[k.slice(9)] = v; else o[k] = v; }
      o.enabled = form.enabled.checked; o.auto_create = !!form.auto_create.value; o.clear_secret = !!(form.clear_secret && form.clear_secret.checked);
      return o;
    };
    const base = JSON.stringify(collect()), changed = () => JSON.stringify(collect()) !== base;
    Unsaved.check = () => form.isConnected && changed();
    const mark = () => { $("#ssoDirty", el).hidden = !changed(); $("#ssoOnLbl", el).textContent = form.enabled.checked ? "SSO ligado" : "SSO desligado"; };
    form.addEventListener("input", mark); form.addEventListener("change", mark);
    form.public_url.oninput = () => { $("#ssoRedir", el).textContent = form.public_url.value ? form.public_url.value.replace(/\/+$/, "") + "/api/sso/callback" : "(informe a URL pública)"; };
    $("#ssoTest", el).onclick = async () => {
      const box = $("#ssoDisc", el); box.innerHTML = `<div class="muted small">Consultando o emissor…</div>`;
      const r = await api("POST", "api/sso/test", { issuer: form.issuer.value }).catch(x => ({ ok: false, message: x.message }));
      box.innerHTML = r.ok ? `<div class="notice ok small">Emissor encontrado: <b>${esc(r.issuer)}</b><br>Autorização: ${esc(r.authorization_endpoint)}<br>Token: ${esc(r.token_endpoint)}${r.algs.length ? `<br>Assinaturas: ${esc(r.algs.join(", "))}${r.algs.includes("RS256") ? "" : " · atenção: é preciso RS256"}` : ""}<br><span class="muted">Isto verifica só o emissor; o login completo é testado entrando pelo botão de SSO numa janela anônima depois de salvar.</span></div>`
        : `<div class="err">${esc(r.message)}</div>`;
    };
    const FIELD = [[/emissor|issuer/i, "issuer"], [/client id/i, "client_id"], [/secret/i, "client_secret"], [/url pública/i, "public_url"], [/escopo/i, "scopes"], [/claim/i, "login_claim"]];
    const fail = x => {
      err.textContent = x.message; err.hidden = false;
      form.querySelectorAll("[aria-invalid]").forEach(i => i.removeAttribute("aria-invalid"));
      const hit = FIELD.find(([re]) => re.test(x.message)), i = hit && form.elements[hit[1]];
      if (i) { i.setAttribute("aria-invalid", "true"); i.setAttribute("aria-errormessage", "ssoErr"); i.focus(); } else err.scrollIntoView({ block: "nearest" });
    };
    form.onsubmit = async e => {
      e.preventDefault();
      const o = collect(), before = JSON.parse(base);
      /* ligar o SSO, mudar quem entra ou restringir a senha: resumo do efeito antes de salvar */
      const risky = o.enabled && (!before.enabled || o.local_login !== before.local_login || o.default_role !== before.default_role || o.auto_create !== before.auto_create);
      if (risky) {
        const me = App.user.auth === "sso" ? "Você entra pelo SSO: se a configuração estiver errada, use uma conta de administrador com senha local." : "Você (conta local) continua entrando por senha.";
        const lines = [`Botão "${o.label || "Entrar com SSO"}" no login, para contas do provedor.`,
          o.default_role ? `Quem não estiver em nenhum grupo mapeado entra como ${roleName(o.default_role)}.` : "Quem não estiver em nenhum grupo mapeado tem o acesso negado.",
          o.auto_create ? "Contas são criadas no primeiro login." : "Só entram contas pré-cadastradas em Usuários.",
          o.local_login === "admins" ? "Login por senha: só administradores (os demais com senha local deixam de entrar)." : "Login por senha continua para todos.", me];
        if (!(await ask(`Ao salvar:\n${lines.map(x => "• " + x).join("\n")}`, { title: before.enabled ? "Confirmar mudanças no SSO" : "Ligar o SSO", ok: before.enabled ? "Salvar" : "Ligar e salvar", danger: o.local_login === "admins" && before.local_login !== "admins" }))) return;
      } else if (before.enabled && !o.enabled && !(await ask("Desligar o SSO? O botão some do login e as contas do SSO deixam de entrar até ele ser ligado de novo.", { title: "Desligar o SSO", ok: "Desligar", danger: true }))) return;
      try { await api("PUT", "api/sso/config", o); Unsaved.check = null; toast("SSO salvo"); ssoAdmin(el); }
      catch (x) { fail(x); }
    };
  }

  /* sub-abas conforme as permissões da role */
  const SUBS = [
    ["usuarios", "Usuários", () => can("users.manage")], ["roles", "Roles", () => can("roles.manage")],
    ["governanca", "Governança", () => canAny("app.reset", "users.manage")], ["aparencia", "Aparência", () => can("branding.edit")],
    ["auditoria", "Auditoria", () => can("audit.view")], ["logs", "Logs e retenção", () => can("logs.manage")], ["sso", "SSO", () => can("sso.manage")]];
  function render(root, sub, key) {
    if (sub === "papeis") { location.replace("#/admin/roles" + (key ? "/" + key : "")); return; }   // endereço antigo (3.0)
    if (sub === "aparencia" && !can("branding.edit")) sub = "governanca";                             // a governança ficava na Aparência até a 3.x
    const subs = SUBS.filter(x => x[2]());
    if (!subs.length) return notFound();
    sub = subs.some(x => x[0] === sub) ? sub : subs[0][0];
    root.innerHTML = `<div class="pbbar"><div class="wrap"><div class="pbhead"><h1>Administração</h1></div>
      <nav class="tabs" aria-label="Seções da administração">${subs.map(([k, l]) => `<a href="#/admin/${k}" class="${sub === k ? "on" : ""}"${sub === k ? ` aria-current="page"` : ""}>${l}</a>`).join("")}</nav></div></div>
      <div class="wrap" id="adminview"><div class="empty">Carregando…</div></div>`;
    const on = $(".tabs a.on", root); if (on) on.scrollIntoView({ block: "nearest", inline: "nearest" });
    ({ usuarios: users, roles: el => roles(el, key), governanca: governanceTab, aparencia: appearance, auditoria: auditLog, logs, sso: ssoAdmin })[sub]($("#adminview"));
  }
  return { render };
})();

/* ───────── biblioteca (playbooks, runbooks e documentos) ─────────
   Nos tipos com pastas (runbooks e documentos), à esquerda, a árvore de pastas (role="tree": ↑ ↓ andam, ← → recolhem/expandem, Enter abre, F2 renomeia; o ⋯ ou o
   botão direito abrem as ações). À direita, busca, filtros gerados pelos campos do template (com contagens) e a lista.
   Documentos e pastas podem ser arrastados para outra pasta. Em telas estreitas a árvore vira um painel recolhível. */
const LibraryPage = (() => {
  const st = {};                                  // por tipo: { closed: Set(ids), limit, panel }; os filtros ficam no endereço
  const S = t => st[t] || (st[t] = { closed: new Set(), limit: 100 });

  function treeHtml(t, d, sel) {
    const kids = {}; d.folders.forEach(f => (kids[f.parentId ?? "root"] = kids[f.parentId ?? "root"] || []).push(f));
    const s = S(t);
    const node = (f, depth) => {
      const has = !!(kids[f.id] || []).length, open = !s.closed.has(f.id);     // pastas começam expandidas
      return `<li role="treeitem" aria-level="${depth + 1}" ${has ? `aria-expanded="${open}"` : ""} aria-selected="${String(sel) === String(f.id)}">
        <div class="tnode ${String(sel) === String(f.id) ? "on" : ""}" data-f="${f.id}" tabindex="-1" draggable="${d.canManage}" style="padding-left:${8 + depth * 14}px">
          <button class="tw" data-tw="${f.id}" tabindex="-1" aria-hidden="true" ${has ? "" : "style='visibility:hidden'"}>${ic(open ? "down" : "right")}</button>
          ${ic("folder")}<span class="tname">${esc(f.name)}</span><small>${f.total}</small>
          ${d.canManage ? `<button class="tmore" data-more="${f.id}" title="Ações da pasta" aria-label="Ações da pasta ${esc(f.name)}" tabindex="-1">${ic("more")}</button>` : ""}</div>
        ${has && open ? `<ul role="group">${kids[f.id].map(k => node(k, depth + 1)).join("")}</ul>` : ""}</li>`;
    };
    const all = d.folders.reduce((n, f) => n + f.count, 0) + d.unfiled;
    return `<ul class="tree" role="tree" aria-label="Pastas">
      <li role="treeitem" aria-level="1" aria-selected="${!sel}"><div class="tnode ${!sel ? "on" : ""}" data-f="" tabindex="0">${ic("grid")}<span class="tname">Todos</span><small>${all}</small></div></li>
      <li role="treeitem" aria-level="1" aria-selected="${sel === "none"}"><div class="tnode ${sel === "none" ? "on" : ""} drop-none" data-f="none" tabindex="-1">${ic("page")}<span class="tname">Sem pasta</span><small>${d.unfiled}</small></div></li>
      ${(kids.root || []).map(f => node(f, 0)).join("")}</ul>`;
  }

  function listHtml(t, items, mode, empty) {
    if (!items.length) return libEmpty(t, empty);
    return mode === "lg" ? libLarge(items, t) : mode === "sm" ? libSmall(items, t, typeInfo(t).plural) : libCards(items, t);
  }

  async function render(root, t, sel) {
    const s = S(t), ti = typeInfo(t), seq = ++routeSeq, folders = !!ti.folders;
    sel = folders ? sel || "" : "";
    /* filtros vêm do endereço: status (ou o padrão da role), texto e campos */
    const hq = hashQuery(), status = libStatus(t), q = (hq.get("q") || "").trim();
    const facet = {}; for (const [k, v] of hq) if (k.startsWith("fields.") && v) facet[k.slice(7)] = v;
    /* o status resolvido vai para o endereço, para que Voltar devolva exatamente a visão anterior */
    if (!hq.get("status")) setHashQuery({ ...Object.fromEntries(hq), status: status || "todos" }, false);
    const qs = new URLSearchParams({ type: t, limit: s.limit });
    if (status) qs.set("status", status);
    if (sel) { qs.set("folder", sel); if (sel !== "none") qs.set("recursive", "1"); }
    if (q) qs.set("q", q);
    for (const [k, v] of Object.entries(facet)) qs.set("fields." + k, v);
    let d, tree = null;
    try { [d, tree] = await Promise.all([api("GET", "api/library?" + qs), folders ? api("GET", `api/folders?type=${t}`) : null, refreshIndex()]); }
    catch (e) { if (seq === routeSeq && e.status !== 401) loadError(root, e); return; }
    if (seq !== routeSeq) return;
    renderSide(); Tabs.render();
    document.title = `${ti.plural} · ${$("#brandName").textContent}`;
    const mode = libView(), selName = !folders ? "" : sel === "none" ? "Sem pasta" : sel ? (tree.folders.find(f => String(f.id) === sel) || {}).name : "";
    const acts = [];
    if (can(`${t}.create`) && can(`${t}.import`)) acts.push({ icon: "upload", label: "Importar", hint: ".medusa.md ou .md vira um documento novo", run: () => importDialog(t) });
    if (can(`${t}.export`)) acts.push({ icon: "download", label: "Exportar tudo", hint: "Baixa um .zip com todos os documentos que você pode ver", href: "api/export" });
    const statuses = libStatuses(t);
    root.innerHTML = `<div class="wrap">
      <header class="page-head"><h1>${esc(ti.plural)}</h1><span class="count">${d.all}</span>
        <div class="home-actions">${acts.length ? `<button class="btn ghost sm" id="libActs" aria-haspopup="menu" aria-expanded="false">${ic("more")}Mais</button>` : ""}
          ${can(`${t}.create`) ? `<a class="btn primary sm" href="${newHref(t, sel)}">${ic("plus")}Novo ${esc(ti.label.toLowerCase())}</a>` : ""}</div></header>
      <div class="${folders ? "lib" : "lib lib-solo"}">
        ${folders ? `<details class="lib-side" ${!matchMedia("(max-width: 900px)").matches || (s.panel ?? false) ? "open" : ""}><summary>${ic("grid")}Pastas${selName ? `: ${esc(selName)}` : ""}</summary>
          <div class="lib-tree-h">${tree.canManage ? `<button class="btn ghost xs" id="fNew">${ic("plus")}Pasta</button><button class="btn ghost xs" id="fTpl" title="Cria as pastas sugeridas pelo template (o que já existe não é duplicado)">Pastas do template</button>` : ""}</div>
          <div id="libTree">${treeHtml(t, tree, sel)}</div></details>` : ""}
        <section class="lib-main">
          <div class="home-bar lib-bar">
            <div class="filters" role="group" aria-label="Filtrar por status">${["", ...statuses].map(v => {
              const n = v ? d.counts[v] || 0 : d.all, l = v ? statusLabel(t, v) : "Todos";
              return `<button class="${v === status ? "on" : ""}" data-ls="${esc(v || "todos")}" aria-pressed="${v === status}" aria-label="${esc(l)}, ${n}">${v ? `<i class="dot ${STATUS_CLS[v]}"></i>` : ""}${esc(l)} <span class="cnt" aria-hidden="true">${n}</span></button>`;
            }).join("")}</div>
            <input class="in sm" id="libQ" type="search" placeholder="Filtrar por nome ou ID" aria-label="Filtrar por nome ou ID" value="${esc(q)}">
            ${Object.entries(d.facets || {}).map(([k, f]) => `<select class="in sm" data-facet="${esc(k)}" aria-label="${esc(f.label)}"><option value="">${esc(f.label)}: todos</option>
              ${Object.entries(f.values).sort((a, b) => b[1] - a[1]).map(([v, n]) => `<option value="${esc(v)}" ${facet[k] === v ? "selected" : ""}>${esc(v)} (${n})</option>`).join("")}
              ${facet[k] && !(facet[k] in f.values) ? `<option value="${esc(facet[k])}" selected>${esc(facet[k])} (0)</option>` : ""}</select>`).join("")}
            <div class="view-seg" role="group" aria-label="Visualização da lista">${LIB_VIEWS.map(([k, n, svg]) => `<button class="${k === mode ? "on" : ""}" data-lv="${k}" title="${n}" aria-label="${n}" aria-pressed="${k === mode}">${svg}</button>`).join("")}</div></div>
          <div class="lib-list">${listHtml(t, d.items, mode, { status, filtered: !!(q || Object.keys(facet).length), folder: sel })}</div>
          ${d.nextCursor ? `<div class="home-more"><button class="btn ghost sm" id="libMore">Carregar mais <span class="muted">(${d.total - d.items.length})</span></button></div>` : ""}
        </section></div></div>`;
    /* refaz a lista com os filtros novos: a lista atual esmaece enquanto carrega e o foco volta ao mesmo controle */
    const refresh = focusSel => {
      const box = root.querySelector(".lib-list"); if (box) box.setAttribute("aria-busy", "true");
      return render(root, t, sel).then(() => {
        const el = focusSel && root.querySelector(focusSel); if (!el) return;
        el.focus(); if (el.id === "libQ") el.setSelectionRange(el.value.length, el.value.length);
      });
    };
    const params = over => ({ status: hashQuery().get("status") || "", q: (hashQuery().get("q") || ""), ...Object.fromEntries(Object.entries(facet).map(([k, v]) => ["fields." + k, v])), ...over });
    const go = f => { const qs = location.hash.split("?")[1]; location.hash = `#/${TYPE_ROUTE[t]}${f ? "/p/" + f : ""}${qs ? "?" + qs : ""}`; };
    if (folders) root.querySelector(".lib-side").ontoggle = e => { s.panel = e.target.open; };      // painel recolhível (telas estreitas) lembra o estado
    root.querySelector(".filters").onclick = e => {
      const b = e.target.closest("[data-ls]"); if (!b) return;
      try { localStorage.setItem(statusKey(t), b.dataset.ls); } catch { }
      s.limit = 100; setHashQuery(params({ status: b.dataset.ls }), true); refresh(`[data-ls="${b.dataset.ls}"]`);
    };
    let qt = 0;
    $("#libQ").oninput = e => { clearTimeout(qt); qt = setTimeout(() => { s.limit = 100; setHashQuery(params({ q: e.target.value.trim() }), false); refresh("#libQ"); }, 250); };
    root.querySelectorAll("[data-facet]").forEach(x => x.onchange = () => { s.limit = 100; setHashQuery(params({ ["fields." + x.dataset.facet]: x.value }), true); refresh(`[data-facet="${x.dataset.facet}"]`); });
    root.querySelector(".view-seg").onclick = e => { const b = e.target.closest("[data-lv]"); if (!b) return; setLibView(b.dataset.lv); refresh(`[data-lv="${b.dataset.lv}"]`); };
    const clear = root.querySelector("[data-clear]");
    if (clear) clear.onclick = () => { try { localStorage.setItem(statusKey(t), "todos"); } catch { } s.limit = 100; setHashQuery({ status: "todos" }, true); refresh('[data-ls="todos"]'); };
    if ($("#libMore")) $("#libMore").onclick = () => { s.limit += 100; refresh("#libMore"); };
    if ($("#libActs")) $("#libActs").onclick = e => actionsMenu(e.currentTarget, acts);
    if (!folders) return;
    const reload = () => render(root, t, sel);
    if ($("#fNew")) $("#fNew").onclick = () => folderName(t, null, sel && sel !== "none" ? +sel : null, reload);
    if ($("#fTpl")) $("#fTpl").onclick = () => fromTemplate(t, reload);
    bindTree(root, t, tree, sel, go, reload);
  }

  function bindTree(root, t, tree, sel, go, reload) {
    const box = $("#libTree"), s = S(t);
    const nodes = () => [...box.querySelectorAll(".tnode")];
    box.onclick = e => {
      const tw = e.target.closest("[data-tw]"); if (tw) { e.preventDefault(); e.stopPropagation(); const id = +tw.dataset.tw; s.closed.has(id) ? s.closed.delete(id) : s.closed.add(id); return reload(); }
      const more = e.target.closest("[data-more]"); if (more) { e.preventDefault(); return folderMenu(t, tree, +more.dataset.more, more, reload, go); }
      const n = e.target.closest(".tnode"); if (n) go(n.dataset.f);
    };
    box.oncontextmenu = e => { const n = e.target.closest(".tnode[data-f]"); if (!n || !tree.canManage || !/^\d+$/.test(n.dataset.f)) return; e.preventDefault(); folderMenu(t, tree, +n.dataset.f, n, reload, go); };
    box.onkeydown = e => {
      const list = nodes(), i = list.indexOf(document.activeElement); if (i < 0) return;
      const cur = list[i], id = cur.dataset.f, f = tree.folders.find(x => String(x.id) === id);
      const focus = n => { if (!n) return; list.forEach(x => x.tabIndex = -1); n.tabIndex = 0; n.focus(); };
      if (e.key === "ArrowDown") { e.preventDefault(); focus(list[i + 1]); }
      else if (e.key === "ArrowUp") { e.preventDefault(); focus(list[i - 1]); }
      else if (e.key === "ArrowRight" && f && tree.folders.some(x => x.parentId === f.id)) { e.preventDefault(); if (s.closed.has(f.id)) { s.closed.delete(f.id); reload(); } else focus(list[i + 1]); }
      else if (e.key === "ArrowLeft" && f) { e.preventDefault(); if (!s.closed.has(f.id) && tree.folders.some(x => x.parentId === f.id)) { s.closed.delete(f.id); s.closed.add(f.id); reload(); } else focus(list.find(x => x.dataset.f === String(f.parentId))); }
      else if (e.key === "Enter") { e.preventDefault(); go(id); }
      else if (e.key === "F2" && f && tree.canManage) { e.preventDefault(); folderName(t, f, f.parentId, reload); }
    };
    /* arrastar: documento (cartão/linha) ou pasta para uma pasta, "Sem pasta" ou a raiz */
    root.querySelectorAll("[data-doc]").forEach(a => a.ondragstart = e => { e.dataTransfer.setData("text/medusa-doc", a.dataset.doc); e.dataTransfer.effectAllowed = "move"; });
    box.querySelectorAll(".tnode[draggable=true]").forEach(n => n.ondragstart = e => { e.dataTransfer.setData("text/medusa-folder", n.dataset.f); e.dataTransfer.effectAllowed = "move"; });
    box.querySelectorAll(".tnode").forEach(n => {
      if (n.dataset.f === "") return;
      n.ondragover = e => { e.preventDefault(); n.classList.add("over"); };
      n.ondragleave = () => n.classList.remove("over");
      n.ondrop = async e => {
        e.preventDefault(); n.classList.remove("over");
        const target = n.dataset.f === "none" ? null : +n.dataset.f;
        const doc = e.dataTransfer.getData("text/medusa-doc"), fol = e.dataTransfer.getData("text/medusa-folder");
        try {
          if (doc) { if (!can(`${t}.edit`)) return toast("Sua role não pode mover documentos", "warn"); await api("PUT", `api/doc/${doc}/folder`, { folder_id: target }); toast(`${doc} movido`); }
          else if (fol && fol !== n.dataset.f && tree.canManage) { await api("PUT", `api/folders/${fol}`, { parent_id: target }); toast("Pasta movida"); }
          else return;
          reload();
        } catch (x) { toast(x.message, "err"); }
      };
    });
  }

  function folderMenu(t, tree, id, anchor, reload, go) {
    const f = tree.folders.find(x => x.id === id); if (!f) return;
    document.querySelectorAll(".fmenu").forEach(m => m.remove());
    const r = anchor.getBoundingClientRect();
    const m = document.createElement("div");
    m.className = "dmenu fmenu"; m.style.cssText = `position:fixed;left:${Math.min(r.left, innerWidth - 220)}px;top:${r.bottom + 4}px;z-index:80`;
    m.innerHTML = `<button data-a="sub">${ic("plus")}Nova subpasta</button><button data-a="ren">${ic("edit")}Renomear</button><button data-a="mov">${ic("swap")}Mover para…</button><button data-a="del" class="danger">${ic("trash")}Excluir</button>`;
    document.body.append(m);
    const close = () => { m.remove(); document.removeEventListener("mousedown", out, true); };
    const out = e => { if (!m.contains(e.target)) close(); };
    setTimeout(() => document.addEventListener("mousedown", out, true), 0);
    m.onclick = e => {
      const a = (e.target.closest("[data-a]") || {}).dataset; if (!a || !a.a) return; close();
      if (a.a === "sub") { S(t).closed.delete(id); return folderName(t, null, id, reload); }
      if (a.a === "ren") return folderName(t, f, f.parentId, reload);
      if (a.a === "mov") return folderMove(t, tree, f, reload);
      if (a.a === "del") return folderDelete(t, tree, f, reload, go);
    };
  }
  function folderName(t, f, parent, done) {
    modal({ title: f ? "Renomear pasta" : "Nova pasta", html: `<form class="tform" id="fnForm"><label>Nome<input class="in" name="name" maxlength="60" required value="${esc(f ? f.name : "")}"></label>
        <div class="err" id="fnErr" hidden></div><div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" type="submit">${f ? "Renomear" : "Criar"}</button></div></form>`,
      onMount: (b, close) => {
        const form = $("#fnForm", b); form.querySelector("[data-cancel]").onclick = close; form.name.focus(); form.name.select();
        form.onsubmit = async e => {
          e.preventDefault();
          try { f ? await api("PUT", `api/folders/${f.id}`, { name: form.name.value }) : await api("POST", "api/folders", { type: t, name: form.name.value, parent_id: parent }); close(); done(); }
          catch (x) { $("#fnErr", b).textContent = x.message; $("#fnErr", b).hidden = false; }
        };
      } });
  }
  function folderMove(t, tree, f, done) {
    const bad = subtree(tree, f);
    modal({ title: `Mover a pasta ${esc(f.name)}`, html: `<form class="tform" id="fmForm"><label>Para dentro de<select class="in" name="to">${folderOptions(tree.folders.filter(x => !bad.has(x.id)), f.parentId, "Raiz (nenhuma pasta)")}</select></label>
        <div class="err" id="fmErr" hidden></div><div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" type="submit">Mover</button></div></form>`,
      onMount: (b, close) => {
        const form = $("#fmForm", b); form.querySelector("[data-cancel]").onclick = close;
        form.onsubmit = async e => { e.preventDefault(); try { await api("PUT", `api/folders/${f.id}`, { parent_id: form.to.value || null }); close(); done(); } catch (x) { $("#fmErr", b).textContent = x.message; $("#fmErr", b).hidden = false; } };
      } });
  }
  /* a pasta e tudo o que está dentro dela (não servem de destino para mover ou para receber o conteúdo) */
  function subtree(tree, f) {
    const out = new Set([f.id]); let grew = true;
    while (grew) { grew = false; tree.folders.forEach(x => { if (out.has(x.parentId) && !out.has(x.id)) { out.add(x.id); grew = true; } }); }
    return out;
  }
  function folderDelete(t, tree, f, done, go) {
    const busy = f.total || tree.folders.some(x => x.parentId === f.id), inside = subtree(tree, f);
    modal({ title: `Excluir a pasta ${esc(f.name)}`, html: `<form class="tform" id="fdForm">
        ${busy ? `<p>A pasta tem ${f.total} documento(s)${tree.folders.some(x => x.parentId === f.id) ? " e subpastas" : ""}. Para onde vai o conteúdo?</p>
          <label>Mover para<select class="in" name="to">${folderOptions(tree.folders.filter(x => !inside.has(x.id)), f.parentId, "Sem pasta / raiz")}</select></label>` : `<p>A pasta está vazia.</p>`}
        <p class="muted small">Os documentos não são apagados nem ganham versão nova: só mudam de pasta.</p>
        <div class="err" id="fdErr" hidden></div><div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn danger" type="submit">Excluir pasta</button></div></form>`,
      onMount: (b, close) => {
        const form = $("#fdForm", b); form.querySelector("[data-cancel]").onclick = close;
        form.onsubmit = async e => {
          e.preventDefault();
          try { await api("DELETE", `api/folders/${f.id}`, busy ? { moveTo: form.to.value ? +form.to.value : null } : {}); close(); toast("Pasta excluída"); go(""); done(); }
          catch (x) { $("#fdErr", b).textContent = x.message; $("#fdErr", b).hidden = false; }
        };
      } });
  }
  async function fromTemplate(t, done) {
    let ts; try { ts = (await api("GET", `api/templates?kind=${t}`)).templates.filter(x => !x.error && x.folders.length); } catch (e) { return toast(e.message, "err"); }
    if (!ts.length) return toast("Nenhum template deste tipo sugere pastas (aba Pastas do template)", "warn");
    modal({ title: "Criar estrutura de pastas do template", html: `<form class="tform" id="ftForm"><label>Template<select class="in" name="tpl">${ts.map(x => `<option value="${esc(x.key)}">${esc(x.name)} (${x.folders.length} pastas)</option>`).join("")}</select></label>
        <pre class="ft-prev" id="ftPrev"></pre><p class="muted small">Só cria o que falta; pastas existentes ficam como estão.</p>
        <div class="err" id="ftErr" hidden></div><div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" type="submit">Criar pastas</button></div></form>`,
      onMount: (b, close) => {
        const form = $("#ftForm", b), prev = () => { $("#ftPrev", b).textContent = ts.find(x => x.key === form.tpl.value).folders.join("\n"); };
        form.tpl.onchange = prev; prev(); form.querySelector("[data-cancel]").onclick = close;
        form.onsubmit = async e => { e.preventDefault(); try { const r = await api("POST", "api/folders/from-template", { type: t, template: form.tpl.value }); close(); toast(`${r.created} pasta(s) criada(s)`); done(); } catch (x) { $("#ftErr", b).textContent = x.message; $("#ftErr", b).hidden = false; } };
      } });
  }
  return { render };
})();

/* ───────── criação de runbook e documento: template do tipo, nome, ID sugerido, pasta e campos ───────── */
const DocCreate = (() => {
  const input = f => {
    const n = `f_${f.key}`, req = f.required ? "required" : "";
    if (f.type === "select") return `<select class="in" name="${n}" ${req}><option value="">—</option>${f.options.map(o => `<option>${esc(o)}</option>`).join("")}</select>`;
    if (f.type === "multiselect") return `<div class="chk-row">${f.options.map(o => `<label class="chk-inline"><input type="checkbox" name="${n}" value="${esc(o)}"> ${esc(o)}</label>`).join("")}</div>`;
    if (f.type === "date") return `<input class="in" type="date" name="${n}" ${req}>`;
    if (f.type === "url") return `<input class="in" type="url" name="${n}" placeholder="https://" ${req}>`;
    return `<input class="in" name="${n}" maxlength="300" ${req}>`;
  };
  async function render(root, t, folder) {
    const ti = typeInfo(t);
    root.innerHTML = `<div class="wrap"><div class="empty">Carregando…</div></div>`;
    let tpls, people, next, tree;
    try { [tpls, people, next, tree] = await Promise.all([api("GET", `api/templates?kind=${t}`), api("GET", "api/people"), api("GET", `api/doc/next-id?type=${t}`), api("GET", `api/folders?type=${t}`)]); }
    catch (e) { root.innerHTML = `<div class="wrap"><div class="err">${esc(e.message)}</div></div>`; return; }
    const list = tpls.templates.filter(x => !x.error), def = list.find(x => x.default) || list[0];
    if (!def) { root.innerHTML = `<div class="wrap"><div class="err">Nenhum template de ${esc(ti.label.toLowerCase())}. Crie um em Templates.</div></div>`; return; }
    const fieldsOf = key => (list.find(x => x.key === key) || def).fields;
    root.innerHTML = `<div class="wrap"><header class="page-head"><h1>Novo ${esc(ti.label.toLowerCase())}</h1></header>
      <form class="ecard tform create-doc" id="dcForm" autocomplete="off">
        <div class="pp-row"><label>Template<select class="in" name="template">${list.map(x => `<option value="${esc(x.key)}" ${x === def ? "selected" : ""}>${esc(x.name)}</option>`).join("")}</select></label>
          <label style="max-width:140px">ID<input class="in" name="id" value="${esc(next.id)}" pattern="${ti.prefix}-\\d{2,4}" required></label></div>
        <label>Nome<input class="in" name="name" maxlength="100" required placeholder="${t === "runbook" ? "ex.: Isolar host no EDR" : "ex.: Política de resposta a incidentes"}"></label>
        <div class="pp-row"><label>Autor<select class="in" name="author">${people.people.map(p => `<option value="${esc(p.login)}" ${p.login === App.user.login ? "selected" : ""}>${esc(p.name)}</option>`).join("")}</select></label>
          <label>Owner do documento<input class="in" name="owner" maxlength="80"></label></div>
        ${ti.folders ? `<label>Pasta<select class="in" name="folder">${folderOptions(tree.folders, folder ? +folder : null)}</select></label>` : ""}
        <div id="dcFields"></div>
        <div class="err" id="dcErr" hidden></div>
        <div class="create-actions"><a class="btn ghost" href="#/${TYPE_ROUTE[t]}">Cancelar</a><button class="btn primary" type="submit">Criar ${esc(ti.label.toLowerCase())}</button></div></form></div>`;
    const form = $("#dcForm");
    const paint = () => { const fs = fieldsOf(form.template.value); $("#dcFields").innerHTML = fs.length ? `<div class="pp-lbl">Campos</div>${fs.map(f => `<label>${esc(f.label)}${f.required ? " *" : ""}${input(f)}</label>`).join("")}` : ""; };
    form.template.onchange = paint; paint();
    form.onsubmit = async e => {
      e.preventDefault();
      const fields = {};
      for (const f of fieldsOf(form.template.value)) fields[f.key] = f.type === "multiselect" ? [...form.querySelectorAll(`[name="f_${f.key}"]:checked`)].map(x => x.value) : (form[`f_${f.key}`] || {}).value || "";
      try {
        const r = await api("POST", "api/doc", { type: t, template: form.template.value, id: form.id.value.trim().toUpperCase(), name: form.name.value.trim(),
          author: form.author.value, owner: form.owner.value, folder_id: form.folder && form.folder.value ? +form.folder.value : null, fields });
        await refreshIndex(); replacePlaybook(r.playbook); toast(`${r.playbook.id} criado em ${statusLabel(t, "Desenvolvimento")}`); location.hash = `#/${r.playbook.slug}/doc`;
      } catch (x) { $("#dcErr").textContent = x.message; $("#dcErr").hidden = false; }
    };
  }
  return { render };
})();

/* ───────── sugestões de alteração ─────────
   Quem pode sugerir seleciona um trecho da documentação (aparece "Sugerir alteração") ou usa o botão da seção para
   propor um acréscimo; dá para só comentar. Quem edita abre o painel de Sugestões e aceita (aplicando no documento,
   o que gera uma versão) ou recusa; quem sugeriu pode retirar. */
const Suggest = (() => {
  const fmt = t => t ? new Date(t).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "";
  const STATUS = { aberta: "aberta", aceita: "aceita", recusada: "recusada", retirada: "retirada" };
  let floatBtn = null;

  /* seção (e subseção) onde está o nó: âncora = slug da seção, como no servidor */
  function where(node) {
    const el = node && (node.nodeType === 3 ? node.parentElement : node);
    const sec = el && el.closest(".doc section.md");
    if (!sec || sec.classList.contains("cites")) return null;
    if (sec.classList.contains("intro")) return { anchor: "intro", title: "Introdução" };
    if (!/^sec-/.test(sec.id)) return null;
    let top = el; while (top && top.parentElement !== sec) top = top.parentElement;
    let h = top; while (h && !/^H[23]$/.test(h.tagName)) h = h.previousElementSibling;
    const h2 = sec.querySelector("h2"), own = x => ((x.firstChild && x.firstChild.nodeType === 3 ? x.firstChild.textContent : x.textContent) || "").trim();
    return { anchor: sec.id.slice(4), title: h && h.tagName === "H3" ? `${own(h2)} › ${own(h)}` : own(h2) };
  }
  function hideFloat() { if (floatBtn) { floatBtn.remove(); floatBtn = null; } }

  function dialog(pb, ctx, done) {
    hideFloat();
    const quote = ctx.quote || "";
    modal({ title: "Sugerir alteração", wide: true, html: `<form class="tform" id="sgForm">
        <div class="sg-where">${ic("page")}<span>${esc(ctx.title)}</span></div>
        ${quote ? `<div class="pp-lbl">Trecho selecionado</div><blockquote class="sg-quote">${esc(quote)}</blockquote>
          <div class="radio-row"><label><input type="radio" name="mode" value="replace" checked> Propor um texto no lugar do trecho</label>
            <label><input type="radio" name="mode" value="comment"> Só comentar</label></div>` : `<p class="muted small" style="margin-top:0">Sem trecho selecionado: o texto sugerido entra no fim desta seção (Markdown: listas, tabelas e código valem). Para trocar um trecho, selecione-o na documentação.</p>`}
        <label id="sgPropL">${quote ? "Texto sugerido" : "Texto a acrescentar"} <small>(opcional se houver comentário)</small><textarea class="in" name="proposal" rows="${quote ? 3 : 5}" maxlength="4000">${esc(quote)}</textarea></label>
        <label>Comentário <small>(por que mudar; aparece para quem edita)</small><textarea class="in" name="comment" rows="3" maxlength="2000"></textarea></label>
        <div class="err" id="sgErr" hidden></div>
        <div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" type="submit">${ic("send")}Enviar sugestão</button></div></form>`,
      onMount: (b, close) => {
        const f = $("#sgForm", b);
        f.querySelector("[data-cancel]").onclick = close;
        const sync = () => { const c = f.mode && f.mode.value === "comment"; $("#sgPropL", b).hidden = c; };
        f.addEventListener("change", sync); sync();
        (quote ? f.proposal : f.proposal).focus();
        f.onsubmit = async e => {
          e.preventDefault();
          const onlyComment = f.mode && f.mode.value === "comment";
          const proposal = onlyComment ? null : f.proposal.value;
          if (quote && proposal !== null && proposal.trim() === quote.trim() && !f.comment.value.trim()) { $("#sgErr", b).textContent = "Mude o texto ou escreva um comentário"; $("#sgErr", b).hidden = false; return; }
          try {
            await api("POST", `api/doc/${pb.id}/suggestions`, { anchor: ctx.anchor, anchor_title: ctx.title, quote, proposal: proposal && proposal.trim() ? proposal : null, comment: f.comment.value });
            close(); toast("Sugestão enviada para quem edita o documento"); done && done();
          } catch (x) { $("#sgErr", b).textContent = x.message; $("#sgErr", b).hidden = false; }
        };
      } });
  }

  function itemHtml(x, d) {
    const open = x.status === "aberta";
    const quote = x.quote ? `<del class="sg-del">${esc(x.quote)}</del>` : "";
    const prop = x.proposal ? `<ins class="sg-ins">${x.quote ? "" : "+ "}${esc(x.proposal)}</ins>` : "";
    return `<div class="sg-item ${open ? "" : "closed"}" data-id="${x.id}">
      <div class="sg-head"><b>${esc(x.author_name)}</b><span class="muted small">${esc(fmt(x.created_at))} · v${esc(x.base_version)} · ${esc(x.anchor_title || "Documento")}</span>
        ${open ? "" : `<span class="tag ${x.status}">${STATUS[x.status]}${x.applied ? " e aplicada" : ""}</span>`}</div>
      ${quote || prop ? `<div class="sg-diff">${quote}${prop}</div>` : ""}
      ${x.comment ? `<p class="sg-comment">${esc(x.comment)}</p>` : ""}
      ${!open && (x.resolved_name || x.resolution_note) ? `<p class="muted small">${esc(x.resolved_name || "")}${x.resolved_at ? ` em ${esc(fmt(x.resolved_at))}` : ""}${x.resolution_note ? `: ${esc(x.resolution_note)}` : ""}</p>` : ""}
      ${open ? `<div class="row-btns">${d.canResolve ? `${x.proposal ? `<button class="btn primary xs" data-sg="apply">${ic("check")}Aceitar e aplicar</button>` : ""}
          <button class="btn ghost xs" data-sg="accept">Marcar como aceita</button><button class="btn ghost xs" data-sg="reject">Recusar</button>` : ""}
        ${x.mine ? `<button class="btn ghost xs" data-sg="withdraw">Retirar</button>` : ""}</div>` : ""}</div>`;
  }

  async function panel(pb, anchor, all = false) {
    let d; try { d = await api("GET", `api/doc/${pb.id}/suggestions${all ? "?status=todas" : ""}`); } catch (e) { return toast(e.message, "err"); }
    const list = d.suggestions.filter(x => !anchor || x.anchor === anchor);
    const html = `<div class="sg-tabs"><button class="${all ? "" : "on"}" data-all="0">Abertas</button><button class="${all ? "on" : ""}" data-all="1">Todas</button>
        ${anchor ? `<button data-clear>Todas as seções</button>` : ""}</div>
      ${list.length ? list.map(x => itemHtml(x, d)).join("") : `<div class="empty">${all ? "Nenhuma sugestão." : "Nenhuma sugestão aberta."}</div>`}
      ${d.canSuggest ? `<p class="muted small">Para sugerir, selecione um trecho na aba Documentação ou use o ${ic("plus")} ao lado do título de uma seção.</p>` : ""}`;
    if (!drawer.hidden) stack.pop();
    pushView(`${ic("edit")} Sugestões · ${esc(pb.id)}`, html, pb, body => {
      body.querySelectorAll("[data-all]").forEach(b => b.onclick = () => panel(pb, anchor, b.dataset.all === "1"));
      const c = body.querySelector("[data-clear]"); if (c) c.onclick = () => panel(pb, null, all);
      body.querySelectorAll("[data-sg]").forEach(b => b.onclick = () => act(pb, +b.closest(".sg-item").dataset.id, b.dataset.sg, () => panel(pb, anchor, all)));
    });
  }

  function noteDialog(title, label, okText, danger) {
    return new Promise(resolve => modal({ title, html: `<form class="tform" id="snForm"><label>${label}<textarea class="in" name="note" rows="3" maxlength="500"></textarea></label>
        <div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn ${danger ? "danger" : "primary"}" type="submit">${okText}</button></div></form>`,
      onClose: () => resolve(null),
      onMount: (b, close) => { const f = $("#snForm", b); f.note.focus(); f.querySelector("[data-cancel]").onclick = () => { resolve(null); close(); };
        f.onsubmit = e => { e.preventDefault(); resolve(f.note.value); close(); }; } }));
  }

  async function act(pb, id, what, done) {
    try {
      if (what === "withdraw") {
        if (!(await ask("Retirar esta sugestão?", { title: "Retirar sugestão", ok: "Retirar" }))) return;
        await api("POST", `api/doc/${pb.id}/suggestions/${id}/withdraw`, {}); toast("Sugestão retirada");
      } else if (what === "reject") {
        const note = await noteDialog("Recusar sugestão", "Motivo <small>(opcional; quem sugeriu vê)</small>", "Recusar", true); if (note === null) return;
        await api("POST", `api/doc/${pb.id}/suggestions/${id}/reject`, { note }); toast("Sugestão recusada");
      } else if (what === "accept") {
        const note = await noteDialog("Marcar como aceita", "Observação <small>(opcional; ex.: aplicado à mão no passo A3)</small>", "Marcar como aceita"); if (note === null) return;
        await api("POST", `api/doc/${pb.id}/suggestions/${id}/accept`, { note }); toast("Sugestão marcada como aceita");
      } else if (what === "apply") {
        const cur = DETAIL.get(pb.id) || pb;
        if (Editor.dirty || Editor.hasDraft(cur.id.toLowerCase())) return toast("Salve ou descarte as alterações do editor deste documento antes de aplicar", "warn");
        const change = await Editor.askChange(cur, "a sugestão aceita"); if (change === false) return;
        const r = await api("POST", `api/doc/${pb.id}/suggestions/${id}/accept`, { apply: true, rev: cur.rev, change: change || undefined });
        replacePlaybook(r.playbook); toast(`Sugestão aplicada: versão ${r.version}`);
        if (location.hash.startsWith(`#/${pb.slug}`)) { const keep = stack.slice(); route(); stack = keep; }
      }
      await refreshIndex(); done();
    } catch (x) {
      if (x.status === 409 && what === "apply") toast(x.message, "warn"); else toast(x.message, "err");
    }
  }

  /* leitura: selecionar texto mostra o botão; o título de cada seção ganha "+" e a contagem de sugestões abertas */
  async function bindDoc(pb, el) {
    const T = pb.type || "playbook", doc = el.querySelector(".doc");
    if (!doc) return;
    const canSg = can(`${T}.suggest`);
    if (canSg) {
      doc.querySelectorAll("section.md:not(.cites)").forEach(sec => {
        const w = where(sec.firstElementChild || sec); if (!w) return;
        const h = sec.querySelector("h2") || sec.firstElementChild;
        if (h && h.tagName === "H2") h.insertAdjacentHTML("beforeend", `<button class="sg-add" title="Sugerir nesta seção" aria-label="Sugerir nesta seção">${ic("plus")}</button>`);
        else sec.insertAdjacentHTML("afterbegin", `<button class="sg-add sg-add-intro" title="Sugerir na introdução" aria-label="Sugerir na introdução">${ic("plus")}</button>`);
      });
      doc.addEventListener("click", e => { const b = e.target.closest(".sg-add"); if (!b) return; e.preventDefault(); const w = where(b); if (w) dialog(pb, w, () => decorate(pb, doc)); });
      const onSel = () => setTimeout(() => {
        const sel = getSelection(), text = sel ? sel.toString().trim() : "";
        if (!text || text.length < 3 || !sel.rangeCount || !doc.contains(sel.anchorNode) || !doc.contains(sel.focusNode)) return hideFloat();
        const a = where(sel.anchorNode), z = where(sel.focusNode);
        if (!a || !z || a.anchor !== z.anchor) return hideFloat();
        const r = sel.getRangeAt(0).getBoundingClientRect();
        hideFloat();
        floatBtn = document.createElement("button");
        floatBtn.className = "btn primary xs sg-float"; floatBtn.innerHTML = `${ic("edit")}Sugerir alteração`;
        floatBtn.style.cssText = `position:fixed;left:${Math.max(8, Math.min(innerWidth - 180, r.left + r.width / 2 - 80))}px;top:${Math.max(8, r.top - 38)}px;z-index:75`;
        floatBtn.onmousedown = e => e.preventDefault();
        floatBtn.onclick = () => dialog(pb, { ...a, quote: text.slice(0, 2000) }, () => decorate(pb, doc));
        document.body.append(floatBtn);
      }, 0);
      doc.addEventListener("mouseup", onSel);
      doc.addEventListener("keyup", e => { if (e.shiftKey) onSel(); });
    }
    decorate(pb, doc);
  }
  /* contagem de sugestões abertas ao lado do título de cada seção */
  async function decorate(pb, doc) {
    let d; try { d = await api("GET", `api/doc/${pb.id}/suggestions`); } catch { return; }
    if (!document.contains(doc)) return;
    doc.querySelectorAll(".sg-count").forEach(x => x.remove());
    const by = {}; d.suggestions.forEach(x => { by[x.anchor] = (by[x.anchor] || 0) + 1; });
    doc.querySelectorAll("section.md:not(.cites)").forEach(sec => {
      const w = where(sec.firstElementChild || sec); if (!w || !by[w.anchor]) return;
      const h = sec.querySelector("h2");
      const chip = `<button class="sg-count" data-anchor="${esc(w.anchor)}" title="Sugestões abertas nesta seção">${by[w.anchor]} sugest${by[w.anchor] > 1 ? "ões" : "ão"}</button>`;
      if (h) h.insertAdjacentHTML("beforeend", chip); else sec.insertAdjacentHTML("afterbegin", chip);
    });
    doc.querySelectorAll(".sg-count").forEach(b => b.onclick = e => { e.preventDefault(); panel(pb, b.dataset.anchor); });
    const btn = $("#sgBtn"); if (btn) { const n = d.suggestions.length; btn.querySelector(".sg-n").textContent = n ? ` ${n}` : ""; }
  }
  document.addEventListener("mousedown", e => { if (floatBtn && !e.target.closest(".sg-float")) hideFloat(); });
  window.addEventListener("hashchange", hideFloat);
  return { panel, bindDoc };
})();

/* ───────── busca ───────── */
/* No servidor (/api/search: sem acento, título vale mais que passo/ramo, que vale mais que texto), com espera de
   150 ms entre teclas e cancelamento da busca anterior. Times vêm do cadastro já carregado. ↑ ↓ e Enter navegam. */
const KIND_NAMES = { documento: "Documento", passo: "Passo", ramo: "Ramo", secao: "Seção", time: "Time", pagina: "Página" };
let HITS = [], hitSel = 0, searchTimer = 0, searchCtl = null;
const q = $("#q"), results = $("#results");
async function doSearch() {
  const v = q.value.trim();
  if (v.length < 2) { showHits(false); HITS = []; return; }
  if (searchCtl) searchCtl.abort();
  searchCtl = new AbortController();
  let hits = [];
  try { hits = (await api("GET", `api/search?q=${encodeURIComponent(v)}&limit=30`, undefined, { signal: searchCtl.signal })).hits; }
  catch (e) { if (e.name === "AbortError") return; }
  const nv = norm(v).split(/\s+/);
  const teams = Object.keys(TEAMS).filter(t => { const x = norm(t + " " + (TEAMS[t].summary || "")); return nv.every(w => x.includes(w)); })
    .map(t => ({ kind: "time", title: t, team: t }));
  /* páginas da própria aplicação (Templates, seções da Administração, Ajuda…), conforme as permissões */
  const pages = PAGES().filter(([title, , words]) => { const x = norm(title + " " + (words || "")); return nv.every(w => x.includes(w)); })
    .map(([title, href]) => ({ kind: "pagina", title, href }));
  HITS = pages.concat(hits, teams).slice(0, 30); hitSel = 0;
  paintHits();
}
const PAGES = () => [
  ["Playbooks", "#/", "biblioteca inicio", true], ["Runbooks", "#/runbooks", "biblioteca procedimentos", can("runbook.view")],
  ["Documentos", "#/documentos", "biblioteca politicas normas", can("doc.view")], ["Novo playbook", "#/novo", "criar", can("playbook.create")],
  ["Templates", "#/templates", "modelos times tags", can("templates.view")],
  ["Administração · Usuários", "#/admin/usuarios", "contas senha", can("users.manage")], ["Administração · Roles", "#/admin/roles", "permissoes papeis", can("roles.manage")],
  ["Administração · Governança", "#/admin/governanca", "aprovador reset", canAny("app.reset", "users.manage")], ["Administração · Aparência", "#/admin/aparencia", "logo nome workspace marca", can("branding.edit")],
  ["Administração · Auditoria", "#/admin/auditoria", "eventos historico", can("audit.view")], ["Administração · Logs e retenção", "#/admin/logs", "siem syslog encaminhamento", can("logs.manage")],
  ["Administração · SSO", "#/admin/sso", "openid login provedor", can("sso.manage")], ["Ajuda", "#/ajuda", "documentacao manual", true]].filter(x => x[3]);
/* busca no padrão combobox: a lista é um listbox, ↑ ↓ mudam a opção ativa (aria-activedescendant) e o leitor de tela
   ouve quantos resultados vieram */
function showHits(v) { results.hidden = !v; q.setAttribute("aria-expanded", String(v)); if (!v) q.removeAttribute("aria-activedescendant"); }
function paintHits() {
  showHits(true);
  results.innerHTML = HITS.length ? HITS.map((h, i) => `<button data-i="${i}" id="hit-${i}" role="option" tabindex="-1" aria-selected="${i === hitSel}" class="${i === hitSel ? "on" : ""}"><small>${h.pid ? esc(h.pid) + " · " : ""}${h.kind === "documento" ? typeInfo(h.type).label : KIND_NAMES[h.kind] || ""}</small><br>${esc(h.title.length > 110 ? h.title.slice(0, 107) + "…" : h.title)}</button>`).join("")
    : `<div class="empty" role="presentation">Nada encontrado.</div>`;
  const on = results.querySelector("button.on"); if (on) { on.scrollIntoView({ block: "nearest" }); q.setAttribute("aria-activedescendant", on.id); } else q.removeAttribute("aria-activedescendant");
  $("#searchStatus").textContent = HITS.length ? `${HITS.length} resultado${HITS.length > 1 ? "s" : ""}` : "Nada encontrado";
}
/* "/" ou o ícone de busca do menu recolhido: abre o menu, se preciso, e foca a busca */
function openSearch() {
  if (!narrow.matches && document.body.classList.contains("side-collapsed")) setCollapsed(false);
  if (narrow.matches && !document.body.classList.contains("side-open")) sideOpen(true);
  setTimeout(() => q.focus(), narrow.matches ? 260 : 0);
}
function goHit(h) {
  showHits(false); q.value = ""; q.blur();
  if (h.kind === "pagina") { location.hash = h.href; return; }
  if (h.kind === "time") return showTeam(currentPb(), h.team, false);
  const slug = h.pid.toLowerCase();
  if (h.kind === "passo" || h.kind === "ramo") location.hash = `#/${slug}/doc/${encodeURIComponent(h.anchor)}`;
  else if (h.kind === "secao") {
    location.hash = `#/${slug}/doc`;
    const scroll = (n = 0) => { const el = document.getElementById(h.anchor); if (el) el.scrollIntoView(); else if (n < 30) setTimeout(() => scroll(n + 1), 60); };
    setTimeout(scroll, 60);
  } else location.hash = `#/${slug}/${h.type === "playbook" ? "fluxo" : "doc"}`;
}
q.addEventListener("input", () => { clearTimeout(searchTimer); searchTimer = setTimeout(doSearch, 150); });
q.addEventListener("keydown", e => {
  if (results.hidden || !HITS.length) return;
  if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); hitSel = (hitSel + (e.key === "ArrowDown" ? 1 : HITS.length - 1)) % HITS.length; paintHits(); }
  else if (e.key === "Enter") { e.preventDefault(); goHit(HITS[hitSel]); }
});
results.addEventListener("click", e => {
  const b = e.target.closest("button[data-i]"); if (b) goHit(HITS[+b.dataset.i]);
});
document.addEventListener("keydown", e => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
  if (e.key === "/" && !typing && App.user) { e.preventDefault(); openSearch(); }
  if (e.key === "Escape") { showHits(false); if (!drawer.hidden) closeDrawer(); if (document.activeElement === q) q.blur(); }
});
document.addEventListener("click", e => { if (!e.target.closest(".search")) showHits(false); });
/* menu recolhido: no lugar do campo, um ícone de busca */
$(".search").insertAdjacentHTML("beforeend", `<button type="button" class="search-rail" id="searchRail" title="Buscar ( / )" aria-label="Buscar">${ic("search")}</button>`);
$("#searchRail").onclick = openSearch;
/* "Pular para o conteúdo": primeiro item do Tab; leva o foco ao título da página sem mexer no endereço (#/…) */
$("#skipLink").onclick = e => { e.preventDefault(); const t = $("#tabview") || $("#view h1") || $("#view"); t.setAttribute("tabindex", "-1"); t.focus(); };

/* ───────── início ───────── */
/* ───────── times e tags ───────── */
/* Times e tags pertencem a um template: ctx = { tpl: chave do template }. done(nome, template) ao salvar. */
async function teamDialog(ctx, name, done, preset) {
  let tv;
  try { tv = (await api("GET", `api/templates/${encodeURIComponent(ctx.tpl)}`)).template; } catch (x) { return toast(x.message, "err"); }
  const own = tv.teamDefs || {};
  const t = name ? (own[name] || TEAMS[name]) : { color: "#5B6673", kind: "", summary: "", does: [], never: [], category: "apoio", ...(preset || {}) };
  if (!t) return toast("Time não encontrado", "err");
  modal({
    title: name ? `Editar ${esc(name)} · template ${esc(tv.name)}` : `Novo time ou tag · template ${esc(tv.name)}`, wide: true, html: `<form id="tmForm" class="tform">
      <div class="pp-row"><label>Nome${name ? " <small>(não editável)</small>" : ""}<input class="in" name="name" value="${esc(name || "")}" ${name ? "readonly" : "required"} maxlength="40" placeholder="ex.: Fraude, OT, Jurídico"></label>
        <label style="max-width:200px">Categoria<select class="in" name="category">
          <option value="central" ${t.category === "central" ? "selected" : ""}>Time central (pode ser raia)</option>
          <option value="apoio" ${t.category !== "central" ? "selected" : ""}>Apoio / tag</option></select></label>
        <label style="max-width:90px">Cor<input class="in" type="color" name="color" value="${esc(t.color)}" style="height:40px;padding:2px"></label></div>
      <label>Tipo / área<input class="in" name="kind" value="${esc(t.kind)}" placeholder="ex.: Apoio · Forense"></label>
      <label>Resumo da função<textarea class="in" name="summary" rows="3">${esc(t.summary)}</textarea></label>
      <div class="pp-row"><label>Responsabilidades <small>(uma por linha)</small><textarea class="in" name="does" rows="5">${esc((t.does || []).join("\n"))}</textarea></label>
        <label>O que não faz <small>(uma por linha)</small><textarea class="in" name="never" rows="5">${esc((t.never || []).join("\n"))}</textarea></label></div>
      <p class="muted small">Vale para o template <b>${esc(tv.name)}</b> e para os playbooks criados com ele.</p>
      <div class="err" id="tmerr" hidden></div>
      <div class="create-actions">${name && own[name] ? `<button type="button" class="btn danger" data-del style="margin-right:auto">Tirar do template</button>` : ""}<button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" type="submit">Salvar</button></div></form>`,
    onMount: (b, close) => {
      const form = $("#tmForm", b), err = $("#tmerr", b);
      form.querySelector("[data-cancel]").onclick = close;
      let nm = name;
      const save = async (all, removing) => {
        try {
          const r = await api("PUT", `api/templates/${encodeURIComponent(tv.key)}/teams`, { teams: all, rev: tv.rev });
          setTeams(r.allTeams); close(); toast(removing ? "Time retirado do template" : "Time salvo no template");
          if (done && !removing) done(nm, r.template); else refreshData();
        } catch (x) { err.textContent = x.message; err.hidden = false; }
      };
      form.onsubmit = e => {
        e.preventDefault();
        const f = new FormData(form), lines = v => v.split("\n").map(x => x.trim()).filter(Boolean);
        nm = (name || f.get("name")).trim();
        if (!name && own[nm]) { err.textContent = "Este template já tem um time com esse nome"; err.hidden = false; return; }
        const all = JSON.parse(JSON.stringify(own));
        all[nm] = { ...(all[nm] || {}), color: f.get("color"), kind: f.get("kind"), summary: f.get("summary"), does: lines(f.get("does")), never: lines(f.get("never")), category: f.get("category") };
        save(all);
      };
      const del = form.querySelector("[data-del]");
      if (del) del.onclick = async () => {
        if (!(await ask(`Tirar "${name}" do template ${tv.name}? Só é possível se ele não estiver no fluxograma do template nem em playbooks dele.`, { title: "Tirar time", ok: "Tirar do template", danger: true }))) return;
        const all = JSON.parse(JSON.stringify(own)); delete all[name]; save(all, true);
      };
    }
  });
}

/* ───────── MITRE ATT&CK ───────── */
const MitrePicker = (() => {
  const tactics = () => (App.data.catalog.mitre || {}).tactics || [];
  /* lê um texto livre ("TA0001 Initial Access · OWASP…") e separa as táticas do complemento; reconhece nomes antigos */
  function parse(text) {
    const ids = [], rest = [];
    for (const part of String(text || "").split(/\s*[·;]\s*/).filter(Boolean)) {
      const t = tactics().find(t => part.includes(t.id) || part.toLowerCase() === t.name.toLowerCase() ||
        (t.aliases || []).some(a => part.toLowerCase().includes(a.toLowerCase())));
      if (t && !ids.includes(t.id)) ids.push(t.id); else if (!t) rest.push(part);
    }
    return { ids, extra: rest.join(" · ") };
  }
  const format = (ids, extra) => ids.map(id => { const t = tactics().find(x => x.id === id); return `${id} ${t ? t.name : ""}`.trim(); }).concat(extra ? [extra] : []).join(" · ");
  function mount(box, ids, onChange) {
    const sel = new Set(ids);
    const paint = () => {
      box.innerHTML = `<div class="mitre-grid">${tactics().map(t => `<button type="button" class="mt ${sel.has(t.id) ? "on" : ""}" data-t="${t.id}" title="${esc(t.description)}">
        <span class="mid">${t.id}</span><b>${esc(t.name)}</b><small>${esc(t.pt || "")}</small></button>`).join("")}</div>
        <div class="muted small" style="margin-top:6px">${sel.size ? `${sel.size} selecionada(s), na ordem da matriz.` : "Nenhuma selecionada."} Fonte: ${esc(App.data.catalog.mitre.source || "")}</div>`;
    };
    box.onclick = e => {
      const b = e.target.closest("[data-t]"); if (!b) return;
      sel.has(b.dataset.t) ? sel.delete(b.dataset.t) : sel.add(b.dataset.t);
      paint(); onChange(tactics().map(t => t.id).filter(id => sel.has(id)));
    };
    paint();
  }
  function dialog(text, onOk) {
    const cur = parse(text);
    let ids = cur.ids;
    modal({ title: "Táticas MITRE ATT&CK", wide: true, html: `<div class="tform"><div id="mpBox"></div>
        <label>Complemento <small>(texto livre que não é tática: OWASP, observações…)</small><input class="in" id="mpExtra" value="${esc(cur.extra)}"></label>
        <div class="create-actions"><button class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" data-ok>Aplicar</button></div></div>`,
      onMount: (b, close) => {
        mount($("#mpBox", b), ids, v => { ids = v; });
        b.querySelector("[data-cancel]").onclick = close;
        b.querySelector("[data-ok]").onclick = () => { onOk(format(ids, $("#mpExtra", b).value.trim())); close(); };
      } });
  }
  return { parse, format, mount, dialog };
})();

/* ───────── exportações geradas no navegador (HTML, PDF, SVG) ───────── */
const Exporter = (() => {
  const CSS = `body{font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#222;max-width:1000px;margin:24px auto;padding:0 20px}
    h1{font-size:26px;margin:0 0 4px}h2{font-size:19px;margin:28px 0 8px;border-bottom:2px solid #ddd;padding-bottom:4px}h3{font-size:16px;margin:20px 0 6px}
    table{border-collapse:collapse;width:100%;font-size:13.5px;margin:8px 0}th,td{border:1px solid #ccc;padding:6px 9px;text-align:left;vertical-align:top}th{background:#f2f2f4}
    blockquote{margin:10px 0;padding:8px 14px;border-left:4px solid #999;background:#f6f6f8}code{background:#f0f0f3;padding:1px 4px;border-radius:3px}
    .meta{color:#666;font-size:13px}.flow{overflow:auto;border:1px solid #ddd;border-radius:8px;margin:12px 0}.flow svg{display:block;max-width:100%;height:auto}
    figure.docimg{margin:14px 0;text-align:center}figure.docimg img{max-width:100%;height:auto;border:1px solid #ddd;border-radius:6px}figure.docimg figcaption{font-size:13px;color:#666;margin-top:6px}
    li.chk{list-style:none;margin-left:-20px}li.chk::before{content:"";display:inline-block;width:.75em;height:.75em;border:1.5px solid #777;border-radius:3px;margin-right:7px;vertical-align:-1px}li.chk.done::before{background:#2E7D32;border-color:#2E7D32}
    .codeblock{position:relative;margin:10px 0}.codeblock pre{background:#f4f4f6;border:1px solid #ddd;border-radius:6px;padding:10px 12px;overflow:auto;font:12.5px/1.5 ui-monospace,Menlo,Consolas,monospace;white-space:pre}
    .codeblock pre code{background:none;padding:0}.code-lang{position:absolute;left:10px;top:-9px;font-size:11px;color:#666;background:#fff;padding:0 4px}
    .code-copy{position:absolute;right:6px;top:6px;font:12px sans-serif;border:1px solid #ccc;background:#fff;border-radius:5px;padding:2px 8px;cursor:pointer}
    @media print{body{margin:0;max-width:none}.flow{border:0;page-break-inside:avoid}h2{page-break-after:avoid}.code-copy{display:none}}`;
  /* botão Copiar dos blocos de código no arquivo exportado (fora da aplicação não há o app.js) */
  const COPY_JS = `document.addEventListener("click",function(e){var b=e.target.closest(".code-copy");if(!b)return;var t=b.parentNode.querySelector("pre").innerText;`
    + `navigator.clipboard.writeText(t).then(function(){b.textContent="Copiado";setTimeout(function(){b.textContent="Copiar"},1500)})});`;
  const SVG_CSS = `.nodetxt{width:100%;height:100%;display:flex;align-items:center;justify-content:center;text-align:center;font:11px/1.25 Helvetica,Arial,sans-serif;color:#1b2230;padding:2px 4px;box-sizing:border-box;overflow:hidden}.nodetxt .m{color:#666}`;
  function flowSvg(pb) {
    const { svg, vb } = Flow.svg(pb.flow, { badges: badgesFor(pb) });
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb.join(" ")}" width="${vb[2]}" height="${vb[3]}"><style>${SVG_CSS}</style><rect x="${vb[0]}" y="${vb[1]}" width="${vb[2]}" height="${vb[3]}" fill="#fff"/>${svg}</svg>`;
  }
  /* imagens do documento entram no arquivo como data URL: o HTML funciona sozinho, fora da aplicação */
  /* JPEG: desenha o fluxograma (texto em SVG puro) num canvas em 2x, com fundo branco */
  async function flowJpeg(pb) {
    const { svg, vb } = Flow.svg(pb.flow, { badges: badgesFor(pb), plainText: true });
    const xml = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb.join(" ")}" width="${vb[2]}" height="${vb[3]}"><rect x="${vb[0]}" y="${vb[1]}" width="${vb[2]}" height="${vb[3]}" fill="#fff"/>${svg}</svg>`;
    const img = new Image();
    await new Promise((ok, bad) => { img.onload = ok; img.onerror = () => bad(new Error("Não foi possível desenhar o fluxograma")); img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(xml); });
    const scale = Math.min(2, 8000 / Math.max(vb[2], vb[3]));
    const c = document.createElement("canvas");
    c.width = Math.round(vb[2] * scale); c.height = Math.round(vb[3] * scale);
    const g = c.getContext("2d");
    g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
    g.drawImage(img, 0, 0, c.width, c.height);
    return new Promise((ok, bad) => c.toBlob(b => b ? ok(b) : bad(new Error("Não foi possível gerar a imagem")), "image/jpeg", .92));
  }
  async function inlineImages(text) {
    const urls = [...new Set([...text.matchAll(/src="(api\/pb\/PB-\d+\/img\/[\w.-]+)"/g)].map(m => m[1]))];
    for (const u of urls) {
      try {
        const blob = await (await fetch(u, { credentials: "same-origin" })).blob();
        const data = await new Promise(ok => { const rd = new FileReader(); rd.onload = () => ok(rd.result); rd.readAsDataURL(blob); });
        text = text.split(`src="${u}"`).join(`src="${data}"`);
      } catch { }
    }
    return text;
  }
  function html(pb) {
    const g = pb.gov, secs = pb.sections;
    const body = secs.map(s => /^Fluxograma/.test(s.title) && pb.hasFlow !== false
      ? `<h2>${esc(s.title)}</h2>${s.html}<div class="flow">${flowSvg(pb)}</div>`
      : `<h2>${esc(s.title)}</h2>${s.html}${s.subs.map(x => `<h3>${esc(x.title)}</h3>${x.html}`).join("")}`).join("\n");
    const withFlow = pb.hasFlow !== false;
    const hasFlowSec = !withFlow || secs.some(s => /^Fluxograma/.test(s.title));
    return `<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>${esc(pb.id)} — ${esc(pb.name)}</title><style>${CSS}</style></head><body>
      <h1>${esc(pb.id)} — ${esc(pb.name)}</h1><div class="meta">${esc(pb.byline)} · Status: ${esc(g.status)}${g.approver ? ` · Aprovador: ${esc(g.approver)}` : ""}${g.reviewer ? ` · Revisado por ${esc(g.reviewer)} em ${esc(g.reviewed)}` : ""}</div>
      ${pb.intro || ""}${hasFlowSec ? "" : `<h2>Fluxograma</h2><div class="flow">${flowSvg(pb)}</div>`}${body}
      <p class="meta">Exportado de ${esc(Brand.get().name)} em ${new Date().toLocaleString("pt-BR")} por ${esc(App.user.name)}.</p>
      <script>${COPY_JS}</script></body></html>`;
  }
  function download(name, content, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([content], { type }));
    a.download = name; document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }
  const base = pb => (pb.folder || pb.id).toLowerCase();
  return {
    html: async pb => { download(`${base(pb)}.html`, await inlineImages(html(pb)), "text/html"); toast("Documento HTML gerado"); },
    svg: pb => { download(`${base(pb)}-fluxo.svg`, flowSvg(pb), "image/svg+xml"); toast("Imagem do fluxograma gerada"); },
    jpeg: async pb => {
      try { download(`${base(pb)}-fluxo.jpg`, await flowJpeg(pb), "image/jpeg"); toast("Fluxograma exportado em JPEG"); }
      catch (e) { toast(e.message || "Falha ao gerar o JPEG", "err"); }
    },
    flowJpeg,
    print: async pb => {
      const w = window.open("", "_blank");       // abre já no clique (senão o navegador bloqueia) e recebe o conteúdo depois
      if (!w) return toast("O navegador bloqueou a nova janela. Use “HTML com fluxograma” e imprima o arquivo.", "warn");
      const text = await inlineImages(html(pb));
      w.document.open(); w.document.write(text); w.document.close();
      setTimeout(() => { w.focus(); w.print(); }, 400);
    },
  };
})();

/* ───────── templates ───────── */
const TemplatesPage = (() => {
  let current = null, vars = [], varsDoc = [], kindFilter = "", openName = "";
  const KIND_LBL = { playbook: "Playbook", runbook: "Runbook", doc: "Documento" };
  const adapter = v => ({
    saveDoc: (doc, rev) => api("PUT", `api/templates/${v.key}/doc`, { doc, rev }).then(Editor.withSync),
    saveFlow: (flow, refs, rev) => api("PUT", `api/templates/${v.key}/flow`, { flow, refs, rev }).then(r => { if (r.allTeams) setTeams(r.allTeams); return Editor.withSync(r); }),
    teams: v.teamDefs || {}, tplKey: v.key,
    reload: () => api("GET", `api/templates/${v.key}`).then(r => r.template),
    after: nv => { current = nv; const h = $(".tplhead small"); if (h) h.textContent = upd(nv); },
    fileBase: "template-" + v.key, draftKey: "templates/" + v.key,
    banner: `<div class="notice tplnote">Você está editando o <b>modelo</b>. Use variáveis como <code>{{nome}}</code> e <code>{{id}}</code>; o que tiver <code>{{ramo.…}}</code> se repete para cada ramo. Lista completa na aba <a href="#/templates/${esc(v.key)}/geral">Geral</a>.</div>`,
    docBar: `<b>Documento modelo</b><span class="muted"> · ${esc(v.name)}</span>`,
    flowBar: `<b>Fluxograma modelo</b><span class="muted"> · ${esc(v.name)}</span>`,
  });
  /* sub-aba com formulário: marca "Alterações não salvas" e registra a mudança para a navegação perguntar antes de
     descartar (trocar de sub-aba refazia a tela e perdia o que foi digitado) */
  function track(el, state) {
    const base = state(), changed = () => el.isConnected && state() !== base;
    const mark = () => { const m = $(".ap-dirty", el); if (m) m.hidden = !changed(); };
    Unsaved.check = changed;
    el.addEventListener("input", mark); el.addEventListener("change", mark);
    return mark;
  }
  const DIRTY = `<span class="ap-dirty" hidden>Alterações não salvas</span>`;
  const upd = t => t.updated_at ? `atualizado ${new Date(t.updated_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" })}${t.updated_by ? " por " + t.updated_by : ""}` : "";

  const KIND_ORDER = { playbook: 0, runbook: 1, doc: 2 };
  async function list(root) {
    if (openName) { openName = ""; Tabs.render(); }
    root.innerHTML = `<div class="pbbar"><div class="wrap"><div class="pbhead"><h1>Templates</h1>
      <div class="pbactions"><button class="btn primary sm" id="tNew">${ic("plus")}Novo template</button><button class="btn ghost sm" id="tImp">${ic("upload")}Importar template</button></div></div>
      <p class="muted tpl-intro">O modelo de documento, fluxograma, times e tags de cada tipo de documento. Quem cria um playbook, runbook ou documento escolhe o template.</p></div></div>
      <div class="wrap" id="tlist"><div class="empty">Carregando templates…</div></div>`;
    let data;
    try { data = await api("GET", "api/templates"); } catch (e) { return loadError($("#tlist"), e); }
    vars = data.variables; varsDoc = data.variablesDoc || [];
    const shown = data.templates.filter(t => !kindFilter || t.kind === kindFilter)
      .sort((a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || (b.default ? 1 : 0) - (a.default ? 1 : 0) || a.name.localeCompare(b.name, "pt-BR"));
    const n = (v, one, many) => `${v} ${v === 1 ? one : many}`;
    $("#tlist").innerHTML = `<h2 class="sr-only">Lista de templates</h2>
      <div class="home-bar"><div class="filters" role="group" aria-label="Filtrar por tipo">${[["", "Todos"], ["playbook", "Playbooks"], ["runbook", "Runbooks"], ["doc", "Documentos"]].map(([k, l]) =>
        `<button class="${k === kindFilter ? "on" : ""}" data-kf="${k}" aria-pressed="${k === kindFilter}">${l} <span class="cnt">${data.templates.filter(t => !k || t.kind === k).length}</span></button>`).join("")}</div></div>
      <div class="cards">${shown.map(t => t.error ? `<div class="card"><h3>${esc(t.name)}</h3><div class="err">${esc(t.error)}</div></div>` : `
      <article class="card tpl-card"><div class="card-top"><span class="id">${esc(KIND_LBL[t.kind] || "Template").toUpperCase()}</span>${t.default ? `<span class="tag" title="Template inicial deste tipo: vem selecionado na criação e recebe os documentos de um template excluído">padrão</span>` : ""}</div>
        <h3><a class="tpl-link" href="#/templates/${esc(t.key)}/geral">${esc(t.name)}</a></h3><p>${esc(t.description || "Sem descrição.")}</p>
        <div class="meta"><span class="chip">${n(t.sections, "seção", "seções")}</span>${t.hasFlow ? `<span class="chip" title="Caixas do fluxograma modelo">${n(t.nodes, "caixa", "caixas")}</span>` : ""}${t.usesRamos ? `<span class="chip" title="Um trecho do documento e uma caixa do fluxograma se repetem para cada ramo informado na criação">usa ramos</span>` : ""}${t.fields.length ? `<span class="chip">${n(t.fields.length, "campo", "campos")}</span>` : ""}${t.folders.length ? `<span class="chip">${n(t.folders.length, "pasta", "pastas")}</span>` : ""}</div>
        ${t.hasFlow ? `<a class="tpl-teams" href="#/templates/${esc(t.key)}/times">${ic("user")}<span class="tt-n">${n(t.teams.length, "time ou tag", "times e tags")}</span><span class="muted">${t.lanes.length ? " · raias " + t.lanes.map(esc).join(", ") : ""}</span></a>` : ""}
        <div class="govline"><span class="muted">${esc(upd(t)) || "Sem alterações registradas"}</span></div>
        <div class="row-btns tpl-acts"><a class="btn ghost xs" href="#/templates/${esc(t.key)}/geral" aria-label="Abrir ${esc(t.name)}">Abrir</a>
          <button class="btn ghost xs" data-dup="${esc(t.key)}" aria-label="Duplicar ${esc(t.name)}">Duplicar</button><a class="btn ghost xs" href="api/templates/${esc(t.key)}/export" download aria-label="Exportar ${esc(t.name)}">${ic("download")}Exportar</a>
          ${can("templates.delete") && !t.default ? `<button class="btn danger xs" data-del="${esc(t.key)}" data-name="${esc(t.name)}" aria-label="Excluir ${esc(t.name)}">Excluir</button>` : ""}</div></article>`).join("") || `<div class="lib-empty"><p>Nenhum template deste tipo.</p></div>`}</div>`;
    const reload = () => list(root);
    $("#tlist").querySelector(".filters").onclick = e => { const b = e.target.closest("[data-kf]"); if (b) { kindFilter = b.dataset.kf; reload(); } };
    $("#tNew").onclick = () => newDialog(data.templates, null, reload);
    $("#tImp").onclick = () => importDialog(reload);
    root.querySelectorAll("[data-dup]").forEach(b => b.onclick = () => newDialog(data.templates, b.dataset.dup, reload));
    root.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
      if (!(await ask(`Excluir o template ${b.dataset.name}? Ele vai para a lixeira do servidor. Os documentos criados com ele passam para o template padrão do tipo, que recebe os times que eles usam.`, { title: "Excluir template", ok: "Excluir", danger: true }))) return;
      try { const r = await api("DELETE", `api/templates/${b.dataset.del}`); toast(`Template excluído${r.moved.length ? ` · ${r.moved.join(", ")} agora usa(m) o padrão` : ""}`); refreshData(); } catch (e) { toast(e.message, "err"); }
    });
  }
  function newDialog(all, from, done) {
    const src = all.find(t => t.key === from);
    const kind0 = src ? src.kind : (kindFilter || "playbook");
    const fromOpts = k => `<option value="">${k === "playbook" ? "Em branco (alerta, ramos e times SOC N1, SOC N2 e CSIRT)" : "Em branco (propriedades e uma seção)"}</option>` +
      all.filter(t => !t.error && t.kind === k).map(t => `<option value="${esc(t.key)}" ${t.key === (from || "") ? "selected" : ""}>Cópia de ${esc(t.name)}</option>`).join("");
    modal({ title: from ? "Duplicar template" : "Novo template", html: `<form id="tnForm" class="tform">
        <label>Nome<input class="in" name="name" required maxlength="60" value="${from ? esc((src || {}).name + " (cópia)") : ""}" placeholder="ex.: CSIRT parceiro, Fraude, OT"></label>
        <label>Tipo de documento<select class="in" name="kind" ${from ? "disabled" : ""}>${Object.entries(KIND_LBL).map(([k, l]) => `<option value="${k}" ${k === kind0 ? "selected" : ""}>${l}</option>`).join("")}</select></label>
        <label>Começar de<select class="in" name="from">${fromOpts(kind0)}</select></label>
        <label>Descrição<input class="in" name="description" maxlength="300"></label>
        <div class="err" id="tnErr" hidden></div>
        <div class="create-actions"><button type="button" class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" type="submit">Criar</button></div></form>`,
      onMount: (b, close) => {
        b.querySelector("[data-cancel]").onclick = close;
        const form = $("#tnForm", b);
        form.kind.onchange = () => { form.from.innerHTML = fromOpts(form.kind.value); };
        form.onsubmit = async e => {
          e.preventDefault(); const f = new FormData(e.target);
          try { const r = await api("POST", "api/templates", { name: f.get("name"), kind: form.kind.value, from: f.get("from") || null, description: f.get("description") });
            close(); toast("Template criado"); location.hash = `#/templates/${r.template.key}/geral`; }
          catch (x) { $("#tnErr", b).textContent = x.message; $("#tnErr", b).hidden = false; }
        };
      } });
  }
  function importDialog(done) {
    modal({ title: "Importar template", html: `<div class="tform"><p class="muted small" style="margin-top:0">Arquivo <b>.medusa-template.md</b> exportado por qualquer instalação do Medusa Docs.</p>
        <label class="import-drop" id="tiDrop">Arraste o arquivo aqui ou clique para escolher<input type="file" id="tiFile" accept=".md,.markdown,.txt" hidden></label><div id="tiPrev"></div></div>`,
      onMount: (b, close) => {
        let text = "";
        const read = f => { if (!f) return; const rd = new FileReader(); rd.onload = async () => { text = rd.result;
          try { const p = (await api("POST", "api/templates/import", { text, dryRun: true })).preview;
            $("#tiPrev", b).innerHTML = `<div class="import-sum"><span>Template</span><b>${esc(p.name)}${p.exists ? " <small class='muted'>(já existe um com esse nome; será importado como cópia)</small>" : ""}</b>
              <span>Conteúdo</span><b>${p.sections} seções · ${p.nodes} caixas</b><span>Raias</span><b>${p.lanes.map(esc).join(", ")}</b><span>Times</span><b>${p.teams.map(esc).join(", ") || "—"}</b></div>
              ${p.warnings.length ? `<ul class="warnlist">${p.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
              <div class="create-actions"><button class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" id="tiGo">Importar</button></div>`;
            $("#tiPrev", b).querySelector("[data-cancel]").onclick = close;
            $("#tiGo", b).onclick = async () => { try { const r = await api("POST", "api/templates/import", { text }); close(); toast("Template importado"); location.hash = `#/templates/${r.template.key}/geral`; } catch (x) { toast(x.message, "err"); } };
          } catch (x) { $("#tiPrev", b).innerHTML = `<div class="err">${esc(x.message)}</div>`; } }; rd.readAsText(f, "utf-8"); };
        $("#tiFile", b).onchange = e => read(e.target.files[0]);
        const d = $("#tiDrop", b); d.ondragover = e => { e.preventDefault(); d.classList.add("over"); }; d.ondragleave = () => d.classList.remove("over");
        d.ondrop = e => { e.preventDefault(); d.classList.remove("over"); read(e.dataTransfer.files[0]); };
      } });
  }

  const MIN_FLOW = { subtitle: "", lanes: [{ key: "n1", label: "SOC N1", team: "SOC N1", color: "#1D62D1", kind: "team" }],
    nodes: [{ id: "inicio", lane: "n1", x: 68, y: 34, w: 96, h: 48, type: "start", lines: [{ t: "Início", s: "n" }] }], edges: [] };
  const FIELD_TYPES = [["text", "Texto"], ["select", "Lista (um)"], ["multiselect", "Lista (vários)"], ["date", "Data"], ["url", "Link"]];

  /* campos do template (runbook e documento): ficam na tabela de propriedades de cada documento criado com ele */
  function fieldsTab(el, t) {
    let fs = JSON.parse(JSON.stringify(t.fields || []));
    const paint = () => {
      el.innerHTML = `<div class="ecard"><div class="ecard-h"><b>Campos</b><span class="muted small">aparecem no formulário de criação, como linhas da tabela de propriedades e, se marcados como filtro, na biblioteca</span></div>
        <div class="tw"><table class="fields-tbl"><thead><tr><th>Rótulo</th><th>Chave</th><th>Tipo</th><th>Opções <small>(uma por linha)</small></th><th>Obrigatório</th><th>Filtro</th><th></th></tr></thead><tbody>
        ${fs.map((f, i) => `<tr data-i="${i}"><td><input class="in sm" data-k="label" value="${esc(f.label)}" maxlength="60"></td>
          <td><input class="in sm mono" data-k="key" value="${esc(f.key)}" maxlength="25" pattern="[a-z][a-z0-9_]{0,24}"></td>
          <td><select class="in sm" data-k="type">${FIELD_TYPES.map(([k, l]) => `<option value="${k}" ${k === f.type ? "selected" : ""}>${l}</option>`).join("")}</select></td>
          <td>${f.type === "select" || f.type === "multiselect" ? `<textarea class="in sm" data-k="options" rows="3">${esc((f.options || []).join("\n"))}</textarea>` : `<span class="muted small">—</span>`}</td>
          <td><input type="checkbox" data-k="required" ${f.required ? "checked" : ""}></td>
          <td>${f.type === "select" || f.type === "multiselect" ? `<input type="checkbox" data-k="filter" ${f.filter ? "checked" : ""}>` : ""}</td>
          <td class="rowctl"><button type="button" data-up="${i}" title="Subir" aria-label="Subir" ${i ? "" : "disabled"}>${ic("up")}</button><button type="button" class="x" data-rm="${i}" title="Remover" aria-label="Remover">${ic("close")}</button></td></tr>`).join("")
          || `<tr><td colspan="7" class="muted">Nenhum campo.</td></tr>`}</tbody></table></div>
        <div class="row-btns"><button class="btn ghost xs" id="fAdd">${ic("plus")}Campo</button></div>
        <p class="muted small">Use <code>{{campo.chave}}</code> no documento modelo para levar o valor a outros trechos. Mudar a chave de um campo em uso faz os documentos existentes deixarem de mostrar o valor na biblioteca.</p>
        <div class="err" id="fErr" hidden></div>
        <div class="create-actions"><span class="ap-dirty" ${changed() ? "" : "hidden"}>Alterações não salvas</span><button class="btn primary" id="fSave">Salvar campos</button></div></div>`;
      el.querySelectorAll("tr[data-i]").forEach(tr => {
        const f = fs[+tr.dataset.i];
        tr.querySelectorAll("[data-k]").forEach(inp => inp.oninput = inp.onchange = () => {
          const k = inp.dataset.k;
          if (k === "required" || k === "filter") f[k] = inp.checked;
          else if (k === "options") f.options = inp.value.split("\n").map(x => x.trim()).filter(Boolean);
          else { f[k] = inp.value; if (k === "label" && !f._keyTouched && !f._saved) f.key = norm(inp.value).replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^(\d)/, "c$1").slice(0, 25); if (k === "key") f._keyTouched = true; }
          if (k === "type" || k === "label") { const at = document.activeElement && document.activeElement.dataset.k; paint(); if (at === "label") { const x = el.querySelector(`tr[data-i="${fs.indexOf(f)}"] [data-k=label]`); x.focus(); x.setSelectionRange(x.value.length, x.value.length); } }
        });
      });
      el.querySelectorAll("[data-rm]").forEach(b => b.onclick = () => { fs.splice(+b.dataset.rm, 1); paint(); });
      el.querySelectorAll("[data-up]").forEach(b => b.onclick = () => { const i = +b.dataset.up; [fs[i - 1], fs[i]] = [fs[i], fs[i - 1]]; paint(); });
      $("#fAdd", el).onclick = () => { fs.push({ key: "", label: "", type: "text", options: [], required: false, filter: false }); paint(); };
      $("#fSave", el).onclick = async () => {
        try { current = (await api("PUT", `api/templates/${t.key}/meta`, { rev: t.rev, fields: fs.map(({ _keyTouched, _saved, ...f }) => f) })).template; toast("Campos salvos"); route(); }
        catch (x) { $("#fErr", el).textContent = x.message; $("#fErr", el).hidden = false; }
      };
    };
    fs.forEach(f => { f._saved = true; });
    const state = () => JSON.stringify(fs.map(({ _keyTouched, _saved, ...f }) => f)), base = state();
    function changed() { return state() !== base; }
    Unsaved.check = () => el.isConnected && changed();
    el.addEventListener("input", () => { const m = $(".ap-dirty", el); if (m) m.hidden = !changed(); });
    paint();
  }
  function foldersTab(el, t) {
    el.innerHTML = `<div class="ecard"><div class="ecard-h"><b>Estrutura de pastas sugerida</b></div>
      <p class="muted small" style="margin-top:0">Um caminho por linha, com <code>/</code> entre os níveis (ex.: <code>Por ferramenta/EDR</code>), até 6 níveis. A estrutura não é aplicada sozinha: na biblioteca, o botão "Criar estrutura de pastas do template" cria o que faltar, sem duplicar.</p>
      <textarea class="in mono" id="flText" rows="10">${esc((t.folders || []).join("\n"))}</textarea>
      <div class="err" id="flErr" hidden></div>
      <div class="create-actions">${DIRTY}<button class="btn primary" id="flSave">Salvar pastas</button></div></div>`;
    track(el, () => $("#flText", el).value);
    $("#flSave", el).onclick = async () => {
      const folders = $("#flText", el).value.split("\n").map(x => x.trim()).filter(Boolean);
      try { current = (await api("PUT", `api/templates/${t.key}/meta`, { rev: t.rev, folders })).template; toast("Pastas salvas"); route(); }
      catch (x) { $("#flErr", el).textContent = x.message; $("#flErr", el).hidden = false; }
    };
  }

  function general(el, t) {
    if (t.kind && t.kind !== "playbook") return generalDoc(el, t);
    el.innerHTML = `<div class="appearance"><div class="ecard"><div class="ecard-h"><b>Dados do template</b></div>
        <form id="tgForm" class="tform">
          <label>Nome<input class="in" name="name" maxlength="60" value="${esc(t.name)}" required></label>
          <label>Descrição<textarea class="in" name="description" rows="2" maxlength="300">${esc(t.description || "")}</textarea></label>
          <div class="pp-row"><label>Owner padrão<input class="in" name="owner" value="${esc(t.owner || "")}"></label>
            <label>Fase NIST padrão<input class="in" name="nist" value="${esc(t.nist || "")}" list="nistPhases" maxlength="200" aria-describedby="nistHelp"></label></div>
          <datalist id="nistPhases">${["Preparação", "Detecção e Análise", "Contenção", "Erradicação", "Recuperação", "Contenção, Erradicação e Recuperação", "Pós-Incidente", "Detecção e Análise → Pós-Incidente (ciclo completo)"].map(x => `<option value="${x}">`).join("")}</datalist>
          <p class="muted small" id="nistHelp">Fase do ciclo NIST SP 800-61 em que o playbook atua; escolha uma sugestão ou descreva um intervalo.</p>
          <div class="err" id="tgErr" hidden></div>
          <div class="create-actions">${DIRTY}<a class="btn ghost" href="api/templates/${esc(t.key)}/export" download>${ic("download")}Exportar template</a><button class="btn primary" type="submit">Salvar</button></div></form>
        <div class="pp-lbl" style="margin-top:18px">Resumo</div>
        <div class="meta"><span class="chip">${t.sections.length} seções</span><span class="chip">${t.flow.nodes.length} caixas</span>${t.usesRamos ? `<span class="chip">usa ramos</span>` : `<span class="chip">sem ramos</span>`}${t.flow.lanes.map(l => `<span class="chip">${esc(l.label)}</span>`).join("")}</div>
        ${t.hasRamos ? `<p class="muted small">Ramos: a subseção <code>R{{ramo.n}} · {{ramo.nome}}</code> e a caixa <code>R{{ramo.n}}</code> do fluxograma se repetem para cada ramo informado na criação. Ficam sincronizadas: criar, renomear ou excluir de um lado reflete no outro ao salvar.</p>`
          : `<div class="notice" style="margin-top:12px">Este template não tem ramos. <button class="btn soft xs" id="tgRamos">${ic("plus")}Adicionar ramos</button><br><small class="muted">Cria a seção “Ramos em detalhe” no documento e a caixa de ramo no fluxograma, como no template Padrão.</small></div>`}</div>
      <div class="ecard"><div class="ecard-h"><b>Variáveis disponíveis</b></div>
        <p class="muted small" style="margin-top:0">Escreva no documento modelo ou nos textos das caixas do fluxograma; são substituídas na criação do playbook.</p>
        <table class="vars"><tbody>${vars.map(([k, d]) => `<tr><td><code>{{${esc(k)}}}</code></td><td>${esc(d)}</td></tr>`).join("")}</tbody></table>
        <p class="muted small">Repetição por ramo: subseções, linhas de tabela, itens de lista, parágrafos e caixas do fluxograma que contêm <code>{{ramo.…}}</code> são duplicados para cada ramo. Caixas repetidas ficam lado a lado e levam junto as setas e o vínculo "ao clicar".</p></div></div>`;
    if ($("#tgRamos", el)) $("#tgRamos", el).onclick = async () => {
      try { current = (await api("POST", `api/templates/${t.key}/ramos`, { rev: t.rev })).template; toast("Ramos adicionados ao documento e ao fluxograma do template"); route(); }
      catch (x) { toast(x.message, "err"); }
    };
    { const form = $("#tgForm", el); track(form, () => JSON.stringify([...new FormData(form)])); }
    $("#tgForm", el).onsubmit = async e => {
      e.preventDefault(); const f = new FormData(e.target);
      try { current = (await api("PUT", `api/templates/${t.key}/meta`, { name: f.get("name"), description: f.get("description"), owner: f.get("owner"), nist: f.get("nist"), rev: t.rev })).template;
        toast("Template salvo"); route(); }
      catch (x) { $("#tgErr", el).textContent = x.message; $("#tgErr", el).hidden = false; }
    };
  }
  /* geral de template de runbook/documento: sem NIST e ramos; no runbook, a opção de incluir fluxograma */
  function generalDoc(el, t) {
    const fv = (t.fields || []).map(f => [`campo.${f.key}`, f.label]);
    el.innerHTML = `<div class="appearance"><div class="ecard"><div class="ecard-h"><b>Dados do template</b><span class="tag">${esc(KIND_LBL[t.kind])}</span></div>
        <form id="tgForm" class="tform">
          <label>Nome<input class="in" name="name" maxlength="60" value="${esc(t.name)}" required></label>
          <label>Descrição<textarea class="in" name="description" rows="2" maxlength="300">${esc(t.description || "")}</textarea></label>
          <label>Owner padrão<input class="in" name="owner" value="${esc(t.owner || "")}"></label>
          ${t.kind === "runbook" ? `<label class="chk-inline"><input type="checkbox" id="tgFlow" ${t.hasFlow ? "checked" : ""}> Incluir fluxograma modelo (runbooks criados com ele já começam com um fluxograma)</label>` : ""}
          <div class="err" id="tgErr" hidden></div>
          <div class="create-actions">${DIRTY}<a class="btn ghost" href="api/templates/${esc(t.key)}/export" download>${ic("download")}Exportar template</a><button class="btn primary" type="submit">Salvar</button></div></form>
        <div class="meta" style="margin-top:14px"><span class="chip">${t.sections.length} seções</span><span class="chip">${(t.fields || []).length} campos</span><span class="chip">${(t.folders || []).length} pastas</span></div></div>
      <div class="ecard"><div class="ecard-h"><b>Variáveis disponíveis</b></div>
        <table class="vars"><tbody>${varsDoc.filter(([k]) => k !== "campo.<chave>").concat(fv).map(([k, d]) => `<tr><td><code>{{${esc(k)}}}</code></td><td>${esc(d)}</td></tr>`).join("")}</tbody></table></div></div>`;
    { const form = $("#tgForm", el); track(form, () => JSON.stringify([...new FormData(form)])); }
    $("#tgForm", el).onsubmit = async e => {
      e.preventDefault(); const f = new FormData(e.target);
      try { current = (await api("PUT", `api/templates/${t.key}/meta`, { name: f.get("name"), description: f.get("description"), owner: f.get("owner"), rev: t.rev })).template; toast("Template salvo"); route(); }
      catch (x) { $("#tgErr", el).textContent = x.message; $("#tgErr", el).hidden = false; }
    };
    if ($("#tgFlow", el)) $("#tgFlow", el).onchange = async e => {
      const on = e.target.checked;
      if (!on && !(await ask("Tirar o fluxograma do template? Runbooks já criados não mudam.", { title: "Fluxograma modelo", ok: "Tirar", danger: true }))) { e.target.checked = true; return; }
      try {
        current = (await api("PUT", `api/templates/${t.key}/flow`, { flow: on ? MIN_FLOW : { subtitle: "", lanes: [], nodes: [], edges: [] }, refs: {}, rev: t.rev })).template;
        toast(on ? "Fluxograma incluído: edite na aba Fluxograma modelo" : "Fluxograma retirado do template");
        location.hash = on ? `#/templates/${t.key}/fluxograma` : `#/templates/${t.key}/geral`; route();
      } catch (x) { toast(x.message, "err"); e.target.checked = !on; }
    };
  }

  function teams(el, t) {
    const own = t.teamDefs || {};
    const used = new Set(t.flow.lanes.map(l => l.team).filter(Boolean).concat(t.flow.nodes.map(n => n.team).filter(Boolean)));
    const other = Object.keys(TEAMS).filter(n => !(n in own)).sort();
    const card = n => { const d = own[n], cat = d.category === "central" ? "central" : "apoio";
      return `<div class="team-card"><h4><span class="chip team" style="background:${esc(d.color)}">${esc(n)}</span>${cat === "central" ? `<span class="cat central">raia</span>` : ""}</h4>
        <p>${esc(d.summary || "Sem descrição.")}</p>
        <div class="row"><button class="btn ghost xs" data-edit="${esc(n)}" aria-label="Editar ${esc(n)}">${ic("edit")}Editar</button>
          ${used.has(n) ? `<span class="muted small" title="Aparece no fluxograma modelo (raia ou caixa de apoio); para tirar do template, tire antes do fluxograma">em uso no fluxograma</span>` : `<button class="btn ghost xs" data-rm="${esc(n)}" aria-label="Tirar ${esc(n)} do template">Tirar do template</button>`}</div></div>`; };
    const names = Object.keys(own);
    el.innerHTML = `<div class="ecard"><div class="ecard-h"><h2>Times e tags do template</h2></div>
      <p class="muted small" style="margin-top:0">Times <b>centrais</b> podem virar raias; <b>apoio e tags</b> aparecem como caixas de apoio e como tags clicáveis nos textos. Valem para este template e para os playbooks criados com ele, e vão junto quando o template é exportado. Um time em uso (no fluxograma do template ou em playbooks dele) não pode ser retirado.</p>
      ${[["central", "Times centrais (raias)"], ["apoio", "Apoio e tags"]].map(([c, h]) => `<h3 class="sect-title">${h}</h3>
        <div class="teams-grid">${names.filter(n => (own[n].category === "central") === (c === "central")).map(card).join("") || `<div class="empty">Nenhum.</div>`}</div>`).join("")}
      <div class="tt-add"><button class="btn primary sm" id="ttNew">${ic("plus")}Novo time ou tag</button>
        ${other.length ? `<select class="in" id="ttCopy"><option value="">Copiar de outro template…</option>${other.map(n => `<option>${esc(n)}</option>`).join("")}</select>` : ""}</div>
      <div class="err" id="ttErr" hidden></div></div>`;
    const put = async (next, msg) => {
      try { const r = await api("PUT", `api/templates/${t.key}/teams`, { teams: next, rev: t.rev }); setTeams(r.allTeams); toast(msg); route(); }
      catch (x) { $("#ttErr", el).textContent = x.message; $("#ttErr", el).hidden = false; }
    };
    const clone = () => JSON.parse(JSON.stringify(own));
    if ($("#ttCopy", el)) $("#ttCopy", el).onchange = e => { const n = e.target.value; if (!n) return; const nx = clone(); nx[n] = TEAMS[n]; put(nx, `${n} copiado para o template`); };
    $("#ttNew", el).onclick = () => teamDialog({ tpl: t.key }, null, () => route());
    el.querySelectorAll("[data-rm]").forEach(b => b.onclick = async () => { if (!(await ask(`Tirar ${b.dataset.rm} do template?`, { title: "Tirar time", ok: "Tirar", danger: true }))) return; const nx = clone(); delete nx[b.dataset.rm]; put(nx, `${b.dataset.rm} retirado do template`); });
    el.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => teamDialog({ tpl: t.key }, b.dataset.edit, () => route()));
  }
  async function detail(root, key, sub) {
    root.innerHTML = `<div class="wrap"><div class="empty">Carregando template…</div></div>`;
    try {
      if (!vars.length) { const d = await api("GET", "api/templates"); vars = d.variables; varsDoc = d.variablesDoc || []; }
      current = (await api("GET", `api/templates/${key}`)).template;
    } catch (e) { return loadError(root, e); }
    const t = current, kind = t.kind || "playbook";
    /* abas por tipo: campos e pastas só em runbook e documento; fluxograma e times onde há fluxograma */
    const subs = [["geral", "Geral"], ["documento", "Documento modelo", "edit"]]
      .concat(kind !== "playbook" ? [["campos", "Campos"], ["pastas", "Pastas"]] : [])
      .concat(t.hasFlow ? [["fluxograma", "Fluxograma modelo", "edit"], ["times", "Times e tags"]] : []);
    sub = subs.some(x => x[0] === sub) ? sub : "geral";
    openName = t.name; document.title = `${t.name} · Templates`; Tabs.render();
    root.innerHTML = `<div class="pbbar"><div class="wrap"><nav class="crumbs" aria-label="Caminho"><a href="#/templates">${ic("left")}Templates</a></nav>
      <div class="pbhead tplhead"><h1>${esc(t.name)}</h1><span class="tag">${esc(KIND_LBL[kind])}</span><small class="muted">${esc(upd(t))}</small></div>
      <nav class="tabs" aria-label="Partes do template">${subs.map(([k, l, i]) =>
        `<a href="#/templates/${esc(key)}/${k}" class="${k === sub ? "on" : ""}"${k === sub ? ` aria-current="page"` : ""}>${i ? ic(i) : ""}${l}</a>`).join("")}</nav></div></div><div class="wrap" id="tplview"></div>`;
    const tv = $("#tplview"), onTab = $(".tabs a.on", root); if (onTab) onTab.scrollIntoView({ block: "nearest", inline: "nearest" });
    if (sub === "documento") return Editor.docEditor(tv, t, adapter);
    if (sub === "fluxograma") { document.body.classList.add("editing"); return Editor.flowEditor(tv, t, adapter); }
    ({ times: teams, campos: fieldsTab, pastas: foldersTab })[sub] ? ({ times: teams, campos: fieldsTab, pastas: foldersTab })[sub](tv, t) : general(tv, t);
  }
  return { render: (root, key, sub) => key ? detail(root, key, sub) : list(root), tabTitle: () => openName ? `${openName} · Templates` : "Templates" };
})();

/* ───────── versões (histórico, leitura, comparação, restauração) ───────── */
const Versions = (() => {
  const fmt = t => t ? new Date(t).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";
  const vpill = v => `<span class="vpill">${esc(v)}</span>`;

  async function list(pb, el) {
    el.innerHTML = `<div class="empty">Carregando histórico…</div>`;
    let d; try { d = await api("GET", `api/pb/${pb.id}/versions`); } catch (e) { el.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
    const vs = d.versions;
    el.innerHTML = `<div class="ver-head"><div><b>Versão atual: ${vpill(d.current)}</b> ${statusPill(d.currentStatus, pb.type)}</div>
        <p class="muted small">Desenvolvimento e Homologação somam 1 depois do ponto a cada gravação (0.1 → 0.2). Publicar em Produção gera a próxima versão cheia (0.4 → 1.0). Em Produção, cada alteração é Minor (2.3 → 2.4) ou Major (2.3 → 3.0), com a descrição de quem salvou. ${can("playbook.view_drafts") ? "" : "Você vê as versões que estiveram em Homologação ou Produção."}</p></div>
      ${vs.length ? `<div class="vtimeline">${vs.map((v, i) => `<div class="vitem ${i === 0 ? "latest" : ""}"><div class="vdot"></div>
          <div class="vbody"><div class="vtop">${vpill(v.version)} ${statusPill(v.status, pb.type)} <span class="vkind">${esc(v.kindName)}</span>${i === 0 ? `<span class="tag">mais recente</span>` : ""}</div>
            <div class="vmeta">${esc(fmt(v.created_at))} · ${esc(v.author_name)}${v.note ? ` · <span class="vnote">${esc(v.note)}</span>` : ""}</div></div>
          <div class="vact"><a class="btn ghost xs" href="#/${pb.slug}/versoes/${v.id}">Ler</a>
            <a class="btn ghost xs" href="#/${pb.slug}/versoes/${v.id}/comparar/${vs[i + 1] ? vs[i + 1].id : "atual"}" title="${vs[i + 1] ? "Comparar com a versão anterior" : "Comparar com a versão atual"}">Comparar</a>
            ${can("playbook.restore") && i > 0 ? `<button class="btn ghost xs" data-restore="${v.id}" data-v="${esc(v.version)}">Restaurar</button>` : ""}</div></div>`).join("")}</div>`
        : `<div class="empty">Ainda não há versões registradas. A primeira é criada na próxima gravação.</div>`}`;
    el.querySelectorAll("[data-restore]").forEach(b => b.onclick = () => restore(pb, b.dataset.restore, b.dataset.v));
  }

  async function restore(pb, id, v) {
    if (Editor.dirty || Editor.hasDraft(pb.id.toLowerCase())) return toast("Salve ou descarte as alterações dos editores deste playbook antes", "warn");
    if (!(await ask(`Restaurar o conteúdo da versão ${v}?\n\nDocumento, fluxograma e vínculos voltam ao daquela versão. O status atual (${pb.gov.status}) e o histórico são mantidos: a restauração vira uma nova versão.`, { title: "Restaurar versão", ok: "Restaurar" }))) return;
    const change = await Editor.askChange(pb, `a restauração do conteúdo da versão ${v}`);
    if (change === false) return;
    try {
      const r = await api("POST", `api/pb/${pb.id}/versions/${id}/restore`, { rev: pb.rev, change: change || undefined });
      replacePlaybook(r.playbook); toast(`Conteúdo da versão ${v} restaurado como versão ${r.version}`); location.hash = `#/${pb.slug}/versoes`;
    } catch (e) { toast(e.message, "err"); }
  }

  /* leitura de uma versão: documentação completa, com o mesmo visual e o fluxograma interativo */
  async function read(pb, el, id) {
    el.innerHTML = `<div class="empty">Carregando versão…</div>`;
    let d; try { d = await api("GET", `api/pb/${pb.id}/versions/${id}`); } catch (e) { el.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
    const v = d.version, vp = d.playbook, g = vp.gov;
    vp.slug = pb.slug;
    const secs = vp.sections.filter(s => !/^Fluxograma/.test(s.title));
    el.innerHTML = `<div class="ver-banner"><div>${ic("history")}Você está lendo a versão ${vpill(v.version)} ${statusPill(v.status, pb.type)} de <b>${esc(fmt(v.created_at))}</b>, salva por <b>${esc(v.author_name)}</b> (${esc(v.kindName)}${v.note ? `: ${esc(v.note)}` : ""}). Não é necessariamente a versão em uso.</div>
        <div class="ver-actions"><a class="btn ghost sm" href="#/${pb.slug}/versoes">${ic("left")}Histórico</a><a class="btn ghost sm" href="#/${pb.slug}/versoes/${v.id}/comparar/atual">${ic("compare")}Comparar com a atual</a>
          <button class="btn ghost sm" id="vHtml" title="Baixa esta versão como HTML com o fluxograma">${ic("download")}HTML</button><button class="btn ghost sm" id="vPrint">${ic("print")}Imprimir / PDF</button>
          ${can("playbook.restore") ? `<button class="btn primary sm" id="vRestore">Restaurar esta versão</button>` : ""}</div></div>
      <article class="docview">
        <header class="docview-head"><div class="dv-id">${esc(vp.id)} · versão ${esc(v.version)}</div><h1>${esc(vp.name)}</h1><div class="muted">${esc(vp.byline)}</div>
          <div class="gov dv-gov"><div><span>Status na versão</span><b>${esc(g.status)}</b></div><div><span>Aprovador</span><b>${esc(g.approver || "—")}</b></div>
            <div><span>Último revisor</span><b>${esc(g.reviewer || "—")}</b></div><div><span>Data de revisão</span><b>${esc(g.reviewed || "—")}</b></div>
            <div><span>Owner</span><b>${esc(vp.props["Owner do documento"] || "—")}</b></div><div><span>Template</span><b>${esc(vp.templateName || "—")}</b></div></div></header>
        <div class="docgrid"><nav class="toc">${vp.flow.nodes.length || pb.type === "playbook" ? `<a href="#" data-go="vfluxo">Fluxograma</a>` : ""}${secs.map(s => `<a href="#" data-go="vsec-${s.id}">${esc(s.title)}</a>`).join("")}</nav>
          <div class="doc">${vp.intro ? `<section class="md intro">${vp.intro}</section>` : ""}<section id="vfluxo" class="md" ${vp.flow.nodes.length || pb.type === "playbook" ? "" : "hidden"}><h2>Fluxograma</h2><p class="muted small">Clique em uma caixa para ler o trecho desta versão da documentação.</p><div class="flowbox viewer dv-flow" id="vflow"></div></section>
            ${secs.map(s => `<section id="vsec-${s.id}" class="md"><h2>${esc(s.title)}</h2>${s.html}${s.subs.map(x => `<h3>${esc(x.title)}</h3>${x.html}`).join("")}</section>`).join("")}</div></div>
      </article>`;
    if (vp.flow.nodes.length) {
      const live = n => (vp.refs[n.id] || []).length || n.team;
      const { svg, vb } = Flow.svg(vp.flow, { badges: badgesFor(vp), nodeClass: n => live(n) ? "" : "static" });
      const box = $("#vflow", el);
      box.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb.join(" ")}" width="${vb[2]}" height="${vb[3]}">${svg}</svg>`;
      const sv = $("svg", box); const fit = () => { const z = Math.min(1.2, (box.clientWidth - 4) / vb[2]); sv.setAttribute("width", vb[2] * z); sv.setAttribute("height", vb[3] * z); }; fit();
      sv.addEventListener("click", e => {
        const node = e.target.closest(".node"); if (!node || node.classList.contains("static")) return;
        if (node.dataset.team) return showTeam(vp, node.dataset.team);
        const n = vp.flow.nodes.find(x => x.id === node.dataset.node);
        showRefs(vp, vp.refs[n.id], esc((n.lines || []).map(l => l.t).join(" ")), false);
      });
    } else $("#vflow", el).innerHTML = `<div class="empty">Esta versão não tem fluxograma.</div>`;
    useTeams(vp); linkify(el.querySelector(".docview .doc"), vp);
    el.querySelector(".docview .toc").onclick = e => { const a = e.target.closest("[data-go]"); if (!a) return; e.preventDefault(); document.getElementById(a.dataset.go).scrollIntoView({ block: "start" }); };
    const named = Object.assign({}, vp, { folder: `${(pb.folder || pb.id)}-v${v.version}` });
    $("#vHtml", el).onclick = () => Exporter.html(named);
    $("#vPrint", el).onclick = () => Exporter.print(named);
    if ($("#vRestore", el)) $("#vRestore", el).onclick = () => restore(pb, v.id, v.version);
  }

  /* comparação: linhas do documento e itens do fluxograma acrescentados (+) e removidos (−) */
  async function compare(pb, el, id, other) {
    el.innerHTML = `<div class="empty">Comparando…</div>`;
    let d, vs;
    try { [d, vs] = await Promise.all([api("GET", `api/pb/${pb.id}/versions/${id}/diff?with=${encodeURIComponent(other || "atual")}`), api("GET", `api/pb/${pb.id}/versions`)]); }
    catch (e) { el.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
    const opt = sel => `<option value="atual" ${sel === "atual" ? "selected" : ""}>Atual (${esc(vs.current)})</option>` +
      vs.versions.map(v => `<option value="${v.id}" ${String(v.id) === String(sel) ? "selected" : ""}>${esc(v.version)} · ${esc(fmt(v.created_at))} · ${esc(v.kindName)}</option>`).join("");
    const CTX = 3, rows = [];
    let eqRun = [];
    const flushEq = last => {
      if (eqRun.length > CTX * 2 + 1 || (last && eqRun.length > CTX)) {
        const head = rows.length ? eqRun.slice(0, CTX) : [], tail = last ? [] : eqRun.slice(-CTX);
        head.forEach(x => rows.push(["eq", x])); rows.push(["gap", eqRun.length - head.length - tail.length]); tail.forEach(x => rows.push(["eq", x]));
      } else eqRun.forEach(x => rows.push(["eq", x]));
      eqRun = [];
    };
    for (const o of d.doc) { if (o.t === "eq") eqRun.push(o.text); else { flushEq(false); rows.push([o.t, o.text]); } }
    flushEq(true);
    const line = ([t, x]) => t === "gap" ? `<div class="dl gap">${ic("more")} ${x} linha(s) iguais</div>` : `<div class="dl ${t}"><span class="sg">${t === "add" ? "+" : t === "del" ? "−" : " "}</span>${esc(x) || "&nbsp;"}</div>`;
    el.innerHTML = `<div class="ver-banner"><div>Comparando ${vpill(d.from.version)} → ${vpill(d.to.version)}
        <span class="dstat"><b class="add">+${d.stats.added}</b> <b class="del">−${d.stats.removed}</b> linhas no documento · ${d.stats.flowChanges} mudança(s) no fluxograma</span></div>
        <div class="ver-actions"><a class="btn ghost sm" href="#/${pb.slug}/versoes">${ic("left")}Histórico</a></div></div>
      <div class="cmp-pick"><label>Versão<select class="in" id="cA">${opt(String(id))}</select></label><span>×</span><label>Comparar com<select class="in" id="cB">${opt(other || "atual")}</select></label></div>
      ${pb.hasFlow === false && !d.flow.length ? "" : `<div class="ecard"><div class="ecard-h"><b>Fluxograma</b><span class="muted small">caixas e setas (posição não conta)</span></div>
        ${d.flow.length ? `<div class="difflines">${d.flow.map(o => line([o.t, o.text])).join("")}</div>` : `<p class="muted">Sem mudanças no fluxograma.</p>`}</div>`}
      <div class="ecard"><div class="ecard-h"><b>Documento</b><span class="muted small">Markdown, linha a linha</span></div>
        ${d.stats.added || d.stats.removed ? `<div class="difflines">${rows.map(line).join("")}</div>` : `<p class="muted">Sem mudanças no documento.</p>`}</div>`;
    const go = () => { const a = $("#cA", el).value, b = $("#cB", el).value;
      if (a === "atual" && b === "atual") return;
      location.hash = a === "atual" ? `#/${pb.slug}/versoes/${b}/comparar/atual` : `#/${pb.slug}/versoes/${a}/comparar/${b}`; };
    $("#cA", el).onchange = go; $("#cB", el).onchange = go;
  }

  return {
    render: (pb, el, id, rest) => !id ? list(pb, el) : rest[0] === "comparar" ? compare(pb, el, id, rest[1]) : read(pb, el, id),
  };
})();

/* ───────── importar ───────── */
async function importDialog(type) {
  type = typeof type === "string" ? type : "playbook";
  const ti = typeInfo(type);
  let text = "", fname = "", tpls = [];
  try { tpls = (await api("GET", `api/templates?kind=${type}`)).templates.filter(t => !t.error); } catch (x) { return toast(x.message, "err"); }
  modal({
    title: `Importar ${ti.label.toLowerCase()}`, wide: true, html: `<div class="tform">
      <p class="muted small" style="margin-top:0">Aceita arquivos <b>.medusa.md</b> exportados por qualquer instalação do Medusa Docs, ou um <b>.md</b> comum
        (título <code># PB-00 — Nome</code> e seções <code>##</code>). O fluxograma vem do bloco <code>mermaid</code>. O playbook importado entra em <b>Desenvolvimento</b>.</p>
      <label>Template <small>(${type === "playbook" ? "define os times e tags; times do arquivo que faltarem entram nele" : "define os campos"})</small><select class="in" id="imTpl">${tpls.map(t => `<option value="${esc(t.key)}" ${t.default ? "selected" : ""}>${esc(t.name)}</option>`).join("")}</select></label>
      <label class="import-drop" id="imDrop">Arraste o arquivo aqui ou clique para escolher<input type="file" id="imFile" accept=".md,.markdown,.txt,text/markdown,text/plain" hidden></label>
      <details style="margin-top:10px"><summary class="small">…ou cole o conteúdo</summary><textarea class="in code" id="imText" style="min-height:160px;margin-top:8px"></textarea>
        <button class="btn ghost sm" id="imPaste" style="margin-top:6px">Analisar texto colado</button></details>
      <div id="imPrev"></div></div>`,
    onMount: (b, close) => {
      const prev = $("#imPrev", b);
      async function analyze(id) {
        try {
          const r = await api("POST", "api/import", { text, id, template: $("#imTpl", b).value, dryRun: true }), p = r.preview;
          const pre = ti.prefix || "PB";
          const nextId = () => { const used = PBS.filter(x => x.id.startsWith(pre + "-")).map(x => +x.id.slice(pre.length + 1)); let n = 1; while (used.includes(n)) n++; return pre + "-" + String(n).padStart(2, "0"); };
          prev.innerHTML = `<div class="import-sum">
              <span>Arquivo</span><b>${esc(fname || "texto colado")}</b>
              <span>${esc(ti.label)}</span><b>${esc(p.id)} — ${esc(p.name)}</b>${p.folder ? `<span>Pasta</span><b>${esc(p.folder)}</b>` : ""}
              <span>Origem</span><b>${esc(p.origin.gerado_por || "—")}${p.origin.status_origem ? ` · estava em ${esc(p.origin.status_origem)}` : ""}${p.origin.exportado_por ? ` · exportado por ${esc(p.origin.exportado_por)}` : ""}</b>
              <span>Conteúdo</span><b>${p.sections} seções${p.nodes ? ` · ${p.nodes} caixas · ${p.edges} setas` : ""}${p.images ? ` · ${p.images} imagem(ns)` : ""}</b>
              ${p.lanes.length ? `<span>Raias</span><b>${p.lanes.map(esc).join(", ")}</b>` : ""}
              <span>Template</span><b>${esc(p.template)}</b>
              ${p.createTeams.length ? `<span>Times novos</span><b>${p.createTeams.map(esc).join(", ")} <small class="muted">(entram no template ${esc(p.template)})</small></b>` : ""}
            </div>
            ${p.warnings.length ? `<ul class="warnlist">${p.warnings.map(w => `<li>${esc(w)}</li>`).join("")}</ul>` : ""}
            ${p.exists ? `<div class="notice">Já existe um <b>${esc(p.id)}</b> aqui. Escolha o que fazer:</div>
              <div class="radio-row"><label><input type="radio" name="mode" value="new" checked> Importar como novo, com o ID <input class="in sm" id="imId" value="${nextId()}" style="width:90px"></label>
              <label><input type="radio" name="mode" value="replace"> Substituir o atual (ele vai para a lixeira)</label></div>` : ""}
            <div class="err" id="imErr" hidden></div>
            <div class="create-actions"><button class="btn ghost" data-cancel>Cancelar</button><button class="btn primary" id="imGo">Importar</button></div>`;
          prev.querySelector("[data-cancel]").onclick = close;
          $("#imGo", prev).onclick = async () => {
            const mode = (prev.querySelector("input[name=mode]:checked") || {}).value || "new";
            const target = p.exists && mode === "new" ? $("#imId", prev).value.trim().toUpperCase() : p.id;
            try {
              const r2 = await api("POST", "api/import", { text, id: target, mode, template: $("#imTpl", b).value });
              replacePlaybook(r2.playbook); setTeams(r2.teams); close();
              await refreshIndex(); toast(`${r2.playbook.id} importado em ${statusLabel(type, "Desenvolvimento")}`); location.hash = `#/${r2.playbook.slug}/${type === "playbook" ? "fluxo" : "doc"}`;
            } catch (x) { $("#imErr", prev).textContent = x.message; $("#imErr", prev).hidden = false; }
          };
        } catch (x) { prev.innerHTML = `<div class="err">${esc(x.message)}</div>`; }
      }
      const readFile = f => {
        if (!f) return;
        if (f.size > 6 * 1024 * 1024) return toast("Arquivo grande demais (máx. 6 MB)", "err");
        fname = f.name; const rd = new FileReader(); rd.onload = () => { text = rd.result; analyze(); }; rd.readAsText(f, "utf-8");
      };
      $("#imFile", b).onchange = e => readFile(e.target.files[0]);
      const drop = $("#imDrop", b);
      drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
      drop.ondragleave = () => drop.classList.remove("over");
      drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); readFile(e.dataTransfer.files[0]); };
      $("#imTpl", b).onchange = () => { if (text.trim()) analyze(); };
      $("#imPaste", b).onclick = () => { text = $("#imText", b).value; fname = ""; if (text.trim()) analyze(); };
    }
  });
}

async function start() {
  try {
    const b = await api("GET", "api/bootstrap");
    App.user = b.user; setData(b);
    await refreshIndex();
  } catch (e) { if (e.status !== 401 && e.status !== 403) view.innerHTML = `<div class="wrap"><div class="err">${esc(e.message)}</div></div>`; return; }
  renderUserMenu();
  Tabs.load();
  lastHash = location.hash;
  route();
}
(async function boot() {
  await Brand.load();
  try {
    App.user = (await api("GET", "api/me")).user;
  } catch { return showLogin(); }
  if (App.user.mustChange) return forcePassword();
  start();
})();

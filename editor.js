"use strict";
/* Edição sem código: documento (.md), fluxograma (.drawio), criação de playbook e times.
   Tudo grava pelo server.py, que guarda backup antes de sobrescrever. */
const Editor = (() => {
  const clone = o => JSON.parse(JSON.stringify(o));
  let cleanup = null;
  const E = { dirty: false };

  E.unmount = () => { if (cleanup) cleanup(); cleanup = null; };

  /* Cada editor montado registra seus ouvintes num AbortController; remontar (salvar, descartar,
     trocar de aba) aborta os anteriores. Antes, ouvintes antigos sobreviviam presos ao documento
     antigo e um Ctrl+S depois de "Descartar" regravava as alterações descartadas. */
  function mount() {
    E.unmount();
    const ac = new AbortController();
    cleanup = () => ac.abort();
    return { signal: ac.signal };
  }
  const normTxt = s => (s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").trim().toLowerCase();
  const GOV_ROWS = ["status", "aprovador", "ultimo revisor", "data de revisao", "versao"];
  const prodBanner = pb => pb.gov.status === "Produção"
    ? `<div class="notice prod">Este playbook está em <b>Produção</b>: ao salvar, as alterações ficam visíveis na hora para todos os perfis. Para uma revisão maior, volte-o antes para Homologação.</div>` : "";

  /* Adaptador: o que muda entre editar um playbook e editar um template (onde salvar, de onde recarregar,
     o que atualizar depois). Os editores de documento e de fluxograma são os mesmos. */
  /* a resposta traz "sync": o que o servidor mudou no outro lado (ramos criados, renomeados, removidos) */
  E.withSync = r => Object.assign(r.playbook || r.template, { _sync: r.sync || [] });
  const savedToast = (v, what) => {
    const s = v._sync || [];
    toast(s.length ? `${what} · ramos sincronizados: ${s.join(", ")}` : what);
  };
  E.playbookAdapter = pb => ({
    saveDoc: (doc, rev) => api("PUT", `api/pb/${pb.id}/doc`, { doc, rev }).then(E.withSync),
    saveFlow: (flow, refs, rev) => api("PUT", `api/pb/${pb.id}/flow`, { flow, refs, rev }).then(E.withSync),
    reload: () => api("GET", `api/pb/${pb.id}`).then(r => r.playbook),
    teams: pb.teams || {}, tplKey: pb.templateKey,
    after: v => { replacePlaybook(v); updateHeader(v); renderNav(); },
    banner: prodBanner(pb), fileBase: pb.id.toLowerCase(),
  });
  async function discard(el, pb, mountFn, what, ad) {
    if (E.dirty && !confirm(`Descartar todas as alterações ${what}?`)) return;
    try {
      const v = await ad.reload();      // recarrega do servidor: a tela volta a refletir o arquivo
      E.dirty = false; ad.after(v);
      mountFn(el, v); toast("Alterações descartadas");
    } catch (e) { toast(e.message, "err"); }
  }
  function saveError(err, el, pb, mountFn, ad) {
    if (err.status !== 409) return toast(err.message, "err");
    modal({ title: "Conflito de edição", html: `<p>${esc(err.message)}</p><p class="muted small">Suas alterações continuam na tela. Copie o que precisar antes de recarregar.</p>
      <div class="create-actions"><button class="btn ghost" data-k>Continuar editando</button><button class="btn primary" data-r>Recarregar versão atual</button></div>`,
      onMount: (b, close) => {
        b.querySelector("[data-k]").onclick = close;
        b.querySelector("[data-r]").onclick = async () => {
          close(); E.dirty = false;
          const v = await ad.reload(); ad.after(v); mountFn(el, v);
        };
      } });
  }
  /* ramos: "R3 · Nome" no documento ↔ caixa "R3 …" vinculada a R3 no fluxograma (ver ramos.py) */
  const PROTO = "{{ramo.n}}";
  const RAMO_SUB = /^R(\d+|\{\{\s*ramo\.n\s*\}\})\s*·\s*(.*)$/;
  const RAMO_NODE = /^R(\d+|\{\{\s*ramo\.n\s*\}\})(?:\s*[·:–-]\s*|\s+|$)(.*)$/;
  const ramoKey = k => /ramo\.n/.test(k) ? PROTO : String(+k);
  const refRamo = r => { const m = String(r).replace(/\s+/g, "").match(/^R(\d+|\{\{ramo\.n\}\})$/); return m ? ramoKey(m[1]) : null; };
  const RAMO_ROWS = ["Entrada", "Cenário", "O N1 verifica", "É sucesso quando", "Desfecho típico", "Contenção do SOC", "Contenção do CSIRT", "Saídas", "MITRE"];
  const nextRamo = keys => String(Math.max(0, ...keys.filter(k => k !== PROTO).map(Number)) + 1);
  const autosize = t => { t.style.height = "auto"; t.style.height = t.scrollHeight + 2 + "px"; };
  const markDirty = (bar) => { E.dirty = true; if (bar) bar.classList.add("dirty"); };

  /* ═════════════════════════ DOCUMENTO ═════════════════════════ */
  const BLOCK_NAMES = { p: "Parágrafo", ul: "Lista", table: "Tabela", quote: "Destaque" };
  const newBlock = t => t === "table" ? { t, head: ["Coluna 1", "Coluna 2"], rows: [["", ""]] } : t === "ul" ? { t, items: [""] } : { t, text: "" };

  E.docEditor = (el, pb, mkAd) => {
    mkAd = mkAd || E.playbookAdapter;
    const ad = mkAd(pb), remount = (e2, v) => E.docEditor(e2, v, mkAd);
    const sig = mount();
    const doc = clone(pb.doc);
    let lastTa = null;

    const ownerOf = path => {            // "s3" | "s3u1"
      const m = path.match(/^s(\d+)(?:u(\d+))?$/);
      const s = doc.sections[+m[1]];
      return m[2] !== undefined ? s.subs[+m[2]] : s;
    };
    const blockOf = (owner, k) => ownerOf(owner).blocks[+k];

    function blockHtml(b, owner, k, n) {
      const ctl = `<div class="blk-ctl"><span class="blk-type">${BLOCK_NAMES[b.t]}</span>
        <button data-act="blk-up" title="Subir" ${k === 0 ? "disabled" : ""}>↑</button><button data-act="blk-down" title="Descer" ${k === n - 1 ? "disabled" : ""}>↓</button>
        <button data-act="blk-del" title="Remover bloco" class="del">✕</button></div>`;
      const at = `data-o="${owner}" data-k="${k}"`;
      let body = "";
      const govSec = /^Propriedades/.test(ownerOf(owner).title || "");
      const locked = ri => govSec && GOV_ROWS.includes(normTxt((b.rows[ri] || [])[0]));
      const mitreRow = ri => govSec && normTxt((b.rows[ri] || [])[0]).startsWith("tatica mitre") && !/\{\{/.test((b.rows[ri] || [])[1] || "");
      if (b.t === "p" || b.t === "quote")
        body = `<textarea class="ta ${b.t === "quote" ? "quote" : ""}" data-f="text" rows="1" placeholder="${b.t === "quote" ? "Texto em destaque" : "Escreva o parágrafo…"}">${esc(b.text)}</textarea>`;
      else if (b.t === "ul")
        body = `<ul class="ed-list">${b.items.map((it, i) => {
          const m = it.match(/^\[( |x)\] (.*)$/s);
          return `<li>${m ? `<input type="checkbox" data-act="li-toggle" data-i="${i}" ${m[1] === "x" ? "checked" : ""} title="Marcar como concluído">` : `<span class="dot">•</span>`}
            <textarea class="ta" data-f="item" data-i="${i}" rows="1" placeholder="Item da lista">${esc(m ? m[2] : it)}</textarea>
            <button data-act="li-del" data-i="${i}" title="Remover item" class="x">✕</button></li>`;
        }).join("")}</ul><div class="row-btns"><button class="btn ghost xs" data-act="li-add">＋ Item</button><button class="btn ghost xs" data-act="li-check" title="Transforma a lista em checklist (ou desfaz)">☑ Checklist</button></div>`;
      else if (b.t === "table") {
        const nc = b.head.length;
        body = `<div class="ed-tw"><table class="ed-table"><thead>
          <tr class="colctl">${b.head.map((_, c) => `<th><button data-act="col-del" data-c="${c}" title="Remover coluna" ${nc < 2 ? "disabled" : ""}>✕</button></th>`).join("")}<th></th></tr>
          <tr>${b.head.map((h, c) => `<th><textarea class="ta th" data-f="head" data-c="${c}" rows="1">${esc(h)}</textarea></th>`).join("")}<th class="addcol"><button data-act="col-add" title="Adicionar coluna">＋</button></th></tr></thead>
          <tbody>${b.rows.map((r, ri) => `<tr class="${locked(ri) ? "locked" : ""}">${b.head.map((_, c) => `<td><textarea class="ta" data-f="cell" data-r="${ri}" data-c="${c}" rows="1" ${locked(ri) ? `readonly title="Controlado pelo ciclo de vida: muda com “Alterar status” e ao salvar (a versão é automática)"` : ""}>${esc(r[c] ?? "")}</textarea></td>`).join("")}
            <td class="rowctl">${mitreRow(ri) ? `<button data-act="mitre" data-r="${ri}" title="Escolher táticas do MITRE ATT&CK">🎯</button>` : ""}${locked(ri) ? `<span class="lock" title="Campo controlado pelo ciclo de vida">🔒</span>` : `<button data-act="row-up" data-r="${ri}" title="Subir linha" ${ri === 0 ? "disabled" : ""}>↑</button><button data-act="row-del" data-r="${ri}" title="Remover linha" class="x">✕</button>`}</td></tr>`).join("")}</tbody></table></div>
          <div class="row-btns"><button class="btn ghost xs" data-act="row-add">＋ Linha</button></div>`;
      }
      return `<div class="blk blk-${b.t}" ${at}>${ctl}${body}</div>`;
    }

    function addBar(owner, ctx) {
      let extra = "";
      if (ctx === "ramos") extra = `<button class="btn soft xs" data-act="ramo-add" data-o="${owner}">＋ Novo ramo</button><small class="muted sync-hint" title="Ao salvar, ramos criados, renomeados ou removidos aqui são aplicados no fluxograma e na aba Ramos">⇄ sincroniza com o fluxograma</small>`;
      if (ctx === "fases") extra = `<button class="btn soft xs" data-act="fase-add" data-o="${owner}">＋ Nova fase</button>`;
      return `<div class="addbar" data-o="${owner}"><span>Adicionar:</span>${Object.entries(BLOCK_NAMES).map(([t, n]) => `<button class="btn ghost xs" data-act="blk-add" data-t="${t}" data-o="${owner}">＋ ${n}</button>`).join("")}
        ${ctx !== "sub" ? `<button class="btn ghost xs" data-act="sub-add" data-o="${owner}">＋ Subseção</button>` : ""}${extra}</div>`;
    }

    function render() {
      const y = window.scrollY;
      el.innerHTML = `<div class="ed-bar" id="edbar"><div>${ad.docBar || `<b>Editando documento</b><span class="muted"> · as alterações viram o arquivo <code>.md</code> (backup automático a cada gravação)</span>`}</div>
          <div class="ed-actions"><span class="dirty-dot" title="Alterações não salvas"></span><button class="btn ghost" id="bold" title="Negrito na seleção (Ctrl+B)"><b>N</b> negrito</button>
          <button class="btn ghost" id="discard">Descartar</button><button class="btn primary" id="save">Salvar documento</button></div></div>
        ${ad.banner}
        <div class="ed-grid"><nav class="toc ed-toc">${doc.sections.map((s, i) => `<a href="#" data-go="${i}">${esc(s.title || "(sem título)")}</a>`).join("")}
          <button class="btn ghost xs" data-act="sec-add" data-i="${doc.sections.length - 1}" style="margin-top:8px">＋ Seção</button>
          ${doc.sections.some(isRamoSec) ? "" : `<button class="btn soft xs" data-act="ramos-sec" style="margin-top:6px" title="Cria a seção “Ramos em detalhe” com o primeiro ramo">＋ Seção de ramos</button>`}</nav>
        <div class="ed-doc">
          <div class="ecard head"><label>Título do playbook<input class="in big" data-f="title" value="${esc(doc.title)}"></label>
            <label>Linha de versão / autor<input class="in" data-f="byline" value="${esc(doc.byline)}"></label></div>
          ${doc.sections.map((s, i) => {
            const ctx = isRamoSec(s) ? "ramos" : /^Fluxo de resposta/.test(s.title) ? "fases" : "sec";
            return `<div class="ecard sec" id="esec-${i}" data-o="s${i}">
              <div class="sec-head"><input class="in h2" data-f="stitle" data-o="s${i}" value="${esc(s.title)}" placeholder="Título da seção">
                <div class="blk-ctl"><button data-act="sec-up" data-i="${i}" ${i === 0 ? "disabled" : ""} title="Subir seção">↑</button><button data-act="sec-down" data-i="${i}" ${i === doc.sections.length - 1 ? "disabled" : ""} title="Descer seção">↓</button>
                <button data-act="sec-del" data-i="${i}" class="del" title="Remover seção">✕</button></div></div>
              ${s.blocks.map((b, k) => blockHtml(b, `s${i}`, k, s.blocks.length)).join("")}
              ${addBar(`s${i}`, ctx)}
              ${s.subs.map((u, j) => `<div class="sub" data-o="s${i}u${j}"><div class="sec-head"><input class="in h3" data-f="stitle" data-o="s${i}u${j}" value="${esc(u.title)}" placeholder="Título da subseção">
                <div class="blk-ctl"><button data-act="sub-up" data-o="s${i}u${j}" ${j === 0 ? "disabled" : ""}>↑</button><button data-act="sub-down" data-o="s${i}u${j}" ${j === s.subs.length - 1 ? "disabled" : ""}>↓</button>
                <button data-act="sub-del" data-o="s${i}u${j}" class="del" title="Remover subseção">✕</button></div></div>
                ${u.blocks.map((b, k) => blockHtml(b, `s${i}u${j}`, k, u.blocks.length)).join("")}${addBar(`s${i}u${j}`, "sub")}</div>`).join("")}
              <div class="sec-after"><button class="btn ghost xs" data-act="sec-add" data-i="${i}">＋ Seção abaixo</button></div></div>`;
          }).join("")}
        </div></div>`;
      el.querySelectorAll("textarea").forEach(autosize);
      if (E.dirty) $("#edbar").classList.add("dirty");
      window.scrollTo(0, y);
    }

    const isRamoSec = s => /^ramos/i.test(s.title.trim()) || s.subs.some(u => RAMO_SUB.test(u.title.trim()));
    const ramoKeys = () => doc.sections.flatMap(s => s.subs.map(u => (u.title.trim().match(RAMO_SUB) || [])[1]).filter(Boolean).map(ramoKey));
    function newRamoSub(sec) {
      const keys = ramoKeys();
      let k;
      if (pb.template) {
        if (keys.includes(PROTO)) { toast("O template já tem o ramo-modelo R{{ramo.n}}: ele é repetido para cada ramo informado na criação do playbook", "warn"); return null; }
        k = PROTO;
      } else k = nextRamo(keys);
      const proto = doc.sections.flatMap(x => x.subs).find(u => RAMO_SUB.test(u.title.trim()));
      const blocks = proto ? clone(proto.blocks).map(b => b.t === "table" ? { ...b, rows: b.rows.map(r => [r[0]].concat(r.slice(1).map(() => ""))) } : b.t === "ul" ? { ...b, items: [""] } : { ...b, text: "" })
        : [{ t: "table", head: ["Item", "Conteúdo"], rows: RAMO_ROWS.map(x => [x, ""]) }];
      if (k === PROTO) blocks.forEach(b => { if (b.t === "table") b.rows.forEach(r => { if (normTxt(r[0]).startsWith("e sucesso quando")) r[1] = "{{ramo.pergunta}}"; }); });
      sec.subs.push({ title: `R${k} · ${k === PROTO ? "{{ramo.nome}}" : "Novo ramo"}`, blocks });
      return k;
    }
    const nextId = (rows) => {
      for (let i = rows.length - 1; i >= 0; i--) {
        const m = String(rows[i][0] || "").match(/^([A-Z]+)(\d+)$/);
        if (m) return m[1] + (+m[2] + 1);
      }
      return "";
    };

    function act(btn) {
      const a = btn.dataset.act, blk = btn.closest(".blk");
      const owner = btn.dataset.o || (blk && blk.dataset.o);
      const k = blk ? +blk.dataset.k : -1;
      const b = blk ? blockOf(blk.dataset.o, k) : null;
      const swap = (arr, i, j) => { [arr[i], arr[j]] = [arr[j], arr[i]]; };
      const i = +btn.dataset.i;
      switch (a) {
        case "sec-add": doc.sections.splice(i + 1, 0, { title: "Nova seção", blocks: [{ t: "p", text: "" }], subs: [] }); break;
        case "sec-up": swap(doc.sections, i, i - 1); break;
        case "sec-down": swap(doc.sections, i, i + 1); break;
        case "sec-del": if (!confirm(`Remover a seção "${doc.sections[i].title}" e todo o conteúdo dela?`)) return; doc.sections.splice(i, 1); break;
        case "sub-add": ownerOf(owner).subs.push({ title: "Nova subseção", blocks: [{ t: "p", text: "" }] }); break;
        case "sub-up": case "sub-down": case "sub-del": {
          const m = owner.match(/^s(\d+)u(\d+)$/), subs = doc.sections[+m[1]].subs, j = +m[2];
          if (a === "sub-del") {
            const rm = subs[j].title.trim().match(RAMO_SUB);
            if (!confirm(rm ? `Remover o ramo "${subs[j].title}"?\n\nAo salvar, a caixa R${ramoKey(rm[1])} também sai do fluxograma.` : `Remover a subseção "${subs[j].title}"?`)) return;
            subs.splice(j, 1);
          }
          else swap(subs, j, a === "sub-up" ? j - 1 : j + 1);
          break;
        }
        case "ramo-add": if (!newRamoSub(ownerOf(owner))) return; break;
        case "ramos-sec": {
          const sec = { title: "Ramos em detalhe", blocks: [{ t: "p", text: "Cada ramo descreve o cenário, o que conta como sucesso e a contenção de cada time." }], subs: [] };
          const at = doc.sections.findIndex(x => /^Fluxo de resposta/.test(x.title));
          doc.sections.splice(at >= 0 ? at + 1 : doc.sections.length, 0, sec);
          newRamoSub(sec);
          break;
        }
        case "fase-add": {
          const subs = ownerOf(owner).subs;
          subs.push({ title: `Fase ${subs.length + 1} · Nova fase — CSIRT`, blocks: [{ t: "table", head: ["ID", "Ação", "Critério de saída"], rows: [["", "", ""]] }] });
          break;
        }
        case "blk-add": ownerOf(owner).blocks.push(newBlock(btn.dataset.t)); break;
        case "blk-up": swap(ownerOf(owner).blocks, k, k - 1); break;
        case "blk-down": swap(ownerOf(owner).blocks, k, k + 1); break;
        case "blk-del": if (!confirm("Remover este bloco?")) return; ownerOf(owner).blocks.splice(k, 1); break;
        case "li-add": b.items.push(b.items.some(x => /^\[( |x)\] /.test(x)) ? "[ ] " : ""); break;
        case "li-del": b.items.splice(+btn.dataset.i, 1); if (!b.items.length) b.items.push(""); break;
        case "li-check": {
          const isChk = b.items.every(x => /^\[( |x)\] /.test(x));
          b.items = b.items.map(x => isChk ? x.replace(/^\[( |x)\] /, "") : "[ ] " + x);
          break;
        }
        case "li-toggle": { const it = b.items[+btn.dataset.i]; b.items[+btn.dataset.i] = it.replace(/^\[( |x)\]/, btn.checked ? "[x]" : "[ ]"); break; }
        case "mitre": {
          const r = +btn.dataset.r;
          MitrePicker.dialog(b.rows[r][1] || "", txt => { b.rows[r][1] = txt; markDirty($("#edbar")); render(); });
          return;
        }
        case "row-add": b.rows.push(b.head.map((_, c) => c === 0 && b.head[0] === "ID" ? nextId(b.rows) : "")); break;
        case "row-del": if (b.rows.length > 1 || confirm("Remover a última linha?")) b.rows.splice(+btn.dataset.r, 1); break;
        case "row-up": swap(b.rows, +btn.dataset.r, +btn.dataset.r - 1); break;
        case "col-add": b.head.push("Nova coluna"); b.rows.forEach(r => r.push("")); break;
        case "col-del": { const c = +btn.dataset.c; if (!confirm(`Remover a coluna "${b.head[c]}"?`)) return; b.head.splice(c, 1); b.rows.forEach(r => r.splice(c, 1)); break; }
        default: return;
      }
      markDirty($("#edbar")); render();
    }

    function onInput(e) {
      const t = e.target, f = t.dataset.f;
      if (!f) return;
      if (t.tagName === "TEXTAREA") autosize(t);
      if (f === "title") doc.title = t.value;
      else if (f === "byline") doc.byline = t.value;
      else if (f === "stitle") ownerOf(t.dataset.o).title = t.value;
      else {
        const blk = t.closest(".blk"), b = blockOf(blk.dataset.o, blk.dataset.k);
        if (f === "text") b.text = t.value;
        else if (f === "item") { const i = +t.dataset.i, m = b.items[i].match(/^\[( |x)\] /); b.items[i] = (m ? m[0] : "") + t.value.replace(/\n/g, " "); }
        else if (f === "head") b.head[+t.dataset.c] = t.value.replace(/\n/g, " ");
        else if (f === "cell") b.rows[+t.dataset.r][+t.dataset.c] = t.value.replace(/\n/g, " ");
      }
      markDirty($("#edbar"));
      if (f === "stitle") { const a = el.querySelectorAll(".ed-toc a"); const m = t.dataset.o.match(/^s(\d+)$/); if (m && a[+m[1]]) a[+m[1]].textContent = t.value; }
    }

    function bold() {
      const t = lastTa; if (!t || !document.contains(t)) return toast("Clique no texto e selecione o trecho primeiro", "warn");
      const { selectionStart: a, selectionEnd: b, value: v } = t;
      if (a === b) return toast("Selecione o trecho que deve ficar em negrito", "warn");
      const sel = v.slice(a, b);
      const out = /^\*\*.*\*\*$/s.test(sel) ? sel.slice(2, -2) : `**${sel}**`;
      t.value = v.slice(0, a) + out + v.slice(b);
      t.setSelectionRange(a, a + out.length); t.focus();
      onInput({ target: t });
    }

    async function save() {
      if (!doc.title.trim()) return toast("O título não pode ficar vazio", "err");
      const btn = $("#save"); btn.disabled = true; btn.textContent = "Salvando…";
      try {
        const v = await ad.saveDoc(doc, pb.rev);
        E.dirty = false; savedToast(v, "Documento salvo");
        ad.after(v); remount(el, v);
      } catch (err) { saveError(err, el, pb, remount, ad); btn.disabled = false; btn.textContent = "Salvar documento"; }
    }

    render();
    el.addEventListener("input", onInput, sig);
    el.addEventListener("focusin", e => { if (e.target.tagName === "TEXTAREA") lastTa = e.target; }, sig);
    el.addEventListener("click", e => {
      const go = e.target.closest("[data-go]");
      if (go) { e.preventDefault(); document.getElementById("esec-" + go.dataset.go).scrollIntoView({ block: "start" }); return; }
      if (e.target.id === "save") return save();
      if (e.target.closest("#bold")) return bold();
      if (e.target.id === "discard") return discard(el, pb, remount, "do documento", ad);
      const btn = e.target.closest("[data-act]");
      if (btn && btn.dataset.act !== "li-toggle") act(btn);
    }, sig);
    el.addEventListener("change", e => { if (e.target.dataset.act === "li-toggle") act(e.target); }, sig);
    const key = e => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b" && document.activeElement.tagName === "TEXTAREA") { e.preventDefault(); bold(); }
    };
    document.addEventListener("keydown", key, sig);
  };

  /* ═════════════════════════ FLUXOGRAMA ═════════════════════════ */
  const PRESETS = [
    { key: "start", type: "start", name: "Início", desc: "Entrada do fluxo (alerta)", lines: [["Alerta", "n"]] },
    { key: "action", type: "action", name: "Ação", desc: "Tarefa executada pelo time", lines: [["Nova ação", "b"], ["detalhe", "m"]] },
    { key: "ramo", type: "action", name: "Ramo", desc: "Caixa de ramo R1, R2…", w: 110, h: 92, ramo: true },
    { key: "decision", type: "decision", name: "Decisão", desc: "Pergunta com saídas sim/não", lines: [["Pergunta?", "n"]] },
    { key: "close", type: "close", name: "Encerramento", desc: "Caso encerrado na fila", lines: [["Encerrar no N1", "b"], ["registro no caso", "m"]] },
    { key: "neutral", type: "neutral", name: "Vínculo / descarte", desc: "Duplicado, descartado", lines: [["Vincular ao", "n"], ["caso aberto", "n"]] },
    { key: "attention", type: "attention", name: "Ponto de atenção", desc: "Validar antes de executar", lines: [["Ponto de atenção", "b"], ["validar antes de executar", "n"]] },
    { key: "crossref", type: "crossref", name: "Outro playbook", desc: "Referência a PB-xx", lines: [["Segue ao PB-00", "b"], ["motivo", "m"]] },
    { key: "support", type: "support", name: "Time de apoio", desc: "Times de apoio do template", lines: [["DFIR", "n"]], team: "DFIR" },
  ];
  const supportLabel = t => [[t, "n"]];
  const SIDES = { auto: null, top: { x: .5, y: 0 }, right: { x: 1, y: .5 }, bottom: { x: .5, y: 1 }, left: { x: 0, y: .5 } };
  const SIDE_NAMES = { auto: "Automático", top: "Topo", right: "Direita", bottom: "Base", left: "Esquerda" };
  const sideKey = p => !p ? "auto" : (Object.entries(SIDES).find(([k, v]) => v && v.x === p.x && v.y === p.y) || ["custom"])[0];
  const mkLines = arr => arr.map(([t, s]) => ({ t, s }));
  const snap = v => Math.round(v / 8) * 8;

  function presetSvg(p) {
    const t = App.data.catalog.nodeTypes[p.type];
    const w = 44, h = p.type === "decision" ? 28 : 24;
    const base = `fill="${t.fill}" stroke="${t.stroke}" stroke-width="${Math.min(t.sw, 1.6)}" ${t.dashed ? 'stroke-dasharray="3 2"' : ""}`;
    const body = t.shape === "rhombus" ? `<polygon ${base} points="${w / 2},1 ${w - 1},${h / 2} ${w / 2},${h - 1} 1,${h / 2}"/>` :
      `<rect ${base} x="1" y="1" width="${w - 2}" height="${h - 2}" rx="${t.shape === "pill" ? h / 2 : 4}"/>`;
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${body}${p.ramo ? `<text x="${w / 2}" y="${h / 2 + 4}" font-size="10" font-weight="700" text-anchor="middle" fill="#333">R</text>` : ""}</svg>`;
  }

  E.flowEditor = (el, pb, mkAd) => {
    mkAd = mkAd || E.playbookAdapter;
    const ad = mkAd(pb), remount = (e2, v) => E.flowEditor(e2, v, mkAd);
    const sig = mount();
    const CAT = App.data.catalog;
    let flow = clone(pb.flow), refs = clone(pb.refs || {});
    let sel = null, mode = null, zoomF = 1, drag = null, autoFit = true;
    let multi = new Set();               // seleção múltipla (Shift/Ctrl+clique, laço, Ctrl+A)
    /* times oferecidos: os do template (do playbook ou o próprio template em edição); os de outros
       templates aparecem à parte e entram no template ao salvar */
    const OWN = ad.teams || TEAMS;
    const others = cat => ad.teams ? Object.keys(TEAMS).filter(t => !(t in OWN) && (cat === "central" ? TEAMS[t].category === "central" : TEAMS[t].category !== "central")) : [];
    const supportTeams = () => Object.keys(OWN).filter(t => (OWN[t].category || "apoio") !== "central");
    const teamInfo = t => OWN[t] || TEAMS[t] || {};
    const undo = [], redo = [];
    let lastSnapKey = "", lastSnapAt = 0;

    const state = () => JSON.stringify({ flow, refs });
    function snapUndo(key = "") {
      const now = Date.now();
      if (key && key === lastSnapKey && now - lastSnapAt < 1200) { lastSnapAt = now; return; }
      lastSnapKey = key; lastSnapAt = now;
      undo.push(state()); if (undo.length > 100) undo.shift();
      redo.length = 0;
      markDirty($("#fbar"));
    }
    function restore(s) {
      const o = JSON.parse(s); flow = o.flow; refs = o.refs;
      multi = new Set([...multi].filter(id => nodeById(id)));
      if (sel && sel.kind === "multi" && multi.size < 2) sel = multi.size ? { kind: "node", id: [...multi][0] } : null;
      if (sel && sel.kind !== "multi" && !findSel()) sel = null;
      draw(); props();
    }
    const doUndo = () => { if (!undo.length) return; redo.push(state()); restore(undo.pop()); markDirty($("#fbar")); };
    const doRedo = () => { if (!redo.length) return; undo.push(state()); restore(redo.pop()); markDirty($("#fbar")); };

    const nodeById = id => flow.nodes.find(n => n.id === id);
    const edgeById = id => flow.edges.find(e => e.id === id);
    const findSel = () => sel && (sel.kind === "node" ? nodeById(sel.id) : sel.kind === "edge" ? edgeById(sel.id) : null);
    const selectNode = id => { sel = { kind: "node", id }; multi = new Set([id]); };
    const selectEdge = id => { sel = { kind: "edge", id }; multi = new Set(); };
    const clearSel = () => { sel = null; multi = new Set(); };
    function setMulti(ids) {
      multi = new Set(ids);
      sel = multi.size > 1 ? { kind: "multi" } : multi.size ? { kind: "node", id: [...multi][0] } : null;
    }
    /* ramos no fluxograma: chave → caixa (texto começa com R3 e a caixa está vinculada a R3) */
    function flowRamos() {
      const out = {};
      for (const n of flow.nodes) {
        const m = ((n.lines[0] || {}).t || "").trim().match(RAMO_NODE); if (!m) continue;
        const k = ramoKey(m[1]);
        if (!out[k] && (refs[n.id] || []).some(r => refRamo(r) === k)) out[k] = n;
      }
      return out;
    }
    const ramoOf = n => { const fr = flowRamos(); return Object.keys(fr).find(k => fr[k] === n) || null; };
    function uid(prefix) {
      const used = new Set(flow.nodes.map(n => n.id).concat(flow.edges.map(e => e.id)));
      let i = 1; while (used.has(prefix + i)) i++;
      return prefix + i;
    }

    el.innerHTML = `<div class="ed-bar fe-bar" id="fbar"><div>${ad.flowBar || `<b>Editando fluxograma</b><span class="muted"> · formas, cores e raias seguem o modelo dos playbooks; grava o <code>.drawio</code> (página 2 preservada)</span>`}</div>
      <div class="ed-actions"><span class="dirty-dot" title="Alterações não salvas"></span>
        <button class="btn ghost" id="fundo" title="Desfazer (Ctrl+Z)">↶</button><button class="btn ghost" id="fredo" title="Refazer (Ctrl+Shift+Z)">↷</button>
        <button class="btn ghost" id="fall" title="Selecionar todas as caixas (Ctrl+A) para mover ou redimensionar juntas">⬚ Tudo</button>
        <span class="sep"></span><button class="btn ghost" data-z="-1">−</button><button class="btn ghost" data-z="0" title="Ajustar">⤢</button><button class="btn ghost" data-z="1">+</button>
        <span class="sep"></span><button class="btn ghost" id="fdiscard">Descartar</button><button class="btn primary" id="fsave">Salvar fluxograma</button></div></div>
      <div class="fe-grid">
        <aside class="fe-pal"><div class="pal-title">Formas do modelo</div>
          ${PRESETS.map(p => `<div class="pal-item" data-preset="${p.key}" title="Clique e depois clique no fluxograma, ou arraste até a raia">${presetSvg(p)}<div><b>${p.name}</b><small>${p.desc}</small></div></div>`).join("")}
          <div class="pal-title" style="margin-top:14px">Setas</div>
          <div class="pal-help">Selecione uma caixa e arraste o círculo <b>→</b> até a caixa de destino. O tipo da seta é sugerido pelas raias (handoff, escalonamento, apoio).</div>
          ${Object.values(CAT.edgeTypes).map(t => `<div class="pal-edge"><i style="border-top:${t.sw + .5}px ${t.dashed ? "dashed" : "solid"} ${t.color}"></i>${t.label}</div>`).join("")}
        </aside>
        <div class="fe-main"><div class="fe-modes"><button class="on" data-mode="visual">◧ Visual</button><button data-mode="code" title="Editar o fluxo como texto (Mermaid)">&lt;/&gt; Código</button></div>
          <div class="fe-status" id="fstatus"></div><div class="flowbox fe-canvas" id="fcanvas"></div></div>
        <aside class="fe-props" id="fprops"></aside>
      </div>`;
    const canvas = $("#fcanvas"), propsEl = $("#fprops"), status = $("#fstatus");
    let svgEl = null, vb = null, lay = null;

    function setStatus(t) { status.innerHTML = t || ""; status.hidden = !t; }
    function setMode(m) {
      mode = m;
      el.querySelectorAll(".pal-item").forEach(p => p.classList.toggle("on", !!(m && m.preset === p.dataset.preset)));
      canvas.classList.toggle("adding", !!m);
      if (!m) setStatus("");
      else if (m.kind === "add") setStatus(`Clique na raia do time onde a caixa <b>${PRESETS.find(p => p.key === m.preset).name}</b> deve ficar · <kbd>Esc</kbd> cancela`);
      else if (m.kind === "connect") setStatus(`Clique na caixa de destino da seta · <kbd>Esc</kbd> cancela`);
    }

    function badges() {
      const out = {};
      for (const n of flow.nodes) { const r = refs[n.id] || []; if (r.length) out[n.id] = r.length <= 2 ? r.map(x => x.replace(/^sec:.*/, "§")).join(" ") : r[0] + "…+" + (r.length - 1); }
      return out;
    }
    function draw() {
      const r = Flow.svg(flow, { editor: true, sel, multi, badges: badges() });
      vb = r.vb; lay = r.lay;
      canvas.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${vb.join(" ")}" width="${vb[2] * zoomF}" height="${vb[3] * zoomF}">${r.svg}<g id="temp" pointer-events="none"></g></svg>`;
      svgEl = $("svg", canvas);
      $("#fundo").disabled = !undo.length; $("#fredo").disabled = !redo.length;
    }
    const fit = () => { autoFit = true; zoomF = Math.min(1.3, Math.max(.5, (canvas.clientWidth - 8) / vb[2])); draw(); };
    const onResize = () => { if (autoFit) fit(); };
    function pt(ev) {
      const p = svgEl.createSVGPoint(); p.x = ev.clientX; p.y = ev.clientY;
      return p.matrixTransform(svgEl.getScreenCTM().inverse());
    }
    function laneAt(y) {
      for (const l of lay.lanes) if (y >= l.y && y <= l.y + l.h + CAT.layout.gap) return l;
      return y < lay.lanes[0].y ? lay.lanes[0] : lay.lanes[lay.lanes.length - 1];
    }
    const minX = CAT.layout.start + 8;

    function addNode(presetKey, p) {
      const pr = PRESETS.find(x => x.key === presetKey), t = CAT.nodeTypes[pr.type];
      const w = pr.w || t.w, h = pr.h || t.h;
      const lane = laneAt(p.y);
      if (pr.ramo) return addRamo(p, lane, w, h);
      const lines = mkLines(pr.lines);
      snapUndo();
      const id = uid(pr.type === "support" ? "apoio" : pr.type);
      const node = { id, lane: lane.key, x: Math.max(minX, snap(p.x - lane.x - w / 2)), y: Math.max(8, snap(p.y - lane.y - h / 2)), w, h, type: pr.type, lines };
      if (pr.type === "support") { const t = supportTeams().includes(pr.team) ? pr.team : supportTeams()[0]; node.team = t || null; if (t) node.lines = mkLines(supportLabel(t)); }
      flow.nodes.push(node);
      selectNode(id);
      setMode(null); draw(); props();
    }

    /* Novo ramo: ganha o próximo número e o vínculo R#. Havendo outros ramos, fica ao lado do último e
       copia as ligações dele. Ao salvar, o servidor cria a subseção no documento. */
    function addRamo(p, lane, w, h) {
      const fr = flowRamos();
      let k;
      if (pb.template) {
        if (fr[PROTO]) { setMode(null); return toast("O template já tem a caixa-modelo de ramo: ela é repetida lado a lado para cada ramo na criação do playbook", "warn"); }
        k = PROTO;
      } else {
        const keys = Object.keys(fr).concat(Object.values(refs).flat().map(refRamo).filter(Boolean), (pb.ramos || []).map(r => refRamo(r.id)).filter(Boolean));
        k = nextRamo(keys);
      }
      snapUndo();
      const lines = k === PROTO ? mkLines([["R{{ramo.n}} {{ramo.nome}}", "b"], ["{{ramo.pergunta}}", "m"]]) : mkLines([[`R${k} Novo ramo`, "b"], ["Indicador de sucesso?", "m"]]);
      const id = uid("r");
      const order = flow.lanes.map(l => l.key);
      const have = Object.values(fr).sort((a, b) => (order.indexOf(a.lane) - order.indexOf(b.lane)) || (a.x - b.x));
      const last = have[have.length - 1];
      if (last) {
        const dx = last.w + 10;
        flow.nodes.push({ ...clone(last), id, x: last.x + dx, lines, team: undefined });
        for (const e of flow.edges.filter(e => e.from === last.id || e.to === last.id)) {
          const c = clone(e); c.id = uid("e");
          if (c.from === last.id) c.from = id; if (c.to === last.id) c.to = id;
          c.wps = (e.wps || []).map(wp => wp.lane === last.lane && wp.x >= last.x && wp.x <= last.x + last.w ? { ...wp, x: wp.x + dx } : wp);
          flow.edges.push(c);
        }
      } else {
        flow.nodes.push({ id, lane: lane.key, x: Math.max(minX, snap(p.x - lane.x - w / 2)), y: Math.max(8, snap(p.y - lane.y - h / 2)), w, h, type: "action", lines });
        const dec = flow.nodes.find(n => n.type === "decision" && /ramo/i.test(n.lines.map(l => l.t).join(" ")));
        if (dec) flow.edges.push({ id: uid("e"), from: dec.id, to: id, label: "", type: "flow", exit: null, entry: null, wps: [] });
      }
      refs[id] = ["R" + k];
      selectNode(id);
      setMode(null); draw(); props();
      toast(`R${k} criado${last ? " ao lado do último ramo, com as mesmas ligações" : ""}. Ao salvar, ele entra no documento e na aba Ramos.`);
    }

    function suggestEdgeType(a, b) {
      const la = flow.lanes.find(l => l.key === a.lane) || {}, lb = flow.lanes.find(l => l.key === b.lane) || {};
      const ia = flow.lanes.indexOf(la), ib = flow.lanes.indexOf(lb);
      if (b.type === "crossref") return "crossref";
      if (lb.kind === "support" || b.type === "support") return "support";
      if (ib > ia && lb.team === "CSIRT") return "escalation";
      if (ib > ia) return "handoff";
      return "flow";
    }
    function connect(fromId, toId) {
      if (fromId === toId) return;
      const a = nodeById(fromId), b = nodeById(toId);
      if (flow.edges.some(e => e.from === fromId && e.to === toId)) return toast("Essas caixas já estão ligadas", "warn");
      snapUndo();
      const id = uid("e");
      const type = suggestEdgeType(a, b);
      flow.edges.push({ id, from: fromId, to: toId, label: type === "handoff" ? "handoff" : "", type, exit: null, entry: null, wps: [] });
      selectEdge(id);
      draw(); props();
    }
    function freeEdges(nodeId) {
      for (const e of flow.edges) if (e.from === nodeId || e.to === nodeId) { e.wps = []; e.exit = null; e.entry = null; }
    }
    function deleteSel() {
      if (!sel) return;
      if (sel.kind === "edge") { snapUndo(); flow.edges = flow.edges.filter(e => e.id !== sel.id); clearSel(); draw(); props(); return; }
      const ids = sel.kind === "multi" ? [...multi] : [sel.id];
      const rs = ids.map(id => ramoOf(nodeById(id))).filter(Boolean).map(k => "R" + k);
      const msg = (ids.length > 1 ? `Excluir ${ids.length} caixas?` : "") + (rs.length ? `${ids.length > 1 ? "\n\n" : ""}${rs.join(", ")} ${rs.length > 1 ? "são ramos e também saem" : "é ramo e também sai"} da documentação (subseção de detalhe) ao salvar. Excluir?` : "");
      if (msg && !confirm(msg)) return;
      snapUndo();
      const S = new Set(ids);
      flow.nodes = flow.nodes.filter(n => !S.has(n.id));
      flow.edges = flow.edges.filter(e => !S.has(e.from) && !S.has(e.to));
      ids.forEach(id => delete refs[id]);
      clearSel(); draw(); props();
    }
    function duplicate() {
      const n = sel && sel.kind === "node" && nodeById(sel.id); if (!n) return;
      snapUndo();
      const c = clone(n); c.id = uid(n.type === "support" ? "apoio" : n.type); c.x += 16; c.y += 16;
      flow.nodes.push(c); selectNode(c.id); draw(); props();
    }

    /* ── propriedades ── */
    function refOptions(current) {
      const opt = (v, l) => current.includes(v) ? "" : `<option value="${esc(v)}">${esc(l)}</option>`;
      let h = `<option value="">＋ Vincular ao documento…</option>`;
      const phases = [...new Set(pb.steps.map(s => s.phase))];
      for (const ph of phases) h += `<optgroup label="${esc(ph)}">${pb.steps.filter(s => s.phase === ph).map(s => opt(s.id, `${s.id} · ${s.action.slice(0, 60)}`)).join("")}</optgroup>`;
      if (pb.ramos.length) h += `<optgroup label="Ramos">${pb.ramos.map(r => opt(r.id, r.title)).join("")}</optgroup>`;
      if (pb.states.length) h += `<optgroup label="Estados da triagem">${pb.states.map(s => opt(s.id, `${s.id} · ${s.name}`)).join("")}</optgroup>`;
      h += `<optgroup label="Seções inteiras">${pb.sections.map(s => opt("sec:" + s.id, s.title)).join("")}</optgroup>`;
      return h;
    }
    const refLabel = r => r.startsWith("sec:") ? "§ " + ((pb.sections.find(s => "sec:" + s.id === r) || {}).title || r.slice(4)) : r;

    function props() {
      if (sel && sel.kind === "multi") return propsMulti();
      const s = findSel();
      if (!s) {
        const orphan = flow.nodes.filter(n => n.type !== "support" && !(refs[n.id] || []).length).length;
        const usedTeams = new Set(flow.lanes.map(l => l.team).filter(Boolean));
        const hasSupport = flow.lanes.some(l => l.kind === "support");
        const addable = Object.keys(OWN).filter(t => OWN[t].category === "central" && !usedTeams.has(t));
        const more = others("central").filter(t => !usedTeams.has(t));
        propsEl.innerHTML = `<div class="pp-title">Fluxograma</div>
          <label>Subtítulo (aparece no topo do .drawio)<textarea class="in" rows="2" data-p="subtitle">${esc(flow.subtitle || "")}</textarea></label>
          <div class="pp-lbl">Raias (times do fluxo)</div>
          <div class="lanes-list">${flow.lanes.map((l, i) => {
            const cnt = flow.nodes.filter(n => n.lane === l.key).length;
            return `<div class="lane-row"><i style="background:${esc(l.color)}"></i><b title="${esc(l.label)}">${esc(l.label)}</b><small>${cnt}</small>
              <button data-lup="${i}" ${i === 0 ? "disabled" : ""} title="Subir">↑</button><button data-ldown="${i}" ${i === flow.lanes.length - 1 ? "disabled" : ""} title="Descer">↓</button>
              <button class="del" data-ldel="${i}" title="${cnt ? "Mova ou exclua as caixas antes" : "Remover raia"}">✕</button></div>`;
          }).join("")}</div>
          <select class="in" data-addlane><option value="">＋ Adicionar raia…</option>${addable.map(t => `<option value="team:${esc(t)}">${esc(t)}</option>`).join("")}${more.length ? `<optgroup label="De outros templates (entra no template ao salvar)">${more.map(t => `<option value="team:${esc(t)}">${esc(t)}</option>`).join("")}</optgroup>` : ""}${hasSupport ? "" : `<option value="support">${esc(CAT.supportLaneLabel)}</option>`}<option value="new">Novo time central…</option></select>
          <div class="pp-stats"><div><b>${flow.nodes.length}</b> caixas</div><div><b>${flow.edges.length}</b> setas</div><div class="${orphan ? "warn" : ""}"><b>${orphan}</b> sem vínculo</div></div>
          <div class="pp-help"><b>Como montar</b><ol>
            <li>Escolha uma forma à esquerda e clique na raia do time responsável.</li>
            <li>Arraste a caixa para outra raia para trocar o time. As raias crescem e encolhem sozinhas.</li>
            <li>Selecione a caixa e arraste o <b>→</b> até o destino para criar a seta.</li>
            <li>Vincule a caixa aos passos (T0, A3…) ou ramos. É isso que o analista lê ao clicar.</li>
            <li>A forma <b>Ramo</b> cria R1, R2…; ao salvar, o ramo aparece no documento e na aba Ramos (e vice-versa).</li>
            <li>Arraste o texto de uma seta (sim, não…) para reposicioná-lo.</li></ol>
            <p><kbd>Shift</kbd>+clique ou arrastar no fundo seleciona várias caixas · <kbd>Ctrl+A</kbd> seleciona tudo · o quadrado no canto da seleção redimensiona proporcionalmente</p>
            <p><kbd>Del</kbd> exclui · <kbd>Ctrl+D</kbd> duplica · setas do teclado movem · <kbd>Ctrl+Z</kbd> desfaz</p></div>`;
        return;
      }
      if (sel.kind === "node") {
        const n = s, r = refs[n.id] || [];
        propsEl.innerHTML = `<div class="pp-title">Caixa <code>${esc(n.id)}</code></div>
          <label>Forma<select class="in" data-p="type">${Object.entries(CAT.nodeTypes).map(([k, t]) => `<option value="${k}" ${k === n.type ? "selected" : ""}>${t.label}</option>`).join("")}</select></label>
          <label>Time responsável (raia)<select class="in" data-p="lane">${flow.lanes.map(l => `<option value="${esc(l.key)}" ${l.key === n.lane ? "selected" : ""}>${esc(l.label)}</option>`).join("")}</select></label>
          ${n.type === "support" ? `<label>Time de apoio<select class="in" data-p="team"><option value="">(nenhum)</option>${supportTeams().map(t => `<option ${t === n.team ? "selected" : ""}>${esc(t)}</option>`).join("")}${others("apoio").length ? `<optgroup label="De outros templates (entra no template ao salvar)">${others("apoio").map(t => `<option ${t === n.team ? "selected" : ""}>${esc(t)}</option>`).join("")}</optgroup>` : ""}</select></label>` : ""}
          ${ramoOf(n) ? `<div class="notice ramo-note">Ramo <b>R${esc(ramoOf(n))}</b>: o texto da 1ª linha (depois de R${esc(ramoOf(n))}) é o nome; a linha cinza é o indicador de sucesso. Ao salvar, o documento e a aba Ramos acompanham.</div>` : ""}
          <div class="pp-lbl">Texto da caixa</div>
          <div class="lines">${n.lines.map((l, i) => `<div class="line"><button class="x up" data-upline="${i}" title="Subir linha" ${i === 0 ? "disabled" : ""}>↑</button><input class="in" data-line="${i}" value="${esc(l.t)}">
            <div class="seg" role="group">${[["n", "Aa", "Normal"], ["b", "<b>B</b>", "Negrito"], ["m", "<span style='color:#888'>Aa</span>", "Cinza (detalhe)"]].map(([k, lb, tt]) => `<button data-style="${i}:${k}" class="${l.s === k ? "on" : ""}" title="${tt}">${lb}</button>`).join("")}</div>
            <button class="x" data-delline="${i}" title="Remover linha">✕</button></div>`).join("")}</div>
          <button class="btn ghost xs" data-addline>＋ Linha</button>
          <div class="pp-row"><label>Largura<input class="in" type="number" step="8" min="40" data-p="w" value="${n.w}"></label><label>Altura<input class="in" type="number" step="4" min="28" data-p="h" value="${n.h}"></label></div>
          <div class="pp-lbl">Ao clicar, o analista lê</div>
          <div class="refchips">${r.length ? r.map((x, i) => `<span class="chip">${esc(refLabel(x))}<button data-delref="${i}" title="Desvincular">✕</button></span>`).join("") : `<span class="muted small">Nada vinculado. A caixa fica sem clique no modo leitura.</span>`}</div>
          <select class="in" data-addref>${refOptions(r)}</select>
          <div class="pp-actions"><button class="btn ghost sm" data-connect>→ Ligar a…</button><button class="btn ghost sm" data-dup>Duplicar</button><button class="btn danger sm" data-del>Excluir</button></div>`;
      } else {
        const e = s, a = nodeById(e.from), b = nodeById(e.to);
        const nm = n => esc((n.lines[0] || {}).t || n.id);
        propsEl.innerHTML = `<div class="pp-title">Seta</div>
          <div class="pp-ft"><span>${nm(a)}</span><b>→</b><span>${nm(b)}</span></div>
          <label>Tipo<select class="in" data-p="etype">${Object.entries(CAT.edgeTypes).map(([k, t]) => `<option value="${k}" ${k === e.type ? "selected" : ""}>${t.label}</option>`).join("")}</select></label>
          <label>Rótulo<input class="in" data-p="label" value="${esc(e.label || "")}" placeholder="ex.: sim, não"></label>
          <div class="quick">${["sim", "não", "handoff", "escala ao CSIRT"].map(q => `<button class="btn ghost xs" data-qlabel="${q}">${q}</button>`).join("")}</div>
          <div class="pp-row"><label>Sai pela<select class="in" data-p="exit">${Object.keys(SIDES).map(k => `<option value="${k}" ${sideKey(e.exit) === k ? "selected" : ""}>${SIDE_NAMES[k]}</option>`).join("")}${sideKey(e.exit) === "custom" ? `<option selected value="custom">Personalizado</option>` : ""}</select></label>
            <label>Chega pela<select class="in" data-p="entry">${Object.keys(SIDES).map(k => `<option value="${k}" ${sideKey(e.entry) === k ? "selected" : ""}>${SIDE_NAMES[k]}</option>`).join("")}${sideKey(e.entry) === "custom" ? `<option selected value="custom">Personalizado</option>` : ""}</select></label></div>
          ${(e.wps || []).length ? `<div class="muted small">${e.wps.length} ponto(s) de dobra: arraste os círculos para ajustar.</div><button class="btn ghost xs" data-clearwps>Remover dobras (rota automática)</button>` : ""}
          ${e.label ? `<div class="muted small" style="margin-top:6px">${e.lp ? "Texto da seta reposicionado." : "Arraste o texto da seta no desenho para movê-lo."}</div>${e.lp ? `<button class="btn ghost xs" data-lpreset>↺ Texto na posição automática</button>` : ""}` : ""}
          <div class="pp-actions"><button class="btn ghost sm" data-reverse>⇄ Inverter</button><button class="btn danger sm" data-del>Excluir</button></div>`;
      }
    }

    function propsMulti() {
      const ns = [...multi].map(nodeById).filter(Boolean);
      const rs = ns.map(ramoOf).filter(Boolean);
      propsEl.innerHTML = `<div class="pp-title">${ns.length} caixas selecionadas</div>
        <div class="pp-lbl">Redimensionar proporcionalmente</div>
        <div class="scale-row"><button class="btn ghost sm" data-scale="0.9" title="Diminuir 10%">−10%</button>
          <label class="pct"><input class="in" type="number" min="30" max="300" step="5" value="100" data-scalepct>%</label>
          <button class="btn ghost sm" data-scaleapply>Aplicar</button><button class="btn ghost sm" data-scale="1.1" title="Aumentar 10%">+10%</button></div>
        <p class="muted small">Ou arraste o quadrado no canto da seleção. Posições, tamanhos e dobras das setas mudam juntos; cada caixa continua na sua raia.</p>
        <div class="pp-lbl">Alinhar</div>
        <div class="align-grid">${[["left", "⇤ Esquerda"], ["center", "↔ Centro"], ["right", "⇥ Direita"], ["top", "⤒ Topo"], ["middle", "↕ Meio"], ["bottom", "⤓ Base"]].map(([k, l]) => `<button class="btn ghost xs" data-align="${k}">${l}</button>`).join("")}</div>
        <div class="align-grid"><button class="btn ghost xs" data-dist="x">Distribuir na horizontal</button><button class="btn ghost xs" data-same="w">Mesma largura</button><button class="btn ghost xs" data-same="h">Mesma altura</button></div>
        <div class="pp-lbl">Mover</div><p class="muted small" style="margin-top:0">Arraste qualquer caixa selecionada ou use as setas do teclado. As caixas mantêm as raias.</p>
        ${rs.length ? `<p class="muted small">Inclui ramo(s) ${rs.map(k => "R" + esc(k)).join(", ")}.</p>` : ""}
        <div class="pp-actions"><button class="btn ghost sm" data-clearsel>Limpar seleção</button><button class="btn danger sm" data-del>Excluir ${ns.length}</button></div>`;
    }
    /* escala proporcional das caixas selecionadas: x a partir da caixa mais à esquerda, y a partir da mais alta
       de cada raia (as caixas não mudam de raia); setas internas à seleção escalam as dobras junto */
    function scaled(base, ids, f) {
      const F = clone(base), S = new Set(ids), r = v => Math.round(v * 2) / 2;
      const ns = F.nodes.filter(n => S.has(n.id)); if (!ns.length) return F;
      const ox = Math.min(...ns.map(n => n.x)), oy = {};
      ns.forEach(n => { oy[n.lane] = Math.min(oy[n.lane] ?? Infinity, n.y); });
      ns.forEach(n => {
        n.x = Math.max(minX, r(ox + (n.x - ox) * f)); n.y = Math.max(4, r(oy[n.lane] + (n.y - oy[n.lane]) * f));
        n.w = Math.max(24, r(n.w * f)); n.h = Math.max(20, r(n.h * f));
      });
      F.edges.forEach(e => {
        const a = S.has(e.from), b = S.has(e.to);
        if (a && b) {
          e.wps = (e.wps || []).map(w => ({ ...w, x: r(ox + (w.x - ox) * f), y: w.lane in oy ? r(oy[w.lane] + (w.y - oy[w.lane]) * f) : w.y }));
          if (e.lp) e.lp = { dx: r(e.lp.dx * f), dy: r(e.lp.dy * f) };
        } else if (a || b) e.wps = [];
      });
      return F;
    }
    function multiOp(d) {
      const ns = [...multi].map(nodeById).filter(Boolean); if (ns.length < 2) return;
      const touched = new Set(ns.map(n => n.id));
      if (d.align) {
        const L = Math.min(...ns.map(n => n.x)), R = Math.max(...ns.map(n => n.x + n.w)), T = Math.min(...ns.map(n => n.y)), B = Math.max(...ns.map(n => n.y + n.h));
        const C = (L + R) / 2, M = (T + B) / 2;
        ns.forEach(n => {
          if (d.align === "left") n.x = L; else if (d.align === "right") n.x = R - n.w; else if (d.align === "center") n.x = Math.round(C - n.w / 2);
          else if (d.align === "top") n.y = T; else if (d.align === "bottom") n.y = B - n.h; else n.y = Math.round(M - n.h / 2);
        });
      } else if (d.dist) {
        const o = ns.slice().sort((a, b) => a.x - b.x), tot = o.reduce((a, n) => a + n.w, 0);
        const gap = (o[o.length - 1].x + o[o.length - 1].w - o[0].x - tot) / (o.length - 1);
        let x = o[0].x; o.forEach(n => { n.x = Math.round(x); x += n.w + gap; });
      } else if (d.same) {
        const v = Math.max(...ns.map(n => n[d.same])); ns.forEach(n => { n[d.same] = v; });
      }
      flow.edges.forEach(e => { if (touched.has(e.from) || touched.has(e.to)) e.wps = []; });
    }

    propsEl.addEventListener("input", ev => {
      const t = ev.target, s = findSel();
      if (t.dataset.p === "subtitle") { snapUndo("subtitle"); flow.subtitle = t.value; return; }
      if (!s) return;
      if (t.dataset.line !== undefined) { snapUndo("line" + s.id + t.dataset.line); s.lines[+t.dataset.line].t = t.value; draw(); return; }
      if (t.dataset.p === "label") { snapUndo("label" + s.id); s.label = t.value; draw(); return; }
      if (t.dataset.p === "w" || t.dataset.p === "h") { const v = +t.value; if (v >= 28) { snapUndo("size" + s.id); s[t.dataset.p] = v; draw(); } }
    }, sig);
    propsEl.addEventListener("change", ev => {
      if (ev.target.matches("[data-addlane]")) { const v = ev.target.value; ev.target.value = ""; if (v) addLane(v); return; }
      const t = ev.target, s = findSel(), p = t.dataset.p;
      if (!s) return;
      if (t.matches("[data-addref]")) { if (!t.value) return; snapUndo(); (refs[s.id] = refs[s.id] || []).push(t.value); draw(); props(); return; }
      if (p === "type") {
        snapUndo(); s.type = t.value;
        if (s.type === "support" && !s.team) { s.team = null; }
        if (s.type !== "support") delete s.team;
      } else if (p === "lane") {
        snapUndo();
        const others = flow.nodes.filter(n => n.lane === t.value && n !== s);
        s.lane = t.value; s.y = others.length ? snap(Math.max(...others.map(n => n.y + n.h)) + 24) : 20;
        freeEdges(s.id);
      } else if (p === "team") {
        snapUndo(); s.team = t.value || null; if (t.value) s.lines = mkLines(supportLabel(t.value));
      } else if (p === "etype") { snapUndo(); s.type = t.value; }
      else if (p === "exit" || p === "entry") { if (t.value === "custom") return; snapUndo(); s[p] = SIDES[t.value]; s.wps = []; }
      else return;
      draw(); props();
    }, sig);
    function laneKey(label) {
      let k = (label || "raia").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 20) || "raia";
      const used = new Set(flow.lanes.map(l => l.key)); let i = 2, base = k;
      while (used.has(k)) k = `${base}${i++}`;
      return k;
    }
    function addLane(v) {
      if (v === "new") {   // cria no template e já adiciona a raia, sem recarregar o editor
        teamDialog({ tpl: ad.tplKey }, null, (nm, tv) => {
          OWN[nm] = tv.teamDefs[nm];
          if (pb.template === true && tv.key === pb.key) pb.rev = tv.rev;   // o template mudou só nos times: a gravação do fluxo segue válida
          if (OWN[nm].category === "central") addLane("team:" + nm); else props();
        }, { category: "central" });
        return;
      }
      if (flow.lanes.length >= 12) return toast("No máximo 12 raias", "warn");
      snapUndo();
      if (v === "support") {
        const i = flow.lanes.length;
        flow.lanes.push({ key: laneKey("apoio"), label: CAT.supportLaneLabel, team: null, color: "#5B6673", kind: "support" });
      } else {
        const t = v.slice(5), sup = flow.lanes.findIndex(l => l.kind === "support");
        const lane = { key: laneKey(t), label: t, team: t, color: teamInfo(t).color || "#5B6673", kind: "team" };
        if (sup >= 0) flow.lanes.splice(sup, 0, lane); else flow.lanes.push(lane);
      }
      draw(); props();
    }
    propsEl.addEventListener("click", ev => {
      const b = ev.target.closest("button"); if (!b) return;
      const d0 = b.dataset;
      if (d0.lup !== undefined || d0.ldown !== undefined || d0.ldel !== undefined) {
        const i = +(d0.lup ?? d0.ldown ?? d0.ldel), L = flow.lanes;
        if (d0.ldel !== undefined) {
          const cnt = flow.nodes.filter(n => n.lane === L[i].key).length;
          if (cnt) return toast(`A raia ${L[i].label} tem ${cnt} caixa(s): mova-as para outra raia ou exclua antes`, "warn");
          if (L.length === 1) return toast("O fluxograma precisa de pelo menos uma raia", "warn");
          snapUndo();
          const key = L[i].key; L.splice(i, 1);
          flow.edges.forEach(e => { if ((e.wps || []).some(w => w.lane === key)) e.wps = []; });
        } else {
          snapUndo();
          const j = d0.lup !== undefined ? i - 1 : i + 1;
          [L[i], L[j]] = [L[j], L[i]];
          flow.edges.forEach(e => { e.wps = []; });
        }
        draw(); props(); return;
      }
      if (sel && sel.kind === "multi") {
        const d = b.dataset;
        if (b.hasAttribute("data-clearsel")) { clearSel(); draw(); props(); return; }
        if (b.hasAttribute("data-del")) return deleteSel();
        let f = d.scale ? +d.scale : null;
        if (b.hasAttribute("data-scaleapply")) f = (+propsEl.querySelector("[data-scalepct]").value || 100) / 100;
        if (f) {
          if (f < .3 || f > 3) return toast("Use uma escala entre 30% e 300%", "warn");
          snapUndo(); flow = scaled(flow, [...multi], f); draw(); props(); setStatus(`Seleção redimensionada para ${Math.round(f * 100)}%`); return;
        }
        if (d.align || d.dist || d.same) { snapUndo(); multiOp(d); draw(); }
        return;
      }
      const s = findSel(); if (!s) return;
      const d = b.dataset;
      if (d.upline !== undefined) { const i = +d.upline; snapUndo(); [s.lines[i - 1], s.lines[i]] = [s.lines[i], s.lines[i - 1]]; }
      else if (b.hasAttribute("data-lpreset")) { snapUndo(); delete s.lp; }
      else if (d.style) { const [i, k] = d.style.split(":"); snapUndo(); s.lines[+i].s = k; }
      else if (d.delline !== undefined) { snapUndo(); s.lines.splice(+d.delline, 1); }
      else if (b.hasAttribute("data-addline")) { snapUndo(); s.lines.push({ t: "", s: "m" }); }
      else if (d.delref !== undefined) { snapUndo(); refs[s.id].splice(+d.delref, 1); }
      else if (d.qlabel) { snapUndo(); s.label = d.qlabel; }
      else if (b.hasAttribute("data-clearwps")) { snapUndo(); s.wps = []; }
      else if (b.hasAttribute("data-reverse")) { snapUndo(); [s.from, s.to] = [s.to, s.from]; [s.exit, s.entry] = [s.entry, s.exit]; s.wps = (s.wps || []).slice().reverse(); }
      else if (b.hasAttribute("data-connect")) { setMode({ kind: "connect", from: s.id }); return; }
      else if (b.hasAttribute("data-dup")) return duplicate();
      else if (b.hasAttribute("data-del")) return deleteSel();
      else return;
      draw(); props();
      if (b.hasAttribute("data-addline")) { const ins = propsEl.querySelectorAll("[data-line]"); ins[ins.length - 1].focus(); }
    }, sig);

    /* ── interação no canvas ── */
    canvas.addEventListener("pointerdown", ev => {
      if (ev.button !== 0) return;
      const p = pt(ev);
      const tg = ev.target;
      const nodeG = tg.closest(".node"), edgeG = tg.closest(".edge, .elabel");
      if (mode && mode.kind === "add") { addNode(mode.preset, p); return; }
      if (mode && mode.kind === "connect") { if (nodeG) connect(mode.from, nodeG.dataset.node); setMode(null); return; }
      if (tg.matches(".ch")) {
        drag = { kind: "connect", from: sel.id, start: p };
        return canvas.setPointerCapture(ev.pointerId);
      }
      if (tg.matches(".rz")) {
        const n = nodeById(sel.id);
        drag = { kind: "resize", id: n.id, w: n.w, h: n.h, start: p, before: state() };
        return canvas.setPointerCapture(ev.pointerId);
      }
      if (tg.matches(".wp")) {
        drag = { kind: "wp", id: sel.id, i: +tg.dataset.wp, before: state() };
        return canvas.setPointerCapture(ev.pointerId);
      }
      if (tg.matches(".grz")) {            // alça da seleção múltipla: escala proporcional
        const bs = [...multi].map(id => lay.abs[id]).filter(Boolean);
        const box = { x: Math.min(...bs.map(b => b.x)), y: Math.min(...bs.map(b => b.y)) };
        box.w = Math.max(...bs.map(b => b.x + b.w)) - box.x; box.h = Math.max(...bs.map(b => b.y + b.h)) - box.y;
        drag = { kind: "gscale", box, base: clone(flow), ids: [...multi], before: state() };
        return canvas.setPointerCapture(ev.pointerId);
      }
      const lbl = tg.closest(".elabel");
      if (lbl) {                           // arrastar o texto da seta
        const e = edgeById(lbl.dataset.edge);
        selectEdge(e.id);
        drag = { kind: "label", id: e.id, start: p, lp0: { dx: (e.lp || {}).dx || 0, dy: (e.lp || {}).dy || 0 }, before: state() };
        canvas.setPointerCapture(ev.pointerId);
        draw(); props(); return;
      }
      const additive = ev.shiftKey || ev.ctrlKey || ev.metaKey;
      if (nodeG) {
        const id = nodeG.dataset.node;
        if (additive) {                    // Shift/Ctrl+clique: soma ou tira da seleção
          const cur = new Set(multi); if (sel && sel.kind === "node") cur.add(sel.id);
          cur.has(id) ? cur.delete(id) : cur.add(id);
          setMulti(cur); draw(); props(); return;
        }
        if (multi.size > 1 && multi.has(id)) {   // arrastar o grupo
          drag = { kind: "gmove", start: p, base: clone(flow), ids: [...multi], moved: false, before: state() };
          return canvas.setPointerCapture(ev.pointerId);
        }
        const n = nodeById(id), a = lay.abs[n.id];
        selectNode(n.id);
        drag = { kind: "move", id: n.id, dx: p.x - a.x, dy: p.y - a.y, moved: false, before: state() };
        canvas.setPointerCapture(ev.pointerId);
        draw(); props(); return;
      }
      if (edgeG) { selectEdge(edgeG.dataset.edge); draw(); props(); return; }
      // fundo: laço de seleção (um clique simples limpa a seleção)
      drag = { kind: "marquee", start: p, add: additive, keep: new Set(multi) };
      canvas.setPointerCapture(ev.pointerId);
    }, sig);
    canvas.addEventListener("pointermove", ev => {
      if (!drag) return;
      const p = pt(ev);
      if (drag.kind === "move") {
        const n = nodeById(drag.id);
        const ax = p.x - drag.dx, ay = p.y - drag.dy;
        if (!drag.moved && Math.hypot(ax - lay.abs[n.id].x, ay - lay.abs[n.id].y) < 4) return;
        drag.moved = true;
        const lane = laneAt(ay + n.h / 2);
        n.lane = lane.key;
        n.x = Math.max(minX, snap(ax - lane.x)); n.y = Math.max(8, snap(ay - lane.y));
        freeEdges(n.id);
        draw();
      } else if (drag.kind === "resize") {
        const n = nodeById(drag.id);
        n.w = Math.max(40, snap(drag.w + p.x - drag.start.x)); n.h = Math.max(28, Math.round((drag.h + p.y - drag.start.y) / 4) * 4);
        draw();
      } else if (drag.kind === "gmove") {
        const dx = snap(p.x - drag.start.x), dy = snap(p.y - drag.start.y);
        if (!drag.moved && Math.hypot(p.x - drag.start.x, p.y - drag.start.y) < 4) return;
        drag.moved = true;
        const S = new Set(drag.ids), B = drag.base;
        flow.nodes.forEach((n, i) => { if (S.has(n.id)) { const o = B.nodes[i]; n.x = Math.max(minX, o.x + dx); n.y = Math.max(8, o.y + dy); } });
        flow.edges.forEach((e, i) => {
          const a = S.has(e.from), b = S.has(e.to), o = B.edges[i];
          if (a && b) e.wps = (o.wps || []).map(w => ({ ...w, x: w.x + dx, y: w.y + dy }));
          else if (a || b) { e.wps = []; e.exit = null; e.entry = null; }
        });
        draw();
      } else if (drag.kind === "gscale") {
        const b = drag.box;
        const f = Math.max(.3, Math.min(3, ((p.x - b.x) / b.w + (p.y - b.y) / b.h) / 2));
        flow = scaled(drag.base, drag.ids, Math.round(f * 20) / 20);
        setStatus(`Escala da seleção: <b>${Math.round(f * 20) * 5}%</b> · solte para aplicar · <kbd>Ctrl+Z</kbd> desfaz`);
        draw();
      } else if (drag.kind === "label") {
        const e = edgeById(drag.id);
        e.lp = { dx: Math.round(drag.lp0.dx + p.x - drag.start.x), dy: Math.round(drag.lp0.dy + p.y - drag.start.y) };
        if (!e.lp.dx && !e.lp.dy) delete e.lp;
        draw();
      } else if (drag.kind === "marquee") {
        const x = Math.min(p.x, drag.start.x), y = Math.min(p.y, drag.start.y), w = Math.abs(p.x - drag.start.x), h = Math.abs(p.y - drag.start.y);
        drag.rect = { x, y, w, h };
        $("#temp", svgEl).innerHTML = `<rect class="marquee" x="${x}" y="${y}" width="${w}" height="${h}"/>`;
      } else if (drag.kind === "wp") {
        const e = edgeById(drag.id), lane = laneAt(p.y);
        e.wps[drag.i] = { lane: lane.key, x: snap(p.x - lane.x), y: snap(p.y - lane.y) };
        draw();
      } else if (drag.kind === "connect") {
        const a = lay.abs[drag.from];
        $("#temp", svgEl).innerHTML = `<line x1="${a.x + a.w}" y1="${a.y + a.h / 2}" x2="${p.x}" y2="${p.y}" stroke="${getComputedStyle(document.documentElement).getPropertyValue("--brand").trim() || "#CC092F"}" stroke-width="2" stroke-dasharray="5 4"/>`;
        const over = document.elementFromPoint(ev.clientX, ev.clientY);
        svgEl.querySelectorAll(".node.target").forEach(x => x.classList.remove("target"));
        const og = over && over.closest(".node"); if (og && og.dataset.node !== drag.from) og.classList.add("target");
      }
    }, sig);
    canvas.addEventListener("pointerup", ev => {
      if (!drag) return;
      const d = drag; drag = null;
      if (d.kind === "marquee") {
        $("#temp", svgEl).innerHTML = "";
        const r = d.rect;
        if (!r || r.w < 4 && r.h < 4) { if (!d.add) clearSel(); draw(); props(); return; }
        const hit = flow.nodes.filter(n => { const a = lay.abs[n.id]; return a.x < r.x + r.w && a.x + a.w > r.x && a.y < r.y + r.h && a.y + a.h > r.y; }).map(n => n.id);
        setMulti(d.add ? [...d.keep, ...hit] : hit); draw(); props(); return;
      }
      if (d.kind === "gscale") setStatus("");
      if (d.kind === "connect") {
        const over = document.elementFromPoint(ev.clientX, ev.clientY);
        const og = over && over.closest(".node");
        $("#temp", svgEl).innerHTML = "";
        if (og) connect(d.from, og.dataset.node); else draw();
        return;
      }
      if (d.before && state() !== d.before) {
        undo.push(d.before); redo.length = 0; markDirty($("#fbar")); lastSnapKey = "";
      }
      draw(); props();
    }, sig);

    /* arrastar da paleta */
    let palDrag = null;
    el.querySelector(".fe-pal").addEventListener("pointerdown", ev => {
      const it = ev.target.closest(".pal-item"); if (!it) return;
      ev.preventDefault();
      palDrag = { key: it.dataset.preset, x: ev.clientX, y: ev.clientY, ghost: null };
    }, sig);
    const palMove = ev => {
      if (!palDrag) return;
      if (!palDrag.ghost && Math.hypot(ev.clientX - palDrag.x, ev.clientY - palDrag.y) > 5) {
        palDrag.ghost = document.createElement("div"); palDrag.ghost.className = "pal-ghost";
        palDrag.ghost.innerHTML = presetSvg(PRESETS.find(p => p.key === palDrag.key));
        document.body.append(palDrag.ghost);
      }
      if (palDrag.ghost) { palDrag.ghost.style.left = ev.clientX + "px"; palDrag.ghost.style.top = ev.clientY + "px"; }
    };
    const palUp = ev => {
      if (!palDrag) return;
      const d = palDrag; palDrag = null;
      if (d.ghost) {
        d.ghost.remove();
        const r = canvas.getBoundingClientRect();
        if (ev.clientX >= r.left && ev.clientX <= r.right && ev.clientY >= r.top && ev.clientY <= r.bottom) { addNode(d.key, pt(ev)); }
      } else setMode(mode && mode.preset === d.key ? null : { kind: "add", preset: d.key });
    };
    window.addEventListener("pointermove", palMove, sig);
    window.addEventListener("pointerup", palUp, sig);

    const key = ev => {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
      const mod = ev.ctrlKey || ev.metaKey;
      if (mod && ev.key.toLowerCase() === "s") { ev.preventDefault(); return save(); }
      if (typing) return;
      if (mod && ev.key.toLowerCase() === "z") { ev.preventDefault(); return ev.shiftKey ? doRedo() : doUndo(); }
      if (mod && ev.key.toLowerCase() === "y") { ev.preventDefault(); return doRedo(); }
      if (mod && ev.key.toLowerCase() === "d") { ev.preventDefault(); return duplicate(); }
      if (mod && ev.key.toLowerCase() === "a") { ev.preventDefault(); return selectAll(); }
      if (ev.key === "Escape") { if (mode) setMode(null); else if (drawer.hidden) { clearSel(); draw(); props(); } }
      if ((ev.key === "Delete" || ev.key === "Backspace") && sel) { ev.preventDefault(); deleteSel(); }
      const arrows = { ArrowLeft: [-8, 0], ArrowRight: [8, 0], ArrowUp: [0, -8], ArrowDown: [0, 8] };
      if (arrows[ev.key] && sel && (sel.kind === "node" || sel.kind === "multi")) {
        ev.preventDefault();
        const ids = sel.kind === "multi" ? [...multi] : [sel.id], S = new Set(ids), [dx, dy] = arrows[ev.key];
        snapUndo("nudge" + ids.join());
        ids.forEach(id => { const n = nodeById(id); n.x = Math.max(minX, n.x + dx); n.y = Math.max(8, n.y + dy); });
        flow.edges.forEach(e => {
          if (S.has(e.from) && S.has(e.to)) e.wps = (e.wps || []).map(w => ({ ...w, x: w.x + dx, y: w.y + dy }));
          else if (S.has(e.from) || S.has(e.to)) { e.wps = []; e.exit = null; e.entry = null; }
        });
        draw();
      }
    };
    document.addEventListener("keydown", key, sig);

    /* ── modo código (Mermaid) ── */
    let codeMode = false, codeDirty = false;
    const codeBox = document.createElement("div");
    codeBox.hidden = true; el.querySelector(".fe-main").append(codeBox);
    const CODE_HELP = `<b>Linguagem: Mermaid flowchart</b>
      <p>O mesmo texto abre no GitHub, GitLab, Confluence (macro Mermaid) e mermaid.live. Linhas <code>%% @…</code> são detalhes do Medusa que o Mermaid ignora.</p>
      <table><tbody>
        <tr><td><code>subgraph n1["SOC N1"]</code> … <code>end</code></td><td>raia (time)</td></tr>
        <tr><td><code>a(["Texto"])</code></td><td>início</td></tr>
        <tr><td><code>a["Texto"]</code></td><td>ação</td></tr>
        <tr><td><code>a{"Pergunta?"}</code></td><td>decisão</td></tr>
        <tr><td><code>:::close</code> <code>:::neutral</code> <code>:::attention</code> <code>:::crossref</code> <code>:::support</code></td><td>encerramento, vínculo, atenção, outro playbook, apoio</td></tr>
        <tr><td><code>&lt;b&gt;…&lt;/b&gt;</code> · <code>&lt;small&gt;…&lt;/small&gt;</code> · <code>&lt;br&gt;</code></td><td>negrito · cinza · nova linha</td></tr>
        <tr><td><code>a --&gt; b</code></td><td>fluxo</td></tr>
        <tr><td><code>a --&gt;|sim| b</code></td><td>com rótulo</td></tr>
        <tr><td><code>a -.-&gt; b</code></td><td>handoff, apoio ou referência (pelas raias)</td></tr>
        <tr><td><code>a ==&gt; b</code></td><td>escalonamento ao CSIRT</td></tr>
        <tr><td><code>%% @refs a T0, R1</code></td><td>o que o analista lê ao clicar</td></tr>
        <tr><td><code>%% @pos a x y l a</code></td><td>posição (opcional)</td></tr>
      </tbody></table>
      <p>Sem <code>@pos</code>, a caixa é posicionada automaticamente. Os ids (<code>a</code>, <code>b</code>…) são livres: letras, números, <code>_</code> e <code>-</code>.</p>`;
    async function enterCode() {
      let txt;
      try { txt = (await api("POST", "api/flow/render", { flow, refs })).text; } catch (e) { return toast(e.message, "err"); }
      codeMode = true; codeDirty = false; setMode(null);
      el.querySelector(".fe-grid").classList.add("coding");
      canvas.hidden = true; status.hidden = true; codeBox.hidden = false;
      el.querySelector(".fe-pal").hidden = true; propsEl.hidden = true;
      el.querySelectorAll("[data-mode]").forEach(b => b.classList.toggle("on", b.dataset.mode === "code"));
      codeBox.innerHTML = `<div class="code-wrap"><div><textarea class="code" id="ftext" spellcheck="false" autocapitalize="off"></textarea>
          <div class="code-msg" id="fmsg"></div>
          <div class="create-actions" style="justify-content:flex-start;flex-wrap:wrap"><button class="btn primary" id="fapply">Aplicar ao desenho</button>
            <button class="btn ghost" id="fauto" title="Descarta as posições e organiza todas as caixas automaticamente">Reorganizar automaticamente</button>
            <button class="btn ghost" id="fcopy">Copiar</button><button class="btn ghost" id="fdl">Baixar .mmd</button></div></div>
        <aside class="code-help">${CODE_HELP}</aside></div>`;
      const ta = $("#ftext", codeBox), msg = $("#fmsg", codeBox);
      ta.value = txt;
      ta.addEventListener("input", () => { codeDirty = true; markDirty($("#fbar")); }, sig);
      ta.addEventListener("keydown", e => { if (e.key === "Tab") { e.preventDefault(); const p = ta.selectionStart; ta.setRangeText("  ", p, ta.selectionEnd, "end"); } }, sig);
      async function apply(text, label) {
        try {
          const r = await api("POST", "api/flow/parse", { text });
          snapUndo(); flow = r.flow; refs = r.refs; sel = null; codeDirty = false;
          leaveCode(); toast(label);
          if (r.warnings.length) setStatus("Avisos: " + r.warnings.map(esc).join(" · "));
        } catch (x) { msg.innerHTML = `<div class="err">${esc(x.message)}</div>`; }
      }
      $("#fapply", codeBox).onclick = () => apply(ta.value, "Fluxograma atualizado a partir do código");
      $("#fauto", codeBox).onclick = async () => {
        if (!confirm("Reorganizar todas as caixas automaticamente? As posições atuais e os pontos de dobra serão descartados (dá para desfazer).")) return;
        try {
          const cur = codeDirty ? (await api("POST", "api/flow/parse", { text: ta.value })) : { flow, refs };
          const t = (await api("POST", "api/flow/render", { flow: cur.flow, refs: cur.refs, positions: false })).text;
          apply(t, "Caixas reorganizadas automaticamente");
        } catch (x) { msg.innerHTML = `<div class="err">${esc(x.message)}</div>`; }
      };
      $("#fcopy", codeBox).onclick = () => navigator.clipboard.writeText(ta.value).then(() => toast("Copiado"), () => { ta.select(); toast("Selecionado: use Ctrl+C", "warn"); });
      $("#fdl", codeBox).onclick = () => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([ta.value], { type: "text/plain" }));
        a.download = `${ad.fileBase}-fluxo.mmd`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
      };
      ta.focus();
    }
    function leaveCode() {
      codeMode = false; codeBox.hidden = true; canvas.hidden = false;
      el.querySelector(".fe-grid").classList.remove("coding");
      el.querySelector(".fe-pal").hidden = false; propsEl.hidden = false;
      el.querySelectorAll("[data-mode]").forEach(b => b.classList.toggle("on", b.dataset.mode === "visual"));
      draw(); props(); setStatus("");
    }
    el.querySelector(".fe-modes").addEventListener("click", e => {
      const b = e.target.closest("[data-mode]"); if (!b) return;
      if (b.dataset.mode === "code" && !codeMode) enterCode();
      if (b.dataset.mode === "visual" && codeMode) {
        if (codeDirty && !confirm("O texto tem alterações não aplicadas. Voltar ao desenho e descartá-las?")) return;
        codeDirty = false; leaveCode();
      }
    }, sig);

    async function save() {
      if (codeMode && codeDirty) return toast("Clique em “Aplicar ao desenho” antes de salvar", "warn");
      const btn = $("#fsave"); btn.disabled = true; btn.textContent = "Salvando…";
      try {
        const v = await ad.saveFlow(flow, refs, pb.rev);
        E.dirty = false; savedToast(v, "Fluxograma salvo");
        ad.after(v); remount(el, v);
      } catch (err) { saveError(err, el, pb, remount, ad); btn.disabled = false; btn.textContent = "Salvar fluxograma"; }
    }
    function selectAll() { if (codeMode) return; setMulti(flow.nodes.map(n => n.id)); draw(); props(); }
    $("#fall").onclick = selectAll;
    $("#fsave").onclick = save;
    $("#fundo").onclick = doUndo; $("#fredo").onclick = doRedo;
    $("#fdiscard").onclick = () => discard(el, pb, remount, "do fluxograma", ad);
    el.querySelectorAll("[data-z]").forEach(b => b.onclick = () => {
      const z = b.dataset.z; if (z === "0") return fit();
      autoFit = false; zoomF = Math.max(.4, Math.min(2.5, zoomF * (z === "1" ? 1.2 : 1 / 1.2))); draw();
    });

    window.addEventListener("resize", onResize, sig);
    $("#fbar").insertAdjacentHTML("afterend", ad.banner || "");
    draw(); fit(); props(); setMode(null);
  };

  /* ═════════════════════════ CRIAR PLAYBOOK ═════════════════════════ */
  E.createForm = async (el) => {
    const sig = mount();
    el.innerHTML = `<div class="wrap"><div class="empty">Carregando templates…</div></div>`;
    let tpls = [], people = [];
    try {
      [tpls, people] = await Promise.all([api("GET", "api/templates").then(r => r.templates), api("GET", "api/people").then(r => r.people)]);
    } catch (e) { el.innerHTML = `<div class="wrap"><div class="err">${esc(e.message)}</div></div>`; return; }
    tpls = tpls.filter(t => !t.error);
    if (!tpls.length) { el.innerHTML = `<div class="wrap"><div class="err">Nenhum template disponível. Crie um em Templates.</div></div>`; return; }
    const used = PBS.map(p => +p.id.slice(3));
    let n = 1; while (used.includes(n)) n++;
    const first = tpls.find(t => t.key === "padrao") || tpls[0];
    const m = { template: first.key, id: "PB-" + String(n).padStart(2, "0"), name: "", owner: first.owner || "", nist: first.nist || "",
      mitre: [], objective: "", question: "", author: App.user.login, ramos: [{ name: "", q: "" }, { name: "", q: "" }] };
    const tplOf = () => tpls.find(t => t.key === m.template);
    const NIST = ["Detecção e Análise → Pós-Incidente (ciclo completo)", "Detecção e Análise → Contenção inicial; erradicação e recuperação seguem no playbook de destino", "Detecção e Análise"];

    function preview() {
      const t = tplOf(), ramos = m.ramos.filter(r => r.name.trim());
      const pv = $("#cpreview"); if (!pv) return;
      pv.innerHTML = `<div class="pv-id">${esc(m.id)} · template ${esc(t.name)}</div><div class="pv-name">${esc(m.name || "Nome do playbook")}</div>
        <div class="pv-tpl">${t.lanes.map(l => `<span class="chip">${esc(l)}</span>`).join("")}</div>
        ${t.usesRamos ? `<div class="pv-row" style="padding:6px 0">${(ramos.length ? ramos : [{ name: "Ramo" }]).map((r, i) => `<i class="ramo"><b>R${i + 1}</b> ${esc(r.name || "")}</i>`).join("")}</div>` : ""}
        ${m.mitre.length ? `<div class="pv-mitre">${m.mitre.map(id => `<span class="chip">${esc(id)}</span>`).join("")}</div>` : ""}
        <div class="pv-note">Gera o documento com as <b>${t.sections}</b> seções do template e o fluxograma inicial com <b>${t.nodes}</b> caixas${t.usesRamos ? ", repetindo o que é de ramo para cada um" : ""}.
          Os times e tags do playbook (${t.teams.length}) são os do template. O playbook começa em <b>Desenvolvimento</b>.</div>`;
    }
    function ramosHtml() {
      return m.ramos.map((r, i) => `<div class="ramo-row"><span class="rn">R${i + 1}</span>
        <input class="in" data-ramo="${i}" data-k="name" value="${esc(r.name)}" placeholder="Nome do ramo (ex.: Varredura)">
        <input class="in" data-ramo="${i}" data-k="q" value="${esc(r.q)}" placeholder="Indicador de sucesso (ex.: IP passou a explorar serviço?)">
        <button type="button" class="x" data-delramo="${i}" title="Remover ramo" ${m.ramos.length < 2 ? "disabled" : ""}>✕</button></div>`).join("");
    }
    function syncTemplate() {
      const t = tplOf();
      $("#ramosCard").hidden = !t.usesRamos;
      $("#tplDesc").textContent = t.description || "";
      if (t.owner && !$("[name=owner]").dataset.touched) { $("[name=owner]").value = t.owner; m.owner = t.owner; }
      if (t.nist && !$("[name=nist]").dataset.touched) { const s = $("[name=nist]"); if (![...s.options].some(o => o.value === t.nist)) s.add(new Option(t.nist, t.nist)); s.value = t.nist; m.nist = t.nist; }
      preview();
    }
    el.innerHTML = `<section class="hero slim"><div class="wrap"><h1>Criar playbook</h1><p>Escolha um template e preencha o essencial. O documento e o fluxograma iniciais saem do template; depois você completa pelos editores.</p></div></section>
      <div class="wrap create">
        <form id="cform" autocomplete="off">
          <div class="ecard"><div class="step-h"><span>1</span>Template</div>
            <div class="tpl-pick">${tpls.map(t => `<label class="tpl-opt"><input type="radio" name="template" value="${esc(t.key)}" ${t.key === m.template ? "checked" : ""}>
              <b>${esc(t.name)}</b><small>${t.sections} seções · ${t.nodes} caixas · ${t.lanes.length} raias${t.usesRamos ? " · usa ramos" : ""}</small></label>`).join("")}</div>
            <p class="muted small" id="tplDesc"></p></div>
          <div class="ecard"><div class="step-h"><span>2</span>Identificação</div>
            <div class="pp-row"><label style="max-width:140px">ID<input class="in" name="id" value="${esc(m.id)}" required pattern="PB-\\d{2,3}"></label>
              <label>Nome do playbook<input class="in" name="name" required placeholder="ex.: Malware em estação"></label></div>
            <div class="pp-row"><label>Autor<select class="in" name="author">${people.map(p => `<option value="${esc(p.login)}" ${p.login === m.author ? "selected" : ""}>${esc(p.name)} (${esc(p.roleName)})</option>`).join("")}</select></label>
              <label>Owner do documento<input class="in" name="owner" value="${esc(m.owner)}"></label></div>
            <label>Fase NIST<select class="in" name="nist">${NIST.map(o => `<option ${o === m.nist ? "selected" : ""}>${esc(o)}</option>`).join("")}</select></label>
            <div class="pp-lbl">Táticas MITRE ATT&amp;CK <small class="muted">(${esc(App.data.catalog.mitre.framework || "")} v${esc(App.data.catalog.mitre.version || "")})</small></div>
            <div id="mitreBox"></div></div>
          <div class="ecard"><div class="step-h"><span>3</span>Escopo e triagem</div>
            <label>Que alertas este playbook trata?<textarea class="in" name="objective" rows="3" placeholder="O PB-xx trata alertas de…"></textarea></label>
            <label>Pergunta central da triagem<input class="in" name="question" placeholder="ex.: houve sucesso ou foi só tentativa?"></label></div>
          <div class="ecard" id="ramosCard"><div class="step-h"><span>4</span>Ramos</div>
            <p class="muted small" style="margin-top:0">O template repete, para cada ramo, a subseção de detalhe e a caixa R do fluxograma.</p>
            <div id="ramos">${ramosHtml()}</div><button type="button" class="btn ghost xs" id="addramo">＋ Ramo</button></div>
          <div class="create-actions"><a class="btn ghost" href="#/">Cancelar</a><button class="btn primary" type="submit">Criar playbook</button></div>
        </form>
        <aside class="ecard pv" id="cpreview"></aside>
      </div>`;
    const form = $("#cform");
    MitrePicker.mount($("#mitreBox"), m.mitre, ids => { m.mitre = ids; E.dirty = true; preview(); });
    form.addEventListener("input", e => {
      const t = e.target;
      if (t.dataset.ramo !== undefined) m.ramos[+t.dataset.ramo][t.dataset.k] = t.value;
      else if (t.name && t.name !== "template") { m[t.name] = t.name === "id" ? t.value.toUpperCase() : t.value; t.dataset.touched = "1"; }
      E.dirty = true; preview();
    }, sig);
    form.addEventListener("change", e => {
      if (e.target.name === "template") { m.template = e.target.value; syncTemplate(); return; }
      if (e.target.name) { m[e.target.name] = e.target.value; e.target.dataset.touched = "1"; } preview();
    }, sig);
    form.addEventListener("click", e => {
      if (e.target.id === "addramo") { m.ramos.push({ name: "", q: "" }); $("#ramos").innerHTML = ramosHtml(); $("#ramos").querySelector(`[data-ramo="${m.ramos.length - 1}"]`).focus(); preview(); }
      const d = e.target.closest("[data-delramo]");
      if (d) { m.ramos.splice(+d.dataset.delramo, 1); $("#ramos").innerHTML = ramosHtml(); preview(); }
    }, sig);
    form.addEventListener("submit", async e => {
      e.preventDefault();
      if (tplOf().usesRamos && !m.ramos.some(r => r.name.trim())) return toast("Informe pelo menos um ramo", "warn");
      const btn = form.querySelector("[type=submit]"); btn.disabled = true; btn.textContent = "Criando…";
      try {
        const r = await api("POST", "api/pb", { ...m, ramos: tplOf().usesRamos ? m.ramos : [] });
        replacePlaybook(r.playbook); if (r.teams) setTeams(r.teams); E.dirty = false;
        toast(`${r.playbook.id} criado com o template ${tplOf().name}. Complete o documento.`);
        Tabs.drop("novo"); location.hash = `#/${r.playbook.slug}/editar`;
      } catch (err) { toast(err.message, "err"); btn.disabled = false; btn.textContent = "Criar playbook"; }
    }, sig);
    syncTemplate();
  };

  return E;
})();

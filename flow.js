"use strict";
/* Layout e desenho do fluxograma. Usado pelo leitor e pelo editor.
   Mesmo algoritmo de pbcore.layout/auto_sides: raias empilhadas que crescem com as caixas. */
const Flow = (() => {
  let CAT = null;
  const setCatalog = c => { CAT = c; };
  const escH = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function layout(flow) {
    const L = CAT.layout, lanes = [], byKey = {};
    const width = Math.max(L.minW, ...flow.nodes.map(n => n.x + n.w + L.pad));
    let y = L.y0;
    for (const def of (flow.lanes && flow.lanes.length ? flow.lanes : CAT.defaultLanes)) {
      const ns = flow.nodes.filter(n => n.lane === def.key);
      const h = Math.max(L.minH, ...ns.map(n => n.y + n.h + L.pad));
      const lane = { ...def, x: L.x, y, w: width, h, start: L.start };
      lanes.push(lane); byKey[def.key] = lane;
      y += h + L.gap;
    }
    const abs = {};
    for (const n of flow.nodes) {
      const ln = byKey[n.lane];
      abs[n.id] = { x: ln.x + n.x, y: ln.y + n.y, w: n.w, h: n.h };
    }
    const edges = [];
    for (const e of flow.edges) {
      const s = abs[e.from], t = abs[e.to];
      if (!s || !t) continue;
      const auto = autoSides(s, t);
      const ex = e.exit || auto[0], en = e.entry || auto[1];
      const wps = (e.wps || []).filter(w => byKey[w.lane]).map(w => [byKey[w.lane].x + w.x, byKey[w.lane].y + w.y]);
      const start = [s.x + s.w * ex.x, s.y + s.h * ex.y], end = [t.x + t.w * en.x, t.y + t.h * en.y];
      edges.push({ ...e, pts: route(start, dirOf(ex), wps, end, dirOf(en)) });
    }
    const last = lanes[lanes.length - 1];
    return { lanes, byKey, abs, edges, bounds: [L.x, L.y0, L.x + width, last.y + last.h] };
  }

  const dirOf = p => ((p.x === 0 || p.x === 1) && p.y !== 0 && p.y !== 1) ? "h" : "v";

  function autoSides(s, t) {
    if (t.y >= s.y + s.h + 8) return [{ x: .5, y: 1 }, { x: .5, y: 0 }];
    if (t.y + t.h <= s.y - 8) return [{ x: .5, y: 0 }, { x: .5, y: 1 }];
    if (t.x + t.w / 2 >= s.x + s.w / 2) return [{ x: 1, y: .5 }, { x: 0, y: .5 }];
    return [{ x: 0, y: .5 }, { x: 1, y: .5 }];
  }

  function route(start, sdir, wps, end, edir) {
    const path = [start];
    let cur = start, d = sdir;
    const targets = wps.map(p => [p, null]).concat([[end, edir]]);
    for (const [t, ed] of targets) {
      if (cur[0] !== t[0] && cur[1] !== t[1]) {
        if (ed !== null && ed === d) {
          if (d === "v") { const my = (cur[1] + t[1]) / 2; path.push([cur[0], my], [t[0], my]); }
          else { const mx = (cur[0] + t[0]) / 2; path.push([mx, cur[1]], [mx, t[1]]); }
        } else path.push(d === "v" ? [cur[0], t[1]] : [t[0], cur[1]]);
      }
      path.push(t);
      const a = path[path.length - 2], b = path[path.length - 1];
      if (a[0] !== b[0] || a[1] !== b[1]) d = a[1] === b[1] ? "h" : "v";
      cur = t;
    }
    return path.filter((p, i) => i === 0 || p[0] !== path[i - 1][0] || p[1] !== path[i - 1][1]);
  }

  function labelHtml(lines) {
    return (lines || []).map(l => l.s === "b" ? `<b>${escH(l.t)}</b>` : l.s === "m" ? `<span class="m">${escH(l.t)}</span>` : escH(l.t)).join("<br>");
  }

  /* posição automática do rótulo; e.lp guarda o deslocamento quando o usuário arrasta o texto */
  function labelPos(e) {
    const [x, y] = labelAuto(e);
    return e.lp ? [x + (+e.lp.dx || 0), y + (+e.lp.dy || 0)] : [x, y];
  }
  function labelAuto(e) {
    const p = e.pts;
    if ((e.label || "").length <= 8 && p.length > 1) {
      const [a, b] = p, dx = Math.sign(b[0] - a[0]), dy = Math.sign(b[1] - a[1]);
      return [a[0] + dx * 18 + (dy ? 12 : 0), a[1] + dy * 16 - (dx ? 7 : 0)];
    }
    let best = -1, bi = 0;
    for (let i = 0; i < p.length - 1; i++) {
      const l = Math.abs(p[i][0] - p[i + 1][0]) + Math.abs(p[i][1] - p[i + 1][1]);
      if (l > best) { best = l; bi = i; }
    }
    return [(p[bi][0] + p[bi + 1][0]) / 2, (p[bi][1] + p[bi + 1][1]) / 2];
  }

  function shape(n, a) {
    const t = CAT.nodeTypes[n.type] || CAT.nodeTypes.action;
    const base = `class="shape" fill="${t.fill}" stroke="${t.stroke}" stroke-width="${t.sw}" ${t.dashed ? 'stroke-dasharray="5 3"' : ""}`;
    const { x, y, w, h } = a;
    if (t.shape === "rhombus") return `<polygon ${base} points="${x + w / 2},${y} ${x + w},${y + h / 2} ${x + w / 2},${y + h} ${x},${y + h / 2}"/>`;
    const r = t.shape === "pill" ? h / 2 : Math.min(12, h * .12 + 3);
    return `<rect ${base} x="${x}" y="${y}" width="${w}" height="${h}" rx="${r}"/>`;
  }

  /* opts: badges {nodeId: texto}, nodeClass(n) → classe extra, editor (bool), sel {kind,id}, multi (Set de ids), laneClickable (bool) */
  function svg(flow, opts = {}) {
    const lay = layout(flow);
    const [x0, y0, x1, y1] = lay.bounds, pad = 14;
    const colors = [...new Set(Object.values(CAT.edgeTypes).map(t => t.color))];
    let s = `<defs>${colors.map(c => `<marker id="ar${c.slice(1)}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${c}"/></marker>`).join("")}
      <pattern id="grid8" width="8" height="8" patternUnits="userSpaceOnUse"><path d="M8 0H0V8" fill="none" stroke="#e9e9ee" stroke-width=".6"/></pattern></defs>`;
    for (const l of lay.lanes) {
      s += `<g class="lane" data-lane="${l.key}"><rect x="${l.x}" y="${l.y}" width="${l.w}" height="${l.h}" rx="6" fill="${opts.editor ? "url(#grid8)" : "#fff"}" stroke="${l.color}"/>`;
      if (opts.editor) s += `<rect x="${l.x}" y="${l.y}" width="${l.w}" height="${l.h}" rx="6" fill="#fff" opacity=".55" pointer-events="none"/>`;
      s += `<g class="lane-label" ${l.team ? `data-team="${escH(l.team)}"` : ""} style="${l.team ? "" : "cursor:default"}"><rect x="${l.x}" y="${l.y}" width="${l.start}" height="${l.h}" rx="6" fill="${l.color}"/>
        <text transform="translate(${l.x + l.start / 2 + 5},${l.y + l.h / 2}) rotate(-90)" text-anchor="middle" fill="#fff" font-weight="700" font-size="${Math.min(13, (l.h - 10) / ((l.label.length + (l.team && !opts.editor ? 2 : 0)) * .62)).toFixed(1)}" font-family="Helvetica,Arial">${escH(l.label)}${l.team && !opts.editor ? " ⓘ" : ""}</text></g></g>`;
    }
    for (const e of lay.edges) {
      const t = CAT.edgeTypes[e.type] || CAT.edgeTypes.flow;
      const sel = opts.sel && opts.sel.kind === "edge" && opts.sel.id === e.id;
      const pts = e.pts.map(p => p.join(",")).join(" ");
      s += `<g class="edge ${sel ? "sel" : ""}" data-edge="${escH(e.id)}">`;
      if (opts.editor) s += `<polyline class="hit" fill="none" stroke="transparent" stroke-width="12" points="${pts}"/>`;
      s += `<polyline class="line" fill="none" stroke="${t.color}" stroke-width="${sel ? t.sw + 1.5 : t.sw}" ${t.dashed ? 'stroke-dasharray="6 4"' : ""} marker-end="url(#ar${t.color.slice(1)})" points="${pts}"/>`;
      if (opts.editor && sel) s += (e.wps || []).map((w, i) => { const ln = lay.byKey[w.lane]; return `<circle class="wp" data-wp="${i}" cx="${ln.x + w.x}" cy="${ln.y + w.y}" r="4"/>`; }).join("");
      s += `</g>`;
    }
    for (const e of lay.edges) if (e.label) {
      const [lx, ly] = labelPos(e), tw = e.label.length * 5.6 + 8;
      const lsel = opts.sel && opts.sel.kind === "edge" && opts.sel.id === e.id;
      s += `<g class="elabel ${lsel ? "sel" : ""}" data-edge="${escH(e.id)}"><rect x="${lx - tw / 2}" y="${ly - 8}" width="${tw}" height="15" rx="3" fill="#fff" opacity=".92"/><text x="${lx}" y="${ly + 3.5}" text-anchor="middle" font-size="11" font-family="Helvetica,Arial" fill="#555">${escH(e.label)}</text></g>`;
    }
    for (const n of flow.nodes) {
      const a = lay.abs[n.id], t = CAT.nodeTypes[n.type] || CAT.nodeTypes.action;
      const inset = t.shape === "rhombus" ? a.w * .2 : 0;
      const sel = (opts.sel && opts.sel.kind === "node" && opts.sel.id === n.id) || (opts.multi && opts.multi.has(n.id));
      s += `<g class="node ${opts.nodeClass ? opts.nodeClass(n) : ""} ${sel ? "sel" : ""}" data-node="${escH(n.id)}" ${n.team ? `data-team="${escH(n.team)}"` : ""}>${shape(n, a)}
        <foreignObject x="${a.x + inset}" y="${a.y}" width="${Math.max(10, a.w - inset * 2)}" height="${a.h}"><div xmlns="http://www.w3.org/1999/xhtml" class="nodetxt" ${t.fc ? `style="color:${t.fc}"` : ""}><div>${labelHtml(n.lines)}</div></div></foreignObject>`;
      const b = opts.badges && opts.badges[n.id];
      if (b) {
        const bw = b.length * 6.3 + 10, col = (lay.byKey[n.lane] || {}).color || "#5B6673";
        s += `<g class="badge" pointer-events="none"><rect x="${a.x + a.w - bw + 4}" y="${a.y - 8}" width="${bw}" height="15" rx="7.5" fill="${col}"/><text x="${a.x + a.w - bw / 2 + 4}" y="${a.y + 3}" text-anchor="middle" font-size="10" font-weight="700" fill="#fff" font-family="Helvetica,Arial">${escH(b)}</text></g>`;
      }
      if (opts.editor && sel && !(opts.multi && opts.multi.size > 1)) {
        s += `<rect class="rz" data-rz="1" x="${a.x + a.w - 5}" y="${a.y + a.h - 5}" width="10" height="10" rx="2"/>`;
        s += `<circle class="ch" data-ch="1" cx="${a.x + a.w + 14}" cy="${a.y + a.h / 2}" r="7"/><text class="ch-t" x="${a.x + a.w + 14}" y="${a.y + a.h / 2 + 4}" text-anchor="middle" pointer-events="none">→</text>`;
      }
      s += `</g>`;
    }
    if (opts.editor && opts.multi && opts.multi.size > 1) {
      const bs = [...opts.multi].map(id => lay.abs[id]).filter(Boolean);
      if (bs.length) {
        const gx = Math.min(...bs.map(b => b.x)) - 6, gy = Math.min(...bs.map(b => b.y)) - 6;
        const gw = Math.max(...bs.map(b => b.x + b.w)) + 6 - gx, gh = Math.max(...bs.map(b => b.y + b.h)) + 6 - gy;
        s += `<rect class="gbox" x="${gx}" y="${gy}" width="${gw}" height="${gh}" rx="4" pointer-events="none"/>
          <rect class="grz" x="${gx + gw - 6}" y="${gy + gh - 6}" width="12" height="12" rx="2"><title>Arraste para redimensionar a seleção proporcionalmente</title></rect>`;
      }
    }
    const W = x1 - x0 + pad * 2 + (opts.editor ? 30 : 0), H = y1 - y0 + pad * 2;
    return { svg: s, vb: [x0 - pad, y0 - pad, W, H], lay };
  }

  return { setCatalog, layout, svg, labelHtml, autoSides, labelAuto };
})();

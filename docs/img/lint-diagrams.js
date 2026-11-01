// Diagram linter: open an SVG from docs/img in a browser, paste this into the
// devtools console, and it returns "CLEAN" or a list of layout problems:
//   OVERFLOW      text not fully inside the box that contains it (6px side padding)
//   TEXT/BORDER   text crossing the edge of a box or panel it is not inside
//   TEXT/TEXT     two labels overlapping
//   TEXT/BADGE    a label overlapping a numbered step badge
//   SHAPE/SHAPE   two boxes partially overlapping
//   EDGE/TEXT     a connector drawn through a label
//   EDGE/SHAPE    a connector running through a box it does not start or end on
// Numbered badges (class "numt") sit on their edges by design and are exempt.
(function lintDiagram() {
  const R = (el) => { const b = el.getBBox(); return { x: b.x, y: b.y, w: b.width, h: b.height }; };
  const inside = (p, r, pad = 0) => p.x > r.x + pad && p.x < r.x + r.w - pad && p.y > r.y + pad && p.y < r.y + r.h - pad;
  const inter = (a, b, pad = 0) => a.x < b.x + b.w - pad && b.x < a.x + a.w - pad && a.y < b.y + b.h - pad && b.y < a.y + a.h - pad;
  const within = (a, r) => a.x >= r.x && a.y >= r.y && a.x + a.w <= r.x + r.w && a.y + a.h <= r.y + r.h;
  const texts = [...document.querySelectorAll('text')].map((t) => ({ badge: /numt/.test(t.getAttribute('class') || ''), s: t.textContent.trim().slice(0, 40), b: R(t) }));
  const circles = [...document.querySelectorAll('circle')].map(R);
  const rects = [...document.querySelectorAll('rect')].map((r) => ({ b: R(r), cls: r.getAttribute('class') || '' }));
  const canvas = rects.reduce((a, r) => (!a || r.b.w * r.b.h > a.b.w * a.b.h ? r : a), null);
  const panels = rects.filter((r) => /zone|cluster/.test(r.cls));
  const shapes = rects.filter((r) => r !== canvas && !panels.includes(r) && r.b.h > 22);
  const issues = [];
  for (const t of texts) {
    if (!within(t.b, { x: canvas.b.x + 8, y: canvas.b.y + 8, w: canvas.b.w - 16, h: canvas.b.h - 16 })) issues.push(`OUTSIDE CANVAS "${t.s}"`);
    if (t.badge) continue;
    const c = { x: t.b.x + t.b.w / 2, y: t.b.y + t.b.h / 2 };
    const cont = shapes.concat(panels).filter((r) => inside(c, r.b)).sort((a, b) => a.b.w * a.b.h - b.b.w * b.b.h);
    if (cont.length) {
      const r = cont[0].b;
      if (t.b.x < r.x + 6 || t.b.x + t.b.w > r.x + r.w - 6 || t.b.y < r.y + 1 || t.b.y + t.b.h > r.y + r.h - 1) issues.push(`OVERFLOW "${t.s}"`);
    }
    for (const s of shapes.concat(panels)) {
      if (cont[0] && s === cont[0]) continue;
      if (inter(t.b, s.b, 1) && !within(t.b, s.b)) issues.push(`TEXT/BORDER "${t.s}" x ${s.cls || 'box'}@${s.b.x},${s.b.y}`);
    }
    for (const cb of circles) if (inter(t.b, cb, 1)) issues.push(`TEXT/BADGE "${t.s}"`);
  }
  const plain = texts.filter((t) => !t.badge);
  for (let i = 0; i < plain.length; i++) for (let j = i + 1; j < plain.length; j++)
    if (inter(plain[i].b, plain[j].b, 1)) issues.push(`TEXT/TEXT "${plain[i].s}" x "${plain[j].s}"`);
  for (let i = 0; i < shapes.length; i++) for (let j = i + 1; j < shapes.length; j++) {
    const a = shapes[i].b, b = shapes[j].b;
    if (inter(a, b, 0) && !within(a, b) && !within(b, a)) issues.push(`SHAPE/SHAPE ${a.x},${a.y} x ${b.x},${b.y}`);
  }
  const edges = [...document.querySelectorAll('path, line')].filter((p) => /edge/.test(p.getAttribute('class') || ''));
  for (const p of edges) {
    const L = p.getTotalLength(); const pts = [];
    for (let d = 0; d <= L; d += 2) pts.push(p.getPointAtLength(d));
    const id = (p.getAttribute('d') || `line ${p.getAttribute('x1')},${p.getAttribute('y1')}`).slice(0, 28);
    for (const t of plain) if (pts.some((q) => inside(q, t.b, 0.5))) issues.push(`EDGE/TEXT [${id}] "${t.s}"`);
    for (const s of shapes) { const n = pts.filter((q) => inside(q, s.b, 3)).length; if (n > 3) issues.push(`EDGE/SHAPE [${id}] ${n * 2}px in box@${s.b.x},${s.b.y}`); }
  }
  return { texts: texts.length, edges: edges.length, issues: issues.length ? issues : ['CLEAN'] };
})();

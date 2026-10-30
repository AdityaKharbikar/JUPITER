/* JUPITER 3D Explainer viewer - dependency-free WebGL (works offline, no CDN).
   Reads a JSON spec (see jupiter/explainer/schema.py) from <script id="spec">. */
(function () {
'use strict';
const SPEC = JSON.parse(document.getElementById('spec').textContent);
const $ = (s, r) => (r || document).querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const ease = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

/* ------------------------------------------------------------ vector / matrix */
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const len = a => Math.hypot(a[0], a[1], a[2]);
const norm = a => { const l = len(a) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };
function perspective(fovy, asp, n, f) {
  const t = 1 / Math.tan(fovy / 2), m = new Float32Array(16);
  m[0] = t / asp; m[5] = t; m[10] = (f + n) / (n - f); m[11] = -1; m[14] = 2 * f * n / (n - f); return m;
}
function lookAt(e, c, up) {
  const z = norm(sub(e, c)), x = norm(cross(up, z)), y = cross(z, x), m = new Float32Array(16);
  m[0] = x[0]; m[1] = y[0]; m[2] = z[0]; m[4] = x[1]; m[5] = y[1]; m[6] = z[1]; m[8] = x[2]; m[9] = y[2]; m[10] = z[2];
  m[12] = -dot(x, e); m[13] = -dot(y, e); m[14] = -dot(z, e); m[15] = 1; return m;
}
function mmul(a, b) {
  const o = new Float32Array(16);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
    o[j * 4 + i] = a[i] * b[j * 4] + a[4 + i] * b[j * 4 + 1] + a[8 + i] * b[j * 4 + 2] + a[12 + i] * b[j * 4 + 3];
  }
  return o;
}
// 3x3 rotation as row-major [[..],[..],[..]] helpers
function rotEuler(rx, ry, rz) {            // degrees, R = Rz*Ry*Rx
  const d = Math.PI / 180, cx = Math.cos(rx * d), sx = Math.sin(rx * d), cy = Math.cos(ry * d), sy = Math.sin(ry * d), cz = Math.cos(rz * d), sz = Math.sin(rz * d);
  return [[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
          [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
          [-sy, cy * sx, cy * cx]];
}
function rotAxis(ax, ang) {                // Rodrigues
  const [x, y, z] = norm(ax), c = Math.cos(ang), s = Math.sin(ang), t = 1 - c;
  return [[t * x * x + c, t * x * y - s * z, t * x * z + s * y],
          [t * x * y + s * z, t * y * y + c, t * y * z - s * x],
          [t * x * z - s * y, t * y * z + s * x, t * z * z + c]];
}
const mv = (R, v) => [R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2], R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2], R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2]];
const mvT = (R, v) => [R[0][0] * v[0] + R[1][0] * v[1] + R[2][0] * v[2], R[0][1] * v[0] + R[1][1] * v[1] + R[2][1] * v[2], R[0][2] * v[0] + R[1][2] * v[1] + R[2][2] * v[2]];
const I3 = [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
function hex(c) {
  c = String(c || '#8899aa').replace('#', '');
  if (c.length === 3) c = c.split('').map(x => x + x).join('');
  const n = parseInt(c, 16); if (isNaN(n)) return [.53, .6, .67];
  return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
}

/* ------------------------------------------------------------ geometry */
class Mesh {
  constructor() { this.p = []; this.n = []; this.c = []; this.i = []; }
  vert(p, n, c) { this.p.push(p[0], p[1], p[2]); this.n.push(n[0], n[1], n[2]); this.c.push(c[0], c[1], c[2]); return this.p.length / 3 - 1; }
  quad(a, b, c, d) { this.i.push(a, b, c, a, c, d); }
}
function addPrim(mesh, pr, baseColor) {
  const t = pr.t || 'box', s = pr.s || [1, 1, 1], col = hex(pr.c || baseColor), R = rotEuler(...(pr.r || [0, 0, 0])), P = pr.p || [0, 0, 0];
  const V = (p, n) => mesh.vert(add(mv(R, p), P), mv(R, norm(n)), col);
  if (t === 'box') {
    const [sx, sy, sz] = s.length === 1 ? [s[0], s[0], s[0]] : s, x = sx / 2, y = sy / 2, z = sz / 2;
    const F = [[[1, 0, 0], [[x, -y, -z], [x, y, -z], [x, y, z], [x, -y, z]]], [[-1, 0, 0], [[-x, -y, z], [-x, y, z], [-x, y, -z], [-x, -y, -z]]],
      [[0, 1, 0], [[-x, y, -z], [-x, y, z], [x, y, z], [x, y, -z]]], [[0, -1, 0], [[-x, -y, z], [-x, -y, -z], [x, -y, -z], [x, -y, z]]],
      [[0, 0, 1], [[-x, -y, z], [x, -y, z], [x, y, z], [-x, y, z]]], [[0, 0, -1], [[x, -y, -z], [-x, -y, -z], [-x, y, -z], [x, y, -z]]]];
    for (const [n, vs] of F) { const k = vs.map(v => V(v, n)); mesh.quad(k[0], k[1], k[2], k[3]); }
  } else if (t === 'cyl' || t === 'cone' || t === 'tube') {
    let rT, rB, h, rIn = 0;
    if (t === 'cone') { rB = s[0]; rT = 0; h = s[1]; }
    else if (t === 'tube') { rT = rB = s[0]; rIn = s[1]; h = s[2]; }
    else if (s.length === 2) { rT = rB = s[0]; h = s[1]; } else { rT = s[0]; rB = s[1]; h = s[2]; }
    const seg = pr.seg || (Math.max(rT, rB) > 0.25 ? 36 : 20), y0 = -h / 2, y1 = h / 2, slope = (rB - rT) / h;
    for (let k = 0; k < seg; k++) {
      const a0 = k / seg * Math.PI * 2, a1 = (k + 1) / seg * Math.PI * 2;
      const c0 = Math.cos(a0), s0 = Math.sin(a0), c1 = Math.cos(a1), s1 = Math.sin(a1);
      const q = [V([c0 * rB, y0, s0 * rB], [c0, slope, s0]), V([c1 * rB, y0, s1 * rB], [c1, slope, s1]), V([c1 * rT, y1, s1 * rT], [c1, slope, s1]), V([c0 * rT, y1, s0 * rT], [c0, slope, s0])];
      mesh.quad(q[0], q[1], q[2], q[3]);
      if (t === 'tube') {
        const q2 = [V([c0 * rIn, y0, s0 * rIn], [-c0, 0, -s0]), V([c1 * rIn, y0, s1 * rIn], [-c1, 0, -s1]), V([c1 * rIn, y1, s1 * rIn], [-c1, 0, -s1]), V([c0 * rIn, y1, s0 * rIn], [-c0, 0, -s0])];
        mesh.quad(q2[0], q2[1], q2[2], q2[3]);
        const top = [V([c0 * rT, y1, s0 * rT], [0, 1, 0]), V([c1 * rT, y1, s1 * rT], [0, 1, 0]), V([c1 * rIn, y1, s1 * rIn], [0, 1, 0]), V([c0 * rIn, y1, s0 * rIn], [0, 1, 0])];
        mesh.quad(top[0], top[1], top[2], top[3]);
        const bot = [V([c0 * rB, y0, s0 * rB], [0, -1, 0]), V([c1 * rB, y0, s1 * rB], [0, -1, 0]), V([c1 * rIn, y0, s1 * rIn], [0, -1, 0]), V([c0 * rIn, y0, s0 * rIn], [0, -1, 0])];
        mesh.quad(bot[0], bot[1], bot[2], bot[3]);
      } else {
        if (rT > 0) { const cc = V([0, y1, 0], [0, 1, 0]), a = V([c0 * rT, y1, s0 * rT], [0, 1, 0]), b = V([c1 * rT, y1, s1 * rT], [0, 1, 0]); mesh.i.push(cc, b, a); }
        if (rB > 0) { const cc = V([0, y0, 0], [0, -1, 0]), a = V([c0 * rB, y0, s0 * rB], [0, -1, 0]), b = V([c1 * rB, y0, s1 * rB], [0, -1, 0]); mesh.i.push(cc, a, b); }
      }
    }
  } else if (t === 'sphere') {
    const [rx, ry, rz] = s.length === 1 ? [s[0], s[0], s[0]] : s, nl = 16, nn = 28;
    const idx = [];
    for (let a = 0; a <= nl; a++) {
      const th = a / nl * Math.PI, st = Math.sin(th), ct = Math.cos(th); idx.push([]);
      for (let b = 0; b <= nn; b++) {
        const ph = b / nn * Math.PI * 2, x = st * Math.cos(ph), z = st * Math.sin(ph);
        idx[a].push(V([x * rx, ct * ry, z * rz], [x / rx, ct / ry, z / rz]));
      }
    }
    for (let a = 0; a < nl; a++) for (let b = 0; b < nn; b++) mesh.quad(idx[a][b], idx[a + 1][b], idx[a + 1][b + 1], idx[a][b + 1]);
  } else if (t === 'torus') {
    const Rr = s[0], r = s[1], nm = 36, nt = 14, idx = [];
    for (let a = 0; a <= nm; a++) {
      const u = a / nm * Math.PI * 2, cu = Math.cos(u), su = Math.sin(u); idx.push([]);
      for (let b = 0; b <= nt; b++) {
        const v = b / nt * Math.PI * 2, cv = Math.cos(v), sv = Math.sin(v);
        idx[a].push(V([(Rr + r * cv) * cu, r * sv, (Rr + r * cv) * su], [cv * cu, sv, cv * su]));
      }
    }
    for (let a = 0; a < nm; a++) for (let b = 0; b < nt; b++) mesh.quad(idx[a][b], idx[a + 1][b], idx[a + 1][b + 1], idx[a][b + 1]);
  }
}

/* ------------------------------------------------------------ build parts */
const parts = (SPEC.parts || []).map((sp, i) => {
  const mesh = new Mesh();
  (sp.prims && sp.prims.length ? sp.prims : [{ t: 'box', s: [.5, .5, .5] }]).forEach(pr => addPrim(mesh, pr, sp.color));
  let mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
  for (let k = 0; k < mesh.p.length; k += 3) for (let a = 0; a < 3; a++) { mn[a] = Math.min(mn[a], mesh.p[k + a]); mx[a] = Math.max(mx[a], mesh.p[k + a]); }
  return {
    i, sp, id: sp.id, name: sp.name, mesh, mn, mx, ctr: sp.bound ? [0, 0, 0] : mul(add(mn, mx), .5), rad: sp.bound || len(sub(mx, mn)) / 2,
    pos: sp.pos || [0, 0, 0], exp: sp.explode || [0, 0, 0], a: 1, R: I3, off: [0, 0, 0], alpha: 1, tint: 0,
    anim: sp.anim || null, step: sp.step == null ? i : sp.step, conns: []
  };
});
const byId = {}; parts.forEach(p => byId[p.id] = p);
const links = (SPEC.links || []).filter(l => byId[l.a] && byId[l.b]);
links.forEach(l => { byId[l.a].conns.push({ id: l.b, label: l.label || '' }); byId[l.b].conns.push({ id: l.a, label: l.label || '' }); });

/* ------------------------------------------------------------ state */
const S = { t: 0, target: 1, auto: SPEC.kind !== 'concept', labels: parts.length <= 18, xray: false, isolate: false, hover: null, sel: null,
  yaw: 0.7, pitch: 0.38, dist: 12, tgt: [0, 0, 0], vy: 0, vp: 0, play: null, mouse: null, dirty: false, time: 0, drag: null };
const concept = SPEC.kind === 'concept';

/* ------------------------------------------------------------ DOM */
const root = $('#app');
const canvas = el('canvas', 'gl'), ov = el('canvas', 'ov');
root.append(canvas, ov);
const tip = el('div', 'tip'); root.append(tip);
const side = el('div', 'side');
const badgeClass = SPEC.curated ? 'ok' : 'warn';
const badgeText = SPEC.curated ? 'CURATED MODEL' : (concept ? 'AI-GENERATED CONCEPT DIAGRAM' : 'AI-GENERATED · APPROXIMATE');
side.innerHTML = `<div class="brand">JUPITER · 3D EXPLAINER</div><h1>${esc(SPEC.title)}</h1>
<div class="badge ${badgeClass}">${badgeText}</div><p class="sum">${esc(SPEC.summary || '')}</p>
${SPEC.disclaimer ? `<p class="disc">${esc(SPEC.disclaimer)}</p>` : ''}<div class="hd">${concept ? 'COMPONENTS' : 'PARTS'} (${parts.length})</div><div class="plist"></div>
<div class="meta">${esc(SPEC.meta_line || '')}</div>`;
root.append(side);
const plist = $('.plist', side);
const rows = parts.map(p => {
  const r = el('div', 'row', `<i style="background:${esc(p.sp.color || '#8899aa')}"></i><span>${p.i + 1}. ${esc(p.name)}</span>`);
  r.onmouseenter = () => { S.hover = p; S.dirty = true; }; r.onmouseleave = () => { if (S.hover === p) S.hover = null; };
  r.onclick = () => select(S.sel === p ? null : p);
  plist.append(r); return r;
});
const card = el('div', 'card'); card.style.display = 'none'; root.append(card);
const bar = el('div', 'bar');
bar.innerHTML = `<label class="sl">${concept ? 'SPREAD' : 'EXPLODE'}<input id="ex" type="range" min="0" max="1" step="0.005" value="0"></label>
<button id="bPlay" title="Space">▶ ${concept ? 'Walkthrough' : 'Assembly'}</button><button id="bRot" class="${S.auto ? 'on' : ''}" title="R">Auto-rotate</button>
<button id="bLab" class="${S.labels ? 'on' : ''}" title="L">Labels</button><button id="bXr" title="X">X-ray</button><button id="bIso" title="I">Isolate</button><button id="bRst">Reset view</button>`;
root.append(bar);
const cap = el('div', 'cap'); cap.style.display = 'none'; root.append(cap);
const errBox = el('div', 'err'); errBox.style.display = 'none'; root.append(errBox);

/* ------------------------------------------------------------ WebGL */
let gl = canvas.getContext('webgl', { antialias: true, alpha: false, preserveDrawingBuffer: true }) || canvas.getContext('experimental-webgl');
let prog, U, A, floorBuf, floorN = 0;
const VS = `attribute vec3 aPos;attribute vec3 aNor;attribute vec3 aCol;uniform mat4 uVP;uniform vec3 uOff;uniform mat3 uRot;
varying vec3 vN;varying vec3 vC;varying vec3 vW;
void main(){vec3 w=uRot*aPos+uOff;vW=w;vN=uRot*aNor;vC=aCol;gl_Position=uVP*vec4(w,1.0);}`;
const FS = `precision mediump float;varying vec3 vN;varying vec3 vC;varying vec3 vW;uniform vec3 uEye;uniform vec4 uTint;uniform float uAlpha;uniform float uFlat;uniform vec3 uFlatCol;
void main(){
 if(uFlat>.5){gl_FragColor=vec4(uFlatCol,uAlpha);return;}
 vec3 N=normalize(vN);vec3 V=normalize(uEye-vW);if(dot(N,V)<0.0)N=-N;
 vec3 L1=normalize(vec3(.5,.9,.6)),L2=normalize(vec3(-.7,.3,-.5)),L3=normalize(vec3(-.3,-.6,.7));
 float d1=max(dot(N,L1),0.),d2=max(dot(N,L2),0.),d3=max(dot(N,L3),0.);
 vec3 hemi=mix(vec3(.10,.12,.17),vec3(.42,.5,.62),N.y*.5+.5);
 vec3 col=vC*(hemi*.85+d1*.56+d2*.22+d3*.12);
 float sp=pow(max(dot(N,normalize(L1+V)),0.),48.)*.35;
 float fr=pow(1.-max(dot(N,V),0.),2.6);
 col+=vec3(sp)+vec3(.12,.55,.75)*fr*.42;
 col=mix(col,uTint.rgb,uTint.a);
 gl_FragColor=vec4(col,uAlpha);}`;
function sh(type, src) { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s)); return s; }
let glOK = !!gl;
if (gl) {
  try {
    prog = gl.createProgram(); gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS)); gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS)); gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);
    U = {}; ['uVP', 'uOff', 'uRot', 'uEye', 'uTint', 'uAlpha', 'uFlat', 'uFlatCol'].forEach(n => U[n] = gl.getUniformLocation(prog, n));
    A = { p: gl.getAttribLocation(prog, 'aPos'), n: gl.getAttribLocation(prog, 'aNor'), c: gl.getAttribLocation(prog, 'aCol') };
    parts.forEach(p => {
      const m = p.mesh, mk = (arr, T, tgt) => { const b = gl.createBuffer(); gl.bindBuffer(tgt, b); gl.bufferData(tgt, new T(arr), gl.STATIC_DRAW); return b; };
      const big = m.p.length / 3 > 65000; if (big) throw new Error('mesh too large');
      p.bp = mk(m.p, Float32Array, gl.ARRAY_BUFFER); p.bn = mk(m.n, Float32Array, gl.ARRAY_BUFFER); p.bc = mk(m.c, Float32Array, gl.ARRAY_BUFFER);
      p.bi = mk(m.i, Uint16Array, gl.ELEMENT_ARRAY_BUFFER); p.ni = m.i.length;
    });
    gl.enable(gl.DEPTH_TEST); gl.disable(gl.CULL_FACE);
  } catch (e) { glOK = false; errBox.textContent = 'WebGL error: ' + e.message; errBox.style.display = 'block'; }
} else { errBox.textContent = 'WebGL is not available here. Open this file in Chrome or Edge.'; errBox.style.display = 'block'; }

/* ------------------------------------------------------------ framing */
let floorY = 0, sceneR = 5;
function worldBounds(t) {
  let mn = [1e9, 1e9, 1e9], mx = [-1e9, -1e9, -1e9];
  parts.forEach(p => {
    const o = add(p.pos, mul(p.exp, t));
    if (p.anim && p.anim.type === 'orbit') { const rr = Math.hypot(o[0], o[2]) + p.rad; mn[0] = Math.min(mn[0], -rr); mx[0] = Math.max(mx[0], rr); mn[2] = Math.min(mn[2], -rr); mx[2] = Math.max(mx[2], rr); mn[1] = Math.min(mn[1], o[1] - p.rad); mx[1] = Math.max(mx[1], o[1] + p.rad); return; }
    for (let a = 0; a < 3; a++) { mn[a] = Math.min(mn[a], o[a] + p.ctr[a] - p.rad); mx[a] = Math.max(mx[a], o[a] + p.ctr[a] + p.rad); }
  });
  return [mn, mx];
}
function frame() {
  const [mn, mx] = worldBounds(1), [m0, m1] = worldBounds(0);
  const c = mul(add(mn, mx), .5); S.tgt = [c[0], c[1], c[2]]; sceneR = len(sub(mx, mn)) / 2;
  floorY = Math.min(mn[1], m0[1]) - 0.15;
  const cam = SPEC.camera || {}; S.dist = Math.max(sceneR * (cam.zoom || 2.0), 4); S.yaw = cam.yaw == null ? 0.7 : cam.yaw; S.pitch = cam.pitch == null ? 0.38 : cam.pitch; S.vy = S.vp = 0;
  if (glOK) buildFloor();
}
function buildFloor() {
  const n = Math.ceil(sceneR * 1.5), step = Math.max(.5, Math.round(sceneR / 8 * 2) / 2), v = [], ext = Math.ceil(sceneR * 1.6 / step) * step;
  for (let x = -ext; x <= ext + 1e-6; x += step) { v.push(x + S.tgt[0], floorY, -ext + S.tgt[2], x + S.tgt[0], floorY, ext + S.tgt[2]); v.push(-ext + S.tgt[0], floorY, x + S.tgt[2], ext + S.tgt[0], floorY, x + S.tgt[2]); }
  floorBuf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, floorBuf); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(v), gl.STATIC_DRAW); floorN = v.length / 3;
}

/* ------------------------------------------------------------ camera */
let W = 1, H = 1, VP = new Float32Array(16), EYE = [0, 0, 1], FWD = [0, 0, -1], RIGHT = [1, 0, 0], UP = [0, 1, 0];
const FOV = 0.78; let SHIFT = 0;
function camera() {
  const cp = Math.cos(S.pitch), e = [S.tgt[0] + S.dist * cp * Math.sin(S.yaw), S.tgt[1] + S.dist * Math.sin(S.pitch), S.tgt[2] + S.dist * cp * Math.cos(S.yaw)];
  EYE = e; FWD = norm(sub(S.tgt, e)); RIGHT = norm(cross(FWD, [0, 1, 0])); UP = cross(RIGHT, FWD);
  SHIFT = W > 760 ? 296 / W : 0;          // keep the model centred in the space right of the side panel
  const Pm = perspective(FOV, W / H, 0.1, 400); Pm[8] = -SHIFT;
  VP = mmul(Pm, lookAt(e, S.tgt, [0, 1, 0]));
}
function project(p) {
  const x = VP[0] * p[0] + VP[4] * p[1] + VP[8] * p[2] + VP[12], y = VP[1] * p[0] + VP[5] * p[1] + VP[9] * p[2] + VP[13],
    w = VP[3] * p[0] + VP[7] * p[1] + VP[11] * p[2] + VP[15];
  if (w <= 0.01) return null;
  return [(x / w * .5 + .5) * W, (1 - (y / w * .5 + .5)) * H, w];
}

/* ------------------------------------------------------------ per-frame update */
function updateParts(dt) {
  S.time += dt;
  const ex = S.t;
  parts.forEach(p => {
    let off = add(p.pos, mul(p.exp, ex * p.a)), R = I3;
    const an = p.anim;
    if (an && an.type === 'spin') R = rotAxis(an.axis || [0, 1, 0], S.time * (an.speed || 40) * Math.PI / 180);
    if (an && an.type === 'orbit') { const ang = (S.time * (an.speed || 10) + (an.phase || 0)) * Math.PI / 180, Ro = rotAxis([0, 1, 0], ang); off = mv(Ro, off); R = Ro; }
    if (an && an.type === 'pulse') { const ph = Math.max(0, Math.sin((S.time + (an.phase || 0)) * Math.PI * 2 * (an.rate || 1.1))), k = 1 + (an.amp || .05) * ph * ph * ph; R = [[k, 0, 0], [0, k, 0], [0, 0, k]]; }
    if (an && an.type === 'swing') { R = rotAxis(an.axis || [0, 0, 1], Math.sin(S.time * (an.speed || 1.5)) * (an.amp || 20) * Math.PI / 180); }
    if (an && an.type === 'slide') { const d = an.dir || [0, 1, 0], o = Math.sin(S.time * (an.speed || 3)) * (an.amp || .3); off = add(off, mul(d, o)); }
    p.off = off; p.R = R;
    const sel = S.sel, hov = S.hover;
    let tint = 0; if (p === hov) tint = .38; if (p === sel) tint = .5;
    p.tint += (tint - p.tint) * Math.min(1, dt * 14);
    let al = S.xray ? .34 : 1; if (S.isolate && sel && p !== sel && !sel.conns.some(c => c.id === p.id)) al = Math.min(al, .1);
    if (S.xray && (p === sel || p === hov)) al = .8;
    p.alpha += (al - p.alpha) * Math.min(1, dt * 10);
    p.cw = add(off, mv(R, p.ctr));
  });
  rows.forEach((r, i) => { r.classList.toggle('sel', parts[i] === S.sel); r.classList.toggle('hov', parts[i] === S.hover); });
}

/* ------------------------------------------------------------ draw */
function drawGL() {
  if (!glOK) return;
  const dpr = canvas.width / W; gl.viewport(0, 0, canvas.width, canvas.height);
  gl.clearColor(.027, .05, .09, 1); gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.uniformMatrix4fv(U.uVP, false, VP); gl.uniform3fv(U.uEye, EYE);
  // floor grid
  gl.uniform1f(U.uFlat, 1); gl.uniform3f(U.uFlatCol, .09, .2, .3); gl.uniform1f(U.uAlpha, 1); gl.uniform3f(U.uOff, 0, 0, 0);
  gl.uniformMatrix3fv(U.uRot, false, [1, 0, 0, 0, 1, 0, 0, 0, 1]);
  gl.bindBuffer(gl.ARRAY_BUFFER, floorBuf); gl.enableVertexAttribArray(A.p); gl.vertexAttribPointer(A.p, 3, gl.FLOAT, false, 0, 0);
  gl.disableVertexAttribArray(A.n); gl.disableVertexAttribArray(A.c);
  gl.drawArrays(gl.LINES, 0, floorN);
  gl.uniform1f(U.uFlat, 0);
  const op = parts.filter(p => p.alpha > .985), tr = parts.filter(p => p.alpha <= .985).sort((a, b) => len(sub(b.cw, EYE)) - len(sub(a.cw, EYE)));
  gl.enableVertexAttribArray(A.n); gl.enableVertexAttribArray(A.c);
  const draw = (p, blend) => {
    if (blend) { gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA); gl.depthMask(false); } else { gl.disable(gl.BLEND); gl.depthMask(true); }
    const R = p.R; gl.uniformMatrix3fv(U.uRot, false, [R[0][0], R[1][0], R[2][0], R[0][1], R[1][1], R[2][1], R[0][2], R[1][2], R[2][2]]);
    gl.uniform3fv(U.uOff, p.off); gl.uniform4f(U.uTint, .25, .85, 1, p.tint); gl.uniform1f(U.uAlpha, p.alpha);
    gl.bindBuffer(gl.ARRAY_BUFFER, p.bp); gl.vertexAttribPointer(A.p, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, p.bn); gl.vertexAttribPointer(A.n, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, p.bc); gl.vertexAttribPointer(A.c, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, p.bi); gl.drawElements(gl.TRIANGLES, p.ni, gl.UNSIGNED_SHORT, 0);
  };
  op.forEach(p => draw(p, false)); tr.forEach(p => draw(p, true));
  gl.depthMask(true); gl.disable(gl.BLEND);
}

const ctx = ov.getContext('2d');
function drawOverlay() {
  const dpr = ov.width / W; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); ctx.clearRect(0, 0, W, H);
  const focus = S.sel || S.hover;
  // links
  const linkVis = concept ? 1 : clamp((S.t - .12) / .5, 0, 1);
  if (linkVis > 0.01) {
    ctx.lineWidth = 1.2; ctx.font = '11px Segoe UI, Arial';
    links.forEach((l, li) => {
      const A_ = byId[l.a], B_ = byId[l.b], pa = project(A_.cw), pb = project(B_.cw); if (!pa || !pb) return;
      const hot = focus && (focus === A_ || focus === B_);
      const dim = S.isolate && S.sel && !hot ? .25 : 1;
      ctx.globalAlpha = (hot ? .95 : .45) * linkVis * dim;
      ctx.strokeStyle = hot ? '#6ee7ff' : '#3aa6d6'; ctx.setLineDash(hot ? [] : [5, 5]);
      ctx.beginPath(); ctx.moveTo(pa[0], pa[1]); ctx.lineTo(pb[0], pb[1]); ctx.stroke(); ctx.setLineDash([]);
      if (SPEC.directed || l.dir) { // arrow head near b
        const dx = pb[0] - pa[0], dy = pb[1] - pa[1], L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L, tx = pb[0] - ux * 18, ty = pb[1] - uy * 18;
        ctx.fillStyle = ctx.strokeStyle; ctx.beginPath(); ctx.moveTo(tx, ty); ctx.lineTo(tx - ux * 9 - uy * 4.5, ty - uy * 9 + ux * 4.5); ctx.lineTo(tx - ux * 9 + uy * 4.5, ty - uy * 9 - ux * 4.5); ctx.closePath(); ctx.fill();
      }
      if (SPEC.flow || l.flow) { // travelling pulse
        const f = ((S.time * .35 + li * .137) % 1); ctx.globalAlpha = .95 * linkVis * dim; ctx.fillStyle = '#9ef0ff';
        ctx.beginPath(); ctx.arc(pa[0] + (pb[0] - pa[0]) * f, pa[1] + (pb[1] - pa[1]) * f, 3.2, 0, 7); ctx.fill();
      }
      if (hot && l.label) { ctx.globalAlpha = 1; ctx.fillStyle = '#bfefff'; ctx.textAlign = 'center'; ctx.fillText(l.label, (pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2 - 5); }
    });
    ctx.globalAlpha = 1;
  }
  // labels with greedy de-overlap
  const placed = [];
  const order = parts.map(p => ({ p, s: project(p.cw) })).filter(o => o.s).sort((a, b) => a.s[2] - b.s[2]);
  ctx.font = '12px Segoe UI, Arial'; ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
  order.forEach(({ p, s }, k) => {
    const isF = p === focus, show = isF || S.labels;
    // dot
    if (show) { ctx.fillStyle = isF ? '#ffffff' : '#6ee7ff'; ctx.beginPath(); ctx.arc(s[0], s[1], isF ? 3.6 : 2.4, 0, 7); ctx.fill(); }
    if (!show) return;
    if (S.isolate && S.sel && p !== S.sel && !S.sel.conns.some(c => c.id === p.id)) return;
    const txt = (p.i + 1) + ' ' + p.name, w = ctx.measureText(txt).width + 14, h = 18;
    let x = s[0] + 8, y = s[1] - 16, tries = 0;
    const hit = r => placed.some(q => r[0] < q[0] + q[2] && r[0] + r[2] > q[0] && r[1] < q[1] + q[3] && r[1] + r[3] > q[1]);
    while (hit([x, y - h / 2, w, h]) && tries < 14) { y += (tries % 2 ? -1 : 1) * (tries + 2) * 5; tries++; }
    if (tries >= 14 && !isF) return;
    placed.push([x, y - h / 2, w, h]);
    ctx.globalAlpha = isF ? 1 : .86; ctx.fillStyle = isF ? 'rgba(22,70,100,.95)' : 'rgba(8,18,32,.78)'; ctx.strokeStyle = isF ? '#6ee7ff' : 'rgba(80,170,220,.55)'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.roundRect ? ctx.roundRect(x, y - h / 2, w, h, 5) : ctx.rect(x, y - h / 2, w, h); ctx.fill(); ctx.stroke();
    ctx.strokeStyle = 'rgba(110,231,255,.5)'; ctx.beginPath(); ctx.moveTo(s[0], s[1]); ctx.lineTo(x, y); ctx.stroke();
    ctx.fillStyle = isF ? '#fff' : '#cfeefa'; ctx.fillText(txt, x + 7, y + .5); ctx.globalAlpha = 1;
  });
}

/* ------------------------------------------------------------ interaction */
function rayFromMouse(mx, my) {
  const nx = mx / W * 2 - 1 - SHIFT, ny = 1 - my / H * 2, th = Math.tan(FOV / 2);
  return { o: EYE, d: norm(add(add(FWD, mul(RIGHT, nx * th * (W / H))), mul(UP, ny * th))) };
}
function hitPart(ray) {
  let best = null, bt = 1e9;
  for (const p of parts) {
    if (p.alpha < .15) continue;
    // bounding sphere reject
    const oc = sub(ray.o, p.cw), b = dot(oc, ray.d), c = dot(oc, oc) - (p.rad * 1.05) ** 2; if (b > 0 && c > 0) continue; if (b * b - c < 0) continue;
    const o = mvT(p.R, sub(ray.o, p.off)), d = mvT(p.R, ray.d), P = p.mesh.p, I = p.mesh.i;
    for (let k = 0; k < I.length; k += 3) {
      const a = I[k] * 3, bb = I[k + 1] * 3, cc = I[k + 2] * 3;
      const e1 = [P[bb] - P[a], P[bb + 1] - P[a + 1], P[bb + 2] - P[a + 2]], e2 = [P[cc] - P[a], P[cc + 1] - P[a + 1], P[cc + 2] - P[a + 2]];
      const h = cross(d, e2), det = dot(e1, h); if (Math.abs(det) < 1e-9) continue;
      const f = 1 / det, s = [o[0] - P[a], o[1] - P[a + 1], o[2] - P[a + 2]], u = f * dot(s, h); if (u < 0 || u > 1) continue;
      const q = cross(s, e1), v = f * dot(d, q); if (v < 0 || u + v > 1) continue;
      const t = f * dot(e2, q); if (t > 1e-4 && t < bt) { bt = t; best = p; }
    }
  }
  return best;
}
function select(p) {
  S.sel = p;
  if (!p) { card.style.display = 'none'; return; }
  const conns = p.conns.map(c => `<span class="chip" data-id="${esc(c.id)}">${esc(byId[c.id].name)}${c.label ? ' · ' + esc(c.label) : ''}</span>`).join('') || '<span class="dim">none listed</span>';
  card.innerHTML = `<div class="cn">${p.i + 1}. ${esc(p.name)}</div>${p.sp.group ? `<div class="grp">${esc(p.sp.group)}</div>` : ''}
   <div class="pp">${esc(p.sp.desc || '')}</div><div class="hd">CONNECTED TO</div><div class="chips">${conns}</div>
   ${p.sp.stylized ? '<div class="sty">Stylized shape - not an exact model of this part.</div>' : ''}`;
  card.style.display = 'block';
  card.querySelectorAll('.chip').forEach(c => c.onclick = () => select(byId[c.dataset.id]));
}
function onMove(e) {
  const r = canvas.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
  if (S.drag) {
    const dx = x - S.drag.x, dy = y - S.drag.y;
    if (S.drag.btn === 2 || e.shiftKey) { const k = S.dist * .0016; S.tgt = add(S.tgt, add(mul(RIGHT, -dx * k), mul(UP, dy * k))); }
    else { S.yaw -= dx * .0075; S.pitch = clamp(S.pitch + dy * .0075, -1.45, 1.45); S.vy = -dx * .0075; S.vp = dy * .0075; }
    if (Math.abs(x - S.drag.sx) + Math.abs(y - S.drag.sy) > 4) S.drag.moved = true;
    S.drag.x = x; S.drag.y = y;
  }
  S.mouse = [x, y]; S.dirty = true;
}
canvas.addEventListener('mousedown', e => { const r = canvas.getBoundingClientRect(); S.drag = { x: e.clientX - r.left, y: e.clientY - r.top, sx: e.clientX - r.left, sy: e.clientY - r.top, btn: e.button, moved: false }; S.auto = false; syncBtn(); });
window.addEventListener('mouseup', e => {
  if (S.drag && !S.drag.moved && e.target === canvas) { const r = canvas.getBoundingClientRect(); const h = hitPart(rayFromMouse(e.clientX - r.left, e.clientY - r.top)); select(h && h !== S.sel ? h : null); }
  S.drag = null;
});
window.addEventListener('mousemove', onMove);
canvas.addEventListener('mouseleave', () => { S.mouse = null; if (!rows.some(r => r.matches(':hover'))) S.hover = null; tip.style.display = 'none'; });
canvas.addEventListener('contextmenu', e => e.preventDefault());
canvas.addEventListener('wheel', e => { e.preventDefault(); S.dist = clamp(S.dist * Math.exp(e.deltaY * .0012), sceneR * .5, sceneR * 7); }, { passive: false });
let touch = null;
canvas.addEventListener('touchstart', e => { if (e.touches.length === 1) touch = [e.touches[0].clientX, e.touches[0].clientY]; S.auto = false; syncBtn(); }, { passive: true });
canvas.addEventListener('touchmove', e => { if (touch && e.touches.length === 1) { S.yaw -= (e.touches[0].clientX - touch[0]) * .008; S.pitch = clamp(S.pitch + (e.touches[0].clientY - touch[1]) * .008, -1.45, 1.45); touch = [e.touches[0].clientX, e.touches[0].clientY]; } }, { passive: true });

const exSl = $('#ex');
if (SPEC.no_explode) { exSl.parentElement.style.display = 'none'; }
exSl.oninput = () => { S.t = S.target = parseFloat(exSl.value); S.play = null; cap.style.display = 'none'; parts.forEach(p => p.a = 1); };
function syncBtn() { $('#bRot').classList.toggle('on', S.auto); $('#bLab').classList.toggle('on', S.labels); $('#bXr').classList.toggle('on', S.xray); $('#bIso').classList.toggle('on', S.isolate); }
$('#bRot').onclick = () => { S.auto = !S.auto; syncBtn(); };
$('#bLab').onclick = () => { S.labels = !S.labels; syncBtn(); };
$('#bXr').onclick = () => { S.xray = !S.xray; syncBtn(); };
$('#bIso').onclick = () => { S.isolate = !S.isolate; syncBtn(); };
$('#bRst').onclick = () => { frame(); };
$('#bPlay').onclick = () => togglePlay();
window.addEventListener('keydown', e => {
  if (e.target && e.target.tagName === 'INPUT') return; const k = e.key.toLowerCase();
  if (k === 'r') { S.auto = !S.auto; syncBtn(); } else if (k === 'l') { S.labels = !S.labels; syncBtn(); } else if (k === 'x') { S.xray = !S.xray; syncBtn(); }
  else if (k === 'i') { S.isolate = !S.isolate; syncBtn(); } else if (k === 'e') { S.target = S.target > .5 ? 0 : 1; } else if (k === ' ') { e.preventDefault(); togglePlay(); }
  else if (k === 'escape') select(null);
});

/* ---- assembly / walkthrough ---- */
function stepsOrder() { return parts.slice().sort((a, b) => a.step - b.step || a.i - b.i); }
function togglePlay() {
  if (S.play) { S.play = null; cap.style.display = 'none'; parts.forEach(p => p.a = 1); S.target = 1; return; }
  const order = stepsOrder(); S.t = S.target = 1; exSl.value = 1; parts.forEach(p => p.a = 1);
  S.play = { order, k: 0, t0: S.time, dur: .9, gap: .55, done: false }; select(null); tip.style.display = 'none';
}
function updatePlay() {
  const P = S.play; if (!P) return;
  const el_ = S.time - P.t0, idx = Math.floor(el_ / (P.dur + P.gap)), cur = P.order[Math.min(idx, P.order.length - 1)];
  P.order.forEach((p, i) => {
    const t0 = i * (P.dur + P.gap), f = clamp((el_ - t0) / P.dur, 0, 1);
    p.a = concept ? 1 : 1 - ease(f);
    if (concept) p.a = 1;
  });
  if (idx < P.order.length) {
    const p = cur, txt = p.sp.step_note || p.sp.desc || '';
    cap.innerHTML = `<b>Step ${Math.min(idx + 1, P.order.length)} / ${P.order.length} · ${esc(p.name)}</b><span>${esc(txt)}</span>`; cap.style.display = 'block'; S.hover = p;
  } else if (el_ > P.order.length * (P.dur + P.gap) + .6) { S.play = null; cap.style.display = 'none'; S.hover = null; parts.forEach(p => p.a = 1); S.target = concept ? 1 : 0; exSl.value = S.target; }
  else { cap.innerHTML = '<b>Complete</b><span>All parts in place.</span>'; S.hover = null; }
}

/* ------------------------------------------------------------ main loop */
function resize() {
  const r = root.getBoundingClientRect(); W = Math.max(300, r.width); H = Math.max(300, r.height);
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  [canvas, ov].forEach(c => { c.width = Math.round(W * dpr); c.height = Math.round(H * dpr); c.style.width = W + 'px'; c.style.height = H + 'px'; });
}
window.addEventListener('resize', resize);
let last = performance.now(), hovTimer = 0;
function loop(now) {
  const dt = Math.min(.05, (now - last) / 1000); last = now;
  if (Math.abs(S.target - S.t) > 1e-4) { S.t += (S.target - S.t) * Math.min(1, dt * 3.2); if (Math.abs(S.target - S.t) < 1e-3) S.t = S.target; exSl.value = S.t; }
  if (S.auto && !S.drag) S.yaw += dt * .22; else if (!S.drag) { S.yaw += S.vy * .9; S.pitch = clamp(S.pitch + S.vp * .9, -1.45, 1.45); S.vy *= .93; S.vp *= .93; }
  updatePlay(); camera(); updateParts(dt);
  hovTimer += dt;
  if (S.mouse && !S.drag && hovTimer > .04 && !S.play) {
    hovTimer = 0; const h = hitPart(rayFromMouse(S.mouse[0], S.mouse[1]));
    if (h !== S.hover && !rows.some(r => r.matches(':hover'))) S.hover = h;
    if (h) { tip.innerHTML = `<b>${esc(h.name)}</b><br>${esc((h.sp.desc || '').slice(0, 130))}`; tip.style.display = 'block'; tip.style.left = Math.min(W - 260, S.mouse[0] + 16) + 'px'; tip.style.top = (S.mouse[1] + 16) + 'px'; canvas.style.cursor = 'pointer'; }
    else { tip.style.display = 'none'; canvas.style.cursor = 'grab'; }
  }
  drawGL(); drawOverlay();
  window.__frames = (window.__frames || 0) + 1;
  requestAnimationFrame(loop);
}
resize(); frame();
setTimeout(() => { if (!window.__noAutoExplode && !SPEC.no_explode) S.target = SPEC.start_exploded === false ? 0 : 1; }, 700);
requestAnimationFrame(loop);
/* ---- external control API (voice commands, hand gestures, tests) ---- */
const hud = el('div', 'hud'); hud.style.display = 'none'; root.append(hud);
let hudTimer = 0;
function say(t) { hud.textContent = t; hud.style.display = 'block'; clearTimeout(hudTimer); hudTimer = setTimeout(() => hud.style.display = 'none', 2200); }
const cur = el('div', 'hcur'); cur.style.display = 'none'; root.append(cur);
function findPart(q) {
  q = String(q || '').toLowerCase().trim(); if (!q) return null;
  const n = parseInt(q, 10); if (!isNaN(n) && parts[n - 1]) return parts[n - 1];
  return parts.find(p => p.name.toLowerCase() === q) || parts.find(p => p.name.toLowerCase().includes(q)) || parts.find(p => q.includes(p.name.toLowerCase())) || null;
}
function stepPart(d) { const i = S.sel ? S.sel.i : -1; select(parts[(i + d + parts.length) % parts.length]); }
const CMD = {
  rotate_left: (a) => { S.auto = false; S.yaw += (a || .5); }, rotate_right: (a) => { S.auto = false; S.yaw -= (a || .5); },
  rotate_up: (a) => { S.auto = false; S.pitch = clamp(S.pitch + (a || .3), -1.45, 1.45); }, rotate_down: (a) => { S.auto = false; S.pitch = clamp(S.pitch - (a || .3), -1.45, 1.45); },
  orbit: (a) => { S.auto = false; S.yaw -= a[0]; S.pitch = clamp(S.pitch + a[1], -1.45, 1.45); S.vy = S.vp = 0; },
  zoom_in: (a) => { S.dist = clamp(S.dist * (a || .8), sceneR * .5, sceneR * 7); }, zoom_out: (a) => { S.dist = clamp(S.dist / (a || .8), sceneR * .5, sceneR * 7); },
  zoom: (f) => { S.dist = clamp(S.dist * f, sceneR * .5, sceneR * 7); },
  pan: (a) => { const k = S.dist * .9; S.tgt = add(S.tgt, add(mul(RIGHT, -a[0] * k), mul(UP, a[1] * k))); },
  explode: () => { S.play = null; cap.style.display = 'none'; parts.forEach(p => p.a = 1); S.target = 1; say('Exploded'); },
  assemble: () => { S.play = null; cap.style.display = 'none'; parts.forEach(p => p.a = 1); S.target = 0; say('Assembled'); },
  explode_set: (v) => { S.play = null; S.target = clamp(v, 0, 1); },
  toggle_explode: () => { S.target = S.target > .5 ? 0 : 1; },
  play: () => { if (!S.play) togglePlay(); }, stop: () => { if (S.play) togglePlay(); S.auto = false; syncBtn(); },
  xray: (v) => { S.xray = v == null ? !S.xray : !!v; syncBtn(); say('X-ray ' + (S.xray ? 'on' : 'off')); },
  labels: (v) => { S.labels = v == null ? !S.labels : !!v; syncBtn(); say('Labels ' + (S.labels ? 'on' : 'off')); },
  isolate: (v) => { S.isolate = v == null ? !S.isolate : !!v; syncBtn(); say('Isolate ' + (S.isolate ? 'on' : 'off')); },
  autorotate: (v) => { S.auto = v == null ? !S.auto : !!v; syncBtn(); },
  reset: () => { frame(); S.auto = false; syncBtn(); select(null); say('View reset'); },
  select: (q) => { const p = findPart(q); if (p) { select(p); say(p.name); } return !!p; },
  deselect: () => select(null), next: () => stepPart(1), prev: () => stepPart(-1),
  cursor: (a) => {                                   // a = [x,y] in 0..1 (screen space) or null; moves the hand pointer + hover
    if (!a) { cur.style.display = 'none'; S.mouse = null; return; }
    const x = a[0] * W, y = a[1] * H; cur.style.display = 'block'; cur.style.left = x + 'px'; cur.style.top = y + 'px'; S.mouse = [x, y];
  },
  click: () => { if (!S.mouse) return false; const h = hitPart(rayFromMouse(S.mouse[0], S.mouse[1])); select(h && h !== S.sel ? h : null); return !!h; },
  hud: (t) => say(t),
};
function cmd(name, arg) { const f = CMD[name]; if (!f) return false; const r = f(arg); return r === undefined ? true : r; }
window.JUP = { select: id => select(byId[id] || null), setExplode: v => { S.t = S.target = v; exSl.value = v; }, play: togglePlay, state: S, parts, frame, setRotate: v => { S.auto = v; syncBtn(); }, glOK, cmd, commands: Object.keys(CMD), findPart };
})();

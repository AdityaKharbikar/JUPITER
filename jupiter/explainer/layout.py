"""Deterministic layout: sanitized semantic components -> render spec (positions, shapes, colours, links, steps).

All geometry decisions happen here, in plain Python. The LLM never writes code or coordinates.
"""
from __future__ import annotations

import math
from collections import deque

from .library._kit import box, cyl, cone, sphere, torus
from .schema import slug
from .shapes import SCALE, shape_prims

LAYER_COLORS = ["#5b7aa8", "#3f9d8f", "#d1873f", "#9a6ad6"]
TIER_COLORS = ["#2bd9ff", "#35e08a", "#ffb020", "#d36bff", "#ff6b8b", "#7aa2ff"]


def _shade(hex_color: str, k: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    f = lambda v: max(0, min(255, int(v * k)))
    return f"#{f(r):02x}{f(g):02x}{f(b):02x}"


DIRS = {"top": (0, 1, 0), "bottom": (0, -1, 0), "left": (-1, 0, 0), "right": (1, 0, 0), "front": (0, 0, 1), "back": (0, 0, -1), "center": (0, 0, 0)}


def _separate(pos, rad, fixed=(), gap=0.18, iters=60, skip=frozenset()):
    """Push overlapping parts apart (bounding spheres) so nothing intersects. Parts in `fixed` do not move."""
    n = len(pos)
    for _ in range(iters):
        moved = False
        for i in range(n):
            for j in range(i + 1, n):
                if (i, j) in skip:
                    continue
                d = [pos[j][k] - pos[i][k] for k in range(3)]
                dist = math.sqrt(sum(v * v for v in d))
                need = (rad[i] + rad[j]) * 0.78 + gap
                if dist >= need:
                    continue
                if dist < 1e-6:
                    d, dist = [0.31, 0.12 * ((i + j) % 3 - 1), 0.17], 0.37
                push = (need - dist) / dist
                wi = 0.0 if i in fixed else (0.5 if j not in fixed else 0.0)
                wj = 0.0 if j in fixed else (0.5 if i not in fixed else 0.0)
                if wi == 0 and wj == 0:
                    continue
                s_ = wi + wj
                for k in range(3):
                    pos[i][k] -= d[k] * push * wi / s_
                    pos[j][k] += d[k] * push * wj / s_
                moved = True
        if not moved:
            break


def _spatial(comps):
    """Assembled/exploded positions from semantic hints: place (top/left/...), inside (container), layer (depth)."""
    from .shapes import prim_radius
    prims = [shape_prims(c["shape"], c["size"], "#888888", c.get("aspect", "")) for c in comps]
    rad = [prim_radius(p) for p in prims]
    idx = {c["name"]: i for i, c in enumerate(comps)}
    n = len(comps)
    asm = [[0.0, 0.0, 0.0] for _ in range(n)]
    # 1) containers / outer shell first (layer 0 or anything others sit inside) define the envelope
    hosts = {c["inside"] for c in comps if c.get("inside")}
    big = max(rad)
    slots: dict[str, int] = {}
    for i, c in enumerate(comps):
        if c.get("inside"):
            continue
        d = DIRS.get(c.get("place") or "", None)
        if d is None or c["layer"] == 0 and not c.get("place"):          # unplaced: fall back to a ring by layer
            k = slots.setdefault("ring", 0); slots["ring"] += 1
            ang = k * 2.399963 + c["layer"] * 0.7                       # golden angle -> even spread
            r_ = (0.0 if c["layer"] == 0 and k == 0 else big * (0.8 + 0.35 * c["layer"]) )
            asm[i] = [r_ * math.cos(ang), (1.5 - c["layer"]) * 0.45, r_ * math.sin(ang)]
        else:
            k = slots.setdefault(c["place"], 0); slots[c["place"]] += 1
            reach = big * (0.55 if c["layer"] >= 2 else 0.9) + rad[i] * 0.7
            side = (k // 2 + (k % 2)) * (-1 if k % 2 else 1) * (rad[i] * 1.35)   # extra parts with the same place fan out sideways
            perp = (1, 0, 0) if d[0] == 0 else (0, 0, 1)
            asm[i] = [d[j] * reach + perp[j] * side for j in range(3)]
    for i, c in enumerate(comps):                                       # 2) contained parts: inside their host, slight offset
        if c.get("inside"):
            h = idx[c["inside"]]; k = slots.setdefault("in:" + c["inside"], 0); slots["in:" + c["inside"]] += 1
            ang = k * 2.399963
            asm[i] = [asm[h][0] + math.cos(ang) * rad[h] * 0.35 * (k > 0), asm[h][1] + 0.05 * k, asm[h][2] + math.sin(ang) * rad[h] * 0.35 * (k > 0)]
    fixed = set()
    skip = {tuple(sorted((i, idx[c["inside"]]))) for i, c in enumerate(comps) if c.get("inside")}   # a part may overlap its container
    _separate(asm, rad, fixed, gap=0.05, skip=skip)
    cx = [sum(p[k] for p in asm) / n for k in range(3)]
    asm = [[p[k] - cx[k] for k in range(3)] for p in asm]
    exp = [[p[k] * 1.7 for k in range(3)] for p in asm]
    for i, c in enumerate(comps):                                       # contained parts fly out of their host
        if c.get("inside"):
            h = idx[c["inside"]]
            away = [exp[i][k] - exp[h][k] for k in range(3)]
            L = math.sqrt(sum(v * v for v in away)) or 1.0
            exp[i] = [exp[h][k] + (away[k] / L if L > .01 else (0, 1, 0)[k]) * (rad[h] + rad[i]) * 1.25 for k in range(3)]
    _separate(exp, rad, fixed, gap=0.25, skip=skip)
    return asm, exp, prims


def layout_physical(data: dict) -> dict:
    comps = data["components"]
    asm, exp, prims = _spatial(comps)
    spec_parts, ids = [], {}
    for i, c in enumerate(comps):
        color = _shade(LAYER_COLORS[min(c["layer"], 3)], 0.85 + 0.3 * ((i * 37 % 10) / 10))
        pid = f"p{i + 1}_{slug(c['name'])[:18]}"
        ids[c["name"]] = pid
        pr = shape_prims(c["shape"], c["size"], color, c.get("aspect", ""))
        spec_parts.append({"id": pid, "name": c["name"], "desc": c["purpose"], "pos": [round(v, 3) for v in asm[i]],
                           "explode": [round(e - a, 3) for e, a in zip(exp[i], asm[i])], "color": color, "prims": pr,
                           "group": f"Layer {c['layer'] + 1}" + (f" · inside {c['inside']}" if c.get("inside") else ""),
                           "stylized": True, "step": 0, "_layer": c["layer"]})
    links, seen = [], set()
    for c in comps:
        for t in c["connects_to"]:
            key = tuple(sorted((c["name"], t)))
            if key not in seen:
                seen.add(key)
                links.append({"a": ids[c["name"]], "b": ids[t], "label": ""})
    _assign_steps(spec_parts, data, ids)
    return {"kind": "physical", "parts": spec_parts, "links": links, "directed": False, "flow": False}


def _assign_steps(spec_parts, data, ids):
    order = [ids[n] for n in data.get("assembly_order", []) if n in ids]
    rest = sorted((p for p in spec_parts if p["id"] not in order), key=lambda p: (-p["_layer"], p["name"]))
    # Without an explicit order: inner layers go in first, outer shell last (a plausible assembly sequence).
    seq = order + [p["id"] for p in rest]
    pos = {pid: i for i, pid in enumerate(seq)}
    for p in spec_parts:
        p["step"] = pos[p["id"]]
        p.pop("_layer", None)


def layout_concept(data: dict) -> dict:
    comps = data["components"]
    names = [c["name"] for c in comps]
    layers = sorted({c["layer"] for c in comps})
    tiers = {c["name"]: c["layer"] for c in comps}
    if len(layers) < 2:                                    # no tier info -> derive depth from the links (BFS from the first node)
        adj = {n: set() for n in names}
        for c in comps:
            for t in c["connects_to"]:
                adj[c["name"]].add(t); adj[t].add(c["name"])
        depth, dq = {names[0]: 0}, deque([names[0]])
        while dq:
            u = dq.popleft()
            for v in sorted(adj[u]):
                if v not in depth:
                    depth[v] = depth[u] + 1; dq.append(v)
        for n in names:
            depth.setdefault(n, max(depth.values()) + 1)
        tiers = {n: min(depth[n], 5) for n in names}
        layers = sorted(set(tiers.values()))
    rows: dict[int, list[dict]] = {}
    for c in comps:
        rows.setdefault(tiers[c["name"]], []).append(c)
    ordered = sorted(rows)
    mid = (len(ordered) - 1) / 2
    spec_parts, ids = [], {}
    for ti, t in enumerate(ordered):
        row = rows[t]
        for i, c in enumerate(row):
            x = (i - (len(row) - 1) / 2) * 2.5
            y_asm, y_exp = (mid - ti) * 0.9, (mid - ti) * 2.0
            z = 0.0 if len(row) < 2 else (0.35 if i % 2 else -0.35)
            color = TIER_COLORS[ordered.index(t) % len(TIER_COLORS)]
            pid = f"n{len(spec_parts) + 1}_{slug(c['name'])[:18]}"
            ids[c["name"]] = pid
            asm = (x * 0.75, y_asm, z)
            exp = (x, y_exp, z)
            spec_parts.append({"id": pid, "name": c["name"], "desc": c["purpose"], "pos": [round(v, 3) for v in asm],
                               "explode": [round(e - a, 3) for e, a in zip(exp, asm)], "color": color,
                               "prims": [box(1.7, 0.5, 1.0), box(1.5, 0.08, 0.8, (0, 0.29, 0), c=_shade(color, 0.72))],
                               "group": f"Tier {ti + 1}", "step": ti * 20 + i})
    links, seen = [], set()
    for c in comps:
        for t in c["connects_to"]:
            key = (c["name"], t)
            if key not in seen and (t, c["name"]) not in seen:
                seen.add(key)
                links.append({"a": ids[c["name"]], "b": ids[t], "label": "", "dir": True})
    return {"kind": "concept", "parts": spec_parts, "links": links, "directed": True, "flow": True}


def to_render_spec(data: dict, *, topic: str, model: str, seconds: float) -> dict:
    spec = layout_concept(data) if data["kind"] == "concept" else layout_physical(data)
    concept = data["kind"] == "concept"
    spec.update({
        "title": data["title"], "summary": data["summary"], "curated": False, "start_exploded": True,
        "disclaimer": ("AI-generated concept diagram: the component list comes from a local language model and may be incomplete or wrong."
                       if concept else
                       "AI-generated approximation: the part list comes from a local language model and the shapes are simplified "
                       "look-alikes chosen from the part names. This is not an accurate or engineering-grade model."),
        "meta_line": f"Generated for “{topic}” by {model} in {seconds:.1f}s",
    })
    return spec

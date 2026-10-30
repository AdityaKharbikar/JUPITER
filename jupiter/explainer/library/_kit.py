"""Tiny helpers for hand-writing curated models compactly.

A *part* is one logical component made of one or more primitives.
Primitive shapes (sizes are in scene units, ~1 unit = a few cm for small objects, whatever looks right):
  box(sx,sy,sz)  cyl(r,h) | cyl(rTop,rBottom,h)  cone(r,h)  tube(rOuter,rInner,h)  sphere(r) | sphere(rx,ry,rz)  torus(R,r)
Cylinders/cones/tubes are along the Y axis; rotate with rot=(rx,ry,rz) degrees.
"""
from __future__ import annotations

import math


def box(sx, sy, sz, p=(0, 0, 0), r=(0, 0, 0), c=None):
    return _prim("box", (sx, sy, sz), p, r, c)


def cyl(r, h, p=(0, 0, 0), rot=(0, 0, 0), c=None, r2=None, seg=None):
    d = _prim("cyl", (r, h) if r2 is None else (r, r2, h), p, rot, c)
    if seg:
        d["seg"] = int(seg)          # 3 = triangular prism, 6 = hexagon (nuts, bolt heads)
    return d


def cone(r, h, p=(0, 0, 0), rot=(0, 0, 0), c=None):
    return _prim("cone", (r, h), p, rot, c)


def tube(ro, ri, h, p=(0, 0, 0), rot=(0, 0, 0), c=None):
    return _prim("tube", (ro, ri, h), p, rot, c)


def sphere(rx, ry=None, rz=None, p=(0, 0, 0), c=None):
    s = (rx,) if ry is None else (rx, ry, rz if rz is not None else rx)
    return _prim("sphere", s, p, (0, 0, 0), c)


def torus(R, r, p=(0, 0, 0), rot=(0, 0, 0), c=None):
    return _prim("torus", (R, r), p, rot, c)


def _prim(t, s, p, r, c):
    d = {"t": t, "s": [round(float(x), 4) for x in s]}
    if any(p):
        d["p"] = [round(float(x), 4) for x in p]
    if any(r):
        d["r"] = [round(float(x), 3) for x in r]
    if c:
        d["c"] = c
    return d


class Model:
    """Collects parts, links and assembly steps, and emits a spec dict."""

    def __init__(self, title, summary, kind="physical", directed=False, flow=False, start_exploded=True):
        self.spec = {"title": title, "summary": summary, "kind": kind, "curated": True,
                     "parts": [], "links": [], "directed": directed, "flow": flow,
                     "start_exploded": start_exploded}
        self._n = 0

    def part(self, pid, name, desc, pos, explode, color, prims, group="", step=None, anim=None, note=None, bound=None):
        part = {"id": pid, "name": name, "desc": desc, "pos": _v(pos), "explode": _v(explode),
                "color": color, "prims": prims, "group": group, "step": self._n if step is None else step}
        if anim:
            part["anim"] = anim
        if note:
            part["step_note"] = note
        if bound:
            part["bound"] = bound
        self.spec["parts"].append(part)
        self._n += 1
        return pid

    def link(self, a, b, label="", flow=False):
        item = {"a": a, "b": b, "label": label}
        if flow:
            item["flow"] = True
        self.spec["links"].append(item)

    def chain(self, ids, label=""):
        for a, b in zip(ids, ids[1:]):
            self.link(a, b, label)

    def build(self):
        return self.spec


def _v(v):
    return [round(float(x), 4) for x in v]


def spin(axis=(0, 1, 0), speed=60):
    return {"type": "spin", "axis": list(axis), "speed": speed}


def slide(direction=(0, 1, 0), amp=0.3, speed=4):
    return {"type": "slide", "dir": list(direction), "amp": amp, "speed": speed}


def orbit(speed=10, phase=0):
    return {"type": "orbit", "speed": speed, "phase": phase}


def swing(axis=(0, 0, 1), amp=20, speed=1.5):
    return {"type": "swing", "axis": list(axis), "amp": amp, "speed": speed}


def rod_between(p1, p2, r, c=None):
    """Cylinder joining two points that lie in the same XY plane (z taken from p1)."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = math.hypot(dx, dy)
    ang = math.degrees(math.atan2(-dx, dy))
    mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, p1[2] if len(p1) > 2 else 0)
    return cyl(r, length, mid, (0, 0, ang), c)


def spokes(radius, n=16, r=0.012, c=None, center=(0, 0, 0)):
    """Radial spokes for a wheel whose axle is the Z axis."""
    out = []
    for i in range(n):
        ang = 180.0 * i / n
        out.append(cyl(r, radius * 2, center, (0, 0, ang), c))
    return out


def pulse(amp=0.05, rate=1.1, phase=0.0):
    return {"type": "pulse", "amp": amp, "rate": rate, "phase": phase}


def rod3(p1, p2, r, c=None):
    """Cylinder between two arbitrary 3D points."""
    dx, dy, dz = (p2[i] - p1[i] for i in range(3))
    length = math.sqrt(dx * dx + dy * dy + dz * dz) or 1e-6
    ux, uy, uz = dx / length, dy / length, dz / length
    alpha = math.degrees(math.asin(max(-1.0, min(1.0, uz))))
    beta = math.degrees(math.atan2(-ux, uy))
    mid = tuple((p1[i] + p2[i]) / 2 for i in range(3))
    return cyl(r, length, mid, (alpha, 0, beta), c)

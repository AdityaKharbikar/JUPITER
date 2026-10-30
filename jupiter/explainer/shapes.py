"""Detailed multi-primitive shapes + name-based shape inference (deterministic, no LLM).

shape_prims(shape, size, aspect, color) -> list of primitives. infer_shape(name, llm_shape) overrides the LLM's
generic shape when the part NAME clearly says what it is (a 'battery' is always a battery, whatever the model said).
"""
from __future__ import annotations

import math

from .library._kit import box, cone, cyl, sphere, torus, tube

SHAPES = ("box", "plate", "cylinder", "rod", "sphere", "ring", "cone", "wheel",
          "gear", "coil", "battery", "chip", "screen", "lens", "blade", "pipe", "dome", "prism", "motor", "button", "cable", "housing")
SCALE = {"small": 0.5, "medium": 0.85, "large": 1.35}
ASPECT = {"cube": (1, 1, 1), "tall": (0.7, 1.7, 0.7), "wide": (1.6, 0.8, 1.0), "flat": (1.5, 0.35, 1.2), "long": (2.0, 0.55, 0.55)}
ASPECTS = tuple(ASPECT)

# (keywords, shape): first match wins. Checked as whole words / prefixes against the lower-cased part name.
_NAME_RULES = [
    (("battery", "cell", "accumulator"), "battery"), (("gear", "cog", "sprocket", "flywheel"), "gear"),
    (("spring", "coil", "winding", "inductor", "solenoid"), "coil"), (("wheel", "tire", "tyre", "rotor"), "wheel"),
    (("screen", "display", "monitor", "panel", "lcd", "touchscreen"), "screen"), (("lens", "glass", "mirror", "cornea"), "lens"),
    (("fan", "propeller", "blade", "impeller", "turbine", "vane", "wing"), "blade"), (("pipe", "tube", "duct", "hose", "nozzle", "exhaust", "artery", "vein"), "pipe"),
    (("cpu", "processor", "chip", "ic", "microcontroller", "gpu", "memory", "ram", "sensor", "pcb", "circuit", "controller"), "chip"),
    (("motor", "engine", "pump", "compressor", "generator", "alternator"), "motor"), (("switch", "button", "key", "knob", "trigger", "valve"), "button"),
    (("wire", "cable", "cord", "antenna", "axle", "shaft", "rod", "pin", "piston", "needle", "handle"), "cable"),
    (("dome", "cover", "cap", "lid", "hood", "helmet"), "dome"), (("case", "casing", "housing", "body", "shell", "chassis", "frame", "enclosure", "cabinet"), "housing"),
    (("led", "bulb", "lamp", "ball", "planet", "sun", "heart", "core", "nucleus"), "sphere"),
]


def infer_shape(name: str, llm_shape: str) -> str:
    import re
    words = [re.sub(r"ies$", "y", w) for w in re.findall(r"[a-z]+", (name or "").lower())]
    for keys, shape in _NAME_RULES:
        if any(w == k or (len(k) > 4 and k in w) or (len(k) > 4 and w.rstrip("s") == k) for w in words for k in keys):
            return shape
    return llm_shape if llm_shape in SHAPES else "box"


def _sh(hex_color, k):
    h = hex_color.lstrip("#"); f = lambda v: max(0, min(255, int(v * k)))
    return "#%02x%02x%02x" % tuple(f(int(h[i:i + 2], 16)) for i in (0, 2, 4))


def shape_prims(shape: str, size: str, color: str, aspect: str = ""):
    s = SCALE.get(size, 0.85)
    ax, ay, az = ASPECT.get(aspect, (1, 1, 1))
    dk, lt = _sh(color, .62), _sh(color, 1.25)
    if shape == "plate":
        return [box(1.5 * s * ax, 0.14, 1.05 * s * az)]
    if shape == "cylinder":
        return [cyl(0.42 * s * ax, 1.0 * s * ay)]
    if shape == "rod" or shape == "cable":
        L = (1.8 if shape == "cable" else 1.7) * s * max(ax, ay)
        return [cyl(0.09 * s, L, rot=(0, 0, 90)), cyl(0.13 * s, 0.16 * s, (L / 2, 0, 0), (0, 0, 90), c=dk), cyl(0.13 * s, 0.16 * s, (-L / 2, 0, 0), (0, 0, 90), c=dk)]
    if shape == "sphere":
        return [sphere(0.52 * s * ax, 0.52 * s * ay, 0.52 * s * az)]
    if shape == "ring":
        return [torus(0.5 * s, 0.12 * s, rot=(90, 0, 0))]
    if shape == "cone":
        return [cone(0.48 * s, 1.0 * s * ay)]
    if shape == "wheel":      # tyre + hub + 8 spokes
        R = 0.5 * s
        out = [torus(R, 0.13 * s, rot=(90, 0, 0)), cyl(0.12 * s, 0.26 * s, rot=(90, 0, 0), c=dk)]
        out += [cyl(0.02 * s, R * 2, (0, 0, 0), (0, 0, 180 * i / 4), c=lt) for i in range(4)]
        return out
    if shape == "gear":       # disc + teeth + hub
        R, n = 0.5 * s, 12
        out = [cyl(R, 0.2 * s, rot=(90, 0, 0)), cyl(0.14 * s, 0.3 * s, rot=(90, 0, 0), c=dk)]
        for i in range(n):
            a = 2 * math.pi * i / n
            out.append(box(0.14 * s, 0.2 * s, 0.17 * s, (math.cos(a) * (R + .06 * s), math.sin(a) * (R + .06 * s), 0), (0, 0, math.degrees(a)), c=lt))
        return out
    if shape == "coil":       # stacked rings along Y + end caps
        n, h = 7, 1.0 * s * ay
        out = [torus(0.3 * s, 0.045 * s, (0, -h / 2 + h * i / (n - 1), 0), (0, 0, 0), c=lt) for i in range(n)]
        return out + [cyl(0.32 * s, 0.05 * s, (0, -h / 2 - .05 * s, 0), c=dk), cyl(0.32 * s, 0.05 * s, (0, h / 2 + .05 * s, 0), c=dk)]
    if shape == "battery":
        h = 1.15 * s * ay
        return [cyl(0.28 * s, h), cyl(0.12 * s, 0.1 * s, (0, h / 2 + .05 * s, 0), c=lt), cyl(0.285 * s, h * 0.18, (0, h * .3, 0), c=dk)]
    if shape == "chip":
        w = 0.9 * s * ax
        out = [box(w, 0.08 * s, w), box(w * .62, 0.05 * s, w * .62, (0, 0.06 * s, 0), c=dk)]
        for i in range(5):
            o = (i - 2) * w * .18
            out += [box(0.05 * s, 0.03 * s, 0.12 * s, (o, 0, w / 2 + .05 * s), c=lt), box(0.05 * s, 0.03 * s, 0.12 * s, (o, 0, -w / 2 - .05 * s), c=lt)]
        return out
    if shape == "screen":
        return [box(1.5 * s * ax, 0.95 * s * ay, 0.08 * s), box(1.36 * s * ax, 0.8 * s * ay, 0.03 * s, (0, 0, 0.05 * s), c="#0b1b2e")]
    if shape == "lens":
        r = 0.5 * s
        return [sphere(r * ax, r * ax, 0.16 * s, c=lt), tube(r * ax * 1.05, r * ax * .9, 0.09 * s, rot=(90, 0, 0), c=dk)]
    if shape == "blade":      # 3 blades on a hub, fan style (spins about Y)
        out = [cyl(0.12 * s, 0.12 * s, c=dk)]
        out += [box(0.62 * s, 0.03 * s, 0.2 * s, (math.cos(a) * 0.38 * s, 0, math.sin(a) * 0.38 * s), (0, -math.degrees(a), 12), c=lt)
                for a in (2 * math.pi * i / 3 for i in range(3))]
        return out
    if shape == "pipe":
        L = 1.6 * s * max(ax, ay)
        return [tube(0.17 * s, 0.12 * s, L, rot=(0, 0, 90)), tube(0.22 * s, 0.12 * s, 0.1 * s, (L / 2 - .05 * s, 0, 0), (0, 0, 90), c=dk), tube(0.22 * s, 0.12 * s, 0.1 * s, (-L / 2 + .05 * s, 0, 0), (0, 0, 90), c=dk)]
    if shape == "dome":
        r = 0.55 * s
        return [sphere(r * ax, r * 0.7 * ay, r * az), cyl(r * ax, 0.06 * s, (0, -r * 0.05, 0), c=dk)]
    if shape == "prism":
        return [cyl(0.5 * s * ax, 0.8 * s * ay, seg=3)]
    if shape == "motor":
        return [cyl(0.36 * s, 0.9 * s, rot=(0, 0, 90)), cyl(0.07 * s, 0.5 * s, (0.65 * s, 0, 0), (0, 0, 90), c=lt),
                cyl(0.38 * s, 0.08 * s, (-0.45 * s, 0, 0), (0, 0, 90), c=dk), box(0.4 * s, 0.1 * s, 0.4 * s, (0, -0.38 * s, 0), c=dk)]
    if shape == "button":
        return [box(0.7 * s, 0.14 * s, 0.7 * s, c=dk), cyl(0.2 * s, 0.14 * s, (0, 0.13 * s, 0), c=lt)]
    if shape == "housing":    # open shell: base + two walls + back, so inner parts stay visible
        w, h, d = 1.5 * s * ax, 1.0 * s * ay, 1.1 * s * az
        return [box(w, 0.07, d, (0, -h / 2, 0)), box(0.07, h, d, (-w / 2, 0, 0)), box(0.07, h, d, (w / 2, 0, 0)), box(w, h, 0.07, (0, 0, -d / 2)), box(w, 0.07, d, (0, h / 2, 0), c=dk)]
    return [box(1.0 * s * ax, 0.75 * s * ay, 0.85 * s * az)]


def prim_radius(prims) -> float:
    """Bounding radius of a prim list around the part origin (cheap upper bound, used for collision-free layout)."""
    best = 0.05
    for pr in prims:
        s, p = pr.get("s", [0.5]), pr.get("p", [0, 0, 0])
        t = pr["t"]
        ext = (math.sqrt(sum(v * v for v in s)) / 2 if t == "box" else max(s[:2] if t == "torus" else s) * (1.0 if t != "torus" else 1.0)
               if t in ("sphere", "torus") else max(s[0], (s[-1] / 2)) * 1.2)
        if t == "torus":
            ext = s[0] + s[1]
        best = max(best, math.sqrt(sum(v * v for v in p)) + ext)
    return best

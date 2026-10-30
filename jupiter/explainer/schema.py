"""Spec schema + validation.

The LLM only ever supplies SEMANTIC data (names, purposes, shape hints). Python turns that into geometry.
Nothing the model returns is ever executed.
"""
from __future__ import annotations

import difflib
import json
import re

from .shapes import ASPECTS, SHAPES, infer_shape

PLACES = ("center", "top", "bottom", "left", "right", "front", "back")
SIZES = ("small", "medium", "large")
PRIM_TYPES = {"box", "cyl", "cone", "tube", "sphere", "torus"}
MAX_PARTS = 16
MIN_PARTS = 3

# JSON schema handed to Ollama's structured-output mode (also documented in the prompt).
LLM_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["physical", "concept"]},
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "components": {
            "type": "array", "minItems": MIN_PARTS, "maxItems": MAX_PARTS,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "purpose": {"type": "string"},
                    "shape": {"type": "string", "enum": list(SHAPES)},
                    "size": {"type": "string", "enum": list(SIZES)},
                    "layer": {"type": "integer"},
                    "aspect": {"type": "string", "enum": list(ASPECTS)},
                    "place": {"type": "string", "enum": list(PLACES)},
                    "inside": {"type": "string"},
                    "connects_to": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "purpose", "shape", "size", "layer", "place", "connects_to"],
            },
        },
        "assembly_order": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["kind", "title", "summary", "components"],
}


class SpecError(ValueError):
    pass


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return s[:60] or "model"


def clean_text(value, limit):
    s = re.sub(r"\s+", " ", str(value or "")).strip()
    s = re.sub(r"[<>`]", "", s)
    return s[:limit]


def extract_json(text: str):
    """Pull the first balanced JSON object out of a model reply (handles ``` fences, <think> blocks, trailing commas)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"```(?:json)?", "", text)
    start = text.find("{")
    if start < 0:
        raise SpecError("no JSON object in the model reply")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                chunk = text[start:i + 1]
                break
    else:
        chunk = text[start:]            # truncated reply: try to close it
        chunk += "]" * max(0, chunk.count("[") - chunk.count("]")) + "}" * max(0, chunk.count("{") - chunk.count("}"))
    for candidate in (chunk, re.sub(r",\s*([}\]])", r"\1", chunk)):
        try:
            return json.loads(candidate)
        except ValueError:
            continue
    raise SpecError("the model reply was not valid JSON")


def sanitize_llm(raw: dict, topic: str) -> dict:
    """Validate/normalise the model's JSON into a clean dict used by layout.py. Raises SpecError when unusable."""
    if not isinstance(raw, dict):
        raise SpecError("reply is not a JSON object")
    comps_in = raw.get("components")
    if not isinstance(comps_in, list):
        raise SpecError("no components list")
    kind = "concept" if str(raw.get("kind", "")).lower().startswith("concept") else "physical"
    comps, seen = [], set()
    for c in comps_in:
        if not isinstance(c, dict):
            continue
        name = clean_text(c.get("name"), 48)
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        shape = str(c.get("shape", "box")).lower()
        size = str(c.get("size", "medium")).lower()
        try:
            layer = int(c.get("layer", 1))
        except (TypeError, ValueError):
            layer = 1
        conns = c.get("connects_to") if isinstance(c.get("connects_to"), list) else []
        aspect = str(c.get("aspect", "")).lower()
        place = str(c.get("place", "")).lower()
        comps.append({"name": name, "purpose": clean_text(c.get("purpose"), 150) or "Purpose not provided.",
                      "shape": infer_shape(name, shape if shape in SHAPES else "box"), "size": size if size in SIZES else "medium",
                      "aspect": aspect if aspect in ASPECTS else "", "place": place if place in PLACES else "",
                      "inside": clean_text(c.get("inside"), 48),
                      "layer": max(0, min(5 if kind == "concept" else 3, layer)),
                      "connects_to": [clean_text(x, 48) for x in conns][:5]})
        if len(comps) >= MAX_PARTS:
            break
    if len(comps) < MIN_PARTS:
        raise SpecError(f"only {len(comps)} usable components")
    names = [c["name"] for c in comps]
    lower = {n.lower(): n for n in names}
    for c in comps:                                    # resolve link names (exact, then fuzzy), drop unknowns/self links
        fixed = []
        for t in c["connects_to"]:
            hit = lower.get(t.lower()) or next(iter(difflib.get_close_matches(t, names, 1, 0.75)), None)
            if hit and hit != c["name"] and hit not in fixed:
                fixed.append(hit)
        c["connects_to"] = fixed
    for c in comps:                                    # 'inside' must name another listed part
        ins = c.pop("inside", "")
        hit = lower.get(ins.lower()) or next(iter(difflib.get_close_matches(ins, names, 1, 0.75)), None) if ins else None
        c["inside"] = hit if hit and hit != c["name"] else ""
    for c in comps:                                    # no orphans: attach unlinked parts to their container / same-layer neighbour
        if not c["connects_to"] and not any(c["name"] in o["connects_to"] for o in comps):
            other = next((o for o in comps if o["name"] == c["inside"]), None) or \
                next((o for o in comps if o is not c and o["layer"] == c["layer"]), None) or next(o for o in comps if o is not c)
            c["connects_to"].append(other["name"])
    order = []
    for n in raw.get("assembly_order") or []:
        hit = lower.get(str(n).lower()) or next(iter(difflib.get_close_matches(str(n), names, 1, 0.75)), None)
        if hit and hit not in order:
            order.append(hit)
    return {"kind": kind, "title": clean_text(raw.get("title"), 60) or clean_text(topic, 60).title(),
            "summary": clean_text(raw.get("summary"), 260), "components": comps, "assembly_order": order}


def validate_spec(spec: dict) -> list[str]:
    """Return a list of problems with a RENDER spec (used by tests for every curated model)."""
    errs = []
    if not spec.get("title"):
        errs.append("missing title")
    parts = spec.get("parts") or []
    if not parts:
        errs.append("no parts")
    ids = [p.get("id") for p in parts]
    if len(ids) != len(set(ids)):
        errs.append("duplicate part ids")
    for p in parts:
        for key in ("id", "name", "desc", "pos", "explode", "color", "prims"):
            if key not in p:
                errs.append(f"{p.get('id')}: missing {key}")
        if len(p.get("pos", [])) != 3 or len(p.get("explode", [])) != 3:
            errs.append(f"{p.get('id')}: pos/explode must have 3 numbers")
        if not p.get("prims"):
            errs.append(f"{p.get('id')}: no prims")
        for pr in p.get("prims", []):
            if pr.get("t") not in PRIM_TYPES:
                errs.append(f"{p.get('id')}: bad primitive {pr.get('t')}")
        if len(p.get("prims", [])) > 200:
            errs.append(f"{p.get('id')}: too many prims")
    idset = set(ids)
    for l in spec.get("links") or []:
        if l.get("a") not in idset or l.get("b") not in idset:
            errs.append(f"link to unknown part: {l}")
    return errs

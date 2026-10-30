import json

from jupiter.explainer import layout, schema, service
from jupiter.explainer.gestures import GestureController, classify
from jupiter.explainer.shapes import SHAPES, infer_shape, shape_prims
from jupiter.skills.explainer import ExplainerSkill


def hand(ext, thumb_out=False, pinch=False, dx=0.0):
    lm = [(0.5, 0.9)] * 21
    lm[9], lm[5], lm[13], lm[17] = (0.5, 0.6), (0.42, 0.62), (0.56, 0.62), (0.62, 0.66)
    for (tip, pip), e, x in zip(((8, 6), (12, 10), (16, 14), (20, 18)), ext, (0.42, 0.5, 0.56, 0.62)):
        lm[pip] = (x, 0.5); lm[tip] = (x, 0.3) if e else (x, 0.58)
    lm[3] = (0.36, 0.72); lm[4] = (0.2, 0.6) if thumb_out else (0.45, 0.66)
    if pinch:
        lm[4] = (lm[8][0] + 0.01, lm[8][1] + 0.01)
    return [(x + dx, y) for x, y in lm]


def test_classify():
    assert classify(hand([1, 1, 1, 1], True)) == "open" and classify(hand([0, 0, 0, 0])) == "fist"
    assert classify(hand([1, 0, 0, 0])) == "point" and classify(hand([1, 1, 0, 0])) == "peace"
    assert classify(hand([1, 1, 1, 0])) == "three" and classify(hand([0, 0, 0, 1], True)) == "call"
    assert classify(hand([1, 0, 0, 0], pinch=True)) == "pinch" and classify(None) == "unknown"


def test_controller_rotate_zoom_toggle():
    out, t = [], [0.0]
    c = GestureController(lambda n, a=None: out.append((n, a)), now=lambda: t[0])
    c.update([hand([1, 1, 1, 1], True)]); c.update([hand([1, 1, 1, 1], True, dx=0.05)])
    assert any(n == "orbit" for n, _ in out)
    out.clear()
    for _ in range(3):
        t[0] += 0.5; c.update([hand([1, 1, 0, 0])])
    assert ("toggle_explode", None) in out and sum(n == "toggle_explode" for n, _ in out) == 1      # fires once per hold
    out.clear()
    c.update([hand([1, 0, 0, 0], pinch=True)]); c.update([hand([1, 0, 0, 0], pinch=True)])
    assert [n for n, _ in out].count("click") == 1                                                   # one click per pinch
    out.clear(); c.update([hand([1, 1, 1, 1], True), hand([1, 1, 1, 1], True, dx=0.3)]); c.update([hand([1, 1, 1, 1], True), hand([1, 1, 1, 1], True, dx=0.5)])
    assert any(n == "zoom" and a < 1 for n, a in out)                                                # hands apart -> zoom in
    c.update([]); assert out[-1] == ("cursor", None)


def test_shapes_all_valid_and_inferred():
    for s in SHAPES:
        assert not schema.validate_spec({"title": "t", "parts": [{"id": "a", "name": "a", "desc": "d", "pos": [0, 0, 0], "explode": [0, 0, 0], "color": "#888888",
                                                                  "prims": shape_prims(s, "medium", "#888888")}]}), s
    assert infer_shape("Batteries", "box") == "battery" and infer_shape("Fan Blades", "box") == "blade" and infer_shape("Zorp", "cone") == "cone"


def test_layout_no_overlap_and_contained_parts():
    raw = {"kind": "physical", "title": "Flashlight", "summary": "s", "components": [
        {"name": "Housing", "purpose": "p", "shape": "box", "size": "large", "layer": 0, "place": "center", "connects_to": ["Batteries"]},
        {"name": "Batteries", "purpose": "p", "shape": "box", "size": "medium", "layer": 1, "inside": "Housing", "connects_to": []},
        {"name": "LED", "purpose": "p", "shape": "sphere", "size": "small", "layer": 2, "place": "top", "connects_to": []},
        {"name": "Switch", "purpose": "p", "shape": "box", "size": "small", "layer": 2, "place": "top", "connects_to": []},
        {"name": "Lens", "purpose": "p", "shape": "box", "size": "medium", "layer": 0, "place": "top", "connects_to": ["LED"]}]}
    d = schema.sanitize_llm(raw, "flashlight")
    assert all(c["connects_to"] or any(c["name"] in o["connects_to"] for o in d["components"]) for c in d["components"])   # no orphans
    sp = layout.to_render_spec(d, topic="t", model="m", seconds=0)
    assert not schema.validate_spec(sp)
    P = {p["name"]: p for p in sp["parts"]}
    assert P["Batteries"]["group"].endswith("inside Housing")
    for state in (0, 1):                                 # LED / Switch / Lens must not sit on top of each other
        pos = {n: [a + b * state for a, b in zip(p["pos"], p["explode"])] for n, p in P.items()}
        for a, b in (("LED", "Switch"), ("LED", "Lens"), ("Switch", "Lens")):
            assert sum((x - y) ** 2 for x, y in zip(pos[a], pos[b])) ** .5 > 0.4


def test_voice_viewer_commands(monkeypatch):
    monkeypatch.setattr(service, "VIEW_ACTIVE", True); monkeypatch.setattr(service, "VIEW_PARTS", ["piston"])
    k = ExplainerSkill()
    assert k.match("rotate left")["cmd"] == "rotate_left" and k.match("zoom in")["cmd"] == "zoom_in" and k.match("explode")["cmd"] == "explode"
    assert k.match("hide labels")["arg"] is False and k.match("select piston")["arg"] == "piston"
    assert k.match("enable hand control")["cmd"] == "hand_on" and k.match("what are the hand gesture commands")["mode"] == "viewhelp"
    for other in ("stop", "reset", "close", "what is the weather", "select the volume"):   # must NOT hijack unrelated phrases
        assert k.match(other) is None
    monkeypatch.setattr(service, "VIEW_ACTIVE", False)
    assert k.match("rotate left") is None                # inactive until a model is open

import math
from ._kit import Model, box, cyl, sphere, torus, pulse, rod_between

TOPIC = "Human heart"
ALIASES = ["human heart", "heart", "the heart", "cardiac anatomy", "heart anatomy", "parts of the heart", "heart chambers", "heart structure"]
BLUE, RED = "#3b6fd1", "#d23c4a"


def _aorta_prims():
    """Ascending aorta, a semicircular arch and the descending aorta, built from short rods + joint spheres."""
    r, cx, cy, rad = 0.3, 0.55, 0.45, 0.55
    prims = [cyl(r, 0.95, (0, -0.025, 0))]
    pts = [(cx + rad * math.cos(math.radians(a)), cy + rad * math.sin(math.radians(a))) for a in range(180, -1, -20)]
    for p, q in zip(pts, pts[1:]):
        prims.append(rod_between((p[0], p[1], 0), (q[0], q[1], 0), r))
    for p in pts:
        prims.append(sphere(r, p=(p[0], p[1], 0)))
    prims.append(cyl(r, 1.25, (cx + rad, cy - 0.625, 0)))
    return prims


def build():
    m = Model("Human heart (simplified)",
              "A double pump: the right side sends oxygen-poor blood to the lungs, the left side sends oxygen-rich blood to the body. "
              "Four valves keep the blood flowing one way.")
    m.spec["disclaimer"] = "Simplified educational diagram, viewed from the front. Not a medical or anatomically exact model."
    m.part("rv", "Right ventricle", "Pumps oxygen-poor blood to the lungs through the pulmonary artery.",
           (-0.55, -0.55, 0.3), (-1.0, -0.8, 0.7), BLUE, [sphere(0.85, 1.05, 0.75)], "Chambers", anim=pulse(0.045, 1.1))
    m.part("lv", "Left ventricle", "The strongest chamber: pumps oxygen-rich blood through the aorta to the whole body.",
           (0.55, -0.6, -0.1), (1.0, -0.9, -0.3), RED, [sphere(0.95, 1.2, 0.85)], "Chambers", anim=pulse(0.055, 1.1))
    m.part("ra", "Right atrium", "Receives oxygen-poor blood returning from the body through the vena cavae.",
           (-1.1, 0.5, 0.0), (-2.1, 0.7, 0.2), BLUE, [sphere(0.6, 0.62, 0.55)], "Chambers", anim=pulse(0.04, 1.1, 0.12))
    m.part("la", "Left atrium", "Receives oxygen-rich blood from the lungs through the pulmonary veins.",
           (0.9, 0.7, -0.6), (1.8, 1.1, -1.1), RED, [sphere(0.55, 0.55, 0.5)], "Chambers", anim=pulse(0.04, 1.1, 0.12))
    m.part("svc", "Superior vena cava", "Large vein bringing oxygen-poor blood from the head and arms into the right atrium.",
           (-1.15, 1.45, 0.0), (-1.7, 2.2, 0.0), BLUE, [cyl(0.2, 1.3)], "Vessels")
    m.part("ivc", "Inferior vena cava", "Large vein bringing oxygen-poor blood from the lower body.",
           (-1.15, -0.5, -0.05), (-1.9, -1.9, -0.3), BLUE, [cyl(0.2, 1.1)], "Vessels")
    m.part("pa", "Pulmonary artery", "Carries oxygen-poor blood to the lungs (the only artery that carries it).",
           (-0.15, 1.05, 0.55), (-0.5, 2.6, 1.3), "#4a82e0", [cyl(0.24, 1.3), cyl(0.2, 0.9, (-0.45, 0.55, 0), (0, 0, 60)), cyl(0.2, 0.9, (0.45, 0.55, 0), (0, 0, -60))], "Vessels")
    arc = _aorta_prims()
    m.part("aorta", "Aorta", "Main artery of the body; it arches over the heart and distributes oxygen-rich blood.",
           (0.35, 1.25, -0.25), (0.7, 2.6, -0.7), "#e24a5a", arc, "Vessels")
    m.part("pv", "Pulmonary veins", "Bring freshly oxygenated blood from the lungs into the left atrium.",
           (1.55, 0.85, -0.65), (3.0, 1.4, -1.1), RED, [cyl(0.15, 1.0, rot=(0, 0, 90)), cyl(0.12, 0.8, (0, 0.3, 0.0), (0, 0, 90)), cyl(0.12, 0.8, (0, -0.3, 0.0), (0, 0, 90))], "Vessels")
    m.part("valves", "Heart valves (x4)", "Tricuspid, pulmonary, mitral and aortic valves: one-way doors that stop blood flowing backwards.",
           (0.0, 0.1, 0.0), (0.0, 0.1, 1.6), "#e5e7eb",
           [cyl(0.22, 0.06, (-0.55, 0.1, 0.1), (20, 0, 0)), cyl(0.2, 0.06, (-0.1, 0.8, 0.5)), cyl(0.22, 0.06, (0.55, 0.05, -0.25), (20, 0, 0)), cyl(0.22, 0.06, (0.4, 0.9, -0.25))], "Valves")
    m.part("septum", "Septum", "Muscular wall that keeps oxygen-rich and oxygen-poor blood separate.",
           (0.0, -0.45, 0.1), (0.0, -2.0, 0.0), "#b45309", [box(0.12, 1.5, 1.2)], "Wall")
    m.link("ivc", "ra", "to heart")
    m.link("svc", "ra", "to heart")
    m.link("ra", "rv", "tricuspid valve")
    m.link("rv", "pa", "pulmonary valve")
    m.link("pv", "la", "from lungs")
    m.link("la", "lv", "mitral valve")
    m.link("lv", "aorta", "aortic valve")
    m.link("rv", "septum", "")
    m.link("lv", "septum", "")
    m.link("valves", "rv", "")
    m.link("valves", "lv", "")
    return m.build()

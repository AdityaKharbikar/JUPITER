from ._kit import Model, box, cyl, cone, tube, torus, spin, slide

TOPIC = "Car engine"
ALIASES = ["car engine", "engine", "petrol engine", "gasoline engine", "internal combustion engine", "ic engine",
           "four stroke engine", "4 stroke engine", "motor car engine", "automobile engine", "combustion engine", "how a car works"]

XS = (-1.35, -0.45, 0.45, 1.35)


def build():
    m = Model("Car engine (4-cylinder, 4-stroke)",
              "Fuel and air burn in four cylinders; each explosion pushes a piston down, and the crankshaft turns that "
              "up-and-down motion into rotation.")
    m.part("pan", "Oil pan", "Reservoir under the engine that holds the oil the pump sends to every moving part.",
           (0, -0.98, 0), (0, -2.6, 0), "#4b5563", [box(3.9, 0.5, 1.5), box(1.0, 0.16, 1.2, (0.7, -0.32, 0))], "Lubrication")
    m.part("crank", "Crankshaft", "Converts the pistons' straight-line push into rotation that finally drives the wheels.",
           (0, -0.42, 0), (0, -1.4, 0), "#c58a2b",
           [cyl(0.13, 4.5, rot=(0, 0, 90))] + [cyl(0.2, 0.2, (x, 0, 0), (0, 0, 90)) for x in XS]
           + [box(0.12, 0.7, 0.5, (x + 0.2, 0.0, 0)) for x in XS], "Rotating assembly", anim=spin((1, 0, 0), 70))
    m.part("block", "Engine block", "The heavy casting with four cylinder bores; everything else bolts to or inside it.",
           (0, 0, 0), (0, 0, 0), "#6b7280",
           [box(4.0, 1.3, 1.5)] + [cyl(0.34, 0.05, (x, 0.66, 0), c="#0b0f16") for x in XS], "Structure")
    m.part("rods", "Connecting rods", "Steel links joining each piston to the crankshaft journals.",
           (0, -0.05, 0), (0, 0.55, 0), "#a3adba", [box(0.14, 0.95, 0.12, (x, 0, 0)) for x in XS], "Rotating assembly",
           anim=None)
    m.part("pistons", "Pistons", "Slide up and down in the bores, compressing the mixture and receiving each combustion push.",
           (0, 0.42, 0), (0, 1.5, 0), "#d1d5db",
           [cyl(0.32, 0.42, (x, 0, 0)) for x in XS] + [torus(0.32, 0.025, (x, 0.12, 0), c="#6b7280") for x in XS],
           "Rotating assembly", anim=slide((0, 1, 0), 0.12, 5))
    m.part("head", "Cylinder head", "Caps the cylinders and houses the valves, spark plugs and the air/exhaust passages.",
           (0, 0.98, 0), (0, 2.9, 0), "#7c8696", [box(4.0, 0.62, 1.5)], "Top end")
    m.part("valves", "Intake & exhaust valves", "Spring-loaded gates that open to let air in and burnt gas out at exactly the right moment.",
           (0, 0.82, 0), (0, 2.05, 0), "#e5e7eb",
           [cyl(0.03, 0.55, (x + d, 0.1, z)) for x in XS for d, z in ((-0.12, 0.28), (0.12, 0.28), (-0.12, -0.28), (0.12, -0.28))]
           + [cyl(0.1, 0.03, (x + d, -0.2, z), c="#9ca3af") for x in XS for d, z in ((-0.12, 0.28), (0.12, 0.28), (-0.12, -0.28), (0.12, -0.28))],
           "Top end", anim=None)
    m.part("plugs", "Spark plugs", "Fire an electric spark that ignites the compressed fuel-air mixture.",
           (0, 1.4, 0.0), (0, 3.9, 0), "#f4f4f5",
           [cyl(0.07, 0.45, (x, 0, 0)) for x in XS] + [cone(0.09, 0.16, (x, 0.3, 0), c="#2d3748") for x in XS], "Ignition")
    m.part("cam", "Camshaft", "Rotating lobes that push the valves open in sequence, driven by the crankshaft.",
           (0, 1.5, 0.3), (0, 4.3, 0.2), "#b45309",
           [cyl(0.09, 4.2, rot=(0, 0, 90))] + [box(0.28, 0.28, 0.12, (x + d, 0, 0)) for x in XS for d in (-0.12, 0.12)],
           "Top end", anim=spin((1, 0, 0), 35))
    m.part("cover", "Valve cover", "Seals the top of the engine and keeps the oil in around the camshaft.",
           (0, 1.82, 0), (0, 5.6, 0), "#334155", [box(4.0, 0.3, 1.3), box(1.0, 0.1, 0.5, (0, 0.2, 0), c="#1e293b")], "Top end")
    m.part("intake", "Intake manifold", "Distributes fresh air (and fuel) evenly to the four cylinders.",
           (0, 1.05, 1.1), (0, 2.1, 2.2), "#2563eb",
           [cyl(0.2, 3.6, (0, 0.25, 0.25), (0, 0, 90))] + [cyl(0.1, 0.5, (x, 0, 0.0)) for x in XS], "Air & exhaust")
    m.part("exhaust", "Exhaust manifold", "Collects hot burnt gas from all cylinders and sends it to the exhaust pipe.",
           (0, 0.85, -1.15), (0, 1.0, -2.4), "#7f1d1d",
           [cyl(0.15, 3.6, (0, -0.15, -0.3), (0, 0, 90))] + [cyl(0.08, 0.6, (x, 0.0, -0.05), (30, 0, 0)) for x in XS],
           "Air & exhaust")
    m.part("belt", "Timing pulley & belt", "Keeps the camshaft turning exactly half as fast as the crankshaft so valves stay in time.",
           (-2.25, 0.4, 0), (-2.3, 0.0, 0), "#111827",
           [torus(0.5, 0.07, rot=(0, 0, 90)), torus(0.22, 0.07, (0, 0.85, 0), (0, 0, 90)), cyl(0.5, 0.1, rot=(0, 0, 90), c="#1f2937")],
           "Timing", anim=spin((1, 0, 0), -45))
    m.part("flywheel", "Flywheel", "Heavy disc that smooths out the pulses of power and connects to the gearbox.",
           (2.35, -0.42, 0), (2.4, 0, 0), "#9ca3af", [cyl(0.75, 0.25, rot=(0, 0, 90)), cyl(0.2, 0.32, rot=(0, 0, 90), c="#374151")],
           "Rotating assembly", anim=spin((1, 0, 0), 70))
    m.link("pistons", "rods", "wrist pin")
    m.link("rods", "crank", "journals")
    m.link("crank", "flywheel", "drives")
    m.link("crank", "belt", "timing drive")
    m.link("belt", "cam", "half speed")
    m.link("cam", "valves", "pushes open")
    m.link("valves", "head", "seat in")
    m.link("plugs", "head", "screw in")
    m.link("intake", "head", "air in")
    m.link("head", "exhaust", "gas out")
    m.link("block", "pistons", "cylinder bores")
    m.link("block", "pan", "oil sump")
    m.link("cover", "head", "seals")
    return m.build()

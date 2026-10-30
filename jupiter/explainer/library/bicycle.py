import math
from ._kit import Model, box, cyl, torus, sphere, rod_between, spokes, spin

TOPIC = "Bicycle"
ALIASES = ["bicycle", "bike", "cycle", "road bike", "mountain bike", "pedal bike", "push bike", "how a bicycle works"]

R = 1.1
RA, FA = (-2.2, 0.0), (2.2, 0.0)
BB, SC, HT, HB = (-0.15, -0.35), (-0.8, 1.4), (1.5, 1.05), (1.65, 0.55)


def wheel(tag, name, desc, cx, color, extra=()):
    return dict(prims=[torus(R, 0.09, rot=(90, 0, 0), c="#111827"), torus(R - 0.1, 0.025, rot=(90, 0, 0), c="#cbd5e1"),
                       cyl(0.1, 0.22, rot=(90, 0, 0), c="#9ca3af")] + spokes(R - 0.1, 18, 0.012, "#d1d5db") + list(extra))


def build():
    m = Model("Bicycle",
              "Pedalling turns the crank, the chain carries the motion to the rear wheel, and a diamond-shaped frame "
              "joins wheels, rider and steering into one light structure.")
    m.part("frame", "Frame", "Diamond of steel or aluminium tubes that carries the rider and ties everything together.",
           (0, 0, 0), (0, 0.0, 0), "#dc2626",
           [rod_between(BB + (0,), SC + (0,), 0.07), rod_between(SC + (0,), HT + (0,), 0.065), rod_between(BB + (0,), HB + (0,), 0.08),
            rod_between(HT + (0,), HB + (0,), 0.075), rod_between(BB + (0,), RA + (0,), 0.05), rod_between(SC + (0,), RA + (0,), 0.04),
            cyl(0.1, 0.3, BB + (0,), (90, 0, 0), c="#9ca3af")], "Structure")
    m.part("rear", "Rear wheel & cassette", "Wheel with a cluster of sprockets that the chain drives; it pushes the bike forward.",
           (RA[0], 0, 0), (-2.2, 0, 0), "#374151",
           wheel("r", "", "", 0, "#374151", [cyl(0.2, 0.08, (0, 0, 0.14), (90, 0, 0), c="#9ca3af"), cyl(0.28, 0.04, (0, 0, 0.2), (90, 0, 0), c="#6b7280")])["prims"],
           "Wheels", anim=spin((0, 0, 1), -120))
    m.part("front", "Front wheel", "Rolls on the road and is steered by the handlebar through the fork.",
           (FA[0], 0, 0), (2.4, 0, 0), "#374151", wheel("f", "", "", 0, "#374151")["prims"], "Wheels", anim=spin((0, 0, 1), -120))
    m.part("fork", "Fork", "Holds the front wheel and pivots in the head tube so you can steer.",
           (0, 0, 0), (1.6, -0.6, 0), "#9ca3af",
           [rod_between(HB + (0.18,), FA + (0.18,), 0.05), rod_between(HB + (-0.18,), FA + (-0.18,), 0.05), box(0.08, 0.08, 0.4, (HB[0], HB[1], 0))],
           "Steering")
    m.part("bar", "Handlebar & stem", "The steering lever: your hands turn the fork; brake levers and shifters mount here.",
           (0, 0, 0), (0.7, 1.6, 0), "#111827",
           [rod_between(HT + (0,), (HT[0] - 0.25, HT[1] + 0.5, 0), 0.05), cyl(0.045, 1.2, (HT[0] - 0.25, HT[1] + 0.5, 0), (90, 0, 0)),
            box(0.3, 0.05, 0.05, (HT[0] - 0.05, HT[1] + 0.45, 0.5), c="#6b7280"), box(0.3, 0.05, 0.05, (HT[0] - 0.05, HT[1] + 0.45, -0.5), c="#6b7280")],
           "Steering")
    m.part("saddle", "Saddle & seatpost", "Supports the rider; the seatpost slides in the seat tube to set the height.",
           (0, 0, 0), (-1.0, 1.5, 0), "#1f2937",
           [rod_between(SC + (0,), (SC[0] - 0.08, SC[1] + 0.45, 0), 0.05, "#9ca3af"), box(0.95, 0.12, 0.3, (SC[0] - 0.08, SC[1] + 0.5, 0)),
            box(0.4, 0.14, 0.45, (SC[0] - 0.4, SC[1] + 0.5, 0)), box(0.45, 0.1, 0.18, (SC[0] + 0.45, SC[1] + 0.5, 0))], "Rider contact")
    m.part("crank", "Crankset & pedals", "Pedals and cranks convert your leg force into rotation of the big chainring.",
           (0, 0, 0), (0, -1.0, 1.8), "#cbd5e1",
           [cyl(0.42, 0.05, (BB[0], BB[1], 0.2), (90, 0, 0), c="#9ca3af"), rod_between((BB[0], BB[1], 0.28), (BB[0] - 0.1, BB[1] - 0.65, 0.28), 0.04, "#cbd5e1"),
            rod_between((BB[0], BB[1], -0.28), (BB[0] + 0.1, BB[1] + 0.65, -0.28), 0.04, "#cbd5e1"),
            box(0.3, 0.05, 0.16, (BB[0] - 0.1, BB[1] - 0.68, 0.38), c="#111827"), box(0.3, 0.05, 0.16, (BB[0] + 0.1, BB[1] + 0.68, -0.38), c="#111827")],
           "Drivetrain", anim=None)
    m.part("chain", "Chain", "Steel links meshing with the chainring and rear sprocket to carry power to the rear wheel.",
           (0, 0, 0), (0, -0.6, 1.2), "#a1a1aa",
           [rod_between((BB[0], BB[1] + 0.42, 0.2), (RA[0], RA[1] + 0.28, 0.2), 0.022), rod_between((BB[0], BB[1] - 0.42, 0.2), (RA[0], RA[1] - 0.28, 0.2), 0.022)],
           "Drivetrain")
    m.part("brakes", "Brakes", "Pads squeeze the rim (or discs) to slow the wheels by friction; cables connect them to the levers.",
           (0, 0, 0), (0.6, 0.9, 0.8), "#f59e0b",
           [box(0.25, 0.1, 0.5, (FA[0], FA[1] + R + 0.2, 0)), box(0.25, 0.1, 0.5, (RA[0], RA[1] + R + 0.2, 0))], "Control")
    m.chain(["bar", "fork", "front"], "")
    m.link("fork", "frame", "head tube")
    m.link("frame", "rear", "dropouts")
    m.link("saddle", "frame", "seat tube")
    m.link("crank", "chain", "power")
    m.link("chain", "rear", "drives")
    m.link("brakes", "front", "")
    m.link("brakes", "rear", "")
    return m.build()

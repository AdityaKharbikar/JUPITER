import math
from ._kit import Model, box, cyl, tube, torus, spin, sphere

TOPIC = "Electric motor"
ALIASES = ["electric motor", "dc motor", "motor", "brushed motor", "brushed dc motor", "electric engine", "ev motor", "how a motor works"]


def build():
    m = Model("Electric motor (brushed DC)",
              "Current in the rotor's coils turns it into an electromagnet; it is pushed round by the fixed magnets, "
              "and the commutator flips the current each half-turn so it keeps spinning.")
    m.part("housing", "Housing (stator shell)", "Steel tube that holds the magnets and completes their magnetic circuit.",
           (0, 0, 0), (0, 0, 0), "#64748b", [tube(1.1, 1.0, 3.0, rot=(0, 0, 90))], "Stator")
    m.part("magnets", "Permanent magnets", "Two curved magnets (north and south) creating the fixed magnetic field.",
           (0, 0, 0), (0, 0, 2.6), "#dc2626",
           [box(2.5, 0.22, 1.0, (0, 0.82, 0), c="#dc2626"), box(2.5, 0.22, 1.0, (0, -0.82, 0), c="#2563eb")], "Stator")
    m.part("rotor", "Rotor (armature) & shaft", "Iron core wrapped in copper coils on a shaft; this is the part that spins and delivers torque.",
           (0, 0, 0), (-3.2, 0, 0), "#b45309",
           [cyl(0.1, 5.6, rot=(0, 0, 90), c="#d1d5db"), cyl(0.62, 2.3, rot=(0, 0, 90), c="#475569")]
           + [torus(0.66, 0.11, (x, 0, 0), (0, 0, 90), c="#ea7c28") for x in (-0.85, -0.45, 0.0, 0.45, 0.85)],
           "Rotor", anim=spin((1, 0, 0), 120))
    segs = [cyl(0.34, 0.52, rot=(0, 0, 90), c="#1f2937")]
    for i in range(8):
        a = math.radians(i * 45)
        segs.append(box(0.54, 0.1, 0.2, (0, 0.36 * math.cos(a), 0.36 * math.sin(a)), (math.degrees(a), 0, 0), c="#d6a35c"))
    m.part("commutator", "Commutator", "Split copper ring that reverses the current in the coils every half turn.",
           (1.75, 0, 0), (2.2, 0, 0), "#d6a35c", segs, "Rotor", anim=spin((1, 0, 0), 120))
    m.part("brushes", "Brushes & springs", "Carbon blocks pressed against the commutator to feed current into the spinning rotor.",
           (1.75, 0, 0), (2.2, 0, 1.9), "#111827",
           [box(0.4, 0.3, 0.3, (0, 0.5, 0)), box(0.4, 0.3, 0.3, (0, -0.5, 0)), cyl(0.05, 0.4, (0, 0.8, 0), c="#9ca3af"), cyl(0.05, 0.4, (0, -0.8, 0), c="#9ca3af")],
           "Electrical")
    m.part("cap_f", "Front end cap & bearing", "Closes the housing at the output end and holds the front bearing for the shaft.",
           (-1.6, 0, 0), (-5.0, 0, 0), "#475569", [cyl(1.12, 0.2, rot=(0, 0, 90)), torus(0.28, 0.07, (-0.12, 0, 0), (0, 0, 90), c="#d1d5db")], "Stator")
    m.part("cap_r", "Rear end cap & bearing", "Holds the rear bearing and the brush holders.",
           (1.6, 0, 0), (4.6, 0, 0), "#475569", [cyl(1.12, 0.2, rot=(0, 0, 90)), torus(0.28, 0.07, (0.12, 0, 0), (0, 0, 90), c="#d1d5db")], "Stator")
    m.part("leads", "Terminals & wires", "Where the battery connects; current flows through the brushes into the rotor.",
           (1.9, 0.0, 0.9), (4.4, 0.8, 2.6), "#b91c1c", [cyl(0.05, 0.9, (0, 0, 0), (90, 0, 0), c="#b91c1c"), cyl(0.05, 0.9, (0, 0.2, 0), (90, 0, 0), c="#111827")], "Electrical")
    m.link("magnets", "housing", "mounted inside")
    m.link("magnets", "rotor", "magnetic field")
    m.link("rotor", "commutator", "")
    m.link("commutator", "brushes", "current")
    m.link("brushes", "leads", "")
    m.link("cap_f", "rotor", "bearing")
    m.link("cap_r", "rotor", "bearing")
    m.link("cap_r", "brushes", "holds")
    return m.build()

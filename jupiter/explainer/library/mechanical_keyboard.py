from ._kit import Model, box, cyl, cone, sphere

TOPIC = "Mechanical keyboard"
ALIASES = ["mechanical keyboard", "keyboard", "computer keyboard", "pc keyboard", "gaming keyboard", "typing keyboard", "keyboard switches",
           "laptop keyboard", "keys"]

COLS, ROWS, PITCH = 10, 4, 0.58


def _grid(fn):
    return [fn(( c - (COLS - 1) / 2) * PITCH, (r - (ROWS - 1) / 2) * PITCH) for r in range(ROWS) for c in range(COLS)]


def build():
    m = Model("Mechanical keyboard",
              "Each key press pushes a switch stem down inside the plate; the switch closes a contact on the PCB, "
              "and a microcontroller sends the key code over USB.")
    m.part("keycaps", "Keycaps", "The plastic caps you touch; they snap onto the switch stems.",
           (0, 0.95, 0), (0, 3.3, 0), "#d9dee7",
           _grid(lambda x, z: box(0.5, 0.26, 0.5, (x, 0, z))) + [box(2.2, 0.26, 0.5, (0, 0, 1.5 * PITCH + 0.0))], "Typing surface")
    m.part("switches", "Mechanical switches", "Spring-loaded stems that click or glide; pressing one closes an electrical contact.",
           (0, 0.6, 0), (0, 2.2, 0), "#2563eb",
           _grid(lambda x, z: cyl(0.14, 0.3, (x, 0.08, z))) + _grid(lambda x, z: box(0.36, 0.14, 0.36, (x, -0.1, z), c="#1e293b")),
           "Switching")
    m.part("stabs", "Stabilizers", "Metal wire bars that keep wide keys such as the spacebar level when pressed at the edge.",
           (0, 0.45, 1.5 * PITCH), (0, 1.6, 1.0), "#9ca3af", [box(2.0, 0.04, 0.08, (0, 0, 0)), cyl(0.04, 0.3, (-1.0, -0.1, 0)), cyl(0.04, 0.3, (1.0, -0.1, 0))],
           "Switching")
    m.part("plate", "Switch plate", "Thin metal sheet with square cut-outs that holds every switch straight and rigid.",
           (0, 0.3, 0), (0, 1.0, 0), "#6b7280", [box(6.3, 0.07, 2.7)], "Structure")
    m.part("pcb", "PCB (circuit board)", "Green board with a grid of copper traces; each switch bridges one row-column crossing.",
           (0, 0.1, 0), (0, 0.0, 0), "#15803d", [box(6.2, 0.07, 2.6)] + _grid(lambda x, z: box(0.2, 0.04, 0.2, (x, 0.06, z), c="#d4d4d8")),
           "Electronics")
    m.part("mcu", "Microcontroller", "Tiny processor that scans the key matrix many times a second and builds the key codes.",
           (0, 0.18, -1.0), (0, 0.5, -2.4), "#111827", [box(0.7, 0.1, 0.7), box(0.9, 0.02, 0.9, (0, -0.04, 0), c="#d4d4d8")], "Electronics")
    m.part("usb", "USB-C connector", "Carries power in and the typed key codes out to the computer.",
           (0, 0.18, -1.45), (0, 0.5, -3.4), "#d4d4d8", [box(0.7, 0.2, 0.4), box(0.5, 0.1, 0.45, (0, 0, -0.1), c="#0b0f16")], "Electronics")
    m.part("foam", "Sound-dampening foam", "Soft layer that absorbs vibration so typing sounds deeper and less hollow.",
           (0, -0.05, 0), (0, -1.2, 0), "#fcd34d", [box(6.1, 0.14, 2.5)], "Acoustics")
    m.part("case", "Case", "Rigid shell that houses everything and sets the keyboard's weight, tilt and sound.",
           (0, -0.3, 0), (0, -2.8, 0), "#334155",
           [box(6.7, 0.16, 3.0, (0, -0.12, 0)), box(6.7, 0.5, 0.14, (0, 0.2, 1.43)), box(6.7, 0.5, 0.14, (0, 0.2, -1.43)),
            box(0.14, 0.5, 3.0, (3.28, 0.2, 0)), box(0.14, 0.5, 3.0, (-3.28, 0.2, 0))], "Structure")
    m.chain(["keycaps", "switches", "plate", "pcb"], "")
    m.link("switches", "stabs", "")
    m.link("pcb", "mcu", "key matrix")
    m.link("mcu", "usb", "data")
    m.link("pcb", "foam", "")
    m.link("foam", "case", "sits in")
    return m.build()

from ._kit import Model, box, cyl, torus, sphere

TOPIC = "Smartphone"
ALIASES = ["smartphone", "smart phone", "phone", "mobile phone", "mobile", "cell phone", "cellphone", "iphone", "android phone", "android"]

W, L = 2.2, 4.4


def build():
    m = Model("Smartphone",
              "A phone is a layered sandwich: touch glass and a display on top, a logic board and battery in the middle, "
              "a camera system and a back cover underneath.")
    m.part("glass", "Cover glass & touch layer", "Scratch-resistant glass with a transparent grid of electrodes that senses your finger.",
           (0, 0.36, 0), (0, 3.6, 0), "#93c5fd", [box(W, 0.06, L), box(0.6, 0.065, 0.06, (0, 0, 1.95), c="#0b0f16")], "Display stack")
    m.part("oled", "OLED display panel", "Millions of tiny self-lit pixels; each can switch off completely for true black.",
           (0, 0.28, 0), (0, 2.7, 0), "#111827", [box(W - 0.1, 0.05, L - 0.12), box(W - 0.4, 0.052, L - 0.6, (0, 0.003, 0), c="#2563eb")], "Display stack")
    m.part("frame", "Metal mid-frame", "Aluminium chassis that gives the phone its strength and acts as a heat spreader and antenna band.",
           (0, 0.1, 0), (0, 1.3, 0), "#9ca3af",
           [box(W + 0.06, 0.28, 0.08, (0, 0, L / 2)), box(W + 0.06, 0.28, 0.08, (0, 0, -L / 2)), box(0.08, 0.28, L, (W / 2 + 0.01, 0, 0)),
            box(0.08, 0.28, L, (-W / 2 - 0.01, 0, 0)), box(W, 0.05, L, (0, -0.1, 0))], "Structure")
    m.part("board", "Logic board & SoC", "Main circuit board carrying the system-on-chip (CPU, GPU, AI engine), memory and modem.",
           (0, 0.1, 1.2), (0, 0.4, 2.4), "#15803d",
           [box(1.9, 0.05, 1.9), box(0.7, 0.08, 0.7, (-0.3, 0.06, 0.1), c="#111827"), box(0.5, 0.07, 0.4, (0.5, 0.06, -0.2), c="#374151"),
            box(0.3, 0.06, 0.3, (0.55, 0.06, 0.55), c="#d4d4d8")], "Electronics")
    m.part("battery", "Lithium-ion battery", "Stores the energy that powers everything, typically 3,000-5,000 mAh.",
           (0, 0.1, -0.85), (0, 0.4, -2.4), "#f59e0b", [box(1.85, 0.2, 2.1), box(1.5, 0.21, 0.5, (0, 0, 0.2), c="#d97706")], "Power")
    m.part("camera", "Camera module", "Lens stack and image sensor; the phone's processor turns the raw data into a photo.",
           (0.45, -0.1, 1.55), (1.8, -1.0, 2.9), "#1f2937",
           [box(1.0, 0.1, 1.0, c="#0f172a"), cyl(0.28, 0.14, (-0.22, -0.07, -0.22), c="#38bdf8"), cyl(0.28, 0.14, (0.22, -0.07, -0.22), c="#38bdf8"),
            cyl(0.28, 0.14, (-0.22, -0.07, 0.22), c="#38bdf8"), cyl(0.12, 0.1, (0.25, -0.07, 0.25), c="#fde68a")], "Imaging")
    m.part("haptic", "Speaker & haptic motor", "Speaker makes sound; the tiny vibrating motor gives you touch feedback.",
           (0.6, 0.1, -1.95), (1.6, 0.3, -3.2), "#a855f7", [box(0.7, 0.18, 0.28), cyl(0.18, 0.2, (-0.55, 0, 0), (0, 0, 90), c="#6d28d9")], "Electronics")
    m.part("back", "Back glass & wireless coil", "Rear cover; behind it a copper coil allows wireless charging.",
           (0, -0.17, 0), (0, -2.0, 0), "#cbd5e1", [box(W, 0.06, L), torus(0.5, 0.025, (0, 0.05, -0.4), c="#b45309")], "Structure")
    m.chain(["glass", "oled", "frame"], "")
    m.link("frame", "board", "mounts")
    m.link("board", "battery", "power")
    m.link("board", "camera", "image data")
    m.link("board", "haptic", "")
    m.link("oled", "board", "display flex cable")
    m.link("frame", "back", "")
    return m.build()

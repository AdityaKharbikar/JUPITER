from ._kit import Model, box, cyl, torus, tube, spin

TOPIC = "Desktop computer"
ALIASES = ["desktop computer", "desktop pc", "desktop", "pc", "computer", "personal computer", "gaming pc", "cpu cabinet"]


def build():
    m = Model("Desktop computer", "A tower PC: the case holds a motherboard that links the CPU, memory, graphics card and storage, "
              "all fed by one power supply and kept cool by fans.")
    m.part("case", "Case (chassis)", "Metal and glass frame that holds every part, guides airflow and shields electronics.",
           (0, 0, 0), (-4.2, 0, 0), "#52657d",
           [box(0.12, 4.6, 3.4, (-1.65, 0, 0)), box(3.4, 0.12, 3.4, (0, 2.3, 0)), box(3.4, 0.12, 3.4, (0, -2.3, 0)),
            box(3.4, 4.6, 0.12, (0, 0, -1.7)), box(0.5, 4.6, 0.12, (1.45, 0, 1.7))], "Structure")
    m.part("psu", "Power supply (PSU)", "Converts wall AC power into the low-voltage DC rails every component needs.",
           (0.2, -1.75, 0.2), (0, -2.6, 0.4), "#2f3a4a",
           [box(2.6, 0.9, 1.9), cyl(0.38, 0.1, (-0.5, 0, 0.96), (90, 0, 0), c="#111a26")], "Power")
    m.part("mobo", "Motherboard", "Main circuit board: sockets, slots and traces that let every component talk to every other.",
           (0.1, 0.1, -1.45), (0, 0.1, -2.7), "#1f6b4a",
           [box(2.9, 2.9, 0.1), box(0.7, 0.9, 0.05, (-1.0, 0.7, 0.07), c="#2b2f36")], "Core")
    m.part("cpu", "CPU", "The processor: runs program instructions, billions of operations per second.",
           (0.2, 0.55, -1.32), (0.3, 1.0, -0.3), "#c8ced6",
           [box(0.55, 0.55, 0.08), box(0.4, 0.4, 0.05, (0, 0, 0.06), c="#8892a0")], "Core")
    m.part("cooler", "CPU cooler", "Heatsink and fan that pull heat away from the CPU so it can keep its speed.",
           (0.2, 0.55, -1.0), (0.3, 1.3, 1.0), "#9aa7b8",
           [box(0.9, 0.9, 0.55), cyl(0.38, 0.08, (0, 0, 0.35), (90, 0, 0), c="#1b2635")], "Cooling", anim=None)
    m.part("ram", "RAM modules", "Fast short-term memory that holds the data and programs currently in use.",
           (1.1, 0.7, -1.28), (1.5, 1.2, -0.2), "#3a7bd5",
           [box(0.14, 1.3, 0.06, (0, 0, 0)), box(0.14, 1.3, 0.06, (0.24, 0, 0))], "Memory")
    m.part("gpu", "Graphics card (GPU)", "Dedicated processor that draws images and runs parallel workloads such as games and AI.",
           (0.1, -0.5, -0.55), (0, -0.9, 1.2), "#222b38",
           [box(2.6, 0.2, 1.0), box(2.4, 0.5, 0.9, (0, 0.34, 0), c="#38465a"),
            cyl(0.36, 0.06, (-0.6, 0.62, 0), c="#111a26"), cyl(0.36, 0.06, (0.6, 0.62, 0), c="#111a26")], "Graphics")
    m.part("ssd", "SSD storage", "Flash drive that keeps the operating system, programs and files when power is off.",
           (-0.9, -1.1, -1.28), (-1.5, -0.9, -0.2), "#7c4dff",
           [box(0.9, 0.12, 0.35), box(0.25, 0.14, 0.2, (-0.3, 0.02, 0), c="#c8ced6")], "Storage")
    m.part("fan_f", "Case fans", "Pull cool air in through the front and push hot air out of the back.",
           (-1.35, 0.4, 0.0), (-2.6, 0.6, 0), "#1b2635",
           [tube(0.75, 0.62, 0.1, (0, 0, 0), (0, 0, 90)), cyl(0.2, 0.12, (0, 0, 0), (0, 0, 90), c="#0b1220"),
            box(0.04, 0.12, 0.6, (0, 0, 0)), box(0.04, 0.6, 0.12, (0, 0, 0))],
           "Cooling", anim=spin((1, 0, 0), 180))
    m.link("psu", "mobo", "24-pin power")
    m.link("psu", "gpu", "PCIe power")
    m.link("mobo", "cpu", "CPU socket")
    m.link("cpu", "cooler", "heat")
    m.link("mobo", "ram", "memory bus")
    m.link("mobo", "gpu", "PCIe x16")
    m.link("mobo", "ssd", "NVMe / SATA")
    m.link("case", "fan_f", "mounts")
    return m.build()

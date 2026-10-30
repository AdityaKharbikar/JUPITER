from ._kit import Model, box, cyl, cone, sphere, tube, spin

TOPIC = "Quadcopter drone"
ALIASES = ["quadcopter drone", "quadcopter", "drone", "quadrotor", "multirotor", "uav", "fpv drone", "camera drone", "quadcopter assembly"]

ARM = 1.7


def _motor_prop(m, tag, sx, sz, color, direction):
    x, z = sx * ARM, sz * ARM
    m.part(f"mp_{tag}", f"Motor & propeller ({tag.upper()})",
           "Brushless motor spinning a propeller; speeding up or slowing down each of the four steers the drone.",
           (x, 0.25, z), (sx * 1.2, 0.9, sz * 1.2), color,
           [cyl(0.2, 0.3, (0, -0.05, 0)), cyl(0.12, 0.08, (0, 0.17, 0), c="#e5e7eb"),
            box(2.3, 0.035, 0.24, (0, 0.24, 0), (0, 14, 0), c="#1f2937")],
           "Propulsion", anim=spin((0, 1, 0), 520 * direction))


def build():
    m = Model("Quadcopter drone",
              "Four motors spin propellers to create lift. A flight controller reads sensors hundreds of times a second "
              "and adjusts each motor's speed to keep the drone level or steer it.")
    m.part("frame", "Frame & arms", "Light carbon-fibre X-shaped body that carries the motors and holds everything together.",
           (0, 0, 0), (0, -0.2, 0), "#374151",
           [box(4.9, 0.1, 0.22, (0, 0, 0), (0, 45, 0)), box(4.9, 0.1, 0.22, (0, 0, 0), (0, -45, 0)),
            box(1.3, 0.1, 1.3, (0, 0.0, 0)), cyl(0.04, 0.35, (1.05, -0.2, 1.05)), cyl(0.04, 0.35, (-1.05, -0.2, 1.05)),
            cyl(0.04, 0.35, (1.05, -0.2, -1.05)), cyl(0.04, 0.35, (-1.05, -0.2, -1.05))], "Structure")
    _motor_prop(m, "fl", -1, 1, "#ef4444", 1)
    _motor_prop(m, "fr", 1, 1, "#3b82f6", -1)
    _motor_prop(m, "bl", -1, -1, "#3b82f6", -1)
    _motor_prop(m, "br", 1, -1, "#ef4444", 1)
    m.part("esc", "ESC (motor driver)", "Electronic speed controllers: turn battery power into the precisely timed pulses each motor needs.",
           (0, 0.12, 0), (0, 0.5, 0), "#15803d", [box(0.9, 0.05, 0.9), box(0.25, 0.08, 0.25, (0.2, 0.06, 0.2), c="#111827")], "Electronics")
    m.part("fc", "Flight controller", "The brain: reads the gyroscope and accelerometer and keeps the drone stable.",
           (0, 0.25, 0), (0, 1.4, 0), "#7c3aed", [box(0.8, 0.05, 0.8), box(0.3, 0.08, 0.3, (0, 0.06, 0), c="#111827")], "Electronics")
    m.part("rx", "Radio receiver & antenna", "Receives your remote-control commands and passes them to the flight controller.",
           (0.9, 0.25, -0.3), (2.2, 1.3, -0.6), "#0ea5e9", [box(0.35, 0.08, 0.2), cyl(0.012, 0.9, (0.1, 0.45, 0))], "Electronics")
    m.part("gps", "GPS module", "Gives position and speed so the drone can hold its place or return home.",
           (-0.85, 0.28, -0.4), (-1.9, 2.1, -0.4), "#f59e0b", [cyl(0.3, 0.1), box(0.45, 0.04, 0.45, (0, -0.07, 0), c="#111827")], "Navigation")
    m.part("battery", "LiPo battery", "Rechargeable lithium-polymer pack: the only energy source, usually ~10-25 minutes of flight.",
           (0, -0.3, 0), (0, -1.7, 0), "#f97316", [box(1.5, 0.35, 0.7), box(0.2, 0.2, 0.2, (0.85, 0, 0), c="#111827")], "Power")
    m.part("cam", "Camera & gimbal", "Records video; a small gimbal motor keeps the picture steady while the drone tilts.",
           (0, -0.1, 0.95), (0, -0.7, 1.9), "#111827", [box(0.4, 0.3, 0.3), cyl(0.12, 0.2, (0, 0, 0.22), (90, 0, 0), c="#38bdf8")], "Payload")
    m.link("battery", "esc", "power")
    m.link("esc", "fc", "power / signal")
    for tag in ("fl", "fr", "bl", "br"):
        m.link("esc", f"mp_{tag}", "")
    m.link("rx", "fc", "commands")
    m.link("gps", "fc", "position")
    m.link("fc", "cam", "gimbal")
    m.link("frame", "battery", "mounts")
    return m.build()

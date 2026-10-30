from ._kit import Model, box, cyl, sphere, torus, spin, swing

TOPIC = "Robotic arm"
ALIASES = ["robotic arm", "robot arm", "robotic manipulator", "industrial robot", "manipulator", "6 axis robot", "6 dof arm", "mechanical arm"]


def build():
    m = Model("Robotic arm (6-axis, simplified)",
              "Each joint is a motor with a gearbox and sensor. A controller works out the angle of every joint so "
              "the gripper reaches a target point.")
    m.part("base", "Base", "Heavy fixed pedestal that bolts to the floor and keeps the arm stable.",
           (0, 0.2, 0), (0, -1.5, 0), "#475569", [cyl(1.3, 0.4), cyl(0.9, 0.3, (0, 0.3, 0), c="#334155")], "Structure")
    m.part("waist", "Waist joint (axis 1)", "Rotates the whole arm left and right around a vertical axis.",
           (0, 0.75, 0), (0, -0.4, 0), "#2563eb", [cyl(0.8, 0.7), cyl(0.5, 0.2, (0, 0.4, 0), c="#1e3a8a")], "Joints", anim=None)
    m.part("shoulder", "Shoulder joint (axis 2)", "Tilts the upper arm forward and back; carries most of the load.",
           (0, 1.45, 0), (0, 0.6, 0), "#dc2626", [box(1.0, 0.9, 1.0), cyl(0.5, 1.3, (0, 0.1, 0), (90, 0, 0), c="#7f1d1d")], "Joints")
    m.part("upper", "Upper arm", "Rigid link transmitting the shoulder's motion to the elbow.",
           (0, 2.9, 0), (0, 2.0, 0), "#e2e8f0", [box(0.7, 2.0, 0.7), box(0.5, 1.9, 0.5, (0, 0, 0.0), c="#cbd5e1")], "Links")
    m.part("elbow", "Elbow joint (axis 3)", "Bends the forearm up and down.",
           (0, 4.3, 0), (0, 3.6, 0), "#dc2626", [cyl(0.55, 1.0, rot=(90, 0, 0)), cyl(0.3, 1.1, rot=(90, 0, 0), c="#7f1d1d")], "Joints")
    m.part("forearm", "Forearm", "Link that carries the wrist forward to the working position.",
           (1.5, 4.3, 0), (2.6, 4.2, 0), "#e2e8f0", [box(2.3, 0.55, 0.55)], "Links")
    m.part("wrist", "Wrist joints (axes 4-6)", "Three small joints that rotate and tilt the gripper into the right orientation.",
           (2.85, 4.3, 0), (4.8, 4.7, 0), "#2563eb", [cyl(0.34, 0.5, rot=(0, 0, 90)), sphere(0.34, p=(0.35, 0, 0)), cyl(0.26, 0.4, (0.7, 0, 0), (0, 0, 90), c="#1e3a8a")], "Joints", anim=spin((1, 0, 0), 60))
    m.part("gripper", "Gripper (end effector)", "Two fingers driven by a small motor; this is the part that actually picks things up.",
           (3.7, 4.3, 0), (6.6, 4.7, 0), "#f59e0b",
           [box(0.45, 0.45, 0.6), box(0.7, 0.12, 0.1, (0.55, 0.22, 0.0)), box(0.7, 0.12, 0.1, (0.55, -0.22, 0.0)),
            box(0.1, 0.4, 0.1, (0.9, 0.2, 0)), box(0.1, 0.4, 0.1, (0.9, -0.2, 0))], "End effector")
    m.part("ctrl", "Controller", "Computer that does the inverse-kinematics maths and sends commands to every joint motor.",
           (-2.5, 0.5, 0), (-4.0, 1.5, 0), "#111827", [box(1.5, 1.0, 1.1), box(1.2, 0.1, 0.4, (0, 0.2, 0.56), c="#22c55e")], "Electronics")
    m.part("sens", "Encoders & sensors", "Measure each joint angle and force so the controller always knows where the arm is.",
           (-1.1, 2.0, 1.2), (-2.4, 3.5, 2.6), "#8b5cf6", [torus(0.22, 0.05, rot=(0, 0, 90)), box(0.25, 0.25, 0.25, (0, 0.4, 0)), box(0.25, 0.25, 0.25, (0, -0.4, 0))], "Electronics")
    m.chain(["base", "waist", "shoulder", "upper", "elbow", "forearm", "wrist", "gripper"], "")
    m.link("ctrl", "waist", "motor power")
    m.link("ctrl", "shoulder", "")
    m.link("ctrl", "elbow", "")
    m.link("ctrl", "gripper", "grip command")
    m.link("sens", "ctrl", "joint angles")
    return m.build()

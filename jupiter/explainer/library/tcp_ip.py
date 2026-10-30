from ._kit import Model, box, cyl, sphere

TOPIC = "TCP/IP network"
ALIASES = ["tcp ip network", "tcp/ip", "tcp ip", "tcpip", "tcp/ip model", "tcp ip model", "tcp ip layers", "network protocol stack", "internet protocol", "how the internet works",
           "osi model", "network layers", "networking", "computer network", "tcp and ip", "internet"]

LAYERS = [  # name, colour, description, label of the data unit
    ("Application", "#2bd9ff", "Programs such as your browser use protocols like HTTP, DNS and SMTP to ask for or send data.", "HTTP request"),
    ("Transport", "#35e08a", "TCP splits data into numbered segments, adds port numbers, and re-sends anything that is lost.", "TCP segment (ports)"),
    ("Internet", "#ffb020", "IP puts source and destination addresses on each packet so routers can forward it across networks.", "IP packet (addresses)"),
    ("Link", "#d36bff", "Ethernet or Wi-Fi moves frames between neighbouring devices using MAC addresses.", "Frame (MAC)"),
]
GAP = 0.9


def _y(i):
    return (1.5 - i) * GAP


def build():
    m = Model("TCP/IP network", "A web request travels DOWN the sender's four layers, hops across routers, then travels UP the receiver's layers. "
              "Each layer wraps the data with its own header.", kind="concept", directed=True, flow=True)
    for host, x in (("A", -3.4), ("B", 3.4)):
        for i, (name, col, desc, unit) in enumerate(LAYERS):
            who = "Sender (your PC)" if host == "A" else "Receiver (web server)"
            m.part(f"{host.lower()}{i}", f"{name} layer · {host}", f"{who}: {desc}", (x * 0.8, _y(i) * 0.5, 0), (x * 0.2, _y(i) * 0.5, 0), col,
                   [box(2.3, 0.5, 1.3), box(2.0, 0.08, 1.0, (0, 0.29, 0), c="#0b1220")], f"Host {host}", step=i if host == "A" else 6 + (3 - i))
    for tag, x in (("1", -0.8), ("2", 0.8)):
        m.part(f"r{tag}", f"Router {tag}", "Reads each packet's IP destination address and forwards it to the next router closer to it.",
               (x * 0.7, _y(2) * 0.5, 0), (x * 0.3, _y(2) * 0.5 + 0.0, 0), "#ffb020",
               [box(1.1, 0.4, 0.9), cyl(0.04, 0.5, (-0.35, 0.4, 0)), cyl(0.04, 0.5, (0.35, 0.4, 0)), sphere(0.07, p=(-0.35, 0.68, 0)), sphere(0.07, p=(0.35, 0.68, 0))],
               "Network", step=4 + int(tag))
    chain = ["a0", "a1", "a2", "a3", "r1", "r2", "b3", "b2", "b1", "b0"]
    labels = ["TCP adds ports", "IP adds addresses", "Link adds MAC", "frame sent", "forward", "frame arrives", "MAC checked", "IP checked", "ports -> app"]
    for (a, b), lab in zip(zip(chain, chain[1:]), labels):
        m.link(a, b, lab)
    return m.build()

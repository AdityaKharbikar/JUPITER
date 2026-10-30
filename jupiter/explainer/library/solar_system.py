from ._kit import Model, sphere, torus, cyl, spin, orbit

TOPIC = "Solar system"
ALIASES = ["solar system", "planetary system", "planets", "simple planetary system", "the planets", "sun and planets", "our solar system"]

# name, orbit radius, planet radius, colour, orbit speed deg/s, fact
PLANETS = [
    ("Mercury", 2.3, 0.14, "#9ca3af", 46, "Smallest planet and closest to the Sun; a year lasts only 88 Earth days."),
    ("Venus", 3.1, 0.3, "#fcd34d", 34, "Thick carbon-dioxide atmosphere makes it the hottest planet."),
    ("Earth", 4.0, 0.32, "#3b82f6", 28, "The only known planet with life; the Moon orbits it."),
    ("Mars", 4.9, 0.22, "#ef4444", 22, "Cold, dusty 'red planet' with the tallest volcano in the solar system."),
    ("Jupiter", 6.7, 0.85, "#d6a35c", 12, "Largest planet: a gas giant whose Great Red Spot is a storm bigger than Earth."),
    ("Saturn", 8.7, 0.7, "#e7c98f", 8, "Gas giant famous for its bright rings of ice and rock."),
    ("Uranus", 10.4, 0.45, "#67e8f9", 5.5, "Ice giant that rotates on its side."),
    ("Neptune", 11.9, 0.43, "#2563eb", 4.2, "Farthest planet; cold, dark and battered by supersonic winds."),
]


def build():
    m = Model("Solar system (not to scale)",
              "Eight planets travel around the Sun in nearly circular orbits held by gravity; planets nearer the Sun move faster.",
              start_exploded=False)
    m.spec["no_explode"] = True
    m.spec["camera"] = {"pitch": 0.75, "zoom": 1.55}
    m.spec["disclaimer"] = "Sizes and distances are NOT to scale - real distances are far larger relative to the planets."
    m.part("sun", "Sun", "A star: a ball of hot plasma whose gravity holds the whole system together and whose light powers life on Earth.",
           (0, 0, 0), (0, 0, 0), "#fbbf24", [sphere(1.35), sphere(1.5, c="#f59e0b")], "Star", anim=spin((0, 1, 0), 8), bound=1.6)
    for i, (name, r, size, col, spd, fact) in enumerate(PLANETS):
        ring = torus(r, 0.012, (-r, 0, 0), c="#3a5a7a")
        size = size * 1.5
        prims = [sphere(size), ring]
        if name == "Saturn":
            prims.append(torus(size * 1.55, 0.07, c="#d9c28a"))
        if name == "Earth":
            prims.append(sphere(0.08, p=(0.55, 0, 0), c="#d1d5db"))
        if name == "Jupiter":
            prims.append(torus(size * 0.99, 0.05, c="#b45309"))
        m.part(name.lower(), name, fact, (r, 0, 0), (0, 0, 0), col, prims, "Planet", anim=orbit(spd, (i * 83) % 360), step=i + 1, bound=size * 1.8)
    m.chain(["sun", "mercury", "venus", "earth", "mars", "jupiter", "saturn", "uranus", "neptune"], "")
    for l in m.spec["links"]:
        l["label"] = ""
    m.spec["links"] = []                    # orbits are drawn by the rings; link lines would only clutter the picture
    return m.build()

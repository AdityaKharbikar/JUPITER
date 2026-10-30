from ._kit import Model, box, cyl, sphere, rod3, pulse

TOPIC = "Neural network"
ALIASES = ["neural network", "neural net", "artificial neural network", "ann", "deep learning", "deep neural network", "mlp", "perceptron", "machine learning model", "ai model"]

LAYERS = [("Input layer", "#2bd9ff", 4, -4.2, "Receives the raw numbers (pixels, words turned into numbers, sensor values), one node per input feature."),
          ("Hidden layer 1", "#35e08a", 5, -1.4, "Each node takes a weighted sum of the inputs and applies an activation function, detecting simple patterns."),
          ("Hidden layer 2", "#ffb020", 5, 1.4, "Combines the first layer's patterns into more complex features."),
          ("Output layer", "#d36bff", 3, 4.2, "Produces the prediction, for example a probability for each possible class.")]


def _nodes(n, x):
    return [(x, (i - (n - 1) / 2) * 0.95, 0.0) for i in range(n)]


def build():
    m = Model("Neural network", "Numbers flow left to right through layers of simple nodes. Learning means nudging the connection "
              "weights until the output becomes more correct.", kind="concept", directed=True, flow=True)
    m.spec["no_explode"] = True
    layer_nodes = [_nodes(n, x) for (_, _, n, x, _) in LAYERS]
    for i, (name, col, n, x, desc) in enumerate(LAYERS):
        m.part(f"l{i}", name, desc, (0, 0, 0), (0, 0, 0), col, [sphere(0.32, p=p) for p in layer_nodes[i]], "Layers", step=i * 2,
               anim=pulse(0.05, 0.6, i * 0.35))
    rods = []
    for a, b in zip(layer_nodes, layer_nodes[1:]):
        rods += [rod3(p, q, 0.012, "#5b7aa8") for p in a for q in b]
    m.part("w", "Weights (connections)", "Every line has a weight: a number saying how strongly one node influences the next. Training adjusts them.",
           (0, 0, 0), (0, 0, 0), "#5b7aa8", rods, "Learning", step=1)
    m.part("act", "Activation function", "A small non-linear rule (such as ReLU) applied at each node, which lets the network learn curved, complex patterns.",
           (0, -3.2, 0), (0, 0, 0), "#fb7185", [box(1.6, 0.12, 0.8), box(0.7, 0.14, 0.14, (-0.35, 0.1, 0)), box(0.7, 0.14, 0.14, (0.35, 0.18, 0), (0, 0, 28))], "Learning", step=3)
    m.part("loss", "Loss function", "Measures how wrong the prediction was compared with the correct answer.",
           (4.2, -3.2, 0), (0, 0, 0), "#f87171", [box(1.1, 0.5, 0.8), sphere(0.2, p=(0, 0.45, 0))], "Learning", step=7)
    m.part("opt", "Optimizer (backpropagation)", "Uses the loss to work out, layer by layer backwards, how to adjust each weight a little to reduce the error.",
           (-1.4, -3.2, 0), (0, 0, 0), "#a78bfa", [cyl(0.5, 0.4), box(1.1, 0.12, 0.3, (0, 0.28, 0))], "Learning", step=8)
    m.chain(["l0", "l1", "l2", "l3"], "forward pass")
    m.link("l3", "loss", "compare with truth")
    m.link("loss", "opt", "error")
    m.link("opt", "w", "update weights")
    m.link("act", "l1", "")
    return m.build()

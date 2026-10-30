# JUPITER Modular Architecture

Migration-safe modularization of `jupiter_try2.py`. `jupiter_try2_reference.py` is retained as the original reference snapshot.

Run with: `python main.py`

The new Skill registry gets first chance to handle migrated commands; the original `handle_action()` remains as a compatibility fallback while features are moved one by one.


## Windows troubleshooting

### `Jupiter` object has no attribute `router`
The router is initialized in `jupiter/core/assistant.py` as `self.router = HybridRouter(self)`.

### Windows "Part of this app has been blocked" for `_beam_utils.cp312-win_amd64.pyd`
That file belongs to a SpaCy native extension. Argos Translate can pull in SpaCy, so this modular
version keeps Argos lazy-loaded: normal startup does not import it. Translation can still be attempted
when explicitly requested. If Windows Smart App Control blocks the SpaCy extension, translation may
remain unavailable until that Python environment/package issue is resolved.

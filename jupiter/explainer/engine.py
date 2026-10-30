"""ExplainerEngine: topic -> curated model | cached model | freshly generated model -> HTML file. Measures everything."""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import library, layout
from .llm import GenerationError, Generator
from .render import WEB_DIR, write_html
from .schema import slug, validate_spec


@dataclass
class BuildResult:
    ok: bool
    topic: str
    title: str = ""
    source: str = ""              # curated | cache | generated
    html_path: str = ""
    spec: dict = field(default_factory=dict)
    seconds: float = 0.0
    model: str = ""
    error: str = ""
    kind: str = "physical"

    @property
    def n_parts(self):
        return len(self.spec.get("parts", []))


class ExplainerEngine:
    def __init__(self, ollama_url, model, data_dir, metrics=None, http=None):
        self.base = Path(data_dir) / "explainer"
        self.cache_dir = self.base / "cache"
        self.html_dir = self.base / "html"
        for d in (self.cache_dir, self.html_dir):
            d.mkdir(parents=True, exist_ok=True)
        self.metrics = metrics
        self.model = model
        self.gen = Generator(ollama_url, model, http=http)
        self._lock = threading.Lock()
        self.last: BuildResult | None = None

    # ---- paths -----------------------------------------------------------
    def _spec_path(self, key):
        return self.cache_dir / f"{key}.json"

    def _html_path(self, key):
        return self.html_dir / f"{key}.html"

    def _html_fresh(self, html: Path, *deps: Path) -> bool:
        try:
            m = html.stat().st_mtime
            return all(d.stat().st_mtime <= m for d in deps)
        except OSError:
            return False

    # ---- public ----------------------------------------------------------
    def curated_topics(self):
        return library.topics()

    def match_curated(self, topic):
        return library.find(topic)

    def pregenerate(self):
        """Build the HTML for every curated model now so opening one later is instant. Returns {key: seconds}."""
        out = {}
        for entry in library.catalog():
            t0 = time.perf_counter()
            try:
                self._build_curated(entry["key"])
                out[entry["key"]] = time.perf_counter() - t0
            except Exception as exc:               # pragma: no cover - reported to the caller instead of crashing startup
                out[entry["key"]] = f"error: {exc}"
        return out

    def build(self, topic: str, progress=None, allow_llm=True, cancelled=None, force_new=False) -> BuildResult:
        progress = progress or (lambda *a: None)
        t0 = time.perf_counter()
        topic = (topic or "").strip()
        res = BuildResult(False, topic)
        try:
            key = None if force_new else library.find(topic)
            if key:
                progress("lookup", 0.5, "Found a hand-built model")
                res = self._build_curated(key)
                res.topic = topic
                cache_hit = True
                ttfo = time.perf_counter() - t0
            else:
                cached = None if force_new else self._load_cached(topic)
                if cached:
                    progress("lookup", 0.5, "Loaded from cache")
                    spec = cached
                    html = self._html_path("gen_" + slug(topic))
                    if not self._html_fresh(html, WEB_DIR / "viewer.js", WEB_DIR / "template.html", self._spec_path("gen_" + slug(topic))):
                        write_html(spec, html)
                    res = BuildResult(True, topic, spec["title"], "cache", str(html), spec, 0, spec.get("_model", ""), kind=spec.get("kind", "physical"))
                    cache_hit = True
                    ttfo = time.perf_counter() - t0
                elif not allow_llm:
                    raise GenerationError("That topic is not in the built-in library and AI generation is off.")
                else:
                    progress("lookup", 0.05, "Not in the library - generating")
                    data, info = self.gen.generate(topic, progress, cancelled)
                    progress("layout", 0.92, "Laying out parts")
                    spec = layout.to_render_spec(data, topic=topic, model=self.model, seconds=info["total_s"])
                    problems = validate_spec(spec)
                    if problems:
                        raise GenerationError("Generated model failed validation: " + "; ".join(problems[:2]))
                    spec["_model"] = self.model
                    self._save_cached(topic, spec)
                    html = self._html_path("gen_" + slug(topic))
                    write_html(spec, html)
                    res = BuildResult(True, topic, spec["title"], "generated", str(html), spec, 0, self.model, kind=spec["kind"])
                    cache_hit = False
                    ttfo = info.get("ttfo_s")
            res.seconds = time.perf_counter() - t0
            progress("done", 1.0, f"{res.title}: {res.n_parts} parts ({res.source}, {res.seconds:.2f}s)")
            self._log(res, cache_hit, ttfo, True)
        except GenerationError as exc:
            res = BuildResult(False, topic, error=str(exc), seconds=time.perf_counter() - t0, source="failed", model=self.model)
            self._log(res, False, None, False)
        except Exception as exc:                      # never let an unexpected bug kill the assistant thread
            res = BuildResult(False, topic, error=f"Unexpected error: {exc}", seconds=time.perf_counter() - t0, source="failed")
            self._log(res, False, None, False)
        self.last = res
        return res

    # ---- internals ---------------------------------------------------------
    def _build_curated(self, key) -> BuildResult:
        mod_file = Path(library.__file__).parent / f"{key}.py"
        spec = library.get_spec(key)
        html = self._html_path("cur_" + key)
        spec.setdefault("meta_line", "Hand-built educational model · stylised, not engineering CAD")
        if not self._html_fresh(html, WEB_DIR / "viewer.js", WEB_DIR / "template.html", mod_file):
            write_html(spec, html)
        return BuildResult(True, spec["title"], spec["title"], "curated", str(html), spec, 0, "", kind=spec.get("kind", "physical"))

    def _load_cached(self, topic):
        p = self._spec_path("gen_" + slug(topic))
        try:
            spec = json.loads(p.read_text(encoding="utf-8"))
            return spec if not validate_spec(spec) else None
        except (OSError, ValueError):
            return None

    def _save_cached(self, topic, spec):
        p = self._spec_path("gen_" + slug(topic))
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

    def _log(self, res: BuildResult, cache_hit, ttfo, ok):
        if self.metrics:
            self.metrics.record("explainer.build", model=res.model if res.source in ("generated",) else "",
                                cache_hit=cache_hit, ttfo_s=ttfo, total_s=res.seconds, ok=ok,
                                detail=f"{res.source}:{res.topic}" + (f" ERR {res.error}" if res.error else ""))

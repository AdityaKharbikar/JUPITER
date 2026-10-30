from ..common import *
from .model_router import ModelRouter


class LLMMixin:
    def _build_messages(self, user_input: str) -> dict:
        """Assemble the system prompt, recalled summaries and recent context
        into an Ollama message list. Shared by think() and think_stream() so
        the two can never drift apart.

        Returns {"messages": [...], "_prefix": str} where _prefix is a
        deterministic note to prepend when a requested recall wasn't found.
        """
        # Get conversation summary if exists
        summary = self._get_conversation_summary()

        system_prompt = f"""
    You are JUPITER, a personal AI assistant having a spoken conversation with {self.user_name}.

    IMPORTANT — how you fit into the system: real actions (playing music, opening
    apps, setting timers/reminders, searching the web, checking weather,
    translating, etc.) are handled by SEPARATE code that runs BEFORE you're ever
    called. If a message has reached you at all, that means none of those direct
    actions matched it — so you are NOT the thing that plays songs, opens
    YouTube, or sets timers. Never say or imply that you just did one of those
    things, and never invent details of an action "happening" (no "here's the
    video", no "playing it now", no describing search results you didn't
    actually retrieve). If the message looks like it was meant to trigger an
    action but reached you instead, say plainly that you didn't catch it as a
    command and ask the user to repeat it — don't perform an imaginary version of
    it in words.

    Speak naturally, like a real spoken reply — not a script. Never use stage
    directions, asterisked actions, or narrate a scene (no "*plays the song*",
    no "there it is!", no invented dialogue). Just answer directly, in your own
    voice, as if you were talking.

    Always address the user as "{self.user_name}" — never switch to any other title.
    Be concise — this is speech, not an essay. A sentence or two is usually enough.
    Never break character. Never say "As an AI language model".
    """
        # Add summary to system prompt if exists
        if summary:
            system_prompt += f"\n\nPrevious conversation summary:\n{summary}\n"
        facts = self._facts_for_prompt()
        if facts:
            system_prompt += (
                f"\n\nThings {self.user_name} has asked you to remember:\n{facts}\n"
                "Use them when relevant; do not recite them unprompted.\n"
            )

        # On-demand recall: only pull in a DIFFERENT conversation's summary if the
        # user explicitly asks for it in this message. Supports both:
        #   "use the summary of conversation 1 to answer this"  (specific number)
        #   "use the summary of the previous conversation..."   (relative)
        recall_requested = False
        recall_target_id = None
        specific_match = RECALL_SPECIFIC_PATTERN.search(user_input.lower())
        if specific_match:
            recall_requested = True
            num = specific_match.group(1) or specific_match.group(2)
            recall_target_id = int(num)
        elif RECALL_PREVIOUS_PATTERN.search(user_input.lower()):
            recall_requested = True
            recall_target_id = self._get_previous_conversation_id()

        recall_missing_note = None
        if recall_requested:
            recalled_summary = self._get_or_generate_summary(recall_target_id) if recall_target_id is not None else None
            if recalled_summary:
                system_prompt += (
                    f"\n\nThe user has asked you to recall an earlier, separate "
                    f"conversation (#{recall_target_id}). Its summary:\n{recalled_summary}\n"
                    f"Use it only to help answer the user's current message.\n"
                )
            else:
                # Don't rely on the model to notice/mention this on its own —
                # answer normally, but prefix the reply with a deterministic note.
                if recall_target_id is not None:
                    recall_missing_note = f"I don't have a conversation #{recall_target_id}, so I'm answering without that context. "
                else:
                    recall_missing_note = "There's no previous conversation to recall yet, so I'm answering without that context. "

        # Build a compact context budget. Four recent turns are enough for voice
        # assistance in most cases and prevent prompt growth from dominating latency.
        recent = self._fetch_recent_context(limit=4)
        clipped = []
        for item in recent:
            content = item.get("content", "")
            if len(content) > 1800:
                content = content[-1800:]
            clipped.append({"role": item["role"], "content": content})
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(clipped)
        messages.append({"role": "user", "content": user_input[-3000:]})
        return {"messages": messages, "_prefix": recall_missing_note or ""}


    def _get_model_router(self):
        router = getattr(self, "model_router", None)
        if router is None:
            router = ModelRouter(self)
            self.model_router = router
        return router

    def _select_model(self, user_input: str) -> str:
        return self._get_model_router().choose(user_input)

    def _generation_options(self, model: str) -> dict:
        coding = model == self._get_model_router().CODING_MODEL
        return {
            "temperature": 0.2 if coding else 0.4,
            "num_predict": 420 if coding else 180,
            "num_ctx": 4096,
        }

    def think(self, user_input: str) -> str:
        """Send user input + compact context to the best installed local model."""
        built = self._build_messages(user_input)
        prefix = built["_prefix"]
        model = self._select_model(user_input)
        self.last_model = model
        t0 = time.perf_counter()
        try:
            response = self.http.post(
                self.ollama_url,
                json={
                    "model": model, "think": False,
                    "messages": built["messages"],
                    "stream": False,
                    "keep_alive": "15m",
                    "options": self._generation_options(model),
                },
                timeout=(5, 90),
            )
            self.last_llm_latency = time.perf_counter() - t0
            if response.status_code == 200:
                reply = response.json().get("message", {}).get("content", "").strip()
                return (prefix + reply) if prefix else reply
            return f"Ollama error ({response.status_code}), {self.user_name}."
        except requests.exceptions.ConnectionError:
            self.last_llm_latency = time.perf_counter() - t0
            return f"I'm offline, {self.user_name}. Ollama is not running."
        except Exception as e:
            self.last_llm_latency = time.perf_counter() - t0
            return f"Error: {str(e)[:80]}"

    def think_stream(self, user_input: str):
        """Same as think(), but queues each sentence for speech as the model
        produces it, so Jupiter starts talking after the first sentence and the
        model keeps generating while it speaks. A spoken "stop" aborts the
        stream (closing the connection makes Ollama stop generating).

        Falls back to the non-streaming path on ANY failure, so a streaming
        hiccup degrades to the old behaviour rather than losing the answer.
        """
        built = self._build_messages(user_input)
        prefix = built["_prefix"]

        model = self._select_model(user_input)
        self.last_model = model
        spoken_any = False
        collected = []
        buffer = ""
        t0 = time.perf_counter()
        try:
            with self.http.post(
                self.ollama_url,
                json={
                    "model": model, "think": False,
                    "messages": built["messages"],
                    "stream": True,
                    "keep_alive": "15m",
                    "options": self._generation_options(model),
                },
                # (connect, read): a dead Ollama fails in ~5s instead of 60
                timeout=(5, 60),
                stream=True,
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                if prefix:
                    self.speak(prefix.strip(), wait=False)
                    spoken_any = True
                for line in response.iter_lines():
                    if self._interrupted.is_set():
                        break
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except ValueError:
                        continue
                    piece = payload.get("message", {}).get("content", "")
                    if piece:
                        buffer += piece
                        collected.append(piece)
                    # Flush on sentence boundaries so Piper gets natural units.
                    # The first one goes out early (14+ chars) for a fast start.
                    while True:
                        match = re.search(r'[.!?](?:\s|$)', buffer)
                        if not match or match.end() < (14 if not spoken_any else 25):
                            break
                        sentence, buffer = buffer[:match.end()].strip(), buffer[match.end():]
                        if sentence:
                            self.speak(sentence, wait=False)
                            spoken_any = True
                    if payload.get("done"):
                        break
            if buffer.strip() and not self._interrupted.is_set():
                self.speak(buffer.strip(), wait=False)
                spoken_any = True
            self.wait_speech_done()
            self.last_llm_latency = time.perf_counter() - t0
            full = prefix + "".join(collected)
            if (spoken_any or self._interrupted.is_set()) and full.strip():
                return full.strip()
            raise RuntimeError("empty stream")
        except Exception as e:
            print(f"[Streaming Error] {e}")
            self.wait_speech_done()
            if spoken_any or self._interrupted.is_set():
                # Already said something (or you cut it off) - don't repeat it
                return (prefix + "".join(collected)).strip() or "I lost my train of thought, sir."
            reply = self.think(user_input)
            self.speak(reply)
            return reply

    def _warm_up_ollama(self):
        """Load the model into memory in the background while Jupiter is
        greeting you, so the first real question isn't slow."""
        def _go():
            try:
                requests.post(
                    self.ollama_url,
                    json={"model": self._get_model_router().GENERAL_MODEL, "think": False, "messages": [{"role": "user", "content": "hi"}],
                          "stream": False, "keep_alive": "15m", "options": {"num_predict": 1, "num_ctx": 4096}},
                    timeout=(3, 60)
                )
            except Exception:
                pass
        threading.Thread(target=_go, name="jupiter-warmup", daemon=True).start()

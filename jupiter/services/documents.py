from ..common import *


class DocumentService:
    def _embed(self, text: str):
        """Return an embedding vector from Ollama, or None on any failure."""
        try:
            resp = requests.post(
                self.ollama_url.replace("/api/chat", "/api/embeddings"),
                json={"model": DOC_EMBED_MODEL, "prompt": text[:8000]},
                timeout=(5, 60)
            )
            if resp.status_code == 200:
                vec = resp.json().get("embedding")
                if vec:
                    return vec
            else:
                print(f"[Embed Error] HTTP {resp.status_code}")
        except Exception as e:
            print(f"[Embed Error] {e}")
        return None

    @staticmethod
    def _chunk_text(text: str):
        """Split into overlapping windows so a sentence spanning a boundary
        still lands intact in at least one chunk."""
        chunks = []
        step = max(1, DOC_CHUNK_CHARS - DOC_CHUNK_OVERLAP)
        for start in range(0, len(text), step):
            chunk = text[start:start + DOC_CHUNK_CHARS].strip()
            if len(chunk) > 40:
                chunks.append(chunk)
            if start + DOC_CHUNK_CHARS >= len(text):
                break
        return chunks

    @staticmethod
    def _pack_vector(vec):
        return struct.pack(f"<{len(vec)}f", *vec)

    @staticmethod
    def _unpack_vector(blob):
        return struct.unpack(f"<{len(blob) // 4}f", blob)

    @staticmethod
    def _cosine(a, b):
        if len(a) != len(b):
            return -1.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return -1.0
        return dot / (na * nb)

    def index_documents(self, folder: str = None):
        """Read plain-text files under a folder and store their embeddings.
        Hard-capped at DOC_MAX_FILES files and DOC_MAX_FILE_BYTES each, so
        pointing it at the wrong directory wastes a little time, not your
        whole evening."""
        folder = (folder or "").strip().strip('"').rstrip("?.!")
        if not folder:
            folder = os.path.join(os.path.expanduser("~"), "Documents")
        folder = os.path.expanduser(folder)

        if not os.path.isdir(folder):
            self.speak(f"I can't find the folder {folder}, {self.user_name}.")
            return

        files = []
        for root, dirs, names in os.walk(folder):
            # Skip hidden and dependency directories — nothing useful, lots of files
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                       ("node_modules", "__pycache__", "venv", ".venv", "site-packages")]
            for name in names:
                if name.lower().endswith(DOC_EXTENSIONS):
                    path = os.path.join(root, name)
                    try:
                        if os.path.getsize(path) <= DOC_MAX_FILE_BYTES:
                            files.append(path)
                    except OSError:
                        continue
                if len(files) >= DOC_MAX_FILES:
                    break
            if len(files) >= DOC_MAX_FILES:
                break

        if not files:
            self.speak(f"I found no readable text files under {folder}, {self.user_name}.")
            return

        self.speak(f"Indexing {len(files)} file(s), {self.user_name}. This runs locally and may take a minute.")

        # Probe the embedding model once before doing the work
        if self._embed("probe") is None:
            self.speak(
                f"I couldn't reach the embedding model, {self.user_name}. "
                f"Run: ollama pull {DOC_EMBED_MODEL}"
            )
            return

        indexed = 0
        chunks_total = 0
        for path in files:
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError as e:
                print(f"[Index Skip] {path}: {e}")
                continue
            if not content.strip():
                continue

            mtime = str(os.path.getmtime(path))
            with self._db_lock:
                existing = self.conn.execute(
                    "SELECT mtime FROM documents WHERE path = ? LIMIT 1", (path,)
                ).fetchone()
            if existing and existing[0] == mtime:
                continue  # unchanged since last index

            chunks = self._chunk_text(content)
            embedded_chunks = []
            embedding_failed = False

            for i, chunk in enumerate(chunks):
                vec = self._embed(chunk)
                if vec is None:
                    embedding_failed = True
                    print(f"[Index Skip] {path}: embedding failed for chunk {i + 1}/{len(chunks)}")
                    break
                embedded_chunks.append((i, chunk, vec))

            # Replace the old index only after every chunk succeeds.
            if embedding_failed:
                continue

            with self._db_lock:
                self.conn.execute("DELETE FROM documents WHERE path = ?", (path,))
                indexed_at = self._get_ist_time().isoformat()
                for i, chunk, vec in embedded_chunks:
                    self.conn.execute(
                        "INSERT INTO documents (path, chunk_index, text, embedding, mtime, indexed_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (path, i, chunk, self._pack_vector(vec), mtime, indexed_at)
                    )
                self.conn.commit()

            chunks_total += len(embedded_chunks)
            indexed += 1
            print(f"  indexed {os.path.basename(path)}")

        self._save_setting("doc_folder", folder)
        self.speak(f"Indexed {indexed} file(s) into {chunks_total} chunk(s), {self.user_name}.")

    def ask_documents(self, question: str, top_k: int = 4):
        question = question.strip().rstrip("?.!")
        if not question:
            self.speak(f"What should I look for, {self.user_name}?")
            return
        with self._db_lock:
            rows = self.conn.execute("SELECT path, text, embedding FROM documents").fetchall()
        if not rows:
            self.speak(
                f"I haven't indexed any documents yet, {self.user_name}. "
                f"Say: index my documents at, then the folder path."
            )
            return

        q_vec = self._embed(question)
        if q_vec is None:
            self.speak(f"I couldn't embed that question, {self.user_name}. Is Ollama running?")
            return

        scored = []
        for path, text, blob in rows:
            try:
                score = self._cosine(q_vec, self._unpack_vector(blob))
            except Exception:
                continue
            scored.append((score, path, text))
        scored.sort(reverse=True, key=lambda x: x[0])
        best = [s for s in scored[:top_k] if s[0] > 0.2]

        if not best:
            self.speak(f"Nothing in your documents looked relevant, {self.user_name}.")
            return

        context = "\n\n---\n\n".join(
            f"From {os.path.basename(p)}:\n{t}" for _, p, t in best
        )
        prompt = (
            f"Answer the question using ONLY the excerpts below. If they don't "
            f"contain the answer, say so plainly.\n\n{context}\n\nQuestion: {question}"
        )
        try:
            resp = requests.post(
                self.ollama_url,
                json={
                    "model": LLM_MODEL, "think": False,
                    "messages": [
                        {"role": "system", "content": "You answer strictly from the provided excerpts."},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 250},
                },
                timeout=(5, 60)
            )
            if resp.status_code == 200:
                answer = resp.json()["message"]["content"].strip()
                sources = ", ".join(sorted({os.path.basename(p) for _, p, _ in best}))
                self.speak(answer)
                self.speak(f"Source: {sources}.")
            else:
                self.speak(f"Ollama returned an error, {self.user_name}.")
        except Exception as e:
            print(f"[Doc Q&A Error] {e}")
            self.speak(f"I couldn't answer from your documents, {self.user_name}.")

    def document_status(self):
        with self._db_lock:
            row = self.conn.execute(
                "SELECT COUNT(DISTINCT path), COUNT(*) FROM documents"
            ).fetchone()
            folder = self.conn.execute(
                "SELECT value FROM metadata WHERE key = 'doc_folder'"
            ).fetchone()
        if not row or not row[0]:
            self.speak(f"No documents are indexed, {self.user_name}.")
            return
        where = f" from {folder[0]}" if folder else ""
        self.speak(f"{row[0]} file(s) indexed{where}, {row[1]} chunk(s) total, {self.user_name}.")

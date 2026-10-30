from datetime import datetime


class ProductivityService:
    """Task/project layer for the next productivity phase."""

    def setup_productivity(self):
        with self._db_lock:
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project TEXT,
                    title TEXT NOT NULL,
                    priority INTEGER DEFAULT 3,
                    due_time TEXT,
                    status TEXT DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            self.conn.commit()

    def add_task(self, title: str, project=None, priority=3, due_time=None):
        self.setup_productivity()
        with self._db_lock:
            cur = self.conn.execute(
                "INSERT INTO tasks(project,title,priority,due_time,status,created_at) VALUES (?,?,?,?,?,?)",
                (project, title, int(priority), due_time, "open", self._get_ist_time().isoformat()),
            )
            self.conn.commit()
            return cur.lastrowid

    def list_tasks(self, project=None):
        self.setup_productivity()
        query = "SELECT id,project,title,priority,due_time,status,created_at FROM tasks WHERE status='open'"
        args = []
        if project:
            query += " AND project=?"
            args.append(project)
        query += " ORDER BY priority ASC, due_time IS NULL, due_time"
        with self._db_lock:
            return self.conn.execute(query, args).fetchall()

    def complete_task(self, task_id: int):
        self.setup_productivity()
        with self._db_lock:
            self.conn.execute(
                "UPDATE tasks SET status='done', completed_at=? WHERE id=?",
                (self._get_ist_time().isoformat(), task_id),
            )
            self.conn.commit()

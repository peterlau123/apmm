#!/usr/bin/env python3
"""
Hermes Kanban Manager - SQLite-backed Kanban Tracking

Based on Hermes Kanban v1 spec (April 25, 2026).
Provides durable, profile-aware work-queue architecture for multi-agent collaboration.

Key features:
- SQLite-backed tasks table (not JSON) for durability and concurrent access
- Status semantics: todo, ready, running, blocked, done, archived
- Task_links for dependency graph
- Task_comments for human-in-the-loop
- Task_events for audit trail
- Atomic claim via compare-and-swap (CAS)
- Workspace kinds: scratch, dir:<path>, worktree

Storage: {run_dir}/kanban.db (SQLite)
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple
import sys
import time
import os

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SKILL_DIR))

from shared.config_loader import get_paths, load_workflow_state


# Schema version
SCHEMA_VERSION = "hermes_kanban_v1"

# SQL Schema (from Hermes spec)
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT,
    assignee TEXT,
    status TEXT NOT NULL DEFAULT 'todo',
    priority INTEGER DEFAULT 0,
    created_by TEXT,
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    completed_at INTEGER,
    workspace_kind TEXT NOT NULL DEFAULT 'scratch',
    workspace_path TEXT,
    claim_lock TEXT,
    claim_expires INTEGER,
    tenant TEXT,
    progress_passed INTEGER DEFAULT 0,
    progress_total INTEGER DEFAULT 0,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS task_links (
    parent_id TEXT NOT NULL,
    child_id TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id),
    FOREIGN KEY (parent_id) REFERENCES tasks(id),
    FOREIGN KEY (child_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS task_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_assignee_status ON tasks(assignee, status);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_links_child ON task_links(child_id);
CREATE INDEX IF NOT EXISTS idx_links_parent ON task_links(parent_id);
CREATE INDEX IF NOT EXISTS idx_comments_task ON task_comments(task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id, created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_tenant ON tasks(tenant);
"""


class HermesKanbanManager:
    """Hermes Kanban Manager - SQLite-backed"""

    # Status values (from Hermes spec)
    STATUS_TODO = "todo"
    STATUS_READY = "ready"
    STATUS_RUNNING = "running"
    STATUS_BLOCKED = "blocked"
    STATUS_DONE = "done"
    STATUS_ARCHIVED = "archived"

    # Workspace kinds
    WORKSPACE_SCRATCH = "scratch"
    WORKSPACE_WORKTREE = "worktree"
    WORKSPACE_DIR = "dir"

    # Default lanes for board view (derived from status)
    DEFAULT_LANES = [
        {"name": "Backlog", "status": "todo", "description": "Created, parents not done"},
        {"name": "Ready", "status": "ready", "description": "All parents done, claimable"},
        {"name": "Running", "status": "running", "description": "Claimed and executing"},
        {"name": "Blocked", "status": "blocked", "description": "Waiting for input"},
        {"name": "Done", "status": "done", "description": "Completed"},
        {"name": "Passed", "status": "done", "description": "Batch passed", "color": "green"},
        {"name": "Failed", "status": "done", "description": "Batch failed", "color": "red"},
    ]

    def __init__(self, workflow_state_path: Optional[Path] = None, db_path: Optional[Path] = None):
        """
        Initialize Hermes Kanban Manager

        Args:
            workflow_state_path: workflow_state.json path for resolving paths
            db_path: Custom kanban.db path (optional)
        """
        self.paths = get_paths(workflow_state_path)

        if db_path:
            self.db_path = Path(db_path)
        else:
            self.db_path = self.paths["run_dir"] / "kanban.db"

        self.workflow_state_path = workflow_state_path or self.paths["workflow_state"]
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create database and schema if not exists"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")  # WAL for concurrent access
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        conn.close()

        print(f"[KANBAN] Database initialized: {self.db_path}")

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection with WAL mode"""
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _now_ts(self) -> int:
        """Get current timestamp as Unix integer"""
        return int(datetime.now(timezone.utc).timestamp())

    def _generate_id(self) -> str:
        """Generate task ID like t_9f2a"""
        import random
        chars = "0123456789abcdef"
        return "t_" + "".join(random.choice(chars) for _ in range(4))

    # === Task CRUD ===

    def create_task(
        self,
        title: str,
        body: Optional[str] = None,
        assignee: Optional[str] = None,
        created_by: str = "supervisor",
        workspace_kind: str = "scratch",
        workspace_path: Optional[str] = None,
        tenant: Optional[str] = None,
        parent_ids: Optional[List[str]] = None,
        progress_total: int = 0
    ) -> Dict[str, Any]:
        """
        Create a new task

        Args:
            title: Task title
            body: Optional body text
            assignee: Profile name (nullable = unassigned)
            created_by: Creator profile or "user"
            workspace_kind: scratch, worktree, or dir:<path>
            workspace_path: Resolved workspace path
            tenant: Optional tenant context
            parent_ids: List of parent task IDs for dependencies
            progress_total: Total items for progress tracking

        Returns:
            dict: Created task data
        """
        task_id = self._generate_id()
        now = self._now_ts()

        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO tasks
                   (id, title, body, assignee, status, created_by, created_at,
                    workspace_kind, workspace_path, tenant, progress_total)
                   VALUES (?, ?, ?, ?, 'todo', ?, ?, ?, ?, ?, ?)""",
                (task_id, title, body, assignee, created_by, now,
                 workspace_kind, workspace_path, tenant, progress_total)
            )

            # Add parent links
            if parent_ids:
                for parent_id in parent_ids:
                    conn.execute(
                        "INSERT INTO task_links (parent_id, child_id) VALUES (?, ?)",
                        (parent_id, task_id)
                    )

            # Log event
            conn.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'create', ?, ?)",
                (task_id, json.dumps({"title": title, "assignee": assignee}), now)
            )

            conn.commit()

            print(f"[KANBAN] Task created: {task_id} - {title}")

            return self.get_task(task_id)

        finally:
            conn.close()

    def get_task(self, task_id: str) -> Dict[str, Any]:
        """Get task by ID"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()

            if not row:
                return {}

            task = dict(row)
            task["parents"] = self._get_parents(conn, task_id)
            task["children"] = self._get_children(conn, task_id)
            task["comments"] = self._get_comments(conn, task_id)
            return task

        finally:
            conn.close()

    def _get_parents(self, conn: sqlite3.Connection, task_id: str) -> List[str]:
        """Get parent task IDs"""
        rows = conn.execute(
            "SELECT parent_id FROM task_links WHERE child_id = ?", (task_id,)
        ).fetchall()
        return [r["parent_id"] for r in rows]

    def _get_children(self, conn: sqlite3.Connection, task_id: str) -> List[str]:
        """Get child task IDs"""
        rows = conn.execute(
            "SELECT child_id FROM task_links WHERE parent_id = ?", (task_id,)
        ).fetchall()
        return [r["child_id"] for r in rows]

    def _get_comments(self, conn: sqlite3.Connection, task_id: str) -> List[Dict]:
        """Get comments for task"""
        rows = conn.execute(
            "SELECT * FROM task_comments WHERE task_id = ? ORDER BY created_at", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def list_tasks(
        self,
        status: Optional[str] = None,
        assignee: Optional[str] = None,
        tenant: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """List tasks with filters"""
        conn = self._get_conn()
        try:
            query = "SELECT * FROM tasks WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)

            if assignee:
                query += " AND assignee = ?"
                params.append(assignee)

            if tenant:
                query += " AND tenant = ?"
                params.append(tenant)

            query += " ORDER BY priority DESC, created_at DESC"

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

        finally:
            conn.close()

    # === Status Transitions ===

    def update_status(self, task_id: str, new_status: str, summary: Optional[str] = None) -> bool:
        """
        Update task status

        Args:
            task_id: Task ID
            new_status: New status (todo, ready, running, blocked, done, archived)
            summary: Optional summary (for done status)

        Returns:
            bool: Success
        """
        now = self._now_ts()
        conn = self._get_conn()
        try:
            # Update status
            update_fields = ["status = ?", "started_at = ?" if new_status == "running" else ""]
            params = [new_status]

            if new_status == "running":
                params.append(now)

            if new_status == "done":
                conn.execute(
                    "UPDATE tasks SET status = ?, completed_at = ?, summary = ? WHERE id = ?",
                    (new_status, now, summary, task_id)
                )
            elif new_status == "running":
                conn.execute(
                    "UPDATE tasks SET status = ?, started_at = ?, claim_lock = ? WHERE id = ?",
                    (new_status, now, f"{os.uname().nodename}:{os.getpid()}", task_id)
                )
            else:
                conn.execute(
                    "UPDATE tasks SET status = ? WHERE id = ?",
                    (new_status, task_id)
                )

            # Log event
            conn.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'status_change', ?, ?)",
                (task_id, json.dumps({"new_status": new_status, "summary": summary}), now)
            )

            conn.commit()

            # Recompute ready status for children
            if new_status == "done":
                self._recompute_children_ready(conn, task_id)

            print(f"[KANBAN] Task {task_id} status: {new_status}")
            return True

        finally:
            conn.close()

    def _recompute_children_ready(self, conn: sqlite3.Connection, parent_id: str) -> None:
        """Recompute ready status for children when parent completes"""
        children = self._get_children(conn, parent_id)

        for child_id in children:
            # Check if all parents are done
            all_parents_done = conn.execute(
                """SELECT COUNT(*) as cnt FROM task_links l
                   JOIN tasks t ON l.parent_id = t.id
                   WHERE l.child_id = ? AND t.status != 'done'""",
                (child_id,)
            ).fetchone()["cnt"] == 0

            if all_parents_done:
                conn.execute(
                    "UPDATE tasks SET status = 'ready' WHERE id = ? AND status = 'todo'",
                    (child_id,)
                )

        conn.commit()

    def update_progress(self, task_id: str, passed: int, total: int) -> bool:
        """Update task progress (for batch tracking)"""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE tasks SET progress_passed = ?, progress_total = ? WHERE id = ?",
                (passed, total, task_id)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    # === Atomic Claim (CAS) ===

    def claim_task(self, task_id: str) -> Tuple[bool, Optional[str]]:
        """
        Atomic claim task via compare-and-swap

        Args:
            task_id: Task ID

        Returns:
            Tuple[bool, Optional[str]]: (success, workspace_path)
        """
        now = self._now_ts()
        claim_lock = f"{os.uname().nodename}:{os.getpid()}"
        claim_expires = now + 900  # 15 min expiry

        conn = self._get_conn()
        try:
            # CAS: only claim if status='ready' AND claim_lock IS NULL
            conn.execute("BEGIN IMMEDIATE")

            result = conn.execute(
                """UPDATE tasks
                   SET status = 'running',
                       claim_lock = ?,
                       claim_expires = ?,
                       started_at = ?
                   WHERE id = ?
                   AND status = 'ready'
                   AND claim_lock IS NULL""",
                (claim_lock, claim_expires, now, task_id)
            )

            if result.rowcount == 0:
                conn.rollback()
                return (False, None)

            # Resolve workspace
            task = conn.execute(
                "SELECT workspace_kind, workspace_path FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()

            workspace = self._resolve_workspace(task["workspace_kind"], task["workspace_path"], task_id)

            # Update workspace path
            conn.execute(
                "UPDATE tasks SET workspace_path = ? WHERE id = ?",
                (str(workspace), task_id)
            )

            # Log event
            conn.execute(
                "INSERT INTO task_events (task_id, kind, payload, created_at) VALUES (?, 'claim', ?, ?)",
                (task_id, json.dumps({"claim_lock": claim_lock, "workspace": str(workspace)}), now)
            )

            conn.commit()
            print(f"[KANBAN] Task {task_id} claimed by {claim_lock}")
            return (True, str(workspace))

        finally:
            conn.close()

    def _resolve_workspace(self, kind: str, path: Optional[str], task_id: str) -> Path:
        """Resolve workspace based on kind"""
        if kind == "scratch":
            workspace = self.paths["run_dir"] / "workspaces" / task_id
            workspace.mkdir(parents=True, exist_ok=True)
            return workspace

        elif kind.startswith("dir:"):
            return Path(kind[4:])

        elif kind == "worktree":
            # Create git worktree
            worktree_path = self.paths["workspace"] / ".worktrees" / task_id
            worktree_path.mkdir(parents=True, exist_ok=True)
            return worktree_path

        return Path(path or str(self.paths["run_dir"] / "workspaces" / task_id))

    def release_claim(self, task_id: str) -> bool:
        """Release claim lock (for blocked state)"""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE tasks SET claim_lock = NULL, claim_expires = NULL WHERE id = ?",
                (task_id,)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    # === Stale Claim Recovery ===

    def recover_stale_claims(self) -> int:
        """
        Recover stale claims (dispatcher responsibility)

        Returns:
            int: Number of recovered tasks
        """
        now = self._now_ts()
        conn = self._get_conn()
        try:
            result = conn.execute(
                """UPDATE tasks
                   SET status = 'ready',
                       claim_lock = NULL,
                       claim_expires = NULL
                   WHERE status = 'running'
                   AND claim_expires < ?""",
                (now,)
            )
            conn.commit()
            recovered = result.rowcount

            if recovered > 0:
                print(f"[KANBAN] Recovered {recovered} stale claims")

            return recovered

        finally:
            conn.close()

    # === Comments ===

    def add_comment(self, task_id: str, author: str, body: str) -> int:
        """Add comment to task"""
        now = self._now_ts()
        conn = self._get_conn()
        try:
            result = conn.execute(
                "INSERT INTO task_comments (task_id, author, body, created_at) VALUES (?, ?, ?, ?)",
                (task_id, author, body, now)
            )
            conn.commit()
            return result.lastrowid

        finally:
            conn.close()

    # === Board View ===

    def get_board_summary(self) -> Dict[str, Any]:
        """Get board summary grouped by status"""
        conn = self._get_conn()
        try:
            # Count by status
            status_counts = {}
            for row in conn.execute("SELECT status, COUNT(*) as cnt FROM tasks GROUP BY status"):
                status_counts[row["status"]] = row["cnt"]

            # Get running tasks
            running = [dict(r) for r in conn.execute(
                "SELECT id, title, assignee, progress_passed, progress_total FROM tasks WHERE status = 'running'"
            )]

            # Get recent done
            recent_done = [dict(r) for r in conn.execute(
                """SELECT id, title, summary, completed_at FROM tasks
                   WHERE status = 'done' ORDER BY completed_at DESC LIMIT 10"""
            )]

            return {
                "status_counts": status_counts,
                "running_tasks": running,
                "recent_done": recent_done,
                "total_tasks": sum(status_counts.values())
            }

        finally:
            conn.close()

    def get_lane_view(self, lane_name: str) -> List[Dict[str, Any]]:
        """Get tasks in a lane (board view)"""
        status_map = {
            "Backlog": "todo",
            "Ready": "ready",
            "Running": "running",
            "Blocked": "blocked",
            "Done": "done",
            "Passed": "done",
            "Failed": "done"
        }

        status = status_map.get(lane_name, lane_name.lower())
        return self.list_tasks(status=status)

    # === Workflow Integration ===

    def sync_from_workflow_state(self) -> Dict[str, Any]:
        """Sync kanban from workflow_state.json"""
        state = load_workflow_state(self.workflow_state_path)

        if not state:
            return {}

        stats = state.get("stats", {})
        iteration = state.get("iteration", 0)
        batch_id = state.get("current_batch", {}).get("batch_id")

        # Update workflow task if exists
        workflow_task = self.list_tasks(assignee="workflow", tenant="main")
        if workflow_task:
            self.update_progress(workflow_task[0]["id"], stats.get("passed", 0), stats.get("total_tests", 0))

        return self.get_board_summary()

    # === UT Workflow Specific ===

    def create_batch_lane(self, batch_id: str, batch_size: int) -> str:
        """Create a lane (task) for a batch"""
        task_id = self.create_task(
            title=f"Batch {batch_id}",
            body=f"{batch_size} tests",
            assignee="batch-executor",
            created_by="supervisor",
            workspace_kind="scratch",
            progress_total=batch_size
        )["id"]

        # Transition to ready immediately (no parents)
        self.update_status(task_id, "ready")

        return task_id

    def move_batch_lane(self, batch_id: str, target_status: str, summary: str) -> bool:
        """Move batch lane to target status"""
        # Find task by title
        tasks = self.list_tasks(assignee="batch-executor")

        batch_task = next(
            (t for t in tasks if f"Batch {batch_id}" in t["title"]),
            None
        )

        if not batch_task:
            return False

        return self.update_status(batch_task["id"], "done", summary)


def main():
    """CLI for Hermes Kanban Manager"""
    import argparse

    parser = argparse.ArgumentParser(description="Hermes Kanban Manager CLI")
    parser.add_argument("--db-path", type=str, default=None, help="kanban.db path")
    parser.add_argument("--workflow-state", type=str, default=None, help="workflow_state.json path")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    subparsers.add_parser("init", help="Initialize database")

    # create
    create_parser = subparsers.add_parser("create", help="Create task")
    create_parser.add_argument("--title", required=True, help="Task title")
    create_parser.add_argument("--assignee", default=None, help="Assignee profile")
    create_parser.add_argument("--parent", nargs="*", default=[], help="Parent task IDs")

    # list
    list_parser = subparsers.add_parser("list", help="List tasks")
    list_parser.add_argument("--status", default=None, help="Filter by status")

    # claim
    claim_parser = subparsers.add_parser("claim", help="Claim task")
    claim_parser.add_argument("--task-id", required=True, help="Task ID")

    # complete
    complete_parser = subparsers.add_parser("complete", help="Complete task")
    complete_parser.add_argument("--task-id", required=True, help="Task ID")
    complete_parser.add_argument("--summary", default=None, help="Summary")

    # board
    subparsers.add_parser("board", help="Show board summary")

    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else None
    workflow_state = Path(args.workflow_state) if args.workflow_state else None
    manager = HermesKanbanManager(workflow_state, db_path)

    if args.command == "init":
        print("[OK] Database initialized")

    elif args.command == "create":
        task = manager.create_task(args.title, assignee=args.assignee, parent_ids=args.parent)
        print(json.dumps(task, indent=2))

    elif args.command == "list":
        tasks = manager.list_tasks(status=args.status)
        print(json.dumps(tasks, indent=2))

    elif args.command == "claim":
        success, workspace = manager.claim_task(args.task_id)
        print(f"Claimed: {success}, Workspace: {workspace}")

    elif args.command == "complete":
        manager.update_status(args.task_id, "done", args.summary)
        print(f"[OK] Task {args.task_id} completed")

    elif args.command == "board":
        summary = manager.get_board_summary()
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
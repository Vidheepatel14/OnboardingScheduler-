from src.database.connection import get_conn
from src.database.training_repository import get_all_modules


def assign_initial_tasks(user_email: str) -> None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM user_tasks WHERE user_email = ?", (user_email,))
        if cur.fetchone()[0] != 0:
            return

        for module_id, _, _, _ in get_all_modules():
            cur.execute(
                "INSERT INTO user_tasks (user_email, module_id, status) VALUES (?, ?, 'pending')",
                (user_email, module_id),
            )


def get_pending_tasks(user_email: str) -> list[dict]:
    tasks = get_tasks_for_user(user_email, status="pending")
    return [
        {"task_id": task["task_id"], "title": task["title"], "duration": task["duration"]}
        for task in tasks
    ]


def get_tasks_for_user(user_email: str, status: str | None = None) -> list[dict]:
    query = """
        SELECT t.task_id, m.title, m.duration_hours, t.status, t.scheduled_start, t.scheduled_end
        FROM user_tasks t
        JOIN training_modules m ON t.module_id = m.module_id
        WHERE t.user_email = ?
    """
    params: list[str] = [user_email]
    if status is not None:
        query += " AND t.status = ?"
        params.append(status)
    query += " ORDER BY t.task_id"

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        rows = cur.fetchall()

    return [
        {
            "task_id": int(row[0]),
            "title": row[1],
            "duration": row[2],
            "status": row[3],
            "scheduled_start": row[4],
            "scheduled_end": row[5],
        }
        for row in rows
    ]


def get_task_status_counts(user_email: str) -> dict[str, int]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT status, COUNT(*)
            FROM user_tasks
            WHERE user_email = ?
            GROUP BY status
            """,
            (user_email,),
        )
        rows = cur.fetchall()

    counts = {"pending": 0, "scheduled": 0, "completed": 0}
    for status, count in rows:
        counts[str(status)] = int(count)
    counts["total"] = sum(counts.values())
    return counts


def get_tasks_by_ids(task_ids: list[int]) -> list[dict]:
    if not task_ids:
        return []

    placeholders = ",".join("?" for _ in task_ids)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT t.task_id, m.title, m.duration_hours
            FROM user_tasks t
            JOIN training_modules m ON t.module_id = m.module_id
            WHERE t.task_id IN ({placeholders})
            """,
            task_ids,
        )
        rows = cur.fetchall()

    details_by_id = {
        int(row[0]): {"task_id": int(row[0]), "title": row[1], "duration": row[2]}
        for row in rows
    }
    return [details_by_id[task_id] for task_id in task_ids if task_id in details_by_id]


def mark_task_complete(task_id: int) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE user_tasks SET status='completed' WHERE task_id = ?", (task_id,))


def update_task_schedule(task_id: int, start_time: str, end_time: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE user_tasks
            SET status='scheduled', scheduled_start = ?, scheduled_end = ?
            WHERE task_id = ?
            """,
            (start_time, end_time, task_id),
        )

from collections.abc import Callable
from datetime import datetime, timedelta
import ast
import re
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from config.settings import LOCAL_TIMEZONE
from src.core.RAG import answer_policy_with_rag
from src.core.document_qa import answer_question_about_file
from src.core.schemas import (
    BookTaskSchema,
    DocumentQuestionSchema,
    DraftHrEmailSchema,
    ProgressSchema,
    ToolResult,
)
from src.database.task_repository import (
    get_pending_tasks,
    get_tasks_by_ids,
    mark_task_complete,
    update_task_schedule,
)
from src.utils.resilience import robust_call, safe_execute

ToolHandler = Callable[[dict], ToolResult]
DOCUMENT_TOOL_ERROR_PREFIXES = (
    "File not found:",
    "Unsupported file type.",
    "PDF dependency missing.",
    "PDF not found:",
    "Error while reading PDF:",
    "Vision generation failed:",
    "Document QA generation failed:",
)
GOOGLE_INTEGRATION_ERROR = (
    "Google integrations are unavailable. Install the Google auth/API packages from "
    "OnboardingScheduler/requirements.txt and make sure Streamlit is running in that same environment."
)
MULTI_TASK_ERROR = (
    "book_task requires at least one numeric task ID. Provide a single number or a list like [16, 17, 18]."
)
SLOT_SELECTION_ERROR = (
    "I could not infer a valid booking window from your request. Ask me to check your availability first, "
    "or provide a time window such as tomorrow 9 AM to 12 PM."
)
LOCAL_TZ = ZoneInfo(LOCAL_TIMEZONE)
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
}


def handle_get_my_tasks(params: dict) -> ToolResult:
    tasks = safe_execute(get_pending_tasks, params.get("email", "unknown"))
    return ToolResult(success=True, data=str(tasks))


def handle_check_calendar(_: dict) -> ToolResult:
    try:
        from src.services.google_cal import find_free_slots
    except ImportError:
        return ToolResult(success=False, error=GOOGLE_INTEGRATION_ERROR)

    slots = safe_execute(robust_call()(find_free_slots))
    return ToolResult(success=True, data=str(slots))


def handle_analyze_document(params: dict) -> ToolResult:
    try:
        valid_data = DocumentQuestionSchema(**params)
    except ValidationError as exc:
        return ToolResult(success=False, error=f"Invalid Parameters: {exc}")

    try:
        answer = answer_question_about_file(valid_data.file_path, valid_data.question)
    except Exception as exc:
        return ToolResult(success=False, error=str(exc))

    if answer.startswith(DOCUMENT_TOOL_ERROR_PREFIXES):
        return ToolResult(success=False, error=answer)

    return ToolResult(success=True, data=answer)


def handle_book_task(params: dict) -> ToolResult:
    try:
        from src.services.google_mail import send_invite
        from src.services.google_cal import find_free_slots
    except ImportError:
        return ToolResult(success=False, error=GOOGLE_INTEGRATION_ERROR)

    try:
        valid_data = BookTaskSchema(**params)
    except ValidationError as exc:
        return ToolResult(success=False, error=f"Invalid Parameters: {exc}")

    task_ids = extract_task_ids(valid_data.task_id)
    if not task_ids:
        return ToolResult(success=False, error=MULTI_TASK_ERROR)

    task_details = get_tasks_by_ids(task_ids)
    if len(task_details) != len(task_ids):
        found_ids = {task["task_id"] for task in task_details}
        missing_ids = [task_id for task_id in task_ids if task_id not in found_ids]
        return ToolResult(success=False, error=f"Task IDs not found: {missing_ids}")

    total_duration_hours = sum(max(float(task.get("duration") or 1.0), 0.5) for task in task_details)
    start_dt, end_dt, window_error = resolve_booking_window(
        valid_data.start_time,
        valid_data.end_time,
        valid_data.request_text or "",
        total_duration_hours,
        find_free_slots,
    )
    if window_error:
        return ToolResult(success=False, error=window_error)

    if end_dt <= start_dt:
        return ToolResult(success=False, error="end_time must be after start_time")

    scheduled_windows = []
    current_start = start_dt
    for task in task_details:
        duration_hours = float(task.get("duration") or 1.0)
        duration = timedelta(hours=max(duration_hours, 0.5))
        current_end = current_start + duration
        if current_end > end_dt:
            return ToolResult(
                success=False,
                error="The selected time window is too small to schedule all requested tasks sequentially.",
            )

        invite_status = safe_execute(
            send_invite,
            valid_data.email,
            task["title"],
            current_start.isoformat(),
            current_end.isoformat(),
        )
        if isinstance(invite_status, str) and invite_status.startswith("SYSTEM_ERROR:"):
            return ToolResult(
                success=False,
                error=f"Failed to create calendar event for task {task['task_id']}: {invite_status}",
            )
        safe_execute(update_task_schedule, task["task_id"], current_start.isoformat(), current_end.isoformat())
        scheduled_windows.append(
            f"{task['task_id']} ({task['title']}): {current_start.isoformat()} to {current_end.isoformat()} [{invite_status}]"
        )
        current_start = current_end

    return ToolResult(success=True, data="Booked tasks:\n" + "\n".join(scheduled_windows))


def handle_search_policy(params: dict) -> ToolResult:
    search_query = params.get("query", "").strip()
    if not search_query:
        return ToolResult(success=False, error="Missing query")

    try:
        return ToolResult(success=True, data=answer_policy_with_rag(search_query))
    except Exception as exc:
        return ToolResult(success=False, error=str(exc))


def handle_draft_hr_email(params: dict) -> ToolResult:
    try:
        from src.services.google_mail import draft_hr_email
    except ImportError:
        return ToolResult(success=False, error=GOOGLE_INTEGRATION_ERROR)

    try:
        valid_data = DraftHrEmailSchema(**params)
    except ValidationError as exc:
        return ToolResult(success=False, error=f"Invalid Parameters: {exc}")

    user_email = params.get("email", "unknown_user")
    status = safe_execute(draft_hr_email, user_email, valid_data.email_body)
    return ToolResult(success=True, data=status)


def handle_mark_complete(params: dict) -> ToolResult:
    try:
        valid_data = ProgressSchema(**params)
    except ValidationError as exc:
        return ToolResult(success=False, error=str(exc))

    safe_execute(mark_task_complete, valid_data.task_id)
    return ToolResult(success=True, data=f"Task {valid_data.task_id} completed.")


def extract_task_ids(task_value) -> list[int]:
    if isinstance(task_value, int):
        return [task_value]
    if isinstance(task_value, list):
        return [int(value) for value in task_value]
    if not isinstance(task_value, str):
        return []

    stripped = task_value.strip()
    if not stripped:
        return []

    try:
        parsed = ast.literal_eval(stripped)
    except (ValueError, SyntaxError):
        parsed = None

    if isinstance(parsed, int):
        return [parsed]
    if isinstance(parsed, list):
        ids = []
        for value in parsed:
            if isinstance(value, int):
                ids.append(value)
            elif isinstance(value, str) and value.isdigit():
                ids.append(int(value))
        return ids

    found = re.findall(r"\d+", stripped)
    return [int(value) for value in found]


def resolve_booking_window(
    start_time: str | None,
    end_time: str | None,
    request_text: str,
    total_duration_hours: float,
    find_free_slots,
) -> tuple[datetime | None, datetime | None, str | None]:
    start_dt, start_error = parse_datetime_value(start_time)
    end_dt, end_error = parse_datetime_value(end_time)
    if start_error:
        return None, None, start_error
    if end_error:
        return None, None, end_error
    if start_dt and end_dt:
        return start_dt, end_dt, None
    if start_dt or end_dt:
        return None, None, "Both start_time and end_time are required when providing explicit datetimes."

    slots = safe_execute(robust_call()(find_free_slots))
    if isinstance(slots, str):
        return None, None, f"Could not read calendar availability: {slots}"
    if not isinstance(slots, list) or not slots:
        return None, None, SLOT_SELECTION_ERROR

    selected_slot = select_free_slot(slots, request_text, total_duration_hours)
    if selected_slot is None:
        return None, None, SLOT_SELECTION_ERROR
    return selected_slot[0], selected_slot[1], None


def parse_datetime_value(value: str | None) -> tuple[datetime | None, str | None]:
    if not value or not value.strip():
        return None, None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        return None, f"Invalid datetime: {exc}"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    else:
        parsed = parsed.astimezone(LOCAL_TZ)
    return parsed, None


def parse_free_slot(slot: str) -> tuple[datetime, datetime] | None:
    match = re.match(r"^\s*(.+?)\s+to\s+(.+?)\s*$", slot)
    if not match:
        return None
    start_raw, end_raw = match.groups()
    start_dt, start_error = parse_datetime_value(start_raw)
    end_dt, end_error = parse_datetime_value(end_raw)
    if start_error or end_error or start_dt is None or end_dt is None:
        return None
    return start_dt, end_dt


def select_free_slot(
    slots: list[str],
    request_text: str,
    total_duration_hours: float,
) -> tuple[datetime, datetime] | None:
    lower_request = request_text.lower()
    now = datetime.now(LOCAL_TZ)
    earliest_date = now.date()
    latest_date = None

    if "tomorrow" in lower_request:
        target = (now + timedelta(days=1)).date()
        earliest_date = target
        latest_date = target
    else:
        match = re.search(r"next\s+(\d+)\s+days?", lower_request)
        if not match:
            match = re.search(
                r"next\s+(one|two|three|four|five|six|seven)\s+days?",
                lower_request,
            )
        if match:
            raw_value = match.group(1)
            days = int(raw_value) if raw_value.isdigit() else NUMBER_WORDS[raw_value]
            earliest_date = now.date()
            latest_date = (now + timedelta(days=days)).date()
        elif "this week" in lower_request:
            earliest_date = now.date()
            latest_date = (now + timedelta(days=max(0, 6 - now.weekday()))).date()

    minimum_duration = timedelta(hours=total_duration_hours)
    for slot in slots:
        parsed_slot = parse_free_slot(slot)
        if parsed_slot is None:
            continue
        slot_start, slot_end = parsed_slot
        slot_date = slot_start.astimezone(LOCAL_TZ).date()
        if slot_date < earliest_date:
            continue
        if latest_date is not None and slot_date > latest_date:
            continue
        if slot_end - slot_start < minimum_duration:
            continue
        return slot_start, slot_end
    return None


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "get_my_tasks": handle_get_my_tasks,
    "check_calendar": handle_check_calendar,
    "analyze_document": handle_analyze_document,
    "book_task": handle_book_task,
    "search_policy": handle_search_policy,
    "draft_hr_email": handle_draft_hr_email,
    "mark_complete": handle_mark_complete,
}

from dataclasses import dataclass

EMAIL_REQUIRED_TOOLS = frozenset({"book_task", "draft_hr_email"})


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: str


TOOL_DEFINITIONS = (
    ToolDefinition("get_my_tasks", "Returns pending tasks.", "None"),
    ToolDefinition("check_calendar", "Returns free slots.", "None"),
    ToolDefinition(
        "analyze_document",
        "Answers questions about a local PDF or image file.",
        '"file_path", "question"',
    ),
    ToolDefinition(
        "book_task",
        "Schedules one or more tasks.",
        '"task_id", "email", "start_time", "end_time"',
    ),
    ToolDefinition("search_policy", "RAG search.", '"query"'),
    ToolDefinition("mark_complete", "Finish a task.", '"task_id"'),
    ToolDefinition(
        "draft_hr_email",
        "Escalates an unanswered policy question to HR by sending an AI-drafted email.",
        '"email_body"',
    ),
)


def render_tool_list() -> str:
    return "\n".join(
        f"- {tool.name}: {tool.description} Params: {tool.parameters}."
        for tool in TOOL_DEFINITIONS
    )

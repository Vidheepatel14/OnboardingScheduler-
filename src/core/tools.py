from src.core.schemas import ToolResult
from src.core.tool_handlers import TOOL_HANDLERS


def execute_tool_call(tool_name: str, params: dict) -> ToolResult:
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return ToolResult(success=False, error="Unknown Tool")
    return handler(params)

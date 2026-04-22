from pydantic import BaseModel, Field
from typing import Optional

# --- Tool Input Schemas ---

class BookTaskSchema(BaseModel):
    task_id: int | list[int] | str = Field(
        ...,
        description="A single numeric task ID or a list of numeric task IDs to book.",
    )
    email: str = Field(..., description="User's email address.")
    start_time: Optional[str] = Field(
        default="",
        description="ISO 8601 start time (YYYY-MM-DDTHH:MM:SS). Can be blank if the app should infer from availability.",
    )
    end_time: Optional[str] = Field(
        default="",
        description="ISO 8601 end time (YYYY-MM-DDTHH:MM:SS). Can be blank if the app should infer from availability.",
    )
    request_text: Optional[str] = Field(
        default="",
        description="Original scheduling request, used to infer a time window such as tomorrow or next three days.",
    )

class RagSchema(BaseModel):
    query: str = Field(..., description="The search query for the training docs.")

class DocumentQuestionSchema(BaseModel):
    file_path: str = Field(..., description="Local path to a PDF or image file.")
    question: str = Field(..., description="Question to answer about the provided file.")

class ProgressSchema(BaseModel):
    task_id: int = Field(..., description="The numeric ID of the completed task.")

class DraftHrEmailSchema(BaseModel):
    email_body: str = Field(
        ...,
        description="The fully drafted, professional email message to send to HR. It should clearly summarize the employee's situation, their exact question, and note that the AI could not find the answer in the handbook."
    )

# --- Tool Output Schema (Standardized) ---
class ToolResult(BaseModel):
    success: bool
    data: Optional[str] = None
    error: Optional[str] = None

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from huggingface_hub import InferenceClient

from config.settings import HF_TOKEN, LLM_MODEL, POLICY_NOT_FOUND_RESPONSE
from src.core.prompt import build_system_prompt
from src.core.tool_catalog import EMAIL_REQUIRED_TOOLS
from src.core.tools import execute_tool_call

_HF_CLIENT: InferenceClient | None = None


def _hf_client() -> InferenceClient:
    global _HF_CLIENT
    if _HF_CLIENT is None:
        _HF_CLIENT = InferenceClient(token=HF_TOKEN)
    return _HF_CLIENT


def _response_text(response) -> str:
    try:
        return response.choices[0].message.content or ""
    except AttributeError:
        return response["choices"][0]["message"].get("content", "")


def _chat_text(messages: list[dict[str, Any]], json_mode: bool = False) -> str:
    kwargs: dict[str, Any] = {
        "model": LLM_MODEL,
        "messages": messages,
        "max_tokens": 700,
        "temperature": 0.1,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = _hf_client().chat_completion(**kwargs)
    except TypeError:
        kwargs.pop("response_format", None)
        response = _hf_client().chat_completion(**kwargs)
    except Exception:
        if not json_mode or "response_format" not in kwargs:
            raise
        kwargs.pop("response_format", None)
        response = _hf_client().chat_completion(**kwargs)

    return _response_text(response).strip()


@dataclass
class AgentSession:
    max_loops: int = 5
    history: list[dict[str, str]] = field(default_factory=list)
    owner_email: str | None = None

    def _ensure_system_prompt(self, user_email: str) -> None:
        if self.owner_email == user_email and self.history:
            return

        self.history.clear()
        self.owner_email = user_email
        today = datetime.now().strftime("%Y-%m-%d")
        self.history.append(
            {"role": "system", "content": build_system_prompt(user_email=user_email, today=today)}
        )

    def _request_decision(self) -> dict | None:
        content_raw = ""
        try:
            content_raw = _chat_text(self.history, json_mode=True)
            decision = self._parse_decision(content_raw)
        except json.JSONDecodeError:
            return None
        except Exception:
            raise

        self.history.append({"role": "assistant", "content": content_raw})
        return decision

    def _parse_decision(self, content_raw: str) -> dict:
        cleaned = content_raw.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            decision = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if not match:
                return {"action": "chat", "response": cleaned}
            decision = json.loads(match.group(0))

        if not isinstance(decision, dict):
            return {"action": "chat", "response": str(decision)}

        action = str(decision.get("action", "")).strip().lower()
        tool_name = decision.get("tool_name")

        if action in {"chat", "respond", "response", "final", "answer"}:
            response_text = (
                decision.get("response")
                or decision.get("answer")
                or decision.get("message")
                or decision.get("content")
                or "Task completed."
            )
            return {"action": "chat", "response": str(response_text)}

        if action in {"tool_use", "tool", "tool_call", "use_tool"} or tool_name:
            return {
                "action": "tool_use",
                "tool_name": tool_name,
                "parameters": decision.get("parameters", {}),
            }

        if any(key in decision for key in ("response", "answer", "message", "content")):
            response_text = (
                decision.get("response")
                or decision.get("answer")
                or decision.get("message")
                or decision.get("content")
            )
            return {"action": "chat", "response": str(response_text)}

        return decision

    def _inject_email(self, tool_name: str | None, params: dict, user_email: str) -> dict:
        if tool_name in EMAIL_REQUIRED_TOOLS and "email" not in params:
            params["email"] = user_email
        return params

    def _inject_request_context(self, tool_name: str | None, params: dict, user_input: str) -> dict:
        if tool_name == "book_task" and "request_text" not in params:
            params["request_text"] = user_input
        return params

    def _record_tool_output(self, result) -> None:
        self.history.append({"role": "user", "content": f"Tool Output: {str(result)}"})

    def _looks_like_policy_question(self, user_input: str) -> bool:
        lowered = user_input.lower()
        policy_keywords = (
            "polic",
            "handbook",
            "pto",
            "paid time off",
            "vacation",
            "sick leave",
            "leave",
            "misconduct",
            "code of conduct",
            "harassment",
            "ethics",
            "benefit",
            "reporting channel",
            "guideline",
            "program",
            "procedure",
            "who do i",
            "who should i",
            "reach out",
            "contact",
        )
        return any(keyword in lowered for keyword in policy_keywords)

    def _build_tool_error_response(self, tool_name: str | None, result) -> str:
        error_text = getattr(result, "error", None) or "The requested action failed."
        if tool_name == "search_policy":
            return (
                "I could not search the company documentation right now. "
                f"{error_text}"
            )
        return error_text

    def _should_auto_escalate(self, tool_name: str | None, result) -> bool:
        if tool_name != "search_policy":
            return False
        if not getattr(result, "success", False):
            return False
        data = getattr(result, "data", None)
        return isinstance(data, str) and data.strip() == POLICY_NOT_FOUND_RESPONSE

    def _build_hr_email_body(self, user_email: str, user_question: str) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        return (
            "Hello HR Team,\n\n"
            "The AI Onboarding Concierge was unable to find an answer in the company documentation "
            "and is escalating the request for follow-up.\n\n"
            f"Employee: {user_email}\n"
            "Employee's question:\n"
            f"\"{user_question}\"\n\n"
            "Please review this question and provide the appropriate guidance to the employee.\n\n"
            "Best regards,\n"
            "AI Onboarding Concierge"
        )

    def _auto_escalate_to_hr(self, user_email: str, user_question: str):
        params = {
            "email": user_email,
            "email_body": self._build_hr_email_body(user_email, user_question),
        }
        print(f"   ⚙️  EXECUTING [AUTO]: draft_hr_email with {params}")
        return execute_tool_call("draft_hr_email", params)

    def _run_policy_search(self, user_input: str, user_email: str) -> str:
        params = {"query": user_input}
        print(f"   ⚙️  EXECUTING [DIRECT]: search_policy with {params}")
        result = execute_tool_call("search_policy", params)
        self._record_tool_output(result)

        if not getattr(result, "success", False):
            return self._build_tool_error_response("search_policy", result)

        if self._should_auto_escalate("search_policy", result):
            escalation_result = self._auto_escalate_to_hr(user_email, user_input)
            self._record_tool_output(escalation_result)
            if getattr(escalation_result, "success", False):
                return f"{POLICY_NOT_FOUND_RESPONSE} I escalated your question to HR."
            return (
                f"{POLICY_NOT_FOUND_RESPONSE} "
                "I could not escalate your question automatically. Please contact HR directly."
            )

        return str(getattr(result, "data", ""))

    def run(self, user_input: str, user_email: str) -> str:
        self._ensure_system_prompt(user_email)
        self.history.append({"role": "user", "content": user_input})

        for loop_count in range(1, self.max_loops + 1):
            try:
                decision = self._request_decision()
            except Exception:
                if self._looks_like_policy_question(user_input):
                    return self._run_policy_search(user_input, user_email)
                raise
            if decision is None:
                if self._looks_like_policy_question(user_input):
                    return self._run_policy_search(user_input, user_email)
                return "System Error: The agent failed to format its response correctly."

            action = decision.get("action")
            if action == "chat":
                return decision.get("response", "Task completed.")

            if action != "tool_use":
                if self._looks_like_policy_question(user_input):
                    return self._run_policy_search(user_input, user_email)
                return "System Error: The agent returned an unknown action."

            tool_name = decision.get("tool_name")
            params = dict(decision.get("parameters", {}))
            params = self._inject_email(tool_name, params, user_email)
            params = self._inject_request_context(tool_name, params, user_input)

            print(f"   ⚙️  EXECUTING [{loop_count}/{self.max_loops}]: {tool_name} with {params}")
            result = execute_tool_call(tool_name, params)
            self._record_tool_output(result)

            if not getattr(result, "success", False):
                return self._build_tool_error_response(tool_name, result)

            if self._should_auto_escalate(tool_name, result):
                escalation_result = self._auto_escalate_to_hr(user_email, user_input)
                self._record_tool_output(escalation_result)
                if getattr(escalation_result, "success", False):
                    return f"{POLICY_NOT_FOUND_RESPONSE} I escalated your question to HR."
                return (
                    f"{POLICY_NOT_FOUND_RESPONSE} "
                    "I could not escalate your question automatically. Please contact HR directly."
                )

            if tool_name == "search_policy":
                return str(getattr(result, "data", ""))

        return "I had to stop thinking because it was taking too many steps. Could you rephrase your request?"


DEFAULT_SESSION = AgentSession()
conversation_history = DEFAULT_SESSION.history


def chat_with_agent(user_input, user_email):
    return DEFAULT_SESSION.run(user_input, user_email)

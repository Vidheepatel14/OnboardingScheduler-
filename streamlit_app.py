from pathlib import Path
from uuid import uuid4

try:
    import streamlit as st
except ImportError as exc:
    raise SystemExit("Streamlit is not installed. Add it from OnboardingScheduler/requirements.txt.") from exc

from src.core.agent import AgentSession
from src.core.tool_handlers import handle_analyze_document
from src.database.connection import init_db
from src.database.task_repository import (
    assign_initial_tasks,
    get_pending_tasks,
    get_task_status_counts,
    get_tasks_for_user,
    mark_task_complete,
)

DEFAULT_EMAIL = "new.employee@company.com"
UPLOAD_DIR = Path(__file__).resolve().parent / "data" / "uploads"


def apply_styles() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: radial-gradient(circle at top left, #f7efe4 0%, #fdfbf8 40%, #eef4f2 100%);
        }
        .hero {
            padding: 1.4rem 1.6rem;
            border-radius: 18px;
            background: linear-gradient(135deg, rgba(26, 80, 92, 0.95), rgba(205, 120, 92, 0.92));
            color: white;
            box-shadow: 0 14px 40px rgba(47, 58, 66, 0.14);
            margin-bottom: 1rem;
        }
        .hero h1 {
            margin: 0 0 0.35rem 0;
            font-size: 2rem;
        }
        .hero p {
            margin: 0;
            font-size: 1rem;
            max-width: 48rem;
        }
        .capability {
            padding: 1rem 1rem 0.85rem 1rem;
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.82);
            border: 1px solid rgba(26, 80, 92, 0.08);
            min-height: 122px;
        }
        .capability h3 {
            margin: 0 0 0.4rem 0;
            font-size: 1rem;
            color: #1a505c;
        }
        .capability p {
            margin: 0;
            font-size: 0.92rem;
            color: #30424a;
        }
        /* Ensure Streamlit widgets are readable on the forced-light background */
        [data-testid="stMetricValue"],
        [data-testid="stMetricLabel"] {
            color: #30424a !important;
        }
        .stTabs button[role="tab"] {
            color: #30424a !important;
        }
        .stTabs button[role="tab"][aria-selected="true"] {
            color: #1a505c !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def ensure_app_ready(user_email: str) -> None:
    init_db()
    assign_initial_tasks(user_email)

    if st.session_state.get("active_email") != user_email:
        st.session_state.active_email = user_email
        st.session_state.agent_session = AgentSession()
        st.session_state.chat_messages = []

    st.session_state.setdefault("agent_session", AgentSession())
    st.session_state.setdefault("chat_messages", [])


def reset_chat() -> None:
    st.session_state.agent_session = AgentSession()
    st.session_state.chat_messages = []


def save_uploaded_file(uploaded_file) -> Path:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = uploaded_file.name.replace("/", "_")
    destination = UPLOAD_DIR / f"{uuid4().hex}_{safe_name}"
    destination.write_bytes(uploaded_file.getbuffer())
    return destination


def render_capabilities() -> None:
    columns = st.columns(3)
    items = [
        ("Policy Answers", "Ask handbook questions and get grounded answers with citations."),
        ("Task Guidance", "See onboarding tasks, mark them done, or schedule work in natural language."),
        ("Document Review", "Upload a PDF or image and ask direct questions about its contents."),
    ]
    for column, (title, description) in zip(columns, items):
        with column:
            st.markdown(
                f"<div class='capability'><h3>{title}</h3><p>{description}</p></div>",
                unsafe_allow_html=True,
            )


def render_chat_tab(user_email: str) -> None:
    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Ask about policies, tasks, scheduling, or a local file path")
    if not prompt:
        return

    st.session_state.chat_messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            response = st.session_state.agent_session.run(prompt, user_email)
        st.markdown(response)

    st.session_state.chat_messages.append({"role": "assistant", "content": response})


def render_tasks_tab(user_email: str) -> None:
    tasks = get_pending_tasks(user_email)
    task_counts = get_task_status_counts(user_email)
    all_tasks = get_tasks_for_user(user_email)
    pending_tasks = [task for task in all_tasks if task["status"] == "pending"]
    scheduled_tasks = [task for task in all_tasks if task["status"] == "scheduled"]
    completed_tasks = [task for task in all_tasks if task["status"] == "completed"]
    open_tasks = [task for task in all_tasks if task["status"] in {"pending", "scheduled"}]
    st.subheader("Pending onboarding tasks")

    metrics = st.columns(4)
    metrics[0].metric("Total", task_counts["total"])
    metrics[1].metric("Pending", task_counts["pending"])
    metrics[2].metric("Scheduled", task_counts["scheduled"])
    metrics[3].metric("Completed", task_counts["completed"])

    st.markdown("### Pending")
    if not pending_tasks:
        st.success("No pending tasks. You are caught up.")
    else:
        st.dataframe(
            [
                {"Task ID": task["task_id"], "Title": task["title"], "Duration (hrs)": task["duration"]}
                for task in pending_tasks
            ],
            width="stretch",
        )

    st.markdown("### Scheduled")
    if not scheduled_tasks:
        st.info("No tasks are currently scheduled.")
    else:
        st.dataframe(
            [
                {
                    "Task ID": task["task_id"],
                    "Title": task["title"],
                    "Scheduled Start": task["scheduled_start"],
                    "Scheduled End": task["scheduled_end"],
                }
                for task in scheduled_tasks
            ],
            width="stretch",
        )

    st.markdown("### Completed")
    if not completed_tasks:
        st.info("No tasks are completed yet.")
    else:
        st.dataframe(
            [{"Task ID": task["task_id"], "Title": task["title"]} for task in completed_tasks],
            width="stretch",
        )

    st.caption("Use the chat tab for scheduling requests, or mark a pending or scheduled task complete here.")
    completion_options = {
        "": None,
        **{
            f'{task["task_id"]} - {task["title"]} ({task["status"]})': task["task_id"]
            for task in open_tasks
        },
    }
    selected_task = st.selectbox("Mark task complete", options=list(completion_options.keys()), index=0)
    if st.button("Update selected task", width="stretch"):
        selected_task_id = completion_options[selected_task]
        if selected_task_id is None:
            st.warning("Choose a task first.")
        else:
            mark_task_complete(int(selected_task_id))
            st.success(f"Task {selected_task_id} marked complete.")
            st.rerun()


def render_document_tab() -> None:
    st.subheader("Analyze a document or equipment photo")
    st.caption(
        "Upload a PDF for document Q&A, or upload an equipment photo such as a headset, monitor, or dock "
        "and ask setup questions. The app will identify the device and search training docs for matching guidance when possible."
    )
    uploaded_file = st.file_uploader("Upload a PDF or equipment image", type=["pdf", "png", "jpg", "jpeg", "bmp", "webp"])
    question = st.text_input("Question about the file or equipment")

    if not st.button("Analyze document", width="stretch"):
        return

    if uploaded_file is None:
        st.warning("Upload a file first.")
        return
    if not question.strip():
        st.warning("Add a question first.")
        return

    saved_path = save_uploaded_file(uploaded_file)
    with st.spinner("Analyzing document..."):
        result = handle_analyze_document({"file_path": str(saved_path), "question": question})

    if result.success:
        st.success("Document analyzed successfully.")
        st.markdown(result.data)
        st.caption(f"Saved file path: `{saved_path}`")
    else:
        st.error(result.error)


def main() -> None:
    st.set_page_config(page_title="Onboarding Concierge", page_icon=":spiral_calendar_pad:", layout="wide")
    apply_styles()

    with st.sidebar:
        st.title("Control Panel")
        user_email = st.text_input("Employee email", value=st.session_state.get("active_email", DEFAULT_EMAIL))
        if st.button("Reset chat history", width="stretch"):
            reset_chat()
        st.divider()
        st.caption(
            "The assistant can answer handbook questions, show task progress, analyze uploaded files, "
            "and escalate missing answers to HR."
        )

    ensure_app_ready(user_email)
    pending_tasks = get_pending_tasks(user_email)

    st.markdown(
        """
        <div class="hero">
            <h1>AI Onboarding Concierge</h1>
            <p>Guide new employees through policies, task progress, scheduling, and document questions from one interface.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_capabilities()

    metrics = st.columns(2)
    metrics[0].metric("Pending tasks", len(pending_tasks))
    metrics[1].metric(
        "Training documents",
        len(list((Path(__file__).resolve().parent / "data" / "training_docs").glob("*.pdf"))),
    )

    chat_tab, tasks_tab, document_tab = st.tabs(["Assistant", "Tasks", "Document QA"])
    with chat_tab:
        render_chat_tab(user_email)
    with tasks_tab:
        render_tasks_tab(user_email)
    with document_tab:
        render_document_tab()


if __name__ == "__main__":
    main()

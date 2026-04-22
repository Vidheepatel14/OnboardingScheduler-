# OnboardingScheduler

## Overview
This app manages employee onboarding workflows and routes questions through a tool-using agent.

The live runtime is organized into clear layers:
- `src/core/` for agent orchestration, prompts, tool registry, policy RAG, and document QA
- `src/database/` for connection management and repository functions
- `src/services/` for Google Calendar and Gmail integrations
- `scripts/` for ingestion and setup helpers

The app can answer handbook questions with RAG and can also analyze local PDF or image files through the agent tool flow.
Legacy milestone code and retired app files now live under [archive/README.md](/Users/vidheepatel/Spring-2026-DSBA-6010-Group-20-TravelTokens/archive/README.md).

## Runtime Flow
1. `main.py` initializes the database and assigns starter tasks.
2. `src/core/agent.py` manages the chat session and tool loop.
3. `src/core/tools.py` routes tool calls through small handlers.
4. Repository and service modules perform the actual work.

## Project Structure
```text
OnboardingScheduler/
  config/
  data/
  scripts/
  src/
    core/
      agent.py
      document_parser.py
      document_qa.py
      prompt.py
      tool_catalog.py
      tool_handlers.py
      tools.py
    database/
      connection.py
      task_repository.py
      training_repository.py
    services/
    utils/
  tests/
```

## How to Run
From the `OnboardingScheduler/` directory:

```bash
python main.py
```

To manually test the RAG pipeline without the full agent:

```bash
python scripts/test_rag.py
```

To launch the Streamlit frontend:

```bash
streamlit run streamlit_app.py
```

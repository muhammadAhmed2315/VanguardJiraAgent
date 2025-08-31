# Vanguard Jira Agent

An AI-powered Proof of Concept application developed during my internship at Vanguard. It provides a conversational interface for interacting with Jira and Confluence pages using natural language, by making use of an Model Context Protocol (MCP) server.

The system consists of:

- A **Flask backend** (`backend/server.py`) that maintains a persistent MCP connection and exposes a streaming API.
- A **Streamlit frontend** (`frontend/app.py`) that provides a chat UI for interacting with the assistant.
- A **LangChain agent** (`backend/MCPClient.py`, `backend/MCPToolHandler.py`) that routes queries to the appropriate LLMs and MCP tools.

---

## Features

- Conversational Jira & Confluence assistant powered by LLMs.
- Handles ticket management (create, update, transition, comment, label).
- Confluence integration (create, update, search, fetch pages).
- Smart LLM routing:
  - **Fast**: small and fast LLM model for quick tasks
  - **Smart**: more powerful LLM context-sensitive updates
  - **Complex**: most complex LLM for handling complex, multi-step tasks
- Real-time tool call streaming with live feedback in the UI.

## Environment Setup

1. Create a .env file in the project root with:

```
OPENAI_API_KEY=your_openai_api_key
GOOGLE_API_KEY=your_google_api_key

LANGCHAIN_API_KEY=your_langsmith_api_key
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=project_name_here
```

- LangChain API keys are optional (enable monitoring via LangSmith)

## Running the Application

1. Start the backend server: `python server.py`

   - Runs on http://localhost:8000.
   - NOTE: On first start, a link will be provided in the console to provide OAuth authorisation for the MCP server to access your Jira and Confluence sites.

2. Start the Streamlit frontend: `streamlit run app.py`

   - Opens at http://localhost:8501.

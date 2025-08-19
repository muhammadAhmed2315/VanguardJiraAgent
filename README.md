#### High-Level Overview of the Flask Server:

- The Flask server has two threads:
  - **Main thread** - handles HTTP requests. Every incoming HTTP request (e.g., `/mcp`) is processed here. When MCP related tasks need to be done, that work is handed off to the background thread.
  - **Background thread** - runs its own asyncio event loop. This loop:
    - Keeps the MCP connection open
    - Hosts the LangChain agent
    - Has a job queue
    - Pulls jobs from the queue one at a time and executes them
    - Returns results back to the main thread via a `Future`

#### Notes:

Is it possible to dynamically switch models in LangChain?

- Make dynamically switching LLMs for more complex calls (e.g., if user wants to
  identify any dependencies just by reading all of the tickets)
- This is possible using the answer-or-escalate call here: https://chatgpt.com/c/689e0981-e3ac-8323-b0ab-469d47cedc06

Optimise the actual LLM calls even further
Switch to React?

creating jira releases
create/close sprints
summarise all epics in progress
summarise sprint stats
check dependencies + blocks for tickets, come up with an order for the tickets in an epic??
architecture diagram, draw.io
approach, hurdles, next steps, how to setup

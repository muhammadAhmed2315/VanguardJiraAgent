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

TODO:

- Architecture diagram (use draw.io)
- Document approach, hurdles, next steps, and how to setup the project
- The tech stack, and your reasoning for each choice

creating jira releases
create/close sprints
summarise all epics in progress
summarise sprint stats
check dependencies + blocks for tickets, come up with an order for the tickets in an epic??

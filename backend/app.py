# app.py
import json
import time
import asyncio
import threading
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import Flask, request, jsonify

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from AgentTools import MCPToolHandler

# -----------------------------

load_dotenv()

REMOTE_URL = "https://mcp.atlassian.com/v1/sse"


async def manual_mcp_call(
    session: ClientSession, tool: str, args: Dict[str, Any] = {}
) -> str:
    """
    Call an MCP tool via an existing ClientSession.

    Args:
        session: Active MCP client session.
        tool: MCP tool name to invoke.
        args: JSON-serializable arguments for the tool (defaults to empty dict).

    Returns:
        A JSON string with the tool result on success, or a JSON string of the form
        {"error": "..."} if the call fails.
    """
    try:
        return await session.call_tool(tool, args)
    except Exception as e:
        return json.dumps({"error": f"Error calling {tool}: {e}"})


class MCPAgentServer:
    """
    Runs a single, long-lived MCP connection + LangChain agent inside an asyncio loop,
    and exposes a thread-safe .submit() API for Flask handlers to call.
    """

    def __init__(self, remote_url: str):
        """
        Initialize the server that hosts a long-lived MCP connection and LangChain agent.

        Args:
            remote_url: Remote MCP URL used by the stdio proxy (mcp-remote).
        """
        self.remote_url = remote_url

        # Thread + event loop
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        # Job queue consumed inside the loop
        self._queue: Optional[asyncio.Queue] = None

        # For signaling readiness to Flask (so requests don’t arrive before init completes)
        self._ready_evt = threading.Event()

        # For graceful shutdown
        self._stop_evt = threading.Event()

    # ---------- public API (sync; called from Flask thread) ----------
    def start(self):
        """
        Start the background thread and event loop for the MCP agent.

        Notes:
            Blocks until the agent is ready (or 30s timeout) so that subsequent
            submit() calls can be served immediately.
        """
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop_forever, daemon=True)
        self._thread.start()
        # Wait until agent is ready (built at least once)
        self._ready_evt.wait(timeout=30)

    def stop(self):
        """
        Signal the background loop to stop and join the worker thread.

        Notes:
            Attempts a graceful shutdown by stopping the asyncio loop and
            waiting up to 5 seconds for the thread to join.
        """
        self._stop_evt.set()
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        if self._thread:
            self._thread.join(timeout=5)

    def submit(
        self, user_input: str, chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Synchronous call from Flask: enqueues a task and waits for the result.
        chat_history is a list of {"role": "human"/"ai", "content": "..."}
        """
        if not self._loop or not self._queue:
            return {"error": "MCP agent loop not started"}

        fut: asyncio.Future = asyncio.run_coroutine_threadsafe(
            self._submit_coro(user_input, chat_history or []), self._loop
        )
        return fut.result(timeout=120)  # adjust timeout as needed

    # ---------- loop/thread internals ----------
    def _run_loop_forever(self):
        """
        Create and run the dedicated asyncio event loop for the agent thread.

        Notes:
            Installs the loop as current, initializes the request queue, starts
            the runner task, and drives the loop until termination. On exit,
            cancels and drains any remaining tasks before closing the loop.
        """
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._queue = asyncio.Queue()

        # Kick off the main runner that ensures persistent connection & worker
        self._loop.create_task(self._runner())
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for t in pending:
                t.cancel()
            try:
                self._loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            finally:
                self._loop.close()

    async def _shutdown(self):
        """
        Stop the currently running asyncio loop from within the agent thread.

        Notes:
            Uses call_soon_threadsafe to request loop termination.
        """
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    async def _submit_coro(
        self, user_input: str, chat_history_kv: List[Dict[str, str]]
    ):
        """
        Enqueue a user request into the agent worker and await the result.

        Args:
            user_input: End-user instruction or query to process.
            chat_history_kv: Prior chat turns as dicts with keys {"role","content"}.

        Returns:
            The result dict produced by the agent execution (e.g., {"ok": True, ...}).

        Raises:
            asyncio.CancelledError: If the task is cancelled before completion.
        """
        # Convert history into LangChain message objects inside the loop
        history_msgs = []
        for m in chat_history_kv:
            if m.get("role") == "human":
                history_msgs.append(HumanMessage(content=m["content"]))
            elif m.get("role") == "ai":
                history_msgs.append(AIMessage(content=m["content"]))

        # Each job is (input, history_msgs, future_for_result)
        loop_fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._queue.put((user_input, history_msgs, loop_fut))
        return await loop_fut

    async def _runner(self):
        """
        Keeps a single MCP connection alive. If it drops, reconnects and rebuilds the agent.
        Also runs a worker that processes queued requests via the single agent executor.
        """
        backoff = 1
        while not self._stop_evt.is_set():
            try:
                # 1) Establish MCP connection
                server = StdioServerParameters(
                    command="npx",
                    args=["-y", "mcp-remote", self.remote_url],
                    env={},
                )
                async with stdio_client(server) as (read, write):
                    async with ClientSession(read, write) as session:
                        # 2) Prime tools + context (done once per successful connection)
                        tool_meta = await session.list_tools()
                        tool_meta.tools = [
                            t for t in tool_meta.tools if "Confluence" not in t.name
                        ]
                        tool_docs = tool_meta.model_dump_json()

                        # Make manual MCP calls to get relevant information from MCP
                        resources = await manual_mcp_call(
                            session, "getAccessibleAtlassianResources", {}
                        )
                        user_info = await manual_mcp_call(
                            session, "atlassianUserInfo", {}
                        )

                        # 3) Build LLM + tools + agent
                        llm = ChatOpenAI(model="gpt-4.1-2025-04-14", temperature=0)

                        system = """
                            # Identity

                            - You are a Jira assistant that can operate Jira using MCP tools.
                            - As general guidelines, you should aim to ensure accuracy, efficiency, and minimal user requirements Only ask for clarifications from the user as a last resort.

                            # Instructions

                            ## Handling ticket IDs
                            - Jira ticket IDs are always in the format <PROJECT_KEY>-<NUMBER>
                            - However, the user may input them with a missing hyphen (e.g., <PROJECT_KEY><NUMBER>)
                            - Since <PROJECT_KEY> may or may not end in a number, so you should always try inferring the ticket ID, but if you can't fnd the correct ticket, then ask the user for clarification.


                            ## Handling ticket comments
                            - When outputting comments for a specific ticket, output each comment in the following format:
                              - <author> (<timestamp converted to X days/hours/minutes/seconds ago>): <comment>
                            - Each comment should be separate dwith a new line
                            - Unless explicitly specified by the user, comments should always be ordered with the most recent first.

                            # Context
                            - Here are the MCP tools that are available to you and their JSON schemas:
                            <available_mcp_tools>
                            {tool_docs}
                            </available_mcp_tools>

                            - Here is the result of calling the MCP command `getAccessibleAtlassianResources`: 
                            <get_accessible_atlassian_resources_result>
                            {resources}
                            </get_accessible_atlassian_resources_result>

                            - Here is the result of calling the MCP command `atlassianUserInfo`:
                            <atlassian_user_info_results>
                            {user_info}
                            </atlassian_user_info_results>

                            - Do not attempt to discover tools again; call `mcp_call` directly
                            - When calling `mcp_call`, provide the tool name as the `tool` parameter and arguments as the `arguments` parameter.
                            """

                        prompt = ChatPromptTemplate.from_messages(
                            [
                                ("system", system),
                                MessagesPlaceholder("chat_history"),
                                ("human", "{input}"),
                                MessagesPlaceholder("agent_scratchpad"),
                            ]
                        ).partial(
                            tool_docs=tool_docs,
                            resources=resources,
                            user_info=user_info,
                        )

                        handler = MCPToolHandler(session)

                        agent_tools = handler.get_all_tools()

                        # agent_tools = [
                        # handler.get_call_tool_tool(),
                        # handler.get_list_tools_tool(),
                        # ]

                        agent = create_tool_calling_agent(llm, agent_tools, prompt)
                        executor = AgentExecutor(
                            agent=agent,
                            tools=agent_tools,
                            verbose=True,
                            handle_parsing_errors=True,
                        )

                        # Signal ready after the first successful build
                        self._ready_evt.set()
                        backoff = 1  # reset backoff after success

                        # 4) Consume jobs while this connection is healthy
                        while not self._stop_evt.is_set():
                            try:
                                user_input, history_msgs, result_fut = (
                                    await asyncio.wait_for(
                                        self._queue.get(), timeout=0.5
                                    )
                                )
                            except asyncio.TimeoutError:
                                continue

                            try:
                                result = await executor.ainvoke(
                                    {"input": user_input, "chat_history": history_msgs}
                                )
                                # result is dict with "output" and intermediate steps if verbose
                                result_fut.set_result(
                                    {
                                        "ok": True,
                                        "output": result.get("output", ""),
                                        "raw": result,
                                    }
                                )
                            except Exception as e:
                                result_fut.set_result({"ok": False, "error": str(e)})
                            finally:
                                self._queue.task_done()

            except Exception as e:
                # Connection or setup failed — backoff and retry
                # (Any pending submit() calls will remain queued until we reconnect)
                if not self._ready_evt.is_set():
                    # If we haven't been ready yet, still let callers know soon
                    # but we keep trying to connect.
                    pass
                time.sleep(min(backoff, 10))
                backoff = min(backoff * 2, 30)


# -------------------- Flask app --------------------

app = Flask(__name__)
mcp_agent = MCPAgentServer(REMOTE_URL)
mcp_agent.start()


@app.route("/health", methods=["GET"])
def health():
    """
    Health check endpoint.

    Returns:
        JSON response {"status": "ok"} with HTTP 200 on success.
    """
    return jsonify({"status": "ok"}), 200


@app.route("/mcp", methods=["POST"])
def mcp():
    """
    POST JSON:
    {
      "input": "move DE-3 to Done",
      "history": [{"role":"human","content":"..."}, {"role":"ai","content":"..."}]
    }
    """
    data = request.get_json(force=True, silent=True) or {}
    user_input: str = data.get("input", "")
    history: List[Dict[str, str]] = data.get("history", [])

    if not user_input:
        return jsonify({"error": "Missing 'input'"}), 400

    result = mcp_agent.submit(user_input, history)
    status = 200 if result.get("ok", False) else 500

    print("*" * 50)
    print(result)
    print("*" * 50)

    temp = []
    for message in result["raw"]["chat_history"]:
        if type(message) == AIMessage:
            temp.append({"role": "ai", "content": message.content})
        elif type(message) == HumanMessage:
            temp.append({"role": "human", "content": message.content})
    result["raw"]["chat_history"] = temp

    return jsonify(result), status


if __name__ == "__main__":
    # Run Flask (WSGI). Use a prod server (gunicorn/uwsgi) in production.
    app.run(host="0.0.0.0", port=8000, debug=False)

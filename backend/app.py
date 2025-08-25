import json
import time
import asyncio
import threading
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import Flask, request, jsonify

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from langchain_core.runnables import RunnableBranch, RunnableLambda, RunnablePassthrough
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from AgentTools import MCPToolHandler
from prompts import router_system_prompt, worker_system_prompt
from utility import replace_iso8601_with_relative

# ----- server setup -----

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
    Maintains a persistent MCP connection and processes requests sequentially.
    Requires the frontend to ensure that only one request is sent at a time.
    """

    def __init__(self, remote_url: str):
        """
        Initialize the server that hosts a long-lived MCP connection and LangChain agent.

        Args:
            remote_url: Remote MCP URL used by the stdio proxy (mcp-remote).

        Attributes:
            remote_url = The URL of the remote MCP server.
            _loop =
        """

        self.remote_url = remote_url

        # Thread + event loop for persistent connection
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        # Agent chain built once connection is established
        self._agent_chain = None

        # For signaling readiness and shutdown
        self._ready_evt = threading.Event()
        self._stop_evt = threading.Event()

    def start(self):
        """
        Start the background thread and event loop for the MCP agent.

        Notes:
            - Blocks until the agent is ready (or 30s timeout) so that subsequent
              submit() calls can be served immediately.
        """
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop_forever, daemon=True)
        self._thread.start()
        # Wait until agent is ready
        self._ready_evt.wait(timeout=30)

    def stop(self):
        """
        Signal the background loop to stop and join the worker thread.

        Notes:
            - Attempts a graceful shutdown by stopping the asyncio loop and waiting up
              to 5 seconds for the thread to join.
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
        Process a single request using the persistent connection.
        Since frontend guarantees sequential requests, no queue needed.
        chat_history is a list of {"role": "human"/"ai", "content": "..."}

        Return Dict Format:
        {
          "ok": True, # response successful?
          "output": "The ticket DE-7 has been successfully moved to 'Done'.", # final LLM output message
          "raw": {
              "input": "move DE-3 to DONE", # user prompt
              "chat_history": [HumanMessage(...), AIMessage(...), ...], # chat history
              "route": "fast", # model chosen by router LLM
              "output": "The ticket DE-7 has been successfully moved to 'Done'.", # final LLM output message
          }
        }
        """
        if not self._loop or not self._agent_chain:
            return {"ok": False, "error": "MCP agent not ready"}

        fut: asyncio.Future = asyncio.run_coroutine_threadsafe(
            self._process_request(user_input, chat_history or []), self._loop
        )
        return fut.result(timeout=120)

    def _run_loop_forever(self):
        """
        Creates event loop and maintains a persistent MCP connection.
        """
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # Start the connection manager
        self._loop.create_task(self._maintain_connection())
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
        """Stop the event loop."""
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    async def _maintain_connection(self):
        """
        Maintain persistent MCP connection and rebuild agent when connection drops.
        """
        backoff = 1
        while not self._stop_evt.is_set():
            try:
                print("Establishing MCP connection...")
                server = StdioServerParameters(
                    command="npx",
                    args=["-y", "mcp-remote", self.remote_url],
                    env={},
                )

                async with stdio_client(server) as (read, write):
                    async with ClientSession(read, write) as session:
                        print("MCP connection established, building agent...")

                        # Build the agent chain
                        self._agent_chain = await self._build_agent_chain(session)

                        # Signal ready after first successful build
                        self._ready_evt.set()
                        backoff = 1  # reset backoff after success
                        print("Agent ready!")

                        # Keep connection alive until stop or connection drops
                        while not self._stop_evt.is_set():
                            await asyncio.sleep(1)
                            # Connection will drop naturally if MCP server disconnects
                            # The context managers will clean up and this loop will restart

            except Exception as e:
                print(f"MCP connection failed, will retry: {e}")
                self._agent_chain = None

                # Don't set ready if we haven't succeeded at least once
                time.sleep(min(backoff, 10))
                backoff = min(backoff * 2, 30)

    async def _build_agent_chain(self, session: ClientSession):
        """
        Build the complete agent chain using the MCP session.
        """
        # Fetch tools and resources
        tool_meta = await session.list_tools()
        tool_docs = tool_meta.model_dump_json()

        resources = await manual_mcp_call(
            session, "getAccessibleAtlassianResources", {}
        )
        user_info = await manual_mcp_call(session, "atlassianUserInfo", {})

        # Build LLMs
        router_llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash-lite", temperature=0
        )
        fast_llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash", temperature=0, thinking_budget=-1
        )
        smart_llm = ChatOpenAI(model="gpt-4.1-2025-04-14", temperature=0)
        complex_llm = ChatOpenAI(model="o4-mini-2025-04-16")

        # Create prompts
        router_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", router_system_prompt),
                ("human", "{input}"),
            ]
        )

        worker_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", worker_system_prompt),
                MessagesPlaceholder("chat_history"),
                ("human", "{input}"),
                MessagesPlaceholder("agent_scratchpad"),
            ]
        ).partial(
            tool_docs=tool_docs,
            resources=resources,
            user_info=user_info,
        )

        # Get tools
        handler = MCPToolHandler(session)
        agent_tools = handler.get_all_tools()

        # Create executors
        fast_agent = create_tool_calling_agent(fast_llm, agent_tools, worker_prompt)
        fast_executor = AgentExecutor(
            agent=fast_agent,
            tools=agent_tools,
            verbose=False,
            handle_parsing_errors=True,
        )

        smart_agent = create_tool_calling_agent(smart_llm, agent_tools, worker_prompt)
        smart_executor = AgentExecutor(
            agent=smart_agent,
            tools=agent_tools,
            verbose=False,
            handle_parsing_errors=True,
        )

        complex_agent = create_tool_calling_agent(
            complex_llm, agent_tools, worker_prompt
        )
        complex_executor = AgentExecutor(
            agent=complex_agent,
            tools=agent_tools,
            verbose=False,
            handle_parsing_errors=True,
        )

        # Create router chain
        router_chain = router_prompt | router_llm

        # Create final chain
        return RunnablePassthrough.assign(
            route=router_chain
            | RunnableLambda(
                lambda r: (
                    (
                        lambda rt: (
                            "complex"
                            if "complex" in rt
                            else "smart" if "smart" in rt else "fast"
                        )
                    )(r.text().strip().lower())
                )
            )
        ) | RunnableBranch(
            (lambda x: x["route"] == "smart", smart_executor),
            (lambda x: x["route"] == "complex", complex_executor),
            fast_executor,
        )

    async def _process_request(
        self, user_input: str, chat_history_kv: List[Dict[str, str]]
    ):
        """
        Process a single request using the existing agent chain.
        """
        if not self._agent_chain:
            return {"ok": False, "error": "Agent not ready"}

        try:
            # Convert history to LangChain messages
            history_msgs = []
            for m in chat_history_kv:
                if m.get("role") == "human":
                    history_msgs.append(HumanMessage(content=m["content"]))
                elif m.get("role") == "ai":
                    history_msgs.append(AIMessage(content=m["content"]))

            # Process using the persistent agent chain
            final_output = None
            async for e in self._agent_chain.astream_events(
                {"input": user_input, "chat_history": history_msgs},
                version="v1",
            ):
                ev = e["event"]
                if ev == "on_tool_start":
                    print(f"[tool start] {e['name']} args={e['data'].get('input')}")
                elif ev == "on_chain_end":
                    final_output = e["data"]

            return {
                "ok": True,
                "output": final_output.get("output", ""),
                "raw": final_output,
            }

        except Exception as e:
            return {"ok": False, "error": str(e)}


# -------------------- Flask app --------------------

app = Flask(__name__)
mcp_agent = MCPAgentServer(REMOTE_URL)
mcp_agent.start()


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"}), 200


@app.route("/mcp", methods=["POST"])
def mcp():
    """
    Process MCP requests using persistent connection.
    Frontend guarantees sequential requests (no concurrency).
    """
    data = request.get_json(force=True, silent=True) or {}

    user_input: str = data.get("input", "")
    history: List[Dict[str, str]] = data.get("history", [])

    if not user_input:
        return jsonify({"error": "Missing 'input'"}), 400

    result = mcp_agent.submit(user_input, history)
    status = 200 if result.get("ok", False) else 500

    if result.get("ok"):
        output = {"output": result["output"]["output"]}
        output["output"] = replace_iso8601_with_relative(output["output"])
        return jsonify(output), status
    else:
        return jsonify({"error": result.get("error", "Unknown error")}), status


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)

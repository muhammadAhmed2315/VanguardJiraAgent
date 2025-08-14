from typing import Any, Dict
from mcp import ClientSession
from langchain_core.tools import StructuredTool
from ToolSchemas import MCPCallInputWithParser


async def get_list_tools_tool(session: ClientSession) -> StructuredTool:
    """
    Create a LangChain StructuredTool for listing available MCP tools.

    This function wraps the MCP `list_tools` method from the provided
    `ClientSession` into a `StructuredTool` that can be used by a LangChain agent.
    The returned tool lists all available MCP tools and their associated JSON
    schemas, excluding any tools containing "Confluence" in their name.

    Args:
        session (ClientSession): An active MCP client session.

    Returns:
        StructuredTool: A LangChain StructuredTool that lists available MCP tools.
    """

    async def _list_wrapper(dummy: str = "") -> str:
        meta = await session.list_tools()
        meta.tools = [tool for tool in meta.tools if "Confluence" not in tool.name]
        return meta.model_dump_json()

    return StructuredTool.from_function(
        name="mcp_list_tools",
        description="List available MCP tool names and their JSON schemas.",
        func=_list_wrapper,
        coroutine=_list_wrapper,
    )


async def get_call_tool_tool(session: ClientSession) -> StructuredTool:
    """
    Create a LangChain StructuredTool for invoking MCP tools.

    This function wraps the MCP `call_tool` method from the provided
    `ClientSession` into a `StructuredTool` that can be used by a LangChain agent.
    It allows the agent to invoke a specified MCP tool by name with a set of
    arguments, returning the tool's output as a string. Errors during tool
    execution are caught and returned as error messages.

    Args:
        session (ClientSession): An active MCP client session.

    Returns:
        StructuredTool: A LangChain StructuredTool for calling MCP tools with arguments.
    """

    async def _mcp_call(
        tool: str, arguments: Dict[str, Any], mcp: "ClientSession"
    ) -> str:
        """Internal helper to call MCP tools with error handling."""
        try:
            return await mcp.call_tool(tool, arguments)
        except Exception as e:
            return f"MCP tool invocation failed: {e}"

    async def _call_wrapper(tool: str, arguments: Dict[str, Any] = {}) -> str:
        """Wrapper to call an MCP tool using the provided session."""
        return await _mcp_call(tool, arguments, session)

    return StructuredTool.from_function(
        name="mcp_call",
        description=(
            "Call an MCP tool by name with the specified arguments. "
            "Provide the tool name and a dictionary of arguments."
        ),
        func=_call_wrapper,
        args_schema=MCPCallInputWithParser,
        coroutine=_call_wrapper,
    )

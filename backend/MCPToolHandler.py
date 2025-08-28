import logging
from mcp import ClientSession
from typing import Any, Dict, List
from langchain_core.tools import StructuredTool
from MCPCallInputWithParser import MCPCallInputWithParser


class MCPToolHandler:
    """
    Handles the creation and logic for MCP LangChain tools.

    This class encapsulates an MCP client session and provides methods to
    generate fully-formed LangChain StructuredTools for listing and
    invoking MCP tools.
    """

    def __init__(self, session: ClientSession):
        """
        Initializes the MCPToolHandler with an active client session.

        Args:
            session (ClientSession): An active MCP client session.
        """
        self.session = session

    async def list_tools(self) -> str:
        """
        Lists available MCP tools and their schemas

        Returns:
            str: A JSON string representing the available tools.
        """
        meta = await self.session.list_tools()
        return meta.model_dump_json()

    async def call_tool(self, tool: str, arguments: Dict[str, Any] = None) -> str:
        """
        Invokes a specific MCP tool by name with the given arguments.

        Args:
            tool (str): The name of the MCP tool to call.
            arguments (Dict[str, Any], optional): The arguments to pass to the tool.

        Returns:
            str: The output from the tool or an error message if invocation fails.
        """
        if arguments is None:
            arguments = {}
        try:
            return await self.session.call_tool(tool, arguments)
        except Exception as e:
            logging.error(f"MCP tool invocation failed: {e}")
            return f"MCP tool invocation failed: {e}"

    def get_list_tools_tool(self) -> StructuredTool:
        """
        Creates a LangChain StructuredTool for listing available MCP tools.

        This method uses the instance's `list_tools` coroutine to build the tool.

        Returns:
            StructuredTool: A LangChain StructuredTool that lists available MCP tools.
        """
        return StructuredTool.from_function(
            name="mcp_list_tools",
            description="List available MCP tool names and their JSON schemas.",
            func=self.list_tools,
            coroutine=self.list_tools,
        )

    def get_call_tool_tool(self) -> StructuredTool:
        """
        Creates a LangChain StructuredTool for invoking MCP tools.

        This method uses the instance's `call_tool` coroutine to build the tool.

        Returns:
            StructuredTool: A LangChain StructuredTool for calling MCP tools.
        """
        return StructuredTool.from_function(
            name="mcp_call",
            description="Call an MCP tool by name with the specified arguments.",
            func=self.call_tool,
            args_schema=MCPCallInputWithParser,
            coroutine=self.call_tool,
        )

    def get_all_tools(self) -> List[StructuredTool]:
        """
        A convenience method to get all available tools as a list.

        Returns:
            List[StructuredTool]: A list containing the list_tools and call_tool tools.
        """
        return [self.get_list_tools_tool(), self.get_call_tool_tool()]

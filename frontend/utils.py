import html
import json
import logging
import requests
from PIL import Image
import streamlit as st
from requests import Response
from typing import Any, Dict, List, Tuple
from streamlit.delta_generator import DeltaGenerator

from constants import API_URL, DEFAULT_AI_ICON, TOOL_NAME_HUMAN_READABLE


def render_error(msg: str) -> str:
    """
    Wraps an error message string in an HTML <span> element with the class
    'error-msg'. This allows consistent styling of error messages in the UI.

    Args:
        msg: The error message text to be displayed.

    Returns:
        str: An HTML string containing the formatted error message.
    """

    return f'<span class="error-msg-FRONTEND">{msg}</span>'


def safe_load_image_icon(path: str, default=DEFAULT_AI_ICON) -> Image.Image | str:
    try:
        return Image.open(path)
    except Exception as e:
        logging.error(
            f"Image icon at path {path} could not be loaded. Falling back to default icon. Error: {e}"
        )
        return default


def render_tool_call_json(obj: Dict[str, Any]) -> str:
    """
    Formats a `tool_call` JSON object (streamed back by the Flask server) into a
    HTML string.

    Parameters:
        obj: A dictionary representing a `tool_call` event.

    Returns:
        str: A HTML string with a formatted message describing the tool call.
    """
    if obj["name"] == "mcp_list_tools":
        return '<div class="tool-line">Fetching a list of all available tools from the MCP server...</div>'

    elif obj["name"] == "mcp_call":
        tool_name = obj.get("args", {}).get("tool", "unknown tool")
        tool_args = obj.get("args", {}).get("arguments", "unknown arguments")
        return f'<div class="tool-line">{TOOL_NAME_HUMAN_READABLE[tool_name]}</div>'

    else:
        tool_name = obj.get("args", {}).get("tool", "unknown tool")
        tool_args = obj.get("args", {}).get("arguments", "unknown arguments")
        return f'<div class="tool-line">Calling unknown tool: <span class="tool-badge">{tool_name}</span><br>With arguments:<br>{tool_args}</div>'


def load_css(css_file: str) -> None:
    """
    Loads and applies styles from a `.css` file to the streamlit page.

    Args:
        css_file: The path to the CSS file.
    """
    try:
        with open(css_file) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        logging.error(f"CSS stylesheet not found: {css_file}")
    except Exception as e:
        logging.error(f"Could not load stylesheet {css_file}: {e}")


def init_state() -> None:
    """Initialises the streamlit page's session state variables."""
    defaults = {
        "chat_history": [],
        "human_history": [],
        "ai_history": [],
        "disabled_submit_btn": False,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# --- state modifier functions ---
def disable_submit_btn():
    st.session_state.disabled_submit_btn = True


def enable_submit_btn():
    st.session_state.disabled_submit_btn = False
    st.rerun()


def render_chat_history(
    human_icon: Image.Image | str, ai_icon: Image.Image | str
) -> None:
    """
    Renders the conversation history between the user and the AI.

    Args:
        human_icon: The avatar icon for user messages. This should either be a string
            containing a single emoji, or a PIL.Image object.
        ai_icon: The avatar icon for AI messages. This should either be a string
            containing a single emoji, or a PIL.Image object.
    """
    for human, ai in zip(
        st.session_state.get("human_history", []),
        st.session_state.get("ai_history", []),
    ):
        with st.chat_message("human", avatar=human_icon):
            st.markdown(human)

        with st.chat_message("ai", avatar=ai_icon):
            with st.expander("Tool calls"):
                st.markdown(format_tool_calls(ai["tool_calls"]), unsafe_allow_html=True)
            st.markdown(ai["final_output"])


def send_request(prompt: str, chat_history: List[str]) -> requests.Response | str:
    """
    Sends a POST request to the API with the given user prompt and previous chat
    history.

    Args:
        prompt: The user message to be sent to the API.
        chat_history: A list of previous messages to provide context.

    Returns:
        request.Response | str: The response object from the API if successful, or an
            error message string if the request fails.
    """
    try:
        return requests.post(
            API_URL,
            json={"input": prompt, "history": chat_history},
            stream=True,
            timeout=300,
        )
    except requests.Timeout:
        return render_error("Timeout: The server took too long to respond.")
    except requests.ConnectionError:
        return render_error(
            "Connection failed: Could not establish a connection to the server."
        )
    except requests.RequestException as e:
        return render_error("Network error: {html.escape(str(e))}")


def process_stream(
    response: Response,
    tools_box: DeltaGenerator,
    final_text_placeholder: DeltaGenerator,
) -> Tuple[str, List[str]]:
    """
    Process a streaming API response and update UI components with tool calls and
    final output.

    Args:
        response: A streaming response object providing NDJSON.
        tools_box: A Streamlit container used to display tool calls as HTML.
        final_text_placeholder: A Streamlit placeholder used to display the model's
            final output message.

    Returns:
        tuple:
            str: The final output text, or a fallback message if no output is produced.
            list: A list of rendered tool call HTML strings.
    """
    rendered_tool_calls = []
    out = None

    try:
        for raw in response.iter_lines(decode_unicode=True):
            if not raw:
                continue

            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                rendered_tool_calls.append(f'<span class="tool-badge">raw</span>{raw}')
                tools_box.markdown(
                    format_tool_calls(rendered_tool_calls), unsafe_allow_html=True
                )
                continue

            et = obj.get("type")
            if et == "tool_call":
                rendered_tool_calls.append(render_tool_call_json(obj))
            elif et == "final":
                out = obj.get("output", "")
                final_text_placeholder.markdown(
                    out or "_(no output)_", unsafe_allow_html=True
                )
            elif et == "error":
                out = render_error(f"Error: {obj.get('error','Unknown error')}")
                final_text_placeholder.markdown(out, unsafe_allow_html=True)
            else:
                rendered_tool_calls.append(render_tool_call_json(obj))

            tools_box.markdown(
                format_tool_calls(rendered_tool_calls), unsafe_allow_html=True
            )
    except requests.ConnectionError:
        if out is None:
            out = render_error("Connection lost while streaming.")
            final_text_placeholder.markdown(out, unsafe_allow_html=True)
    except requests.RequestException as e:
        out = render_error(f"Stream error: {html.escape(str(e))}")
        final_text_placeholder.markdown(out, unsafe_allow_html=True)
    except Exception as e:
        out = render_error(f"Unexpected error: {html.escape(str(e))}")
        final_text_placeholder.markdown(out, unsafe_allow_html=True)

    return out or "No final output produced.", rendered_tool_calls


def format_tool_calls(calls: List[str]) -> str:
    """
    Format a list of `tool_call` strings into HTML div elements.

    Args:
        calls: A list of `tool_call` objects formatted as HTML string.

    Returns:
        A single string with each tool call wrapped in a <div> element, separated by
            newline characters.
    """
    return "\n".join(calls)

import json
import requests
from PIL import Image
import streamlit as st


# --- Page style ---
st.markdown(
    """
    <style>
    [data-testid="stHeader"] {
        background-color: #96151d;
    }
    [data-testid="stHeader"] * {
        color: white !important;
    }
    .tool-line {
        font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
        font-size: 0.9rem;
        background: #96151d;
        color: #e0e0e0;
        border-radius: 6px;
        padding: 6px 8px;
        margin: 4px 0;
        border: 1px solid #96151d;
        word-break: break-word;
    }
    .tool-badge {
        background: #96151d;
        color: white;
        border-radius: 4px;
        padding: 1px 6px;
        margin-right: 6px;
        font-size: 0.75rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- page config ---
ai_icon = Image.open("./backend/assets/vanguard.jpg")
st.set_page_config(page_title="Vanguard ")

# --- state variables ---
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
    st.session_state.human_history = []
    st.session_state.ai_history = []

if "disabled_submit_btn" not in st.session_state:
    st.session_state.disabled_submit_btn = False


# --- state modifier functions ---
def disable_submit_btn():
    st.session_state.disabled_submit_btn = True


def enable_submit_btn():
    st.session_state.disabled_submit_btn = False
    st.rerun()


# --- title ---
st.header("Vanguard Jira Agent")

# --- layout anchors ---
history_box = st.container()  # chat history at the top
live_box = st.container()  # spinner + NDJSON stream just below history
input_box = st.container()  # input area at the bottom


def _format_tool_line(name, args_obj):
    """Formats a 'tool_start' JSON object into the correct format for rendering onscreen"""
    try:
        args_pretty = json.dumps(
            args_obj, ensure_ascii=False, separators=(",", ":"), indent=None
        )
    except Exception:
        args_pretty = str(args_obj)
    return f'<span class="tool-badge">tool_start</span><strong>{name or "unknown"}</strong> {args_pretty}'


# --- render previous chat history ---
with history_box:
    for human, ai in zip(st.session_state.human_history, st.session_state.ai_history):
        with st.chat_message("human", avatar="👤"):
            st.markdown(human)
        with st.chat_message("ai", avatar=ai_icon):
            st.markdown(ai)

# --- text input area ---
with input_box.form("prompt_form", clear_on_submit=True):
    prompt = st.text_area(
        "Prompt",
        placeholder="Enter your prompt here…",
    )
    send = st.form_submit_button(
        "Send",
        on_click=disable_submit_btn,
        disabled=st.session_state.disabled_submit_btn,
    )

# --- handle submit and render spinner/NDJSON in the live_box (between history and input) ---
if send:
    if not prompt:
        st.warning("Please enter a prompt.")
    else:
        st.session_state.human_history.append(prompt)

        with live_box:
            with st.chat_message("ai", avatar=ai_icon):
                final_text_placeholder = st.empty()  # where final model text will land
                tools_box = st.container()  # rolling tool events
                with st.spinner("Thinking…"):
                    out = None
                    tool_lines = []
                    try:
                        r = requests.post(
                            "http://localhost:8000/mcp",
                            json={
                                "input": prompt,
                                "history": st.session_state.chat_history,
                            },
                            stream=True,
                            timeout=300,
                        )
                        # Iterate over NDJSON lines
                        for raw in r.iter_lines(decode_unicode=True):
                            if not raw:
                                continue
                            # Each raw line is a JSON object
                            try:
                                obj = json.loads(raw)
                            except json.JSONDecodeError:
                                # Non-JSON safety: show as-is in tools area
                                tool_lines.append(
                                    f'<span class="tool-badge">raw</span>{raw}'
                                )
                                tools_box.markdown(
                                    "\n".join(
                                        [
                                            f'<div class="tool-line">{l}</div>'
                                            for l in tool_lines
                                        ]
                                    ),
                                    unsafe_allow_html=True,
                                )
                                continue

                            et = obj.get("type")
                            if et == "tool_start":
                                line = _format_tool_line(
                                    obj.get("name"), obj.get("args")
                                )
                                tool_lines.append(line)
                                tools_box.markdown(
                                    "\n".join(
                                        [
                                            f'<div class="tool-line">{l}</div>'
                                            for l in tool_lines
                                        ]
                                    ),
                                    unsafe_allow_html=True,
                                )
                            elif et == "final":
                                out = obj.get("output", "")
                                # Render final output immediately
                                final_text_placeholder.markdown(
                                    out if out else "_(no output)_"
                                )
                            elif et == "error":
                                out = f"Error: {obj.get('error','Unknown error')}"
                                final_text_placeholder.markdown(out)
                            else:
                                # Unknown event type -> show in tools area for visibility
                                tool_lines.append(
                                    f'<span class="tool-badge">event</span>{json.dumps(obj, ensure_ascii=False)}'
                                )
                                tools_box.markdown(
                                    "\n".join(
                                        [
                                            f'<div class="tool-line">{l}</div>'
                                            for l in tool_lines
                                        ]
                                    ),
                                    unsafe_allow_html=True,
                                )

                        # Fallback if stream ended without a final message
                        if out is None:
                            out = "No final output produced."

                        # Update session state history variables
                        st.session_state.ai_history.append(out)
                        st.session_state.chat_history.append(
                            {"role": "human", "content": prompt}
                        )
                        st.session_state.chat_history.append(
                            {"role": "ai", "content": out}
                        )

                    except requests.RequestException as e:
                        err = f"Request failed: {e}"
                        final_text_placeholder.markdown(err)
                        st.session_state.ai_history.append(err)
                        st.session_state.chat_history.append(
                            {"role": "ai", "content": err}
                        )
                    finally:
                        enable_submit_btn()

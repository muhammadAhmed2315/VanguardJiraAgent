import streamlit as st
from PIL import Image, UnidentifiedImageError

from utils import (
    init_state,
    load_css,
    process_stream,
    render_chat_history,
    safe_load_image_icon,
    send_request,
)
from constants import AI_ICON_FILE, STYLES_FILE, HUMAN_ICON


# --- Page + state setup ---
load_css(STYLES_FILE)

ai_icon = safe_load_image_icon(AI_ICON_FILE)
st.set_page_config(page_title="Vanguard Helper Agent")
st.header("Vanguard Jira Agent")

init_state()

# --- Layout ---
history_box = st.container()
live_box = st.container()
input_box = st.container()

# --- Render history ---
with history_box:
    render_chat_history(HUMAN_ICON, ai_icon)

# --- Input form ---
with input_box.form("prompt_form", clear_on_submit=True):
    prompt = st.text_area("Prompt", placeholder="Enter your prompt here…")
    send = st.form_submit_button("Send", disabled=st.session_state.disabled_submit_btn)

# --- Handle submission ---
if send:
    if not prompt:
        st.warning("Please enter a prompt.")
    else:
        st.session_state.human_history.append(prompt)
        with history_box:
            st.chat_message("human", avatar=HUMAN_ICON).write(prompt)

        # Render live response box
        with live_box:
            with st.chat_message("ai", avatar=ai_icon):
                tools_box = st.expander("Tool calls", True)
                final_text_placeholder = st.empty()

                with st.spinner("Thinking…"):
                    response = send_request(prompt, st.session_state.chat_history)
                    if isinstance(response, str):  # error
                        final_text_placeholder.markdown(
                            response, unsafe_allow_html=True
                        )
                        st.session_state.ai_history.append(
                            {"final_output": response, "tool_calls": []}
                        )
                    else:
                        out, tool_calls = process_stream(
                            response, tools_box, final_text_placeholder
                        )
                        st.session_state.ai_history.append(
                            {"final_output": out, "tool_calls": tool_calls}
                        )
                        st.session_state.chat_history.extend(
                            [
                                {"role": "human", "content": prompt},
                                {"role": "ai", "content": out},
                            ]
                        )

import requests
import streamlit as st

st.set_page_config(page_title="Jira Helper Bot")

# --- state ---
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
    st.session_state.human_history = []
    st.session_state.ai_history = []

st.header("Jira Helper Bot")

# Reserve space at the top for chat messages
chat_box = st.container()

# --- input area (prompt above button) ---
with st.form("prompt_form", clear_on_submit=True):
    prompt = st.text_input("Prompt", placeholder="Enter your prompt here…")
    send = st.form_submit_button("Send")

# --- handle submit BEFORE rendering chat, so new messages show up ---
if send:
    if not prompt:
        st.warning("Please enter a prompt.")
    else:
        st.session_state.human_history.append(prompt)
        with st.spinner("Thinking..."):
            try:
                r = requests.post(
                    "http://localhost:8000/mcp",
                    json={"input": prompt, "history": st.session_state.chat_history},
                    # timeout=30,
                )
                # Prefer JSON if available; fall back to raw text
                try:
                    out = r.json().get("output", r.text)
                except ValueError:
                    out = r.text

                # Update session state history variables
                st.session_state.ai_history.append(out)
                st.session_state.chat_history.append(
                    {"role": "human", "content": prompt}
                )
                st.session_state.chat_history.append({"role": "ai", "content": out})
            except requests.RequestException as e:
                st.session_state.ai_history.append(f"Request failed: {e}")
                st.session_state.chat_history.append(
                    {"role": "ai", "content": f"Request failed: {e}"}
                )

# --- render chat at the top ---
with chat_box:
    for human, ai in zip(st.session_state.human_history, st.session_state.ai_history):
        st.chat_message("human").text(human)
        st.chat_message("ai").text(ai)

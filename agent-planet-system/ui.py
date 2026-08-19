# ui.py — WildTails Catalyst Verse: Streamlit Product UI
import streamlit as st
import requests

# --- Configuration ---
API_URL = "http://127.0.0.1:8000"
USER_ID = "u1"
USER_NAME = "Mina"

# Agent display config: sender_name -> (emoji, color label)
AGENT_STYLE = {
    "System Agent":          ("🛰️", "System Agent"),
    "Người giữ kỷ niệm":    ("🌸", "Memory Keeper"),
    "Sếp Kỷ Luật":          ("📢", "Discipline Boss"),
    "Thuyền Viên Bão Thú":  ("🎮", "Gamemaster"),
    "Wildcats Event Scout":  ("🔭", "Event Scout"),
}

st.set_page_config(
    page_title="WildTails - Catalyst Verse",
    page_icon="🪐",
    layout="wide",
)

# --- Custom CSS ---
st.markdown("""
<style>
    /* Cosmic dark sidebar accents */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d1117 0%, #161b22 100%);
    }
    [data-testid="stSidebar"] * {
        color: #c9d1d9 !important;
    }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {
        color: #58a6ff !important;
    }
    /* Token badge */
    .token-badge {
        background: linear-gradient(135deg, #f0c27f, #fc5c7d);
        color: #1a1a2e !important;
        padding: 8px 16px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 1.1em;
        text-align: center;
        margin: 8px 0;
    }
    /* Planet indicator */
    .planet-indicator {
        padding: 6px 12px;
        border-radius: 12px;
        font-weight: 600;
        text-align: center;
        margin: 4px 0;
    }
    .planet-sun {
        background: linear-gradient(135deg, #ff9a56, #ff6a00);
        color: #fff !important;
    }
    .planet-garden {
        background: linear-gradient(135deg, #56ab2f, #a8e063);
        color: #1a1a2e !important;
    }
    /* Goal status pills */
    .goal-active { color: #58a6ff; font-weight: 600; }
    .goal-done { color: #3fb950; font-weight: 600; }
    .goal-dropped { color: #8b949e; text-decoration: line-through; }
</style>
""", unsafe_allow_html=True)

# --- Session State Init ---
if "planet" not in st.session_state:
    st.session_state.planet = ""
if "mood" not in st.session_state:
    st.session_state.mood = ""


# --- Helper functions ---
def api_get(path, params=None, timeout=5):
    try:
        r = requests.get(f"{API_URL}{path}", params=params, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.ConnectionError:
        pass
    return None


def api_post(path, json_data=None, timeout=30):
    try:
        r = requests.post(f"{API_URL}{path}", json=json_data, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.ConnectionError:
        pass
    return None


def api_put(path, json_data=None, timeout=10):
    try:
        r = requests.put(f"{API_URL}{path}", json=json_data, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except requests.exceptions.ConnectionError:
        pass
    return None


def get_planet_html(planet: str) -> str:
    if "mặt trời" in planet.lower():
        return f'<div class="planet-indicator planet-sun">☀️ {planet}</div>'
    elif "kỷ niệm" in planet.lower():
        return f'<div class="planet-indicator planet-garden">🌿 {planet}</div>'
    return f'<div class="planet-indicator">🪐 {planet}</div>'


# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("## 🪐 WildTails")
    st.caption("Catalyst Verse — Multi-Agent Journal")
    st.divider()

    # Avatar + Name
    st.image(
        f"https://api.dicebear.com/7.x/notionists/svg?seed={USER_NAME}&backgroundColor=b6e3f4",
        width=90,
    )
    st.markdown(f"### {USER_NAME}")

    # Token balance
    token_data = api_get(f"/api/tokens/{USER_ID}")
    balance = token_data["balance"] if token_data else 0
    st.markdown(f'<div class="token-badge">⚡ {balance} Catalyst Points</div>', unsafe_allow_html=True)

    st.divider()

    # Current status
    st.markdown("#### Status")
    if st.session_state.mood:
        st.markdown(f"**Mood:** {st.session_state.mood}")
    else:
        st.caption("Mood: awaiting journal entry")

    if st.session_state.planet:
        st.markdown(get_planet_html(st.session_state.planet), unsafe_allow_html=True)
    else:
        st.caption("Planet: not assigned yet")

    st.divider()

    # Refresh button
    if st.button("🔄 Refresh Messages", use_container_width=True):
        st.rerun()

    st.caption("Agents connected via SSE event bridge")


# ==================== MAIN CONTENT ====================
st.markdown("# 🪐 WildTails — Catalyst Verse")

tab_journal, tab_knowledge, tab_goals, tab_events = st.tabs([
    "📝 Journaling Space",
    "📚 Knowledge Ingestion",
    "🎯 Goals & Tasks",
    "🗓️ Wildcats Events",
])


# ===================== TAB 1: JOURNALING SPACE =====================
with tab_journal:
    # Visibility toggle
    col_mode, col_spacer = st.columns([2, 3])
    with col_mode:
        visibility = st.radio(
            "Journal Mode",
            ["🌍 Planet Feed (Public)", "🔒 Captain's Cabin (Private)"],
            horizontal=True,
            label_visibility="collapsed",
        )
    vis_value = "private" if "Private" in visibility else "public"

    if vis_value == "private":
        st.info("Captain's Cabin mode — your entry stays private and will NOT be shared with other agents.")
    else:
        st.success("Planet Feed mode — your entry will be visible to the agent ecosystem.")

    st.divider()

    # Fetch message history (owner scope to see own private messages)
    messages = []
    msg_data = api_get("/api/messages", params={"scope": f"owner:{USER_NAME}"})
    if msg_data:
        messages = msg_data.get("messages", [])

    if not messages:
        st.caption("No messages yet. Write your first journal entry below!")

    # Chat history rendering
    for msg in messages:
        role = msg.get("role", "assistant")
        sender = msg.get("sender", "")
        content = msg.get("content", "")
        msg_vis = msg.get("visibility", "public")

        with st.chat_message(role):
            if role == "user":
                prefix = "🔒 " if msg_vis == "private" else ""
                st.markdown(f"{prefix}{content}")
            elif sender in AGENT_STYLE:
                emoji, label = AGENT_STYLE[sender]
                st.markdown(f"**{emoji} {label}:** {content}")
            else:
                st.markdown(f"**🤖 {sender}:** {content}")

    # Chat input
    if prompt := st.chat_input("Hom nay ban cam thay the nao?... (How are you feeling today?)"):
        with st.chat_message("user"):
            prefix = "🔒 " if vis_value == "private" else ""
            st.markdown(f"{prefix}{prompt}")

        with st.chat_message("assistant"):
            placeholder = st.empty()
            placeholder.markdown("Connecting to AI brain (Ollama)... ⏳")

            result = api_post("/api/chat", {
                "user_id": USER_ID,
                "user_name": USER_NAME,
                "message": prompt,
                "visibility": vis_value,
            })

            if result:
                st.session_state.planet = result.get("assigned_planet", "")
                st.session_state.mood = result.get("mood", "")
                reply = result.get("agent_reply", "Message received.")
                placeholder.markdown(f"**🛰️ System Agent:** {reply}")
                st.rerun()
            else:
                placeholder.error(
                    "Cannot connect to Backend. Make sure `python app.py` is running."
                )


# ===================== TAB 2: KNOWLEDGE INGESTION =====================
with tab_knowledge:
    st.markdown("### 📚 Knowledge Auto-Log")
    st.markdown(
        "Paste a URL (article, YouTube video, blog post) to extract and embed its content "
        "into your knowledge base for semantic search."
    )

    with st.form("ingest_form", clear_on_submit=True):
        url_input = st.text_input(
            "URL",
            placeholder="https://example.com/article or https://youtube.com/watch?v=...",
        )
        submitted = st.form_submit_button("Ingest Knowledge", use_container_width=True)

    if submitted and url_input:
        with st.spinner("Fetching, chunking, and embedding content..."):
            result = api_post("/api/knowledge/ingest", {
                "url": url_input,
                "user_id": USER_ID,
                "user_name": USER_NAME,
            })

        if result and result.get("status") == "success":
            st.success(
                f"**{result['title']}** ingested successfully!  \n"
                f"Source: `{result['source_type']}` | "
                f"Chunks: {result['stored_chunks']}/{result['total_chunks']} embedded"
            )
        elif result:
            st.error(f"Ingestion failed: {result.get('detail', 'Unknown error')}")
        else:
            st.error("Cannot connect to Backend.")
    elif submitted:
        st.warning("Please enter a URL.")


# ===================== TAB 3: GOALS & TASKS =====================
with tab_goals:
    st.markdown("### 🎯 Mission Control")

    # New goal form
    with st.form("goal_form", clear_on_submit=True):
        goal_title = st.text_input(
            "New Goal",
            placeholder="e.g., Write 3 journal entries this week",
        )
        goal_submitted = st.form_submit_button("Add Goal", use_container_width=True)

    if goal_submitted and goal_title:
        result = api_post("/api/goals", {
            "user_id": USER_ID,
            "user_name": USER_NAME,
            "title": goal_title,
        })
        if result and result.get("status") == "success":
            st.success(f"Goal created! (ID: {result['goal_id']})")
            st.rerun()
        else:
            st.error("Failed to create goal.")
    elif goal_submitted:
        st.warning("Please enter a goal title.")

    st.divider()

    # Existing goals
    goals_data = api_get(f"/api/goals/{USER_ID}")
    goals = goals_data.get("goals", []) if goals_data else []

    if not goals:
        st.caption("No goals yet. Add your first mission above!")
    else:
        for goal in goals:
            gid = goal["id"]
            status = goal["status"]
            title = goal["title"]

            col_title, col_action = st.columns([4, 1])
            with col_title:
                if status == "completed":
                    st.markdown(f'<span class="goal-done">✅ {title}</span>', unsafe_allow_html=True)
                elif status == "abandoned":
                    st.markdown(f'<span class="goal-dropped">⏹️ {title}</span>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<span class="goal-active">🔄 {title}</span>', unsafe_allow_html=True)

            with col_action:
                if status == "in_progress":
                    if st.button("✅", key=f"complete_{gid}", help="Mark complete"):
                        api_put(f"/api/goals/{gid}", {"status": "completed"})
                        st.rerun()

    st.divider()

    # Discipline Boss trigger
    if st.button("📢 Summon Discipline Boss", use_container_width=True,
                  help="Send a reminder SSE event for all pending goals"):
        result = api_post(f"/api/goals/{USER_ID}/remind")
        if result and result.get("status") == "reminder_sent":
            st.success(
                f"Discipline Boss alerted! {result['pending_count']} pending goal(s). "
                "Refresh messages to see the response."
            )
        elif result and result.get("status") == "no_pending_goals":
            st.info("No pending goals — nothing to remind!")
        else:
            st.error("Could not trigger reminder.")


# ===================== TAB 4: WILDCATS EVENTS =====================
with tab_events:
    st.markdown("### 🗓️ Wildcats Community Events")

    col_refresh, col_spacer2 = st.columns([1, 4])
    with col_refresh:
        if st.button("🔄 Refresh Events"):
            api_post("/api/events/refresh")
            st.rerun()

    events_data = api_get("/api/events")
    events_list = events_data.get("events", []) if events_data else []

    if not events_list:
        st.caption("No events loaded. Click Refresh to fetch from Wildcats.io.")
    else:
        for ev in events_list:
            with st.container():
                c1, c2 = st.columns([3, 1])
                with c1:
                    title = ev.get("title", "Untitled")
                    desc = ev.get("description", "")
                    url = ev.get("event_url", "")

                    if url:
                        st.markdown(f"**[{title}]({url})**")
                    else:
                        st.markdown(f"**{title}**")

                    if desc:
                        st.caption(desc[:200])

                    tags = ev.get("tags", [])
                    if tags:
                        st.markdown(" ".join(f"`{t}`" for t in tags))

                with c2:
                    date = ev.get("event_date", "")
                    loc = ev.get("location", "")
                    if date:
                        st.markdown(f"📅 {date}")
                    if loc:
                        st.markdown(f"📍 {loc}")

                st.divider()

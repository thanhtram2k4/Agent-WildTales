# ui.py — WildTails Catalyst Verse: Streamlit Product UI
import streamlit as st
import requests

# --- Configuration ---
API_URL = "http://127.0.0.1:8000"
USER_ID = "u1"
USER_NAME = "Mina"
SSE_POLL_INTERVAL = 3  # seconds between message polls

# Agent display config: sender_name -> (emoji, label)
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

# --- WildTails Visual Identity: Navy / Teal / Golden Yellow ---
st.markdown("""
<style>
    /* Cosmic dark sidebar — navy base */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0b1628 0%, #132240 60%, #1a2d50 100%);
    }
    [data-testid="stSidebar"] * { color: #c9d1d9 !important; }
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 { color: #4dd0c8 !important; }  /* teal headings */

    /* Token badge — golden yellow gradient */
    .token-badge {
        background: linear-gradient(135deg, #f5c842, #e6a817);
        color: #0b1628 !important;
        padding: 8px 16px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 1.1em;
        text-align: center;
        margin: 8px 0;
    }
    /* Planet indicators */
    .planet-indicator {
        padding: 6px 12px; border-radius: 12px;
        font-weight: 600; text-align: center; margin: 4px 0;
    }
    .planet-sun {
        background: linear-gradient(135deg, #f5c842, #e6a817);
        color: #0b1628 !important;
    }
    .planet-garden {
        background: linear-gradient(135deg, #4dd0c8, #2da89e);
        color: #0b1628 !important;
    }
    /* Goal status pills */
    .goal-active { color: #4dd0c8; font-weight: 600; }
    .goal-done { color: #3fb950; font-weight: 600; }
    .goal-dropped { color: #8b949e; text-decoration: line-through; }
    /* Private banner */
    .private-banner {
        background: linear-gradient(135deg, #2d1b4e, #1a1040);
        color: #d4a5ff !important;
        padding: 10px 16px; border-radius: 8px;
        border-left: 4px solid #9b59b6;
        margin-bottom: 12px;
    }
    /* Health status */
    .health-ok { color: #3fb950; }
    .health-warn { color: #f5c842; }
    .health-err { color: #f85149; }
</style>
""", unsafe_allow_html=True)

# --- Session State ---
for key, default in [("planet", ""), ("mood", ""), ("last_msg_count", 0), ("auto_refresh", True)]:
    if key not in st.session_state:
        st.session_state[key] = default


# --- Helpers ---
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


def render_chat_messages(messages, show_private=True):
    """Render a list of chat messages."""
    for msg in messages:
        role = msg.get("role", "assistant")
        sender = msg.get("sender", "")
        content = msg.get("content", "")
        msg_vis = msg.get("visibility", "public")

        if not show_private and msg_vis == "private":
            continue

        with st.chat_message(role):
            if role == "user":
                prefix = "🔒 " if msg_vis == "private" else ""
                st.markdown(f"{prefix}{content}")
            elif sender in AGENT_STYLE:
                emoji, label = AGENT_STYLE[sender]
                st.markdown(f"**{emoji} {label}:** {content}")
            else:
                st.markdown(f"**🤖 {sender}:** {content}")


# ==================== SIDEBAR ====================
with st.sidebar:
    st.markdown("## 🪐 WildTails")
    st.caption("Catalyst Verse — Multi-Agent Journal")
    st.divider()

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

    # Status
    if st.session_state.mood:
        st.markdown(f"**Mood:** {st.session_state.mood}")
    else:
        st.caption("Mood: awaiting journal entry")

    if st.session_state.planet:
        st.markdown(get_planet_html(st.session_state.planet), unsafe_allow_html=True)
    else:
        st.caption("Planet: not assigned yet")

    st.divider()

    # Health check
    health = api_get("/api/health")
    if health:
        services = health.get("services", {})
        for svc, info in services.items():
            status_class = "health-ok" if info.get("ok") else "health-err"
            icon = "●" if info.get("ok") else "○"
            st.markdown(f'<span class="{status_class}">{icon}</span> {svc}', unsafe_allow_html=True)
    else:
        st.markdown('<span class="health-err">○</span> Backend offline', unsafe_allow_html=True)

    st.divider()

    st.session_state.auto_refresh = st.toggle("Auto-refresh", value=st.session_state.auto_refresh)
    if st.button("🔄 Refresh", use_container_width=True):
        st.rerun()


# ==================== MAIN CONTENT ====================
st.markdown("# 🪐 WildTails — Catalyst Verse")

tab_cabin, tab_feed, tab_knowledge, tab_lounge, tab_goals, tab_points, tab_events = st.tabs([
    "🔒 Captain's Cabin",
    "🌍 Planet Feed",
    "📚 Knowledge Station",
    "🎮 Meeting Lounge",
    "🎯 Goals & Tasks",
    "⚡ Catalyst Points",
    "🗓️ Wildcats Events",
])


# ===================== TAB 1: CAPTAIN'S CABIN (PRIVATE) =====================
with tab_cabin:
    st.markdown('<div class="private-banner">🔒 <b>Captain\'s Cabin</b> — Everything here is PRIVATE. '
                'Your entries will NOT be shared with agents or the community.</div>', unsafe_allow_html=True)

    # Fetch only private messages for this user
    messages = []
    msg_data = api_get("/api/messages", params={"scope": f"owner:{USER_ID}"})
    if msg_data:
        all_msgs = msg_data.get("messages", [])
        messages = [m for m in all_msgs if m.get("visibility") == "private"]

    if not messages:
        st.caption("Your private journal is empty. Write your first private entry below.")

    render_chat_messages(messages)

    if prompt := st.chat_input("Write privately... (only you can see this)", key="cabin_input"):
        with st.chat_message("user"):
            st.markdown(f"🔒 {prompt}")

        with st.chat_message("assistant"):
            placeholder = st.empty()
            placeholder.markdown("Processing... ⏳")

            result = api_post("/api/chat", {
                "user_id": USER_ID, "user_name": USER_NAME,
                "message": prompt, "visibility": "private",
            })

            if result:
                st.session_state.planet = result.get("assigned_planet", "")
                st.session_state.mood = result.get("mood", "")
                placeholder.markdown(f"**🛰️ System Agent:** {result.get('agent_reply', 'Saved.')}")
                st.rerun()
            else:
                placeholder.error("Cannot connect to Backend.")


# ===================== TAB 2: PLANET FEED (PUBLIC) =====================
with tab_feed:
    st.markdown("Public journal entries visible to the agent ecosystem.")

    messages = []
    msg_data = api_get("/api/messages", params={"scope": f"owner:{USER_ID}"})
    if msg_data:
        all_msgs = msg_data.get("messages", [])
        messages = [m for m in all_msgs if m.get("visibility") == "public"]

    current_msg_count = len(messages)
    if st.session_state.auto_refresh and current_msg_count > st.session_state.last_msg_count and st.session_state.last_msg_count > 0:
        st.toast("New agent reply received!", icon="🤖")
    st.session_state.last_msg_count = current_msg_count

    if not messages:
        st.caption("No public entries yet.")

    render_chat_messages(messages, show_private=False)

    if prompt := st.chat_input("Share with the planet... (agents will respond)", key="feed_input"):
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            placeholder = st.empty()
            placeholder.markdown("Connecting to AI brain (Ollama)... ⏳")

            result = api_post("/api/chat", {
                "user_id": USER_ID, "user_name": USER_NAME,
                "message": prompt, "visibility": "public",
            })

            if result:
                st.session_state.planet = result.get("assigned_planet", "")
                st.session_state.mood = result.get("mood", "")
                placeholder.markdown(f"**🛰️ System Agent:** {result.get('agent_reply', 'Message received.')}")
                st.rerun()
            else:
                placeholder.error("Cannot connect to Backend. Make sure `python app.py` is running.")

    # Auto-refresh
    if st.session_state.auto_refresh:
        @st.fragment(run_every=SSE_POLL_INTERVAL)
        def _poll_for_updates():
            data = api_get("/api/messages", params={"scope": f"owner:{USER_ID}"})
            if data:
                pub_msgs = [m for m in data.get("messages", []) if m.get("visibility") == "public"]
                if len(pub_msgs) > st.session_state.last_msg_count:
                    st.session_state.last_msg_count = len(pub_msgs)
                    st.rerun()

        _poll_for_updates()


# ===================== TAB 3: KNOWLEDGE STATION =====================
with tab_knowledge:
    st.markdown("### 📚 Knowledge Station")

    ingest_col, search_col = st.columns(2)

    with ingest_col:
        st.markdown("**Ingest a URL**")
        with st.form("ingest_form", clear_on_submit=True):
            url_input = st.text_input(
                "URL", placeholder="https://example.com/article",
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button("Ingest", use_container_width=True)

        if submitted and url_input:
            with st.spinner("Fetching, chunking, and embedding..."):
                result = api_post("/api/knowledge/ingest", {
                    "url": url_input, "user_id": USER_ID, "user_name": USER_NAME,
                })
            if result and result.get("status") == "success":
                st.success(
                    f"**{result['title']}** ingested!  \n"
                    f"`{result['source_type']}` | {result['stored_chunks']}/{result['total_chunks']} chunks"
                )
            elif result:
                st.error(f"Failed: {result.get('detail', 'Unknown error')}")
            else:
                st.error("Backend unavailable.")
        elif submitted:
            st.warning("Enter a URL.")

    with search_col:
        st.markdown("**Semantic Search**")
        with st.form("search_form", clear_on_submit=False):
            search_query = st.text_input(
                "Search", placeholder="What do you want to find?",
                label_visibility="collapsed",
            )
            search_submitted = st.form_submit_button("Search", use_container_width=True)

        if search_submitted and search_query:
            with st.spinner("Searching knowledge base..."):
                result = api_post("/api/knowledge/search", {
                    "query": search_query, "n_results": 5,
                })
            if result and result.get("results"):
                for r in result["results"]:
                    meta = r.get("metadata", {})
                    title = meta.get("title", "Untitled")
                    st.markdown(f"**{title}** (distance: {r.get('distance', 0):.3f})")
                    st.caption(r.get("document", "")[:200])
                    st.divider()
            elif result:
                st.info("No results found.")
            else:
                st.error("Backend unavailable.")

    st.divider()
    st.markdown("**Ask a Question (RAG)**")
    with st.form("ask_form", clear_on_submit=False):
        ask_query = st.text_input(
            "Question", placeholder="Ask anything about ingested knowledge...",
            label_visibility="collapsed",
        )
        ask_submitted = st.form_submit_button("Ask", use_container_width=True)

    if ask_submitted and ask_query:
        with st.spinner("Retrieving and generating answer..."):
            result = api_post("/api/knowledge/ask", {"question": ask_query})
        if result and result.get("answer"):
            st.markdown(f"**Answer:** {result['answer']}")
            if result.get("sources"):
                st.caption("Sources: " + ", ".join(
                    s.get("title", "?") for s in result["sources"] if s.get("title")
                ))
        else:
            st.info("Could not generate an answer.")


# ===================== TAB 4: MEETING LOUNGE (TRIVIA) =====================
with tab_lounge:
    st.markdown("### 🎮 Meeting Lounge — Trivia Challenge")

    # Check for active game
    active_game = api_get(f"/api/game/{USER_ID}/active")

    if active_game and active_game.get("active"):
        room_id = active_game["room_id"]
        question = active_game["question"]
        reward = active_game["reward"]

        st.info(f"**Active Game (Room #{room_id})** — {reward} ⚡ at stake!")
        st.markdown(f"**Question:** {question}")

        with st.form("answer_form", clear_on_submit=True):
            answer_input = st.text_input("Your answer", placeholder="Type your answer...")
            answer_submitted = st.form_submit_button("Submit Answer", use_container_width=True)

        if answer_submitted and answer_input:
            result = api_post("/api/game/answer", {
                "room_id": room_id, "user_id": USER_ID, "answer": answer_input,
            })
            if result and result.get("status") == "answered":
                if result["result"] == "correct":
                    st.success(f"Correct! +{result['reward']} ⚡ Catalyst Points!")
                    st.balloons()
                else:
                    st.error(f"Wrong! The answer was: **{result['correct_answer']}**")
                st.rerun()
            elif result:
                st.error(result.get("detail", "Error"))
    else:
        st.caption("No active game. Start a new trivia challenge!")
        if st.button("🎲 Start Trivia", use_container_width=True):
            result = api_post("/api/game/start", {
                "user_id": USER_ID, "user_name": USER_NAME,
            })
            if result and result.get("status") == "started":
                st.rerun()
            else:
                st.error("Could not start game.")


# ===================== TAB 5: GOALS & TASKS =====================
with tab_goals:
    st.markdown("### 🎯 Mission Control")

    with st.form("goal_form", clear_on_submit=True):
        g_col1, g_col2 = st.columns([3, 1])
        with g_col1:
            goal_title = st.text_input("New Goal", placeholder="e.g., Write 3 journal entries this week")
        with g_col2:
            target_date = st.date_input("Target date", value=None)
        goal_submitted = st.form_submit_button("Add Goal", use_container_width=True)

    if goal_submitted and goal_title:
        result = api_post("/api/goals", {
            "user_id": USER_ID, "user_name": USER_NAME, "title": goal_title,
            "target_date": target_date.isoformat() if target_date else "",
        })
        if result and result.get("status") == "success":
            st.success(f"Goal created! (ID: {result['goal_id']})")
            st.rerun()
        else:
            st.error("Failed to create goal.")

    st.divider()

    goals_data = api_get(f"/api/goals/{USER_ID}")
    goals = goals_data.get("goals", []) if goals_data else []

    if not goals:
        st.caption("No goals yet. Add your first mission above!")
    else:
        for goal in goals:
            gid = goal["id"]
            status = goal["status"]
            title = goal["title"]
            progress = goal.get("progress", 0)
            tdate = goal.get("target_date", "")

            col_title, col_progress, col_action = st.columns([3, 1, 1])
            with col_title:
                if status == "completed":
                    st.markdown(f'<span class="goal-done">✅ {title}</span>', unsafe_allow_html=True)
                elif status == "abandoned":
                    st.markdown(f'<span class="goal-dropped">⏹️ {title}</span>', unsafe_allow_html=True)
                else:
                    deadline_label = f" (due {tdate})" if tdate else ""
                    st.markdown(f'<span class="goal-active">🔄 {title}{deadline_label}</span>', unsafe_allow_html=True)

            with col_progress:
                if status == "in_progress":
                    st.progress(progress / 100, text=f"{progress}%")

            with col_action:
                if status == "in_progress":
                    if st.button("✅", key=f"complete_{gid}", help="Mark complete"):
                        api_put(f"/api/goals/{gid}", {"status": "completed"})
                        st.rerun()

    st.divider()

    if st.button("📢 Summon Discipline Boss", use_container_width=True):
        result = api_post(f"/api/goals/{USER_ID}/remind")
        if result and result.get("status") == "reminder_sent":
            st.success(f"Discipline Boss alerted! {result['pending_count']} pending goal(s).")
        elif result and result.get("status") == "no_pending_goals":
            st.info("No pending goals!")
        else:
            st.error("Could not trigger reminder.")


# ===================== TAB 6: CATALYST POINTS =====================
with tab_points:
    st.markdown("### ⚡ Catalyst Points")

    # Balance
    token_data = api_get(f"/api/tokens/{USER_ID}")
    bal = token_data["balance"] if token_data else 0
    st.markdown(f'<div class="token-badge" style="font-size:1.5em;">⚡ {bal} Points</div>', unsafe_allow_html=True)

    st.divider()
    st.markdown("**Transaction History**")

    txn_data = api_get(f"/api/tokens/{USER_ID}/transactions")
    txns = txn_data.get("transactions", []) if txn_data else []

    if not txns:
        st.caption("No transactions yet. Earn points by completing trivia and goals!")
    else:
        for txn in txns:
            amount = txn["amount"]
            sign = "+" if amount > 0 else ""
            color = "green" if amount > 0 else "red"
            st.markdown(
                f":{color}[**{sign}{amount}**] — {txn['reason']}  \n"
                f"<small>{txn.get('created_at', '')}</small>",
                unsafe_allow_html=True,
            )


# ===================== TAB 7: WILDCATS EVENTS =====================
with tab_events:
    st.markdown("### 🗓️ Wildcats Community Events")

    col_refresh, col_spacer = st.columns([1, 4])
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
                    if ev.get("event_date"):
                        st.markdown(f"📅 {ev['event_date']}")
                    if ev.get("location"):
                        st.markdown(f"📍 {ev['location']}")
                st.divider()

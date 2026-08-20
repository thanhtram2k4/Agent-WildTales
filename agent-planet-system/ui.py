# ui.py — WildTails Catalyst Verse: Streamlit Product UI
import streamlit as st
import requests

from ui.sse_component import render_sse_listener

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

# --- Session State ---
for key, default in [("planet", ""), ("mood", ""), ("last_msg_count", 0), ("auto_refresh", True)]:
    if key not in st.session_state:
        st.session_state[key] = default


# ---------------------------------------------------------------------------
# Dynamic mood-based theming
# ---------------------------------------------------------------------------
def resolve_mood_theme(planet: str) -> str:
    """Map the assigned planet string to a theme key.

    Returns:
        "sun"     — Positive mood  → Golden Yellow palette
        "garden"  — Negative mood  → Deep Navy / Calming Blue palette
        "neutral" — No mood yet    → Default Navy / Teal palette
    """
    p = planet.lower()
    if "mặt trời" in p:
        return "sun"
    if "kỷ niệm" in p:
        return "garden"
    return "neutral"


# Three complete CSS variable palettes.  Every colour in the UI reads from
# these variables so changing them is a single-point switch.
_THEME_VARS = {
    # ── Default Hub (Neutral) — Navy / Teal ──
    "neutral": {
        "sidebar-bg":        "linear-gradient(180deg, #0b1628 0%, #132240 60%, #1a2d50 100%)",
        "sidebar-text":      "#c9d1d9",
        "sidebar-heading":   "#4dd0c8",
        "accent":            "#4dd0c8",
        "accent-glow":       "rgba(77, 208, 200, 0.25)",
        "main-bg":           "transparent",
        "heading-color":     "#4dd0c8",
        "chat-user-bg":      "rgba(77, 208, 200, 0.08)",
        "chat-user-border":  "#4dd0c8",
        "chat-agent-bg":     "rgba(245, 200, 66, 0.06)",
        "chat-agent-border": "#f5c842",
        "badge-bg":          "linear-gradient(135deg, #f5c842, #e6a817)",
        "badge-text":        "#0b1628",
        "mood-banner-bg":    "linear-gradient(135deg, #132240, #1a2d50)",
        "mood-banner-border": "#4dd0c8",
        "mood-banner-text":  "#4dd0c8",
        "mood-icon":         "🪐",
        "mood-label":        "Neutral Hub",
    },
    # ── Sun Planet (Positive) — Golden Yellow / Warm Amber ──
    "sun": {
        "sidebar-bg":        "linear-gradient(180deg, #1a1505 0%, #2d2008 60%, #3d2e0a 100%)",
        "sidebar-text":      "#e8d5a3",
        "sidebar-heading":   "#f5c842",
        "accent":            "#f5c842",
        "accent-glow":       "rgba(245, 200, 66, 0.30)",
        "main-bg":           "transparent",
        "heading-color":     "#f5c842",
        "chat-user-bg":      "rgba(245, 200, 66, 0.10)",
        "chat-user-border":  "#f5c842",
        "chat-agent-bg":     "rgba(245, 170, 40, 0.08)",
        "chat-agent-border": "#e6a817",
        "badge-bg":          "linear-gradient(135deg, #f5c842, #e6a817)",
        "badge-text":        "#1a1505",
        "mood-banner-bg":    "linear-gradient(135deg, #3d2e0a, #5a4510)",
        "mood-banner-border": "#f5c842",
        "mood-banner-text":  "#f5c842",
        "mood-icon":         "☀️",
        "mood-label":        "Sun Planet",
    },
    # ── Memory Garden (Negative) — Deep Navy / Calming Blue ──
    "garden": {
        "sidebar-bg":        "linear-gradient(180deg, #0a0e1a 0%, #0f1a30 60%, #162040 100%)",
        "sidebar-text":      "#a0b4cc",
        "sidebar-heading":   "#6c8ebf",
        "accent":            "#6c8ebf",
        "accent-glow":       "rgba(108, 142, 191, 0.25)",
        "main-bg":           "transparent",
        "heading-color":     "#6c8ebf",
        "chat-user-bg":      "rgba(108, 142, 191, 0.10)",
        "chat-user-border":  "#6c8ebf",
        "chat-agent-bg":     "rgba(77, 208, 200, 0.06)",
        "chat-agent-border": "#4dd0c8",
        "badge-bg":          "linear-gradient(135deg, #6c8ebf, #4a6d9e)",
        "badge-text":        "#0a0e1a",
        "mood-banner-bg":    "linear-gradient(135deg, #0f1a30, #162040)",
        "mood-banner-border": "#6c8ebf",
        "mood-banner-text":  "#8fa8c8",
        "mood-icon":         "🌿",
        "mood-label":        "Memory Garden",
    },
}


def _build_theme_css(theme_key: str) -> str:
    """Build the full CSS string for the given theme, using CSS custom properties."""
    t = _THEME_VARS.get(theme_key, _THEME_VARS["neutral"])
    return f"""
<style>
    /* ====== CSS custom properties — single source of truth ====== */
    :root {{
        --wt-accent:            {t["accent"]};
        --wt-accent-glow:       {t["accent-glow"]};
        --wt-heading:           {t["heading-color"]};
        --wt-chat-user-bg:      {t["chat-user-bg"]};
        --wt-chat-user-border:  {t["chat-user-border"]};
        --wt-chat-agent-bg:     {t["chat-agent-bg"]};
        --wt-chat-agent-border: {t["chat-agent-border"]};
    }}

    /* ====== Sidebar ====== */
    [data-testid="stSidebar"] {{
        background: {t["sidebar-bg"]};
        transition: background 0.6s ease;
    }}
    [data-testid="stSidebar"] * {{ color: {t["sidebar-text"]} !important; }}
    [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {{ color: {t["sidebar-heading"]} !important; }}

    /* ====== Main area ====== */
    .stApp > header + div {{
        transition: background 0.6s ease;
    }}

    /* ====== Token badge ====== */
    .token-badge {{
        background: {t["badge-bg"]};
        color: {t["badge-text"]} !important;
        padding: 8px 16px;
        border-radius: 20px;
        font-weight: 700;
        font-size: 1.1em;
        text-align: center;
        margin: 8px 0;
        transition: background 0.5s ease;
    }}

    /* ====== Mood banner (sidebar) ====== */
    .mood-banner {{
        background: {t["mood-banner-bg"]};
        color: {t["mood-banner-text"]} !important;
        padding: 10px 14px;
        border-radius: 10px;
        border-left: 4px solid {t["mood-banner-border"]};
        margin: 8px 0;
        font-size: 0.9em;
        line-height: 1.4;
        transition: background 0.5s ease, border-color 0.5s ease;
    }}
    .mood-banner strong {{
        color: {t["mood-banner-text"]} !important;
    }}

    /* ====== Planet indicators ====== */
    .planet-indicator {{
        padding: 6px 12px; border-radius: 12px;
        font-weight: 600; text-align: center; margin: 4px 0;
    }}
    .planet-sun {{
        background: linear-gradient(135deg, #f5c842, #e6a817);
        color: #0b1628 !important;
    }}
    .planet-garden {{
        background: linear-gradient(135deg, #6c8ebf, #4a6d9e);
        color: #0a0e1a !important;
    }}

    /* ====== Chat message accents ====== */
    [data-testid="stChatMessage"] {{
        transition: border-color 0.4s ease;
    }}

    /* ====== Goal status pills ====== */
    .goal-active {{ color: var(--wt-accent); font-weight: 600; }}
    .goal-done {{ color: #3fb950; font-weight: 600; }}
    .goal-dropped {{ color: #8b949e; text-decoration: line-through; }}

    /* ====== Private banner (Captain's Cabin — never changes) ====== */
    .private-banner {{
        background: linear-gradient(135deg, #2d1b4e, #1a1040);
        color: #d4a5ff !important;
        padding: 10px 16px; border-radius: 8px;
        border-left: 4px solid #9b59b6;
        margin-bottom: 12px;
    }}

    /* ====== Health status ====== */
    .health-ok {{ color: #3fb950; }}
    .health-warn {{ color: #f5c842; }}
    .health-err {{ color: #f85149; }}

    /* ====== Ambient glow — subtle planet-coloured shadow under header ====== */
    .planet-glow {{
        height: 3px;
        background: var(--wt-accent);
        box-shadow: 0 0 18px 4px var(--wt-accent-glow);
        border-radius: 2px;
        margin: -4px 0 12px 0;
        transition: background 0.6s ease, box-shadow 0.6s ease;
    }}
</style>
"""


# Resolve theme and inject CSS
_current_theme = resolve_mood_theme(st.session_state.planet)
st.markdown(_build_theme_css(_current_theme), unsafe_allow_html=True)


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
    p = planet.lower()
    if "mặt trời" in p:
        return f'<div class="planet-indicator planet-sun">☀️ {planet}</div>'
    if "kỷ niệm" in p:
        return f'<div class="planet-indicator planet-garden">🌿 {planet}</div>'
    return f'<div class="planet-indicator" style="background:var(--wt-accent);color:#0b1628;">🪐 {planet}</div>'


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

    # Mood-aware status banner
    _theme_meta = _THEME_VARS.get(_current_theme, _THEME_VARS["neutral"])
    if st.session_state.mood and st.session_state.planet:
        st.markdown(
            f'<div class="mood-banner">'
            f'{_theme_meta["mood-icon"]} <strong>{_theme_meta["mood-label"]}</strong><br>'
            f'{st.session_state.mood}'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.markdown(get_planet_html(st.session_state.planet), unsafe_allow_html=True)
    else:
        st.caption("Mood: awaiting journal entry")
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
st.markdown('<div class="planet-glow"></div>', unsafe_allow_html=True)

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

    # Real-time SSE listener — replaces st.fragment polling.
    # Injects NEW_MESSAGE and AGENT_REPLY events directly into the DOM
    # without triggering a Streamlit rerun. Only public messages are
    # broadcast by the backend, so Captain's Cabin stays isolated.
    if st.session_state.auto_refresh:
        render_sse_listener(
            sse_url=f"{API_URL}/api/sse/events",
            user_id=USER_ID,
            height=0,
            theme=_current_theme,
        )


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


# ===================== TAB 4: MEETING LOUNGE (TRIVIA + MA SÓI RPG) =====================
with tab_lounge:
    st.markdown("### 🎮 Meeting Lounge")

    # Check for any active game
    active_game = api_get(f"/api/game/{USER_ID}/active")

    if active_game and active_game.get("active"):
        game_type = active_game.get("game_type", "trivia")
        room_id = active_game["room_id"]

        if game_type == "masoi":
            # ---- Ma Sói RPG UI ----
            phase = active_game.get("phase", "NIGHT_PHASE")
            round_num = active_game.get("round_number", 1)
            player_role = active_game.get("player_role", "")
            alive_npcs = active_game.get("alive_npcs", [])

            # Role display
            ROLE_EMOJI = {"sói": "🐺", "tiên_tri": "🔮", "bảo_vệ": "🛡️", "dân": "🐱", "thợ_săn": "🏹"}
            role_em = ROLE_EMOJI.get(player_role, "🐱")
            st.info(f"**Ma Sói RPG (Room #{room_id})** — Vòng {round_num} | {role_em} Vai: {player_role}")

            # Phase indicator
            phase_labels = {
                "ROLE_ASSIGNMENT": "📜 Phân vai...",
                "NIGHT_PHASE": "🌙 Đêm — chọn hành động",
                "DAY_DISCUSSION": "☀️ Ban ngày — thảo luận",
                "VOTING": "⚖️ Bỏ phiếu loại người chơi",
                "FINISHED": "🏁 Trò chơi kết thúc",
            }
            st.markdown(f"**Giai đoạn:** {phase_labels.get(phase, phase)}")
            st.caption(f"Còn sống: {', '.join(alive_npcs)}")

            # Night action or Vote input
            if phase == "NIGHT_PHASE" and player_role in ("sói", "tiên_tri", "bảo_vệ"):
                action_labels = {"sói": "Tấn công", "tiên_tri": "Soi", "bảo_vệ": "Bảo vệ"}
                targets = list(alive_npcs)
                if player_role == "bảo_vệ":
                    targets = [USER_NAME] + targets

                with st.form("night_action_form", clear_on_submit=True):
                    target = st.selectbox(
                        f"{action_labels[player_role]} ai?", targets,
                    )
                    submitted = st.form_submit_button(
                        f"{role_em} {action_labels[player_role]}", use_container_width=True,
                    )
                if submitted and target:
                    result = api_post(f"/api/game/rpg/{room_id}/action", {
                        "room_id": room_id, "user_id": USER_ID, "target": target,
                    })
                    if result and result.get("status") == "action_received":
                        st.success(f"Hành động đã gửi: {target}")
                        st.rerun()
                    elif result:
                        st.error(result.get("error", "Error"))

            elif phase == "NIGHT_PHASE":
                st.caption("Bạn là Dân Làng — đang ngủ... chờ bình minh.")

            elif phase == "VOTING":
                with st.form("vote_form", clear_on_submit=True):
                    target = st.selectbox("Bỏ phiếu loại ai?", alive_npcs)
                    submitted = st.form_submit_button("⚖️ Bỏ phiếu", use_container_width=True)
                if submitted and target:
                    result = api_post(f"/api/game/rpg/{room_id}/action", {
                        "room_id": room_id, "user_id": USER_ID, "target": target,
                    })
                    if result and result.get("status") == "action_received":
                        st.success(f"Phiếu đã gửi: {target}")
                        st.rerun()
                    elif result:
                        st.error(result.get("error", "Error"))

            elif phase == "DAY_DISCUSSION":
                st.caption("Đang thảo luận... Gamemaster sẽ mở phiếu bầu.")

            elif phase == "FINISHED":
                st.success("Trò chơi đã kết thúc! Xem kết quả trong chat.")
                if st.button("🎮 Chơi lại", key="rpg_restart", use_container_width=True):
                    result = api_post("/api/game/rpg/start", {
                        "user_id": USER_ID, "user_name": USER_NAME,
                    })
                    if result and result.get("status") == "started":
                        st.rerun()

        else:
            # ---- Trivia UI (original) ----
            question = active_game.get("question", "")
            reward = active_game.get("reward", 5)

            st.info(f"**Trivia (Room #{room_id})** — {reward} ⚡ at stake!")
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
        st.caption("No active game. Choose a game mode to start!")
        col_trivia, col_rpg = st.columns(2)
        with col_trivia:
            if st.button("🎲 Start Trivia", use_container_width=True):
                result = api_post("/api/game/start", {
                    "user_id": USER_ID, "user_name": USER_NAME,
                })
                if result and result.get("status") == "started":
                    st.rerun()
                else:
                    st.error("Could not start game.")
        with col_rpg:
            if st.button("🐺 Start Ma Sói RPG", use_container_width=True):
                result = api_post("/api/game/rpg/start", {
                    "user_id": USER_ID, "user_name": USER_NAME,
                })
                if result and result.get("status") == "started":
                    st.toast(f"Vai của bạn: {result.get('role_emoji','')} {result.get('role_label','')}")
                    st.rerun()
                else:
                    st.error("Could not start Ma Sói game.")


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

    # Fetch user's participation records to show current status on each card
    _participation_data = api_get(f"/api/events/participation/{USER_ID}")
    _participation_map: dict[str, str] = {}
    if _participation_data:
        for p in _participation_data.get("participations", []):
            _participation_map[p["event_id"]] = p["status"]

    events_data = api_get("/api/events")
    events_list = events_data.get("events", []) if events_data else []

    if not events_list:
        st.caption("No events loaded. Click Refresh to fetch from Wildcats.io.")
    else:
        for _ev_idx, ev in enumerate(events_list):
            with st.container():
                c1, c2, c3 = st.columns([3, 1, 1])
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
                with c3:
                    # Use a stable event_id derived from title (same logic as embed)
                    _event_id = f"event_{title.lower().replace(' ', '_')[:50]}"
                    _current_status = _participation_map.get(_event_id, "")

                    if _current_status == "attended":
                        st.markdown(":green[**Attended**]")
                    elif _current_status == "interested":
                        st.caption("Interested")
                        if st.button("Mark Attended", key=f"attend_{_ev_idx}"):
                            result = api_post("/api/events/participation", {
                                "user_id": USER_ID,
                                "event_id": _event_id,
                                "status": "attended",
                            })
                            if result and result.get("token_award") == "awarded":
                                st.success("+8 Catalyst Points!")
                            st.rerun()
                    else:
                        if st.button("Interested", key=f"interest_{_ev_idx}"):
                            api_post("/api/events/participation", {
                                "user_id": USER_ID,
                                "event_id": _event_id,
                                "status": "interested",
                            })
                            st.rerun()
                st.divider()

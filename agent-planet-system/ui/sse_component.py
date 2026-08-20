"""
WildTails SSE Component — True real-time Streamlit component.

Embeds a persistent EventSource connection to the FastAPI SSE endpoint.
Listens for NEW_MESSAGE and AGENT_REPLY events, and injects them into
the Streamlit chat container DOM *without* triggering a full script rerun.

Privacy: Only PUBLIC messages are broadcast by the backend; the component
never receives Captain's Cabin (private) entries.
"""
from __future__ import annotations

import json
import streamlit.components.v1 as components

# Agent display config matching ui.py AGENT_STYLE
_AGENT_STYLE_JS = json.dumps({
    "System Agent":         ["🛰️", "System Agent"],
    "Người giữ kỷ niệm":   ["🌸", "Memory Keeper"],
    "Sếp Kỷ Luật":         ["📢", "Discipline Boss"],
    "Thuyền Viên Bão Thú":  ["🎮", "Gamemaster"],
    "Wildcats Event Scout":  ["🔭", "Event Scout"],
})


def render_sse_listener(
    sse_url: str = "http://127.0.0.1:8000/api/sse/events",
    user_id: str = "u1",
    height: int = 0,
    theme: str = "neutral",
) -> None:
    """Render an invisible iframe that keeps an SSE connection alive.

    The iframe connects to ``sse_url`` and listens for server-sent events.
    When a ``NEW_MESSAGE`` or ``AGENT_REPLY`` event arrives it locates the
    Planet Feed chat container in the *parent* Streamlit DOM and appends
    the message bubble directly — no ``st.rerun()`` needed.

    Injected bubble styles read CSS custom properties (``--wt-*``) from the
    parent frame, so they automatically match the active mood theme.

    Args:
        sse_url: Full URL to the ``GET /api/sse/events`` endpoint.
        user_id: Current user id (used to style own messages differently).
        height: Iframe height in pixels.  ``0`` keeps it invisible.
        theme: Current mood theme key (``"sun"``, ``"garden"``, ``"neutral"``).
    """
    html = _build_component_html(sse_url, user_id, theme)
    components.html(html, height=height, scrolling=False)


def _build_component_html(sse_url: str, user_id: str, theme: str = "neutral") -> str:
    """Return the full HTML/JS for the SSE listener component."""
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<style>
  /* Component itself is invisible — it only manipulates the parent DOM */
  body {{ margin: 0; padding: 0; overflow: hidden; }}

  /* Injected message bubble styles (scoped via class prefix) */
  .sse-msg-bubble {{
    padding: 0.75rem 1rem;
    margin: 0.5rem 0;
    border-radius: 0.75rem;
    animation: sse-fade-in 0.35s ease-out;
    line-height: 1.5;
    font-family: "Source Sans Pro", sans-serif;
    font-size: 0.95rem;
  }}
  .sse-msg-user {{
    background: rgba(77, 208, 200, 0.12);
    border-left: 3px solid #4dd0c8;
  }}
  .sse-msg-agent {{
    background: rgba(245, 200, 66, 0.10);
    border-left: 3px solid #f5c842;
  }}
  .sse-msg-sender {{
    font-weight: 700;
    margin-bottom: 2px;
  }}
  .sse-toast {{
    position: fixed; top: 12px; right: 12px;
    background: #1a2d50; color: #4dd0c8;
    padding: 10px 18px; border-radius: 8px;
    font-size: 0.85rem; z-index: 99999;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    animation: sse-fade-in 0.3s ease-out;
  }}
  @keyframes sse-fade-in {{
    from {{ opacity: 0; transform: translateY(-8px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}
</style>
</head>
<body>
<script>
(function() {{
  "use strict";

  const SSE_URL  = {json.dumps(sse_url)};
  const USER_ID  = {json.dumps(user_id)};
  const AGENT_STYLE = {_AGENT_STYLE_JS};

  // ---- Seen-event dedup (avoid duplicates on reconnect) ----
  const seenIds = new Set();
  const MAX_SEEN = 500;

  // ---- Locate the Planet Feed chat container in the parent frame ----
  function findChatContainer() {{
    try {{
      const parent = window.parent.document;
      // Streamlit renders tab content in [data-testid="stVerticalBlockBorderWrapper"]
      // The Planet Feed tab is the second tab.  We look for the chat container
      // that lives inside it by searching for all stChatMessageContainers.
      const containers = parent.querySelectorAll(
        '[data-testid="stChatMessageContainer"]'
      );
      // The second chat container belongs to the Planet Feed tab
      // (index 0 = Captain's Cabin, index 1 = Planet Feed)
      if (containers.length >= 2) return containers[1];
      // Fallback: try the last one
      if (containers.length > 0) return containers[containers.length - 1];
    }} catch (e) {{
      // Cross-origin — can't reach parent
    }}
    return null;
  }}

  // ---- Toast notification in parent ----
  function showToast(text, durationMs) {{
    durationMs = durationMs || 3000;
    try {{
      const parent = window.parent.document;
      const toast = parent.createElement("div");
      toast.className = "sse-toast";
      toast.textContent = text;
      parent.body.appendChild(toast);
      setTimeout(function() {{ toast.remove(); }}, durationMs);
    }} catch (_) {{ /* no-op */ }}
  }}

  // ---- Inject a message bubble into the DOM ----
  function injectMessage(data) {{
    const container = findChatContainer();
    if (!container) return;

    const eventId = data.event_id || "";
    if (eventId && seenIds.has(eventId)) return;
    if (eventId) {{
      seenIds.add(eventId);
      if (seenIds.size > MAX_SEEN) {{
        const first = seenIds.values().next().value;
        seenIds.delete(first);
      }}
    }}

    const isAgent = data.type === "AGENT_REPLY";
    const sender  = data.sender || data.user || "Unknown";
    const content = data.content || data.message || "";

    // Build bubble
    const bubble = document.createElement("div");
    bubble.className = "sse-msg-bubble " + (isAgent ? "sse-msg-agent" : "sse-msg-user");

    // Sender label
    const labelDiv = document.createElement("div");
    labelDiv.className = "sse-msg-sender";
    if (isAgent && AGENT_STYLE[sender]) {{
      const style = AGENT_STYLE[sender];
      labelDiv.textContent = style[0] + " " + style[1];
    }} else if (isAgent) {{
      labelDiv.textContent = "🤖 " + sender;
    }} else {{
      labelDiv.textContent = "👤 " + sender;
    }}
    bubble.appendChild(labelDiv);

    // Content
    const contentDiv = document.createElement("div");
    contentDiv.textContent = content;
    bubble.appendChild(contentDiv);

    // Inject into parent DOM (inside the Streamlit chat container)
    try {{
      const parentDoc = window.parent.document;
      // Ensure theme-aware styles exist in parent.  Uses CSS custom
      // properties (--wt-*) set by ui.py so colours automatically match
      // the active mood theme without hardcoded values.
      if (!parentDoc.getElementById("sse-injected-styles")) {{
        const styleTag = parentDoc.createElement("style");
        styleTag.id = "sse-injected-styles";
        styleTag.textContent = `
          .sse-msg-bubble {{
            padding: 0.75rem 1rem;
            margin: 0.5rem 0;
            border-radius: 0.75rem;
            animation: sse-fade-in 0.35s ease-out;
            line-height: 1.5;
            font-family: "Source Sans Pro", sans-serif;
            font-size: 0.95rem;
            transition: background 0.4s ease, border-color 0.4s ease;
          }}
          .sse-msg-user {{
            background: var(--wt-chat-user-bg, rgba(77, 208, 200, 0.12));
            border-left: 3px solid var(--wt-chat-user-border, #4dd0c8);
          }}
          .sse-msg-agent {{
            background: var(--wt-chat-agent-bg, rgba(245, 200, 66, 0.10));
            border-left: 3px solid var(--wt-chat-agent-border, #f5c842);
          }}
          .sse-msg-sender {{
            font-weight: 700;
            margin-bottom: 2px;
          }}
          .sse-toast {{
            position: fixed; top: 12px; right: 12px;
            background: var(--wt-accent, #4dd0c8);
            color: #0b1628;
            padding: 10px 18px; border-radius: 8px;
            font-size: 0.85rem; z-index: 99999;
            box-shadow: 0 0 16px 2px var(--wt-accent-glow, rgba(77,208,200,0.25));
            animation: sse-fade-in 0.3s ease-out;
            transition: background 0.4s ease;
          }}
          @keyframes sse-fade-in {{
            from {{ opacity: 0; transform: translateY(-8px); }}
            to   {{ opacity: 1; transform: translateY(0); }}
          }}
        `;
        parentDoc.head.appendChild(styleTag);
      }}

      container.appendChild(bubble);

      // Smooth scroll into view
      bubble.scrollIntoView({{ behavior: "smooth", block: "end" }});
    }} catch (e) {{
      console.warn("[SSE Component] Could not inject into parent DOM:", e);
    }}

    // Toast
    const toastLabel = isAgent
      ? (AGENT_STYLE[sender] ? AGENT_STYLE[sender][0] + " " + AGENT_STYLE[sender][1] : sender) + " replied!"
      : sender + " posted a new entry";
    showToast(toastLabel, 3500);
  }}

  // ---- SSE Connection with auto-reconnect ----
  let reconnectDelay = 1000;
  const MAX_RECONNECT = 15000;

  function connect() {{
    console.log("[SSE Component] Connecting to", SSE_URL);
    const es = new EventSource(SSE_URL);

    es.addEventListener("agent_message", function(e) {{
      try {{
        const data = JSON.parse(e.data);
        // Parse the inner JSON if data is a string (double-encoded)
        const payload = typeof data === "string" ? JSON.parse(data) : data;

        // Only handle NEW_MESSAGE and AGENT_REPLY types
        if (payload.type === "NEW_MESSAGE" || payload.type === "AGENT_REPLY") {{
          injectMessage(payload);
        }}
      }} catch (err) {{
        console.warn("[SSE Component] Parse error:", err);
      }}
    }});

    es.onopen = function() {{
      console.log("[SSE Component] Connected");
      reconnectDelay = 1000;
    }};

    es.onerror = function() {{
      console.warn("[SSE Component] Connection lost, reconnecting in", reconnectDelay, "ms");
      es.close();
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.5, MAX_RECONNECT);
    }};
  }}

  connect();
}})();
</script>
</body>
</html>
"""

# agents/base_agent.py — Reusable base framework for WildTails persona agents
import json
import logging
import os
import random
import time
import threading
from abc import ABC, abstractmethod

import requests
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("wildtails.agents")

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3")

# Inter-agent collaboration limits
MAX_AGENT_DEPTH = 2          # max consecutive agent-to-agent replies
AGENT_REPLY_DELAY = (1.5, 4.0)  # random delay range (seconds) before replying to another agent


class BaseAgent(ABC):
    """Abstract base class for all WildTails persona agents.

    Subclasses must implement:
      - agent_name: display name for this agent
      - system_prompt: LLM system prompt defining persona
      - event_filter(data): return True if this agent should handle the event
      - handle_event(data): process the event and optionally reply

    For inter-agent collaboration, subclasses may override:
      - agent_reply_filter(data): return True if this agent should react to
        another agent's AGENT_REPLY event.  Defaults to False (opt-in).
      - handle_agent_reply(data): process the other agent's message.
    """

    RECONNECT_DELAY = 3  # seconds between SSE reconnect attempts

    def __init__(self):
        self.ollama = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
        self._running = False

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Display name for this agent."""

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """LLM system prompt defining the agent persona."""

    @abstractmethod
    def event_filter(self, data: dict) -> bool:
        """Return True if this agent should respond to the given SSE event.

        This is the deterministic routing gate — each agent only processes
        events matching its scope to prevent agent spam.
        """

    @abstractmethod
    def handle_event(self, data: dict) -> None:
        """Process a filtered SSE event. May call generate_reply / send_reply."""

    # --- Inter-agent collaboration (opt-in) ---

    def agent_reply_filter(self, data: dict) -> bool:
        """Return True if this agent should react to another agent's reply.

        Override in subclasses that participate in inter-agent conversation.
        The default returns False — agents ignore each other unless they
        explicitly opt in.

        Args:
            data: The AGENT_REPLY event payload.  Contains at minimum:
                  sender, content, user_id, conversation_id, depth.
        """
        return False

    def handle_agent_reply(self, data: dict) -> None:
        """React to another agent's AGENT_REPLY event.

        Override in subclasses.  The ``depth`` field has already been
        validated (< MAX_AGENT_DEPTH) before this method is called.
        Call ``send_reply(..., depth=data["depth"] + 1)`` to chain.
        """

    # --- Shared utilities ---

    def fetch_recent_context(self, n: int = 10) -> str:
        """Fetch last n public messages from backend.

        Community agents ONLY see public scope — private (Captain's Cabin)
        entries are never included in agent context.
        """
        try:
            resp = requests.get(
                f"{BACKEND_URL}/api/messages",
                params={"scope": "public"},
                timeout=5,
            )
            if resp.status_code == 200:
                messages = resp.json().get("messages", [])
                # Double-check: filter out any non-public messages defensively
                messages = [m for m in messages if m.get("visibility") != "private"]
                recent = messages[-n:] if len(messages) > n else messages
                lines = [f"[{m.get('sender', '?')}]: {m.get('content', '')}" for m in recent]
                return "\n".join(lines)
        except Exception as e:
            logger.warning("[%s] Failed to fetch context: %s", self.agent_name, e)
        return ""

    def generate_reply(self, user_prompt: str, temperature: float = 0.7) -> str:
        """Generate an LLM reply using this agent's persona."""
        try:
            response = self.ollama.chat.completions.create(
                model=OLLAMA_CHAT_MODEL,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("[%s] LLM generation failed: %s", self.agent_name, e)
            return ""

    def send_reply(self, message: str, user_id: str = "",
                   conversation_id: str = "", depth: int = 0) -> None:
        """Post a reply back to the backend chat timeline.

        Args:
            message: The reply text.
            user_id: Target user this reply is for (from SSE event envelope).
            conversation_id: Conversation this reply belongs to.
            depth: Inter-agent depth counter.  0 = direct reply to user,
                   1 = reply to another agent's reply, etc.
        """
        if not message:
            return
        try:
            requests.post(
                f"{BACKEND_URL}/api/external_agent_reply",
                json={
                    "agent_name": self.agent_name,
                    "message": message,
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "depth": depth,
                },
                timeout=5,
            )
            logger.info("[%s] Reply sent (user=%s, conv=%s, depth=%d)",
                        self.agent_name, user_id, conversation_id, depth)
        except requests.exceptions.ConnectionError:
            logger.warning("[%s] Failed to send reply to backend", self.agent_name)

    # --- SSE listener ---

    def listen(self) -> None:
        """Connect to SSE stream and dispatch filtered events. Reconnects on failure."""
        url = f"{BACKEND_URL}/api/sse/events"
        self._running = True
        logger.info("[%s] Connecting to SSE at %s", self.agent_name, url)

        while self._running:
            try:
                with requests.get(url, stream=True, timeout=None) as response:
                    logger.info("[%s] SSE connected", self.agent_name)
                    for line in response.iter_lines():
                        if not self._running:
                            break
                        if not line:
                            continue
                        decoded = line.decode("utf-8")
                        if not decoded.startswith("data:"):
                            continue

                        try:
                            data = json.loads(decoded.replace("data: ", "", 1))
                        except json.JSONDecodeError:
                            continue

                        # --- Inter-agent collaboration routing ---
                        if data.get("type") == "AGENT_REPLY":
                            self._dispatch_agent_reply(data)
                            continue

                        # --- Standard event routing ---
                        if self.event_filter(data):
                            logger.info("[%s] Handling event: %s", self.agent_name, data.get("type"))
                            try:
                                self.handle_event(data)
                            except Exception as e:
                                logger.error("[%s] Error handling event: %s", self.agent_name, e)

            except requests.exceptions.ConnectionError:
                logger.warning("[%s] SSE disconnected, retrying in %ds", self.agent_name, self.RECONNECT_DELAY)
                time.sleep(self.RECONNECT_DELAY)
            except Exception as e:
                logger.warning("[%s] Unexpected error: %s, retrying in %ds", self.agent_name, e, self.RECONNECT_DELAY)
                time.sleep(self.RECONNECT_DELAY)

    def _dispatch_agent_reply(self, data: dict) -> None:
        """Route an AGENT_REPLY event through inter-agent safeguards.

        Safeguards:
        1. Self-ignore: never react to your own replies.
        2. Depth limit: refuse if depth >= MAX_AGENT_DEPTH.
        3. Opt-in gate: only dispatch if agent_reply_filter() returns True.
        4. Thinking delay: random pause to simulate natural conversation pacing.
        """
        sender = data.get("sender", "")

        # 1. Never respond to yourself
        if sender == self.agent_name:
            return

        # 2. Enforce depth limit
        depth = data.get("depth", 0)
        if depth >= MAX_AGENT_DEPTH:
            logger.debug("[%s] Ignoring AGENT_REPLY from %s (depth %d >= %d)",
                         self.agent_name, sender, depth, MAX_AGENT_DEPTH)
            return

        # 3. Opt-in filter
        if not self.agent_reply_filter(data):
            return

        # 4. Thinking delay — prevents instant agent flood
        delay = random.uniform(*AGENT_REPLY_DELAY)
        logger.info("[%s] Reacting to %s's reply (depth %d) after %.1fs delay",
                    self.agent_name, sender, depth, delay)
        time.sleep(delay)

        try:
            self.handle_agent_reply(data)
        except Exception as e:
            logger.error("[%s] Error handling agent reply: %s", self.agent_name, e)

    def stop(self) -> None:
        """Signal the listener to stop."""
        self._running = False

    def start_in_thread(self) -> threading.Thread:
        """Launch this agent's SSE listener in a daemon thread."""
        t = threading.Thread(target=self.listen, name=f"agent-{self.agent_name}", daemon=True)
        t.start()
        return t

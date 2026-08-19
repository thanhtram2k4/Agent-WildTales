# agents/run_all.py — Launch all persona agents concurrently
"""
Usage:
    python -m agents.run_all

Starts all four WildTails persona agents as daemon threads listening
to the SSE event stream with deterministic routing.
"""
import logging
import signal
import sys
import time

from agents.memory_keeper import MemoryKeeperAgent
from agents.discipline_boss import DisciplineBossAgent
from agents.gamemaster import GamemasterAgent
from agents.event_matcher import EventMatcherAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("wildtails.agents.runner")


def main():
    agents = [
        MemoryKeeperAgent(),
        DisciplineBossAgent(),
        GamemasterAgent(),
        EventMatcherAgent(),
    ]

    threads = []
    for agent in agents:
        logger.info("Starting agent: %s", agent.agent_name)
        t = agent.start_in_thread()
        threads.append((agent, t))

    logger.info("All %d agents started. Press Ctrl+C to stop.", len(agents))

    # Graceful shutdown on SIGINT/SIGTERM
    def shutdown(sig, frame):
        logger.info("Shutting down all agents...")
        for agent, _ in threads:
            agent.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Keep main thread alive
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()

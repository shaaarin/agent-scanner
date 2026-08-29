import os

from sqlmodel import Session

from app.db import engine

DEMO_SESSION_ID = os.environ.get("DEMO_SESSION_ID", "demo-session-1")


def seed_demo_data() -> None:
    """Seed demo data into the database."""
    # Currently no demo data needed for the new architecture
    # Scan, AgentConfig, and LLMModel are created by users via API
    pass

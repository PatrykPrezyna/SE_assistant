"""Local SE assistant: a chat page, a swappable model provider, and activity tools."""

from .agent import GREETING, opening_text, run_turn
from .config import Settings, load_settings

__all__ = [
    "GREETING",
    "Settings",
    "load_settings",
    "opening_text",
    "run_turn",
]

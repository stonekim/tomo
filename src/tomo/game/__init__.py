"""Tomo's explicitly fictional, event-sourced alternative-life game."""
from .api import router
from .engine import register_game_rules

__all__ = ['router', 'register_game_rules']

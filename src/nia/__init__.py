"""
src/nia — Nia's core package.

Nia is the central strategic agent.  Channels (Telegram, Email, Teams…)
are adapters that feed input to Nia and deliver her output back to users.
"""
from src.nia.agent import NiaAgent, DispatchResult, NiaConfig

__all__ = ["NiaAgent", "DispatchResult", "NiaConfig"]

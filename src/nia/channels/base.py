"""
ChannelAdapter — Abstract Base Class for all channel integrations.

A channel is anything that can deliver input to Nia and receive output:
Telegram, Email, Teams, Slack, CLI, etc.

Every concrete adapter must implement:
  start()  — begin accepting/delivering messages
  stop()   — graceful shutdown
  send()   — deliver a message to a user/chat
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class InlineButton:
    """A single button in an inline keyboard / action row."""
    label: str
    callback_data: str   # Opaque string passed back when user taps the button


@dataclass
class ChannelConfig:
    """
    Generic channel configuration.

    Concrete channels extend this with their own fields.
    The minimum required fields are defined here so the base class can
    reference them without knowing the concrete type.
    """
    enabled: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(ABC):
    """
    Abstract base for all channel adapters.

    Parameters
    ----------
    config:
        Channel-specific configuration object.
    nia:
        NiaAgent instance — the brain that processes input.
    """

    def __init__(self, config: ChannelConfig, nia: Any) -> None:
        self.config = config
        self.nia = nia

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def start(self) -> None:
        """Start the channel (open connection, start polling, etc.)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the channel."""
        ...

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    @abstractmethod
    async def send(
        self,
        user_id: str,
        message: str,
        parse_mode: Optional[str] = None,
    ) -> None:
        """Send a plain text / markdown message to a user or chat."""
        ...

    async def send_with_buttons(
        self,
        user_id: str,
        message: str,
        buttons: List[Tuple[str, str]],
        parse_mode: Optional[str] = None,
    ) -> None:
        """
        Send a message with inline action buttons.

        Default implementation falls back to plain send() (no buttons).
        Override in channels that support interactive buttons.

        Parameters
        ----------
        user_id:
            Destination user or chat identifier.
        message:
            Text body of the message.
        buttons:
            List of (label, callback_data) tuples.
        parse_mode:
            Optional parse mode, e.g. "Markdown".
        """
        # Fallback: append button labels as plain text options
        options_text = "\n".join(f"  • {label}" for label, _ in buttons)
        await self.send(user_id, f"{message}\n\n{options_text}", parse_mode=parse_mode)

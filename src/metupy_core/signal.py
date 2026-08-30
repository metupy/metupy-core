"""
metupy_core.signal
~~~~~~~~~~~~~~

Event signaling system for Metupy.
Provides hooks for plugins and core lifecycle events.
Uses blinker if available, otherwise falls back to simple implementation.

Available signals:
    - before_build       → Before build process starts
    - after_build        → After build completes successfully
    - before_page_render → Before rendering a single page
    - after_page_render  → After rendering a single page
    - file_created       → When a new file is created
    - file_changed       → When a content file is modified
    - file_deleted       → When a content file is deleted
    - server_start       → When dev server starts
    - server_stop        → When dev server stops

Usage:
    from metupy_core.signal import on, emit

    @on("before_build")
    def my_hook(**kwargs):
        print("Building will start...")
"""

import sys
from typing import Any, Callable, Dict, List, Optional, Set
from dataclasses import dataclass, field

from .logging import log


__all__ = [
    "Signal",
    "SignalManager",
    "on",
    "off",
    "emit",
    "connect",
    "disconnect",
    "list_signals",
    "reset",
]


# ─── Detect Blinker ───

try:
    from blinker import Signal as BlinkerSignal
    _BLINKER_AVAILABLE = True
except ImportError:
    BlinkerSignal = None
    _BLINKER_AVAILABLE = False
    log.debug("blinker not installed, using built-in signal system")


# ─── Signal Implementation ───

class Signal:
    """
    A single event signal that listeners can subscribe to.
    Wraps blinker when available, uses simple dict-based fallback otherwise.
    """

    def __init__(self, name: str):
        self.name = name
        self._listeners: Set[Callable] = set()
        self._blinker_signal = BlinkerSignal() if _BLINKER_AVAILABLE else None

    def connect(self, receiver: Callable, weak: bool = False) -> None:
        """Register a function to be called when this signal is emitted."""
        if receiver in self._listeners:
            log.debug(f"Listener already connected to signal '{self.name}'")
            return

        if self._blinker_signal is not None:
            self._blinker_signal.connect(receiver, weak=weak)
        else:
            self._listeners.add(receiver)

        log.debug(f"Listener connected to signal '{self.name}'")

    def disconnect(self, receiver: Callable) -> None:
        """Remove a function from this signal's listeners."""
        if self._blinker_signal is not None:
            self._blinker_signal.disconnect(receiver)
        else:
            self._listeners.discard(receiver)
        log.debug(f"Listener disconnected from signal '{self.name}'")

    def emit(self, **kwargs: Any) -> int:
        """
        Emit this signal — call all listeners with provided keyword arguments.
        Returns number of listeners successfully called.
        """
        count = 0

        if self._blinker_signal is not None:
            for receiver in list(self._blinker_signal.receivers):
                try:
                    receiver(**kwargs)
                    count += 1
                except Exception as e:
                    log.error(f"Error in signal listener for '{self.name}': {e}")
            return count

        # Fallback: built-in implementation
        for receiver in list(self._listeners):
            try:
                receiver(**kwargs)
                count += 1
            except Exception as e:
                log.error(f"Error in signal listener for '{self.name}': {e}")

        return count

    def clear(self) -> None:
        """Remove all listeners from this signal."""
        self._listeners.clear()
        if self._blinker_signal is not None:
            self._blinker_signal.receivers.clear()

    def __len__(self) -> int:
        """Return number of connected listeners."""
        if self._blinker_signal is not None:
            return len(self._blinker_signal.receivers)
        return len(self._listeners)


# ─── Signal Manager ───

class SignalManager:
    """
    Central registry for all available signals.
    Provides global connect/disconnect/emit interface.
    """

    _signals: Dict[str, Signal] = {}

    # Standard Metupy built-in signals
    _BUILTIN_SIGNALS = {
        "before_build": "Emitted before build process begins",
        "after_build": "Emitted after build completes successfully",
        "before_page_render": "Emitted before rendering a single page",
        "after_page_render": "Emitted after rendering a single page",
        "file_created": "Emitted when a new content file is detected",
        "file_changed": "Emitted when a content file is modified",
        "file_deleted": "Emitted when a content file is removed",
        "server_start": "Emitted when development server starts",
        "server_stop": "Emitted when development server stops",
    }

    @classmethod
    def _register_builtins(cls) -> None:
        """Register all built-in signals on first access."""
        if not cls._signals:
            for name in cls._BUILTIN_SIGNALS:
                cls._signals[name] = Signal(name)

    @classmethod
    def get_signal(cls, name: str) -> Optional[Signal]:
        """Get signal object by name."""
        cls._register_builtins()
        return cls._signals.get(name)

    @classmethod
    def connect(cls, signal_name: str, receiver: Callable) -> None:
        """Connect a listener function to a signal."""
        cls._register_builtins()
        signal = cls.get_signal(signal_name)
        if not signal:
            log.warning(f"Signal '{signal_name}' does not exist")
            return
        signal.connect(receiver)

    @classmethod
    def disconnect(cls, signal_name: str, receiver: Callable) -> None:
        """Disconnect a listener from a signal."""
        signal = cls.get_signal(signal_name)
        if signal:
            signal.disconnect(receiver)

    @classmethod
    def emit(cls, signal_name: str, **kwargs: Any) -> int:
        """Emit a signal — trigger all listeners."""
        signal = cls.get_signal(signal_name)
        if not signal:
            log.warning(f"Cannot emit: signal '{signal_name}' not found")
            return 0
        return signal.emit(**kwargs)

    @classmethod
    def list_all(cls) -> Dict[str, str]:
        """Return all available signal names and descriptions."""
        cls._register_builtins()
        return dict(cls._BUILTIN_SIGNALS)

    @classmethod
    def reset(cls) -> None:
        """Clear all signal listeners (for testing/reload)."""
        for signal in cls._signals.values():
            signal.clear()
        log.debug("All signals reset")


# ─── Decorator API ───

def on(signal_name: str) -> Callable:
    """
    Decorator to register a signal listener.

    Example:
        from metupy.signals import on

        @on("before_build")
        def backup_before_build(**kwargs):
            print("Running backup before build...")
    """
    def decorator(func: Callable) -> Callable:
        SignalManager.connect(signal_name, func)
        return func
    return decorator


# ─── Shortcut Functions ───

def connect(signal_name: str, receiver: Callable) -> None:
    """Connect a function to a signal."""
    SignalManager.connect(signal_name, receiver)


def disconnect(signal_name: str, receiver: Callable) -> None:
    """Disconnect a function from a signal."""
    SignalManager.disconnect(signal_name, receiver)


def emit(signal_name: str, **kwargs: Any) -> int:
    """Emit a signal with optional data."""
    return SignalManager.emit(signal_name, **kwargs)


def off(signal_name: str, receiver: Callable) -> None:
    """Alias for disconnect()."""
    SignalManager.disconnect(signal_name, receiver)


def list_signals() -> Dict[str, str]:
    """List all available signals with descriptions."""
    return SignalManager.list_all()


def reset() -> None:
    """Reset all signal listeners."""
    SignalManager.reset()

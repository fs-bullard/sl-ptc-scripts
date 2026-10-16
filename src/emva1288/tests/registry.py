"""Registry of available test scripts."""

from __future__ import annotations

from .base import TestScript


class UnknownTestError(Exception):
    """No test script by that name."""


_REGISTRY: dict[str, type[TestScript]] = {}


def register(cls: type[TestScript]) -> type[TestScript]:
    """Class decorator adding a test script to the registry."""
    _REGISTRY[cls.name] = cls
    return cls


def get_test(name: str) -> TestScript:
    """Instantiate a registered test script by name."""
    _load_builtins()
    if name not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "none"
        raise UnknownTestError(f"Unknown test {name!r}. Available: {available}")
    return _REGISTRY[name]()


def available_tests() -> dict[str, type[TestScript]]:
    _load_builtins()
    return dict(_REGISTRY)


def _load_builtins() -> None:
    """Import modules that self-register, on first use."""
    from . import ptc  # noqa: F401

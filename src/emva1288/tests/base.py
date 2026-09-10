"""Test script interface.

Each EMVA 1288 measurement is a TestScript: it acquires a session, analyses one
into results, and contributes sections to the report. Adding a new measurement
(dark current, linearity, PRNU/DSNU) means one new module plus a registry entry
-- no changes to the CLI, preferences, storage or report scaffolding.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from ..camera.base import CameraDriver
from ..io.session import Session
from ..prefs import Preferences

#: Callback used to ask the operator to change the illumination. Takes a
#: prompt string, returns nothing. Injected so capture is testable headlessly.
PromptFn = Callable[[str], None]


class TestScript(ABC):
    """One EMVA 1288 measurement."""

    #: Identifier used on the CLI and in the registry.
    name: str = "base"

    #: One-line description shown by `emva1288 tests`.
    description: str = ""

    @abstractmethod
    def acquire(
        self,
        driver: CameraDriver,
        prefs: Preferences,
        options: dict[str, Any],
        prompt: PromptFn,
    ) -> Session:
        """Run the acquisition, returning the completed session."""

    @abstractmethod
    def analyse(self, session: Session, prefs: Preferences, options: dict[str, Any]) -> Any:
        """Compute results from a session's stored frames."""

    @abstractmethod
    def write_outputs(self, session: Session, results: Any, prefs: Preferences) -> list:
        """Write CSV and plots, returning the paths produced."""

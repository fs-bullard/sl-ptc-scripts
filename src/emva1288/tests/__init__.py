"""Library of EMVA 1288 test scripts."""

from .base import TestScript
from .registry import available_tests, get_test, register

__all__ = ["TestScript", "available_tests", "get_test", "register"]

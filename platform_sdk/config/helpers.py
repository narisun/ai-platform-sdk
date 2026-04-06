"""
Typed environment variable readers with defaults.

This module provides helper functions for reading environment variables
with automatic type coercion and sensible defaults. All config classes
use these functions to initialize from the environment.
"""
import os


def _env(name: str, default: str) -> str:
    """Read a string environment variable with a default fallback."""
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a default fallback."""
    return int(os.environ.get(name, str(default)))


def _env_float(name: str, default: float) -> float:
    """Read a float environment variable with a default fallback."""
    return float(os.environ.get(name, str(default)))


def _env_bool(name: str, default: bool = True) -> bool:
    """Read a boolean environment variable with a default fallback."""
    return os.environ.get(name, str(default).lower()).lower() == "true"

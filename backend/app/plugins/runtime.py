"""Runtime context handed to plugin instances during pipeline execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunContext:
    client_id: int
    feed_source_id: int
    run_id: int
    logger: logging.Logger
    original_product: dict[str, Any]

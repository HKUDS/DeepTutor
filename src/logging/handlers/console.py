# -*- coding: utf-8 -*-
"""
Console Log Handler
===================

Color-coded console output with standard level tags.
"""

import logging
import sys
from typing import Optional

# Import ConsoleFormatter from the main logger module to avoid duplication
from ..logger import ConsoleFormatter


class ConsoleHandler(logging.StreamHandler):
    """
    Console handler with color-coded output.
    """

    def __init__(self, level: int = logging.INFO, service_prefix: Optional[str] = None):
        """
        Initialize console handler.

        Args:
            level: Minimum log level to display
            service_prefix: Optional service layer prefix (e.g., "Backend", "Frontend")
        """
        super().__init__(sys.stdout)
        self.setLevel(level)
        self.setFormatter(ConsoleFormatter(service_prefix=service_prefix))

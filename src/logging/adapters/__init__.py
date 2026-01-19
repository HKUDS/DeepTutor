# -*- coding: utf-8 -*-
"""
Log Adapters
============

Adapters for forwarding logs from external libraries to the unified logging system.
"""

from .lightrag import LightRAGLogContext, LightRAGLogForwarder, get_lightrag_forwarding_config
from .llamaindex import LlamaIndexLogContext, LlamaIndexLogForwarder

__all__ = [
    "LightRAGLogContext",
    "LightRAGLogForwarder",
    "get_lightrag_forwarding_config",
    "LlamaIndexLogContext",
    "LlamaIndexLogForwarder",
]

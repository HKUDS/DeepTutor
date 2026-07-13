"""Chat channels module with plugin architecture."""

from deeptutor.partners.channels.base import BaseChannel
from deeptutor.partners.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]

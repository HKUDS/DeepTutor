"""Single source of truth for the DeepTutor version.

To cut a release, bump ``__version__`` here, commit, and tag the commit with
``v<__version__>`` (e.g. ``v1.4.0``). CI verifies the tag matches this value
before publishing to PyPI; the web sidebar badge and CLI banner read from this
file directly.
"""

__version__ = "1.5.1"

__all__ = ("__version__",)

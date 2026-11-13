"""Independent QTI 2.1/2.2 item-bank dialects."""

from .profile import DIALECTS, PACKAGE_NS
from .xml import validate_xml

__all__ = ["DIALECTS", "PACKAGE_NS", "validate_xml"]

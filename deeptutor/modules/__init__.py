"""Import-free module discovery and deployment-scoped feature selection."""

from .catalog import ModuleUnavailable, module_enabled, module_for_path, module_statuses

__all__ = ["ModuleUnavailable", "module_enabled", "module_for_path", "module_statuses"]

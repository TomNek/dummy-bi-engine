from __future__ import annotations


class ProjectFormatError(ValueError):
    """Raised when the on-disk project format is invalid."""


class ProjectValidationError(ValueError):
    """Raised when references in the project do not validate against the model."""


class NotFoundError(ValueError):
    """Raised when a named resource (environment, folder, pipeline, etc.) does not exist."""

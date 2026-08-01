# ================================================
# CUSTOM EXCEPTIONS
# ================================================

class ConfigError(Exception):
    """
    Base exception for all configuration ingestion failures.
    """
    pass

class ConfigNotFoundError(ConfigError):
    """
    Raised when the target YAML file does not exist on disk.
    """
    pass

class InvalidSchemaError(ConfigError):
    """
    Raised when YAML structure fails Pydantic type validation or parsing.
    """
    pass

class DimensionalMismatchError(ConfigError):
    """
    Raised when state bounds/drift rates do not match defined metric keys
    """
    pass

class InitialBoundsError(ConfigError):
    """
    Raised when an entity's intial_metrics lie outside its state or metric bounds
    """
    pass
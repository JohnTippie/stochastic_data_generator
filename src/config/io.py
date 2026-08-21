import logging
import os
from pathlib import Path
import yaml
from .exceptions import ConfigNotFoundError, InvalidSchemaError

logger = logging.getLogger(__name__)


def read_yaml_file(config_path: Path | str) -> dict:
    """
    Reads a YAML file from disk and parses it into a raw dictionary mapping.
    """
    path = Path(config_path) if isinstance(config_path, str) else config_path

    try:
        logger.debug(f"Attempting to read configuration from {path}")
        """ CWE-776 """
        MAX_CONFIG_SIZE_BYTES = 10 * 1024 * 1024
        if path.stat().st_size > MAX_CONFIG_SIZE_BYTES:
            raise InvalidSchemaError("Configuration file exceeds maximum allowed size of 10 MB")
        with open(path, "r", encoding="utf-8") as f:
            raw_data = yaml.safe_load(f)
    except FileNotFoundError as e:
        logger.critical(f"Config file not found at: {path}")
        raise ConfigNotFoundError(f"Config file not found at: {path}") from e
    except (PermissionError, OSError) as e:
        logger.critical(f"OS/Access error reading config file at {path}: {e}")
        raise ConfigNotFoundError(f"Unreadable or inaccessible config file at {path}: {e}") from e
    except (yaml.YAMLError, UnicodeDecodeError) as e:
        logger.critical(f"Parsing or encoding error in config file {path}: {e}")
        raise InvalidSchemaError(f"YAML parsing/decoding error in {path}: {e}") from e

    if not isinstance(raw_data, dict) or not raw_data:
        raise InvalidSchemaError(f"Root configuration in {path} must be a non-empty mapping.")

    return raw_data
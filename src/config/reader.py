import logging
from pathlib import Path
from pydantic import ValidationError

from .exceptions import InvalidSchemaError
from .invariants import validate_domain_invariants
from .io import read_yaml_file
from .schemas import SimulationConfig

logger = logging.getLogger(__name__)

def load_config(config_path: Path | str) -> SimulationConfig:
    """Parses a YAML configuration file into a frozen SimulationConfig object hierarchy."""
    raw_data = read_yaml_file(config_path)

    logger.debug("YAML parsed cleanly. Validating Pydantic schema...")
    try:
        config = SimulationConfig.model_validate(raw_data)
    except ValidationError as e:
        logger.critical("Pydantic Schema validation failed!")
        raise InvalidSchemaError(f"Config schema validation failed:\n{e}") from e

    logger.debug("Executing semantic cross-field invariant checks...")
    validate_domain_invariants(config)

    logger.info(
        f"Config parsed successfully: {len(config.metrics)} metrics, "
        f"{len(config.entities)} entities, "
        f"use_state_engine={config.pipeline_toggles.use_state_engine}"
    )
    return config

class ConfigReader:
    """Backwards-compatible wrapper delegating to functional load_config."""

    @classmethod
    def load_config(cls, config_path: Path | str) -> SimulationConfig:
        return load_config(config_path)
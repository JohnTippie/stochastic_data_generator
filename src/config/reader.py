from pathlib import Path
import logging
from pydantic import ValidationError
from .schemas import SimulationConfig
from .exceptions import InvalidSchemaError
from .io import read_yaml_file
from .formulas import validate_derivative_metric_formulas
from .invariants import validate_domain_invariants

logger = logging.getLogger(__name__)


def load_config(config_path: Path | str) -> SimulationConfig:
    """
    Parses a YAML configuration file into a frozen SimulationConfig object hierarchy.
    """
    raw_data = read_yaml_file(config_path)

    logger.debug("YAML parsed cleanly. Validating Pydantic schema...")
    try:
        config = SimulationConfig(**raw_data)
    except ValidationError as e:
        logger.critical("Pydantic Schema validation failed!")
        raise InvalidSchemaError(f"Config schema validation failed: {e}") from e

    logger.debug("Executing AST formula checks...")
    validate_derivative_metric_formulas(config.metrics)

    logger.debug("Executing semantic cross-field invariant checks...")
    validate_domain_invariants(config)

    logger.info(
        f"Config parsed successfully: {len(config.metrics)} metrics, "
        f"{len(config.entities)} entities, "
        f"state_engine={config.toggles.enable_state_engine}"
    )
    return config


class ConfigReader:
    """Backwards-compatible wrapper delegating to functional load_config."""

    @classmethod
    def load_config(cls, config_path: Path | str) -> SimulationConfig:
        return load_config(config_path)
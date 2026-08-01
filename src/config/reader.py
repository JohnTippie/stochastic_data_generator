from pathlib import Path
import logging
import yaml
from pydantic import ValidationError
from typing import Iterable
from .schemas import SimulationConfig
from .exceptions import (
    ConfigError,
    ConfigNotFoundError,
    DimensionalMismatchError,
    InitialBoundsError,
    InvalidSchemaError
)

# ================================================
# CONFIG READER & VALIDATOR
# ================================================

logger = logging.getLogger(__name__)

class ConfigReader:

    @classmethod
    def load_config(cls, config_path: Path | str) -> SimulationConfig:
        """
        Parses a YAML configuration file into a frozen SimulationConfig object hierarchy.

        Args:
            config_path: Path to target YAML configurations file.

        Returns:
            SimulationConfig: Immutable, fully validated configuration object graph.

        Raises:
            ConfigNotFoundError: If file path is invalid or unreadable.
            InvalidSchemaError: If YAML fails Pydantic schema verification.
            DimensionalMismatchError: If metric keys across states/metrics disagree.
            InitialBoundsError: If initial entity coordinates lie outside bounding boxes.
        """

        path = Path(config_path) if isinstance(config_path, str) else config_path
        logger.debug(f"Attempting to read configuration from {path.resolve()}.")

        if not path.is_file():
            logger.critical("Config file not found!")
            raise ConfigNotFoundError(f"Config file not found at: {path}")

        try:
            with open(path, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            logger.critical("YAML parsing failed!")
            raise InvalidSchemaError(f"YAML parsing error in {path}: {e}") from e

        if not isinstance(raw_data, dict) or not raw_data:
            raise InvalidSchemaError(f"Root configuration in {path} must be a non-empty mapping.")

        logger.debug("YAML parsed cleanly. Validating Pydantic schema...")
        try:
            config = SimulationConfig(**raw_data)
        except ValidationError as e:
            logger.critical("Pydantic Schema validation failed!")
            raise InvalidSchemaError(f"Config schema validation failed: {e}") from e

        logger.debug("Executing semantic cross-field invariant checks...")
        cls._validate_unique_metric_names(config)
        cls._validate_toggle_data_alignment(config)
        cls._validate_dimensional_alignment(config)
        cls._validate_macro_shocks(config)
        cls._validate_initial_coordinates(config)

        logger.info(
            f"Config parsed successfully: {len(config.metrics)} metrics, "
            f"{len(config.entities)} entities, "
            f"state_engine={config.toggles.enable_state_engine}"
        )
        return config

    @classmethod
    def _validate_unique_metric_names(cls, config: SimulationConfig) -> None:
        """
        Ensures top-level metric manifest contains no duplicate names
        """
        seen_names: set[str] = set()
        for metric in config.metrics:
            if metric.name in seen_names:
                raise InvalidSchemaError(f"Duplicate metric definition found for key '{metric.name}'. Metric names must be unique.")
            seen_names.add(metric.name)

    @classmethod
    def _validate_dimensional_alignment(cls, config: SimulationConfig) -> None:
        """
        Ensures all metric keys used across states, limits, and entities match the top-level metrics manifest exactly.
        """

        valid_metric_names = {m.name for m in config.metrics}

        # Validate global_limits
        if config.global_limits:
            for key in config.global_limits.keys():
                if key not in valid_metric_names:
                    raise DimensionalMismatchError(f"Global limit references unknown metric key: '{key}'")

        # Validate global behavior states
        for state in config.global_behavior_states:
            cls._check_metric_keys_subset(
                state.state_bounds.keys(), valid_metric_names, f"state_bounds in '{state.name}'"
            )
            cls._check_metric_keys_subset(
                state.drift_rates.keys(), valid_metric_names, f"drift_rates in '{state.name}'"
            )
            cls._check_metric_keys_subset(
                state.volatilities.keys(), valid_metric_names, f"volatilities in '{state.name}"
            )

        # Validate entities
        for entity in config.entities:
            cls._check_metric_keys_subset(
                entity.initial_metrics.keys(), valid_metric_names, f"initial_metrics in entity '{entity.id}'"
            )

            if entity.metric_bounds:
                cls._check_metric_keys_subset(
                    entity.metric_bounds.keys(), valid_metric_names, f"metric_bounds in entity '{entity.id}'"
                )

            if entity.behavior_states:
                for b_state in entity.behavior_states:
                    cls._check_metric_keys_subset(
                        b_state.state_bounds.keys(), valid_metric_names, f"state_bounds in custom state '{b_state.name}' for entity {entity.id}"
                    )

            if entity.deferral_policy and entity.deferral_policy.enabled:
                driver = entity.deferral_policy.driver_metric
                if driver and driver not in valid_metric_names:
                    raise DimensionalMismatchError(f"Deferral policy driver_metric '{driver}' in entity '{entity.id}' "
                                                   f"does not exist in top-level metrics manifest.")

    @classmethod
    def _validate_macro_shocks(cls, config: SimulationConfig) -> None:
        """
        Ensure target_state in macro shocks references a declared state name.
        """
        global_state_names = {s.name for s in config.global_behavior_states}

        # Validate global macro shocks
        for shock in config.global_macro_shocks:
            if shock.target_state and shock.target_state not in global_state_names:
                raise InvalidSchemaError(
                    f"Global macro shock '{shock.name}' references target_state '{shock.target_state}' "
                    f"which does not exist in global_behavior_states."
                )

        # Validate entity custom macro shocks
        for entity in config.entities:
            entity_state_names = (
                {s.name for s in entity.behavior_states}
                if (not config.toggles.use_global_behavior and entity.behavior_states)
                else global_state_names
            )
            shocks = (
                entity.macro_shocks
                if (not config.toggles.use_global_macro_shock and entity.macro_shocks)
                else []
            )

            for shock in shocks:
                if shock.target_state and shock.target_state not in entity_state_names:
                    raise InvalidSchemaError(
                        f"Macro shock '{shock.name}' in entity '{entity.id}' references target_state "
                        f"'{shock.target_state}' which does not exist in active states."
                    )

    @classmethod
    def _check_metric_keys_subset(
        cls,
        keys: Iterable[str],
        valid_names: set[str],
        context: str 
    ) -> None:
        """
        Helper asserting every key in 'keys' exists in valid_names.
        """

        for key in keys:
            if key not in valid_names:
                raise DimensionalMismatchError(f"Unrecognized metric key '{key}' found in {context}")

    @classmethod
    def _validate_initial_coordinates(cls, config: SimulationConfig) -> None:
        """
        Asserts initial_metrics coordinates lie strictly inside initial_state bounds and metric_bounds / global_limits
        """

        for entity in config.entities:
            # Resolve effective safety limits
            effective_limits = entity.metric_bounds or config.global_limits or {}

            # Resolve active behavior states for entity
            states = (
                entity.behavior_states
                if (not config.toggles.use_global_behavior and entity.behavior_states)
                else config.global_behavior_states
            )

            matching_state = None
            if entity.initial_state and states:
                matching_state = next((s for s in states if s.name == entity.initial_state), None)
                if not matching_state:
                    raise InitialBoundsError(
                        f"Entity '{entity.id}' initial_state '{entity.initial_state}' "
                        f"does not exist in defined states."
                    )

            # Validate each metric coordinate
            for metric_name, val in entity.initial_metrics.items():
                # 1. State Bounds Check (if state engine and matching initial state exist)
                if matching_state and metric_name in matching_state.state_bounds:
                    min_b, max_b = matching_state.state_bounds[metric_name]
                    if not (min_b <= val <= max_b):
                        raise InitialBoundsError(
                            f"Entity '{entity.id}' initial metric '{metric_name}' value {val} "
                            f"lies outside state '{matching_state.name}' bounds [{min_b}, {max_b}]."
                        )

                # 2. Safety Rail Limits Check
                if metric_name in effective_limits:
                    min_l, max_l = effective_limits[metric_name]
                    if not (min_l <= val <= max_l):
                        raise InitialBoundsError(
                            f"Entity '{entity.id}' initial metric '{metric_name}' value {val} "
                            f"lies outside safety limits [{min_l}, {max_l}]."
                        )

    @classmethod
    def _validate_toggle_data_alignment(cls, config: SimulationConfig) -> None:
        """
        Enforces that enabled toggles have their corresponding data structures populated.
        """
        # 1. Global Behavior Toggle vs Data Check
        if config.toggles.use_global_behavior and not config.global_behavior_states:
            raise InvalidSchemaError(
                "Toggle 'use_global_behavior' is True, but 'global_behavior_states' is empty or missing."
            )

        # 2. Global Macro Shock Toggle vs Data Check
        if config.toggles.use_global_macro_shock and not config.global_macro_shocks:
            raise InvalidSchemaError(
                "Toggle 'use_global_macro_shock' is True, but 'global_macro_shocks' is empty or missing."
            )

        # 3. Global Limits Toggle vs Data Check
        if config.toggles.use_global_limits and not config.global_limits:
            raise InvalidSchemaError(
                "Toggle 'use_global_limits' is True, but 'global_limits' is empty or missing."
            )
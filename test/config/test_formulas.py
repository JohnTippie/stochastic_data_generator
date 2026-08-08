from pathlib import Path
import pytest
from src.config.reader import load_config
from src.config.exceptions import InvalidSchemaError
from conftest import write_yaml


def test_derivative_metric_valid_formula_passes(valid_config_dict: dict, tmp_path: Path):
    """Verifies that a valid derivative metric with AST formula loads cleanly."""
    valid_config_dict["metrics"].append({
        "name": "derived_ratio",
        "is_derivative": True,
        "primitive_type": "float",
        "formula": "metric_1 / (metric_2 + 1.0) + abs(metric_1)",
    })
    config_file = write_yaml(valid_config_dict, tmp_path)
    config = load_config(config_file)
    assert len(config.metrics) == 3


def test_derivative_metric_missing_formula_rejected(valid_config_dict: dict, tmp_path: Path):
    """Verifies that is_derivative=True without a formula raises InvalidSchemaError."""
    valid_config_dict["metrics"].append({
        "name": "derived_missing",
        "is_derivative": True,
        "primitive_type": "float",
    })
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="no formula was provided"):
        load_config(config_file)


def test_derivative_metric_formula_unknown_variable_rejected(valid_config_dict: dict, tmp_path: Path):
    """Verifies that formulas referencing non-existent metrics raise InvalidSchemaError."""
    valid_config_dict["metrics"].append({
        "name": "derived_bad_var",
        "is_derivative": True,
        "primitive_type": "float",
        "formula": "metric_1 + ghost_metric",
    })
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="references unknown metric variable"):
        load_config(config_file)


def test_derivative_metric_unsafe_syntax_rejected(valid_config_dict: dict, tmp_path: Path):
    """Verifies that unsafe/disallowed AST nodes or functions raise InvalidSchemaError."""
    valid_config_dict["metrics"].append({
        "name": "derived_unsafe",
        "is_derivative": True,
        "primitive_type": "float",
        "formula": "__import__('os').system('echo hack')",
    })
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError):
        load_config(config_file)


def test_derivative_metric_circular_dependency_rejected(valid_config_dict: dict, tmp_path: Path):
    """Verifies that circular dependencies among derivative metrics raise InvalidSchemaError."""
    valid_config_dict["metrics"].extend([
        {
            "name": "d1",
            "is_derivative": True,
            "primitive_type": "float",
            "formula": "d2 + 1.0",
        },
        {
            "name": "d2",
            "is_derivative": True,
            "primitive_type": "float",
            "formula": "d1 * 2.0",
        },
    ])
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="Circular dependency detected"):
        load_config(config_file)
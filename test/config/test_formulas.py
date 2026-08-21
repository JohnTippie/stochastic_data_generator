from pathlib import Path
import pytest
from src.config.reader import load_config
from src.config.exceptions import InvalidSchemaError
from conftest import write_yaml

def test_derivative_metric_valid_formula_passes(valid_config_dict: dict, tmp_path: Path):
    m1 = valid_config_dict["metrics"][0]["name"]
    m2 = valid_config_dict["metrics"][1]["name"]

    valid_config_dict["metrics"].append({
        "name": "derived_ratio",
        "is_derivative": True,
        "primitive_type": "float",
        "formula": f"{m1} / ({m2} + 1.0) + abs({m1})",
    })
    config_file = write_yaml(valid_config_dict, tmp_path)
    config = load_config(config_file)
    assert any(m.name == "derived_ratio" for m in config.metrics)

def test_derivative_metric_clamp_function_supported(valid_config_dict: dict, tmp_path: Path):
    m1 = valid_config_dict["metrics"][0]["name"]

    valid_config_dict["metrics"].append({
        "name": "clamped_metric",
        "is_derivative": True,
        "primitive_type": "float",
        "formula": f"clamp({m1}, 1.0, 120.0)",
    })
    config_file = write_yaml(valid_config_dict, tmp_path)
    config = load_config(config_file)
    assert any(m.name == "clamped_metric" for m in config.metrics)

def test_derivative_metric_missing_formula_rejected(valid_config_dict: dict, tmp_path: Path):
    valid_config_dict["metrics"].append({
        "name": "derived_missing",
        "is_derivative": True,
        "primitive_type": "float",
    })
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="no formula was provided"):
        load_config(config_file)

def test_non_derivative_metric_with_formula_rejected(valid_config_dict: dict, tmp_path: Path):
    valid_config_dict["metrics"].append({
        "name": "non_deriv_with_formula",
        "is_derivative": False,
        "primitive_type": "float",
        "formula": "10.0 + 20.0",
    })
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="must not specify a formula"):
        load_config(config_file)

def test_derivative_metric_formula_unknown_variable_rejected(valid_config_dict: dict, tmp_path: Path):
    m1 = valid_config_dict["metrics"][0]["name"]

    valid_config_dict["metrics"].append({
        "name": "derived_bad_var",
        "is_derivative": True,
        "primitive_type": "float",
        "formula": f"{m1} + ghost_metric",
    })
    config_file = write_yaml(valid_config_dict, tmp_path)

    with pytest.raises(InvalidSchemaError, match="references unknown metric variable"):
        load_config(config_file)

def test_derivative_metric_unsafe_syntax_rejected(valid_config_dict: dict, tmp_path: Path):
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
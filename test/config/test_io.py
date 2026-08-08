from pathlib import Path
from unittest.mock import patch
import pytest
from src.config.reader import load_config
from src.config.exceptions import ConfigNotFoundError, InvalidSchemaError
from conftest import write_yaml


def test_guard_empty_yaml(tmp_path: Path):
    """Asserts that empty or scalar YAML files raise InvalidSchemaError."""
    empty_file = tmp_path / "empty.yaml"
    empty_file.write_text("", encoding="utf-8")

    with pytest.raises(InvalidSchemaError):
        load_config(empty_file)


def test_config_not_found_error(tmp_path: Path):
    """Asserts that passing a non-existent path raises ConfigNotFoundError cleanly."""
    non_existent_file = tmp_path / "missing_config.yaml"

    with pytest.raises(ConfigNotFoundError):
        load_config(non_existent_file)


def test_permission_error_raises_config_not_found_error(valid_config_dict: dict, tmp_path: Path):
    """Verifies OS PermissionError during file ingestion maps to ConfigNotFoundError."""
    file_path = write_yaml(valid_config_dict, tmp_path)

    with patch("builtins.open", side_effect=PermissionError("Permission denied")):
        with pytest.raises(ConfigNotFoundError, match="Unreadable or inaccessible config file"):
            load_config(file_path)


def test_unicode_decode_error_raises_invalid_schema_error(tmp_path: Path):
    """Verifies non-UTF-8 binary bytes raise UnicodeDecodeError and map to InvalidSchemaError."""
    corrupted_file = tmp_path / "corrupted.yaml"
    corrupted_file.write_bytes(b"\x80\x81\xff\xfe invalid utf8 content")

    with pytest.raises(InvalidSchemaError, match="YAML parsing/decoding error"):
        load_config(corrupted_file)
import os
import pytest
from llm_from_here import common

def test_get_resources_path():
    resources_path = common.get_resources_path()
    test_directory = os.path.dirname(os.path.abspath(resources_path))
    expected_path = os.path.join(test_directory, 'resources')
    assert resources_path == expected_path

def test_log_exception():
    # Define a mock logger_error_func
    def logger_error_func(message):
        pass

    # Define a mock function
    def mock_function():
        raise ValueError("Test exception")

    # Decorate the mock function with log_exception
    decorated_function = common.log_exception(logger_error_func)(mock_function)

    # Ensure the exception is logged and re-raised
    with pytest.raises(ValueError):
        decorated_function()

def test_get_env(monkeypatch):
    # Test when LLMFH_ENV is not set
    assert common.get_env() == 'dev'

    # Test when LLMFH_ENV is set to 'prod'
    monkeypatch.setenv('LLMFH_ENV', 'prod')
    assert common.get_env() == 'prod'

def test_is_production(monkeypatch):
    # Test when LLMFH_ENV is not set
    assert not common.is_production()

    # Test when LLMFH_ENV is set to 'prod'
    monkeypatch.setenv('LLMFH_ENV', 'prod')
    assert common.is_production()

def test_is_production_prefix(monkeypatch):
    # Test when is_production() returns True
    monkeypatch.setattr(common, 'is_production', lambda: True)
    assert common.is_production_prefix() == ''

    # Test when is_production() returns False and LLMFH_ENV is set
    monkeypatch.setattr(common, 'is_production', lambda: False)
    monkeypatch.setenv('LLMFH_ENV', 'prod')
    assert common.is_production_prefix() == 'prod_'

    # Test when is_production() returns False and LLMFH_ENV is not set
    monkeypatch.delenv('LLMFH_ENV', raising=False)
    assert common.is_production_prefix() == 'dev_'

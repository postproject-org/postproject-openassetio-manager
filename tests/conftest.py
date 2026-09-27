"""Shared fixtures for tests against an installed PostProject library."""

import os

import pytest


@pytest.fixture
def native_library():
    return os.environ["POSTPROJECT_LIBRARY"]

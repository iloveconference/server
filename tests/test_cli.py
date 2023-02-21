"""Test cases for the CLI."""
import pytest
from click.testing import CliRunner

from server import cli


@pytest.fixture
def runner() -> CliRunner:
    """Fixture for invoking command-line interfaces."""
    return CliRunner()


def test_main_succeeds(runner: CliRunner) -> None:
    """It exits with a status code of zero."""
    result = runner.invoke(cli.main)
    assert result.exit_code == 0

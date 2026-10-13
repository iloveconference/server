"""Test cases for config."""

from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

from server import config

SECRETS = {
    "OPENAI_KEY": "openai-key",
    "PINECONE_KEY": "pinecone-key",
    "UPSTASH_REDIS_REST_URL": "https://example.upstash.io",
    "UPSTASH_REDIS_REST_TOKEN": "upstash-token",
}


def test_load_secrets_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without SSM_PREFIX, it reads the secrets from the environment."""
    monkeypatch.delenv("SSM_PREFIX", raising=False)
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)

    assert config.load_secrets() == SECRETS


@pytest.fixture
def ssm(monkeypatch: pytest.MonkeyPatch) -> Stubber:
    """Make boto3.client("ssm") return a stubbed client.

    Args:
        monkeypatch: The monkeypatch fixture.

    Returns:
        The stubber for the client.
    """
    monkeypatch.setenv("SSM_PREFIX", "/ilc/prod/")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-west-2")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    client = boto3.client("ssm", region_name="us-west-2")
    stubber = Stubber(client)

    def fake_client(service_name: str, *args: Any, **kwargs: Any) -> Any:
        assert service_name == "ssm"
        return client

    monkeypatch.setattr(boto3, "client", fake_client)
    return stubber


def parameter(name: str, value: str) -> dict[str, Any]:
    """Create a GetParameters result entry.

    Args:
        name: The parameter name.
        value: The parameter value.

    Returns:
        The entry.
    """
    return {"Name": name, "Type": "SecureString", "Value": value, "Version": 1}


def test_load_secrets_from_ssm(ssm: Stubber) -> None:
    """With SSM_PREFIX, it reads all secrets with one decrypting GetParameters call."""
    names = [f"/ilc/prod/{name}" for name in config.SECRET_NAMES]
    ssm.add_response(
        "get_parameters",
        {
            "Parameters": [
                parameter(f"/ilc/prod/{name}", value) for name, value in SECRETS.items()
            ],
        },
        expected_params={"Names": names, "WithDecryption": True},
    )
    with ssm:
        assert config.load_secrets() == SECRETS
    ssm.assert_no_pending_responses()


def test_load_secrets_missing_ssm_parameter(ssm: Stubber) -> None:
    """It raises an error naming any SSM parameter that doesn't exist."""
    ssm.add_response(
        "get_parameters",
        {
            "Parameters": [
                parameter(f"/ilc/prod/{name}", value)
                for name, value in SECRETS.items()
                if name != "PINECONE_KEY"
            ],
            "InvalidParameters": ["/ilc/prod/PINECONE_KEY"],
        },
    )
    with ssm, pytest.raises(RuntimeError, match="/ilc/prod/PINECONE_KEY"):
        config.load_secrets()

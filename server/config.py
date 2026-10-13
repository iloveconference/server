"""Configuration."""

import os

from dotenv import load_dotenv

SECRET_NAMES = (
    "OPENAI_KEY",
    "PINECONE_KEY",
    "UPSTASH_REDIS_REST_URL",
    "UPSTASH_REDIS_REST_TOKEN",
)


def load_secrets() -> dict[str, str]:
    """Load the secrets the server needs.

    When SSM_PREFIX is set (in Lambda), read each secret from the SSM parameter
    "<SSM_PREFIX><NAME>" with a single GetParameters call. Otherwise read them from
    the environment, after loading a .env file if there is one.

    Returns:
        The secret values, keyed by name.

    Raises:
        RuntimeError: If any of the SSM parameters doesn't exist.
    """
    ssm_prefix = os.environ.get("SSM_PREFIX")
    if not ssm_prefix:
        load_dotenv()
        return {name: os.environ[name] for name in SECRET_NAMES}

    # boto3 is provided by the Lambda runtime, so it isn't a runtime dependency
    import boto3

    ssm = boto3.client("ssm")
    response = ssm.get_parameters(
        Names=[ssm_prefix + name for name in SECRET_NAMES], WithDecryption=True
    )
    secrets = {
        param["Name"].removeprefix(ssm_prefix): param["Value"]
        for param in response["Parameters"]
    }
    missing = [ssm_prefix + name for name in SECRET_NAMES if name not in secrets]
    if missing:
        raise RuntimeError(f"Missing SSM parameters: {', '.join(missing)}")
    return secrets

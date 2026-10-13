"""Shared test fixtures."""

import json
import os
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from typing import cast
from unittest.mock import MagicMock

import pytest

from tests.support import TEST_ENV
from tests.support import Invoke
from tests.support import Services
from tests.support import allowed
from tests.support import function_url_event
from tests.support import query_response

# server.main reads its settings and creates its clients when it is first imported (by
# the test modules, after this file), so give it fake settings. Creating the clients makes
# no requests. Importing it here would also bypass typeguard's import hook.
for _name in ("SSM_PREFIX", "AWS_LAMBDA_FUNCTION_NAME", "DEBUG"):
    os.environ.pop(_name, None)
os.environ.update(TEST_ENV)


@pytest.fixture
def services(monkeypatch: pytest.MonkeyPatch) -> Iterator[Services]:
    """Replace the OpenAI, Pinecone and Upstash clients with mocks.

    Args:
        monkeypatch: The monkeypatch fixture.

    Yields:
        The mocks, set up for a successful search.
    """
    from server import main

    mocks = Services(
        embed_client=MagicMock(),
        index=MagicMock(),
        answer_client=MagicMock(),
        client_limiter=MagicMock(),
        global_limiter=MagicMock(),
    )
    mocks.embed_client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])]
    )
    mocks.index.query.return_value = query_response()
    mocks.answer_client.responses.create.return_value = SimpleNamespace(
        output_text="  Faith is trust in God.\n"
    )
    mocks.client_limiter.limit.return_value = allowed()
    mocks.global_limiter.limit.return_value = allowed()
    for name in vars(mocks):
        monkeypatch.setattr(main, name, getattr(mocks, name))
    yield mocks


@pytest.fixture
def invoke() -> Invoke:
    """Get a function that invokes the Lambda handler with a Function URL event.

    Returns:
        A function that takes the path, query parameters and headers of a GET request
        and returns the Lambda response, adding the parsed body as "json" when the
        body is JSON.
    """
    from server.lambda_handler import handler

    def _invoke(
        path: str,
        query: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        context = cast(Any, SimpleNamespace(function_name="ilc-search"))
        response = handler(function_url_event(path, query, headers), context)
        content_type = (response.get("headers") or {}).get("content-type", "")
        if response["body"] and content_type.startswith("application/json"):
            response["json"] = json.loads(response["body"])
        return response

    return _invoke

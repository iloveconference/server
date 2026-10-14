"""Test helpers."""

import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

from pinecone import QueryResponse
from pinecone import ScoredVector
from upstash_ratelimit import Response as RatelimitResponse

# The settings server.main reads when it is imported
TEST_ENV = {
    "OPENAI_KEY": "test-openai-key",
    "PINECONE_KEY": "test-pinecone-key",
    "UPSTASH_REDIS_REST_URL": "https://upstash.invalid",
    "UPSTASH_REDIS_REST_TOKEN": "test-upstash-token",
    "METRIC_NAMESPACE": "server_test",
    "RATE_LIMIT_PER_CLIENT": "40",
    "RATE_LIMIT_GLOBAL_DAILY": "300",
}

# Invokes the Lambda handler with a GET request: (path, query, headers) -> response
Invoke = Callable[..., dict[str, Any]]


@dataclass
class Services:
    """Mocks for the paid and external services the search endpoint calls."""

    embed_client: MagicMock
    index: MagicMock
    answer_client: MagicMock
    client_limiter: MagicMock
    global_limiter: MagicMock

    def paid_calls(self) -> int:
        """Count the calls to OpenAI and Pinecone.

        Returns:
            The number of calls.
        """
        return int(
            self.embed_client.embeddings.create.call_count
            + self.index.query.call_count
            + self.answer_client.responses.create.call_count
        )


def allowed() -> RatelimitResponse:
    """Create a rate-limit response that lets a request through.

    Returns:
        The response.
    """
    return RatelimitResponse(allowed=True, limit=40, remaining=10, reset=0.0)


def rejected() -> RatelimitResponse:
    """Create a rate-limit response that rejects a request.

    Returns:
        The response.
    """
    return RatelimitResponse(allowed=False, limit=40, remaining=0, reset=0.0)


def query_response() -> QueryResponse:
    """Create a Pinecone query response with two matches, one with an anchor.

    Returns:
        The response.
    """
    return QueryResponse(
        matches=[
            ScoredVector(
                id="talk-1-p3",
                score=0.91,
                values=[],
                metadata={
                    "title": "The Power of Faith",
                    "author": "First Speaker",
                    "year": "2020",
                    "month": "04",
                    "url": "https://example.org/talk-1",
                    "anchor": "p3",
                    "text": "Faith is a principle of action and power.",
                },
            ),
            ScoredVector(
                id="talk-2-p1",
                score=0.87,
                values=[],
                metadata={
                    "title": "Hope",
                    "author": "Second Speaker",
                    "year": "2019",
                    "month": "10",
                    "url": "https://example.org/talk-2",
                    "text": "Hope is an anchor to the soul.",
                },
            ),
        ],
        namespace="",
    )


def function_url_event(
    path: str,
    query: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Create a Lambda Function URL event (payload format 2.0) for a GET request.

    Args:
        path: The request path.
        query: The query parameters.
        headers: The request headers, in addition to Host.

    Returns:
        The event.
    """
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": urllib.parse.urlencode(query or {}),
        "headers": {"host": "abc123.lambda-url.us-west-2.on.aws", **(headers or {})},
        "queryStringParameters": query,
        "requestContext": {
            "accountId": "123456789012",
            "apiId": "abc123",
            "domainName": "abc123.lambda-url.us-west-2.on.aws",
            "domainPrefix": "abc123",
            "http": {
                "method": "GET",
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "130.176.0.1",
                "userAgent": "test",
            },
            "requestId": "request-id",
            "routeKey": "$default",
            "stage": "$default",
            "time": "13/Oct/2026:12:00:00 +0000",
            "timeEpoch": 1791892800000,
        },
        "isBase64Encoded": False,
    }

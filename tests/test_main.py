"""Test cases for main."""

import json
import logging
import os
import subprocess  # noqa: S404
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from server import main
from server.search_utils import hash_client_key
from tests.support import TEST_ENV
from tests.support import Invoke
from tests.support import Services
from tests.support import rejected

VIEWER = {"cloudfront-viewer-address": "203.0.113.7:51234"}


def client_id(client_key: str) -> str:
    """Get the identifier the per-client limiter is called with.

    Args:
        client_key: The IP address or IPv6 /64 network.

    Returns:
        The keyed hash of the client key.
    """
    return hash_client_key(client_key, TEST_ENV["UPSTASH_REDIS_REST_TOKEN"])


def test_warm(invoke: Invoke, services: Services) -> None:
    """/api/warm returns an empty 204 and does no paid work."""
    response = invoke("/api/warm")

    assert response["statusCode"] == 204
    assert response["body"] == ""
    assert services.paid_calls() == 0
    services.client_limiter.limit.assert_not_called()
    services.global_limiter.limit.assert_not_called()


def test_warm_up_schedule_event(services: Services) -> None:
    """The warm-up schedule's event returns at once without reaching the app."""
    from server.lambda_handler import handler

    response = handler(
        {"ilc_warm_up": True}, SimpleNamespace(function_name="ilc-search")
    )

    assert response == {"warm": True}
    assert services.paid_calls() == 0
    services.client_limiter.limit.assert_not_called()
    services.global_limiter.limit.assert_not_called()


def test_health(invoke: Invoke, services: Services) -> None:
    """/api/health returns OK."""
    response = invoke("/api/health")

    assert response["statusCode"] == 200
    assert response["body"] == "OK"
    assert services.paid_calls() == 0


def test_routes_are_under_api(invoke: Invoke, services: Services) -> None:
    """The old unprefixed routes are gone, and so is /rate."""
    for path in ("/search", "/health", "/rate", "/api/rate"):
        assert invoke(path, {"q": "faith"}, VIEWER)["statusCode"] == 404
    assert services.paid_calls() == 0


def test_search(
    invoke: Invoke,
    services: Services,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A search returns the answer and results, and logs and records metrics."""
    caplog.set_level(logging.INFO)
    response = invoke("/api/search", {"q": "What is faith?"}, VIEWER)

    assert response["statusCode"] == 200
    body = response["json"]
    assert set(body) == {"q", "session", "answer", "results"}
    assert body["q"] == "What is faith?"
    assert isinstance(body["session"], int) and 0 <= body["session"] < 2**32
    assert body["answer"] == "Faith is trust in God."
    assert body["results"] == [
        {
            "id": "talk-1-p3",
            "title": "The Power of Faith",
            "author": "First Speaker",
            "year": "2020",
            "month": "04",
            "url": "https://example.org/talk-1#p3",
            "text": "Faith is a principle of action and power.",
        },
        {
            "id": "talk-2-p1",
            "title": "Hope",
            "author": "Second Speaker",
            "year": "2019",
            "month": "10",
            "url": "https://example.org/talk-2",
            "text": "Hope is an anchor to the soul.",
        },
    ]

    # rate limits: the client (by a hash of its IP) first, then the global cap
    services.client_limiter.limit.assert_called_once_with(client_id("203.0.113.7"))
    assert "203.0.113.7" not in services.client_limiter.limit.call_args.args[0]
    services.global_limiter.limit.assert_called_once_with("global")

    # paid calls, with their timeouts set on the clients
    services.embed_client.embeddings.create.assert_called_once_with(
        input=["What is faith?"], model="text-embedding-ada-002"
    )
    services.index.query.assert_called_once_with(
        vector=[0.1, 0.2, 0.3], top_k=20, include_metadata=True, timeout=10
    )
    answer_kwargs = services.answer_client.responses.create.call_args.kwargs
    assert answer_kwargs["model"] == "gpt-5-mini"
    assert answer_kwargs["reasoning"] == {"effort": "low"}
    assert answer_kwargs["max_output_tokens"] == 500
    assert answer_kwargs["input"][0] == {"role": "system", "content": main.role_content}
    prompt = answer_kwargs["input"][1]["content"]
    assert prompt.startswith(main.prompt_content)
    assert prompt.endswith("Question: What is faith?\nAnswer:")

    # log records
    records = {record.getMessage(): record for record in caplog.records}
    assert records["search"].name == "server.main"
    assert vars(records["search"])["role"] == main.role_content
    assert vars(records["search"])["prefix"] == main.prompt_content
    assert vars(records["search"])["response"] == body
    assert records["Query response"].name == "server.main"
    query_record = vars(records["Query response"])["query_response"]
    assert [match["id"] for match in query_record["matches"]] == [
        "talk-1-p3",
        "talk-2-p1",
    ]

    # metrics
    emf_lines = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith('{"_aws"')
    ]
    assert len(emf_lines) == 1
    emf = emf_lines[0]
    assert "name" not in emf
    assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "server_test"
    assert emf["search_prompt_length"] == len(prompt)
    assert emf["search_prompt_contexts"] == 2
    assert emf["search_answer_length"] == len("Faith is trust in God.")


def test_search_without_metric_namespace(
    invoke: Invoke,
    services: Services,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a metric namespace, a search prints no EMF line."""
    monkeypatch.setattr(main, "metric_namespace", "")

    assert invoke("/api/search", {"q": "faith"}, VIEWER)["statusCode"] == 200
    assert '"_aws"' not in capsys.readouterr().out


def test_search_rate_limited(invoke: Invoke, services: Services) -> None:
    """A client over its daily limit gets 429 rate_limited and no paid work is done."""
    services.client_limiter.limit.return_value = rejected()

    response = invoke("/api/search", {"q": "faith"}, VIEWER)

    assert response["statusCode"] == 429
    assert response["json"] == {
        "error": "rate_limited",
        "message": (
            "Too many requests. Generating answers is somewhat expensive so currently"
            " we set a limit on how many queries can be performed each day. Please try"
            " again after this time tomorrow."
        ),
    }
    services.global_limiter.limit.assert_not_called()
    assert services.paid_calls() == 0


def test_search_busy(invoke: Invoke, services: Services) -> None:
    """Over the global daily cap, a search gets 429 busy and no paid work is done."""
    services.global_limiter.limit.return_value = rejected()

    response = invoke("/api/search", {"q": "faith"}, VIEWER)

    assert response["statusCode"] == 429
    assert response["json"] == {
        "error": "busy",
        "message": (
            "The site is getting more questions than usual today."
            " Please try again later."
        ),
    }
    services.client_limiter.limit.assert_called_once_with(client_id("203.0.113.7"))
    assert services.paid_calls() == 0


@pytest.mark.parametrize("failing", ["client_limiter", "global_limiter"])
def test_search_rate_limiter_fails_closed(
    invoke: Invoke,
    services: Services,
    failing: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If Upstash fails, a search gets 503 unavailable and no paid work is done."""
    getattr(services, failing).limit.side_effect = httpx.ReadTimeout("timed out")

    response = invoke("/api/search", {"q": "faith"}, VIEWER)

    assert response["statusCode"] == 503
    assert response["json"] == {
        "error": "unavailable",
        "message": "Search is temporarily unavailable. Please try again later.",
    }
    assert services.paid_calls() == 0
    assert any(
        record.name == "server.main" and record.exc_info for record in caplog.records
    )


def test_search_ipv6_client(invoke: Invoke, services: Services) -> None:
    """An IPv6 client is rate-limited by its /64 network."""
    headers = {"cloudfront-viewer-address": "2001:db8:aa:bb:1:2:3:4:443"}

    assert invoke("/api/search", {"q": "faith"}, headers)["statusCode"] == 200
    services.client_limiter.limit.assert_called_once_with(
        client_id("2001:db8:aa:bb::/64")
    )


def test_search_missing_viewer_address_in_lambda(
    invoke: Invoke, services: Services, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inside Lambda, a search without CloudFront-Viewer-Address gets 400."""
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "ilc-search")

    response = invoke("/api/search", {"q": "faith"})

    assert response["statusCode"] == 400
    assert response["json"] == {
        "error": "bad_request",
        "message": "Missing client address.",
    }
    services.client_limiter.limit.assert_not_called()
    assert services.paid_calls() == 0


def test_search_missing_viewer_address_locally(
    invoke: Invoke, services: Services
) -> None:
    """Outside Lambda, a search without the header is limited by the client host."""
    assert "AWS_LAMBDA_FUNCTION_NAME" not in os.environ

    assert invoke("/api/search", {"q": "faith"})["statusCode"] == 200
    services.client_limiter.limit.assert_called_once_with(client_id("130.176.0.1"))


@pytest.mark.parametrize("query", [{}, {"q": ""}, {"q": "x" * 101}])
def test_search_invalid_query(
    invoke: Invoke, services: Services, query: dict[str, str]
) -> None:
    """A missing, empty or too long query gets FastAPI's 422."""
    response = invoke("/api/search", query, VIEWER)

    assert response["statusCode"] == 422
    assert "detail" in response["json"]
    services.client_limiter.limit.assert_not_called()
    assert services.paid_calls() == 0


def test_search_error(invoke: Invoke, services: Services) -> None:
    """An unexpected error is logged and returns 500."""
    services.answer_client.responses.create.side_effect = RuntimeError("boom")

    response = invoke("/api/search", {"q": "faith"}, VIEWER)

    assert response["statusCode"] == 500
    assert response["body"] == "Internal Server Error"


def test_client_settings() -> None:
    """The clients give up in time: OpenAI, Pinecone and Upstash timeouts and retries."""
    assert main.embed_client.timeout == 10
    assert main.answer_client.timeout == 25
    assert main.answer_client.max_retries == 0
    # pinecone v10 retries read timeouts and cannot be told not to, so the old
    # urllib3 read=0 intent is gone; what is left to guarantee is that the attempts
    # are bounded tightly enough to fit inside the 55s Lambda timeout.
    assert main.index_retry.max_retries == 1
    assert main.index_timeout == 10
    assert main.redis._http._client.timeout == httpx.Timeout(2.0)
    assert main.redis._http._retries == 0
    assert main.client_limiter._prefix != main.global_limiter._prefix


def test_openai_resources_loaded_at_import() -> None:
    """The OpenAI API modules are imported at init, which /api/warm pays for."""
    # the client caches each resource on itself the first time it's used
    assert "embeddings" in vars(main.embed_client)
    assert "responses" in vars(main.answer_client)


def test_log_lines_are_json() -> None:
    """The root handler writes each record as one JSON object on one line."""
    handlers = logging.getLogger().handlers
    formatter = next(
        handler.formatter
        for handler in handlers
        if type(handler) is logging.StreamHandler and handler.formatter
    )
    record = logging.makeLogRecord(
        {
            "name": "server.main",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "search",
            "response": {"answer": "line one\nline two"},
        }
    )

    line = formatter.format(record)

    assert "\n" not in line
    data = json.loads(line)
    assert data.pop("asctime")
    assert data == {
        "name": "server.main",
        "levelname": "INFO",
        "message": "search",
        "response": {"answer": "line one\nline two"},
    }


def test_logging_replaces_existing_handlers() -> None:
    """Importing the server replaces handlers set up before it, like Lambda's."""
    code = textwrap.dedent("""
        import json, logging, sys
        runtime_handler = logging.StreamHandler(sys.stderr)
        logging.getLogger().addHandler(runtime_handler)
        # pinecone v10 logs "Index client created for host ..." at INFO while the app
        # is imported; this test is about handler replacement, not third-party chatter.
        logging.getLogger("pinecone").setLevel(logging.WARNING)
        import server.lambda_handler
        handlers = logging.getLogger().handlers
        assert runtime_handler not in handlers, handlers
        assert len(handlers) == 1, handlers
        logging.getLogger("server.main").info("search", extra={"response": {"q": "x"}})
        logging.getLogger("server.main").info("second")
        """)
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, **TEST_ENV},
        cwd=Path(__file__).parent.parent,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert [(r["name"], r["message"]) for r in records] == [
        ("server.main", "search"),
        ("server.main", "second"),
    ]
    assert records[0]["response"] == {"q": "x"}

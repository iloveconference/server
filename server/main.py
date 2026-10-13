"""Server."""

import logging.config
import os
import random
import time
import traceback
from collections.abc import Awaitable
from collections.abc import Callable
from pathlib import Path
from typing import cast

from fastapi import APIRouter
from fastapi import FastAPI
from fastapi import Query
from fastapi import Request
from fastapi import Response
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
from openai import OpenAI
from pinecone import Pinecone
from pinecone import QueryResponse
from pydantic import BaseModel
from upstash_ratelimit import FixedWindow
from upstash_ratelimit import Ratelimit
from upstash_ratelimit import SlidingWindow
from upstash_redis import Redis
from urllib3.util.retry import Retry

from server.config import load_secrets
from server.search_utils import get_client_key
from server.search_utils import get_emf_line
from server.search_utils import get_prompt
from server.search_utils import hash_client_key

# Everything below runs at import, which in Lambda is the init phase that /api/warm pays for.

# init logging
logging.config.fileConfig(Path(__file__).with_name("logging.ini"))
# hard-coded rather than __name__: the log archive's subscription filter matches this name
logger = logging.getLogger("server.main")

# init environment
secrets = load_secrets()
metric_namespace = os.environ.get("METRIC_NAMESPACE", "")
per_client_daily_limit = int(os.environ.get("RATE_LIMIT_PER_CLIENT", "40"))
global_daily_limit = int(os.environ.get("RATE_LIMIT_GLOBAL_DAILY", "300"))

# init fastapi
debug = os.environ.get("DEBUG", "false").lower() == "true"
app = FastAPI(debug=debug)
router = APIRouter(prefix="/api")

# init openai
openai_client = OpenAI(api_key=secrets["OPENAI_KEY"])
embed_client = openai_client.with_options(timeout=10)
# no retries: a retried answer would be paid for twice
answer_client = openai_client.with_options(timeout=25, max_retries=0)
# The client imports its API modules (about 500) the first time one is used. Use the two we
# need now, so /api/warm pays for those imports instead of the first search.
embed_client.embeddings
answer_client.responses
embedding_model = "text-embedding-ada-002"
answer_model = "gpt-5-mini"
prompt_limit = 3000  # 3750

# init pinecone
index_host = "https://conf-ada-002-svrless-29e6444.svc.aped-4627-b74a.pinecone.io"
index_timeout = 10
# initialize connection to pinecone (get API key at app.pinecone.io)
pc = Pinecone(api_key=secrets["PINECONE_KEY"])
# The client retries every error up to 5 times by default, including read timeouts, so a
# hung query would take 6 x index_timeout. Keep the quick retries (5xx, connection
# errors) but give up on a read timeout. Pinecone has no public setting for this.
pc._openapi_config.retries = Retry(
    total=2,
    read=0,
    backoff_factor=0.25,
    status_forcelist=(500, 502, 503, 504),
    allowed_methods=None,
)
index = pc.Index(host=index_host)

# init rate limiting
redis = Redis(
    url=secrets["UPSTASH_REDIS_REST_URL"],
    token=secrets["UPSTASH_REDIS_REST_TOKEN"],
    rest_retries=0,
)
# upstash-redis has no timeout setting and its httpx client never times out
redis._http._client.timeout = 2.0
# keys the hash of client IP addresses, so Upstash never stores an IP address
client_key_secret = secrets["UPSTASH_REDIS_REST_TOKEN"]
client_limiter = Ratelimit(
    redis=redis,
    limiter=SlidingWindow(max_requests=per_client_daily_limit, window=86400),
    prefix="ilc:client",
)
global_limiter = Ratelimit(
    redis=redis,
    limiter=FixedWindow(max_requests=global_daily_limit, window=1, unit="d"),
    prefix="ilc:global",
)

# other constants
search_limit = 20
max_answer_tokens = 500
role_content = "You are an apostle of the Church of Jesus Christ of Latter-day Saints"
prompt_content = (
    "Answer the question as truthfully as possible using the provided context, "
    + 'and if answer is not contained within the text below, say "Sorry, I don\'t know".'
)
rate_limited_message = (
    "Too many requests. Generating answers is somewhat expensive so currently we set "
    "a limit on how many queries can be performed each day. "
    "Please try again after this time tomorrow."
)
busy_message = (
    "The site is getting more questions than usual today. Please try again later."
)
unavailable_message = "Search is temporarily unavailable. Please try again later."


# data models
class SearchResult(BaseModel):
    """Search result."""

    id: str
    title: str
    author: str
    year: str
    month: str
    url: str
    text: str


class SearchResponse(BaseModel):
    """Search response."""

    q: str
    session: int
    answer: str
    results: list[SearchResult]


def error_response(status_code: int, error: str, message: str) -> JSONResponse:
    """Create an error response.

    Args:
        status_code: The HTTP status code.
        error: The error code the client switches on.
        message: The message to show the user.

    Returns:
        The response.
    """
    return JSONResponse(
        status_code=status_code, content={"error": error, "message": message}
    )


def get_rate_limit_key(request: Request) -> str | None:
    """Get the key to rate-limit a request by.

    The client address comes from the CloudFront-Viewer-Address header. Inside
    Lambda the request's own client is a CloudFront edge server shared by many
    users, so it is only a fallback for local development.

    Args:
        request: The request.

    Returns:
        The key, or None if the request has no usable client address.
    """
    key = get_client_key(request.headers.get("cloudfront-viewer-address"))
    if key is None and "AWS_LAMBDA_FUNCTION_NAME" not in os.environ and request.client:
        key = request.client.host
    return key


def check_rate_limits(key: str) -> JSONResponse | None:
    """Check the per-client limit, then the global daily limit.

    Fails closed: if Upstash can't be reached, the request is rejected.

    Args:
        key: The client's rate-limit key: its IP address or IPv6 /64 network.

    Returns:
        An error response if the request is rejected, otherwise None.
    """
    try:
        if not client_limiter.limit(hash_client_key(key, client_key_secret)).allowed:
            return error_response(429, "rate_limited", rate_limited_message)
        if not global_limiter.limit("global").allowed:
            return error_response(429, "busy", busy_message)
    except Exception:
        logger.exception("Rate limit check failed")
        return error_response(503, "unavailable", unavailable_message)
    return None


@app.middleware("http")
async def log_exceptions_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Log exceptions."""
    try:
        return await call_next(request)
    except Exception:
        logger.error(
            traceback.format_exc(),
            extra={
                "url": str(request.url),
                "method": request.method,
            },
        )
        return PlainTextResponse("Internal Server Error", status_code=500)


@router.get("/search", response_model=SearchResponse)
def search(
    request: Request, q: str = Query(min_length=1, max_length=100)
) -> SearchResponse | JSONResponse:
    """Search."""
    # rate limit
    key = get_rate_limit_key(request)
    if key is None:
        return error_response(400, "bad_request", "Missing client address.")
    rejection = check_rate_limits(key)
    if rejection is not None:
        return rejection

    # get query embedding
    start = time.perf_counter()
    embed_response = embed_client.embeddings.create(input=[q], model=embedding_model)
    embed_secs = time.perf_counter() - start
    embedding = embed_response.data[0].embedding

    # query index
    start = time.perf_counter()
    query_response = cast(
        QueryResponse,
        index.query(
            vector=embedding,
            top_k=search_limit,
            include_metadata=True,
            _request_timeout=index_timeout,
        ),
    )
    index_secs = time.perf_counter() - start
    logger.info("Query response", extra={"query_response": query_response.to_dict()})

    # get prompt
    texts = [res["metadata"]["text"] for res in query_response["matches"]]
    prompt, n_contexts = get_prompt(prompt_content, q, texts, prompt_limit)

    # get answer
    start = time.perf_counter()
    answer_response = answer_client.responses.create(
        model=answer_model,
        input=[
            {"role": "system", "content": role_content},
            {"role": "user", "content": prompt},
        ],
        reasoning={"effort": "low"},
        max_output_tokens=max_answer_tokens,
    )
    answer_secs = time.perf_counter() - start
    answer = answer_response.output_text.strip()

    # create response
    response = SearchResponse(
        q=q,
        session=random.getrandbits(32),  # noqa: S311 - an ID, not a secret
        answer=answer,
        results=[
            SearchResult(
                id=res["id"],
                title=res["metadata"]["title"],
                text=res["metadata"]["text"],
                author=res["metadata"]["author"],
                year=res["metadata"]["year"],
                month=res["metadata"]["month"],
                url=(
                    f'{res["metadata"]["url"]}#{res["metadata"]["anchor"]}'
                    if "anchor" in res["metadata"] and res["metadata"]["anchor"]
                    else res["metadata"]["url"]
                ),
            )
            for res in query_response["matches"]
        ],
    )

    logger.info(
        "search",
        extra={
            "role": role_content,
            "prefix": prompt_content,
            "response": response.model_dump(),
        },
    )
    if metric_namespace:
        print(
            get_emf_line(
                metric_namespace,
                "search",
                embed_secs,
                index_secs,
                answer_secs,
                len(prompt),
                n_contexts,
                len(answer),
            ),
            flush=True,
        )
    return response


@router.get("/warm", status_code=204)
async def warm() -> Response:
    """Warm up a Lambda execution environment; the work is done at import."""
    return Response(status_code=204)


@router.get("/health")
async def health() -> PlainTextResponse:
    """Health check."""
    return PlainTextResponse("OK")


app.include_router(router)

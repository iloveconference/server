"""Server."""
import logging.config
import os
import random
import traceback
from enum import IntEnum
from typing import Awaitable
from typing import Callable

import openai
import pinecone  # type: ignore
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi import Query
from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import Response

from server.search_utils import get_prompt


# init environment
load_dotenv()
pinecone_key = os.environ["PINECONE_KEY"]
openai_key = os.environ["OPENAI_KEY"]

# init logging
logging.config.fileConfig("server/logging.ini")
logger = logging.getLogger(__name__)

# init fastapi
debug = os.environ.get("DEBUG", "false").lower() == "true"
app = FastAPI(debug=debug)

# init openai
openai.api_key = openai_key
embedding_model = "text-embedding-ada-002"
prompt_limit = 1000  # 3750

# init pinecone
index_name = "conf-ada-002"
# initialize connection to pinecone (get API key at app.pinecone.io)
pinecone.init(
    api_key=pinecone_key,
    environment="us-west1-gcp",  # may be different, check at app.pinecone.io
)
index = pinecone.Index(index_name)

# other constants
search_limit = 20


# data models
class SearchResult(BaseModel):
    """Search result."""

    id: int
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


@app.middleware("http")
async def log_exceptions_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Log exceptions."""
    try:
        return await call_next(request)
    except Exception:
        body = await request.body()
        logger.error(
            traceback.format_exc(),
            extra={
                "url": request.url,
                "method": request.method,
                # "headers": request.headers,
                "body": body,
            },
        )
        return Response(status_code=500, content="Internal Server Error")


@app.get("/search")
async def search(q: str = Query(max_length=100)) -> SearchResponse:
    """Search."""
    # get query embedding
    logger.info("get embedding", extra={"q": q})
    embed_response = openai.Embedding.create(
        input=[q], engine=embedding_model
    )  # type: ignore
    embedding = embed_response["data"][0]["embedding"]
    # query index
    logger.info("query index", extra={"q": q})
    query_response = index.query(embedding, top_k=search_limit, include_metadata=True)
    # get prompt
    logger.info("get prompt", extra={"q": q})
    texts = [res["metadata"]["text"] for res in query_response["matches"]]
    prompt = get_prompt(q, texts, prompt_limit)
    # get answer
    logger.info("get answer", extra={"q": q})
    answer_response = openai.Completion.create(
        engine="text-davinci-003",
        prompt=prompt,
        temperature=0,
        max_tokens=400,
        top_p=1,
        frequency_penalty=0,
        presence_penalty=0,
        stop=None,
    )  # type: ignore
    answer = answer_response["choices"][0]["text"].strip()
    response = SearchResponse(
        q=q,
        session=random.getrandbits(32),
        answer=answer,
        results=[
            SearchResult(
                id=res["id"],
                title=res["metadata"]["title"],
                text=res["metadata"]["text"],
                author=res["metadata"]["author"],
                year=res["metadata"]["year"],
                month=res["metadata"]["month"],
                url=res["metadata"]["url"],
            )
            for res in query_response["matches"]
        ],
    )
    logger.info("search", extra={"q": q, "response": response.dict()})
    return response


class Rating(IntEnum):
    """Rating."""

    UP = 1
    DOWN = -1


@app.post("/rate")
async def rate(session: int, user: str, result: int, rating: Rating) -> Response:
    """Rate."""
    logger.info(
        "rate",
        extra={"session": session, "user": user, "result": result, "rating": rating},
    )
    return Response(status_code=201)


@app.get("/health")
async def health() -> Response:
    """Health check."""
    # logger.info("health")
    return Response(status_code=200, content="OK")

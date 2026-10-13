"""Search utility functions."""

import hashlib
import hmac
import ipaddress
import json
import time


def get_prompt(
    prompt: str, query: str, contexts: list[str], prompt_limit: int
) -> tuple[str, int]:
    """Get prompt for query and contexts."""

    def _get_prompt_for_contexts(ctxs: list[str]) -> str:
        return (
            prompt
            + "\n\nContext:\n"
            + "\n\n---\n\n".join(ctxs)
            + f"\n\nQuestion: {query}\nAnswer:"
        )

    n_contexts = 0
    while (
        n_contexts < len(contexts)
        and len(_get_prompt_for_contexts(contexts[0 : n_contexts + 1])) < prompt_limit
    ):
        n_contexts += 1
    return _get_prompt_for_contexts(contexts[0:n_contexts]), n_contexts


def get_client_key(viewer_address: str | None) -> str | None:
    """Get the rate-limit key for a CloudFront-Viewer-Address header value.

    The header value is "ip:port". IPv6 addresses contain colons, so split on the
    last one. An IPv6 client is keyed by its /64 network, because one subscriber is
    usually given a whole /64 and could otherwise rotate through its addresses.

    Args:
        viewer_address: The header value, or None if the header is missing.

    Returns:
        The IPv4 address or IPv6 /64 network, or None if the value is missing or
        malformed.
    """
    if not viewer_address:
        return None
    host, separator, _ = viewer_address.rpartition(":")
    if not separator:
        return None
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped:
            return str(address.ipv4_mapped)
        return str(ipaddress.IPv6Network((address, 64), strict=False))
    return str(address)


def hash_client_key(client_key: str, secret: str) -> str:
    """Hash a client key so the rate limiter never stores an IP address.

    The privacy policy promises that only a one-way hash of the IP address is stored.
    The hash is keyed with a server secret, so it can't be reversed by hashing all
    4 billion IPv4 addresses.

    Args:
        client_key: The key from get_client_key.
        secret: The secret to key the hash with.

    Returns:
        The hash, as 32 hex digits.
    """
    digest = hmac.new(secret.encode(), client_key.encode(), hashlib.sha256)
    return digest.hexdigest()[:32]


def get_emf_line(
    metric_namespace: str,
    metric_name: str,
    embed_secs: float,
    index_secs: float,
    answer_secs: float,
    prompt_len: int,
    n_contexts: int,
    answer_len: int,
) -> str:
    """Get a CloudWatch Embedded Metric Format line with the metrics for a search.

    Printed to stdout in Lambda, CloudWatch turns the line into metrics without an
    API call. It has no "name" field, so the log archive's subscription filter
    (``$.name = "server.main"``) skips it.

    Args:
        metric_namespace: The CloudWatch namespace.
        metric_name: The prefix of the metric names.
        embed_secs: How long getting the query embedding took.
        index_secs: How long querying the index took.
        answer_secs: How long getting the answer took.
        prompt_len: The length of the prompt.
        n_contexts: The number of contexts in the prompt.
        answer_len: The length of the answer.

    Returns:
        The line, a JSON object without a trailing newline.
    """
    seconds = {
        f"{metric_name}_embed_seconds": embed_secs,
        f"{metric_name}_index_seconds": index_secs,
        f"{metric_name}_answer_seconds": answer_secs,
    }
    counts = {
        f"{metric_name}_prompt_length": prompt_len,
        f"{metric_name}_prompt_contexts": n_contexts,
        f"{metric_name}_answer_length": answer_len,
    }
    return json.dumps(
        {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": metric_namespace,
                        "Dimensions": [[]],
                        "Metrics": [
                            *({"Name": name, "Unit": "Seconds"} for name in seconds),
                            *({"Name": name, "Unit": "Count"} for name in counts),
                        ],
                    }
                ],
            },
            **seconds,
            **counts,
        }
    )

"""Search utility functions."""

from typing import Any
from typing import Tuple


def get_prompt(query: str, contexts: list[str], prompt_limit: int) -> Tuple[str, int]:
    """Get prompt for query and contexts."""

    def _get_prompt_for_contexts(ctxs: list[str]) -> str:
        return (
            "Answer the question based on the context below.\n\n"
            + "Context:\n"
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


def log_metrics(
    cloudwatch: Any,
    metric_namespace: str,
    metric_name: str,
    embed_secs: float,
    index_secs: float,
    answer_secs: float,
    prompt_len: int,
    n_contexts: int,
    answer_len: int,
) -> None:
    """Log metrics to CloudWatch."""
    cloudwatch.put_metric_data(
        Namespace=metric_namespace,
        MetricData=[
            {
                "MetricName": f"{metric_name}_embed_seconds",
                "Value": embed_secs,
                "Unit": "Seconds",
            },
            {
                "MetricName": f"{metric_name}_index_seconds",
                "Value": index_secs,
                "Unit": "Seconds",
            },
            {
                "MetricName": f"{metric_name}_answer_seconds",
                "Value": answer_secs,
                "Unit": "Seconds",
            },
            {
                "MetricName": f"{metric_name}_prompt_length",
                "Value": prompt_len,
                "Unit": "Count",
            },
            {
                "MetricName": f"{metric_name}_prompt_contexts",
                "Value": n_contexts,
                "Unit": "Count",
            },
            {
                "MetricName": f"{metric_name}_answer_length",
                "Value": answer_len,
                "Unit": "Count",
            },
            {
                "MetricName": f"{metric_name}_hits",
                "Value": 1,
                "Unit": "Count",
            },
        ],
    )

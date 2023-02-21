"""Search utility functions."""


def get_prompt(query: str, contexts: list[str], prompt_limit: int) -> str:
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
    return _get_prompt_for_contexts(contexts[0:n_contexts])

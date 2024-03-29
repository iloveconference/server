"""Test cases for search utils."""

from server import search_utils


def test_get_prompt() -> None:
    """It gets the correct number of contexts."""
    prompt, _ = search_utils.get_prompt(
        "This is my prompt content",
        "Question?",
        ["Answer...1", "Answer...2", "Answer...3", "Answer...4", "Answer...5"],
        100,
    )
    assert 90 <= len(prompt) <= 100

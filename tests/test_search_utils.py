"""Test cases for search utils."""

import json
import time

import pytest

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


@pytest.mark.parametrize(
    "viewer_address, key",
    [
        ("198.51.100.10:46532", "198.51.100.10"),
        ("2001:db8:85a3:12:8a2e:370:7334:1:443", "2001:db8:85a3:12::/64"),
        ("2001:DB8:85A3:12:FFFF:FFFF:FFFF:FFFF:443", "2001:db8:85a3:12::/64"),
        ("2001:db8::1:443", "2001:db8::/64"),
        ("[2001:db8::1]:443", "2001:db8::/64"),
        ("::ffff:198.51.100.10:443", "198.51.100.10"),
    ],
)
def test_get_client_key(viewer_address: str, key: str) -> None:
    """It keys IPv4 clients by address and IPv6 clients by /64 network."""
    assert search_utils.get_client_key(viewer_address) == key


def test_get_client_key_same_network() -> None:
    """Two addresses in the same IPv6 /64 share a key."""
    assert search_utils.get_client_key(
        "2001:db8:1:2:aaaa::1:1000"
    ) == search_utils.get_client_key("2001:db8:1:2:bbbb::2:2000")


@pytest.mark.parametrize(
    "viewer_address", [None, "", "198.51.100.10", "not-an-ip:443", ":443"]
)
def test_get_client_key_missing(viewer_address: str | None) -> None:
    """It returns None for a missing or malformed header."""
    assert search_utils.get_client_key(viewer_address) is None


def test_hash_client_key() -> None:
    """It hashes a client key with a secret, so the IP address isn't stored."""
    key = search_utils.hash_client_key("198.51.100.10", "secret")

    assert len(key) == 32 and int(key, 16) >= 0
    assert "198.51.100.10" not in key
    assert key == search_utils.hash_client_key("198.51.100.10", "secret")
    assert key != search_utils.hash_client_key("198.51.100.11", "secret")
    assert key != search_utils.hash_client_key("198.51.100.10", "other secret")


def test_get_emf_line() -> None:
    """It creates one EMF JSON line with six metrics and no name field."""
    before = int(time.time() * 1000)
    line = search_utils.get_emf_line(
        "server_prod", "search", 0.5, 0.25, 3.0, 2900, 4, 812
    )
    after = int(time.time() * 1000)

    assert "\n" not in line
    emf = json.loads(line)
    assert "name" not in emf
    assert before <= emf["_aws"]["Timestamp"] <= after
    assert emf["_aws"]["CloudWatchMetrics"] == [
        {
            "Namespace": "server_prod",
            "Dimensions": [[]],
            "Metrics": [
                {"Name": "search_embed_seconds", "Unit": "Seconds"},
                {"Name": "search_index_seconds", "Unit": "Seconds"},
                {"Name": "search_answer_seconds", "Unit": "Seconds"},
                {"Name": "search_prompt_length", "Unit": "Count"},
                {"Name": "search_prompt_contexts", "Unit": "Count"},
                {"Name": "search_answer_length", "Unit": "Count"},
            ],
        }
    ]
    assert {key: value for key, value in emf.items() if key != "_aws"} == {
        "search_embed_seconds": 0.5,
        "search_index_seconds": 0.25,
        "search_answer_seconds": 3.0,
        "search_prompt_length": 2900,
        "search_prompt_contexts": 4,
        "search_answer_length": 812,
    }

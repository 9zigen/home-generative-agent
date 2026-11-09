# ruff: noqa: S101
"""An OpenAI-compatible server keeps the model's own top_p default."""

from __future__ import annotations

import inspect

import pytest

import custom_components.home_generative_agent as hga


@pytest.mark.parametrize(
    "provider", ["chat_provider", "vlm_provider", "sum_provider", "sentinel_provider"]
)
def test_openai_compatible_primary_sends_no_top_p(provider: str) -> None:
    """The hard-coded 1.0 overrode what the model's authors recommend."""
    source = inspect.getsource(hga.async_setup_entry)
    start = source.index(f'elif {provider} == "openai_compatible":')
    branch = source[start : source.index("elif ", start + 10)]
    assert '"model_name"' in branch
    assert '"top_p"' not in branch


def test_openai_compatible_fallback_sends_no_top_p() -> None:
    """A fallback on such a server is configured the same way."""
    source = inspect.getsource(hga.async_setup_entry)
    assert 'provider.provider_type != "openai_compatible" and top_p' in source

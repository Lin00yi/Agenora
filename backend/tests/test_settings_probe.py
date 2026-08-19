from src.api.routes.settings import ProbeLLMBody


def test_probe_llm_body_allows_empty_key_for_saved_configuration() -> None:
    """The route resolves an empty key only when provider and URL match the saved config."""
    body = ProbeLLMBody(
        provider="openai-compat",
        base_url="https://api.deepseek.com",
        api_key="",
    )

    assert body.api_key == ""

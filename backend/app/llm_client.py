import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMConfigurationError(Exception):
    pass


class LLMRequestError(Exception):
    pass


def chat_completion(system_prompt: str, user_prompt: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip().rstrip("/")
    model = os.getenv("OPENAI_MODEL", "").strip()
    missing = [name for name, value in (("OPENAI_API_KEY", api_key), ("OPENAI_BASE_URL", base_url), ("OPENAI_MODEL", model)) if not value]
    if missing:
        raise LLMConfigurationError("Missing required model configuration: " + ", ".join(missing))

    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }, ensure_ascii=False).encode("utf-8")
    request = Request(
        base_url + "/chat/completions",
        data=payload,
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=75) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Avoid forwarding provider response bodies, which may contain sensitive details.
        raise LLMRequestError(f"Model provider returned HTTP {exc.code}.") from None
    except (URLError, TimeoutError, OSError):
        raise LLMRequestError("Could not connect to the configured model provider.") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise LLMRequestError("The model provider returned an invalid response.") from None

    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMRequestError("The model provider response did not contain a chat completion.") from None
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    if not isinstance(content, str) or not content.strip():
        raise LLMRequestError("The model returned an empty response.")
    return content.strip()

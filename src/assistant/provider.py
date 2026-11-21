"""One OpenAI-compatible chat client. Cloud and local models differ by settings."""

import json
import urllib.error
import urllib.request


class ProviderError(Exception):
    """The model provider refused the request or returned something unusable."""


def complete(messages, settings, tools=None, timeout=90, urlopen=None):
    """Send one chat-completions request.

    Returns {"content": str, "tool_calls": [{"id", "name", "arguments"}]}.
    `arguments` is a dict. The API key is sent as a header and is not copied
    into the return value.
    """
    urlopen = urlopen or urllib.request.urlopen
    url = settings.base_url + settings.chat_path
    body = {
        "model": settings.model,
        "messages": messages,
        "temperature": 0.2,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    request.add_header("Accept", "application/json")
    if settings.api_key:
        if settings.auth == "api-key":
            request.add_header("api-key", settings.api_key)
        else:
            request.add_header("Authorization", "Bearer " + settings.api_key)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderError(f"the model provider returned {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach the model provider: {exc.reason}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProviderError("the model provider did not return JSON") from exc
    return _parse_completion(payload)


def _parse_completion(payload):
    try:
        message = payload["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderError("the model provider returned no assistant message") from exc
    content = message.get("content") or ""
    if isinstance(content, list):
        texts = []
        for part in content:
            if isinstance(part, dict):
                texts.append(part.get("text") or "")
            else:
                texts.append(str(part))
        content = "".join(texts)
    if not isinstance(content, str):
        content = str(content)
    calls = []
    for index, call in enumerate(message.get("tool_calls") or []):
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        name = function.get("name") or call.get("name") or ""
        arguments = function.get("arguments")
        if arguments is None:
            arguments = call.get("arguments") or {}
        if isinstance(arguments, str):
            if not arguments.strip():
                arguments = {}
            else:
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        if not name:
            continue
        calls.append({
            "id": str(call.get("id") or f"call-{index + 1}"),
            "name": name,
            "arguments": arguments,
        })
    return {"content": content, "tool_calls": calls}

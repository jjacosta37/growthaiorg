"""Stand-ins for the Anthropic client. Tests never hit the network."""

from types import SimpleNamespace


def usage(input_tokens=100, output_tokens=20, cache_read=0, cache_write=0, web_search=0):
    return SimpleNamespace(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_write,
        server_tool_use=SimpleNamespace(web_search_requests=web_search) if web_search else None,
    )


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def message(content, stop_reason="end_turn", usage_=None, stop_details=None):
    if isinstance(content, str):
        content = [text_block(content)]
    return SimpleNamespace(
        content=content,
        stop_reason=stop_reason,
        stop_details=stop_details,
        usage=usage_ or usage(),
        _request_id="req_test",
    )


class FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **params):
        self.calls.append(params)
        if not self._responses:
            raise AssertionError("FakeAnthropic: no more queued responses")
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeAnthropic:
    """Queue responses (messages or exceptions); inspect `.messages.calls` afterwards."""

    def __init__(self, *responses):
        self.messages = FakeMessages(responses)

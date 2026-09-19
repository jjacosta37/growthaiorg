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


def task_system(params) -> str:
    """The task-instructions block (last system block) of a request."""
    return params["system"][-1]["text"] if params.get("system") else ""


def schema_title(params) -> str | None:
    fmt = (params.get("output_config") or {}).get("format")
    return fmt["schema"].get("title") if fmt else None


class FakeMessages:
    def __init__(self, responses, responder=None):
        self._responses = list(responses)
        self._responder = responder
        self.calls: list[dict] = []
        self.batches = FakeBatches()

    def create(self, **params):
        self.calls.append(params)
        if self._responder is not None:
            r = self._responder(params)
        elif self._responses:
            r = self._responses.pop(0)
        else:
            raise AssertionError("FakeAnthropic: no more queued responses")
        if isinstance(r, Exception):
            raise r
        return r


class FakeAnthropic:
    """Either queue responses (messages or exceptions) in order, or pass `responder(params)`
    to answer based on the request. Inspect `.messages.calls` afterwards."""

    def __init__(self, *responses, responder=None):
        self.messages = FakeMessages(responses, responder)


class FakeBatches:
    """messages.batches: create() records requests; results come from `answer(custom_id, params)`."""

    def __init__(self):
        self.created: list[list[dict]] = []
        self.answer = None  # (custom_id, params) -> message | ("errored"|"expired"|"canceled", detail)
        self.ended = True

    def create(self, requests):
        self.created.append(requests)
        return SimpleNamespace(id=f"msgbatch_{len(self.created)}", processing_status="in_progress")

    def retrieve(self, batch_id):
        return SimpleNamespace(id=batch_id, processing_status="ended" if self.ended else "in_progress")

    def results(self, batch_id):
        requests = self.created[int(batch_id.rsplit("_", 1)[1]) - 1]
        for req in reversed(requests):  # results arrive in any order
            out = self.answer(req["custom_id"], req["params"])
            if isinstance(out, tuple):
                kind, detail = out
                result = SimpleNamespace(type=kind, error=SimpleNamespace(error=detail))
            else:
                result = SimpleNamespace(type="succeeded", message=out)
            yield SimpleNamespace(custom_id=req["custom_id"], result=result)

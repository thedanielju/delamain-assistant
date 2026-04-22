import json

from delamain_backend.events.sse import format_sse


def test_sse_event_serialization():
    event = {
        "id": 123,
        "conversation_id": "conv_1",
        "run_id": "run_1",
        "type": "message.delta",
        "created_at": "2026-04-17T00:00:00Z",
        "payload": {"text": "hello"},
    }
    encoded = format_sse(event)
    assert encoded.startswith("id: 123\nevent: message.delta\n")
    data_line = [line for line in encoded.splitlines() if line.startswith("data: ")][0]
    assert json.loads(data_line.removeprefix("data: "))["payload"]["text"] == "hello"

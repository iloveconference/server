"""AWS Lambda entry point."""

from typing import Any

from mangum import Mangum

from server.main import app

# template.yaml's warm-up schedule invokes the function with {"ilc_warm_up": true}.
WARM_UP_EVENT_KEY = "ilc_warm_up"

_asgi_handler = Mangum(app, lifespan="off")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Handle a Lambda invocation.

    The warm-up schedule's event returns at once: its only job is to keep an execution
    environment warm, so searches skip the cold start. Every other event is a function URL
    request, which goes to the FastAPI app.

    Args:
        event: The invocation event.
        context: The Lambda context.

    Returns:
        The function URL response, or {"warm": True} for the warm-up event.
    """
    if event.get(WARM_UP_EVENT_KEY) is True:
        return {"warm": True}
    return _asgi_handler(event, context)

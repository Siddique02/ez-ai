"""Langfuse tracing for every OpenAI call the app makes.

Tracing is on only when LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY are set.
Without them the app runs exactly as before and nothing is sent anywhere.

Import OpenAI, observe and propagate_attributes from this module rather than
from openai or langfuse, so the client below is configured before any call.
"""

import logging
import re
from typing import Any

from langfuse import Langfuse, observe, propagate_attributes
from langfuse.openai import OpenAI

from app.core.config import settings


__all__ = ["OpenAI", "langfuse", "observe", "propagate_attributes"]


_DATA_URL = re.compile(r"^data:[\w.+/-]+;base64,", re.IGNORECASE)


def mask_file_data(*, data: Any, **kwargs: Any) -> Any:
    """Replace uploaded files with a short note before anything is sent.

    Blueprints travel to OpenAI as base64 data URLs of up to 25 MB. Storing
    them in every trace would be heavy and would copy contractors' drawings
    into Langfuse, so only their type and size are kept.
    """
    if isinstance(data, str):
        if _DATA_URL.match(data):
            header = data[: data.index(",")]
            return f"<{header} omitted, {len(data):,} characters>"
        return data
    if isinstance(data, dict):
        return {key: mask_file_data(data=value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [mask_file_data(data=value) for value in data]
    return data


tracing_enabled = bool(
    settings.langfuse_public_key and settings.langfuse_secret_key
)
if not tracing_enabled:
    # Without keys the SDK warns on every call; tracing is simply off.
    logging.getLogger("langfuse").setLevel(logging.ERROR)

langfuse = Langfuse(
    public_key=settings.langfuse_public_key,
    secret_key=settings.langfuse_secret_key,
    host=settings.langfuse_host,
    tracing_enabled=tracing_enabled,
    mask=mask_file_data,
)

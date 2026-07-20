"""Broker adapter factory.

Students can switch brokers with `.env`:

    LECTURE_BROKER=kis      # existing bridge
    LECTURE_BROKER=kiwoom   # Kiwoom REST API teaching adapter
    LECTURE_BROKER=toss     # optional pinned tossctl WTS adapter
"""

from __future__ import annotations

import importlib
import os
from typing import Any

from .config import load_dotenv_once

_BUILTIN_ADAPTERS = {
    "kis": "brokers.kis:KISBrokerAdapter",
    "kiwoom": "brokers.kiwoom:KiwoomBrokerAdapter",
    "toss": "brokers.toss:TossBrokerAdapter",
}


def supported_brokers() -> tuple[str, ...]:
    return tuple(sorted(_BUILTIN_ADAPTERS))


def selected_broker_name(default: str = "kis") -> str:
    load_dotenv_once()
    return (os.getenv("LECTURE_BROKER") or os.getenv("PRISM_BROKER") or default).strip().lower()


def _load_class(dotted: str) -> type[Any]:
    module_name, class_name = dotted.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def get_broker_adapter(name: str | None = None) -> Any:
    """Instantiate the selected broker adapter.

    Advanced students can set:
      LECTURE_BROKER=custom
      LECTURE_BROKER_ADAPTER=my_package.my_module:MyAdapter
    """

    load_dotenv_once()
    broker = (name or selected_broker_name()).strip().lower()
    if broker == "custom":
        target = os.getenv("LECTURE_BROKER_ADAPTER", "").strip()
        if not target:
            raise ValueError("LECTURE_BROKER=custom requires LECTURE_BROKER_ADAPTER=module:Class")
    else:
        target = _BUILTIN_ADAPTERS.get(broker)
        if not target:
            raise ValueError(f"Unsupported broker '{broker}'. Supported: {', '.join(supported_brokers())}, custom")
    adapter_cls = _load_class(target)
    return adapter_cls()

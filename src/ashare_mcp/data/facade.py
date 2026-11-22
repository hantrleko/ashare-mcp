"""Provider facade: try akshare first, fall back to tushare."""
from __future__ import annotations

from typing import Any, Callable

from . import akshare_data, tushare_data


class MarketData:
    """Routes each data call through providers in priority order."""

    _PROVIDERS = (("akshare", akshare_data), ("tushare", tushare_data))

    def call(self, func_name: str, *args: Any, **kwargs: Any) -> tuple[Any, str]:
        """Call ``func_name`` on providers; return ``(result, provider_name)``."""
        errors: list[str] = []
        for name, mod in self._PROVIDERS:
            fn: Callable | None = getattr(mod, func_name, None)
            if fn is None:
                continue
            try:
                return fn(*args, **kwargs), name
            except Exception as e:  # noqa: BLE001 - collect, try next
                errors.append(f"{name}: {e}")
        raise RuntimeError("all providers failed — " + " | ".join(errors))

    def provider_status(self) -> dict[str, Any]:
        from ..config import tushare_token

        return {
            "primary": "akshare",
            "fallback": "tushare",
            "tushare_token_set": bool(tushare_token()),
        }


market_data = MarketData()

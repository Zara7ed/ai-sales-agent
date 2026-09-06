"""Payment link sender (stdlib only).

Reads link/template from ``kb_data['payment']`` and formats a Persian
message containing the amount + link.
"""
from __future__ import annotations

from typing import Any, Optional

DEFAULT_LINK = "https://pay.example.com/checkout"
DEFAULT_TEMPLATE = (
    "💳 برای تکمیل خرید، لطفاً مبلغ {amount} را از طریق لینک زیر پرداخت کنید:\n"
    "{link}\n"
    "پس از پرداخت، رسید را همین‌جا ارسال کنید تا سفارش شما ثبت نهایی شود. 🙏"
)


def _kb_dict(kb_data: Any) -> dict[str, Any]:
    if kb_data is None:
        return {}
    if isinstance(kb_data, dict) and "payment" in kb_data:
        cfg = kb_data.get("payment") or {}
        return cfg if isinstance(cfg, dict) else {"link": cfg}
    if isinstance(kb_data, dict):
        return kb_data
    data = getattr(kb_data, "data", None)  # BusinessKB instance
    if isinstance(data, dict):
        cfg = data.get("payment") or {}
        return cfg if isinstance(cfg, dict) else {}
    return {}


def format_amount(amount: Any, currency: str = "") -> str:
    """Format a number with thousands separators (+ optional currency)."""
    try:
        n = float(amount)
        s = f"{n:,.0f}" if n.is_integer() else f"{n:,.2f}"
    except (TypeError, ValueError):
        s = str(amount)
    return f"{s} {currency}".strip()


def get_payment_config(kb_data: Any = None) -> dict[str, str]:
    """Return {'link', 'template'} merged over defaults."""
    cfg = _kb_dict(kb_data)
    link = str(cfg.get("link") or cfg.get("url") or DEFAULT_LINK)
    template = str(cfg.get("template") or cfg.get("message") or DEFAULT_TEMPLATE)
    extra = {k: str(v) for k, v in cfg.items() if k not in ("link", "url", "template", "message")}
    return {"link": link, "template": template, **extra}


def build_payment_message(
    amount: Any,
    kb_data: Any = None,
    link: Optional[str] = None,
    currency: str = "",
    template: Optional[str] = None,
    **extra: Any,
) -> str:
    """Format the Persian payment message with amount + link."""
    cfg = get_payment_config(kb_data)
    final_link = link or cfg["link"]
    tpl = template or cfg["template"]
    ctx = {"amount": format_amount(amount, currency), "link": final_link, **extra}
    try:
        return tpl.format(**ctx)
    except (KeyError, IndexError):
        return f"{tpl}\nمبلغ: {ctx['amount']}\nلینک پرداخت: {final_link}"


class PaymentSender:
    """Convenience wrapper bound to one KB snapshot."""

    def __init__(self, kb_data: Any = None, **kwargs: Any):
        if kb_data is None and "kb" in kwargs:
            kb_data = kwargs["kb"]
        self.kb_data = kb_data
        self.config = get_payment_config(kb_data)

    def reload(self, kb_data: Any = None) -> dict[str, str]:
        if kb_data is not None:
            self.kb_data = kb_data
        else:
            data = getattr(self.kb_data, "data", None)
            if isinstance(data, dict):  # hot-reload BusinessKB
                getattr(self.kb_data, "maybe_reload", lambda: None)()
        self.config = get_payment_config(self.kb_data)
        return self.config

    def payment_message(
        self,
        amount: Any,
        link: Optional[str] = None,
        currency: str = "",
        **extra: Any,
    ) -> str:
        self.reload()
        return build_payment_message(
            amount, self.kb_data, link=link, currency=currency, **extra
        )

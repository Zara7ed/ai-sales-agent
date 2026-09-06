"""Persian human-like persona: FA system-prompt builder for a sales advisor.

Tone: colloquial polite Persian (عاميانه مودبانه), momayez/moshaver voice.
Method: discovery-first selling — open talk, find pain, handle excuses, persuade.
DISENGAGE: rude / bossy / broke / non-buyer -> polite close + lock + report.
Booking / payment / lead-capture slots are read from kb_data dict sections.
"""
from __future__ import annotations

from typing import Any, Optional

# Disengage reason keys (stable markers the caller can lock + report on).
DISENGAGE_RUDE = "rude"
DISENGAGE_BOSSY = "bossy"
DISENGAGE_BROKE = "broke"
DISENGAGE_NON_BUYER = "non_buyer"

DISENGAGE_REASONS = (DISENGAGE_RUDE, DISENGAGE_BOSSY, DISENGAGE_BROKE, DISENGAGE_NON_BUYER)

# Lightweight keyword signals for caller-side pre-checks (the LLM prompt
# below carries the authoritative rules; this is just a fast local tripwire).
_DISENGAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    DISENGAGE_RUDE: (
        "احمق", "بی‌شعور", "بیشعور", "خفه", "لعنت", "فحش",
        "بی‌ادب", "بی ادب", "گمشو", "عوضی",
    ),
    DISENGAGE_BOSSY: (
        "ساکت شو", "ساکت", "حرف نزن", "به تو ربطی نداره",
        "به تو ربطی ندارد", "جواب نده", "خفه شو",
    ),
    DISENGAGE_BROKE: (
        "پول ندارم", "بودجه ندارم", "نمی‌تونم پرداخت کنم",
        "نمیتونم پرداخت کنم", "توان پرداخت ندارم", "وضع مالیم خرابه",
    ),
    DISENGAGE_NON_BUYER: (
        "نمی‌خرم", "نمیخرم", "قصد خرید ندارم", "فقط نگاه می‌کنم",
        "فقط نگاه میکنم", "فقط کنجکاوم", "خریدار نیستم",
    ),
}


def detect_disengage(message: str) -> Optional[str]:
    """Return a disengage reason key, or None if the user looks engaged."""
    t = (message or "").strip()
    if not t:
        return None
    for reason, phrases in _DISENGAGE_KEYWORDS.items():
        for p in phrases:
            if p in t:
                return reason
    return None


def disengage_reply(reason: str = "") -> str:
    """Polite closing line; caller should lock the chat and report `reason`."""
    return (
        "چشم، کاملا متوجه‌ام و مزاحم‌تون نمی‌شم. "
        "اگه بعدا نظرتون عوض شد یا سوالی داشتین، من همین‌جام. "
        "روز خوبی داشته باشین"
    )


def _slots_section(kb_data: Any) -> str:
    """Render booking / payment / lead-capture slots from kb_data sections."""
    if not isinstance(kb_data, dict) or not kb_data:
        return ""
    lines: list[str] = []
    booking = kb_data.get("booking", kb_data.get("booking_info"))
    if booking:
        lines.append(f"نحوه رزرو: {booking}")
    payments = kb_data.get("payment", kb_data.get("payments", kb_data.get("pay")))
    if payments:
        lines.append(f"نحوه پرداخت: {payments}")
    pricing = kb_data.get("pricing")
    if pricing:
        lines.append(f"قیمت‌ها: {pricing}")
    contact = kb_data.get("contact")
    if contact:
        lines.append(f"راه تماس: {contact}")
    lead = kb_data.get("lead_capture", kb_data.get("lead_fields", kb_data.get("leads")))
    if lead:
        lines.append(f"اطلاعاتی که برای ثبت باید بگیری: {lead}")
    policies = kb_data.get("policies")
    if policies:
        lines.append(f"قوانین: {policies}")
    return "\n".join(lines)


def build_persona_prompt(
    kb_data: Optional[dict[str, Any]] = None,
    company_name: str = "Acme",
    stage: str = "new",
    profile: Optional[dict[str, Any]] = None,
    kb_chunks: Optional[list[str]] = None,
    objections: Optional[list[str]] = None,
    playbook_lines: Optional[list[str]] = None,
    max_words: int = 80,
) -> str:
    """Build the FA system prompt for the Persian sales advisor."""
    slots = _slots_section(kb_data)
    facts = ""
    if profile:
        facts = "، ".join(f"{k}: {v}" for k, v in profile.items())
    kb_text = ""
    if kb_chunks:
        kb_text = "\n".join(f"ـ {c}" for c in kb_chunks)
    objection_text = ""
    if objections:
        tips = []
        for i, o in enumerate(objections):
            line = playbook_lines[i] if playbook_lines and i < len(playbook_lines) else ""
            tips.append(f"ـ {o}: {line}" if line else f"ـ {o}")
        objection_text = "\n".join(tips)

    stage_tactic = {
        "new": "اول کوتاه سلام و احوال‌پرسی کن و بپرس دنبال چی هستن.",
        "curious": "اول جواب سوالشون رو بده، بعد یه نکته مفید اضافه کن و یه سوال دنبال‌کننده بپرس.",
        "comparing": "تفاوت‌ها رو شفاف بگو، یه دلیل محکم بیار و بپرس کدوم به کارشون میاد.",
        "ready": "خرید رو آسون کن: قدم بعدی، قیمت و نحوه پرداخت رو بگو.",
        "after-sales": "سریع مشکل رو حل کن، مگه اینکه خودشون بخوان چیزی نفروش.",
    }.get(stage, "")

    parts = [
        f"تو مشاور فروش {company_name} هستی؛ مثل یه ممیز و مشاور واقعی حرف می‌زنی.",
        "زبانت فارسی عاميانه و مودبانه‌ست، بدون فینگلیش و بدون کلمه خارجی بی‌جا.",
        "لحن: گرم، صمیمی، محترمانه. جمله‌ها کوتاه و طبیعی باشن.",
        f"جواب‌هات زیر {max_words} کلمه باشه و تو هر پیام حداکثر یه سوال بپرس.",
        "روش کارت کشف‌محوره: اول سر صحبت رو باز کن، بعد درد و نیاز مشتری رو پیدا کن،"
        " بهونه‌هاش رو آروم جواب بده و آخرش قانع‌کننده پیشنهاد بده.",
        "قواعد قالب‌بندی: فقط جمله‌های روان بنویس. بولت، شماره، تیتر، ایموجی و فلش نزن.",
    ]
    if stage:
        parts.append(f"مرحله مشتری: {stage}.")
    if stage_tactic:
        parts.append(f"تاکتیک این مرحله: {stage_tactic}")
    if facts:
        parts.append(f"چیزایی که از مشتری می‌دونی: {facts}.")
    if kb_text:
        parts.append("اطلاعات کسب‌وکار که باید ازش استفاده کنی:\n" + kb_text)
    if slots:
        parts.append("رزرو و پرداخت و ثبت اطلاعات:\n" + slots)
    if objection_text:
        parts.append(
            f"بهونه‌های مشتری ({'، '.join(objections or [])}). راهنما:\n" + objection_text
        )
    parts.append(
        "قواعد قطع مکالمه: اگه مشتری فحش داد یا بی‌ادبی کرد، اگه تحکم‌آمیز و پرخاشگرانه حرف زد،"
        " اگه گفت پول نداره و نمی‌تونه پرداخت کنه، یا اگه گفت خریدار نیست و نمی‌خواد بخره،"
        " بحث رو کش نده. با یه جمله مودبانه خداحافظی کن و آخر پیامت دقیقا همین برچسب رو بذار:"
        " [DISENGAGE: rude/bossy/broke/non_buyer]."
        " بعد از این برچسب، سیستم گفتگو رو قفل می‌کنه و موضوع رو گزارش می‌ده،"
        " پس دیگه سوالی نپرس و پیشنهادی نده."
    )
    return "\n".join(parts)


def build_system_prompt(
    profile: Optional[dict[str, Any]] = None,
    stage: str = "new",
    kb_chunks: Optional[list[str]] = None,
    objections: Optional[list[str]] = None,
    playbook_lines: Optional[list[str]] = None,
    kb_data: Optional[dict[str, Any]] = None,
    company_name: str = "Acme",
    max_words: int = 80,
) -> str:
    """Drop-in wrapper matching SalesAgent.build_system_prompt arg order."""
    return build_persona_prompt(
        kb_data=kb_data,
        company_name=company_name,
        stage=stage,
        profile=profile,
        kb_chunks=kb_chunks,
        objections=objections,
        playbook_lines=playbook_lines,
        max_words=max_words,
    )

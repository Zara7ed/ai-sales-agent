"""SalesAgent: stage-aware, objection-aware selling brain.

Pipeline per user message:
  1. Classify buying stage (new/curious/comparing/ready/after-sales).
  2. Detect objections (price/trust/need/timing) and fetch playbook lines.
  3. Retrieve KB chunks relevant to the message.
  4. Build a system prompt from KB + profile + stage (+ playbook).
  5. Call the LLM router (with offline fallback reply if no LLM available).
  6. Enforce short/direct/human-like replies (max words, configurable).
  7. Persist history + stage, return reply + stage + analytics event.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

STAGES = ("new", "curious", "comparing", "ready", "after-sales")
OBJECTIONS = ("price", "trust", "need", "timing")

_STAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "after-sales": (
        "refund", "return", "broken", "not working", "support", "warranty",
        "cancel", "receipt", "deliver", "shipping status", "track",
    ),
    "ready": (
        "buy now", "i'll take", "i will take", "checkout", "pay", "order now",
        "place order", "sign me up", "let's do it", "how to pay", "card",
    ),
    "comparing": (
        "vs", "versus", "compare", "comparison", "alternative", "competitor",
        "better than", "difference between", "which one", "pros and cons",
    ),
    "curious": (
        "what", "how", "tell me", "price", "cost", "feature", "do you offer",
        "interested", "info", "detail", "?",
    ),
}

_OBJECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "price": (
        "expensive", "too much", "cheaper", "discount", "cost too",
        "can't afford", "cannot afford", "overpriced", "price", "budget",
    ),
    "trust": (
        "scam", "trust", "legit", "reliable", "guarantee", "reviews",
        "refund", "risk", "safe", "credible",
    ),
    "need": (
        "don't need", "do not need", "not sure", "useless", "why should",
        "not for me", "no use",
    ),
    "timing": (
        "later", "not now", "think about", "next month", "busy",
        "call back", "timing", "hurry",
    ),
}

_DEFAULT_PLAYBOOK: dict[str, str] = {
    "price": "Acknowledge the budget concern, restate value per cost, offer options.",
    "trust": "Share proof: guarantees, reviews, policies. Lower perceived risk.",
    "need": "Ask about their goal, link one concrete benefit to it.",
    "timing": "Respect timing, create a light reason to act now, offer next step.",
}


def _contains(text: str, phrases: tuple[str, ...]) -> bool:
    return any(p in text for p in phrases)


@dataclass
class AgentReply:
    reply: str
    stage: str
    event: dict[str, Any]


class SalesAgent:
    """Stage + objection aware sales/support agent over an LLM router."""

    def __init__(
        self,
        kb: Any,  # BusinessKB
        store: Any,  # ConversationStore
        router: Any = None,  # LLMRouter or compatible .chat()
        company_name: str = "Acme",
        tone: str = "friendly, direct, human-like",
        max_words: int = 80,
        time_fn: Callable[[], float] | None = None,
    ):
        self.kb = kb
        self.store = store
        self.router = router
        self.company_name = company_name
        self.tone = tone
        self.max_words = max_words
        self._now = time_fn or time.time

    # -- classification ----------------------------------------------------
    def classify_stage(self, message: str, current: str = "new") -> str:
        """Rule-based buying-stage classifier (LLM-free, deterministic)."""
        t = message.lower()
        for stage in ("after-sales", "ready", "comparing", "curious"):
            if _contains(t, _STAGE_KEYWORDS[stage]):
                return stage
        # Mild progression: a second engaged message moves new -> curious.
        if current == "new" and len(t.split()) > 2:
            return "curious"
        return current if current in STAGES else "new"

    def detect_objections(self, message: str) -> list[str]:
        """Return objection types present in the message."""
        t = message.lower()
        return [o for o in OBJECTIONS if _contains(t, _OBJECTION_KEYWORDS[o])]

    def playbook(self, objections: list[str]) -> list[str]:
        """Fetch playbook guidance: KB objection_handlers first, defaults aft."""
        handlers: Any = {}
        try:
            handlers = self.kb.get_section("objection_handlers") or {}
        except Exception:
            handlers = {}
        lines: list[str] = []
        for o in objections:
            hit: Optional[str] = None
            if isinstance(handlers, dict):
                hit = handlers.get(o)
            elif isinstance(handlers, list):
                for h in handlers:
                    if isinstance(h, dict) and h.get("objection", "").lower() == o:
                        hit = h.get("response")
                        break
                    elif isinstance(h, str) and o in h.lower():
                        hit = h
                        break
            lines.append(str(hit) if hit else _DEFAULT_PLAYBOOK[o])
        return lines

    # -- prompting ----------------------------------------------------------
    def build_system_prompt(
        self,
        profile: dict[str, Any],
        stage: str,
        kb_chunks: list[str],
        objections: list[str],
        playbook_lines: list[str],
    ) -> str:
        parts = [
            f"You are a sales & support agent for {self.company_name}.",
            f"Tone: {self.tone}. Keep replies under {self.max_words} words,"
            " short, direct, human-like. One question max per reply.",
            f"Customer buying stage: {stage}.",
        ]
        if profile:
            facts = ", ".join(f"{k}: {v}" for k, v in profile.items())
            parts.append(f"Known about customer: {facts}.")
        if kb_chunks:
            parts.append("Business facts to use:\n" + "\n".join(f"- {c}" for c in kb_chunks))
        if objections:
            tips = "\n".join(f"- {o}: {line}" for o, line in zip(objections, playbook_lines))
            parts.append(f"Customer objections detected ({', '.join(objections)}). Playbook:\n{tips}")
        stage_hint = {
            "new": "Greet briefly and ask what they need.",
            "curious": "Answer the question, add one helpful detail, ask a follow-up.",
            "comparing": "Differentiate clearly, one proof point, ask which fits.",
            "ready": "Make buying easy: next step, price, how to pay.",
            "after-sales": "Solve fast, no selling unless asked.",
        }.get(stage, "")
        if stage_hint:
            parts.append(f"Stage tactic: {stage_hint}")
        return "\n".join(parts)

    # -- reply ---------------------------------------------------------------
    @staticmethod
    def _enforce_length(text: str, max_words: int) -> str:
        words = text.split()
        if len(words) <= max_words:
            return text.strip()
        cut = " ".join(words[:max_words]).rstrip(" ,;:")
        # Avoid mid-sentence cutoff when a sentence ends inside the budget.
        sentences = re.split(r"(?<=[.!?])\s+", cut)
        if len(sentences) > 1 and len(sentences[-1].split()) < 5:
            cut = " ".join(sentences[:-1])
        return cut.rstrip() + "…"

    def _fallback_reply(
        self, stage: str, objections: list[str], kb_chunks: list[str]
    ) -> str:
        """Offline reply used when no router/LLM is configured or fails."""
        if stage == "after-sales":
            return "Sorry for the trouble — tell me what happened and I'll sort it out. What's your order number?"
        if objections:
            if kb_chunks:
                first = kb_chunks[0] if kb_chunks else ""
                bits = " ".join(first.split()[:30])
                return (
                    f"Fair point on {objections[0]}. Here's the short version: {bits} "
                    "Want me to tailor it to your case?"
                ).strip()
            return (
                f"Fair point on {objections[0]} — tell me a bit more about "
                "your budget and goals, and I'll find the best fit. What matters most?"
            )
        if stage == "ready":
            return "Great — I can set that up now. Which option do you want, and how would you like to pay?"
        if stage == "comparing":
            first = kb_chunks[0] if kb_chunks else "happy to break down the differences"
            return f"Good question — {first}. Which matters more to you: price or features?"
        if kb_chunks:
            first = " ".join(kb_chunks[0].split()[:40])
            return f"{first} Want me to go deeper on anything?"
        return "Hi! What are you looking for today?"

    def handle(
        self,
        user_id: str,
        message: str,
        channel: str = "default",
        history_limit: int = 20,
    ) -> AgentReply:
        """Process one user message; returns reply + stage + analytics event."""
        profile = self.store.get_profile(user_id)
        prev_stage = self.store.get_stage(user_id)
        stage = self.classify_stage(message, prev_stage)
        objections = self.detect_objections(message)
        playbook_lines = self.playbook(objections)
        kb_chunks = self.kb.search(message, top_k=3)

        system = self.build_system_prompt(
            profile, stage, kb_chunks, objections, playbook_lines
        )
        history = self.store.get_history(user_id, channel, history_limit)
        llm_messages = [{"role": "system", "content": system}] + history + [
            {"role": "user", "content": message}
        ]

        text: str
        provider = "fallback"
        model = ""
        if self.router is not None:
            try:
                res = self.router.chat(llm_messages)
                text = res.text.strip() or self._fallback_reply(stage, objections, kb_chunks)
                provider = getattr(res, "provider", "router")
                model = getattr(res, "model", "")
            except Exception:
                text = self._fallback_reply(stage, objections, kb_chunks)
        else:
            text = self._fallback_reply(stage, objections, kb_chunks)

        text = self._enforce_length(text, self.max_words)

        self.store.save_message(user_id, "user", message, channel)
        self.store.save_message(user_id, "assistant", text, channel)
        self.store.set_stage(user_id, stage)

        event = {
            "type": "agent_reply",
            "user_id": user_id,
            "channel": channel,
            "prev_stage": prev_stage,
            "stage": stage,
            "objections": objections,
            "kb_hits": len(kb_chunks),
            "provider": provider,
            "model": model,
            "reply_words": len(text.split()),
            "ts": self._now(),
        }
        return AgentReply(reply=text, stage=stage, event=event)

"""Generation half of PawPal+ RAG: the Gemini client wrapper.

Two answering styles live here, and comparing them is the whole lesson:

- :meth:`GeminiClient.naive_answer` — ask the model straight out, no retrieval.
  Fluent, confident, and free to invent a dosage.
- :meth:`GeminiClient.answer_from_snippets` — answer *only* from the passages
  retrieved by :class:`care_kb.CareKnowledgeBase`, cite them, and refuse when
  they are not enough.

The API key comes from ``GEMINI_API_KEY``. If it is missing, constructing the
client raises ``RuntimeError`` and PawPal+ falls back to retrieval-only mode
rather than breaking.
"""

from __future__ import annotations

import logging
import os
from typing import Iterable, Optional

from google import genai

from care_kb import REFUSAL

# Same logger as care_advisor, fetched by name rather than by importing that
# module — the two stay decoupled and both land in the one PawPal log.
logger = logging.getLogger("pawpal")

# One place to change the model for the whole project.
GEMINI_MODEL_NAME = "gemini-flash-lite-latest"

# Values that are present but not real keys. `.env.example` ships the first one,
# and copying that file without editing it is the most likely setup mistake.
PLACEHOLDER_KEYS = frozenset(
    {"your_api_key_here", "your-api-key-here", "YOUR_API_KEY_HERE", "changeme"}
)

# Standing rules for every grounded answer. Kept separate from the question so
# the prompt reads as: role -> rules -> evidence -> question.
SYSTEM_RULES = """
You are PawPal+, a careful pet care planning assistant.

Rules:
- Use only the information in the pet care notes provided below. Do not add
  advice, amounts, frequencies, or medication guidance that is not in them.
- You may reason about the owner's current schedule (shown below) to say when a
  task should go, but the care guidance itself must come from the notes.
- If the notes do not cover the question, reply with exactly this sentence and
  nothing else: "{refusal}"
- Never diagnose an illness and never suggest changing a medication or dose.
  Direct anything medical to a veterinarian.
- Finish with a "Sources:" line listing the note sections you relied on.
- Keep the answer under 150 words and practical.
""".strip()


class GeminiClient:
    """Thin wrapper around the Gemini model used for both answering modes."""

    def __init__(self, model_name: str = GEMINI_MODEL_NAME) -> None:
        """Create a Gemini client, or raise ``RuntimeError`` if no usable key is set.

        "Usable" excludes the placeholder shipped in ``.env.example``. Copying
        that file to ``.env`` without editing it is the obvious first mistake, and
        a non-empty placeholder would otherwise pass this check: the app would
        report RAG as available, then fail on every single question with an auth
        error. Failing here instead degrades cleanly to retrieval-only and says
        exactly what to fix.
        """
        api_key = (os.getenv("GEMINI_API_KEY") or "").strip()

        if not api_key:
            raise RuntimeError(
                "Missing GEMINI_API_KEY environment variable. "
                "Add it to a .env file to enable RAG answers. "
                "Retrieval-only mode works without it."
            )
        if api_key in PLACEHOLDER_KEYS:
            raise RuntimeError(
                f"GEMINI_API_KEY is still the placeholder value ({api_key!r}). "
                "Your .env looks like an unedited copy of .env.example — replace "
                "it with a real key from https://aistudio.google.com/apikey. "
                "Retrieval-only mode works without one."
            )

        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)

    # --- baseline: no retrieval -------------------------------------------

    def naive_answer(self, question: str) -> str:
        """Answer with no retrieved context at all — the ungrounded baseline.

        Kept so the app can show the two answers side by side. This is the
        version that will happily state a confident dosage it has no source for.
        """
        prompt = (
            "You are a pet care assistant. Answer this pet owner's question:\n\n"
            f"{question}"
        )
        return self._generate(prompt)

    # --- RAG: grounded in retrieved snippets ------------------------------

    def answer_from_snippets(
        self,
        question: str,
        snippets: Iterable,
        schedule_context: Optional[str] = None,
    ) -> str:
        """Answer ``question`` using only ``snippets`` (plus optional schedule).

        ``snippets`` is the list of :class:`care_kb.Snippet` objects chosen by
        the knowledge base. Each is rendered with its citation label so the
        model can name its sources — and so a reader can check them.

        ``schedule_context`` is a plain-text summary of the owner's real tasks
        (see :meth:`care_advisor.CareAdvisor.schedule_context`). It is what turns
        a generic doc lookup into advice about *this* owner's actual day.

        With no snippets there is nothing to ground an answer in, so this
        refuses without spending an API call.
        """
        snippets = list(snippets)
        if not snippets:
            return REFUSAL

        notes = "\n\n".join(f"### {s.label}\n{s.text}" for s in snippets)

        context_section = ""
        if schedule_context:
            context_section = (
                "\nThe owner's current schedule:\n"
                f"{schedule_context}\n"
            )

        prompt = f"""{SYSTEM_RULES.format(refusal=REFUSAL)}

Pet care notes:
{notes}
{context_section}
Owner's question:
{question}
"""
        return self._generate(prompt)

    # --- internals --------------------------------------------------------

    def _generate(self, prompt: str) -> str:
        """Send ``prompt`` to Gemini and return the text, or an error string.

        Network and API failures are returned as readable text instead of
        raising, so one bad call shows a message in the UI rather than taking
        down the app mid-schedule.
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
            text = (response.text or "").strip()
            if not text:
                # An empty response is a failure that looks like success — log it
                # rather than handing the UI a blank answer with no explanation.
                logger.warning(
                    "Empty response from %s (prompt %d chars)",
                    self.model_name, len(prompt),
                )
            return text
        except Exception as exc:  # noqa: BLE001 - surfaced to the user as text
            # Logged with a traceback so the cause survives; returned as text so
            # one failed call degrades the answer instead of crashing the app.
            logger.error(
                "LLM call failed (%s): %s", type(exc).__name__, exc, exc_info=True
            )
            return f"Could not reach the language model. ({type(exc).__name__}: {exc})"

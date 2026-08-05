"""Retrieval half of PawPal+ RAG: the pet care knowledge base.

This is the ``R`` in RAG. It owns everything that happens *before* the LLM:

1. **Load**   — read the markdown files in ``knowledge/``
2. **Chunk**  — split each file into one passage per ``##`` heading, so a
                retrieved snippet is a focused section ("Cats") instead of a
                whole 60-line document
3. **Index**  — build an inverted index mapping each word to the chunks it
                appears in, so scoring only touches plausible candidates
4. **Score**  — rank candidate chunks by how well they match the question
5. **Retrieve** — return the best ``top_k`` chunks

No LLM is involved in this module at all, which is the point: retrieval is
testable on its own (see ``tests/test_care_kb.py``) and usable on its own (the
"retrieval only" mode in the app).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

# The one canonical refusal sentence. It lives here, in the module with no LLM
# dependency, because three separate places must agree on it *exactly*: the RAG
# prompt instructs the model to emit it, retrieval-only mode falls back to it,
# and rag_evaluation.py counts it to measure how often the assistant abstains.
REFUSAL = "I do not know based on the pet care notes I have."

# Words that appear in almost every question and therefore carry no signal
# about *which* document is relevant. Dropping them stops "How do I ..." from
# matching every chunk that happens to contain "do".
STOPWORDS = frozenset(
    """
    a an the and or but if is are was were be been being do does did doing
    of in on at to for from with without about into over under by as than then
    i my me we our you your it its this that these those there here
    how what when where which who why should can could would will shall may
    much many long often need needs needed have has had get got give gives
    """.split()
)

# Splits text into bare words: letters/digits/apostrophes, everything else is a
# separator. Keeps "12" and "don't" whole, drops punctuation and markdown.
_WORD_RE = re.compile(r"[a-z0-9']+")

# How much a boost term counts relative to a word the user actually typed.
# Boost terms (the pet's species, name, medication) are context the owner did
# not ask about, so they may *reorder* results but must not outvote the question:
# at full weight, a household with two medicated pets pushed "Feeding around
# medication" above "Cats" for the question "how many times a day should I feed
# my cat?". Expansion should break ties, not decide them.
BOOST_WEIGHT = 0.3

# Minimum score a chunk must reach to count as evidence. A chunk that merely
# shares one generic word ("pet") with the question scores about 1.0 — enough to
# look like a match, not enough to answer from. Anything below this floor is
# discarded, which is what lets "what is the best pet insurance?" retrieve
# nothing and get an honest refusal instead of a confident answer built on the
# grooming section. Raise it for stricter refusals, lower it for more recall.
MIN_SCORE = 2.0


def stem(word: str) -> str:
    """Fold a word to a crude common form so related spellings match.

    Without this, keyword retrieval misses the obvious: a question about a
    ``cat`` never matches the section headed ``Cats``, and ``bathe`` never
    matches ``Bathing``. Both are the same question to an owner.

    The rules are deliberately crude — strip ``-ing``, ``-ies``, ``-es``,
    ``-ed``, ``-s``, then a trailing ``-e``::

        cats, cat            -> cat
        bathe, bathing       -> bath
        doses, dose          -> dos
        feeding, feeds       -> feed
        vomiting, vomited    -> vomit

    The folded forms are not real words, and that is fine: queries and
    documents go through the same function, so they only have to agree with
    each other. Length guards keep short words (``is``, ``has``) intact.
    """
    if len(word) > 5 and word.endswith("ing"):
        word = word[:-3]
    elif len(word) > 4 and word.endswith("ies"):
        word = word[:-3] + "y"
    elif len(word) > 4 and word.endswith("es"):
        word = word[:-2]
    elif len(word) > 4 and word.endswith("ed"):
        word = word[:-2]   # "vomited" -> "vomit", matching "vomiting"
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]

    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]   # so "bathe" lands on the same stem as "bathing"
    return word


def tokenize(text: str) -> List[str]:
    """Lowercase ``text`` and return its meaningful, stemmed words.

    Punctuation and stopwords are dropped and the rest are folded by
    :func:`stem`, so ``"How often do I bathe a dog?"`` becomes
    ``["bath", "dog"]`` — the two words that should actually drive retrieval.

    Stopwords are filtered *before* stemming so the list can stay written in
    ordinary English.
    """
    return [
        stem(word)
        for word in _WORD_RE.findall(text.lower())
        if word not in STOPWORDS
    ]


@dataclass(frozen=True)
class Snippet:
    """One retrievable passage: a single ``##`` section of one knowledge file.

    ``source`` is the filename (``"FEEDING.md"``) and ``heading`` is the section
    title (``"Cats"``). Together they form the citation the LLM is asked to
    quote back, which is how an answer stays auditable.
    """

    source: str
    heading: str
    text: str
    score: float = 0.0

    @property
    def label(self) -> str:
        """Return a short human-readable citation, e.g. ``FEEDING.md › Cats``."""
        return f"{self.source} › {self.heading}" if self.heading else self.source

    def __str__(self) -> str:
        """Return the citation plus the passage text, ready to print."""
        return f"[{self.label}]\n{self.text}"


class CareKnowledgeBase:
    """A tiny keyword search engine over the ``knowledge/`` markdown corpus.

    Usage::

        kb = CareKnowledgeBase()
        for snippet in kb.retrieve("how often should I bathe my dog?"):
            print(snippet.label, snippet.score)
    """

    def __init__(self, knowledge_folder: str | Path = "knowledge") -> None:
        """Load the corpus, chunk it, and build the inverted index once."""
        # Resolve relative to this file, not the current working directory, so
        # the app works whether it is launched from the project root or not.
        folder = Path(knowledge_folder)
        if not folder.is_absolute():
            folder = Path(__file__).parent / folder

        self.knowledge_folder = folder
        self.documents = self.load_documents()          # [(filename, text)]
        self.chunks = self.build_chunks(self.documents)  # [Snippet]
        self.index = self.build_index(self.chunks)       # word -> {chunk ids}

    # --- load -------------------------------------------------------------

    def load_documents(self) -> List[tuple]:
        """Read every ``.md``/``.txt`` file in the knowledge folder.

        Returns a list of ``(filename, text)`` tuples, sorted by filename so
        the chunk ids (and therefore tie-breaking) are stable between runs.
        Returns an empty list if the folder is missing — the app degrades to
        "no knowledge base" rather than crashing.
        """
        if not self.knowledge_folder.is_dir():
            return []

        docs = []
        for path in sorted(self.knowledge_folder.iterdir()):
            if path.suffix.lower() in {".md", ".txt"}:
                docs.append((path.name, path.read_text(encoding="utf8")))
        return docs

    # --- chunk ------------------------------------------------------------

    def build_chunks(self, documents: Iterable[tuple]) -> List[Snippet]:
        """Split each document into one :class:`Snippet` per ``##`` section.

        Chunking matters more than it looks: whole files are mostly irrelevant
        text, which both dilutes the match score and wastes context window. A
        question about cats should retrieve the "Cats" section of FEEDING.md,
        not all of FEEDING.md.

        Text before the first ``##`` (the title and intro) becomes a chunk with
        an empty heading so nothing is silently dropped.
        """
        chunks: List[Snippet] = []

        for filename, text in documents:
            heading = ""
            buffer: List[str] = []

            def flush() -> None:
                """Turn the lines collected so far into a Snippet, if any."""
                body = "\n".join(buffer).strip()
                if body:
                    chunks.append(Snippet(source=filename, heading=heading, text=body))

            for line in text.splitlines():
                if line.startswith("## "):
                    flush()                      # close out the previous section
                    heading = line[3:].strip()   # start a new one
                    buffer = []
                else:
                    buffer.append(line)
            flush()                              # don't lose the last section

        return chunks

    # --- index ------------------------------------------------------------

    def build_index(self, chunks: Iterable[Snippet]) -> Dict[str, Set[int]]:
        """Build an inverted index: word -> set of chunk positions.

        Example::

            {"medication": {2, 5, 9}, "bathe": {11}}

        Scoring then only has to look at chunks that share at least one word
        with the question, instead of every chunk in the corpus.
        """
        index: Dict[str, Set[int]] = {}
        for chunk_id, chunk in enumerate(chunks):
            for word in set(tokenize(f"{chunk.heading}\n{chunk.text}")):
                index.setdefault(word, set()).add(chunk_id)
        return index

    # --- score ------------------------------------------------------------

    def score_chunk(
        self,
        query_words: Iterable[str],
        chunk: Snippet,
        boost_words: Iterable[str] = (),
    ) -> float:
        """Return how well ``chunk`` matches the question, plus context terms.

        Each matched word contributes three signals, deliberately simple enough
        to reason about:

        - **coverage** (1.0 per distinct word found) — matching two of the
          question's words beats matching one word twice
        - **heading match** (+2.0) — a word in the section title is strong
          evidence the whole section is on-topic ("Cats" for a cat question)
        - **repetition** (+0.25 per extra mention, capped) — a small nudge, kept
          small on purpose so a long rambling chunk can't outrank a precise one

        ``boost_words`` are scored the same way but multiplied by
        :data:`BOOST_WEIGHT`, so context the owner never typed can nudge the
        ranking without taking it over. Words in both sets count once, at full
        weight.
        """
        body_words = tokenize(chunk.text)
        heading_words = set(tokenize(chunk.heading))

        def contribution(word: str) -> float:
            """Score one word against this chunk (0.0 if it does not appear)."""
            occurrences = body_words.count(word)
            in_heading = word in heading_words

            if not occurrences and not in_heading:
                return 0.0                  # this word isn't here at all

            value = 1.0                     # coverage
            if in_heading:
                value += 2.0                # heading match
            if occurrences > 1:
                value += 0.25 * min(occurrences - 1, 4)   # repetition
            return value

        asked = set(query_words)
        score = sum(contribution(word) for word in asked)

        # Context terms, discounted, and never double-counted with the question.
        score += BOOST_WEIGHT * sum(
            contribution(word) for word in set(boost_words) - asked
        )
        return score

    # --- retrieve ---------------------------------------------------------

    def retrieve(
        self,
        query: str,
        top_k: int = 3,
        boost_terms: Optional[Iterable[str]] = None,
        min_score: float = MIN_SCORE,
    ) -> List[Snippet]:
        """Return the ``top_k`` best-matching snippets, highest score first.

        ``boost_terms`` lets the caller widen the query with context the user
        did not type — PawPal+ passes the pet's species and medication name, so
        "how often should I feed them?" can still find the *cat* section. See
        :meth:`CareAdvisor.expanded_terms`.

        Chunks below ``min_score`` are dropped, so an off-topic question returns
        an empty list. That empty list is what lets the assistant say "I do not
        know" instead of answering from thin air, so the floor is a safety
        feature, not just tidiness.
        """
        query_words = tokenize(query)
        boost_words = [
            word for term in (boost_terms or []) for word in tokenize(term)
        ]

        if not query_words or not self.chunks:
            return []

        # Candidate set from the inverted index: only chunks sharing a word.
        candidate_ids: Set[int] = set()
        for word in set(query_words) | set(boost_words):
            candidate_ids |= self.index.get(word, set())

        scored = []
        for chunk_id in candidate_ids:
            chunk = self.chunks[chunk_id]
            score = self.score_chunk(query_words, chunk, boost_words)
            if score >= min_score:
                # Snippet is frozen, so attach the score by making a copy.
                scored.append(Snippet(chunk.source, chunk.heading, chunk.text, score))

        # Sort by score descending; ties fall back to source/heading so the
        # order is deterministic (important for tests and for the eval harness).
        scored.sort(key=lambda s: (-s.score, s.source, s.heading))
        return scored[:top_k]

    # --- helpers ----------------------------------------------------------

    def full_corpus_text(self) -> str:
        """Return every document concatenated — the no-retrieval baseline.

        Used by the "naive LLM" mode, which stuffs the whole corpus into the
        prompt. Handy for showing *why* retrieval is worth doing: this grows
        without bound, a retrieved snippet set does not.
        """
        return "\n\n".join(text for _, text in self.documents)

    def __str__(self) -> str:
        """Return a one-line summary of the loaded corpus."""
        return (
            f"CareKnowledgeBase — {len(self.documents)} file(s), "
            f"{len(self.chunks)} chunk(s), {len(self.index)} indexed word(s)"
        )

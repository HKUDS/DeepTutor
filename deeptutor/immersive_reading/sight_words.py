"""Built-in vocabulary dictionary with simple English definitions.

Used as a deterministic fallback when LLM quiz generation fails —
ensures children always get word-meaning questions from the story.
"""

from __future__ import annotations

import random
import re
from collections import Counter

# ── Vocabulary ──────────────────────────────────────────────────────────────
# Each word maps to a short, simple definition a 4-8 year old can understand.
# Organized by difficulty: core sight words first, then story vocabulary.

VOCAB: dict[str, str] = {
    # — Core Dolch / sight words —
    "away": "not here, gone",
    "big": "very large",
    "blue": "the color of the sky",
    "can": "able to do it",
    "come": "to go to someone",
    "down": "toward the ground",
    "find": "to look for and see",
    "funny": "making you laugh",
    "help": "to do something for someone",
    "here": "in this place",
    "jump": "to go up in the air",
    "little": "small in size",
    "look": "to see with your eyes",
    "make": "to create something",
    "one": "the number 1",
    "play": "to have fun with a game",
    "red": "the color of an apple",
    "run": "to move very fast on your feet",
    "said": "spoke, talked",
    "see": "to look at something",
    "three": "the number 3",
    "two": "the number 2",
    "up": "toward the sky",
    "where": "what place",
    "yellow": "the color of the sun",
    "you": "the person I talk to",

    # — Question / connecting words —
    "what": "asking about a thing",
    "who": "asking about a person",
    "how": "asking in what way",
    "when": "asking at what time",
    "good": "nice, not bad",
    "hard": "not soft, firm",
    "soft": "not hard, squishy",
    "fast": "moving very quickly",
    "old": "not new, aged",
    "new": "not old, fresh",

    # — Nature words —
    "sun": "the bright star in the daytime sky",
    "rain": "water falling from clouds",
    "tree": "a tall plant with branches",
    "rock": "a hard stone on the ground",
    "grass": "the green plant on the ground",
    "twig": "a tiny branch from a tree",
    "flower": "a pretty plant that blooms",
    "leaf": "the green part of a tree",
    "snow": "white cold stuff from the sky",

    # — Animal words —
    "bug": "a tiny crawling insect",
    "cat": "a furry pet that says meow",
    "dog": "a furry pet that says woof",
    "pig": "a pink farm animal",
    "fox": "a wild animal like a small dog",
    "duck": "a bird that swims and says quack",
    "fish": "an animal that swims in water",
    "bird": "an animal that flies in the sky",
    "bear": "a big furry animal",

    # — Things / objects —
    "hat": "something you wear on your head",
    "box": "a container with four sides",
    "bed": "where you sleep at night",
    "bag": "something you carry things in",
    "ball": "a round thing you play with",
    "book": "pages with words you read",
    "pen": "something you write with",
    "mat": "a small rug on the floor",
    "sled": "something you slide on snow",
    "flag": "cloth on a pole for a country",
    "truck": "a big car that carries things",
    "vest": "a piece of clothing like a small jacket",
    "pants": "clothing you wear on your legs",
    "card": "a small piece of paper with a picture",
    "rock": "a hard stone you find outside",
    "rock": "a big stone on the ground",
    "pool": "a place filled with water to swim",
    "pan": "a flat thing you cook on",
    "pot": "a deep thing you cook in",

    # — Food words —
    "plum": "a small sweet purple fruit",
    "plums": "small sweet purple fruits",
    "snack": "a little bit of food you eat",
    "egg": "an oval food from a chicken",
    "ham": "meat from a pig",
    "milk": "the white drink from a cow",
    "cake": "a sweet baked treat for parties",
    "soup": "hot food you eat with a spoon",

    # — Body / action —
    "leg": "a part of your body you walk with",
    "hand": "the end of your arm, with fingers",
    "swim": "to move through water",
    "sit": "to put your bottom on something",
    "eat": "to put food in your mouth",
    "wash": "to clean with water",
    "wear": "to put clothes on your body",
    "fit": "to be the right size",

    # — Story words from Bob Books —
    "twin": "a brother or sister born at the same time",
    "pretty": "nice to look at",
    "dress": "clothing a girl wears",
    "stack": "a pile of things on top of each other",
    "dip": "a short swim or a quick go in water",
    "test": "to try something to see if it works",
    "long": "not short, big from end to end",
    "small": "not big, tiny",
    "lots": "many, a big amount",
    "thing": "an object, one stuff",
    "things": "objects, more than one stuff",
    "snack": "a little food between meals",
    "pancakes": "flat round cakes you eat for breakfast",
    "mag": "a short word for a magazine",
    "tag": "a game where you touch someone",
}

# Build a lookup that also handles singular/plural and capitalization
_WORD_LOOKUP: dict[str, str] = {}
for _w, _d in VOCAB.items():
    _WORD_LOOKUP[_w.lower()] = _d
    # Add simple plural/singular variants
    if _w.endswith("s") and len(_w) > 3:
        _WORD_LOOKUP.setdefault(_w[:-1].lower(), _d)  # plums -> plum
    elif not _w.endswith("s"):
        _WORD_LOOKUP.setdefault(_w + "s", _d)  # plum -> plums

# Pool of definitions for building distractor choices
_DEFINITION_POOL = list(set(VOCAB.values()))


def extract_words(text: str, min_freq: int = 1) -> list[tuple[str, int]]:
    """Find vocabulary words in text, ordered by frequency (most frequent first)."""
    words = re.findall(r"[A-Za-z]+", text.lower())
    freq = Counter(words)
    found: list[tuple[str, int]] = []
    seen: set[str] = set()
    for word, count in freq.most_common():
        if word in _WORD_LOOKUP and word not in seen and count >= min_freq:
            found.append((word, count))
            seen.add(word)
    return found


def generate_translation_quiz(
    text: str,
    *,
    num_questions: int = 3,
    seed: int | None = None,
) -> list[dict]:
    """Generate word-meaning questions from the story text.

    Prioritizes words that appear most often (frequency-based), so
    children practice the vocabulary they encounter repeatedly.

    Each question: "What does 'plums' mean?"
    Choices are 4 simple English definitions.
    """
    found = extract_words(text)
    if not found:
        return []

    rng = random.Random(seed if seed is not None else hash(text[:300]) % 100000)

    # Prefer high-frequency words, but add slight randomness so quizzes vary
    # Weight: frequency^2 so 3x appearances >> 1x
    weighted: list[str] = []
    for word, count in found:
        weight = count * count
        weighted.extend([word] * weight)
    rng.shuffle(weighted)

    # Deduplicate while preserving the randomized order
    targets: list[str] = []
    for w in weighted:
        if w not in targets:
            targets.append(w)
        if len(targets) >= num_questions:
            break

    if len(targets) < num_questions:
        # Fill from less frequent words
        for word, _ in found:
            if word not in targets:
                targets.append(word)
            if len(targets) >= num_questions:
                break

    questions: list[dict] = []
    for i, word in enumerate(targets):
        correct = _WORD_LOOKUP[word]

        # Build 3 plausible distractors
        # Prefer definitions that are short and different from the correct one
        candidates = [d for d in _DEFINITION_POOL if d != correct]
        rng.shuffle(candidates)
        distractors = candidates[:3]

        choices = [correct] + distractors
        rng.shuffle(choices)
        answer_index = choices.index(correct)

        questions.append({
            "id": f"q{i + 1}",
            "kind": "sight_word",
            "question": f'What does "{word}" mean?',
            "choices": choices,
            "answer_index": answer_index,
            "explanation": f'"{word}" means: {correct}.',
        })

    return questions

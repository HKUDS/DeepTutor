"""Age-tiered vocabulary dictionary with simple English definitions.

Used as a deterministic fallback when LLM quiz generation fails.
Questions scale with the child's age band:
  - 3-5: very basic sight words, picture-book vocabulary
  - 6-8: early reader words (Bob Books level)
  - 9-12: chapter book vocabulary, more nuanced definitions
"""

from __future__ import annotations

import random
import re
from collections import Counter

# ── Tier 1: Ages 3-5 (pre-K to kindergarten) ────────────────────────────────
# Very simple words, concrete nouns, basic action verbs.

VOCAB_3_5: dict[str, str] = {
    "big": "very large",
    "small": "not big, tiny",
    "good": "nice, not bad",
    "bad": "not good",
    "hot": "very warm",
    "cold": "not warm, chilly",
    "up": "toward the sky",
    "down": "toward the ground",
    "sun": "the bright star in the sky",
    "moon": "the bright thing in the night sky",
    "star": "a tiny light in the night sky",
    "tree": "a tall plant with branches",
    "flower": "a pretty plant that blooms",
    "rain": "water falling from clouds",
    "snow": "white cold stuff from the sky",
    "cat": "a furry pet that says meow",
    "dog": "a furry pet that says woof",
    "bird": "an animal that flies",
    "fish": "an animal that swims in water",
    "bug": "a tiny crawling insect",
    "red": "the color of an apple",
    "blue": "the color of the sky",
    "yellow": "the color of the sun",
    "green": "the color of grass",
    "hat": "something you wear on your head",
    "ball": "a round thing you play with",
    "box": "a container with four sides",
    "bed": "where you sleep",
    "food": "things you eat",
    "milk": "the white drink from a cow",
    "egg": "an oval food from a chicken",
    "run": "to move very fast",
    "jump": "to go up in the air",
    "swim": "to move through water",
    "sit": "to put your bottom on something",
    "look": "to see with your eyes",
    "play": "to have fun",
    "eat": "to put food in your mouth",
    "sleep": "to rest with your eyes closed",
    "happy": "feeling good, smiling",
    "sad": "not happy, feeling down",
    "one": "the number 1",
    "two": "the number 2",
    "three": "the number 3",
}

# ── Tier 2: Ages 6-8 (first to third grade) ─────────────────────────────────
# Early reader vocabulary (Bob Books / Magic Tree House level).
# Builds on tier 1 — includes everything above plus slightly harder words.

VOCAB_6_8_EXTRA: dict[str, str] = {
    "said": "spoke, told in words",
    "find": "to look for and discover",
    "make": "to create or build something",
    "help": "to do something for someone",
    "where": "asking about a place",
    "what": "asking about a thing",
    "who": "asking about a person",
    "how": "asking in what way",
    "when": "asking at what time",
    "why": "asking for a reason",
    "fast": "moving very quickly",
    "slow": "not fast, taking a long time",
    "hard": "not soft, firm to touch",
    "soft": "not hard, squishy",
    "old": "not new, aged",
    "new": "not old, fresh",
    "long": "not short, big from end to end",
    "short": "not long, small",
    "pretty": "nice to look at",
    "funny": "making you laugh",
    "little": "small in size",
    "away": "not here, gone",
    "here": "in this place",
    "come": "to go to someone",
    "pig": "a pink farm animal",
    "fox": "a wild animal like a small dog",
    "duck": "a bird that swims and says quack",
    "bear": "a big furry animal",
    "frog": "a small green animal that jumps",
    "rabbit": "a small furry animal with long ears",
    "plum": "a small sweet purple fruit",
    "plums": "small sweet purple fruits",
    "snack": "a little food between meals",
    "ham": "meat from a pig",
    "cake": "a sweet baked treat for parties",
    "soup": "hot food you eat with a spoon",
    "grass": "the green plant on the ground",
    "leaf": "the green part of a tree",
    "twig": "a tiny branch from a tree",
    "rock": "a hard stone on the ground",
    "sled": "something you slide on snow",
    "flag": "cloth on a pole for a country",
    "truck": "a big car that carries things",
    "vest": "a piece of clothing like a small jacket",
    "pants": "clothing you wear on your legs",
    "dress": "clothing a girl wears",
    "card": "a small piece of paper with a picture",
    "pool": "a place filled with water to swim",
    "pan": "a flat thing you cook on",
    "pot": "a deep thing you cook in",
    "bag": "something you carry things in",
    "mat": "a small rug on the floor",
    "pen": "something you write with",
    "book": "pages with words you read",
    "twin": "a brother or sister born at the same time",
    "stack": "a pile of things on top of each other",
    "dip": "a short swim or a quick go in water",
    "test": "to try something to see if it works",
    "fit": "to be the right size",
    "wear": "to put clothes on your body",
    "wash": "to clean with water",
    "leg": "a part of your body you walk with",
    "hand": "the end of your arm, with fingers",
    "lots": "many, a big amount",
    "thing": "an object, one item",
    "things": "objects, more than one item",
    "pancakes": "flat round cakes you eat for breakfast",
    "mag": "a short word for a magazine",
    "tag": "a game where you touch someone",
}

# ── Tier 3: Ages 9-12 (fourth to seventh grade) ─────────────────────────────
# Chapter book vocabulary: emotions, abstract concepts, descriptive language,
# harder verbs, and words that appear in middle-grade fiction.

VOCAB_9_12_EXTRA: dict[str, str] = {
    "adventure": "an exciting or dangerous journey",
    "ancient": "very old, from long ago",
    "appear": "to come into sight, to show up",
    "approach": "to move closer to something",
    "arrive": "to reach a place after traveling",
    "attempt": "to try to do something",
    "believe": "to think something is true",
    "brave": "showing no fear, being courageous",
    "bright": "full of light, shining, or smart",
    "calm": "peaceful, not excited or worried",
    "careful": "doing things with attention to avoid mistakes",
    "ceiling": "the top surface of a room above you",
    "certain": "sure, without doubt",
    "chance": "a possibility, an opportunity",
    "clever": "quick to learn and understand",
    "climb": "to go up something using hands and feet",
    "collect": "to gather things together",
    "comfortable": "feeling relaxed and at ease",
    "complete": "finished, whole, not missing anything",
    "confirm": "to make sure something is correct",
    "consider": "to think carefully about something",
    "continue": "to keep going, not stop",
    "curious": "wanting to know and learn",
    "dangerous": "likely to cause harm",
    "decide": "to make a choice",
    "depend": "to rely on someone or something",
    "describe": "to tell what something is like in words",
    "despair": "a feeling of having no hope",
    "difficult": "hard to do, not easy",
    "discover": "to find something for the first time",
    "dreadful": "very bad or unpleasant",
    "eager": "wanting very much to do something",
    "effort": "trying hard, using energy to do something",
    "emergency": "a sudden dangerous situation needing quick action",
    "encourage": "to give someone hope or confidence",
    "enormous": "very, very large",
    "escape": "to get away from danger",
    "examine": "to look at something very carefully",
    "excited": "feeling very happy and eager",
    "expect": "to think something will happen",
    "experience": "something that happens to you, a lived event",
    "explore": "to travel and discover new places",
    "fear": "a feeling of being scared or in danger",
    "fierce": "wild, aggressive, showing strong anger",
    "final": "last, coming at the end",
    "fortunate": "lucky, having good luck",
    "freedom": "being able to do what you want",
    "frightened": "feeling afraid, scared",
    "gather": "to bring things or people together",
    "gentle": "soft and kind, not rough",
    "glance": "to look at something quickly",
    "glorious": "wonderful, full of beauty or praise",
    "grateful": "feeling thankful",
    "horizon": "the line where the sky meets the land",
    "imagine": "to form a picture in your mind",
    "impatient": "not wanting to wait, restless",
    "important": "having great meaning or value",
    "improve": "to make something better",
    "include": "to have something as a part",
    "incredible": "amazing, hard to believe",
    "information": "facts and details about something",
    "innocent": "not guilty, doing nothing wrong",
    "instead": "in place of, rather than",
    "journey": "traveling from one place to another",
    "knowledge": "what you know, facts you have learned",
    "lonely": "feeling alone and sad",
    "marvelous": "wonderful, extremely good",
    "mention": "to say something briefly",
    "mission": "an important task or job",
    "mystery": "something hard to understand or explain",
    "narrow": "not wide, thin from side to side",
    "nervous": "feeling worried or uneasy",
    "ordinary": "not special, normal, usual",
    "patient": "able to wait without getting upset",
    "pattern": "a repeated design or order",
    "peaceful": "calm and quiet, not fighting",
    "perfect": "without any flaws, the best possible",
    "plenty": "more than enough, a lot",
    "possible": "able to happen or be done",
    "precious": "very valuable, deeply loved",
    "prefer": "to like one thing better than another",
    "pretend": "to act as if something is true when it is not",
    "proud": "feeling good about something you did",
    "realize": "to suddenly understand something",
    "recognize": "to know someone or something again",
    "rescue": "to save someone from danger",
    "resource": "something useful you can use",
    "respect": "to treat someone with care and honor",
    "responsible": "being trusted to do the right thing",
    "reveal": "to show something that was hidden",
    "ridiculous": "silly in a way that makes no sense",
    "rustle": "a soft sound like leaves moving",
    "scarce": "hard to find, not enough of something",
    "scenery": "the natural view around you",
    "search": "to look carefully for something",
    "secret": "something kept hidden from others",
    "serious": "not joking, important",
    "settle": "to come to rest, to resolve a problem",
    "shelter": "a place that protects you from weather",
    "shiver": "to shake because you are cold or scared",
    "silence": "a complete lack of sound",
    "similar": "almost the same, alike",
    "slumber": "a deep, peaceful sleep",
    "smooth": "flat and even, not rough",
    "solution": "an answer to a problem",
    "squeeze": "to press things tightly together",
    "sturdy": "strong and solid, not easily broken",
    "sudden": "happening quickly, without warning",
    "suggest": "to offer an idea for someone to consider",
    "survive": "to stay alive through something difficult",
    "suspect": "to think someone did something wrong",
    "terrible": "very bad, awful",
    "throughout": "all the way through, in every part",
    "tremble": "to shake from cold, fear, or excitement",
    "triumph": "a great victory or success",
    "unusual": "not normal, rare, strange",
    "valiant": "brave and determined, heroic",
    "venture": "a risky or daring journey",
    "village": "a small town in the countryside",
    "visible": "able to be seen",
    "wander": "to walk around without a set path",
    "whisper": "to speak very softly, using breath",
    "wicked": "evil, morally bad",
    "wisdom": "deep knowledge and good judgment",
    "witness": "someone who sees something happen",
    "wonder": "to feel amazement and curiosity",
    "wretched": "very unhappy or unfortunate",
}


def _get_dictionary(age_band: str = "6-8") -> dict[str, str]:
    """Get the age-appropriate vocabulary dictionary."""
    if age_band == "3-5":
        return VOCAB_3_5.copy()
    elif age_band == "9-12":
        combined = VOCAB_3_5.copy()
        combined.update(VOCAB_6_8_EXTRA)
        combined.update(VOCAB_9_12_EXTRA)
        return combined
    else:  # 6-8 (default)
        combined = VOCAB_3_5.copy()
        combined.update(VOCAB_6_8_EXTRA)
        return combined


def _build_lookup(age_band: str = "6-8") -> dict[str, str]:
    """Build a lookup including plural/singular variants."""
    vocab = _get_dictionary(age_band)
    lookup: dict[str, str] = {}
    for word, definition in vocab.items():
        lookup[word.lower()] = definition
        if word.endswith("s") and len(word) > 3:
            lookup.setdefault(word[:-1].lower(), definition)
        elif not word.endswith("s"):
            lookup.setdefault(word + "s", definition)
    return lookup


def extract_words(text: str, age_band: str = "6-8", min_freq: int = 1) -> list[tuple[str, int]]:
    """Find vocabulary words in text, ordered by frequency."""
    lookup = _build_lookup(age_band)
    words = re.findall(r"[A-Za-z]+", text.lower())
    freq = Counter(words)
    found: list[tuple[str, int]] = []
    seen: set[str] = set()
    for word, count in freq.most_common():
        if word in lookup and word not in seen and count >= min_freq:
            found.append((word, count))
            seen.add(word)
    return found


def generate_translation_quiz(
    text: str,
    *,
    age_band: str = "6-8",
    num_questions: int = 3,
    seed: int | None = None,
) -> list[dict]:
    """Generate word-meaning questions from the story text.

    Difficulty scales with age_band:
      3-5: basic nouns and verbs
      6-8: early reader vocabulary
      9-12: chapter book words with nuanced definitions
    """
    lookup = _build_lookup(age_band)
    definition_pool = list(set(_get_dictionary(age_band).values()))

    found = extract_words(text, age_band)
    if not found:
        return []

    rng = random.Random(seed if seed is not None else hash(text[:300]) % 100000)

    # For 9-12, prefer harder words (tier 3) when available
    if age_band == "9-12":
        tier3 = VOCAB_9_12_EXTRA
        found.sort(key=lambda x: (x[0] not in tier3, -x[1]))
    else:
        # Weight by frequency^2 so repeated words are prioritized
        weighted: list[str] = []
        for word, count in found:
            weight = count * count
            weighted.extend([word] * weight)
        rng.shuffle(weighted)
        found = [(w, 1) for w in dict.fromkeys(weighted)]

    targets: list[str] = []
    for word, _ in found:
        if word not in targets:
            targets.append(word)
        if len(targets) >= num_questions:
            break

    questions: list[dict] = []
    for i, word in enumerate(targets):
        correct = lookup.get(word, "an unknown word")

        candidates = [d for d in definition_pool if d != correct]
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

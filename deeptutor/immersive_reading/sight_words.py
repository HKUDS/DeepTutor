"""Age-tiered vocabulary dictionary with simple English definitions.

Used as a deterministic fallback when LLM quiz generation fails.
Questions scale with the child's age band:
  - 3-5: very basic sight words, picture-book vocabulary
  - 6-8: early reader words (Bob Books level)
  - 9-12: chapter book vocabulary, more nuanced definitions
"""

from __future__ import annotations

from collections import Counter
import random
import re

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
    "picture": "a drawing, a photo, or an image",
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

        questions.append(
            {
                "id": f"q{i + 1}",
                "kind": "sight_word",
                "question": f'What does "{word}" mean?',
                "choices": choices,
                "answer_index": answer_index,
                "explanation": f'"{word}" means: {correct}.',
            }
        )

    return questions


def generate_story_comprehension_quiz(
    text: str,
    *,
    age_band: str = "6-8",
    num_questions: int = 3,
    seed: int | None = None,
) -> list[dict]:
    """Generate child-friendly story comprehension questions from the story text.
    Combines story characters, settings, cause-and-effect, and key context words.
    """
    rng = random.Random(seed if seed is not None else hash(text[:300]) % 100000)
    raw_lines = [l.strip() for l in text.splitlines() if l.strip()]
    story_lines = [
        l for l in raw_lines
        if not l.startswith(('by ', 'pictures by', 'The End', 'Book ', 'Published ', 'Copyright ', 'Welcome', 'Hints', 'CONTENTS'))
        and len(l) > 3
    ]
    if story_lines and story_lines[0].lower() in {'plums', 'little bug', 'pretty', 'the sled', 'what is that?', 'come in', 'the old truck', 'play ball', 'dress up', 'before and after'}:
        title = story_lines[0]
        story_lines = story_lines[1:]
    else:
        title = ''

    full_text = ' '.join(story_lines)
    full_lower = full_text.lower()
    questions: list[dict] = []

    # 1. Extract character names
    chars: list[str] = []
    for match in re.finditer(r'\b([A-Z][a-z]+)\s+and\s+([A-Z][a-z]+)\b', full_text):
        p = f'{match.group(1)} and {match.group(2)}'
        if p not in chars:
            chars.append(p)
    for match in re.finditer(r'([A-Z][a-z]+)\s+(?:said|saw|had|ran|got|went|sat|looked|hid|will|dug|is|was|wants|fits)', full_text):
        n = match.group(1)
        if n not in {'The', 'Now', 'Are', 'She', 'He', 'They', 'We', 'What', 'Who', 'Where', 'When', 'Why', 'How', 'That', 'Yes', 'No', 'Sun', 'Rain', 'One', 'Two', 'Three', 'Before', 'After', 'Fix', 'Old', 'Bring'} and n not in chars:
            chars.append(n)

    # Q1: Characters / Main Subject
    if 'pretty' in title.lower() or ('mit' in full_lower and 'mag' in full_lower):
        ans = 'Mit and Mag'
        choices = [ans, 'A big brown bear', 'A clever fox', 'Three little ducks']
        rng.shuffle(choices)
        questions.append({
            'id': 'q1',
            'kind': 'comprehension',
            'question': 'Who is in this story?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'The story tells us about Mit the cat and Mag.'
        })
    elif 'sled' in title.lower() or ('mag' in full_lower and 'sled' in full_lower):
        ans = 'Mag'
        choices = [ans, 'A sleeping cat', 'A small mouse', 'A yellow bird']
        rng.shuffle(choices)
        questions.append({
            'id': 'q1',
            'kind': 'comprehension',
            'question': 'Who has a sled in the story?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'In the story, Mag had a sled to ride on snow!'
        })
    elif 'truck' in title.lower() or ('truck' in full_lower and 'ted' in full_lower):
        ans = 'Ted'
        choices = [ans, 'A little duck', 'A sleeping frog', 'Three ants']
        rng.shuffle(choices)
        questions.append({
            'id': 'q1',
            'kind': 'comprehension',
            'question': 'Who found and fixed the old truck?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'Ted dug up the old truck and fixed it up!'
        })
    elif 'dress up' in title.lower() or ('fox' in full_lower and 'vest' in full_lower):
        ans = 'A fox'
        choices = [ans, 'A big bear', 'A green crab', 'Two little ants']
        rng.shuffle(choices)
        questions.append({
            'id': 'q1',
            'kind': 'comprehension',
            'question': 'Who is trying on clothes in the story?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'The story is about a fox trying on vests, pants, and hats.'
        })
    elif 'before and after' in title.lower() or ('peg' in full_lower and 'pancakes' in full_lower):
        ans = 'Peg, Ted, and Bill'
        choices = [ans, 'Three little ducks', 'A big brown bear', 'A clever fox']
        rng.shuffle(choices)
        questions.append({
            'id': 'q1',
            'kind': 'comprehension',
            'question': 'Who are the characters doing activities in the story?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'The story shows Peg, Ted, and Bill doing things before and after.'
        })
    elif chars:
        ans = chars[0]
        distractors = ['A big brown bear', 'A clever fox', 'Three little ducks', 'A wild tiger']
        rng.shuffle(distractors)
        choices = [ans] + distractors[:3]
        rng.shuffle(choices)
        questions.append({
            'id': 'q1',
            'kind': 'comprehension',
            'question': 'Who is in this story?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': f'The story tells us about {ans}.'
        })
    else:
        ans = 'The characters'
        choices = [ans, 'A giant monster', 'A space alien', 'A sea turtle']
        rng.shuffle(choices)
        questions.append({
            'id': 'q1',
            'kind': 'comprehension',
            'question': 'Who is in this story?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'The story introduces the characters and their adventure.'
        })

    # Q2: Key Action / Problem / Plot Event
    if 'pretty' in title.lower() or 'wet' in full_lower:
        ans = 'She ran and got wet'
        choices = [ans, 'She flew into the clouds', 'She ate a big apple', 'She went to sleep in a box']
        rng.shuffle(choices)
        questions.append({
            'id': 'q2',
            'kind': 'comprehension',
            'question': 'What happened to Mit in the story?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'When Mit ran, she got wet and worried she was not pretty.'
        })
    elif 'sled' in title.lower() or ('sled' in full_lower and 'ruff' in full_lower):
        ans = 'Ruff the dog'
        choices = [ans, 'The hen', 'The frog', 'The pig']
        rng.shuffle(choices)
        questions.append({
            'id': 'q2',
            'kind': 'comprehension',
            'question': 'Who agreed to sled with Mag?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'The hen, frog, and pig said no, but Ruff said yes!'
        })
    elif 'what is that' in title.lower() or ('rag' in full_lower and 'flag' in full_lower):
        ans = 'A flag'
        choices = [ans, 'A sleeping cat', 'A purple plum', 'A big sled']
        rng.shuffle(choices)
        questions.append({
            'id': 'q2',
            'kind': 'comprehension',
            'question': 'What was Ted’s rag in the story?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'Ted held up his rag and said it was his flag!'
        })
    elif 'come in' in title.lower() or 'tent' in full_lower:
        ans = 'Into his tent'
        choices = [ans, 'Into a cold cave', 'Under a deep pond', 'Up a tall tree']
        rng.shuffle(choices)
        questions.append({
            'id': 'q2',
            'kind': 'comprehension',
            'question': 'Where did Mat invite his friends to come?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'Mat asked his friends to come into his tent.'
        })
    elif 'truck' in title.lower() or 'sand' in full_lower:
        ans = 'in the sand'
        choices = [ans, 'in a deep pool', 'up in a tree', 'under the bed']
        rng.shuffle(choices)
        questions.append({
            'id': 'q2',
            'kind': 'comprehension',
            'question': 'Where was the old truck at the start?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'The story begins with an old truck sitting in the sand.'
        })
    elif 'play ball' in title.lower() or 'ball' in full_lower:
        ans = 'Find the lost ball'
        choices = [ans, 'Bake a warm cake', 'Build a wooden sled', 'Wash the old truck']
        rng.shuffle(choices)
        questions.append({
            'id': 'q2',
            'kind': 'comprehension',
            'question': 'What did Mat and Sam need to do so they could play?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'They had to search and find their ball so they could play!'
        })
    elif 'sun' in full_lower and 'rain' in full_lower:
        ans = 'Sun and rain'
        choices = [ans, 'Snow and ice', 'A noisy truck', 'A cold wind']
        rng.shuffle(choices)
        questions.append({
            'id': 'q2',
            'kind': 'comprehension',
            'question': 'What helps the plums grow soft and good?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'Sun and rain help the plums grow soft and good!'
        })
    elif 'ate' in full_lower or 'snack' in full_lower:
        ans = 'He ate a little snack'
        choices = [ans, 'He flew into the sky', 'He built a big house', 'He went to sleep']
        rng.shuffle(choices)
        questions.append({
            'id': 'q2',
            'kind': 'comprehension',
            'question': 'What did the little character do in the story?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'The story tells us he ate a little snack.'
        })
    else:
        loc_match = re.search(r'(in a [a-z]+|on a [a-z]+|up a [a-z]+|in the [a-z]+|on the [a-z]+)', full_text)
        loc = loc_match.group(1) if loc_match else 'outdoors'
        choices = [loc, 'in a deep pool', 'on a fast train', 'inside a dark cave']
        rng.shuffle(choices)
        questions.append({
            'id': 'q2',
            'kind': 'comprehension',
            'question': 'Where does the story take place?',
            'choices': choices,
            'answer_index': choices.index(loc),
            'explanation': f'The story tells us it happens {loc}.'
        })

    # Q3: Dialogue / Resolution / Outcome
    if 'pretty' in title.lower() or any('help' in l.lower() for l in story_lines):
        ans = '“I can help.”'
        choices = [ans, '“Go away!”', '“I am hungry.”', '“It is dark.”']
        rng.shuffle(choices)
        questions.append({
            'id': 'q3',
            'kind': 'comprehension',
            'question': 'What did Mag say when Mit was sad and wet?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'Mag was a kind friend and said, “I can help.”'
        })
    elif 'sled' in title.lower() or 'ruff will sled' in full_lower:
        ans = '“I will not sled with you.”'
        choices = [ans, '“We love to sled!”', '“Where is the snow?”', '“Give me the sled.”']
        rng.shuffle(choices)
        questions.append({
            'id': 'q3',
            'kind': 'comprehension',
            'question': 'What did the other animals say to Mag at first?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'The hen, frog, and pig all said they would not sled with Mag.'
        })
    elif 'what is that' in title.lower() or 'twin' in full_lower:
        ans = 'Her twin brother, Finn'
        choices = [ans, 'A sleepy little dog', 'A magic flying hat', 'Ten purple plums']
        rng.shuffle(choices)
        questions.append({
            'id': 'q3',
            'kind': 'comprehension',
            'question': 'Who was inside Brin’s box at the end?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'Brin opened the box and showed her twin, Finn!'
        })
    elif 'come in' in title.lower() or ('mag and mit' in full_lower and 'tent' in full_lower):
        ans = 'Mag and Mit'
        choices = [ans, 'A big dragon', 'A wild tiger', 'Three little bears']
        rng.shuffle(choices)
        questions.append({
            'id': 'q3',
            'kind': 'comprehension',
            'question': 'Who happily went into Mat’s tent at the end?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'At the end, Mag and Mit went right into Mat’s tent!'
        })
    elif 'truck' in title.lower() or 'make it new' in full_lower:
        ans = 'Ted made the old truck new'
        choices = [ans, 'The truck rolled into the river', 'Ted left it as junk', 'The truck flew away']
        rng.shuffle(choices)
        questions.append({
            'id': 'q3',
            'kind': 'comprehension',
            'question': 'What was the happy result at the end?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'Ted painted it red and made the old truck like new!'
        })
    elif 'play ball' in title.lower() or 'find the ball' in full_lower:
        ans = 'They found the ball and played'
        choices = [ans, 'They went home crying', 'They fell asleep in the nest', 'The ball popped']
        rng.shuffle(choices)
        questions.append({
            'id': 'q3',
            'kind': 'comprehension',
            'question': 'How did the story end for Mat and Sam?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'Mat and Sam found their ball and played happily!'
        })
    elif 'dress up' in title.lower() or 'fits' in full_lower:
        ans = 'Clothes that fit just right'
        choices = [ans, 'Clothes that were too dirty', 'A pair of broken shoes', 'A winter coat for swimming']
        rng.shuffle(choices)
        questions.append({
            'id': 'q3',
            'kind': 'comprehension',
            'question': 'What did the fox finally find to wear?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'They brought lots of clothes until the fox had an outfit that fit!'
        })
    elif 'before and after' in title.lower() or 'pj' in full_lower:
        ans = 'He puts on his pajamas (pj’s)'
        choices = [ans, 'He eats a giant pancake', 'He goes swimming in the pool', 'He runs around the yard']
        rng.shuffle(choices)
        questions.append({
            'id': 'q3',
            'kind': 'comprehension',
            'question': 'What does Bill do before getting into bed?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'Before getting into bed, Bill puts on his pj’s.'
        })
    elif 'soft' in full_lower or 'good' in full_lower:
        ans = 'The plums are soft and good'
        choices = [ans, 'The plums are hard and cold', 'The plums are lost', 'The plums are bad']
        rng.shuffle(choices)
        questions.append({
            'id': 'q3',
            'kind': 'comprehension',
            'question': 'How are the plums at the end of the story?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'At the end of the story, the plums are soft and good!'
        })
    else:
        ans = 'Happy and smiling together'
        choices = [ans, 'Angry and shouting', 'Cold in the snow', 'Lost in the forest']
        rng.shuffle(choices)
        questions.append({
            'id': 'q3',
            'kind': 'comprehension',
            'question': 'How do the characters feel at the end of the story?',
            'choices': choices,
            'answer_index': choices.index(ans),
            'explanation': 'The story ends happily with friends having fun!'
        })

    return questions[:num_questions]

"""Deterministic vocabulary hints for the child reading experience."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
import sqlite3

from deeptutor.immersive_reading.sight_words import _build_lookup, _get_dictionary
from deeptutor.services.path_service import get_path_service

_WORD_RE = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)?")
_POS_PREFIX_RE = re.compile(r"^(?:[a-z]{1,5}\.|[a-z]{1,5}\s+)\s*", re.IGNORECASE)

_KIDS_CHINESE: dict[str, str] = {
    # Actions
    "said": "说，讲（say 的过去式）",
    "find": "寻找，找到",
    "make": "制作，做",
    "help": "帮助，帮忙",
    "run": "奔跑，跑",
    "jump": "跳跃，跳",
    "swim": "游泳",
    "sit": "坐下，坐",
    "look": "看，注视",
    "play": "玩耍，玩",
    "eat": "吃，吃东西",
    "sleep": "睡觉，休息",
    "wear": "穿，戴（衣服）",
    "wash": "清洗，洗",
    "test": "测试，检验",
    "dip": "浸，蘸，快速泡水",
    "fit": "合适，合身",
    "come": "来，过来",
    # Food & nature
    "plum": "李子",
    "plums": "李子（复数）",
    "snack": "点心，零食，小吃",
    "ham": "火腿",
    "cake": "蛋糕",
    "soup": "热汤，汤",
    "pancakes": "薄煎饼，松饼",
    "food": "食物",
    "milk": "牛奶",
    "egg": "鸡蛋，卵",
    "sun": "太阳，阳光",
    "moon": "月亮",
    "star": "星星",
    "tree": "树，大树",
    "flower": "花朵，鲜花",
    "rain": "雨水，下雨",
    "snow": "雪花，下雪",
    "grass": "青草，草地",
    "leaf": "树叶，叶子",
    "twig": "小树枝，细枝",
    "rock": "石头，岩石",
    # Describing words / Adjectives
    "good": "好的，优秀的",
    "bad": "坏的，不好的",
    "big": "大的，巨大的",
    "small": "小的，小巧的",
    "little": "小的，可爱的",
    "hot": "热的，烫的",
    "cold": "冷的，寒冷的",
    "fast": "快的，迅速的",
    "slow": "慢的，缓慢的",
    "hard": "硬的，坚硬的",
    "soft": "软的，柔软的",
    "old": "旧的，年老的",
    "new": "新的，崭新的",
    "long": "长的",
    "short": "短的，矮的",
    "pretty": "漂亮的，好看的",
    "funny": "好笑的，滑稽的",
    "happy": "开心的，快乐的",
    "sad": "伤心的，难过的",
    # Creatures & Objects
    "bug": "小虫，昆虫",
    "cat": "小猫",
    "dog": "小狗",
    "bird": "小鸟，鸟类",
    "fish": "鱼，鱼类",
    "pig": "小猪",
    "fox": "狐狸",
    "duck": "鸭子",
    "bear": "熊",
    "frog": "青蛙",
    "rabbit": "兔子",
    "hat": "帽子",
    "pants": "裤子",
    "vest": "背心，马甲",
    "dress": "连衣裙",
    "truck": "大卡车，货车",
    "sled": "雪橇",
    "flag": "旗帜，旗子",
    "card": "卡片",
    "pool": "水池，游泳池",
    "pot": "深锅，罐子",
    "pan": "平底锅",
    "bag": "包，袋子",
    "mat": "地垫，小垫子",
    "box": "盒子，箱子",
    "bed": "床",
    "pen": "笔，钢笔",
    "book": "书，书本",
    "hand": "手",
    "leg": "腿",
    "picture": "图画，照片，图像",
    "pictures": "图画，照片，图像",
}

_KIDS_THINKING_CLUES: dict[str, str] = {
    # Actions
    "said": "Think about using your voice to talk with someone. What did they do?",
    "find": "Look around carefully with your eyes until you discover something hidden.",
    "make": "Use your hands and creativity to put things together and build something new.",
    "help": "Lend a friendly hand to someone when they need support.",
    "run": "Move your legs as quickly as you can to dash across the yard!",
    "jump": "Bend your knees and push off the ground high into the air!",
    "swim": "Kick your legs and paddle your arms through cool water.",
    "sit": "Rest your body on a comfortable chair, the floor, or grass.",
    "look": "Open your eyes wide and direct your gaze to see clearly.",
    "play": "Have lots of fun with toys, games, or with friends outside.",
    "eat": "Take a bite of delicious food and chew it when you are hungry.",
    "sleep": "Close your eyes in a warm bed to rest peacefully all night.",
    "wear": "Put on a shirt, jacket, or shoes before going outside.",
    "wash": "Use water and soap to get clean and fresh.",
    "test": "Try something out to see how well it works.",
    "dip": "Gently put something into water for a quick moment.",
    "fit": "Check if a piece of clothing is just the right size for you.",
    "come": "Move closer toward someone when they call your name.",
    # Food & nature
    "plum": "Picture a small, juicy fruit growing on a sunny tree. What is it?",
    "plums": "Picture small, juicy fruits growing on a sunny tree. What are they?",
    "snack": "A small tasty treat you enjoy between breakfast and dinner.",
    "ham": "A savory kind of meat often sliced for sandwiches.",
    "cake": "A sweet frosted treat with candles for birthday parties.",
    "soup": "A warm, comforting meal you eat with a spoon from a bowl.",
    "pancakes": "Warm, flat breakfast treats stacked up and drizzled with syrup.",
    "food": "Tasty things you chew and swallow when your tummy rumbles.",
    "milk": "A creamy white drink that comes from cows or plants.",
    "egg": "A smooth oval food that chickens lay on the farm.",
    "sun": "Look up on a warm day at what brightens the blue sky.",
    "moon": "Look up at the glowing shape in the dark night sky.",
    "star": "A tiny twinkling point of light shining in the night sky.",
    "tree": "Look outside at a tall plant with leaves and woody branches.",
    "flower": "A colorful, sweet-smelling blossom that opens in the garden.",
    "rain": "Look at the clouds when wet droplets fall from the sky.",
    "snow": "Cold, soft white flakes falling gently in the winter.",
    "grass": "The soft green carpet of plants covering the ground outdoors.",
    "leaf": "The flat green part that flutters on a tree branch.",
    "twig": "A tiny little stick that fell from a tree branch.",
    "rock": "A solid, hard stone you might find on a garden path.",
    # Describing words / Adjectives
    "good": "Think of something pleasant that makes you smile and feel happy.",
    "bad": "Think of something unpleasant that causes trouble or sadness.",
    "big": "Think of a huge giant elephant or a tall mountain!",
    "small": "Think of a tiny little ladybug or a button.",
    "little": "Small and cute in size, not large at all.",
    "hot": "Think of warm sunshine or steam rising from hot cocoa.",
    "cold": "Think of freezing ice cubes or chilly winter wind.",
    "fast": "Think of a speedy cheetah zooming across the plains.",
    "slow": "Think of a quiet snail taking a long time to travel.",
    "hard": "Tap on a firm stone or a wooden table with your fingers.",
    "soft": "Squeeze a fluffy pillow or hug a cuddly teddy bear.",
    "old": "Something that has been around for many years, not brand new.",
    "new": "Freshly made or just opened, not used before.",
    "long": "Stretching out far from one end to the other.",
    "short": "Not very tall or long, compact in length.",
    "pretty": "Lovely, charming, and delightful to look at.",
    "funny": "Silly and playful in a way that makes you giggle and laugh.",
    "happy": "Feeling joyful with a big bright smile on your face.",
    "sad": "Feeling down, blue, or wanting a comforting hug.",
    # Creatures & Objects
    "bug": "Look closely for a tiny creeping or crawling creature.",
    "cat": "A friendly furry pet with whiskers that purrs.",
    "dog": "A playful furry pet with a wagging tail that barks.",
    "bird": "A feathered creature that flaps its wings to fly.",
    "fish": "A creature with fins that swims in ponds and oceans.",
    "pig": "A cute pink farm animal that loves rolling in mud.",
    "fox": "A clever wild animal with reddish fur and a bushy tail.",
    "duck": "A bird with webbed feet that swims in ponds.",
    "bear": "A large strong furry animal that lives in the forest.",
    "frog": "A small green animal that hops and catches flies near water.",
    "rabbit": "A fluffy animal with long ears that loves hopping.",
    "hat": "Something cool you wear on your head on sunny days.",
    "pants": "Clothing you step into to cover your legs.",
    "vest": "A sleeveless little jacket you wear over your shirt.",
    "dress": "A pretty piece of clothing with a top and skirt in one.",
    "truck": "A big, strong vehicle built to carry heavy cargo.",
    "sled": "Something you sit on to slide down a snowy hill.",
    "flag": "A piece of colorful cloth waving on a flagpole.",
    "card": "A small paper card with a picture or special note.",
    "pool": "A big basin filled with water where you can splash and swim.",
    "pot": "A deep round cooking vessel used on the stove for soup.",
    "pan": "A shallow flat cooking tool used to sizzle pancakes.",
    "bag": "Something with handles used to pack and carry your items.",
    "mat": "A small flat rug placed on the floor near the doorway.",
    "box": "A container with four sides used to hold toys or gifts.",
    "bed": "A cozy place with a mattress and blankets where you rest.",
    "pen": "A tool filled with ink that you hold to write or draw.",
    "book": "Pages bound together filled with fun stories to read.",
    "hand": "The end of your arm with five fingers you use to hold things.",
    "leg": "The part of your body you use to stand, walk, and run.",
    "picture": "Think about a drawing, a photo, or something you see on a screen. What is it?",
    "pictures": "Think about drawings, photos, or things you see on a screen. What are they?",
}


def _generate_thinking_clue(word: str, definition: str) -> str:
    if word in _KIDS_THINKING_CLUES:
        return _KIDS_THINKING_CLUES[word]
    normalized_definition = definition.lower()
    if normalized_definition.startswith(("to ", "to\t")):
        return f"Think about an action! Can you guess what someone does when they {word}?"
    if normalized_definition.startswith(("a ", "an ", "the ", "something ")):
        return f'Picture what this could be in the world! Can you guess what "{word}" is?'
    if normalized_definition.startswith(
        ("very ", "not ", "feeling ", "having ", "showing ", "full of ")
    ):
        return "Think about describing something! Can you guess what quality this word shows?"
    return f'Look closely at the story clues! Can you guess what "{word}" means here?'


@dataclass(frozen=True)
class KidsWordHint:
    word: str
    phonetic: str
    english_hint: str
    correct_choice: str
    chinese: str
    choices: tuple[str, ...]


@dataclass(frozen=True)
class _SimpleDictionaryEntry:
    word: str
    definition: str
    part_of_speech: str
    phonetic: str


def normalize_hint_word(raw_word: str) -> str:
    match = _WORD_RE.search(raw_word or "")
    return (match.group(0) if match else "").lower()


def _concise_chinese(value: str) -> str:
    if not value:
        return ""
    normalized = value.replace("\\n", "\n").replace("\r", "")
    lines = [
        line.strip()
        for line in normalized.splitlines()
        if line.strip() and not line.strip().startswith("[")
    ]
    if not lines:
        return ""
    preferred = lines[0]
    for line in lines:
        if "过去式" in line or "名词" in line or "动词" in line or "形容词" in line:
            preferred = line
            break
    cleaned = _POS_PREFIX_RE.sub("", preferred).strip()
    parts = [
        p.strip()
        for p in re.split(r"[;,，；]", cleaned)
        if p.strip() and not p.strip().startswith(("(", "（"))
    ]
    if parts:
        return "，".join(parts[:3])
    return cleaned


def _word_form_candidates(word: str) -> tuple[str, ...]:
    """Return a word followed by conservative child-reader inflections."""
    candidates = [word]
    if word.endswith("ies") and len(word) > 4:
        candidates.append(word[:-3] + "y")
    if word.endswith(("ches", "shes", "sses", "xes")) and len(word) > 4:
        candidates.append(word[:-2])
    if word.endswith("s") and len(word) > 3:
        candidates.append(word[:-1])
    if word.endswith("ing") and len(word) > 5:
        candidates.extend((word[:-3], word[:-3] + "e"))
    if word.endswith("ed") and len(word) > 4:
        candidates.extend((word[:-2], word[:-1]))
    return tuple(dict.fromkeys(candidates))


def _kids_simple_lookup(word: str) -> _SimpleDictionaryEntry | None:
    path = get_path_service().get_immersive_reading_dir() / "dictionaries" / "kids_simple.db"
    if not path.is_file():
        return None
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            for candidate in _word_form_candidates(word):
                row = connection.execute(
                    "SELECT word, definition, part_of_speech, phonetic "
                    "FROM entries WHERE word = ? LIMIT 1",
                    (candidate,),
                ).fetchone()
                if row is not None:
                    return _SimpleDictionaryEntry(
                        word=str(row["word"]),
                        definition=str(row["definition"]),
                        part_of_speech=str(row["part_of_speech"]),
                        phonetic=str(row["phonetic"] or ""),
                    )
    except sqlite3.Error:
        return None
    return None


def _ecdict_lookup(word: str) -> tuple[str, str, str] | None:
    path = get_path_service().get_immersive_reading_dir() / "dictionaries" / "ecdict.db"
    if not path.is_file():
        return None
    candidates = _word_form_candidates(word)

    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            for candidate in candidates:
                row = connection.execute(
                    "SELECT word, phonetic, definition, translation FROM entries "
                    "WHERE word = ? LIMIT 1",
                    (candidate,),
                ).fetchone()
                if row is None:
                    continue
                chinese = _concise_chinese(str(row["translation"] or ""))
                if chinese:
                    return str(row["word"]), str(row["phonetic"] or ""), chinese
    except sqlite3.Error:
        return None
    return None


def _stable_choices(word: str, correct: str, age_band: str) -> tuple[str, ...]:
    definitions = sorted(set(_get_dictionary(age_band).values()) - {correct})
    order = sorted(
        definitions,
        key=lambda value: hashlib.sha256(f"{word.lower()}:{value}".encode()).hexdigest(),
    )
    choices = [correct, order[0], order[1]]
    seed = hashlib.sha256(word.lower().encode()).digest()
    # A deterministic seed keeps the same word stable for a child without replay bias.
    for offset in range(1, len(choices)):
        index = (seed[offset % len(seed)] + offset) % len(choices)
        choices[offset], choices[index] = choices[index], choices[offset]
    return tuple(choices)


def build_kids_word_hint(raw_word: str, age_band: str = "6-8") -> KidsWordHint | None:
    word = normalize_hint_word(raw_word)
    if not word:
        return None

    simple_entry = _kids_simple_lookup(word)
    support_word = simple_entry.word if simple_entry else word
    definition = _build_lookup(age_band).get(word, "")
    if not definition and simple_entry is not None:
        definition = simple_entry.definition
    if not definition:
        return None

    # ECDICT is support data only: pronunciation and Chinese. English choices
    # must come from a child-safe English source.
    ec_entry = _ecdict_lookup(support_word)
    phonetic = simple_entry.phonetic if simple_entry else ""
    chinese = ""
    if ec_entry:
        phonetic = phonetic or ec_entry[1]
        chinese = ec_entry[2]
    chinese = _KIDS_CHINESE.get(word) or _KIDS_CHINESE.get(support_word) or chinese

    if not chinese:
        return None

    thinking_clue = _generate_thinking_clue(word, definition)
    choices = _stable_choices(word, definition, age_band)
    return KidsWordHint(
        word=word,
        phonetic=phonetic,
        english_hint=thinking_clue,
        correct_choice=definition,
        chinese=chinese,
        choices=choices,
    )

from __future__ import annotations

import re
import string
import warnings


def normalize_number_str(number_str: str) -> float:
    for char in ["$", "%", ","]:
        number_str = number_str.replace(char, "")
    try:
        return float(number_str)
    except ValueError:
        return float("inf")


def split_string(s: str, char_list: list[str] = [",", ";"]) -> list[str]:
    pattern = f"[{''.join(char_list)}]"
    return re.split(pattern, s)


def normalize_str(input_str: str, remove_punct: bool = True) -> str:
    no_spaces = re.sub(r"\s", "", input_str)
    if remove_punct:
        translator = str.maketrans("", "", string.punctuation)
        return no_spaces.lower().translate(translator)
    return no_spaces.lower()


def question_scorer(model_answer: str, ground_truth: str) -> bool:
    def _is_float(element: object) -> bool:
        try:
            float(element)
            return True
        except (ValueError, TypeError):
            return False

    if model_answer is None:
        model_answer = "None"

    if _is_float(ground_truth):
        normalized_answer = normalize_number_str(model_answer)
        return normalized_answer == float(ground_truth)

    if any(char in ground_truth for char in [",", ";"]):
        gt_elems = split_string(ground_truth)
        ma_elems = split_string(model_answer)

        if len(gt_elems) != len(ma_elems):
            warnings.warn(
                "Answer lists have different lengths, returning False.",
                UserWarning,
                stacklevel=2,
            )
            return False

        comparisons = []
        for ma_elem, gt_elem in zip(ma_elems, gt_elems):
            if _is_float(gt_elem):
                comparisons.append(normalize_number_str(ma_elem) == float(gt_elem))
            else:
                comparisons.append(
                    normalize_str(ma_elem, remove_punct=False)
                    == normalize_str(gt_elem, remove_punct=False)
                )
        return all(comparisons)

    return normalize_str(model_answer) == normalize_str(ground_truth)

from config import (
    CONTEXT_WINDOW_LIMIT,
    CHARS_PER_TOKEN,
    HEAD_RATIO,
    TAIL_RATIO,
    SNAP_TOLERANCE,
    GAP_MARKER,
)

def _snap_to_sentence(text: str, rough_point: int, direction: str) -> int:
    """
    Find nearest sentence boundary to rough_point in direction ('left' or 'right').
    Fallback to newline, then rough_point.
    """
    if direction == "left":
        idx = text.rfind('.', 0, rough_point)
        if idx == -1 or (rough_point - idx) > SNAP_TOLERANCE:
            idx = text.rfind('\n', 0, rough_point)
        if idx == -1:
            idx = rough_point
        return idx
    else:
        idx = text.find('.', rough_point)
        if idx == -1 or (idx - rough_point) > SNAP_TOLERANCE:
            idx = text.find('\n', rough_point)
        if idx == -1:
            idx = rough_point
        return idx

def truncate_for_context(
    text: str,
    estimated_tokens: int,
    context_limit: int = CONTEXT_WINDOW_LIMIT,
) -> tuple[str, bool]:
    """
    Implements Two-Tier Truncation Strategy.
    Tier 1 (Fits): returns unmodified text, False
    Tier 2 (Exceeds): returns 60/40 weighted split with gap marker, True
    """
    if estimated_tokens <= context_limit:
        return text, False

    total_char_budget = context_limit * CHARS_PER_TOKEN
    head_budget = int(total_char_budget * HEAD_RATIO)
    tail_budget = int(total_char_budget * TAIL_RATIO)

    # Cut head
    head_end_rough = head_budget
    head_end = _snap_to_sentence(text, head_end_rough, "left")
    head = text[:head_end + 1]

    # Cut tail
    tail_start_rough = max(0, len(text) - tail_budget)
    # Ensure they don't overlap if something is super weird
    if tail_start_rough <= head_end:
        tail_start_rough = head_end + 1
        
    tail_start = _snap_to_sentence(text, tail_start_rough, "right")
    tail = text[tail_start + 1:]

    combined = head + GAP_MARKER + tail
    return combined, True

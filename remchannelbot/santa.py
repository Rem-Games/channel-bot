"""Secret Santa lifecycle, selection, and best-effort exclusion matching."""

from __future__ import annotations

import random
from datetime import UTC, datetime

from .state import SANTA_CLOSED, SANTA_COMPLETED, SANTA_OPEN, SantaExclusion, SecretSantaDrawing


def timestamp() -> int:
    return int(datetime.now(UTC).timestamp())


def drawing_sort_key(drawing: SecretSantaDrawing | SantaExclusion) -> tuple[bool, int, str, str]:
    if isinstance(drawing, SecretSantaDrawing):
        stamp = {
            SANTA_OPEN: drawing.created_at,
            SANTA_CLOSED: drawing.closed_at,
            SANTA_COMPLETED: drawing.completed_at,
        }[drawing.state]
    else:
        stamp = drawing.completed_at
    return (stamp is None, -(stamp or 0), drawing.name.casefold(), drawing.drawing_id)


def complete_santa_drawing(drawing: SecretSantaDrawing) -> None:
    if drawing.state != SANTA_CLOSED:
        raise ValueError("Only Closed drawings can be marked Completed.")
    now = timestamp()
    if drawing.created_at is None:
        drawing.created_at = now
    if drawing.closed_at is None:
        drawing.closed_at = now
    drawing.completed_at = now
    drawing.state = SANTA_COMPLETED


def close_santa_drawing(drawing: SecretSantaDrawing) -> list[str]:
    if drawing.state == SANTA_COMPLETED:
        raise ValueError("Completed drawings cannot be redrawn.")
    # Matching is proven impossible before relaxing an older drawing's restrictions.
    exclusions = sorted(drawing.exclusions, key=drawing_sort_key)
    relaxed = []
    while exclusions:
        forbidden = {
            (giver, giftee)
            for exclusion in exclusions
            for giver, giftee in exclusion.assignments.items()
        }
        assignments = constrained_assignment(drawing.participant_ids, forbidden)
        if assignments is not None:
            break
        relaxed.append(exclusions.pop().name)
    else:
        assignments = assign_secret_santa(drawing.participant_ids)
    drawing.assignments = assignments
    if drawing.state == SANTA_OPEN:
        now = timestamp()
        if drawing.created_at is None:
            drawing.created_at = now
        drawing.closed_at = now
        drawing.state = SANTA_CLOSED
    return relaxed


def constrained_assignment(
    participant_ids: list[int], forbidden: set[tuple[int, int]]
) -> dict[int, int] | None:
    """Find a perfect bipartite matching using iterative augmenting paths."""
    participants = list(dict.fromkeys(participant_ids))
    if len(participants) < 2:
        raise ValueError("Secret Santa drawings need at least 2 participants.")
    candidates = {
        giver: [
            giftee
            for giftee in participants
            if giver != giftee and (giver, giftee) not in forbidden
        ]
        for giver in participants
    }
    random.shuffle(participants)
    for choices in candidates.values():
        random.shuffle(choices)
    owners = {}
    assignments = {}
    for start in participants:
        queue = [start]
        parents = {}
        seen = {start}
        free = None
        for giver in queue:
            for giftee in candidates[giver]:
                if giftee in parents:
                    continue
                parents[giftee] = giver
                if giftee not in owners:
                    free = giftee
                    break
                owner = owners[giftee]
                if owner not in seen:
                    seen.add(owner)
                    queue.append(owner)
            if free is not None:
                break
        if free is None:
            return None
        while True:
            giver = parents[free]
            previous = assignments.get(giver)
            assignments[giver] = free
            owners[free] = giver
            if previous is None:
                break
            free = previous
    return assignments


def assign_secret_santa(participant_ids: list[int]) -> dict[int, int]:
    participants = list(dict.fromkeys(participant_ids))
    if len(participants) < 2:
        raise ValueError("Secret Santa drawings need at least 2 participants.")
    for _attempt in range(100):
        giftees = participants[:]
        random.shuffle(giftees)
        if all(giver != giftee for giver, giftee in zip(participants, giftees, strict=True)):
            return dict(zip(participants, giftees, strict=True))
    random.shuffle(participants)
    return dict(zip(participants, participants[1:] + participants[:1], strict=True))

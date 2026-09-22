"""Resolve the effective episode rule for a playlist assignment.

A single resolver shared by the playlist builder and the API, so what the UI
shows is exactly what the next build will do (docs/design/assignment-rules.md).
"""

from dataclasses import dataclass
from typing import Literal, Protocol

from app.models.playlist import PickFrom

RuleSource = Literal["override", "sequential", "playlist"]


class _PlaylistDefaults(Protocol):
    default_episode_limit: int
    default_pick_from: str


class _PodcastHint(Protocol):
    is_sequential: bool


class _AssignmentOverride(Protocol):
    episode_limit: int | None
    pick_from: str | None


@dataclass(frozen=True)
class ResolvedRule:
    """The rule a build applies to one assignment, with where each part came from."""

    episode_limit: int  # 0 = all unplayed, n >= 1 = at most n
    pick_from: PickFrom
    episode_limit_source: RuleSource
    pick_from_source: RuleSource

    @property
    def unlimited(self) -> bool:
        return self.episode_limit == 0


def resolve_rule(
    playlist: _PlaylistDefaults,
    podcast: _PodcastHint,
    assignment: _AssignmentOverride | None,
) -> ResolvedRule:
    """Resolve limit and direction for one assignment.

    Order of precedence:

    - ``episode_limit``: assignment override, else the playlist default.
    - ``pick_from``: assignment override, else ``oldest`` when the podcast is
      sequential, else the playlist default.

    ``assignment`` may be ``None`` for callers that want "what would a fresh
    row get" (e.g. previewing before adding).
    """
    if assignment is not None and assignment.episode_limit is not None:
        limit, limit_source = assignment.episode_limit, "override"
    else:
        limit, limit_source = playlist.default_episode_limit, "playlist"

    if assignment is not None and assignment.pick_from is not None:
        pick, pick_source = PickFrom(assignment.pick_from), "override"
    elif podcast.is_sequential:
        pick, pick_source = PickFrom.OLDEST, "sequential"
    else:
        pick, pick_source = PickFrom(playlist.default_pick_from), "playlist"

    return ResolvedRule(
        episode_limit=limit,
        pick_from=pick,
        episode_limit_source=limit_source,
        pick_from_source=pick_source,
    )

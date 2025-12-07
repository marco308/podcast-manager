# Sequential Podcast Constraint - Critical Implementation Guide

## Overview

The `is_sequential` flag on the Podcast model is an **inviolable constraint** that must be respected in ALL playlist ordering implementations.

## The Rule

**Sequential podcasts MUST ALWAYS have their episodes sorted oldest-to-newest (chronological ascending), regardless of any playlist ordering configuration.**

This applies to:
- ✅ All ordering modes (default, podcast_order, chronological_desc, etc.)
- ✅ All playlist types (primary, news, morning, background)
- ✅ All future ordering enhancements

## Why This Matters

Sequential podcasts are **story-based content** where episodes build on each other:
- Serialized narratives (e.g., "Serial")
- Audiobook series
- Documentary series with progressive storylines
- Educational series with prerequisite concepts

Playing these out of order would:
- ❌ Spoil plot points
- ❌ Confuse the listener
- ❌ Break the narrative flow
- ❌ Make content incomprehensible

## Implementation Requirements

### Backend (playlist_builder.py)

Every ordering method MUST:

```python
def _apply_ordering(episodes, podcasts):
    # 1. Group episodes by podcast
    for podcast in podcasts:
        podcast_episodes = [e for e in episodes if e.show_id == podcast.spotify_id]

        # 2. Check is_sequential flag
        if podcast.is_sequential:
            # 3. ALWAYS sort oldest-first for sequential podcasts
            podcast_episodes.sort(key=lambda e: e.release_date)
        else:
            # Apply the ordering mode's logic for non-sequential podcasts
            pass

        # 4. Add to final list (other podcasts can be interleaved)
        result.extend(podcast_episodes)
```

### Code Review Checklist

When reviewing ANY code that touches episode ordering:

- [ ] Does it group episodes by podcast?
- [ ] Does it check the `is_sequential` flag?
- [ ] Does it force oldest-first for sequential podcasts?
- [ ] Does it work correctly when sequential and non-sequential podcasts are mixed?
- [ ] Are there tests covering sequential podcast scenarios?

## Example Scenarios

### Scenario 1: Chronological Descending with Mixed Podcasts

**Setup:**
- Playlist: `ordering_mode = 'chronological_desc'`
- Podcast A: non-sequential
- Podcast B: `is_sequential = True`

**Expected Behavior:**
```
Podcast A - Episode 3 (2024-01-03) ← newest first (non-sequential)
Podcast A - Episode 2 (2024-01-02)
Podcast A - Episode 1 (2024-01-01)
Podcast B - Episode 1 (2024-01-01) ← oldest first (SEQUENTIAL)
Podcast B - Episode 2 (2024-01-02)
Podcast B - Episode 3 (2024-01-03)
```

### Scenario 2: Custom Podcast Order

**Setup:**
- Playlist: `ordering_mode = 'podcast_order'`
- Podcast X: `playlist_order = 1`, non-sequential
- Podcast Y: `playlist_order = 2`, `is_sequential = True`
- Podcast Z: `playlist_order = 3`, non-sequential

**Expected Behavior:**
```
Podcast X episodes (newest first, position 1)
Podcast Y episodes (OLDEST first, position 2) ← respects sequential
Podcast Z episodes (newest first, position 3)
```

## Testing Requirements

Every ordering mode MUST have tests for:

1. **Pure sequential playlist**: All podcasts are sequential
2. **Pure non-sequential playlist**: No sequential podcasts
3. **Mixed playlist**: Some sequential, some non-sequential
4. **Sequential at different positions**: Sequential at start, middle, end
5. **Multiple sequential podcasts**: Ensure all are ordered correctly

### Example Test

```python
def test_chronological_desc_respects_sequential():
    """Verify chronological_desc doesn't reverse sequential podcast episodes."""

    # Setup
    podcast_a = Podcast(id="A", is_sequential=False)
    podcast_b = Podcast(id="B", is_sequential=True)

    episodes = [
        Episode(show_id="A", release_date="2024-01-01"),
        Episode(show_id="A", release_date="2024-01-02"),
        Episode(show_id="B", release_date="2024-01-01"),
        Episode(show_id="B", release_date="2024-01-02"),
    ]

    # Execute
    result = apply_ordering(episodes, 'chronological_desc', [podcast_a, podcast_b])

    # Assert: Podcast A reversed, Podcast B NOT reversed
    podcast_b_episodes = [e for e in result if e.show_id == "B"]
    assert podcast_b_episodes[0].release_date < podcast_b_episodes[1].release_date, \
        "Sequential podcast must be oldest-first even in chronological_desc mode"
```

## Common Mistakes to Avoid

### ❌ WRONG: Global Sort Only

```python
# This violates the constraint!
def build_playlist(episodes, ordering_mode):
    if ordering_mode == 'chronological_desc':
        return sorted(episodes, key=lambda e: e.release_date, reverse=True)
    # This reverses EVERYTHING, including sequential podcasts
```

### ✅ CORRECT: Group First, Then Sort

```python
def build_playlist(episodes, ordering_mode, podcasts):
    result = []

    for podcast in podcasts:
        podcast_episodes = [e for e in episodes if e.show_id == podcast.spotify_id]

        if podcast.is_sequential:
            # ALWAYS oldest first
            podcast_episodes.sort(key=lambda e: e.release_date)
        elif ordering_mode == 'chronological_desc':
            # Only apply desc for non-sequential
            podcast_episodes.sort(key=lambda e: e.release_date, reverse=True)

        result.extend(podcast_episodes)

    return result
```

## Frontend Considerations

### UI Indicators

When showing podcasts in ordering UI, indicate sequential podcasts:

```tsx
{podcast.is_sequential && (
  <Tag color="blue">SEQUENTIAL</Tag>
  <Tooltip title="Episodes always play oldest-first for story continuity" />
)}
```

### User Education

Include explanatory text in ordering mode descriptions:

```tsx
{
  value: 'chronological_desc',
  label: 'Newest first',
  description: 'Newest episodes first (except sequential podcasts which always play oldest-first)'
}
```

## Related Files

- Implementation: [backend/app/services/playlist_builder.py](../backend/app/services/playlist_builder.py)
- Model: [backend/app/models/podcast.py](../backend/app/models/podcast.py)
- Feature Plan: [feature_flexible_playlist_ordering.md](./feature_flexible_playlist_ordering.md)

## Questions?

If you're unsure whether your code respects the sequential constraint, ask yourself:

1. **"Could this code accidentally reverse episodes from a story-based podcast?"**
   - If yes, you have a bug

2. **"Does this code ever sort ALL episodes globally without checking is_sequential?"**
   - If yes, you need to refactor

3. **"What happens if someone adds a new ordering mode in the future?"**
   - Will it automatically respect sequential podcasts, or will they need to remember this constraint?

**When in doubt, preserve chronological order for sequential podcasts.**

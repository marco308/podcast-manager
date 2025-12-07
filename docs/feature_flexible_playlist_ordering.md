# Flexible Playlist Ordering Feature

This document outlines the implementation plan for extending custom ordering to **all** playlists, not just the morning playlist. This allows users to define ordering preferences for any playlist based on their needs.

## Feature Overview

Currently, only the morning playlist supports custom ordering via the `morning_order` field on podcasts. This feature will generalize ordering to work with any playlist by:

1. Adding an `order_field` to the Playlist model to specify which ordering method to use
2. Supporting multiple ordering strategies (by category, by podcast, chronological, etc.)
3. Creating a flexible UI that adapts based on the playlist's ordering configuration

---

## Current State Analysis

### Existing Implementation
- **Morning Playlist**: Uses `podcasts.morning_order` field with drag-and-drop UI
- **Other Playlists**: Use hardcoded sorting logic in `playlist_builder.py`:
  - Primary: oldest first
  - News: newest first (latest episode only)
  - Background: oldest first
- **Limitation**: Ordering is tied to podcast category, not playlist configuration

### Problems with Current Approach
1. **Inflexible**: Can't customize order for individual playlists
2. **Scalability**: Adding new ordering types requires DB schema changes
3. **User Experience**: No way to control episode order in primary/background playlists

---

## Design Goals

1. **Backward Compatible**: Existing playlists continue to work without changes
2. **Flexible**: Support multiple ordering strategies per playlist
3. **User-Friendly**: Intuitive UI that adapts to playlist type
4. **Future-Proof**: Easy to add new ordering strategies
5. **Respect Sequential Constraint**: Always honor `podcast.is_sequential` flag

---

## Critical Constraint: Sequential Podcasts

**The `is_sequential` flag is an inviolable constraint that MUST be respected in all ordering modes.**

> 📘 **Important:** See [sequential_podcast_constraint.md](./sequential_podcast_constraint.md) for detailed implementation guide, test requirements, and common mistakes to avoid.

### Sequential Podcast Behavior

- **Story-based podcasts** (e.g., Serial, audiobooks) have `is_sequential = True`
- Episodes from sequential podcasts **MUST ALWAYS** appear oldest-to-newest
- This applies regardless of playlist ordering mode
- Other podcasts can be interleaved between sequential podcast episodes

### Example Scenario

Playlist with custom podcast order:
1. Podcast A (non-sequential, `playlist_order = 1`)
2. Podcast B (sequential, `playlist_order = 2`)
3. Podcast C (non-sequential, `playlist_order = 3`)

**Correct episode order in playlist:**
```
1. Podcast A - Episode 5 (newest)
2. Podcast A - Episode 4
3. Podcast A - Episode 3
4. Podcast B - Episode 1 (oldest first - SEQUENTIAL)
5. Podcast B - Episode 2
6. Podcast B - Episode 3
7. Podcast C - Episode 10 (newest)
8. Podcast C - Episode 9
```

**Incorrect** (violates sequential constraint):
```
1. Podcast A - Episode 5 (newest)
2. Podcast B - Episode 3 (newest) ❌ WRONG - breaks story continuity
3. Podcast B - Episode 2
4. Podcast B - Episode 1
5. Podcast C - Episode 10 (newest)
```

### Implementation Notes

All ordering methods must:
1. Group episodes by podcast
2. Check `podcast.is_sequential` for each group
3. If `is_sequential = True`: sort group oldest-to-newest
4. If `is_sequential = False`: apply the ordering mode's logic
5. Interleave groups according to playlist ordering

---

## Implementation Plan

### 1. Database Schema Changes

#### 1.1 Add `ordering_mode` to Playlist Model

**File**: `backend/app/models/playlist.py`

Add new enum and field:

```python
class PlaylistOrderingMode(str, PyEnum):
    """Playlist ordering modes."""

    DEFAULT = "default"           # Use rule_type default logic (backward compatible)
    PODCAST_ORDER = "podcast_order"  # Order by podcast.playlist_order field
    CHRONOLOGICAL_ASC = "chronological_asc"   # Oldest episodes first
    CHRONOLOGICAL_DESC = "chronological_desc"  # Newest episodes first
    CUSTOM = "custom"             # Custom ordering via playlist_episode_order table
```

Add to Playlist model:
```python
ordering_mode: Mapped[PlaylistOrderingMode] = mapped_column(
    Enum(PlaylistOrderingMode),
    default=PlaylistOrderingMode.DEFAULT,
    nullable=False
)
```

**Migration**: Create Alembic migration to add `ordering_mode` column with default `DEFAULT`.

#### 1.2 Add Generic `playlist_order` Field to Podcast Model

**File**: `backend/app/models/podcast.py`

Rename `morning_order` to support all playlists:

```python
# DEPRECATED: morning_order - kept for backward compatibility during migration
morning_order: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

# NEW: Generic ordering field for any playlist using PODCAST_ORDER mode
playlist_order: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
```

**Migration Strategy**:
1. Add `playlist_order` column
2. Copy `morning_order` values to `playlist_order` for NEWS podcasts
3. Keep `morning_order` for backward compatibility (can be removed in future version)

#### 1.3 Create Association Table for Playlist-Specific Ordering (Future Enhancement)

**File**: `backend/app/models/playlist_podcast_order.py` (NEW)

For advanced use case where users want different ordering per playlist:

```python
class PlaylistPodcastOrder(Base):
    """Stores custom ordering of podcasts within specific playlists."""

    __tablename__ = "playlist_podcast_order"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    playlist_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False
    )
    podcast_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("podcasts.id", ondelete="CASCADE"), nullable=False
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint('playlist_id', 'podcast_id'),
        Index('idx_playlist_order', 'playlist_id', 'order'),
    )
```

**Note**: This is **optional** and can be implemented in Phase 2. Start with simpler `playlist_order` approach.

---

### 2. Backend Changes

#### 2.1 Update Schemas

**File**: `backend/app/schemas/playlist.py`

```python
class PlaylistOrderingMode(str, Enum):
    """Playlist ordering modes."""
    DEFAULT = "default"
    PODCAST_ORDER = "podcast_order"
    CHRONOLOGICAL_ASC = "chronological_asc"
    CHRONOLOGICAL_DESC = "chronological_desc"
    CUSTOM = "custom"

class PlaylistCreate(PlaylistBase):
    """Schema for creating a playlist."""
    spotify_playlist_id: str | None = None
    ordering_mode: PlaylistOrderingMode = PlaylistOrderingMode.DEFAULT

class PlaylistResponse(PlaylistBase):
    """Schema for playlist API response."""
    # ... existing fields ...
    ordering_mode: PlaylistOrderingMode

class PlaylistUpdate(BaseModel):
    """Schema for updating playlist configuration."""
    # ... existing fields ...
    ordering_mode: PlaylistOrderingMode | None = None
```

**File**: `backend/app/schemas/podcast.py`

```python
class PodcastResponse(PodcastBase):
    # ... existing fields ...
    morning_order: int | None = None  # DEPRECATED but kept for compatibility
    playlist_order: int | None = None  # NEW

class PodcastUpdate(BaseModel):
    # ... existing fields ...
    morning_order: int | None = None  # DEPRECATED but kept for compatibility
    playlist_order: int | None = None  # NEW
```

#### 2.2 Update Playlist Builder Service

**File**: `backend/app/services/playlist_builder.py`

Refactor to use `ordering_mode`:

```python
def _apply_ordering(
    self,
    episodes: list[Episode],
    ordering_mode: PlaylistOrderingMode,
    podcasts: list[Podcast] | None = None
) -> list[Episode]:
    """Apply ordering based on playlist configuration.

    IMPORTANT: This method respects the podcast.is_sequential flag.
    Sequential podcasts ALWAYS have their episodes sorted oldest-to-newest,
    regardless of the ordering_mode. Other podcasts can be interleaved between
    sequential podcast episodes.

    Args:
        episodes: Episodes to order
        ordering_mode: Ordering strategy to use
        podcasts: Optional podcast list for PODCAST_ORDER mode

    Returns:
        Ordered list of episodes
    """
    if ordering_mode == PlaylistOrderingMode.CHRONOLOGICAL_ASC:
        # Group by podcast to respect is_sequential
        from itertools import groupby
        result = []

        # Sort by release date, then group by podcast
        sorted_eps = sorted(episodes, key=lambda e: (e.release_date, e.show_id))
        for show_id, group in groupby(sorted_eps, key=lambda e: e.show_id):
            podcast = next((p for p in (podcasts or []) if p.spotify_id == show_id), None)
            group_list = list(group)

            # Sequential podcasts: oldest first (already sorted correctly)
            # Non-sequential podcasts: oldest first (already sorted correctly)
            result.extend(group_list)

        return result

    elif ordering_mode == PlaylistOrderingMode.CHRONOLOGICAL_DESC:
        # Group by podcast to respect is_sequential
        from itertools import groupby
        result = []

        # Sort by release date descending, then group by podcast
        sorted_eps = sorted(episodes, key=lambda e: (e.release_date, e.show_id), reverse=True)
        for show_id, group in groupby(sorted_eps, key=lambda e: e.show_id):
            podcast = next((p for p in (podcasts or []) if p.spotify_id == show_id), None)
            group_list = list(group)

            if podcast and podcast.is_sequential:
                # Sequential podcasts: MUST be oldest first
                group_list.sort(key=lambda e: e.release_date)
            # else: non-sequential stays newest first

            result.extend(group_list)

        return result

    elif ordering_mode == PlaylistOrderingMode.PODCAST_ORDER and podcasts:
        # Create podcast_id -> (order, is_sequential) mapping
        podcast_order_map = {
            p.spotify_id: (p.playlist_order or float('inf'), p.is_sequential)
            for p in podcasts
        }

        # Group episodes by podcast
        from itertools import groupby
        episodes_by_order: list[Episode] = []

        # Sort episodes by podcast order first, then by show_id
        sorted_eps = sorted(
            episodes,
            key=lambda e: (
                podcast_order_map.get(e.show_id, (float('inf'), False))[0],  # playlist_order
                e.show_id  # group by podcast
            )
        )

        # Within each podcast group, respect is_sequential
        for show_id, group in groupby(sorted_eps, key=lambda e: e.show_id):
            group_list = list(group)
            podcast_info = podcast_order_map.get(show_id, (float('inf'), False))
            is_sequential = podcast_info[1]

            if is_sequential:
                # Sequential podcasts: MUST be oldest first
                group_list.sort(key=lambda e: e.release_date)
            else:
                # Non-sequential podcasts: newest first (default for most playlists)
                group_list.sort(key=lambda e: e.release_date, reverse=True)

            episodes_by_order.extend(group_list)

        return episodes_by_order

    else:
        # DEFAULT mode - use existing rule_type logic
        return episodes

async def build_primary_playlist(self, playlist: Playlist) -> list[str]:
    """Build primary playlist with configurable ordering."""
    podcasts = await self._get_podcasts_by_category(PodcastCategory.PRIMARY)
    is_weekend = is_weekend_or_holiday()

    all_episodes: list[Episode] = []

    for podcast in podcasts:
        if podcast.is_weekend_only and not is_weekend:
            continue

        episodes = await self._get_unplayed_episodes(podcast)
        sorted_episodes = self._sort_episodes(episodes, podcast.is_sequential)
        all_episodes.extend(sorted_episodes)

    # Apply playlist ordering
    if playlist.ordering_mode == PlaylistOrderingMode.DEFAULT:
        all_episodes.sort(key=lambda e: e.release_date)  # Oldest first (default)
    else:
        all_episodes = self._apply_ordering(all_episodes, playlist.ordering_mode, podcasts)

    return [ep.uri for ep in all_episodes]

async def build_morning_playlist(self, playlist: Playlist) -> list[str]:
    """Build morning playlist with configurable ordering."""
    podcasts = await self._get_podcasts_by_category(PodcastCategory.NEWS)
    is_weekend = is_weekend_or_holiday()

    latest_episodes: list[Episode] = []

    for podcast in podcasts:
        if podcast.is_weekend_only and not is_weekend:
            continue

        episodes = await self._get_unplayed_episodes(podcast, max_episodes=10)
        if episodes:
            sorted_eps = self._sort_episodes(episodes, sequential=False)
            latest_episodes.append(sorted_eps[0])

    # Apply playlist ordering
    if playlist.ordering_mode == PlaylistOrderingMode.DEFAULT:
        # Backward compatible: use podcast.playlist_order (migrated from morning_order)
        latest_episodes = self._apply_ordering(
            latest_episodes,
            PlaylistOrderingMode.PODCAST_ORDER,
            podcasts
        )
    else:
        latest_episodes = self._apply_ordering(latest_episodes, playlist.ordering_mode, podcasts)

    return [ep.uri for ep in latest_episodes]

# Update update_playlist to pass playlist object to build methods
async def update_playlist(self, playlist: Playlist) -> PlaylistUpdateResult:
    """Update a single playlist based on its rule type and ordering mode."""
    try:
        spotify_playlist_id = await self._ensure_spotify_playlist(playlist)

        # Build episode list based on rule type
        if playlist.rule_type == PlaylistRuleType.PRIMARY:
            episode_uris = await self.build_primary_playlist(playlist)
        elif playlist.rule_type == PlaylistRuleType.NEWS:
            episode_uris = await self.build_news_playlist(playlist)
        elif playlist.rule_type == PlaylistRuleType.MORNING:
            episode_uris = await self.build_morning_playlist(playlist)
        elif playlist.rule_type == PlaylistRuleType.BACKGROUND:
            episode_uris = await self.build_background_playlist(playlist)
        else:
            return PlaylistUpdateResult(...)

        # ... rest of implementation
```

---

### 3. Frontend Changes

#### 3.1 Update Types

**File**: `frontend/src/types/index.ts`

```typescript
export type PlaylistOrderingMode =
  | 'default'
  | 'podcast_order'
  | 'chronological_asc'
  | 'chronological_desc'
  | 'custom';

export interface Playlist {
  // ... existing fields ...
  ordering_mode: PlaylistOrderingMode;
}

export interface Podcast {
  // ... existing fields ...
  morning_order: number | null;  // DEPRECATED
  playlist_order: number | null; // NEW
}
```

#### 3.2 Refactor Playlists Page

**File**: `frontend/src/pages/Playlists.tsx`

Major changes:

1. **Add ordering mode selector to playlist form**
2. **Generalize MorningOrderSection to PlaylistOrderingSection**
3. **Show ordering UI based on selected playlist's ordering_mode**

```typescript
// New component for managing podcast order for any playlist
interface PlaylistOrderingSectionProps {
  playlist: Playlist;
}

function PlaylistOrderingSection({ playlist }: PlaylistOrderingSectionProps) {
  // Determine which podcasts to show based on rule_type
  const category = ruleTypeToCategoryMap[playlist.rule_type];
  const { data: podcasts, isLoading } = usePodcasts(category);
  const updatePodcast = useUpdatePodcast();
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [localPodcasts, setLocalPodcasts] = useState<Podcast[]>([]);

  // Only show if ordering_mode is PODCAST_ORDER
  if (playlist.ordering_mode !== 'podcast_order') {
    return null;
  }

  const hasSequentialPodcasts = podcasts?.some(p => p.is_sequential);

  // Rest of implementation similar to MorningOrderSection but using playlist_order
  // IMPORTANT: Show indicator for sequential podcasts

  return (
    <Card title={`Order: ${playlist.name}`} style={{ marginTop: 24 }}>
      {hasSequentialPodcasts && (
        <Alert
          type="info"
          message="Sequential podcasts detected"
          description="Podcasts marked as sequential (story-based) will always play oldest-to-newest regardless of ordering."
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}
      {/* ... rest of component */}
    </Card>
  );
}

  const renderPodcastItem = (podcast: Podcast) => (
    <List.Item>
      <List.Item.Meta
        title={
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Text ellipsis>{podcast.name}</Text>
            {podcast.is_sequential && (
              <Tooltip title="Sequential podcast - episodes always play oldest-first">
                <Tag color="blue" style={{ fontSize: 10 }}>SEQUENTIAL</Tag>
              </Tooltip>
            )}
          </div>
        }
        description={<Text type="secondary">{podcast.publisher}</Text>}
      />
      <InputNumber
        min={1}
        max={999}
        value={podcast.playlist_order}
        onChange={(value) => handleOrderChange(podcast.spotify_id, value)}
        disabled={updatingId === podcast.spotify_id}
      />
    </List.Item>
  );

  // ... rest of component
}

// Add ordering mode options to playlist form
const orderingModeOptions = [
  {
    value: 'default',
    label: 'Default (by category)',
    description: 'Use standard sorting for this category'
  },
  {
    value: 'podcast_order',
    label: 'Custom podcast order',
    description: 'Manually order podcasts (sequential podcasts always oldest-first)'
  },
  {
    value: 'chronological_asc',
    label: 'Oldest first',
    description: 'Sort episodes by release date (oldest first)'
  },
  {
    value: 'chronological_desc',
    label: 'Newest first',
    description: 'Sort episodes by release date (newest first for non-sequential podcasts)'
  },
];

// In playlist form modal
<Form.Item
  name="ordering_mode"
  label="Ordering Mode"
  extra="How should episodes be ordered in this playlist?"
>
  <Select
    placeholder="Select ordering mode"
    options={orderingModeOptions.map((opt) => ({
      value: opt.value,
      label: (
        <div>
          <div>{opt.label}</div>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {opt.description}
          </Text>
        </div>
      ),
    }))}
  />
</Form.Item>

// Main Playlists component - show ordering section for selected playlist
export function Playlists() {
  const [selectedPlaylist, setSelectedPlaylist] = useState<Playlist | null>(null);

  return (
    <div>
      {/* Playlist table with click to select */}
      <Table
        dataSource={playlists}
        columns={columns}
        rowKey="id"
        onRow={(record) => ({
          onClick: () => setSelectedPlaylist(record),
          style: { cursor: 'pointer' },
        })}
        rowClassName={(record) =>
          record.id === selectedPlaylist?.id ? 'selected-row' : ''
        }
      />

      {/* Show ordering UI for selected playlist */}
      {selectedPlaylist && (
        <PlaylistOrderingSection playlist={selectedPlaylist} />
      )}

      {/* Existing modal */}
    </div>
  );
}
```

#### 3.3 Alternative: Dedicated Ordering Page

For better UX, consider a dedicated ordering page at `/playlists/:id/order`:

**File**: `frontend/src/pages/PlaylistOrder.tsx` (NEW)

```typescript
import { useParams } from 'react-router-dom';
import { usePlaylist, usePodcasts, useUpdatePodcast } from '../hooks';

export function PlaylistOrder() {
  const { id } = useParams<{ id: string }>();
  const { data: playlist } = usePlaylist(Number(id));

  // Show appropriate ordering UI based on playlist.ordering_mode
  // Full-page drag-and-drop interface
  // ...
}
```

---

### 4. Migration Path

#### Phase 1: Backend Foundation
1. Add `ordering_mode` column to playlists table (default: `DEFAULT`)
2. Add `playlist_order` column to podcasts table
3. Data migration: Copy `morning_order` → `playlist_order` for NEWS podcasts
4. Update Playlist/Podcast models and schemas
5. Set existing morning playlists to `ordering_mode = 'podcast_order'`

#### Phase 2: Backend Logic
1. Refactor `PlaylistBuilder` to support all ordering modes
2. Update `build_*_playlist()` methods to accept Playlist parameter
3. Add tests for new ordering logic

#### Phase 3: Frontend Basic
1. Update TypeScript types
2. Add `ordering_mode` selector to playlist form
3. Update API calls to handle new fields

#### Phase 4: Frontend Advanced
1. Generalize ordering UI component
2. Add playlist selection to show ordering section
3. Update drag-and-drop to use `playlist_order` instead of `morning_order`

#### Phase 5: Cleanup (Future)
1. Deprecate `morning_order` field (add deprecation notice)
2. Remove hardcoded ordering logic from old implementations
3. Consider adding playlist-specific ordering table for multi-playlist scenarios

---

### 5. Testing Plan

#### Backend Tests

**Ordering Mode Tests:**
1. Test each `ordering_mode` produces correct episode order
2. Test backward compatibility (DEFAULT mode works like old behavior)
3. Test `playlist_order` sorting (nulls last, ties by release date)
4. Test migration script (morning_order → playlist_order)

**Sequential Podcast Tests (CRITICAL):**
1. **Test: Sequential podcast in CHRONOLOGICAL_DESC mode**
   - Setup: Playlist with `ordering_mode = 'chronological_desc'`
   - Podcasts: 1 sequential, 1 non-sequential
   - Expected: Sequential podcast episodes sorted oldest-first, non-sequential newest-first

2. **Test: Sequential podcast in PODCAST_ORDER mode**
   - Setup: Playlist with custom podcast order
   - Podcasts: Sequential at position 2, non-sequential at positions 1 and 3
   - Expected: Sequential podcast's episodes appear oldest-first between the other podcasts

3. **Test: Multiple sequential podcasts**
   - Setup: Playlist with 2 sequential podcasts with different `playlist_order`
   - Expected: Both sequential podcasts have episodes oldest-first, interleaved correctly

4. **Test: Sequential podcast with no unplayed episodes**
   - Expected: Gracefully handle empty episode list

5. **Test: Mixed playlist (primary + sequential)**
   - Setup: Primary playlist with both sequential and non-sequential podcasts
   - Expected: Sequential episodes always oldest-first, regardless of global ordering

**Example Test Case:**
```python
async def test_sequential_podcast_ordering_with_custom_order():
    """Test that sequential podcasts always appear oldest-first."""
    # Setup
    podcast_a = create_podcast(spotify_id="A", is_sequential=False, playlist_order=1)
    podcast_b = create_podcast(spotify_id="B", is_sequential=True, playlist_order=2)
    podcast_c = create_podcast(spotify_id="C", is_sequential=False, playlist_order=3)

    episodes_a = [
        create_episode(show_id="A", release_date="2024-01-03", name="A-E3"),
        create_episode(show_id="A", release_date="2024-01-02", name="A-E2"),
        create_episode(show_id="A", release_date="2024-01-01", name="A-E1"),
    ]

    episodes_b = [
        create_episode(show_id="B", release_date="2024-01-03", name="B-E3"),
        create_episode(show_id="B", release_date="2024-01-02", name="B-E2"),
        create_episode(show_id="B", release_date="2024-01-01", name="B-E1"),
    ]

    episodes_c = [
        create_episode(show_id="C", release_date="2024-01-03", name="C-E3"),
        create_episode(show_id="C", release_date="2024-01-02", name="C-E2"),
    ]

    all_episodes = episodes_a + episodes_b + episodes_c
    playlist = create_playlist(ordering_mode=PlaylistOrderingMode.PODCAST_ORDER)

    # Execute
    builder = PlaylistBuilder(db, user)
    result = builder._apply_ordering(
        all_episodes,
        playlist.ordering_mode,
        podcasts=[podcast_a, podcast_b, podcast_c]
    )

    # Assert
    expected_names = [
        "A-E3", "A-E2", "A-E1",  # Podcast A: newest first (non-sequential)
        "B-E1", "B-E2", "B-E3",  # Podcast B: oldest first (SEQUENTIAL)
        "C-E3", "C-E2",          # Podcast C: newest first (non-sequential)
    ]

    actual_names = [ep.name for ep in result]
    assert actual_names == expected_names, (
        f"Sequential podcast B must be oldest-first. "
        f"Expected: {expected_names}, Got: {actual_names}"
    )
```

#### Frontend Tests
1. Test ordering UI only shows when `ordering_mode = 'podcast_order'`
2. Test drag-and-drop updates `playlist_order` via API
3. Test playlist form saves `ordering_mode` correctly
4. **Test: Sequential podcast indicator in UI** (optional enhancement)
   - Show badge or icon for sequential podcasts in ordering UI
   - Tooltip explaining they will always play oldest-first

#### Integration Tests
1. Create playlist with `podcast_order` mode
2. Set podcast ordering via UI (including sequential podcasts)
3. Trigger playlist rebuild
4. Verify Spotify playlist matches expected order
5. **Test: Sequential podcast in Spotify playlist**
   - Verify sequential podcast episodes appear oldest-first in actual Spotify playlist
   - Verify non-sequential podcasts interleaved correctly

---

## User Stories

### Story 1: Custom Order for Primary Playlist
**As a user**, I want to listen to my primary podcasts in a specific order, so that I hear my favorite shows first.

**Acceptance Criteria**:
- Can set `ordering_mode = 'podcast_order'` for primary playlist
- Can drag-and-drop podcasts to reorder them
- Playlist updates reflect the custom order

### Story 2: Newest First for Background
**As a user**, I want my background playlist sorted newest-first instead of oldest-first, so I hear more recent content while working.

**Acceptance Criteria**:
- Can set `ordering_mode = 'chronological_desc'` for background playlist
- Episodes appear in reverse chronological order

### Story 3: Backward Compatibility
**As an existing user**, I expect my morning playlist to continue working with my custom order after the update.

**Acceptance Criteria**:
- Existing morning playlists automatically migrated to `podcast_order` mode
- `morning_order` values copied to `playlist_order`
- No user action required

### Story 4: Sequential Podcast Ordering
**As a user listening to a story-based podcast**, I want episodes to always play in chronological order (oldest-first) regardless of how I configure my playlist, so I don't accidentally skip ahead in the story.

**Acceptance Criteria**:
- Sequential podcasts (marked with `is_sequential = True`) always have episodes ordered oldest-to-newest
- This applies to ALL ordering modes (chronological_desc, podcast_order, etc.)
- Other podcasts can be interleaved between sequential podcast episodes
- UI indicates which podcasts are sequential (optional enhancement)

**Example**: I have a playlist with:
- "The Daily" (news, non-sequential) at position 1
- "Serial" (story, sequential) at position 2
- "Planet Money" (non-sequential) at position 3

Even if I set `ordering_mode = 'chronological_desc'`, "Serial" episodes must still play oldest-first to maintain story continuity.

---

## Future Enhancements

### 1. Playlist-Specific Ordering
Support different ordering for the same podcast across multiple playlists using `playlist_podcast_order` table.

**Example**:
- Morning playlist: "The Daily" at position 1
- Evening playlist: "The Daily" at position 5

### 2. Episode-Level Ordering
Allow users to manually reorder individual episodes within a playlist (not just podcasts).

### 3. Smart Ordering
AI-driven ordering based on:
- Listening history
- Episode duration
- Time of day
- Topic clustering

### 4. Ordering Presets
Save and load ordering configurations:
- "Commute" preset (short episodes first)
- "Weekend" preset (long-form content)
- "News First" preset (news shows before entertainment)

---

## Files to Modify

### Backend
- `backend/alembic/versions/XXX_add_playlist_ordering.py` (new migration)
- `backend/app/models/playlist.py` (add `ordering_mode`)
- `backend/app/models/podcast.py` (add `playlist_order`)
- `backend/app/schemas/playlist.py` (add `ordering_mode` to schemas)
- `backend/app/schemas/podcast.py` (add `playlist_order` to schemas)
- `backend/app/services/playlist_builder.py` (refactor ordering logic)

### Frontend
- `frontend/src/types/index.ts` (add `ordering_mode`, `playlist_order`)
- `frontend/src/pages/Playlists.tsx` (generalize ordering UI)
- `frontend/src/api/playlists.ts` (handle new fields)

### Documentation
- `docs/feature_morning_order.md` (mark as superseded)
- `docs/feature_flexible_playlist_ordering.md` (this document)
- `docs/sequential_podcast_constraint.md` (critical constraint reference)

---

## Acceptance Criteria

### Database & Backend
- [ ] `ordering_mode` field added to Playlist model with migration
- [ ] `playlist_order` field added to Podcast model with migration
- [ ] Data migration copies `morning_order` → `playlist_order` for NEWS podcasts
- [ ] Existing morning playlists set to `ordering_mode = 'podcast_order'`
- [ ] All ordering modes (default, podcast_order, chronological_asc/desc) work correctly

### Sequential Podcast Constraint (CRITICAL)
- [ ] Sequential podcasts (`is_sequential = True`) always ordered oldest-to-newest
- [ ] Constraint respected in ALL ordering modes
- [ ] Test coverage for sequential podcast ordering in each mode
- [ ] Non-sequential podcasts can be interleaved with sequential ones
- [ ] Mixed playlists (sequential + non-sequential) work correctly

### Frontend
- [ ] Playlist form allows selecting ordering mode with descriptions
- [ ] Ordering UI shows for playlists with `ordering_mode = 'podcast_order'`
- [ ] Drag-and-drop updates `playlist_order` field
- [ ] (Optional) Sequential podcasts shown with indicator/badge in ordering UI

### Quality & Compatibility
- [ ] Backward compatibility maintained (existing playlists work without changes)
- [ ] Tests pass for all ordering modes
- [ ] Integration tests verify Spotify playlist reflects correct order
- [ ] Documentation updated

---

## Risks & Mitigations

### Risk 1: Breaking Changes
**Mitigation**: Default all existing playlists to `ordering_mode = 'default'` to preserve current behavior. Only morning playlists migrate to `podcast_order`.

### Risk 2: Performance
**Mitigation**: Add database indexes on `playlist_order` and `ordering_mode`. Consider caching for frequently accessed playlists.

### Risk 3: User Confusion
**Mitigation**:
- Clear UI labels and descriptions
- Default to `default` mode (no changes required)
- Add help tooltips explaining each mode

### Risk 4: Data Migration Complexity
**Mitigation**:
- Test migration on copy of production data
- Make migration idempotent
- Keep `morning_order` field temporarily for rollback capability

---

## Timeline Estimate

- **Phase 1** (Backend Foundation): 2-3 hours
- **Phase 2** (Backend Logic): 3-4 hours
- **Phase 3** (Frontend Basic): 2-3 hours
- **Phase 4** (Frontend Advanced): 4-5 hours
- **Phase 5** (Testing & QA): 2-3 hours

**Total**: ~15-20 hours of development time

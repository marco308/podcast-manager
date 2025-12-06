# Morning Playlist Order Feature

This document outlines the implementation of a new feature that allows users to customize the order of episodes in their morning playlist based on their preferences. The feature aims to enhance user experience by providing more control over the content they consume during their morning routine.

## Feature Overview

The morning playlist should only include a single, most recent, unplayed episode from each podcast. The order of podcasts in the playlist should be determined by user-defined preferences.

- A UI element to set podcast order preference
- A backend job to reorder the morning playlist based on preferences

---

## Implementation Plan

### 1. Database Schema Changes

**Add `morning_order` field to `podcasts` table:**

```sql
ALTER TABLE podcasts ADD COLUMN morning_order INTEGER DEFAULT NULL;
```

- **Type**: `INTEGER` (nullable)
- **Purpose**: Stores the user's preferred order for morning playlist (lower number = earlier in playlist)
- **Default**: `NULL` (unordered, falls back to release date sorting)
- **Index**: Add index for faster ordering queries

**Migration**: Create Alembic migration to add this column

---

### 2. Backend Changes

#### 2.1 Update Podcast Model

**File**: `backend/app/models/podcast.py`

Add field:
```python
morning_order: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
```

#### 2.2 Update Podcast Schema

**File**: `backend/app/schemas/podcast.py`

Add to `PodcastResponse` and `PodcastUpdate`:
```python
morning_order: int | None = None
```

#### 2.3 Update Playlist Builder

**File**: `backend/app/services/playlist_builder.py`

Modify `build_morning_playlist()` method:

```python
async def build_morning_playlist(self) -> list[str]:
    """Build morning playlist: latest episode from NEWS podcasts, ordered by morning_order.
    
    Returns:
        List of episode URIs ordered by user preference (morning_order), then release date.
    """
    podcasts = await self._get_podcasts_by_category(PodcastCategory.NEWS)
    is_weekend = is_weekend_or_holiday()

    latest_episodes: list[tuple[Episode, int | None]] = []  # (episode, morning_order)

    for podcast in podcasts:
        # Skip weekend-only podcasts on weekdays
        if podcast.is_weekend_only and not is_weekend:
            continue

        episodes = await self._get_unplayed_episodes(podcast, max_episodes=10)

        if episodes:
            # Sort by release date descending and take the newest
            sorted_eps = self._sort_episodes(episodes, sequential=False)
            latest_episodes.append((sorted_eps[0], podcast.morning_order))

    # Sort by morning_order (nulls last), then by release date (newest first)
    latest_episodes.sort(
        key=lambda x: (
            x[1] if x[1] is not None else float('inf'),  # morning_order (nulls last)
            x[0].release_date  # release date as tiebreaker (newest first)
        ),
        reverse=False  # Ascending order for morning_order
    )

    return [ep.uri for ep, _ in latest_episodes]
```

**Key Logic**:
- Only include NEWS category podcasts
- Take latest unplayed episode per podcast
- Sort by `morning_order` (ascending, with `NULL` values last)
- Fall back to release date (newest first) for ties or unordered podcasts

#### 2.4 Update API Endpoint

**File**: `backend/app/routers/podcasts.py`

Ensure PATCH `/api/podcasts/{spotify_id}` accepts `morning_order` in request body.

---

### 3. Frontend Changes

#### 3.1 Update Podcast Type

**File**: `frontend/src/types/index.ts`

Add to `Podcast` interface:
```typescript
morning_order: number | null;
```

#### 3.2 Add Morning Order Management Section to Playlists Page

**File**: `frontend/src/pages/Playlists.tsx`

Add a new section above the playlists table to manage morning order for NEWS podcasts:

```tsx
import { usePodcasts, useUpdatePodcast } from '../hooks';

// Add new component for morning order management
function MorningOrderSection() {
  const { data: newsPodcasts, isLoading } = usePodcasts('news');
  const updatePodcast = useUpdatePodcast();
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  const handleOrderChange = async (spotifyId: string, order: number | null) => {
    setUpdatingId(spotifyId);
    try {
      await updatePodcast.mutateAsync({ spotifyId, data: { morning_order: order } });
      message.success('Morning order updated');
    } catch {
      message.error('Failed to update order');
    } finally {
      setUpdatingId(null);
    }
  };

  if (isLoading) {
    return <LoadingSpinner size="small" />;
  }

  // Sort podcasts by morning_order (nulls last), then alphabetically
  const sortedPodcasts = [...(newsPodcasts || [])].sort((a, b) => {
    if (a.morning_order === null && b.morning_order === null) {
      return a.name.localeCompare(b.name);
    }
    if (a.morning_order === null) return 1;
    if (b.morning_order === null) return -1;
    return a.morning_order - b.morning_order;
  });

  return (
    <Card 
      title="Morning Playlist Order" 
      style={{ marginBottom: 24 }}
      extra={
        <Text type="secondary" style={{ fontSize: 12 }}>
          Set the order for NEWS podcasts in your morning playlist
        </Text>
      }
    >
      <List
        dataSource={sortedPodcasts}
        renderItem={(podcast) => (
          <List.Item>
            <List.Item.Meta
              title={podcast.name}
              description={
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {podcast.publisher}
                </Text>
              }
            />
            <InputNumber
              size="small"
              min={1}
              max={999}
              value={podcast.morning_order}
              onChange={(value) => handleOrderChange(podcast.spotify_id, value)}
              placeholder="Order"
              disabled={updatingId === podcast.spotify_id}
              prefix={<SortAscendingOutlined />}
              style={{ width: 120 }}
            />
          </List.Item>
        )}
      />
    </Card>
  );
}

// In main Playlists component, add before the playlists table:
export function Playlists() {
  // ... existing code ...

  return (
    <div>
      <MorningOrderSection />
      
      {/* Existing playlists management UI */}
      <div style={{ display: 'flex', justifyContent: 'space-between', ... }}>
        ...
      </div>
    </div>
  );
}
```

**Required imports to add**:
```tsx
import { Card, List, InputNumber } from 'antd';
import { SortAscendingOutlined } from '@ant-design/icons';
```

#### 3.3 Optional: Drag-and-Drop Reordering

For enhanced UX, add drag-and-drop to visually reorder NEWS podcasts:

**Library**: `@dnd-kit/core`, `@dnd-kit/sortable`

**Implementation**:
- Wrap List in `DndContext` and `SortableContext`
- Add drag handles to each list item
- On drop, recalculate `morning_order` for all affected podcasts and batch update

---

### 4. Testing Plan

#### Backend Tests
1. Test `morning_order` field CRUD operations
2. Test `build_morning_playlist()` ordering logic:
   - Podcasts with `morning_order` sorted correctly
   - `NULL` values sorted to end
   - Release date fallback for ties

#### Frontend Tests
1. Morning order input only shows for NEWS podcasts
2. Input updates podcast `morning_order` via API
3. Validation (min=1, max=999)

#### Integration Tests
1. Update morning order → trigger playlist rebuild → verify Spotify playlist order

---

### 5. Migration Path

1. **Phase 1**: Add `morning_order` column (migration)
2. **Phase 2**: Update backend models/schemas/builder
3. **Phase 3**: Deploy backend
4. **Phase 4**: Update frontend UI
5. **Phase 5**: Deploy frontend
6. **Phase 6**: Users manually set morning order via UI

**Backwards Compatibility**: 
- Existing playlists continue to work (NULL `morning_order` = default sorting by release date)
- No breaking changes to existing API contracts

---

## Future Enhancements

1. **Bulk Order Update**: UI to reorder all NEWS podcasts at once
2. **Auto-numbering**: Button to auto-assign sequential order based on current sort
3. **Presets**: Save/load morning order presets (e.g., "Weekday", "Weekend")
4. **Per-User Orders**: If multi-user support added, store `morning_order` per user

---

## Files to Modify

### Backend
- `backend/alembic/versions/XXX_add_morning_order.py` (new migration)
- `backend/app/models/podcast.py`
- `backend/app/schemas/podcast.py`
- `backend/app/services/playlist_builder.py`
- `backend/app/routers/podcasts.py` (verify PATCH endpoint)

### Frontend
- `frontend/src/types/index.ts`
- `frontend/src/pages/Playlists.tsx` (add MorningOrderSection component)
- `frontend/src/hooks/usePodcasts.ts` (already supports category filtering)

---

## Acceptance Criteria

- [ ] `morning_order` field added to database and models
- [ ] NEWS podcasts can be assigned a morning order via UI on the Playlists page (`/playlists`)
- [ ] Morning order section only shows NEWS category podcasts
- [ ] Morning playlist sorts episodes by `morning_order` (ascending)
- [ ] Podcasts without `morning_order` appear last (sorted alphabetically by name)
- [ ] UI displays podcasts sorted by their current order
- [ ] Playlist updates reflect new order within 5 minutes (or on manual trigger)
- [ ] No breaking changes to existing playlists

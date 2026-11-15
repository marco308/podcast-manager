// Works out what saving the playlist form has to change in the playlist's
// podcast assignments. Pure — no React, no API — so it can be unit-tested.
import type { PickFrom, PlaylistKind } from '../../types';

// The parts of an editor row the diff reads.
export interface AssignmentRow {
  id: number;
  episode_limit: number | null;
  pick_from: PickFrom | null;
}

export interface AssignmentDiff<T extends AssignmentRow> {
  // The membership to save, in order: the draft with anything the playlist's
  // kind can't keep dropped.
  rows: T[];
  // Podcasts to add, in draft order.
  toAdd: T[];
  // Podcasts to remove.
  toRemove: T[];
  // Rows whose overrides need a PATCH.
  toPatch: T[];
  // Whether the saved order differs from the initial one.
  orderChanged: boolean;
}

export function diffAssignments<T extends AssignmentRow>(
  initialRows: T[],
  draftRows: T[],
  kind: PlaylistKind
): AssignmentDiff<T> {
  // A standard playlist can't keep a `random` override; the server clears
  // those when the kind changes, so the draft drops them too.
  const rows = draftRows.map((r) =>
    kind !== 'sleep' && r.pick_from === 'random' ? { ...r, pick_from: null } : r
  );
  const before = new Map(initialRows.map((r) => [r.id, r]));
  const wanted = new Set(rows.map((r) => r.id));
  const toAdd = rows.filter((r) => !before.has(r.id));
  const toRemove = initialRows.filter((r) => !wanted.has(r.id));
  const toPatch = rows.filter((r) => {
    const prev = before.get(r.id);
    // A new row only needs a PATCH when it carries an override; an existing
    // row only when an override changed.
    if (!prev) return r.episode_limit !== null || r.pick_from !== null;
    return prev.episode_limit !== r.episode_limit || prev.pick_from !== r.pick_from;
  });
  const orderChanged =
    toAdd.length > 0 || toRemove.length > 0 || rows.some((r, i) => initialRows[i]?.id !== r.id);

  return { rows, toAdd, toRemove, toPatch, orderChanged };
}

import { createContext, useContext, useMemo } from 'react';
import { Avatar, Button, InputNumber, Select, Space, Table, Tag, Tooltip, Typography } from 'antd';
import type { TableProps } from 'antd';
import { CloseOutlined, HolderOutlined } from '@ant-design/icons';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DraggableAttributes,
  type DraggableSyntheticListeners,
} from '@dnd-kit/core';
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { PickFrom, Podcast } from '../../types';
import { EPISODE_LIMIT_MAX } from '../../types';
import { episodeLimitLabel, pickFromLabel } from '../../utils/playlistLabels';

const { Text } = Typography;

// One row of the editor: a podcast plus its per-playlist overrides. `null`
// means "inherit" (the playlist default, or the sequential hint for pick_from).
export interface EditorRow {
  id: number;
  name: string;
  publisher: string | null;
  image_url: string | null;
  is_sequential: boolean;
  episode_limit: number | null;
  pick_from: PickFrom | null;
}

// Episode-limit override as the Select sees it. 'inherit' maps to null;
// 'custom' keeps a number >= 2 in the row.
type LimitChoice = 'inherit' | 'all' | 'latest' | 'custom';

function limitChoice(limit: number | null): LimitChoice {
  if (limit === null) return 'inherit';
  if (limit === 0) return 'all';
  if (limit === 1) return 'latest';
  return 'custom';
}

interface PlaylistPodcastsEditorProps {
  rows: EditorRow[];
  onChange: (rows: EditorRow[]) => void;
  allPodcasts: Podcast[];
  // The playlist defaults as currently set in the form, so the "Inherit"
  // options can say what they resolve to.
  defaultEpisodeLimit: number;
  defaultPickFrom: PickFrom;
  // Position only matters when the playlist arranges by position.
  orderMatters: boolean;
}

interface RowContextValue {
  setActivatorNodeRef?: (element: HTMLElement | null) => void;
  listeners?: DraggableSyntheticListeners;
  attributes?: DraggableAttributes;
}

// Lets the handle cell reach its row's drag activator without antd having to
// know about dnd-kit (the pattern from antd's "drag sorting" table example).
const RowContext = createContext<RowContextValue>({});

function DragHandle() {
  const { setActivatorNodeRef, listeners, attributes } = useContext(RowContext);
  return (
    <span
      ref={setActivatorNodeRef}
      {...attributes}
      {...listeners}
      role="button"
      tabIndex={0}
      aria-label="Drag to reorder"
      style={{ cursor: 'grab', touchAction: 'none', display: 'inline-flex', padding: 4 }}
    >
      <HolderOutlined style={{ color: '#999' }} />
    </span>
  );
}

interface SortableRowProps extends React.HTMLAttributes<HTMLTableRowElement> {
  'data-row-key': number;
}

function SortableRow(props: SortableRowProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    setActivatorNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: props['data-row-key'] });

  const style: React.CSSProperties = {
    ...props.style,
    transform: CSS.Translate.toString(transform),
    transition,
    ...(isDragging ? { position: 'relative', zIndex: 10, opacity: 0.6 } : {}),
  };

  const contextValue = useMemo<RowContextValue>(
    () => ({ setActivatorNodeRef, listeners, attributes }),
    [setActivatorNodeRef, listeners, attributes]
  );

  return (
    <RowContext.Provider value={contextValue}>
      <tr {...props} ref={setNodeRef} style={style} />
    </RowContext.Provider>
  );
}

export function PlaylistPodcastsEditor({
  rows,
  onChange,
  allPodcasts,
  defaultEpisodeLimit,
  defaultPickFrom,
  orderMatters,
}: PlaylistPodcastsEditorProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
  );

  const assigned = useMemo(() => new Set(rows.map((r) => r.id)), [rows]);
  const available = useMemo(
    () =>
      allPodcasts.filter((p) => !assigned.has(p.id)).map((p) => ({ value: p.id, label: p.name })),
    [allPodcasts, assigned]
  );

  const updateRow = (id: number, patch: Partial<EditorRow>) =>
    onChange(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const handleAdd = (podcastId: number) => {
    const podcast = allPodcasts.find((p) => p.id === podcastId);
    if (!podcast) return;
    onChange([
      ...rows,
      {
        id: podcast.id,
        name: podcast.name,
        publisher: podcast.publisher,
        image_url: podcast.image_url,
        is_sequential: podcast.is_sequential,
        episode_limit: null,
        pick_from: null,
      },
    ]);
  };

  const handleDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    const from = rows.findIndex((r) => r.id === active.id);
    const to = rows.findIndex((r) => r.id === over.id);
    onChange(arrayMove(rows, from, to));
  };

  const columns: TableProps<EditorRow>['columns'] = [
    {
      key: 'sort',
      width: 36,
      render: () => <DragHandle />,
    },
    {
      title: 'Podcast',
      key: 'podcast',
      render: (_, row) => (
        <Space size={8}>
          {row.image_url ? (
            <Avatar
              src={row.image_url}
              size={32}
              shape="square"
              style={{ borderRadius: 6, flexShrink: 0 }}
            >
              {row.name[0]}
            </Avatar>
          ) : null}
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Text ellipsis style={{ maxWidth: 220 }}>
                {row.name}
              </Text>
              {row.is_sequential && (
                <Tooltip title="Sequential: takes from the oldest unfinished episode unless overridden">
                  <Tag color="blue" style={{ fontSize: 10, margin: 0 }}>
                    SEQ
                  </Tag>
                </Tooltip>
              )}
            </div>
            {row.publisher && (
              <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                {row.publisher}
              </Text>
            )}
          </div>
        </Space>
      ),
    },
    {
      title: 'Episodes',
      key: 'episode_limit',
      width: 220,
      render: (_, row) => {
        const choice = limitChoice(row.episode_limit);
        return (
          <Space size={4}>
            <Select<LimitChoice>
              size="small"
              value={choice}
              style={{ width: choice === 'custom' ? 110 : 150 }}
              onChange={(value) =>
                updateRow(row.id, {
                  episode_limit:
                    value === 'inherit' ? null : value === 'all' ? 0 : value === 'latest' ? 1 : 2,
                })
              }
              options={[
                { value: 'inherit', label: `Inherit (${episodeLimitLabel(defaultEpisodeLimit)})` },
                { value: 'all', label: 'All unplayed' },
                { value: 'latest', label: 'Latest only' },
                { value: 'custom', label: 'Up to…' },
              ]}
            />
            {choice === 'custom' && (
              <InputNumber
                size="small"
                min={2}
                max={EPISODE_LIMIT_MAX}
                precision={0}
                value={row.episode_limit ?? 2}
                onChange={(value) => updateRow(row.id, { episode_limit: value ?? 2 })}
                style={{ width: 70 }}
              />
            )}
          </Space>
        );
      },
    },
    {
      title: 'Take from',
      key: 'pick_from',
      width: 170,
      render: (_, row) => {
        const inherited = row.is_sequential ? 'oldest' : defaultPickFrom;
        return (
          <Select<'inherit' | PickFrom>
            size="small"
            value={row.pick_from ?? 'inherit'}
            style={{ width: 160 }}
            onChange={(value) =>
              updateRow(row.id, { pick_from: value === 'inherit' ? null : value })
            }
            options={[
              {
                value: 'inherit',
                label: `Inherit (${pickFromLabel(inherited)}${row.is_sequential ? ', sequential' : ''})`,
              },
              { value: 'newest', label: 'Newest' },
              { value: 'oldest', label: 'Oldest' },
            ]}
          />
        );
      },
    },
    {
      key: 'remove',
      width: 40,
      render: (_, row) => (
        <Tooltip title="Remove from playlist">
          <Button
            size="small"
            type="text"
            danger
            icon={<CloseOutlined />}
            aria-label="Remove from playlist"
            onClick={() => onChange(rows.filter((r) => r.id !== row.id))}
          />
        </Tooltip>
      ),
    },
  ];

  return (
    <div>
      <Select<number>
        showSearch
        style={{ width: '100%', marginBottom: 8 }}
        placeholder={
          available.length ? 'Add a podcast…' : 'Every podcast is already in this playlist'
        }
        disabled={available.length === 0}
        optionFilterProp="label"
        value={undefined}
        onSelect={handleAdd}
        options={available}
      />
      {rows.length === 0 ? (
        <Text type="secondary">No podcasts yet. Add one above.</Text>
      ) : (
        <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
          <SortableContext items={rows.map((r) => r.id)} strategy={verticalListSortingStrategy}>
            <Table<EditorRow>
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={rows}
              columns={columns}
              components={{ body: { row: SortableRow } }}
              scroll={{ x: 560 }}
            />
          </SortableContext>
        </DndContext>
      )}
      <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 8 }}>
        {orderMatters
          ? 'Drag rows to set the order podcasts appear in. Changes apply when you save.'
          : 'Row order is only used when the arrangement is "In podcast order". Changes apply when you save.'}
      </Text>
    </div>
  );
}

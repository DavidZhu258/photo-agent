import React, { useState } from 'react';

function chipPlaceholder(id) {
  return {
    Where: 'Fukuoka / Kyoto',
    When: '2026-06-10 to 2026-06-12',
    Who: '2 people',
    Budget: '1000 CNY',
    Preferences: 'yatai, quiet temples',
    Avoid: 'queues, crowds'
  }[id] || id;
}

export default function TripHeader() {
  const initial = props || {};
  const [localProps, setLocalProps] = useState(initial);
  const chips = Array.isArray(localProps.chips) ? localProps.chips : [];

  async function updateChip(chip) {
    const value = window.prompt(chip.label || chip.id, chip.value || '');
    if (value === null) return;
    const response = await callAction({
      name: 'trip_header_update',
      payload: { field: chip.id, value }
    });
    const nextProps = response?.response || {
      ...localProps,
      chips: chips.map((item) =>
        item.id === chip.id
          ? { ...item, value, label: value || item.id, empty: !value }
          : item
      )
    };
    setLocalProps(nextProps);
    await updateElement(nextProps);
  }

  async function shareTrip() {
    const text = localProps.share_text || `${localProps.title || 'Trip'}\n${localProps.subtitle || ''}`;
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    }
  }

  return (
    <div className="trip-header-shell mt-2 rounded-lg border bg-background px-4 py-3">
      <div className="trip-header-row">
        <div className="min-w-0">
          <div className="trip-header-title truncate">
            {localProps.title || 'Michi'}
          </div>
          <div className="trip-header-subtitle truncate">
            {localProps.subtitle || '旅径'}
          </div>
        </div>

        <div className="trip-header-chips">
          {chips.map((chip) => (
            <button
              key={chip.id}
              type="button"
              className={`trip-header-chip ${chip.empty ? 'is-empty' : ''}`}
              title={chipPlaceholder(chip.id)}
              onClick={() => updateChip(chip)}
            >
              {chip.label || chip.id}
            </button>
          ))}
        </div>

        <div className="trip-header-actions">
          <button type="button" className="trip-header-action">
            Trip
            <span className="trip-header-badge">{localProps.trip_count || 0}</span>
          </button>
          <button type="button" className="trip-header-icon" onClick={shareTrip} title="Share">
            Share
          </button>
        </div>
      </div>
    </div>
  );
}

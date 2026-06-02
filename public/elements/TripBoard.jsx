import React, { useEffect, useMemo, useRef, useState } from 'react';

const DEFAULT_CENTER = { lat: 35.6812, lng: 139.7671 };

function ratingText(card) {
  const parts = [];
  if (card.rating) parts.push(String(card.rating));
  if (card.review_count) parts.push(`${card.review_count} reviews`);
  return parts.join(' · ');
}

function cardImages(card) {
  const urls = Array.isArray(card.image_urls) ? card.image_urls : [];
  const values = card.image_url ? [card.image_url, ...urls] : urls;
  return Array.from(new Set(values.filter((url) => typeof url === 'string' && url.startsWith('http'))));
}

function validPins(map) {
  const pins = Array.isArray(map.pins) ? map.pins : [];
  return pins.filter((pin) => Number.isFinite(Number(pin.lat)) && Number.isFinite(Number(pin.lng)));
}

function safeCenter(center) {
  if (Number.isFinite(Number(center?.lat)) && Number.isFinite(Number(center?.lng))) {
    return { lat: Number(center.lat), lng: Number(center.lng) };
  }
  return DEFAULT_CENTER;
}

function boundsForPins(pins, center) {
  const points = pins.length ? pins : [safeCenter(center)];
  const lats = points.map((point) => Number(point.lat));
  const lngs = points.map((point) => Number(point.lng));
  const latMin = Math.min(...lats);
  const latMax = Math.max(...lats);
  const lngMin = Math.min(...lngs);
  const lngMax = Math.max(...lngs);
  const latPad = Math.max((latMax - latMin) * 0.18, 0.01);
  const lngPad = Math.max((lngMax - lngMin) * 0.18, 0.01);
  return {
    latMin: latMin - latPad,
    latMax: latMax + latPad,
    lngMin: lngMin - lngPad,
    lngMax: lngMax + lngPad
  };
}

function projectPin(pin, bounds) {
  const lngSpan = bounds.lngMax - bounds.lngMin || 1;
  const latSpan = bounds.latMax - bounds.latMin || 1;
  const x = ((Number(pin.lng) - bounds.lngMin) / lngSpan) * 100;
  const y = (1 - (Number(pin.lat) - bounds.latMin) / latSpan) * 100;
  return {
    left: `${Math.min(94, Math.max(6, x))}%`,
    top: `${Math.min(92, Math.max(8, y))}%`
  };
}

function googleMapsUrl(cardOrPin) {
  return cardOrPin?.google_maps_uri || cardOrPin?.googleMapsUri || '';
}

function loadGoogleMaps(apiKey) {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return Promise.reject(new Error('Google Maps requires a browser.'));
  }
  if (window.google?.maps?.Map) {
    return Promise.resolve(window.google.maps);
  }
  if (window.__photoAgentGoogleMapsPromise) {
    return window.__photoAgentGoogleMapsPromise;
  }
  window.__photoAgentGoogleMapsPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    const params = new URLSearchParams({
      key: apiKey,
      v: 'weekly',
      libraries: 'maps,marker,places',
      loading: 'async'
    });
    script.src = `https://maps.googleapis.com/maps/api/js?${params.toString()}`;
    script.async = true;
    script.defer = true;
    script.onload = async () => {
      try {
        if (window.google?.maps?.importLibrary) {
          await window.google.maps.importLibrary('maps');
        }
        resolve(window.google.maps);
      } catch (error) {
        reject(error);
      }
    };
    script.onerror = () => reject(new Error('Failed to load Google Maps.'));
    document.head.appendChild(script);
  });
  return window.__photoAgentGoogleMapsPromise;
}

function markerContent(pin, active, index) {
  const node = document.createElement('button');
  node.type = 'button';
  node.className = `trip-google-marker ${active ? 'is-active' : ''}`;
  node.title = pin.title || `Stop ${index + 1}`;
  node.innerHTML = `
    <span class="trip-google-marker-dot">${index + 1}</span>
    <span class="trip-google-marker-label">${pin.title || 'Place'}</span>
  `;
  return node;
}

function clearMarker(marker) {
  if (!marker) return;
  if (typeof marker.setMap === 'function') {
    marker.setMap(null);
    return;
  }
  marker.map = null;
}

function FallbackTripMap({ map, pins, cards, selected, selectedId, setSelectedId }) {
  return (
    <div className="trip-board-map">
      <div className="trip-google-map-missing">
        <div className="trip-google-map-missing-card">
          <div className="trip-google-map-missing-title">Google Maps is not configured</div>
          <p>
            Set <code>GOOGLE_MAPS_API_KEY</code> and restart Chainlit to render the
            movable embedded Google map with pins.
          </p>
          <div className="trip-google-map-missing-list">
            {pins.slice(0, 8).map((pin) => (
              <button
                key={pin.id}
                type="button"
                className={`trip-google-map-missing-pin ${pin.id === selectedId ? 'is-active' : ''}`}
                onClick={() => setSelectedId(pin.id)}
              >
                {pin.title}
              </button>
            ))}
          </div>
          <MapCallout card={selected} />
        </div>
      </div>
    </div>
  );
}

function GoogleTripMap({ map, pins, cards, selected, selectedId, setSelectedId }) {
  const apiKey = map.api_key || map.browser_key || props.google_maps_key || '';
  const mapId = map.map_id || '';
  const mapElement = useRef(null);
  const mapInstance = useRef(null);
  const markers = useRef([]);
  const [loadState, setLoadState] = useState(apiKey ? 'loading' : 'missing_key');

  useEffect(() => {
    let cancelled = false;
    if (!apiKey || map.provider !== 'google_maps') {
      setLoadState('missing_key');
      return undefined;
    }
    setLoadState('loading');
    loadGoogleMaps(apiKey)
      .then(() => {
        if (!cancelled) setLoadState('ready');
      })
      .catch(() => {
        if (!cancelled) setLoadState('error');
      });
    return () => {
      cancelled = true;
    };
  }, [apiKey, map.provider]);

  useEffect(() => {
    if (!apiKey || map.provider !== 'google_maps' || loadState === 'ready') {
      return undefined;
    }
    const timer = window.setInterval(() => {
      if (window.google?.maps?.Map) {
        setLoadState('ready');
        window.clearInterval(timer);
      }
    }, 400);
    return () => window.clearInterval(timer);
  }, [apiKey, loadState, map.provider]);

  useEffect(() => {
    if (
      loadState !== 'ready' &&
      apiKey &&
      map.provider === 'google_maps' &&
      window.google?.maps?.Map
    ) {
      setLoadState('ready');
    }
  }, [apiKey, loadState, map.provider]);

  useEffect(() => {
    let cancelled = false;
    async function renderMap() {
      if (loadState !== 'ready' || !mapElement.current || !window.google?.maps) return;
      const center = safeCenter(map.center);
      let MapCtor = window.google.maps.Map;
      if (window.google.maps.importLibrary) {
        try {
          const mapsLib = await window.google.maps.importLibrary('maps');
          MapCtor = mapsLib.Map || MapCtor;
        } catch {
          MapCtor = window.google.maps.Map;
        }
      }
      if (!MapCtor) {
        setLoadState('error');
        return;
      }
      if (!mapInstance.current) {
        mapInstance.current = new MapCtor(mapElement.current, {
          center,
          zoom: pins.length ? 13 : 11,
          mapId: mapId || undefined,
          clickableIcons: true,
          fullscreenControl: true,
          mapTypeControl: false,
          streetViewControl: false,
          zoomControl: true
        });
      }
      const googleMap = mapInstance.current;
      markers.current.forEach(clearMarker);
      markers.current = [];

      let AdvancedMarkerElement = null;
      if (mapId && window.google.maps.importLibrary) {
        try {
          const markerLib = await window.google.maps.importLibrary('marker');
          AdvancedMarkerElement = markerLib.AdvancedMarkerElement || null;
        } catch {
          AdvancedMarkerElement = null;
        }
      }
      if (cancelled) return;

      if (!pins.length) {
        googleMap.setCenter(center);
        googleMap.setZoom(11);
        return;
      }

      const bounds = new window.google.maps.LatLngBounds();
      pins.forEach((pin, index) => {
        const position = { lat: Number(pin.lat), lng: Number(pin.lng) };
        bounds.extend(position);
        if (AdvancedMarkerElement) {
          const content = markerContent(pin, pin.id === selectedId, index);
          content.addEventListener('click', () => setSelectedId(pin.id));
          const marker = new AdvancedMarkerElement({
            map: googleMap,
            position,
            title: pin.title || '',
            content
          });
          marker.addListener('click', () => setSelectedId(pin.id));
          markers.current.push(marker);
        } else {
          const marker = new window.google.maps.Marker({
            map: googleMap,
            position,
            title: pin.title || '',
            label: {
              text: String(index + 1),
              color: '#ffffff',
              fontSize: '12px',
              fontWeight: '700'
            }
          });
          marker.addListener('click', () => setSelectedId(pin.id));
          markers.current.push(marker);
        }
      });
      googleMap.fitBounds(bounds, 64);
      if (pins.length === 1) {
        googleMap.setZoom(14);
      }
    }
    renderMap();
    return () => {
      cancelled = true;
    };
  }, [loadState, pins, selectedId, setSelectedId, map.center, mapId]);

  useEffect(() => {
    if (loadState !== 'ready' || !mapInstance.current) return;
    const selectedPin = pins.find((pin) => pin.id === selectedId);
    if (!selectedPin) return;
    mapInstance.current.panTo({ lat: Number(selectedPin.lat), lng: Number(selectedPin.lng) });
  }, [loadState, pins, selectedId]);

  if (loadState === 'missing_key') {
    return (
      <FallbackTripMap
        map={map}
        pins={pins}
        cards={cards}
        selected={selected}
        selectedId={selectedId}
        setSelectedId={setSelectedId}
      />
    );
  }

  return (
    <div className="trip-board-map">
      <div className="trip-google-map-shell">
        <div ref={mapElement} className="trip-google-map-canvas" />
        {loadState !== 'ready' ? <div className="trip-map-loading">Loading Google Maps...</div> : null}
        <div className="trip-google-map-toolbar">
          <span>{pins.length} places</span>
          {googleMapsUrl(selected) ? (
            <a href={googleMapsUrl(selected)} target="_blank" rel="noreferrer">
              Open in Google Maps
            </a>
          ) : null}
        </div>
        <MapCallout card={selected} />
      </div>
    </div>
  );
}

function MapCallout({ card }) {
  if (!card?.title) return null;
  return (
    <div className="trip-map-callout">
      <div className="trip-map-callout-title">{card.title}</div>
      <div className="trip-map-callout-meta">
        {[card.category, card.subcategory, card.trip_state].filter(Boolean).join(' · ')}
      </div>
      <div className="trip-map-callout-address">
        {card.address || 'Map location pending confirmation'}
      </div>
      <div className="trip-map-callout-links">
        {card.google_maps_uri ? (
          <a href={card.google_maps_uri} target="_blank" rel="noreferrer">
            Google Maps
          </a>
        ) : null}
        {card.directions_uri ? (
          <a href={card.directions_uri} target="_blank" rel="noreferrer">
            Directions
          </a>
        ) : null}
      </div>
    </div>
  );
}

export default function TripBoard() {
  const [cards, setCards] = useState(Array.isArray(props.cards) ? props.cards : []);
  const map = props.map || {};
  const pins = useMemo(() => validPins(map), [map]);
  const [selectedId, setSelectedId] = useState(
    map.selected_pin_id || (cards[0] && cards[0].id) || ''
  );
  const [imageIndexes, setImageIndexes] = useState({});

  useEffect(() => {
    const nextCards = Array.isArray(props.cards) ? props.cards : [];
    setCards(nextCards);
    setSelectedId(map.selected_pin_id || (nextCards[0] && nextCards[0].id) || '');
    setImageIndexes({});
  }, [props.cards, map.selected_pin_id]);

  const selected = useMemo(() => {
    return cards.find((card) => card.id === selectedId) || cards[0] || {};
  }, [cards, selectedId]);

  async function cardAction(event, action, card) {
    event.stopPropagation();
    const nextState =
      action === 'add_to_trip'
        ? 'planned'
        : card.trip_state === 'liked'
          ? 'none'
          : 'liked';
    const nextCards = cards.map((item) =>
      item.id === card.id ? { ...item, trip_state: nextState } : item
    );
    setCards(nextCards);
    await callAction({ name: 'trip_card_action', payload: { action, card } });
  }

  function changeImage(event, card, delta) {
    event.stopPropagation();
    const images = cardImages(card);
    if (images.length < 2) return;
    const current = imageIndexes[card.id] || 0;
    const next = (current + delta + images.length) % images.length;
    setImageIndexes({ ...imageIndexes, [card.id]: next });
  }

  return (
    <div className="trip-board-shell mt-4 overflow-hidden rounded-lg border bg-background">
      <div className="trip-board-header flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
        <div>
          <div className="text-sm font-semibold">{props.title || 'Trip Board'}</div>
          <div className="text-xs text-muted-foreground">
            {cards.length} recommendations · {pins.length} mapped
          </div>
        </div>
        <div className="flex flex-wrap gap-2 text-xs">
          {Array.from(new Set(cards.map((card) => card.category).filter(Boolean)))
            .slice(0, 5)
            .map((category) => (
              <span key={category} className="rounded-full border px-2 py-1">
                {category}
              </span>
            ))}
        </div>
      </div>

      <div className="trip-board-grid">
        <div className="trip-board-list">
          {cards.map((card) => {
            const active = card.id === selected.id;
            const images = cardImages(card);
            const imageIndex = imageIndexes[card.id] || 0;
            const currentImage = images[imageIndex] || '';
            return (
              <div
                key={card.id}
                onClick={() => setSelectedId(card.id)}
                role="button"
                tabIndex={0}
                className={`trip-board-card ${active ? 'is-active' : ''}`}
              >
                <div className="trip-card-copy">
                  <div className="trip-card-meta">
                    <span>{card.category || 'Recommendation'}</span>
                    {card.subcategory ? <span>{card.subcategory}</span> : null}
                    {card.price ? <span>{card.price}</span> : null}
                    {ratingText(card) ? <span>{ratingText(card)}</span> : null}
                  </div>
                  <div className="trip-card-title">{card.title}</div>
                  {card.subtitle ? <div className="trip-card-subtitle">{card.subtitle}</div> : null}
                  <p className="trip-card-description">
                    {card.description || card.reason || 'API recommendation.'}
                  </p>
                  {card.address ? <div className="trip-card-address">{card.address}</div> : null}
                  <div className="trip-board-card-actions">
                    <button
                      type="button"
                      className={`trip-board-mini-action ${card.trip_state === 'liked' ? 'is-active' : ''}`}
                      onClick={(event) => cardAction(event, 'toggle_like', card)}
                    >
                      Like
                    </button>
                    <button
                      type="button"
                      className={`trip-board-mini-action ${card.trip_state === 'planned' ? 'is-active' : ''}`}
                      onClick={(event) => cardAction(event, 'add_to_trip', card)}
                    >
                      Add to Trip
                    </button>
                    {card.google_maps_uri ? (
                      <a
                        href={card.google_maps_uri}
                        target="_blank"
                        rel="noreferrer"
                        className="trip-board-mini-action"
                        onClick={(event) => event.stopPropagation()}
                      >
                        Google Maps
                      </a>
                    ) : null}
                    {card.directions_uri ? (
                      <a
                        href={card.directions_uri}
                        target="_blank"
                        rel="noreferrer"
                        className="trip-board-mini-action"
                        onClick={(event) => event.stopPropagation()}
                      >
                        Directions
                      </a>
                    ) : null}
                  </div>
                </div>

                <div className="trip-card-media">
                  {currentImage ? (
                    <img
                      src={currentImage}
                      alt={card.title}
                      className="trip-card-image"
                      loading="lazy"
                      referrerPolicy="no-referrer"
                    />
                  ) : (
                    <div className="trip-card-image-placeholder">
                      No verified place photo
                    </div>
                  )}
                  {images.length > 1 ? (
                    <>
                      <button
                        type="button"
                        className="trip-card-image-nav is-prev"
                        onClick={(event) => changeImage(event, card, -1)}
                        aria-label="Previous image"
                      >
                        ‹
                      </button>
                      <button
                        type="button"
                        className="trip-card-image-nav is-next"
                        onClick={(event) => changeImage(event, card, 1)}
                        aria-label="Next image"
                      >
                        ›
                      </button>
                      <div className="trip-card-image-dots">
                        {images.slice(0, 5).map((url, index) => (
                          <span
                            key={url}
                            className={`trip-card-image-dot ${index === imageIndex ? 'is-active' : ''}`}
                          />
                        ))}
                      </div>
                    </>
                  ) : null}
                  {card.photo_attributions?.length ? (
                    <div className="trip-card-photo-credit">{card.photo_attributions[0]}</div>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>

        <GoogleTripMap
          map={map}
          pins={pins}
          cards={cards}
          selected={selected}
          selectedId={selectedId}
          setSelectedId={setSelectedId}
        />
      </div>
    </div>
  );
}

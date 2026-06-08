import type { UIMessage } from "ai";

export type TripContext = {
  city?: string;
  where?: string;
  when?: string;
  who?: string;
  budget?: string;
  preferences?: string[];
  avoid?: string[];
  tripItems?: TripCard[];
  likedItems?: TripCard[];
  lastQuery?: string;
  activeQuery?: string;
  lastAnswerMode?: string;
  lastCards?: TripCard[];
  lastMapPins?: TripPin[];
  lastItineraryPlan?: TripItineraryPlan;
  selectedCardId?: string;
};

export type TripChip = {
  id: string;
  label: string;
  value: string;
};

export type TripAnswerSection = {
  id: string;
  title: string;
  body: string;
  bullets: string[];
  chips?: string[];
  tables?: {
    caption?: string;
    columns: string[];
    rows: string[][];
  }[];
  images?: {
    url: string;
    caption?: string;
    source?: string;
  }[];
  card_ids?: string[];
  pin_ids?: string[];
};

export type TripAnswerSectionsPart = {
  type: "trip-answer-sections";
  sections: TripAnswerSection[];
};

export type TripHeaderPart = {
  type: "trip-header";
  title: string;
  subtitle: string;
  chips: TripChip[];
  trip_count: number;
};

export type TripCard = {
  id: string;
  title: string;
  category: string;
  subcategory: string;
  subtitle?: string;
  description?: string;
  rating?: number | null;
  review_count?: number | null;
  price?: string;
  address?: string;
  image_url?: string;
  image_urls?: string[];
  image_status?: string;
  source_url?: string;
  source_provider?: string;
  place_id?: string;
  reason?: string;
  display_reason?: string;
  lat?: number | null;
  lng?: number | null;
  tags?: string[];
  trip_state?: "none" | "liked" | "planned";
  google_maps_uri?: string;
  directions_uri?: string;
  mapbox_uri?: string;
  match_reason?: string;
  matched_terms?: string[];
  match_score?: number;
  source_query?: string;
};

export type TripCardsPart = {
  type: "trip-cards";
  cards: TripCard[];
};

export type TripHotelOffer = {
  id: string;
  title: string;
  provider?: string;
  price?: string;
  rating?: number | null;
  review_count?: number | null;
  address?: string;
  image_url?: string;
  image_urls?: string[];
  source_url?: string;
  booking_url?: string;
  check_in_date?: string;
  check_out_date?: string;
  currency?: string;
  display_reason?: string;
  data_gaps?: string[];
};

export type TripFlightOffer = {
  id: string;
  title: string;
  provider?: string;
  airline?: string;
  departure_airport?: string;
  arrival_airport?: string;
  departure_time?: string;
  arrival_time?: string;
  duration?: string;
  stops?: string;
  price?: string;
  currency?: string;
  source_url?: string;
  booking_url?: string;
  display_reason?: string;
  data_gaps?: string[];
};

export type TripHotelsPart = {
  type: "trip-hotels";
  offers: TripHotelOffer[];
};

export type TripFlightsPart = {
  type: "trip-flights";
  offers: TripFlightOffer[];
};

export type TripPin = {
  id: string;
  title: string;
  category?: string;
  subcategory?: string;
  lat: number;
  lng: number;
  rating?: number | null;
  address?: string;
  place_id?: string;
  trip_state?: string;
  google_maps_uri?: string;
  directions_uri?: string;
  mapbox_uri?: string;
};

export type TripMap = {
  provider?: string;
  mode?: string;
  center?: { lat: number; lng: number };
  pins: TripPin[];
  selected_pin_id?: string;
  status?: string;
};

export type TripMapPart = {
  type: "trip-map";
  map: TripMap;
};

export type RuntimeWarningsPart = {
  type: "runtime-warnings";
  warnings: string[];
};

export type FollowupsPart = {
  type: "followups";
  questions: string[];
};

type TripItineraryBlock = {
  title?: string;
  place_ids?: string[];
  route_note?: string;
  budget_note?: string;
  why?: string;
  alternatives?: string[];
};

type TripItineraryDay = {
  day?: number;
  title?: string;
  date?: string;
  time_blocks?: TripItineraryBlock[];
};

type TripItineraryPlan = {
  title?: string;
  summary?: string;
  days?: TripItineraryDay[];
  assumptions?: string[];
};

export type TravelChatPart =
  | { type: "text"; text: string }
  | TripAnswerSectionsPart
  | TripHeaderPart
  | TripCardsPart
  | TripHotelsPart
  | TripFlightsPart
  | TripMapPart
  | RuntimeWarningsPart
  | FollowupsPart;

export type TravelChatMessage = Omit<UIMessage, "parts" | "role"> & {
  role: "user" | "assistant";
  content?: string;
  parts: TravelChatPart[];
};

export type RawTravelPlan = {
  summary?: string;
  narrative_answer?: string;
  answer_sections?: TripAnswerSection[];
  answer_mode?: string;
  intent_summary?: string;
  plan_draft?: Record<string, unknown>;
  decision_cards?: Record<string, unknown>[];
  itinerary_plan?: TripItineraryPlan;
  followup_slots?: string[];
  formatted_markdown?: string;
  category_groups?: { title?: string; items?: string[]; reason?: string }[];
  resolved_intent?: Record<string, unknown>;
  display_cards?: TripCard[];
  hotel_offers?: TripHotelOffer[];
  flight_offers?: TripFlightOffer[];
  map_view?: Partial<TripMap>;
  optional_followups?: string[];
  data_gaps?: string[];
  uncertainty?: string[];
  raw_provider_refs?: Record<string, unknown>;
};

export function inferCityFromText(text: string): string {
  const lowered = text.toLowerCase();
  if (lowered.includes("广岛") || lowered.includes("廣島") || lowered.includes("hiroshima")) {
    return "Hiroshima";
  }
  if (lowered.includes("福冈") || lowered.includes("福岡") || lowered.includes("fukuoka")) {
    return "Fukuoka";
  }
  if (lowered.includes("东京") || lowered.includes("東京") || lowered.includes("tokyo")) {
    return "Tokyo";
  }
  if (lowered.includes("京都") || lowered.includes("kyoto")) {
    return "Kyoto";
  }
  if (lowered.includes("大阪") || lowered.includes("osaka")) {
    return "Osaka";
  }
  if (lowered.includes("别府") || lowered.includes("別府") || lowered.includes("beppu")) {
    return "Beppu";
  }
  if (lowered.includes("宫岛") || lowered.includes("宮島") || lowered.includes("miyajima")) {
    return "Miyajima";
  }
  return "";
}

export function inferRequestedCategories(text: string): string[] {
  const lowered = text.toLowerCase();
  if (
    /好吃|吃的|吃饭|吃什么|去哪吃|美食|餐厅|拉面|屋台|日料|日本料理|寿司|food|restaurant|ramen|sushi/.test(
      lowered,
    )
  ) {
    return ["美食"];
  }
  if (/购物|买|香水|商场|伴手礼|shopping|perfume|fragrance/.test(lowered)) {
    return ["购物"];
  }
  if (/历史|文化|寺|神社|博物馆|遗迹|heritage|museum/.test(lowered)) {
    return ["历史文化"];
  }
  if (/温泉|溫泉|泡汤|泡湯|泡温泉|泡溫泉|onsen|hot spring|public bath|rotenburo/.test(lowered)) {
    return ["本地体验"];
  }
  if (/好玩|玩什么|去哪玩|景点|活动|体验|things to do|attraction/.test(lowered)) {
    return ["本地体验"];
  }
  if (/街区|逛街|商店街|neighborhood/.test(lowered)) {
    return ["购物与街区"];
  }
  if (/自然|摄影|拍照|风景|公园|日落|photo|sunset/.test(lowered)) {
    return ["自然与摄影"];
  }
  return [];
}

export function mergeContextFromText(context: TripContext, text: string): TripContext {
  const city = inferCityFromText(text) || context.city || "";
  const preferences = Array.from(
    new Set([
      ...(context.preferences ?? []),
      ...inferPreferenceTagsFromText(text),
    ]),
  );
  return {
    ...context,
    city,
    where: city || context.where || "",
    preferences,
  };
}

export function buildTravelPayload(message: string, context: TripContext) {
  const city = context.city || inferCityFromText(message);
  const query = contextualizedQuery(message, context);
  const explicitInterestTags = inferExplicitInterestTags(message);
  const inheritedInterestTags = context.preferences ?? [];
  const carryPlaceMemory = shouldCarryPlaceMemory(message, context);
  return {
    city,
    origin_city: null,
    query,
    question: message,
    interest_tags: Array.from(
      new Set([...inheritedInterestTags, ...explicitInterestTags]),
    ),
    avoid: context.avoid ?? [],
    fixed_itinerary: [],
    date_range: context.when ? [context.when] : [],
    budget: context.budget ?? "",
    travelers: parseTravelers(context.who),
    requested_categories: [],
    previous_context: {
      city,
      date_range: context.when ? [context.when] : [],
      budget: context.budget,
      travelers: parseTravelers(context.who),
      interest_tags: context.preferences ?? [],
      avoid: context.avoid ?? [],
      active_query: context.activeQuery,
      current_user_message: message,
      last_query: context.lastQuery,
      last_answer_mode: context.lastAnswerMode,
      last_cards: carryPlaceMemory ? compactCards(context.lastCards) : [],
      map_pins: carryPlaceMemory ? compactPins(context.lastMapPins) : [],
      selected_card_id: carryPlaceMemory ? context.selectedCardId : "",
      itinerary_plan: context.lastItineraryPlan,
      trip_items: compactCards(context.tripItems),
      liked_items: compactCards(context.likedItems),
    },
    allow_web_search: true,
    evidence_refresh: "auto",
  };
}

function shouldCarryPlaceMemory(message: string, context: TripContext): boolean {
  const hasPlaceMemory =
    Boolean(context.selectedCardId) ||
    Boolean(context.lastCards?.length) ||
    Boolean(context.lastMapPins?.length);
  if (!hasPlaceMemory) {
    return false;
  }
  const raw = message.trim();
  if (!raw) {
    return false;
  }
  if (isRefinementFollowup(raw, context)) {
    return true;
  }
  return /这些|這些|上面|前面|刚才|剛才|地图|地圖|卡片|第[一二三四五六七八九十0-9]+个|这个|這個|那个|那個|那家|它|那里|那裡|顺路|順路|哪一个|哪個|哪个|加入|收藏|路线|路線|怎么排|怎麼排/.test(
    raw,
  );
}

export function mergeContextFromPlan(
  context: TripContext,
  plan: RawTravelPlan,
  query?: string,
): TripContext {
  const city = cityFromPlan(plan) || context.city || "";
  const cards = normalizeCards(plan.display_cards).slice(0, 12);
  const map = normalizeMap(plan.map_view, cards);
  const answerMode = String(
    plan.answer_mode ?? plan.resolved_intent?.answer_mode ?? "",
  ).trim();
  const next: TripContext = {
    ...context,
    city,
    where: city || context.where || "",
    lastQuery: query?.trim() || context.lastQuery,
    activeQuery: activeQueryFromPlan(context, query),
    lastAnswerMode: answerMode || context.lastAnswerMode,
  };
  if (cards.length > 0) {
    next.lastCards = cards;
  }
  if (map.pins.length > 0) {
    next.lastMapPins = map.pins;
    next.selectedCardId = map.selected_pin_id || cards[0]?.id || context.selectedCardId;
  }
  if (plan.itinerary_plan && Array.isArray(plan.itinerary_plan.days) && plan.itinerary_plan.days.length > 0) {
    next.lastItineraryPlan = plan.itinerary_plan;
  }
  return next;
}

function inferExplicitInterestTags(text: string): string[] {
  const lowered = text.toLowerCase();
  const tags: string[] = [];
  if (/温泉|溫泉|泡汤|泡湯|泡温泉|泡溫泉|onsen|hot spring|public bath|rotenburo/.test(lowered)) {
    tags.push("温泉");
  }
  if (/日料|日本料理|寿司|sushi|kaiseki|tempura|izakaya/.test(lowered)) {
    tags.push("日料");
  }
  if (/香水|perfume|fragrance|parfum|nicolai|ニコライ/.test(lowered)) {
    tags.push("香水");
  }
  return tags;
}

function inferPreferenceTagsFromText(text: string): string[] {
  const lowered = text.toLowerCase();
  const tags: string[] = [];
  if (/户外风光|自然风光|自然|海边|海岸|山景|森林|湖泊|徒步|hiking|outdoor|nature|scenery/.test(lowered)) {
    tags.push("户外风光");
  }
  if (/亲子|带娃|儿童|family|kids/.test(lowered)) {
    tags.push("亲子");
  }
  if (/慢节奏|轻松|不累|悠闲|relax/.test(lowered)) {
    tags.push("轻松");
  }
  if (/小众|人少|避开游客|local/.test(lowered)) {
    tags.push("小众");
  }
  return tags;
}

function contextualizedQuery(message: string, context: TripContext): string {
  const raw = message.trim();
  if (!raw || !isRefinementFollowup(raw, context)) {
    return message;
  }
  const activeQuery = context.activeQuery || context.lastQuery;
  if (!activeQuery) {
    return message;
  }
  if (context.city) {
    return `${context.city} ${raw}`;
  }
  return `${activeQuery}；用户补充偏好或约束：${raw}`;
}

function activeQueryFromPlan(context: TripContext, query?: string): string | undefined {
  const raw = query?.trim();
  if (!raw) {
    return context.activeQuery;
  }
  if (isRefinementFollowup(raw, context)) {
    return context.activeQuery || context.lastQuery || raw;
  }
  return raw;
}

function isRefinementFollowup(text: string, context: TripContext): boolean {
  if (!(context.activeQuery || context.lastQuery)) {
    return false;
  }
  if (inferCityFromText(text)) {
    return false;
  }
  if (/去哪|哪里|推荐|怎么走|路线|酒店|航班|天气|签证|安全吗|怎么样|评价|[?？]/.test(text)) {
    return false;
  }
  return (
    inferPreferenceTagsFromText(text).length > 0 ||
    /喜欢|偏好|预算|不要|别太|改成|换成|更|轻松|小众|带娃|亲子|户外|风光|自然|\d+\s*天|[一二三四五六七八九十两]\s*天/.test(
      text,
    )
  );
}

function cityFromPlan(plan: RawTravelPlan): string {
  const intent = plan.resolved_intent ?? {};
  const candidates = [
    intent.city,
    intent.destination,
    intent.destination_city,
    intent.place,
  ];
  for (const candidate of candidates) {
    const value = String(candidate ?? "").trim();
    if (!value) continue;
    return inferCityFromText(value) || value;
  }
  return "";
}

function compactCards(cards: TripCard[] | undefined): Partial<TripCard>[] {
  if (!Array.isArray(cards)) {
    return [];
  }
  return cards.slice(0, 12).map((card) => ({
    id: card.id,
    title: card.title,
    category: card.category,
    subcategory: card.subcategory,
    address: card.address,
    rating: card.rating,
    review_count: card.review_count,
    price: card.price,
    source_provider: card.source_provider,
    place_id: card.place_id,
    lat: card.lat,
    lng: card.lng,
    trip_state: card.trip_state,
  }));
}

function compactPins(pins: TripPin[] | undefined): Partial<TripPin>[] {
  if (!Array.isArray(pins)) {
    return [];
  }
  return pins.slice(0, 12).map((pin) => ({
    id: pin.id,
    title: pin.title,
    category: pin.category,
    subcategory: pin.subcategory,
    lat: pin.lat,
    lng: pin.lng,
    rating: pin.rating,
    address: pin.address,
    place_id: pin.place_id,
  }));
}

export function buildAssistantMessageFromPlan(
  plan: RawTravelPlan,
  context: TripContext,
  query: string,
): TravelChatMessage {
  const cards = normalizeCards(plan.display_cards);
  const hotelOffers = normalizeHotelOffers(plan.hotel_offers);
  const flightOffers = normalizeFlightOffers(plan.flight_offers);
  const map = normalizeMap(plan.map_view, cards);
  const header = buildTripHeader(plan, context, cards);
  const answerSections = answerSectionsFromPlan(plan);
  const text = conversationalText(plan, cards, query, answerSections);
  const warnings = runtimeWarnings(plan);
  const followups = [
    ...(Array.isArray(plan.followup_slots) ? plan.followup_slots : []),
    ...(Array.isArray(plan.optional_followups) ? plan.optional_followups : []),
    ...(Array.isArray(plan.data_gaps) ? plan.data_gaps : []),
  ].slice(0, 3);

  return {
    id: `assistant-${Date.now()}`,
    role: "assistant",
    parts: [
      { type: "text", text },
      ...(answerSections.length > 0
        ? [{ type: "trip-answer-sections" as const, sections: answerSections }]
        : []),
      header,
      ...(hotelOffers.length > 0 ? [{ type: "trip-hotels" as const, offers: hotelOffers }] : []),
      ...(flightOffers.length > 0 ? [{ type: "trip-flights" as const, offers: flightOffers }] : []),
      { type: "trip-cards", cards },
      { type: "trip-map", map },
      { type: "runtime-warnings", warnings },
      { type: "followups", questions: followups },
    ],
  };
}

export function buildMissingDestinationMessage(): TravelChatMessage {
  return {
    id: `assistant-${Date.now()}`,
    role: "assistant",
    parts: [
      {
        type: "text",
        text: "我可以直接推荐，但需要先知道目的地。你可以像这样问：福冈有什么好玩的？",
      },
      {
        type: "trip-header",
        title: "Mira",
        subtitle: "识境",
        trip_count: 0,
        chips: defaultChips({}),
      },
      { type: "trip-cards", cards: [] },
      { type: "trip-map", map: { pins: [], status: "empty" } },
    ],
  };
}

export function textFromMessage(message: TravelChatMessage): string {
  if (message.content) {
    return message.content;
  }
  const textPart = message.parts.find((part) => part.type === "text");
  return textPart?.type === "text" ? textPart.text : "";
}

export function userFacingRuntimeWarnings(warnings: unknown): string[] {
  if (!Array.isArray(warnings)) {
    return [];
  }
  return warnings
    .map(String)
    .filter((warning) => warning.trim().length > 0)
    .filter((warning) => !isInternalProviderWarning(warning))
    .slice(0, 4);
}

function buildTripHeader(
  plan: RawTravelPlan,
  context: TripContext,
  cards: TripCard[],
): TripHeaderPart {
  const intent = plan.resolved_intent ?? {};
  const category = String(intent.category ?? cards[0]?.category ?? "").trim();
  const city = String(intent.city ?? context.city ?? "").trim();
  const cityLabel = cityDisplayName(city);
  return {
    type: "trip-header",
    title: cityLabel && category ? `${cityLabel}${category}推荐` : "Mira",
    subtitle: city ? `Trip to ${city}` : "识境",
    trip_count: context.tripItems?.length ?? 0,
    chips: defaultChips({ ...context, city }),
  };
}

function defaultChips(context: TripContext): TripChip[] {
  return [
    { id: "Where", label: "Where", value: context.city ?? context.where ?? "" },
    { id: "When", label: "When", value: context.when ?? "" },
    { id: "Who", label: "Who", value: context.who ?? "" },
    { id: "Budget", label: "Budget", value: context.budget ?? "" },
    {
      id: "Preferences",
      label: "Preferences",
      value: (context.preferences ?? []).join(", "),
    },
  ];
}

function normalizeHotelOffers(offers: TripHotelOffer[] | undefined): TripHotelOffer[] {
  if (!Array.isArray(offers)) {
    return [];
  }
  return offers.slice(0, 8).map((offer, index) => ({
    ...offer,
    id: offer.id || `hotel-${index + 1}`,
    image_urls: Array.from(
      new Set(
        [offer.image_url, ...(Array.isArray(offer.image_urls) ? offer.image_urls : [])].filter(
          (url): url is string => typeof url === "string" && url.startsWith("http"),
        ),
      ),
    ),
    data_gaps: Array.isArray(offer.data_gaps) ? offer.data_gaps : [],
  }));
}

function normalizeFlightOffers(offers: TripFlightOffer[] | undefined): TripFlightOffer[] {
  if (!Array.isArray(offers)) {
    return [];
  }
  return offers.slice(0, 8).map((offer, index) => ({
    ...offer,
    id: offer.id || `flight-${index + 1}`,
    data_gaps: Array.isArray(offer.data_gaps) ? offer.data_gaps : [],
  }));
}

function normalizeCards(cards: TripCard[] | undefined): TripCard[] {
  if (!Array.isArray(cards)) {
    return [];
  }
  return cards.slice(0, 12).map((card, index) => ({
    ...card,
    id: card.id || `card-${index + 1}`,
    image_urls: Array.from(
      new Set(
        [card.image_url, ...(Array.isArray(card.image_urls) ? card.image_urls : [])].filter(
          (url): url is string => typeof url === "string" && url.startsWith("http"),
        ),
      ),
    ),
    trip_state: card.trip_state ?? "none",
  }));
}

function normalizeMap(mapView: Partial<TripMap> | undefined, cards: TripCard[]): TripMap {
  const pinsFromMap = Array.isArray(mapView?.pins) ? mapView.pins : [];
  const pins =
    pinsFromMap.length > 0
      ? pinsFromMap
      : cards
          .filter((card) => Number.isFinite(card.lat) && Number.isFinite(card.lng))
          .map((card) => ({
            id: card.id,
            title: card.title,
            category: card.category,
            subcategory: card.subcategory,
            lat: Number(card.lat),
            lng: Number(card.lng),
            rating: card.rating,
            address: card.address,
            place_id: card.place_id,
            trip_state: card.trip_state,
            google_maps_uri: card.google_maps_uri,
            directions_uri: card.directions_uri,
            mapbox_uri: card.mapbox_uri,
          }));
  return {
    provider: "mapbox",
    mode: "mapbox_gl",
    center: mapView?.center ?? centerFromPins(pins),
    selected_pin_id: mapView?.selected_pin_id ?? pins[0]?.id ?? "",
    status: mapView?.status ?? (pins.length ? "ready" : "needs_coordinates"),
    pins,
  };
}

function conversationalText(
  plan: RawTravelPlan,
  cards: TripCard[],
  query: string,
  answerSections: TripAnswerSection[] = [],
): string {
  const itinerary = itineraryText(plan.itinerary_plan);
  if (itinerary) {
    return itinerary;
  }
  if (answerSections.length > 0) {
    const lead = leadTextFromAnswerSections(answerSections);
    if (lead) {
      return lead;
    }
  }
  if (typeof plan.narrative_answer === "string" && plan.narrative_answer.trim()) {
    return plan.narrative_answer.trim();
  }
  if (typeof plan.intent_summary === "string" && plan.intent_summary.trim()) {
    return plan.intent_summary.trim();
  }
  if (cards.length > 0) {
    const category = cards[0].category || "推荐";
    const names = cards
      .slice(0, 3)
      .map((card) => card.title)
      .join("、");
    return `我按你的问题只筛了${category}相关选择，先给你这些更容易落地的地点：${names}。你可以直接点卡片看位置、图片和地图链接，喜欢的先加进 Trip；如果你补充时间、预算或同行人，我再帮你收窄顺序。`;
  }
  return (
    plan.summary ||
    `我会根据“${query}”先给可执行选择，再把需要确认的信息放到后面。`
  );
}

function leadTextFromAnswerSections(answerSections: TripAnswerSection[]): string {
  const first = answerSections.find((section) => section.body || section.bullets.length > 0);
  if (!first) {
    return "";
  }
  const body = cleanPublicText(first.body);
  if (body) {
    return body;
  }
  const bullet = first.bullets.map((item) => cleanPublicText(item)).find(Boolean);
  return bullet ?? "";
}

function answerSectionsFromPlan(plan: RawTravelPlan): TripAnswerSection[] {
  if (Array.isArray(plan.answer_sections) && plan.answer_sections.length > 0) {
    return plan.answer_sections
      .map((section, index) => normalizeAnswerSection(section, index))
      .filter(
        (section) =>
          section.title &&
          (section.body || section.bullets.length > 0 || Boolean(section.tables?.length) || Boolean(section.images?.length)),
      );
  }
  const source =
    textCandidate(plan.narrative_answer) ||
    textCandidate(plan.formatted_markdown) ||
    textCandidate(plan.summary);
  if (!source) {
    return [];
  }
  return parseAnswerSections(source).slice(0, 4);
}

function normalizeAnswerSection(section: TripAnswerSection, index: number): TripAnswerSection {
  const title = cleanPublicText(String(section.title ?? ""));
  return {
    id: section.id || sectionId(title, index),
    title,
    body: cleanPublicText(String(section.body ?? "")),
    bullets: Array.isArray(section.bullets)
      ? section.bullets.map((bullet) => cleanPublicText(String(bullet))).filter(Boolean).slice(0, 8)
      : [],
    chips: Array.isArray(section.chips) ? section.chips.map(String).filter(Boolean).slice(0, 8) : [],
    tables: normalizeSectionTables(section.tables),
    images: normalizeSectionImages(section.images),
    card_ids: Array.isArray(section.card_ids) ? section.card_ids.map(String).filter(Boolean) : [],
    pin_ids: Array.isArray(section.pin_ids) ? section.pin_ids.map(String).filter(Boolean) : [],
  };
}

function normalizeSectionTables(tables: TripAnswerSection["tables"]): TripAnswerSection["tables"] {
  if (!Array.isArray(tables)) return [];
  return tables
    .map((table) => ({
      caption: typeof table.caption === "string" ? cleanPublicText(table.caption) : "",
      columns: Array.isArray(table.columns)
        ? table.columns.map((column) => cleanPublicText(String(column))).filter(Boolean)
        : [],
      rows: Array.isArray(table.rows)
        ? table.rows
            .filter((row) => Array.isArray(row))
            .map((row) => row.map((cell) => cleanPublicText(String(cell))))
            .filter((row) => row.some(Boolean))
        : [],
    }))
    .filter((table) => table.columns.length > 0 || table.rows.length > 0)
    .slice(0, 4);
}

function normalizeSectionImages(images: TripAnswerSection["images"]): TripAnswerSection["images"] {
  if (!Array.isArray(images)) return [];
  return images
    .map((image) => ({
      url: typeof image.url === "string" ? image.url.trim() : "",
      caption: typeof image.caption === "string" ? cleanPublicText(image.caption) : "",
      source: typeof image.source === "string" ? cleanPublicText(image.source) : "",
    }))
    .filter((image) => image.url.startsWith("http"))
    .slice(0, 4);
}

function textCandidate(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function parseAnswerSections(markdown: string): TripAnswerSection[] {
  const sections: TripAnswerSection[] = [];
  let current: TripAnswerSection | null = null;
  const bodyLines: string[] = [];

  function flush() {
    if (!current) return;
    const body = cleanPublicText(bodyLines.join(" "));
    sections.push({
      ...current,
      body,
      bullets: current.bullets.map(cleanPublicText).filter(Boolean).slice(0, 5),
    });
    bodyLines.length = 0;
  }

  for (const rawLine of markdown.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const heading = line.match(/^#{2,4}\s+(.+)$/);
    if (heading) {
      flush();
      const title = cleanPublicText(heading[1]);
      current = {
        id: sectionId(title, sections.length),
        title,
        body: "",
        bullets: [],
      };
      continue;
    }
    if (!current) continue;
    const bullet = line.match(/^(?:[-*•]|\d+[.)、])\s*(.+)$/);
    if (bullet) {
      current.bullets.push(bullet[1]);
    } else {
      bodyLines.push(line);
    }
  }
  flush();

  return sections.filter((section) => section.title && (section.body || section.bullets.length > 0));
}

function sectionId(title: string, index: number): string {
  const known: Record<string, string> = {
    "怎么选": "how-to-choose",
    "去哪儿": "where-to-go",
    "怎么排/地图": "map-order",
    "怎么走/地图": "map-order",
  };
  if (known[title]) {
    return known[title];
  }
  const slug = title
    .toLowerCase()
    .replace(/[`*_#]/g, "")
    .replace(/[^\p{Letter}\p{Number}]+/gu, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40);
  return slug || `answer-section-${index + 1}`;
}

function cleanPublicText(value: string): string {
  return value
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/<[^>]*>/g, "")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

function itineraryText(plan: TripItineraryPlan | undefined): string {
  if (!plan || !Array.isArray(plan.days) || plan.days.length === 0) {
    return "";
  }
  const lines: string[] = [];
  if (typeof plan.title === "string" && plan.title.trim()) {
    lines.push(plan.title.trim());
  }
  if (typeof plan.summary === "string" && plan.summary.trim()) {
    lines.push(plan.summary.trim());
  }
  for (const day of plan.days) {
    const title = typeof day.title === "string" && day.title.trim()
      ? day.title.trim()
      : `第${day.day ?? lines.length}天`;
    lines.push(title);
    const blocks = Array.isArray(day.time_blocks) ? day.time_blocks : [];
    for (const block of blocks) {
      const blockTitle = String(block.title ?? "").trim();
      if (!blockTitle) continue;
      const details = String(block.route_note ?? "").trim();
      lines.push(`- ${blockTitle}${details ? `：${details}` : ""}`);
    }
  }
  return lines.join("\n").trim();
}

function runtimeWarnings(plan: RawTravelPlan): string[] {
  const refs = plan.raw_provider_refs;
  if (!refs || typeof refs !== "object") {
    return [];
  }
  const warnings = refs.model_runtime_warnings;
  return userFacingRuntimeWarnings(warnings);
}

function isInternalProviderWarning(warning: string): boolean {
  return /Google Places 解析|Quota exceeded|SearchTextRequest|模型调用失败|formatter .*失败|critic .*失败|HTTP\s*5\d\d/i.test(
    warning,
  );
}

function centerFromPins(pins: TripPin[]): { lat: number; lng: number } {
  if (pins.length === 0) {
    return { lat: 33.5902, lng: 130.4017 };
  }
  return {
    lat: pins.reduce((sum, pin) => sum + Number(pin.lat), 0) / pins.length,
    lng: pins.reduce((sum, pin) => sum + Number(pin.lng), 0) / pins.length,
  };
}

function parseTravelers(who: string | undefined): number {
  const match = String(who ?? "").match(/\d+/);
  return match ? Number.parseInt(match[0], 10) : 1;
}

function cityDisplayName(city: string): string {
  const normalized = city.toLowerCase();
  if (normalized === "fukuoka") return "福冈";
  if (normalized === "kyoto") return "京都";
  if (normalized === "osaka") return "大阪";
  if (normalized === "beppu") return "别府";
  if (normalized === "miyajima") return "宫岛";
  return city;
}

export type Place = {
  place_id: number | null;
  name: string;
  name_ja?: string | null;
  category: string;
  tags: string[];
  photo_potential?: number;
};

export type EvidenceCard = {
  source_type: string;
  title: string;
  snippet: string;
  score: number;
  ad_risk: number;
};

export type OpenSourceStep = {
  step_id: string;
  framework: string;
  title: string;
  summary: string;
  status: string;
  metadata: Record<string, unknown>;
};

export type ApiSource = {
  provider: string;
  name: string;
  source_type: string;
  format: string;
  commercial: boolean;
  status: string;
  url?: string | null;
  ad_risk?: number;
};

export type CacheInfo = {
  provider: string;
  key: string;
  hit: boolean;
  ttl_seconds: number;
};

export type ImportSummary = {
  places_upserted: number;
  aliases_created: number;
  evidence_created: number;
};

export type TravelRecommendation = {
  place: Place;
  score: number;
  reasons: string[];
  caution: string;
  ad_risk_label: string;
  decision: string;
  decision_reason: string;
  pros: string[];
  cons: string[];
  evidence_confidence: string;
  evidence_cards: EvidenceCard[];
};

export type TravelSuggestionGroup = {
  title: string;
  intent: string;
  items: string[];
  reason: string;
  evidence_needed: boolean;
};

export type TravelPlan = {
  summary: string;
  recommendations: TravelRecommendation[];
  not_recommended: TravelRecommendation[];
  conditional_options: TravelRecommendation[];
  excluded_candidates: TravelRecommendation[];
  decision_notes: string[];
  uncertainty: string[];
  evidence_cards: EvidenceCard[];
  pros: string[];
  cons: string[];
  route_summary: {
    used?: boolean;
    source?: string;
    warnings?: string[];
  };
  suggestion_groups: TravelSuggestionGroup[];
  category_groups: TravelSuggestionGroup[];
  suggestion_source: string;
  api_sources_used: ApiSource[];
  source_breakdown: Record<string, number>;
  commercial_disclosure: string;
  raw_provider_refs: Record<string, unknown>;
  thinking_steps: OpenSourceStep[];
  cache: CacheInfo;
  search_used: boolean;
  search_queries: string[];
  sources_consulted: string[];
  data_gaps: string[];
  evidence_freshness: string;
  llm_used: boolean;
  model_used: string;
  reasoning_mode: string;
  needs_user_confirmation: boolean;
};

export type TravelAgentResult = {
  model?: string;
  summary?: string;
  raw_api_count?: number;
  status?: string;
};

export type TravelPlanInput = {
  city: string;
  originCity: string;
  dateText: string;
  budget: string;
  travelers: number;
  question: string;
  interests: string;
  avoid: string;
};

export type EvidenceSearchResult = {
  search_used: boolean;
  search_queries: string[];
  sources_consulted: string[];
  data_gaps: string[];
  evidence_freshness: string;
};

export type EvidenceSearchRun = {
  query: string;
  city?: string | null;
  trigger_reason: string;
  status: string;
  result_count: number;
  imported_count: number;
  error?: string | null;
  created_at?: string | null;
};

export type VisibleClue = {
  clue: string;
  interpretation: string;
  confidence: number;
};

export type CulturalHypothesis = {
  name: string;
  entity_type: string;
  region?: string | null;
  rationale: string;
  confidence: number;
  evidence_support: string[];
  evidence_against: string[];
};

export type PerspectiveCard = {
  perspective: string;
  title: string;
  summary: string;
  reasons: string[];
  confidence: number;
  followup_prompt?: string | null;
};

export type DeepVisualSection = {
  title: string;
  body: string;
  bullets: string[];
  chips: string[];
  tables?: {
    caption: string;
    columns: string[];
    rows: string[][];
  }[];
  images?: {
    url: string;
    caption: string;
    source: string;
  }[];
};

export type DeepVisualCard = {
  title: string;
  body: string;
  supporting_points: string[];
  next_action: string;
  sections: DeepVisualSection[];
};

export type VisualMemoryItem = {
  memory_id: string;
  title: string;
  entity_type: string;
  region_hint?: string | null;
  thumbnail_sha256?: string | null;
  status: string;
};

export type VisualWorkflowSummary = {
  provider: string;
  model: string;
  selected_perspectives: string[];
  knowledge_used: boolean;
  confidence: number;
  uncertainty: string[];
};

export type RelatedVisualPlace = {
  place_id?: number | null;
  name: string;
  relation: string;
  reason: string;
  distance_meters?: number | null;
};

export type VisualExploreResult = {
  session_id: string;
  what_it_is: string;
  why_it_matters: string;
  why_popular_or_overhyped: string;
  related_places: RelatedVisualPlace[];
  needs_user_confirmation: boolean;
  story_title: string;
  narrative: string;
  visible_clues: VisibleClue[];
  cultural_hypotheses: CulturalHypothesis[];
  meaning_layers: Record<string, string>;
  confidence_notes: string[];
  followup_questions: string[];
  one_line_answer: string;
  deep_cards: DeepVisualCard[];
  perspective_cards: PerspectiveCard[];
  visual_memory_item?: VisualMemoryItem | null;
  audio_script: string;
  visual_workflow_summary: VisualWorkflowSummary;
  visual_matches: {
    provider: string;
    title: string;
    source: string;
    url?: string | null;
    thumbnail_url?: string | null;
    match_type: string;
    confidence: number;
  }[];
  knowledge_cards: EvidenceCard[];
  api_sources_used: ApiSource[];
  source_breakdown: Record<string, number>;
  thinking_steps: OpenSourceStep[];
  cache: CacheInfo;
};

export type VisualFollowupResult = {
  session_id: string;
  answer: string;
  evidence_cards: EvidenceCard[];
  followup_questions: string[];
};

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api-backend";

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

function asArray<T>(value: T[] | undefined | null): T[] {
  return Array.isArray(value) ? value : [];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function normalizePlace(place: Partial<Place> | undefined): Place {
  return {
    place_id: place?.place_id ?? null,
    name: place?.name ?? "Unknown place",
    name_ja: place?.name_ja ?? null,
    category: place?.category ?? "unknown",
    tags: asArray(place?.tags),
    photo_potential: place?.photo_potential,
  };
}

function normalizeEvidenceCard(card: Partial<EvidenceCard>): EvidenceCard {
  return {
    source_type: card.source_type ?? "unknown",
    title: card.title ?? "Untitled evidence",
    snippet: card.snippet ?? "",
    score: card.score ?? 0,
    ad_risk: card.ad_risk ?? 0,
  };
}

function normalizeSuggestionGroup(
  group: Partial<TravelSuggestionGroup>,
): TravelSuggestionGroup {
  return {
    title: group.title ?? "未分类",
    intent: group.intent ?? "",
    items: asArray(group.items),
    reason: group.reason ?? "",
    evidence_needed: group.evidence_needed ?? false,
  };
}

function normalizeRecommendation(
  item: Partial<TravelRecommendation>,
): TravelRecommendation {
  return {
    place: normalizePlace(item.place),
    score: item.score ?? 0,
    reasons: asArray(item.reasons),
    caution: item.caution ?? "",
    ad_risk_label: item.ad_risk_label ?? "未知",
    decision: item.decision ?? "conditional",
    decision_reason: item.decision_reason ?? "",
    pros: asArray(item.pros),
    cons: asArray(item.cons),
    evidence_confidence: item.evidence_confidence ?? "unknown",
    evidence_cards: asArray(item.evidence_cards).map(normalizeEvidenceCard),
  };
}

function normalizeTravelPlan(raw: Partial<TravelPlan>): TravelPlan {
  const suggestionGroups = asArray(raw.suggestion_groups).map(normalizeSuggestionGroup);
  const categoryGroups = asArray(raw.category_groups).map(normalizeSuggestionGroup);
  const recommendations = asArray(raw.recommendations).map(normalizeRecommendation);

  return {
    summary: raw.summary ?? "",
    recommendations,
    not_recommended: asArray(raw.not_recommended).map(normalizeRecommendation),
    conditional_options: asArray(raw.conditional_options).map(normalizeRecommendation),
    excluded_candidates: asArray(raw.excluded_candidates).map(normalizeRecommendation),
    decision_notes: asArray(raw.decision_notes),
    uncertainty: asArray(raw.uncertainty),
    evidence_cards: asArray(raw.evidence_cards).map(normalizeEvidenceCard),
    pros: asArray(raw.pros),
    cons: asArray(raw.cons),
    route_summary: {
      used: raw.route_summary?.used,
      source: raw.route_summary?.source,
      warnings: asArray(raw.route_summary?.warnings),
    },
    suggestion_groups: suggestionGroups,
    category_groups: categoryGroups.length > 0 ? categoryGroups : suggestionGroups,
    suggestion_source: raw.suggestion_source ?? "unknown",
    api_sources_used: asArray(raw.api_sources_used),
    source_breakdown: raw.source_breakdown ?? {},
    commercial_disclosure: raw.commercial_disclosure ?? "",
    raw_provider_refs: raw.raw_provider_refs ?? {},
    thinking_steps: asArray(raw.thinking_steps),
    cache: raw.cache ?? {
      provider: "none",
      key: "",
      hit: false,
      ttl_seconds: 0,
    },
    search_used: raw.search_used ?? false,
    search_queries: asArray(raw.search_queries),
    sources_consulted: asArray(raw.sources_consulted),
    data_gaps: asArray(raw.data_gaps),
    evidence_freshness: raw.evidence_freshness ?? "unknown",
    llm_used: raw.llm_used ?? false,
    model_used: raw.model_used ?? "unknown",
    reasoning_mode: raw.reasoning_mode ?? "unknown",
    needs_user_confirmation: raw.needs_user_confirmation ?? true,
  };
}

function normalizeVisualResult(raw: Partial<VisualExploreResult>): VisualExploreResult {
  return {
    session_id: raw.session_id ?? "",
    what_it_is: raw.what_it_is ?? "",
    why_it_matters: raw.why_it_matters ?? "",
    why_popular_or_overhyped: raw.why_popular_or_overhyped ?? "",
    related_places: asArray(raw.related_places),
    needs_user_confirmation: raw.needs_user_confirmation ?? true,
    story_title: raw.story_title ?? "",
    narrative: raw.narrative ?? "",
    visible_clues: asArray(raw.visible_clues),
    cultural_hypotheses: asArray(raw.cultural_hypotheses).map((item) => ({
      ...item,
      evidence_support: asArray(item.evidence_support),
      evidence_against: asArray(item.evidence_against),
    })),
    meaning_layers: asRecord(raw.meaning_layers) as Record<string, string>,
    confidence_notes: asArray(raw.confidence_notes),
    followup_questions: asArray(raw.followup_questions),
    one_line_answer: raw.one_line_answer ?? "",
    deep_cards: asArray(raw.deep_cards).map((card) => ({
      title: card.title ?? "",
      body: card.body ?? "",
      supporting_points: asArray(card.supporting_points),
      next_action: card.next_action ?? "",
      sections: asArray(card.sections).map((section) => ({
        title: section.title ?? "",
        body: section.body ?? "",
        bullets: asArray(section.bullets),
        chips: asArray(section.chips),
        tables: asArray((section as DeepVisualSection).tables).map((table) => ({
          caption: table.caption ?? "",
          columns: asArray(table.columns),
          rows: asArray(table.rows).map((row) => asArray(row).map(String)),
        })),
        images: asArray((section as DeepVisualSection).images)
          .map((image) => ({
            url: image.url ?? "",
            caption: image.caption ?? "",
            source: image.source ?? "",
          }))
          .filter((image) => /^https?:\/\//i.test(image.url)),
      })),
    })),
    perspective_cards: asArray(raw.perspective_cards).map((card) => ({
      perspective: card.perspective ?? "guide",
      title: card.title ?? "视觉视角",
      summary: card.summary ?? "",
      reasons: asArray(card.reasons),
      confidence: card.confidence ?? 0,
      followup_prompt: card.followup_prompt ?? null,
    })),
    visual_memory_item: raw.visual_memory_item
      ? {
          memory_id: raw.visual_memory_item.memory_id ?? "",
          title: raw.visual_memory_item.title ?? "Visual memory",
          entity_type: raw.visual_memory_item.entity_type ?? "unknown",
          region_hint: raw.visual_memory_item.region_hint ?? null,
          thumbnail_sha256: raw.visual_memory_item.thumbnail_sha256 ?? null,
          status: raw.visual_memory_item.status ?? "discovered",
        }
      : null,
    audio_script: raw.audio_script ?? "",
    visual_workflow_summary: raw.visual_workflow_summary ?? {
      provider: "unknown",
      model: "vision",
      selected_perspectives: [],
      knowledge_used: false,
      confidence: 0,
      uncertainty: [],
    },
    visual_matches: asArray(raw.visual_matches),
    knowledge_cards: asArray(raw.knowledge_cards).map(normalizeEvidenceCard),
    api_sources_used: asArray(raw.api_sources_used),
    source_breakdown: raw.source_breakdown ?? {},
    thinking_steps: asArray(raw.thinking_steps),
    cache: raw.cache ?? {
      provider: "none",
      key: "",
      hit: false,
      ttl_seconds: 0,
    },
  };
}

export async function fetchPlaces(token: string) {
  const response = await fetch(`${apiBaseUrl}/v1/admin/places`, {
    headers: { "X-Admin-Token": token },
  });
  const raw = await readJson<{ places?: Partial<Place>[] }>(response);
  return { places: asArray(raw.places).map(normalizePlace) };
}

export async function importEvidence(token: string, payload: unknown) {
  const response = await fetch(`${apiBaseUrl}/v1/admin/import-evidence`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": token,
    },
    body: JSON.stringify(payload),
  });
  return readJson<ImportSummary>(response);
}

export async function searchEvidence(token: string, input: {
  city: string;
  query: string;
  interestTags: string[];
}) {
  const response = await fetch(`${apiBaseUrl}/v1/admin/evidence/search-exa`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Token": token,
    },
    body: JSON.stringify({
      city: input.city,
      query: input.query,
      interest_tags: input.interestTags,
      trigger_reason: "manual_admin",
    }),
  });
  return readJson<EvidenceSearchResult>(response);
}

export async function fetchSearchRuns(token: string) {
  const response = await fetch(`${apiBaseUrl}/v1/admin/evidence/search-runs`, {
    headers: { "X-Admin-Token": token },
  });
  const raw = await readJson<{ runs?: EvidenceSearchRun[] }>(response);
  return { runs: asArray(raw.runs) };
}

function parseDateRange(dateText: string): string[] {
  return dateText
    .split(/到|至|~|—|-{2}|,/)
    .map((item) => item.trim())
    .filter(Boolean)
    .slice(0, 2);
}

export function travelAgentResults(plan: TravelPlan): [string, TravelAgentResult][] {
  const agentResults = plan.raw_provider_refs.agent_results;
  if (!agentResults || typeof agentResults !== "object" || Array.isArray(agentResults)) {
    return [];
  }
  return Object.entries(agentResults as Record<string, TravelAgentResult>);
}

export async function planTravel(input: TravelPlanInput) {
  const response = await fetch(`${apiBaseUrl}/v1/travel/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      city: input.city,
      origin_city: input.originCity || null,
      query: input.question,
      question: input.question,
      interest_tags: input.interests
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      constraints: input.budget ? [`预算：${input.budget}`] : [],
      avoid: input.avoid
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
      fixed_itinerary: [],
      date_range: parseDateRange(input.dateText),
      budget: input.budget,
      travelers: Number.isFinite(input.travelers) ? input.travelers : 1,
      allow_web_search: true,
      evidence_refresh: "auto",
    }),
  });
  return normalizeTravelPlan(await readJson<Partial<TravelPlan>>(response));
}

export async function exploreVisual(input: {
  imagesBase64: string[];
  userContextText: string;
  explorationFocus: string;
  interestTags: string[];
}) {
  const response = await fetch(`${apiBaseUrl}/v1/visual/discover`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      images_base64: input.imagesBase64,
      user_context_text: input.userContextText,
      exploration_focus: input.explorationFocus,
      interest_tags: input.interestTags,
    }),
  });
  return normalizeVisualResult(await readJson<Partial<VisualExploreResult>>(response));
}

export async function followupVisual(input: {
  sessionId: string;
  question: string;
  imagesBase64: string[];
  previousResult: Partial<VisualExploreResult>;
  userContextText: string;
  explorationFocus: string;
  interestTags: string[];
}) {
  const response = await fetch(`${apiBaseUrl}/v1/visual/followup`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: input.sessionId,
      question: input.question,
      images_base64: input.imagesBase64,
      previous_result: input.previousResult,
      user_context_text: input.userContextText,
      exploration_focus: input.explorationFocus,
      interest_tags: input.interestTags,
    }),
  });
  const raw = await readJson<Partial<VisualFollowupResult>>(response);
  return {
    session_id: raw.session_id ?? input.sessionId,
    answer: raw.answer ?? "",
    evidence_cards: asArray(raw.evidence_cards).map(normalizeEvidenceCard),
    followup_questions: asArray(raw.followup_questions),
  };
}

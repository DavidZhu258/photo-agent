import pytest

from app.schemas.visual import (
    ClientOcr,
    EvidenceCard,
    PlaceCandidate,
    ShootHint,
    VisualExploreInput,
    VisualExploreResponse,
    VisualFollowupInput,
)
from app.services.agent import AgentDependencies, VisualExploreAgent


class FakeCache:
    def __init__(self):
        self.items = {}
        self.saved = []

    async def get(self, key):
        return self.items.get(key)

    async def put(self, key, value):
        self.items[key] = value
        self.saved.append((key, value))


class FakeVlm:
    def __init__(self):
        self.calls = 0

    async def identify(self, request):
        self.calls += 1
        return {
            "subject": "temple gate",
            "place_candidates": ["青蓮院門跡"],
            "confidence": 0.76,
            "visible_clues": [
                {
                    "clue": "painted wooden gate",
                    "interpretation": "historic temple entrance",
                    "confidence": 0.7,
                }
            ],
            "cultural_hypotheses": [
                {
                    "name": "Kyoto temple gate",
                    "entity_type": "place",
                    "region": "Kyoto",
                    "rationale": "wooden gate and garden context",
                    "confidence": 0.65,
                    "evidence_support": ["temple architecture"],
                    "evidence_against": ["limited angle"],
                }
            ],
        }


class FakeNarrative:
    def __init__(self):
        self.calls = 0
        self.last_visual_reasoning = {}

    async def compose(self, request, visual_reasoning, evidence_cards):
        self.calls += 1
        self.last_visual_reasoning = visual_reasoning
        return {
            "story_title": "静かな門が教えてくれること",
            "narrative": "写真の意味は、門そのものよりも、静けさを守る庭の気配にあります。",
            "meaning_layers": {
                "visual": "木門と庭の奥行き",
                "cultural_history": visual_reasoning.get("meaning_layers", {}).get(
                    "cultural_history",
                    "門跡寺院の静かな格式",
                ),
                "emotional": "観光地の外側に残る落ち着き",
                "practical": "角度を変えると庭との関係が見える",
            },
            "confidence_notes": ["角度が限られるため候補として扱う"],
            "followup_questions": ["庭側から撮った写真はありますか？"],
        }


class ComposeOnlyNarrative(FakeNarrative):
    answer_followup = None


class FailingNarrative:
    async def compose(self, request, visual_reasoning, evidence_cards):
        raise RuntimeError("narrative unavailable")


class FakePlaceResolver:
    async def resolve(self, request, vlm_result):
        return [
            PlaceCandidate(
                place_id=1,
                name="Shoren-in Monzeki",
                name_ja="青蓮院門跡",
                category="temple",
                lat=35.0076,
                lng=135.7825,
                confidence=0.82,
                match_reason="matched OCR/GPS",
                distance_meters=80,
                tags=["quiet", "garden"],
                photo_potential=0.86,
            )
        ]


class FakeEvidenceStore:
    async def search(self, request, candidates):
        return {
            1: [
                EvidenceCard(
                    source_type="official",
                    title="Official temple history",
                    snippet="A Tendai temple known for gardens and sliding-door paintings.",
                    url="https://example.jp/shorenin",
                    score=0.91,
                    ad_risk=0.0,
                    local_signal=0.8,
                    tourist_signal=0.35,
                )
            ]
        }


class FakeOfficialHistoryEnricher:
    def __init__(self):
        self.calls = []

    async def enrich(self, request, visual_reasoning):
        self.calls.append((request, visual_reasoning))
        return {
            "meaning_layers": {
                "cultural_history": "官方由绪记载：青蓮院門跡与天台宗门迹寺院和皇室关系有关。"
            },
            "official_history_sources": [
                {
                    "title": "青蓮院門跡 公式由緒",
                    "url": "https://www.shorenin.com/history/",
                    "snippet": "公式由緒",
                }
            ],
            "evidence_cards": [
                EvidenceCard(
                    source_type="official_history",
                    title="青蓮院門跡 公式由緒",
                    snippet="官方由绪记载：青蓮院門跡与天台宗门迹寺院和皇室关系有关。",
                    url="https://www.shorenin.com/history/",
                    score=0.86,
                )
            ],
        }


class FakeComposer:
    async def compose(
        self,
        request,
        intent,
        candidates,
        ranked,
        evidence_by_place_id,
        visual_reasoning=None,
        narrative_result=None,
    ):
        place = ranked[0].place if ranked else candidates[0]
        return VisualExploreResponse(
            session_id="snap_123",
            what_it_is=f"{place.name_ja or place.name} 的候选识别结果",
            why_it_matters="这里适合安静庭院和历史兴趣。",
            why_popular_or_overhyped="不是典型刷屏点，热度来自小众推荐。",
            related_places=[],
            shoot_hint=ShootHint(
                best_time="16:30",
                stand_where="庭院入口外侧",
                face_where="朝东南",
                how_to_shoot="压低机位拍庭院层次",
                camera_hint="24-35mm",
            ),
            evidence_cards=evidence_by_place_id.get(place.place_id, []),
            confidence=place.confidence,
            needs_user_confirmation=False,
            story_title=(narrative_result or {}).get("story_title", "视觉线索故事"),
            narrative=(narrative_result or {}).get(
                "narrative", "根据可见线索给出谨慎解释。"
            ),
            visible_clues=(visual_reasoning or {}).get("visible_clues", []),
            cultural_hypotheses=(visual_reasoning or {}).get(
                "cultural_hypotheses", []
            ),
            meaning_layers=(narrative_result or {}).get("meaning_layers", {}),
            confidence_notes=(narrative_result or {}).get("confidence_notes", []),
        )


def make_agent(cache=None, vlm=None, narrative=None, history_enricher=None):
    return VisualExploreAgent(
        AgentDependencies(
            cache=cache or FakeCache(),
            vlm=vlm or FakeVlm(),
            place_resolver=FakePlaceResolver(),
            evidence_store=FakeEvidenceStore(),
            composer=FakeComposer(),
            narrative_client=narrative or FakeNarrative(),
            official_history_enricher=history_enricher,
        )
    )


@pytest.mark.asyncio
async def test_text_heavy_menu_still_runs_vlm_for_meaning_exploration():
    cache = FakeCache()
    vlm = FakeVlm()
    narrative = FakeNarrative()
    agent = make_agent(cache=cache, vlm=vlm, narrative=narrative)
    request = VisualExploreInput(
        image_sha256="menu-hash",
        image_bytes=b"fake-image",
        gps_lat=33.5902,
        gps_lng=130.4017,
        client_ocr=ClientOcr(
            text="抹茶パフェ 900円\n親子丼 1200円\n営業時間 11:00-20:00",
            translated_text="Matcha parfait 900 yen\nOyakodon 1200 yen\nHours 11:00-20:00",
            language="ja",
        ),
        interest_tags=["food"],
    )

    response = await agent.explore(request)

    assert vlm.calls == 1
    assert narrative.calls == 1
    assert response.story_title == "静かな門が教えてくれること"
    assert response.visible_clues[0].clue == "painted wooden gate"
    assert response.needs_user_confirmation is False
    assert cache.saved


@pytest.mark.asyncio
async def test_history_focus_injects_official_history_into_visual_story():
    history = FakeOfficialHistoryEnricher()
    narrative = FakeNarrative()
    agent = make_agent(history_enricher=history, narrative=narrative)

    response = await agent.explore(
        VisualExploreInput(
            image_sha256="shorenin-history",
            image_bytes=b"fake-image",
            user_context_text="青蓮院門跡",
            exploration_focus="history",
            interest_tags=["history"],
        )
    )

    assert len(history.calls) == 1
    assert "官方由绪" in narrative.last_visual_reasoning["meaning_layers"]["cultural_history"]
    assert any(card.source_type == "official_history" for card in response.evidence_cards)
    assert "官方由绪" in response.meaning_layers["cultural_history"]
    history_sections = [
        section
        for card in response.deep_cards
        for section in card.sections
        if section.title == "历史视角"
    ]
    assert history_sections
    assert "官方由绪" in history_sections[0].body


@pytest.mark.asyncio
async def test_history_followup_uses_official_history_when_available():
    history = FakeOfficialHistoryEnricher()
    agent = make_agent(history_enricher=history, narrative=ComposeOnlyNarrative())

    response = await agent.followup(
        VisualFollowupInput(
            session_id="snap_shorenin",
            question="它的起源是什么？由谁创建的？",
            image_bytes=b"fake-image",
            previous_result={
                "what_it_is": "青蓮院門跡",
                "one_line_answer": "这是一处京都寺院线索。",
            },
            user_context_text="想看历史视角",
            exploration_focus="history",
            interest_tags=["history"],
        )
    )

    assert len(history.calls) == 1
    assert "官方由绪" in response.answer
    assert response.evidence_cards[0].source_type == "official_history"


@pytest.mark.asyncio
async def test_cache_hit_returns_saved_response_without_vlm_call():
    cached = VisualExploreResponse(
        session_id="cached",
        what_it_is="缓存结果",
        why_it_matters="之前已经分析过。",
        why_popular_or_overhyped="缓存。",
        related_places=[],
        shoot_hint=ShootHint(
            best_time="now",
            stand_where="same spot",
            face_where="same direction",
            how_to_shoot="reuse",
        ),
        evidence_cards=[],
        confidence=0.99,
        needs_user_confirmation=False,
    )
    cache = FakeCache()
    vlm = FakeVlm()
    agent = make_agent(cache=cache, vlm=vlm)
    request = VisualExploreInput(
        image_sha256="abc",
        gps_lat=35.0,
        gps_lng=135.0,
        client_ocr=ClientOcr(text=""),
    )
    cache.items[agent._cache_key(request)] = cached

    response = await agent.explore(request)

    assert response.session_id == cached.session_id
    assert response.what_it_is == cached.what_it_is
    assert response.why_it_matters == cached.why_it_matters
    assert response.cache.hit is True
    assert response.cache.provider == "redis"
    assert response.thinking_steps
    assert vlm.calls == 0


@pytest.mark.asyncio
async def test_cache_key_changes_when_ocr_text_changes():
    cache = FakeCache()
    vlm = FakeVlm()
    agent = make_agent(cache=cache, vlm=vlm)

    base_request = VisualExploreInput(
        image_sha256="same-image",
        gps_lat=35.0,
        gps_lng=135.0,
        client_ocr=ClientOcr(text=""),
    )
    ocr_request = VisualExploreInput(
        image_sha256="same-image",
        gps_lat=35.0,
        gps_lng=135.0,
        client_ocr=ClientOcr(text="青蓮院"),
    )

    first_response = await agent.explore(base_request)
    second_response = await agent.explore(ocr_request)

    assert first_response is not second_response
    assert vlm.calls == 2
    assert len({key for key, _ in cache.saved}) == 2


@pytest.mark.asyncio
async def test_cache_key_changes_when_user_context_changes():
    cache = FakeCache()
    vlm = FakeVlm()
    agent = make_agent(cache=cache, vlm=vlm)

    base_request = VisualExploreInput(
        image_sha256="same-image",
        user_context_text="位于中国西南山区",
        exploration_focus="style",
    )
    other_context_request = VisualExploreInput(
        image_sha256="same-image",
        user_context_text="位于京都东山",
        exploration_focus="style",
    )

    await agent.explore(base_request)
    await agent.explore(other_context_request)

    assert vlm.calls == 2
    assert len({key for key, _ in cache.saved}) == 2


@pytest.mark.asyncio
async def test_narrative_failure_returns_visual_reasoning_fallback():
    agent = make_agent(narrative=FailingNarrative())

    response = await agent.explore(
        VisualExploreInput(
            image_sha256="temple-hash",
            image_bytes=b"fake-image",
            user_context_text="位于京都东山",
            exploration_focus="place",
        )
    )

    assert response.narrative
    assert response.visible_clues[0].clue == "painted wooden gate"
    assert response.confidence_notes


@pytest.mark.asyncio
async def test_place_photo_runs_vlm_and_returns_grounded_evidence():
    vlm = FakeVlm()
    agent = make_agent(vlm=vlm)

    response = await agent.explore(
        VisualExploreInput(
            image_sha256="temple-hash",
            image_bytes=b"fake-image",
            gps_lat=35.007,
            gps_lng=135.782,
            heading_degrees=120.0,
            client_ocr=ClientOcr(text="青蓮院"),
            interest_tags=["quiet", "garden"],
        )
    )

    assert vlm.calls == 1
    assert "青蓮院門跡" in response.what_it_is
    assert response.evidence_cards[0].source_type == "official"
    assert response.shoot_hint.best_time == "16:30"

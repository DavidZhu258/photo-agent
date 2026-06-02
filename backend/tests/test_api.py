from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas.visual import (
    CulturalHypothesis,
    EvidenceCard,
    ShootHint,
    VisibleClue,
    VisualExploreResponse,
    VisualFollowupResponse,
)


class FakeAgent:
    async def explore(self, request):
        assert request.image_bytes == b"fake-photo"
        assert request.images_bytes == [b"fake-photo"]
        assert request.gps_lat == 35.0
        assert request.client_ocr.text == "青蓮院"
        return VisualExploreResponse(
            session_id="snap_api",
            what_it_is="青蓮院門跡",
            why_it_matters="静かな庭園と歴史がある。",
            why_popular_or_overhyped="小众但稳定好评。",
            related_places=[],
            shoot_hint=ShootHint(
                best_time="16:30",
                stand_where="入口右侧",
                face_where="朝东南",
                how_to_shoot="广角低机位",
            ),
            evidence_cards=[
                EvidenceCard(
                    source_type="official",
                    title="Official",
                    snippet="History source",
                    score=0.9,
                )
            ],
            confidence=0.87,
            needs_user_confirmation=False,
        )


class FakeMeaningAgent:
    async def explore(self, request):
        assert request.image_bytes == b"angle-one"
        assert request.images_bytes == [b"angle-one", b"angle-two"]
        assert request.user_context_text == "位于中国西南山区"
        assert request.exploration_focus == "style"
        return VisualExploreResponse(
            session_id="snap_story",
            what_it_is="一处可能带有山地木构传统的建筑细部",
            why_it_matters="它的价值在于材料、地形和日常使用痕迹共同构成地方记忆。",
            why_popular_or_overhyped="当前证据不足以判断热度，不能硬说它是网红点。",
            related_places=[],
            shoot_hint=ShootHint(
                best_time="柔和侧光时",
                stand_where="站在能同时拍到屋檐和地形的位置",
                face_where="朝向木构细节",
                how_to_shoot="保留环境线索，而不是只拍局部",
            ),
            evidence_cards=[],
            confidence=0.52,
            needs_user_confirmation=True,
            story_title="木头、山雾和旧路之间的线索",
            narrative="这张照片真正有趣的地方，不是它像什么，而是它透露出怎样的生活方式。",
            visible_clues=[
                VisibleClue(
                    clue="深色木材与潮湿环境痕迹",
                    interpretation="可能长期处在山地湿润气候中",
                    confidence=0.66,
                )
            ],
            cultural_hypotheses=[
                CulturalHypothesis(
                    name="西南山地木构民居",
                    entity_type="place_style",
                    region="中国西南",
                    rationale="材料和地形线索相互吻合",
                    confidence=0.52,
                    evidence_support=["木材、坡地、潮湿痕迹"],
                    evidence_against=["缺少招牌或明确地标"],
                )
            ],
            meaning_layers={
                "visual": "木构和山地环境形成第一层印象",
                "cultural_history": "可能与地方居住和手工建造传统有关",
                "emotional": "亲近感来自可见的使用痕迹",
                "practical": "需要更多角度确认地点",
            },
            known_comparisons=["西南吊脚楼或山地木屋的局部特征"],
            confidence_notes=["没有明确文字或地标，结论应保持开放"],
            followup_questions=["这张照片附近是否有村寨、溪流或牌匾？"],
        )


class FakeLandmarkAgent:
    async def explore(self, request):
        assert request.image_bytes == b"eiffel-photo"
        assert request.images_bytes == [b"eiffel-photo"]
        assert request.user_context_text == ""
        assert request.exploration_focus == "auto"
        return VisualExploreResponse(
            session_id="snap_eiffel",
            what_it_is="Eiffel Tower",
            why_it_matters="它是巴黎、现代铁构工程和旅行想象的共同符号。",
            why_popular_or_overhyped="非常热门，但作为城市地标仍有明确文化价值。",
            related_places=[],
            shoot_hint=ShootHint(
                best_time="日落前后",
                stand_where="塞纳河对岸或特罗卡德罗广场",
                face_where="朝向塔身轮廓",
                how_to_shoot="保留城市尺度和人物前景",
            ),
            evidence_cards=[],
            confidence=0.88,
            needs_user_confirmation=False,
            story_title="铁塔把城市的天际线变成了记忆",
            narrative="这张照片可以联想到埃菲尔铁塔，它不只是一个观景点，也是工业时代和巴黎形象的叠加。",
            visible_clues=[
                VisibleClue(
                    clue="高耸铁构塔身",
                    interpretation="与巴黎埃菲尔铁塔的开放式钢铁桁架高度吻合",
                    confidence=0.86,
                )
            ],
            cultural_hypotheses=[
                CulturalHypothesis(
                    name="Eiffel Tower",
                    entity_type="landmark",
                    region="Paris, France",
                    rationale="塔身轮廓、钢铁结构和城市地标形象相互吻合",
                    confidence=0.86,
                    evidence_support=["开放式铁构", "塔形轮廓"],
                    evidence_against=["单张图仍需排除复制品或模型"],
                )
            ],
            meaning_layers={
                "visual": "铁构、塔形和尺度形成第一层识别线索",
                "cultural_history": "它关联巴黎、世界博览会和现代工程美学",
                "emotional": "它常被当作抵达巴黎的视觉确认",
                "practical": "可以继续查看附近观景点和拍摄角度",
            },
            confidence_notes=["单张图片识别为高置信，但仍建议用地图或来源确认"],
            followup_questions=["附近哪里适合拍铁塔全景？"],
        )


class FakeFollowupAgent(FakeLandmarkAgent):
    async def followup(self, request):
        assert request.session_id == "snap_eiffel"
        assert request.question == "附近哪里适合拍铁塔全景？"
        assert request.image_bytes == b"eiffel-photo"
        assert request.images_bytes == [b"eiffel-photo"]
        assert request.user_context_text == "第一次到巴黎"
        assert request.exploration_focus == "place"
        assert request.interest_tags == ["history", "viewpoint"]
        assert request.previous_result["what_it_is"] == "Eiffel Tower"
        return VisualFollowupResponse(
            session_id=request.session_id,
            answer="可以优先去特罗卡德罗广场或塞纳河对岸，那里更适合把铁塔和城市层次一起拍进去。",
            evidence_cards=[
                EvidenceCard(
                    source_type="visual_memory",
                    title="Eiffel Tower",
                    snippet="上一轮图片识别为埃菲尔铁塔。",
                    score=0.8,
                )
            ],
            followup_questions=["它适合日落拍还是夜景拍？"],
        )


def test_visual_explore_api_accepts_base64_image_and_returns_contract():
    app = create_app(agent=FakeAgent())
    client = TestClient(app)

    response = client.post(
        "/v1/visual/explore",
        json={
            "image_base64": "ZmFrZS1waG90bw==",
            "gps_lat": 35.0,
            "gps_lng": 135.0,
            "heading_degrees": 120.0,
            "client_ocr_text": "青蓮院",
            "client_ocr_language": "ja",
            "interest_tags": ["quiet", "garden"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "snap_api"
    assert body["what_it_is"] == "青蓮院門跡"
    assert body["shoot_hint"]["stand_where"] == "入口右侧"
    assert body["evidence_cards"][0]["source_type"] == "official"


def test_visual_explore_api_accepts_multi_image_context_and_returns_story_fields():
    app = create_app(agent=FakeMeaningAgent())
    client = TestClient(app)

    response = client.post(
        "/v1/visual/explore",
        json={
            "images_base64": ["YW5nbGUtb25l", "YW5nbGUtdHdv"],
            "gps_lat": 26.1,
            "gps_lng": 102.2,
            "user_context_text": "位于中国西南山区",
            "exploration_focus": "style",
            "interest_tags": ["architecture", "local craft"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "snap_story"
    assert body["story_title"] == "木头、山雾和旧路之间的线索"
    assert body["visible_clues"][0]["clue"] == "深色木材与潮湿环境痕迹"
    assert body["cultural_hypotheses"][0]["evidence_against"] == [
        "缺少招牌或明确地标"
    ]
    assert body["meaning_layers"]["emotional"] == "亲近感来自可见的使用痕迹"
    assert body["confidence_notes"] == ["没有明确文字或地标，结论应保持开放"]


def test_visual_discover_api_is_chance_style_entrypoint_with_open_source_metadata():
    app = create_app(agent=FakeMeaningAgent())
    client = TestClient(app)

    response = client.post(
        "/v1/visual/discover",
        json={
            "images_base64": ["YW5nbGUtb25l", "YW5nbGUtdHdv"],
            "gps_lat": 26.1,
            "gps_lng": 102.2,
            "user_context_text": "位于中国西南山区",
            "exploration_focus": "style",
            "interest_tags": ["architecture", "local craft"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["story_title"] == "木头、山雾和旧路之间的线索"
    assert body["narrative"].startswith("这张照片真正有趣的地方")
    assert body["visible_clues"][0]["interpretation"] == "可能长期处在山地湿润气候中"
    assert body["cultural_hypotheses"][0]["entity_type"] == "place_style"
    assert body["knowledge_cards"][0]["source_type"] == "exa"
    assert body["api_sources_used"][0]["provider"] == "serpapi_google_lens"
    assert body["thinking_steps"][0]["framework"] == "haystack"


def test_visual_discover_api_accepts_single_image_without_prompt():
    app = create_app(agent=FakeLandmarkAgent())
    client = TestClient(app)

    response = client.post(
        "/v1/visual/discover",
        json={
            "image_base64": "ZWlmZmVsLXBob3Rv",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["what_it_is"] == "Eiffel Tower"
    assert body["story_title"] == "铁塔把城市的天际线变成了记忆"
    assert body["visible_clues"][0]["clue"] == "高耸铁构塔身"
    assert body["cultural_hypotheses"][0]["entity_type"] == "landmark"
    assert body["needs_user_confirmation"] is False


def test_visual_discover_get_returns_helpful_web_ui_pointer_instead_of_not_found():
    app = create_app(agent=FakeLandmarkAgent())
    client = TestClient(app)

    response = client.get("/v1/visual/discover")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["method"] == "POST"
    assert body["web_ui"].endswith("/visual")


def test_visual_followup_api_uses_same_image_session_and_context():
    app = create_app(agent=FakeFollowupAgent())
    client = TestClient(app)

    response = client.post(
        "/v1/visual/followup",
        json={
            "session_id": "snap_eiffel",
            "question": "附近哪里适合拍铁塔全景？",
            "image_base64": "ZWlmZmVsLXBob3Rv",
            "user_context_text": "第一次到巴黎",
            "exploration_focus": "place",
            "interest_tags": ["history", "viewpoint"],
            "previous_result": {"what_it_is": "Eiffel Tower"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "snap_eiffel"
    assert "特罗卡德罗" in body["answer"]
    assert body["evidence_cards"][0]["source_type"] == "visual_memory"
    assert body["followup_questions"] == ["它适合日落拍还是夜景拍？"]

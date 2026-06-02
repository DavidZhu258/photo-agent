from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chainlit_app.renderer import (  # noqa: E402
    apply_trip_card_action,
    apply_trip_header_update,
    build_travel_payload,
    merge_travel_context,
    markdown_from_response,
    missing_core_fields,
    response_message_sequence,
    step_summaries,
    trip_board_props,
    trip_header_props,
)


def test_build_travel_payload_extracts_common_trip_fields_from_chinese_text():
    payload = build_travel_payload(
        "我从东京出发，2026-06-10 到 2026-06-12 去福冈，2个人，中等预算，女生 solo 也想看安全和天气"
    )

    assert payload["origin_city"] == "Tokyo"
    assert payload["city"] == "Fukuoka"
    assert payload["date_range"] == ["2026-06-10", "2026-06-12"]
    assert payload["travelers"] == 2
    assert payload["budget"] == "中等预算"
    assert payload["allow_web_search"] is True
    assert "女生 solo" in payload["query"]


def test_chainlit_payload_requires_only_destination_and_can_inherit_context():
    missing_destination = build_travel_payload("帮我安排三天两晚")
    assert missing_core_fields(missing_destination) == ["目的地"]

    destination_only = build_travel_payload("去福冈，偏美食和摄影")
    assert destination_only["city"] == "Fukuoka"
    assert destination_only["origin_city"] is None
    assert destination_only["date_range"] == []
    assert missing_core_fields(destination_only) == []

    followup = build_travel_payload(
        "第二天下雨的话怎么调整？",
        previous_payload=destination_only,
    )
    assert followup["city"] == "Fukuoka"
    assert followup["origin_city"] is None
    assert followup["date_range"] == []
    assert "第二天下雨" in followup["query"]


def test_chainlit_context_keeps_previous_fields_and_detects_requested_categories():
    context = merge_travel_context(
        {},
        build_travel_payload("去福冈，2个人，中等预算，偏美食和摄影"),
        last_response={
            "summary": "福冈适合低压力美食和摄影。",
            "category_groups": [
                {"title": "美食", "items": ["屋台", "拉面"]},
                {"title": "自然与摄影", "items": ["大濠公园"]},
            ],
            "not_recommended": [{"place": {"name": "太赶的别府往返"}}],
        },
    )

    next_payload = build_travel_payload("只推荐美食，预算1000", previous_payload=context)

    assert next_payload["city"] == "Fukuoka"
    assert next_payload["budget"] == "1000"
    assert next_payload["travelers"] == 2
    assert next_payload["requested_categories"] == ["美食"]
    assert next_payload["previous_context"]["last_summary"] == "福冈适合低压力美食和摄影。"
    assert "屋台" in next_payload["previous_context"]["last_recommended_items"]
    assert "太赶的别府往返" in next_payload["previous_context"]["last_not_recommended"]


def test_payload_uses_chat_settings_and_scopes_plain_food_query():
    payload = build_travel_payload(
        "有什么好吃的？",
        previous_payload={},
        chat_settings={
            "Where": "Fukuoka",
            "When": "2026-06-10 到 2026-06-12",
            "Who": "2",
            "Budget": "1000人民币",
            "Preferences": ["屋台", "拉面"],
            "Avoid": ["排队"],
        },
    )

    assert payload["city"] == "Fukuoka"
    assert payload["date_range"] == ["2026-06-10", "2026-06-12"]
    assert payload["travelers"] == 2
    assert payload["budget"] == "1000人民币"
    assert payload["requested_categories"] == ["美食"]
    assert payload["interest_tags"] == ["屋台", "拉面"]
    assert payload["avoid"] == ["排队"]


def test_plain_japanese_food_query_keeps_food_scope_and_interest_hint():
    payload = build_travel_payload("福冈有什么好吃的日料？")

    assert payload["city"] == "Fukuoka"
    assert payload["requested_categories"] == ["美食"]
    assert "日料" in payload["interest_tags"]


def test_plain_things_to_do_query_scopes_to_local_experiences_not_food():
    payload = build_travel_payload("福冈有什么好玩的？")

    assert payload["city"] == "Fukuoka"
    assert payload["requested_categories"] == ["本地体验"]
    assert "好玩" in payload["interest_tags"]


def test_trip_header_default_and_context_updates_feed_next_payload():
    props = trip_header_props({})

    assert props["title"] == "新的旅行推荐"
    assert props["subtitle"] == "Ask anything"
    assert props["trip_count"] == 0
    assert [chip["id"] for chip in props["chips"]] == [
        "Where",
        "When",
        "Who",
        "Budget",
        "Preferences",
        "Avoid",
    ]
    assert all(chip["empty"] for chip in props["chips"])

    context = apply_trip_header_update({}, {"field": "Where", "value": "Fukuoka"})
    context = apply_trip_header_update(context, {"field": "When", "value": "2026-06-10 到 2026-06-12"})
    context = apply_trip_header_update(context, {"field": "Who", "value": "2"})
    context = apply_trip_header_update(context, {"field": "Budget", "value": "1000人民币"})
    context = apply_trip_header_update(context, {"field": "Preferences", "value": "屋台,日料"})

    next_payload = build_travel_payload("有什么好吃的日料？", previous_payload=context)
    assert next_payload["city"] == "Fukuoka"
    assert next_payload["date_range"] == ["2026-06-10", "2026-06-12"]
    assert next_payload["travelers"] == 2
    assert next_payload["budget"] == "1000人民币"
    assert "屋台" in next_payload["interest_tags"]
    assert "日料" in next_payload["interest_tags"]

    updated_props = trip_header_props(context)
    assert updated_props["title"] == "福冈旅行推荐"
    assert updated_props["subtitle"] == "Trip to Fukuoka"
    assert updated_props["chips"][0]["label"] == "Fukuoka"
    assert updated_props["chips"][1]["label"] == "2026-06-10 - 2026-06-12"


def test_trip_card_action_updates_local_trip_state_and_header_count():
    context = apply_trip_card_action(
        {"city": "Fukuoka"},
        {
            "action": "add_to_trip",
            "card": {
                "id": "card-1",
                "title": "Gyoza & Ramen Danbo",
                "category": "美食",
                "subcategory": "拉面",
            },
        },
    )

    assert context["trip_items"][0]["title"] == "Gyoza & Ramen Danbo"
    assert trip_header_props(context)["trip_count"] == 1

    context = apply_trip_card_action(
        context,
        {"action": "toggle_like", "card": {"id": "card-1", "title": "Gyoza & Ramen Danbo"}},
    )

    assert context["liked_items"][0]["title"] == "Gyoza & Ramen Danbo"


def test_trip_board_props_preserve_cards_and_map_pins():
    props = trip_board_props(
        {
            "summary": "福冈美食推荐",
            "resolved_intent": {"category": "美食", "subcategory": "local_specialties"},
            "display_cards": [
                {
                    "id": "card-1",
                    "title": "Gyoza & Ramen Danbo",
                    "subcategory": "拉面",
                    "trip_state": "planned",
                    "description": "评分高，适合当宵夜。",
                    "rating": 4.4,
                    "review_count": 1300,
                    "price": "$",
                    "address": "Fukuoka",
                    "image_url": "https://example.com/ramen.jpg",
                    "image_status": "place_photo",
                    "image_urls": [
                        "https://example.com/ramen.jpg",
                        "https://example.com/ramen-2.jpg",
                        "https://example.com/ramen-3.jpg",
                    ],
                    "lat": 33.59,
                    "lng": 130.4,
                    "source_url": "https://example.com/place",
                    "place_id": "ChIJFoodPick1",
                    "photo_attributions": ["Example Photographer"],
                    "google_maps_uri": "https://www.google.com/maps/search/?api=1&query=Gyoza",
                    "directions_uri": "https://www.google.com/maps/dir/?api=1&destination=Gyoza",
                }
            ],
            "map_view": {
                "center": {"lat": 33.59, "lng": 130.4},
                "pins": [
                    {
                        "id": "card-1",
                        "title": "Gyoza & Ramen Danbo",
                        "lat": 33.59,
                        "lng": 130.4,
                        "trip_state": "planned",
                        "place_id": "ChIJFoodPick1",
                    }
                ],
                "selected_pin_id": "card-1",
                "provider": "photo_agent_map",
                "mode": "dedicated_panel",
            },
        },
        runtime_config={
            "google_maps_api_key": "test-google-key",
            "google_maps_map_id": "test-map-id",
        },
    )

    assert props["title"] == "福冈美食推荐"
    assert props["cards"][0]["image_url"] == "https://example.com/ramen.jpg"
    assert props["cards"][0]["image_status"] == "place_photo"
    assert props["cards"][0]["image_urls"] == [
        "https://example.com/ramen.jpg",
        "https://example.com/ramen-2.jpg",
        "https://example.com/ramen-3.jpg",
    ]
    assert props["cards"][0]["rating"] == 4.4
    assert props["cards"][0]["subcategory"] == "拉面"
    assert props["cards"][0]["trip_state"] == "planned"
    assert props["cards"][0]["place_id"] == "ChIJFoodPick1"
    assert props["cards"][0]["photo_attributions"] == ["Example Photographer"]
    assert props["cards"][0]["google_maps_uri"].startswith("https://www.google.com/maps/search/")
    assert props["map"]["pins"][0]["title"] == "Gyoza & Ramen Danbo"
    assert props["map"]["pins"][0]["place_id"] == "ChIJFoodPick1"
    assert props["map"]["selected_pin_id"] == "card-1"
    assert props["map"]["provider"] == "google_maps"
    assert props["map"]["fallback_provider"] == "photo_agent_map"
    assert props["map"]["mode"] == "google_maps_js"
    assert props["map"]["api_key"] == "test-google-key"
    assert props["map"]["map_id"] == "test-map-id"


def test_trip_board_props_marks_missing_google_maps_key_but_keeps_fallback_map():
    props = trip_board_props(
        {
            "summary": "福冈本地体验推荐",
            "display_cards": [
                {
                    "id": "card-1",
                    "title": "Ohori Park",
                    "category": "本地体验",
                    "lat": 33.586,
                    "lng": 130.376,
                }
            ],
            "map_view": {
                "center": {"lat": 33.586, "lng": 130.376},
                "pins": [{"id": "card-1", "title": "Ohori Park", "lat": 33.586, "lng": 130.376}],
                "provider": "photo_agent_map",
                "mode": "dedicated_panel",
            },
        }
    )

    assert props["map"]["provider"] == "google_maps_missing_key"
    assert props["map"]["fallback_provider"] == "photo_agent_map"
    assert props["map"]["mode"] == "fallback_panel"
    assert props["map"]["api_key"] == ""


def test_response_sequence_places_trip_board_before_markdown():
    response = {
        "summary": "福冈本地体验推荐",
        "formatted_markdown": "## 总建议\n先看上面的地图卡片。",
        "display_cards": [
            {
                "id": "card-1",
                "title": "Ohori Park",
                "category": "本地体验",
                "lat": 33.586,
                "lng": 130.376,
            }
        ],
        "map_view": {
            "center": {"lat": 33.586, "lng": 130.376},
            "pins": [{"id": "card-1", "title": "Ohori Park", "lat": 33.586, "lng": 130.376}],
        },
    }

    sequence = response_message_sequence(
        response,
        runtime_config={"google_maps_api_key": "test-google-key"},
    )

    assert [item["type"] for item in sequence] == ["trip_board", "markdown"]
    assert sequence[0]["props"]["cards"][0]["title"] == "Ohori Park"
    assert sequence[0]["props"]["map"]["provider"] == "google_maps"
    assert sequence[0]["props"]["map"]["browser_key"] == "test-google-key"
    assert sequence[0]["props"]["google_maps_key"] == "test-google-key"
    assert sequence[1]["content"].startswith("## 总建议")


def test_markdown_renderer_prefers_formatter_output_and_steps_show_agents():
    response = {
        "formatted_markdown": "## 总建议\n适合，但要注意交通。",
        "suggestion_source": "serper",
        "search_used": True,
        "budget_summary": {"items": [{"title": "Daily budget"}]},
        "transport_summary": {"items": [{"title": "Subway pass"}]},
        "optional_context": {"weather": [{"title": "Rainy season"}]},
        "workflow_summary": {
            "tool_summary": "调用了 4 个工具，保留预算、交通和天气。",
            "sources_used": ["serper:budget", "serper:transport"],
            "candidate_counts": {"tool_count": 4, "total_items": 9, "agent_count": 2},
            "agent_findings": ["Itinerary 负责压缩路线。"],
            "critic_notes": ["雨季属于非阻断风险。"],
            "confidence": "medium",
            "missing_but_non_blocking": ["补充日期会更准。"],
        },
        "raw_provider_refs": {
            "agent_results": {
                "Flight": {"model": "travel-reasoning", "raw_api_count": 3},
                "Critic": {"model": "travel-critic", "raw_api_count": 0},
            }
        },
        "agentic_workflow": [
            {
                "phase": "act",
                "actor": "Supervisor",
                "action": "调用 Serper 工具",
                "tools": ["serper:budget", "serper:transport"],
                "observation": {"total_items": 2},
                "status": "completed",
            },
            {
                "phase": "analyze",
                "actor": "Multi-Agent",
                "action": "并发分析候选",
                "tools": ["Destination", "Itinerary"],
                "observation": {"agent_count": 2},
                "status": "completed",
            },
        ],
    }

    rendered = markdown_from_response(response)
    assert rendered == "## 总建议\n适合，但要注意交通。"
    assert "调用了 4 个工具" not in rendered
    steps = step_summaries(response)
    assert steps[0] == "Workflow summary: tools 4 / candidates 9 / agents 2 / confidence medium"
    assert "Serper: budget 1 / transport 1 / optional weather" in steps
    assert "ReACT act: Supervisor / 调用 Serper 工具 / tools 2" in steps
    assert "ReACT analyze: Multi-Agent / 并发分析候选 / tools 2" in steps
    assert "Flight: travel-reasoning / API候选 3" in steps
    assert "Critic: travel-critic / API候选 0" in steps

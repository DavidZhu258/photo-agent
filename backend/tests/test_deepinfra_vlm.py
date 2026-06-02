import json

import httpx
import pytest

from app.schemas.visual import ClientOcr, VisualExploreInput
from app.services.vlm import DeepInfraVlmClient


@pytest.mark.asyncio
async def test_deepinfra_client_sends_openai_vision_payload_and_parses_json():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "subject": "青蓮院門跡",
                                    "place_candidates": ["青蓮院"],
                                    "confidence": 0.81,
                                }
                            )
                        }
                    }
                ],
                "usage": {"prompt_tokens": 123, "completion_tokens": 45},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = DeepInfraVlmClient(
            api_key="test-token",
            model="mistralai/Mistral-Small-3.2-24B-Instruct-2506",
            http_client=http_client,
        )
        result = await client.identify(
            VisualExploreInput(
                image_bytes=b"fake-jpeg",
                images_bytes=[b"fake-jpeg", b"second-angle"],
                client_ocr=ClientOcr(text="青蓮院"),
                gps_lat=35.007,
                gps_lng=135.782,
                interest_tags=["quiet", "garden"],
                user_context_text="位于京都东山",
                exploration_focus="place",
            )
        )

    assert captured["authorization"] == "Bearer test-token"
    assert captured["payload"]["model"] == "mistralai/Mistral-Small-3.2-24B-Instruct-2506"
    assert captured["payload"]["max_tokens"] == 2400
    content = captured["payload"]["messages"][1]["content"]
    assert content[0]["type"] == "image_url"
    assert content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert content[1]["type"] == "image_url"
    assert "visible_clues" in content[-1]["text"]
    assert "famous landmark" in content[-1]["text"]
    assert "canonical landmark name" in content[-1]["text"]
    assert "Simplified Chinese" in content[-1]["text"]
    assert "位于京都东山" in content[-1]["text"]
    assert "Simplified Chinese" in captured["payload"]["messages"][0]["content"]
    assert result["subject"] == "青蓮院門跡"
    assert result["place_candidates"] == ["青蓮院"]
    assert result["confidence"] == 0.81
    assert result["usage"]["prompt_tokens"] == 123


@pytest.mark.asyncio
async def test_deepinfra_narrative_client_uses_gemma_and_parses_story_json():
    from app.services.vlm import DeepInfraNarrativeClient

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "story_title": "一扇门背后的山路",
                                    "narrative": "它像是一段被保留下来的地方记忆。",
                                    "meaning_layers": {
                                        "visual": "木料和坡地构成视觉线索",
                                        "cultural_history": "可能与山地聚落有关",
                                        "emotional": "亲近感来自日常痕迹",
                                        "practical": "需要更多角度确认",
                                    },
                                    "confidence_notes": ["没有招牌，保持谨慎"],
                                    "followup_questions": ["附近是否有说明牌？"],
                                }
                            )
                        }
                    }
                ],
                "model": "google/gemma-4-26B-A4B-it",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        result = await DeepInfraNarrativeClient(
            api_key="test-token",
            model="google/gemma-4-26B-A4B-it",
            http_client=http_client,
        ).compose(
            VisualExploreInput(
                image_bytes=b"x",
                user_context_text="位于中国西南山区",
                exploration_focus="style",
            ),
            visual_reasoning={
                "subject": "wooden mountain house detail",
                "visible_clues": [
                    {
                        "clue": "dark timber",
                        "interpretation": "humid mountain climate",
                        "confidence": 0.62,
                    }
                ],
            },
            evidence_cards=[],
        )

    assert captured["payload"]["model"] == "google/gemma-4-26B-A4B-it"
    assert "Chance AI" in captured["payload"]["messages"][0]["content"]
    assert "位于中国西南山区" in captured["payload"]["messages"][1]["content"]
    assert result["story_title"] == "一扇门背后的山路"
    assert result["meaning_layers"]["emotional"] == "亲近感来自日常痕迹"
    assert captured["payload"]["max_tokens"] >= 5000


@pytest.mark.asyncio
async def test_deepinfra_narrative_client_does_not_publish_truncated_json_as_copy():
    from app.services.vlm import DeepInfraNarrativeClient

    captured = {}
    truncated_json = (
        '{"story_title":"暮色与飞檐","narrative":"沿着石板路向上，八坂塔突然出现在街巷尽头。",'
        '"one_line_answer":"这是京都东山的八坂塔。","deep_cards":[{"title":"识别","body":"'
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": truncated_json}}],
                "model": "google/gemini-3.1-pro",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        result = await DeepInfraNarrativeClient(
            api_key="test-token",
            model="google/gemini-3.1-pro",
            http_client=http_client,
        ).compose(
            VisualExploreInput(image_bytes=b"x"),
            visual_reasoning={
                "subject": "Hokan-ji Yasaka Pagoda",
                "visible_clues": [
                    {
                        "clue": "five-story pagoda",
                        "interpretation": "五重塔和东山街巷共同指向八坂塔。",
                        "confidence": 0.9,
                    }
                ],
                "meaning_layers": {
                    "visual": "五重塔和坡道形成清晰纵深。",
                    "cultural_history": "法观寺八坂塔是京都东山的重要地标。",
                },
            },
            evidence_cards=[],
        )

    assert captured["payload"]["max_tokens"] >= 5000
    public_text = " ".join(
        [
            result["narrative"],
            result["one_line_answer"],
            *[
                " ".join(
                    [
                        str(card.get("title", "")),
                        str(card.get("body", "")),
                        " ".join(str(item) for item in card.get("supporting_points", [])),
                    ]
                )
                for card in result["deep_cards"]
                if isinstance(card, dict)
            ],
        ]
    )
    assert "story_title" not in public_text
    assert "deep_cards" not in public_text
    assert truncated_json not in public_text
    assert result["deep_cards"][1]["title"] == "看点"


@pytest.mark.asyncio
async def test_deepinfra_narrative_client_normalizes_section_dicts_from_gateway():
    from app.services.vlm import DeepInfraNarrativeClient

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "story_title": "京都东山的五重塔",
                                    "narrative": "八坂塔把坡道、町屋和古都天际线连在一起。",
                                    "one_line_answer": "这是京都东山区的法观寺八坂塔。",
                                    "deep_cards": [
                                        {
                                            "title": "识别",
                                            "body": "画面主体是法观寺五重塔。",
                                            "sections": {
                                                "主体": "法观寺八坂塔",
                                                "地点": "京都东山区八坂通",
                                            },
                                        },
                                        {
                                            "title": "看点",
                                            "body": "它浓缩了东山街区的古都风貌。",
                                            "sections": {
                                                "导游视角": "沿坡道抬头即可看到塔身。",
                                                "历史视角": "五重塔承接法观寺的寺院记忆。",
                                                "文化视角": ["町屋街巷", "和服游客", "清水寺动线"],
                                            },
                                        },
                                        {
                                            "title": "线索",
                                            "body": "坡道、木造町屋和塔顶相轮共同指向京都东山。",
                                            "sections": {
                                                "画面细节": {
                                                    "body": "五层塔身位于街巷尽头。",
                                                    "bullets": ["深色木构", "石板坡道"],
                                                }
                                            },
                                        },
                                    ],
                                }
                            )
                        }
                    }
                ],
                "model": "gpt-5.5",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        result = await DeepInfraNarrativeClient(
            api_key="test-token",
            model="gpt-5.5",
            http_client=http_client,
        ).compose(
            VisualExploreInput(image_bytes=b"x"),
            visual_reasoning={"subject": "Hokan-ji Yasaka Pagoda"},
            evidence_cards=[],
        )

    cards = result["deep_cards"]
    assert cards[0]["sections"] == [
        {"title": "主体", "body": "法观寺八坂塔", "bullets": [], "chips": []},
        {"title": "地点", "body": "京都东山区八坂通", "bullets": [], "chips": []},
    ]
    assert cards[1]["sections"][2] == {
        "title": "文化视角",
        "body": "",
        "bullets": ["町屋街巷", "和服游客", "清水寺动线"],
        "chips": [],
    }
    assert cards[2]["sections"][0] == {
        "title": "画面细节",
        "body": "五层塔身位于街巷尽头。",
        "bullets": ["深色木构", "石板坡道"],
        "chips": [],
    }


@pytest.mark.asyncio
async def test_deepinfra_narrative_client_normalizes_multimodal_blocks_tables_and_images():
    from app.services.vlm import DeepInfraNarrativeClient

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": [
                                {
                                    "type": "text",
                                    "text": json.dumps(
                                        {
                                            "story_title": "塔与街巷",
                                            "narrative": "八坂塔把传统街巷组织成一条视觉轴线。",
                                            "one_line_answer": "这是京都东山的八坂塔。",
                                            "deep_cards": [
                                                {
                                                    "title": "识别",
                                                    "body": "主体是五重塔。",
                                                    "sections": [
                                                        {
                                                            "title": "主体身份",
                                                            "body": "法观寺八坂塔。",
                                                            "images": [
                                                                {
                                                                    "url": "https://example.com/yasaka-detail.jpg",
                                                                    "caption": "塔身细节",
                                                                }
                                                            ],
                                                        }
                                                    ],
                                                },
                                                {
                                                    "title": "看点",
                                                    "body": "它值得从多个视角看。",
                                                    "sections": [
                                                        {
                                                            "title": "视角对比",
                                                            "body": (
                                                                "| 视角 | 看什么 |\n"
                                                                "| --- | --- |\n"
                                                                "| 导游 | 坡道尽头的地标 |\n"
                                                                "| 风格 | 木构塔身和町屋 |\n"
                                                            ),
                                                        }
                                                    ],
                                                },
                                                {
                                                    "title": "线索",
                                                    "body": "石板坡道与五层塔身相互印证。",
                                                    "sections": [
                                                        {
                                                            "title": "线索表",
                                                            "body": "可见细节如下。",
                                                            "table": {
                                                                "columns": ["线索", "解释"],
                                                                "rows": [
                                                                    ["五层塔", "佛塔形制"],
                                                                    ["町屋", "京都东山街区"],
                                                                ],
                                                            },
                                                        }
                                                    ],
                                                },
                                            ],
                                        }
                                    ),
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "https://example.com/generated-context.png"},
                                },
                            ]
                        }
                    }
                ],
                "model": "gpt-5.5",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        result = await DeepInfraNarrativeClient(
            api_key="test-token",
            model="gpt-5.5",
            http_client=http_client,
        ).compose(
            VisualExploreInput(image_bytes=b"x"),
            visual_reasoning={"subject": "Hokan-ji Yasaka Pagoda"},
            evidence_cards=[],
        )

    cards = result["deep_cards"]
    assert cards[0]["sections"][0]["images"] == [
        {
            "url": "https://example.com/yasaka-detail.jpg",
            "caption": "塔身细节",
            "source": "",
        }
    ]
    assert cards[1]["sections"][0]["body"] == ""
    assert cards[1]["sections"][0]["tables"] == [
        {
            "caption": "",
            "columns": ["视角", "看什么"],
            "rows": [["导游", "坡道尽头的地标"], ["风格", "木构塔身和町屋"]],
        }
    ]
    assert cards[2]["sections"][0]["tables"][0]["columns"] == ["线索", "解释"]
    assert cards[0]["sections"][1]["title"] == "补充图像"
    assert cards[0]["sections"][1]["images"][0]["url"] == "https://example.com/generated-context.png"


@pytest.mark.asyncio
async def test_deepinfra_client_extracts_json_from_markdown_fence():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "```json\n{\"subject\":\"temple\",\"place_candidates\":[\"清水寺\"],\"confidence\":0.7}\n```"
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        result = await DeepInfraVlmClient(
            api_key="test-token",
            model="mistralai/Mistral-Small-3.2-24B-Instruct-2506",
            http_client=http_client,
        ).identify(VisualExploreInput(image_bytes=b"x", client_ocr=ClientOcr(text="")))

    assert result["subject"] == "temple"
    assert result["place_candidates"] == ["清水寺"]
    assert result["confidence"] == 0.7


@pytest.mark.asyncio
async def test_deepinfra_client_extracts_nested_json_from_markdown_fence():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": (
                                "```json\n"
                                "{\n"
                                '  "subject": "Sydney Opera House",\n'
                                '  "place_candidates": ["Sydney Harbour"],\n'
                                '  "confidence": 1.0,\n'
                                '  "visible_clues": [{"clue": "sails", "interpretation": "opera house", "confidence": 0.9}],\n'
                                '  "meaning_layers": {"visual": "harbor landmark"}\n'
                                "}\n"
                                "```"
                            )
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        result = await DeepInfraVlmClient(
            api_key="test-token",
            model="google/gemini-3.1-pro",
            http_client=http_client,
        ).identify(VisualExploreInput(image_bytes=b"x", client_ocr=ClientOcr(text="")))

    assert result["subject"] == "Sydney Opera House"
    assert result["confidence"] == 1.0
    assert result["visible_clues"][0]["clue"] == "sails"
    assert result["meaning_layers"]["visual"] == "harbor landmark"


@pytest.mark.asyncio
async def test_deepinfra_client_uses_png_data_url_for_png_bytes():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "{\"subject\":\"blank\",\"confidence\":0.4}"}}
                ]
            },
        )

    png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake"
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        await DeepInfraVlmClient(
            api_key="test-token",
            model="mistralai/Mistral-Small-3.2-24B-Instruct-2506",
            http_client=http_client,
        ).identify(VisualExploreInput(image_bytes=png_bytes, client_ocr=ClientOcr(text="")))

    image_url = captured["payload"]["messages"][1]["content"][0]["image_url"]["url"]
    assert image_url.startswith("data:image/png;base64,")


@pytest.mark.asyncio
async def test_deepinfra_client_normalizes_percent_confidence_strings():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "subject": "Sydney Opera House",
                                    "place_candidates": ["Sydney Opera House"],
                                    "confidence": "95%",
                                }
                            )
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        result = await DeepInfraVlmClient(
            api_key="test-token",
            model="google/gemini-3.1-pro",
            http_client=http_client,
        ).identify(VisualExploreInput(image_bytes=b"x", client_ocr=ClientOcr(text="")))

    assert result["confidence"] == 0.95


@pytest.mark.asyncio
async def test_deepinfra_client_normalizes_hypothesis_string_evidence_fields():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "subject": "Eiffel Tower",
                                    "place_candidates": ["Paris, France"],
                                    "confidence": 1.0,
                                    "cultural_hypotheses": [
                                        {
                                            "name": "Eiffel Tower",
                                            "entity_type": "landmark",
                                            "region": "Paris, France",
                                            "rationale": "iron lattice tower",
                                            "confidence": 1.0,
                                            "evidence_support": "Exact match of the iron lattice tower.",
                                            "evidence_against": "None.",
                                        }
                                    ],
                                }
                            )
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        result = await DeepInfraVlmClient(
            api_key="test-token",
            model="google/gemini-3.1-pro",
            http_client=http_client,
        ).identify(VisualExploreInput(image_bytes=b"x", client_ocr=ClientOcr(text="")))

    hypothesis = result["cultural_hypotheses"][0]
    assert hypothesis["evidence_support"] == ["Exact match of the iron lattice tower."]
    assert hypothesis["evidence_against"] == ["None."]

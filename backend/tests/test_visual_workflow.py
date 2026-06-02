import pytest

from app.schemas.visual import ShootHint, VisualExploreInput, VisualExploreResponse
from app.services.visual_workflow import enrich_visual_response


@pytest.mark.asyncio
async def test_visual_workflow_adds_perspectives_memory_audio_and_summary():
    base = VisualExploreResponse(
        session_id="snap_kushida",
        what_it_is="Kushida Shrine",
        why_it_matters="博多文化的重要神社。",
        why_popular_or_overhyped="不是单纯打卡点，价值在祭礼和社区记忆。",
        related_places=[],
        shoot_hint=ShootHint(
            best_time="morning",
            stand_where="front gate",
            face_where="toward shrine",
            how_to_shoot="include lanterns",
        ),
        evidence_cards=[],
        confidence=0.84,
        needs_user_confirmation=False,
        story_title="博多街区里的一座精神坐标",
        narrative="这张照片指向 Kushida Shrine，它和博多的祭礼记忆连在一起。",
        visible_clues=[],
        cultural_hypotheses=[],
    )
    visual_reasoning = {
        "subject": "Kushida Shrine",
        "confidence": 0.84,
        "visible_clues": [
            {
                "clue": "shrine gate and lanterns",
                "interpretation": "Hakata shrine architecture",
                "confidence": 0.78,
            }
        ],
        "cultural_hypotheses": [
            {
                "name": "Kushida Shrine",
                "entity_type": "landmark",
                "region": "Fukuoka, Japan",
                "rationale": "visible shrine features match Hakata context",
                "confidence": 0.82,
                "evidence_support": ["gate", "lanterns"],
                "evidence_against": ["single angle only"],
            }
        ],
        "meaning_layers": {
            "visual": "lanterns and shrine gate",
            "cultural_history": "Hakata festival culture",
        },
        "confidence_notes": ["needs map confirmation"],
        "suggested_perspectives": ["guide", "history", "culture"],
        "provider": "gemini",
        "model": "gemini-3.1-pro-preview",
    }

    enriched = enrich_visual_response(
        base,
        VisualExploreInput(image_sha256="kushida-hash", image_bytes=b"fake"),
        visual_reasoning=visual_reasoning,
        model_used="gemini-3.1-pro-preview",
    )

    assert [card.perspective for card in enriched.perspective_cards] == [
        "guide",
        "history",
        "culture",
    ]
    assert enriched.perspective_cards[0].summary
    assert enriched.visual_memory_item is not None
    assert enriched.visual_memory_item.memory_id == "visual_kushida-hash"
    assert enriched.visual_memory_item.title == "Kushida Shrine"
    assert enriched.visual_memory_item.region_hint == "Fukuoka, Japan"
    assert enriched.audio_script.startswith("博多街区里的一座精神坐标")
    assert enriched.visual_workflow_summary.provider == "gemini"
    assert enriched.visual_workflow_summary.selected_perspectives == [
        "guide",
        "history",
        "culture",
    ]
    assert enriched.visual_workflow_summary.uncertainty == ["needs map confirmation"]


@pytest.mark.asyncio
async def test_visual_workflow_uses_safe_default_perspectives_for_weak_reasoning():
    base = VisualExploreResponse(
        session_id="snap_unknown",
        what_it_is="unknown visual subject",
        why_it_matters="需要更多线索。",
        why_popular_or_overhyped="热度未知。",
        related_places=[],
        shoot_hint=ShootHint(
            best_time="soft light",
            stand_where="same spot",
            face_where="subject",
            how_to_shoot="add context",
        ),
        evidence_cards=[],
        confidence=0.3,
        needs_user_confirmation=True,
    )

    enriched = enrich_visual_response(
        base,
        VisualExploreInput(image_bytes=b"fake"),
        visual_reasoning={"subject": "unknown visual subject", "confidence": 0.3},
        model_used="heuristic",
    )

    assert len(enriched.perspective_cards) >= 2
    assert enriched.visual_memory_item is not None
    assert enriched.audio_script
    assert enriched.visual_workflow_summary.confidence == 0.3


@pytest.mark.asyncio
async def test_visual_workflow_marks_provider_as_heuristic_when_model_fell_back():
    base = VisualExploreResponse(
        session_id="snap_fallback",
        what_it_is="unknown visual subject",
        why_it_matters="fallback",
        why_popular_or_overhyped="unknown",
        related_places=[],
        shoot_hint=ShootHint(
            best_time="soft light",
            stand_where="same spot",
            face_where="subject",
            how_to_shoot="add context",
        ),
        evidence_cards=[],
        confidence=0.45,
        needs_user_confirmation=True,
    )

    enriched = enrich_visual_response(
        base,
        VisualExploreInput(image_bytes=b"fake"),
        visual_reasoning={
            "subject": "unknown visual subject",
            "confidence": 0.45,
            "provider_error": "ReadTimeout",
            "confidence_notes": ["Heuristic fallback; do not treat as confirmed."],
        },
        model_used="google/gemini-3.1-pro",
    )

    assert enriched.visual_workflow_summary.provider == "heuristic"
    assert enriched.visual_workflow_summary.model == "google/gemini-3.1-pro"
    assert "Heuristic fallback" in enriched.visual_workflow_summary.uncertainty[0]


@pytest.mark.asyncio
async def test_visual_workflow_builds_one_line_answer_and_three_deep_cards():
    base = VisualExploreResponse(
        session_id="snap_yasaka",
        what_it_is="Hokan-ji Yasaka Pagoda",
        why_it_matters="它把京都东山街区、寺院历史和游客视线连在一起。",
        why_popular_or_overhyped="热门但不是只有打卡价值，关键在街区尺度和古塔关系。",
        related_places=[],
        shoot_hint=ShootHint(
            best_time="blue hour",
            stand_where="Ninenzaka/Sannenzaka street approach",
            face_where="toward the pagoda",
            how_to_shoot="用街巷作前景，让塔身成为视线终点。",
        ),
        evidence_cards=[],
        confidence=0.91,
        needs_user_confirmation=False,
        story_title="东山街巷尽头的八坂塔",
        narrative="这很可能是京都东山的八坂塔，它有意思的地方不只是古塔本身，而是街区、信仰和游客视线在同一个画面里汇合。",
        visible_clues=[],
        cultural_hypotheses=[],
        meaning_layers={
            "visual": "五重塔被低矮町屋和坡道衬托，形成京都式街景纵深。",
            "cultural_history": "法观寺八坂塔是东山地标，常被当作京都古都意象的视觉锚点。",
            "practical": "沿二年坂、三年坂靠近时最能看出它和街区的关系。",
        },
        confidence_notes=["仍建议用地图或周边招牌确认具体拍摄点。"],
    )
    visual_reasoning = {
        "subject": "Hokan-ji Yasaka Pagoda",
        "confidence": 0.91,
        "visible_clues": [
            {
                "clue": "five-story pagoda silhouette",
                "interpretation": "五重塔轮廓与京都东山八坂塔高度吻合。",
                "confidence": 0.9,
            },
            {
                "clue": "narrow preserved street",
                "interpretation": "低矮町屋和坡道说明它不是孤立建筑，而是嵌在历史街区里。",
                "confidence": 0.82,
            },
        ],
        "cultural_hypotheses": [
            {
                "name": "Hokan-ji Yasaka Pagoda",
                "entity_type": "landmark",
                "region": "Kyoto, Japan",
                "rationale": "五重塔、东山坡道和传统町屋共同指向八坂塔。",
                "confidence": 0.91,
                "evidence_support": ["五重塔轮廓", "东山街区尺度"],
                "evidence_against": ["单张照片无法确认门牌或精确街口"],
            }
        ],
        "meaning_layers": {
            "visual": "五重塔是视线终点，街巷是引导线。",
            "cultural_history": "它承载京都东山的寺院与町屋景观记忆。",
            "practical": "可以从坡道低处向上拍，保留街区层次。",
        },
        "known_comparisons": ["清水寺周边街巷", "京都东山保存街区"],
        "confidence_notes": ["单张图仍需确认具体街口。"],
        "provider": "gemini",
        "model": "google/gemini-3.1-pro",
    }

    enriched = enrich_visual_response(
        base,
        VisualExploreInput(image_sha256="yasaka-hash", image_bytes=b"fake"),
        visual_reasoning=visual_reasoning,
        model_used="google/gemini-3.1-pro",
    )

    assert enriched.one_line_answer.startswith("这是京都东山的八坂塔")
    assert [card.title for card in enriched.deep_cards] == [
        "识别",
        "看点",
        "线索",
    ]
    assert all(card.body for card in enriched.deep_cards)
    assert any("五重塔" in item for item in enriched.deep_cards[0].supporting_points)
    assert "街区、信仰" in enriched.deep_cards[1].body
    assert "坡道低处" in enriched.deep_cards[2].next_action
    assert [section.title for section in enriched.deep_cards[0].sections] == [
        "主体身份",
        "地点/类型",
        "核心特征",
    ]
    section_titles = [section.title for section in enriched.deep_cards[1].sections]
    assert section_titles == ["导游视角", "历史视角", "文化视角", "风格视角"]
    assert [section.title for section in enriched.deep_cards[2].sections] == [
        "画面线索",
        "判断依据",
        "继续探索",
    ]
    public_text = " ".join(
        [
            enriched.one_line_answer,
            *[
                " ".join(
                    [
                        card.title,
                        card.body,
                        card.next_action,
                        " ".join(card.supporting_points),
                        " ".join(section.title + section.body for section in card.sections),
                    ]
                )
                for card in enriched.deep_cards
            ],
        ]
    )
    banned_public_terms = [
        "候选",
        "置信度",
        "不确定",
        "高价值候选",
        "绝对定论",
        "fallback",
        "模型",
        "可能",
    ]
    assert not any(term in public_text for term in banned_public_terms)


@pytest.mark.asyncio
async def test_visual_workflow_sanitizes_model_public_answer_and_keeps_uncertainty_in_debug():
    base = VisualExploreResponse(
        session_id="snap_low",
        what_it_is="unknown visual subject",
        why_it_matters="内部仍需要更多证据。",
        why_popular_or_overhyped="热度未知。",
        related_places=[],
        shoot_hint=ShootHint(
            best_time="soft light",
            stand_where="front",
            face_where="subject",
            how_to_shoot="add context",
        ),
        evidence_cards=[],
        confidence=0.31,
        needs_user_confirmation=True,
        one_line_answer="这可能是一个高价值候选，但置信度不高。",
        deep_cards=[
            {
                "title": "这是什么",
                "body": "如果缺少文字、门牌或地图信息，我会把它作为高价值候选而不是绝对定论。",
                "supporting_points": ["候选自身没有足够证据"],
                "next_action": "补充信息降低不确定性。",
            },
            {
                "title": "为什么值得看",
                "body": "模型认为它可能有文化价值。",
                "supporting_points": ["置信度较低"],
                "next_action": "继续确认。",
            },
            {
                "title": "怎么看更懂",
                "body": "先看可见线索。",
                "supporting_points": ["fallback result"],
                "next_action": "补拍。",
            },
        ],
        confidence_notes=["低置信度，保留在思考过程。"],
    )

    enriched = enrich_visual_response(
        base,
        VisualExploreInput(image_sha256="low-hash", image_bytes=b"fake"),
        visual_reasoning={
            "subject": "small roadside shrine",
            "confidence": 0.31,
            "visible_clues": [
                {
                    "clue": "small roof and offering area",
                    "interpretation": "小屋顶和供奉空间指向路边小祠。",
                    "confidence": 0.42,
                }
            ],
            "confidence_notes": ["低置信度，保留在思考过程。"],
            "provider": "gemini",
        },
        model_used="google/gemini-3.1-pro",
    )

    public_text = " ".join(
        [
            enriched.one_line_answer,
            *[
                " ".join(
                    [
                        card.title,
                        card.body,
                        card.next_action,
                        " ".join(card.supporting_points),
                        " ".join(section.title + section.body for section in card.sections),
                    ]
                )
                for card in enriched.deep_cards
            ],
        ]
    )

    assert [card.title for card in enriched.deep_cards] == ["识别", "看点", "线索"]
    assert "低置信度" in enriched.visual_workflow_summary.uncertainty[0]
    for term in ["候选", "置信度", "不确定", "高价值候选", "绝对定论", "fallback", "模型", "可能"]:
        assert term not in public_text


@pytest.mark.asyncio
async def test_visual_workflow_rebalances_thin_model_sections_and_absorbs_meaning_layers():
    base = VisualExploreResponse(
        session_id="snap_shorenin",
        what_it_is="Shoren-in Temple",
        why_it_matters="它是京都东山一处更安静的门迹寺院，适合从庭院、动线和贵族佛教传统一起理解。",
        why_popular_or_overhyped="它不像清水寺那样拥挤，价值在安静庭院和青莲院门迹的层次。",
        related_places=[],
        shoot_hint=ShootHint(
            best_time="雨后清晨",
            stand_where="庭院回廊边",
            face_where="面向苔庭和楠木",
            how_to_shoot="保留回廊、苔庭和树影，让空间层次自然展开。",
        ),
        evidence_cards=[],
        confidence=0.88,
        needs_user_confirmation=False,
        one_line_answer="这是京都东山的青莲院，它的看点在安静庭院、门迹寺院传统和空间层次。",
        deep_cards=[
            {
                "title": "识别",
                "body": "青莲院。",
                "supporting_points": [],
                "next_action": "",
                "sections": [
                    {"title": "主体身份", "body": "青莲院。", "bullets": [], "chips": []},
                    {"title": "地点/类型", "body": "寺院。", "bullets": [], "chips": []},
                    {"title": "核心特征", "body": "庭院。", "bullets": [], "chips": []},
                ],
            },
            {
                "title": "看点",
                "body": "值得看。",
                "supporting_points": [],
                "next_action": "",
                "sections": [
                    {"title": "导游视角", "body": "看庭院。", "bullets": [], "chips": []},
                    {"title": "历史视角", "body": "有历史。", "bullets": [], "chips": []},
                    {"title": "文化视角", "body": "有文化。", "bullets": [], "chips": []},
                    {"title": "风格视角", "body": "有风格。", "bullets": [], "chips": []},
                ],
            },
            {
                "title": "线索",
                "body": "看线索。",
                "supporting_points": [],
                "next_action": "",
                "sections": [
                    {"title": "画面线索", "body": "苔庭。", "bullets": [], "chips": []},
                    {"title": "判断依据", "body": "庭院。", "bullets": [], "chips": []},
                    {"title": "继续探索", "body": "继续看。", "bullets": [], "chips": []},
                ],
            },
        ],
    )
    visual_reasoning = {
        "subject": "Shoren-in Temple",
        "confidence": 0.88,
        "visible_clues": [
            {
                "clue": "moss garden and covered corridor",
                "interpretation": "苔庭、回廊和低矮屋檐共同形成青莲院式的安静游览动线。",
                "confidence": 0.82,
            },
            {
                "clue": "large camphor tree beside temple garden",
                "interpretation": "大楠木和庭院边界让空间显得更像可停留的寺院庭园。",
                "confidence": 0.76,
            },
        ],
        "cultural_hypotheses": [
            {
                "name": "Shoren-in Temple",
                "entity_type": "temple",
                "region": "Kyoto, Japan",
                "rationale": "青莲院的苔庭、回廊、大楠木和东山语境互相吻合。",
                "confidence": 0.88,
                "evidence_support": ["苔庭与回廊", "东山寺院环境", "大楠木"],
                "evidence_against": ["单张图未包含门牌"],
            }
        ],
        "meaning_layers": {
            "practical": "导游上应把它放在知恩院、圆山公园一带的慢速步行路线里，先看庭院动线，再看建筑与树影。",
            "cultural_history": "历史上它属于门迹寺院系统，和皇室、贵族佛教及东山寺院网络有关。",
            "emotional": "文化体验的重点是安静、留白和停留感，而不是拥挤打卡。",
            "visual": "风格上是低矮屋檐、回廊、苔庭和大树形成的横向空间，不靠高耸体量取胜。",
            "craft": "材料和工艺层面可观察木构、纸门、庭石与苔面的细腻组合。",
        },
        "known_comparisons": ["知恩院周边", "东山庭院寺院", "京都门迹寺院"],
        "provider": "gemini",
    }

    enriched = enrich_visual_response(
        base,
        VisualExploreInput(image_sha256="shorenin-hash", image_bytes=b"fake"),
        visual_reasoning=visual_reasoning,
        model_used="google/gemini-3.1-pro",
    )

    worth = enriched.deep_cards[1]
    sections = {section.title: section for section in worth.sections}
    assert list(sections) == ["导游视角", "历史视角", "文化视角", "风格视角"]
    assert "看庭院" != sections["导游视角"].body
    assert "慢速步行路线" in sections["导游视角"].body
    assert "门迹寺院" in sections["历史视角"].body
    assert "安静、留白" in sections["文化视角"].body
    assert "低矮屋檐" in sections["风格视角"].body
    assert "木构、纸门" in " ".join([worth.body, *[section.body for section in worth.sections]])
    assert all(len(section.body) >= 35 for section in worth.sections)


@pytest.mark.asyncio
async def test_visual_workflow_keeps_raw_json_fragments_out_of_public_card_bodies():
    raw_truncated_json = (
        '**探索京都永恒之美** {"story_title":"暮色与飞檐","narrative":"沿着京都东山那些蜿蜒的石板坡道",'
        '"one_line_answer":"这是京都东山的八坂塔","deep_cards":[{"title":"识别","body":"画面中这座巍峨的五重塔'
    )
    base = VisualExploreResponse(
        session_id="snap_json_leak",
        what_it_is="Hokan-ji Yasaka Pagoda",
        why_it_matters="它把京都东山街区、寺院历史和游客视线连在一起。",
        why_popular_or_overhyped="热门但不是只有打卡价值，关键在街区尺度和古塔关系。",
        related_places=[],
        shoot_hint=ShootHint(
            best_time="傍晚",
            stand_where="八坂通入口",
            face_where="面向塔身",
            how_to_shoot="用街巷作前景，让塔身成为视线终点。",
        ),
        evidence_cards=[],
        confidence=0.91,
        needs_user_confirmation=False,
        narrative=raw_truncated_json,
        meaning_layers={
            "visual": "五重塔被低矮町屋和坡道衬托，形成京都式街景纵深。",
            "cultural_history": "法观寺八坂塔是京都东山地标，常被当作京都古都意象的视觉锚点。",
            "practical": "沿二年坂、三年坂靠近时最能看出它和街区的关系。",
        },
    )
    visual_reasoning = {
        "subject": "Hokan-ji Yasaka Pagoda",
        "confidence": 0.91,
        "visible_clues": [
            {
                "clue": "five-story pagoda silhouette",
                "interpretation": "五重塔轮廓与京都东山八坂塔高度吻合。",
                "confidence": 0.9,
            }
        ],
        "cultural_hypotheses": [
            {
                "name": "Hokan-ji Yasaka Pagoda",
                "entity_type": "landmark",
                "region": "Kyoto, Japan",
                "rationale": "五重塔、东山坡道和传统町屋共同指向八坂塔。",
                "confidence": 0.91,
                "evidence_support": ["五重塔轮廓", "东山街区尺度"],
                "evidence_against": [],
            }
        ],
        "meaning_layers": {
            "visual": "五重塔是视线终点，街巷是引导线。",
            "cultural_history": "它承载京都东山的寺院与町屋景观记忆。",
            "practical": "可以从坡道低处向上拍，保留街区层次。",
        },
    }

    enriched = enrich_visual_response(
        base,
        VisualExploreInput(image_sha256="json-leak-hash", image_bytes=b"fake"),
        visual_reasoning=visual_reasoning,
        model_used="google/gemini-3.1-pro",
    )

    public_text = " ".join(
        [
            enriched.one_line_answer,
            *[
                " ".join(
                    [
                        card.body,
                        card.next_action,
                        " ".join(card.supporting_points),
                        " ".join(section.body for section in card.sections),
                    ]
                )
                for card in enriched.deep_cards
            ],
        ]
    )
    assert "story_title" not in public_text
    assert "deep_cards" not in public_text
    assert "one_line_answer" not in public_text
    assert "{" not in public_text
    assert "}" not in public_text
    assert "story_title" not in enriched.audio_script
    assert "deep_cards" not in enriched.audio_script
    assert "京都东山" in enriched.deep_cards[1].body
    assert "五重塔" in enriched.deep_cards[1].body

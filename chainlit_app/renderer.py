from __future__ import annotations

import re
from typing import Any


CITY_ALIASES = {
    "福冈": "Fukuoka",
    "福岡": "Fukuoka",
    "fukuoka": "Fukuoka",
    "京都": "Kyoto",
    "kyoto": "Kyoto",
    "大阪": "Osaka",
    "osaka": "Osaka",
    "别府": "Beppu",
    "別府": "Beppu",
    "beppu": "Beppu",
    "宫岛": "Miyajima",
    "宮島": "Miyajima",
    "miyajima": "Miyajima",
    "广岛": "Hiroshima",
    "広島": "Hiroshima",
    "hiroshima": "Hiroshima",
}

CITY_DISPLAY_NAMES = {
    "Fukuoka": "福冈",
    "Kyoto": "京都",
    "Osaka": "大阪",
    "Beppu": "别府",
    "Miyajima": "宫岛",
    "Hiroshima": "广岛",
}

CATEGORY_ALIASES = {
    "美食": [
        "美食",
        "好吃",
        "吃的",
        "吃饭",
        "餐厅",
        "拉面",
        "屋台",
        "咖啡",
        "甜品",
        "日料",
        "日本料理",
        "寿司",
        "天妇罗",
        "居酒屋",
        "food",
        "japanese food",
    ],
    "购物": ["购物", "买", "伴手礼", "商场", "香水", "perfume", "fragrance", "souvenir", "shopping"],
    "历史文化": ["历史", "文化", "寺", "神社", "博物馆", "遗迹", "heritage"],
    "本地体验": [
        "本地体验",
        "好玩",
        "玩什么",
        "去哪玩",
        "游玩",
        "景点",
        "活动",
        "体验",
        "工作坊",
        "things to do",
        "attraction",
        "attractions",
        "local",
    ],
    "购物与街区": ["街区", "逛街", "步行街", "商店街", "neighborhood"],
    "自然与摄影": ["自然", "摄影", "拍照", "风景", "公园", "日落", "photo"],
}

ORIGIN_ALIASES = {
    "东京": "Tokyo",
    "東京": "Tokyo",
    "tokyo": "Tokyo",
    "大阪": "Osaka",
    "osaka": "Osaka",
    "上海": "Shanghai",
    "shanghai": "Shanghai",
    "北京": "Beijing",
    "beijing": "Beijing",
}


def build_travel_payload(
    message: str,
    previous_payload: dict[str, Any] | None = None,
    chat_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous_payload = previous_payload or {}
    chat_settings = chat_settings or {}
    settings_text = " ".join(
        str(chat_settings.get(key) or "") for key in ["Where", "When", "Who", "Budget"]
    )
    city = (
        _first_alias(message, CITY_ALIASES)
        or _first_alias(str(chat_settings.get("Where") or ""), CITY_ALIASES)
        or str(chat_settings.get("Where") or "").strip()
        or previous_payload.get("city")
    )
    origin = _origin_from_text(message)
    date_range = re.findall(r"20\d{2}-\d{2}-\d{2}", f"{message} {settings_text}")[:2]
    travelers = _travelers_from_text(message) or _travelers_from_setting(chat_settings.get("Who"))
    budget = _budget_from_text(message) or _budget_from_setting(chat_settings.get("Budget"))
    requested_categories = _requested_categories_from_text(message)
    preferences = _settings_list(chat_settings.get("Preferences"))
    intent_tags = _intent_tags_from_text(message)
    avoid = _settings_list(chat_settings.get("Avoid"))
    previous_context = _previous_context(previous_payload)
    previous_interest_tags = _string_list(previous_payload.get("interest_tags"))
    interest_tags = list(
        dict.fromkeys(
            [
                *previous_interest_tags,
                *(preferences or []),
                *intent_tags,
                *(requested_categories if not previous_interest_tags and not preferences and not intent_tags else []),
            ]
        )
    ) or previous_payload.get("interest_tags", [])
    return {
        "city": city,
        "origin_city": origin or previous_payload.get("origin_city"),
        "query": message,
        "question": message,
        "date_range": date_range or previous_payload.get("date_range", []),
        "budget": budget or previous_payload.get("budget", ""),
        "travelers": travelers or previous_payload.get("travelers", 1),
        "interest_tags": interest_tags,
        "avoid": avoid or previous_payload.get("avoid", []),
        "requested_categories": requested_categories,
        "previous_context": previous_context,
        "allow_web_search": True,
        "evidence_refresh": "auto",
    }


def merge_travel_context(
    previous_context: dict[str, Any],
    payload: dict[str, Any],
    *,
    last_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = dict(previous_context or {})
    for key in [
        "city",
        "origin_city",
        "date_range",
        "budget",
        "travelers",
        "interest_tags",
        "avoid",
        "requested_categories",
        "trip_items",
        "liked_items",
    ]:
        value = payload.get(key)
        if value not in (None, "", []):
            context[key] = value
    if last_response:
        context["last_summary"] = str(last_response.get("summary") or "")
        context["last_recommended_items"] = _response_group_items(last_response)
        context["last_not_recommended"] = _response_not_recommended(last_response)
    return context


def trip_header_props(
    context: dict[str, Any],
    response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context or {}
    response = response or {}
    city = str(context.get("city") or "").strip()
    display_city = CITY_DISPLAY_NAMES.get(city, city)
    intent = response.get("resolved_intent")
    intent = intent if isinstance(intent, dict) else {}
    category = str(intent.get("category") or "").strip()
    title = "新的旅行推荐"
    if city and category:
        title = f"{display_city}{category}推荐"
    elif city:
        title = f"{display_city}旅行推荐"
    subtitle = f"Trip to {city}" if city else "Ask anything"
    return {
        "title": title,
        "subtitle": subtitle,
        "trip_count": len(_trip_items(context)),
        "chips": [
            _header_chip("Where", city or ""),
            _header_chip("When", _date_range_label(context.get("date_range"))),
            _header_chip("Who", _who_label(context.get("travelers"))),
            _header_chip("Budget", str(context.get("budget") or "")),
            _header_chip("Preferences", _list_label(context.get("interest_tags"))),
            _header_chip("Avoid", _list_label(context.get("avoid"))),
        ],
        "share_text": _share_text(context, response),
    }


def apply_trip_header_update(context: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(context or {})
    field = str(payload.get("field") or "").strip()
    value = payload.get("value")
    text = str(value or "").strip()
    if field == "Where":
        updated["city"] = _first_alias(text, CITY_ALIASES) or text
    elif field == "When":
        dates = re.findall(r"20\d{2}-\d{2}-\d{2}", text)[:2]
        updated["date_range"] = dates or ([text] if text else [])
    elif field == "Who":
        travelers = _travelers_from_setting(text)
        if travelers:
            updated["travelers"] = travelers
    elif field == "Budget":
        updated["budget"] = text
    elif field == "Preferences":
        updated["interest_tags"] = _settings_list(text)
    elif field == "Avoid":
        updated["avoid"] = _settings_list(text)
    return updated


def apply_trip_card_action(context: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(context or {})
    card = payload.get("card")
    card = _normalize_trip_card(card) if isinstance(card, dict) else {}
    if not card.get("title"):
        return updated
    action = str(payload.get("action") or "").strip()
    if action == "add_to_trip":
        updated["trip_items"] = _upsert_card(_trip_items(updated), card)
    elif action == "toggle_like":
        liked = _trip_items({"trip_items": updated.get("liked_items")})
        updated["liked_items"] = [] if _has_card(liked, card) else _upsert_card(liked, card)
    return updated


def markdown_from_response(response: dict[str, Any]) -> str:
    formatted = str(response.get("formatted_markdown") or "").strip()
    if formatted:
        return formatted
    workflow_summary = _workflow_summary_markdown(response.get("workflow_summary"))
    lines = [
        "## 总建议",
        str(response.get("summary") or "已生成推荐，但后端没有返回格式化文本。"),
    ]
    pros = _string_list(response.get("pros"))
    cons = _string_list(response.get("cons"))
    if pros:
        lines.extend(["", "## 正面", *[f"- {item}" for item in pros[:5]]])
    if cons:
        lines.extend(["", "## 反面", *[f"- {item}" for item in cons[:5]]])
    gaps = _string_list(response.get("data_gaps"))
    if gaps:
        lines.extend(["", "## 需要确认", *[f"- {item}" for item in gaps[:6]]])
    fallback = "\n".join(lines)
    return f"{workflow_summary}\n\n{fallback}" if workflow_summary else fallback


def step_summaries(response: dict[str, Any]) -> list[str]:
    steps = []
    workflow_summary = response.get("workflow_summary")
    if isinstance(workflow_summary, dict):
        counts = workflow_summary.get("candidate_counts")
        counts = counts if isinstance(counts, dict) else {}
        steps.append(
            "Workflow summary: "
            f"tools {counts.get('tool_count', 0)} / "
            f"candidates {counts.get('total_items', 0)} / "
            f"agents {counts.get('agent_count', 0)} / "
            f"confidence {workflow_summary.get('confidence', 'unknown')}"
        )
    budget_count = len(_items(response.get("budget_summary")))
    transport_count = len(_items(response.get("transport_summary")))
    optional = response.get("optional_context")
    optional_keys = ", ".join(optional.keys()) if isinstance(optional, dict) and optional else "none"
    provider = str(response.get("suggestion_source") or "api").title()
    steps.append(
        f"{provider}: budget {budget_count} / transport {transport_count} / optional {optional_keys}"
    )
    for workflow_step in response.get("agentic_workflow") or []:
        if not isinstance(workflow_step, dict):
            continue
        tools = workflow_step.get("tools") or []
        tool_count = len(tools) if isinstance(tools, list) else 0
        steps.append(
            " / ".join(
                [
                    f"ReACT {workflow_step.get('phase', 'step')}: {workflow_step.get('actor', 'Agent')}",
                    str(workflow_step.get("action") or ""),
                    f"tools {tool_count}",
                ]
            )
        )
    refs = response.get("raw_provider_refs")
    if isinstance(refs, dict):
        agents = refs.get("agent_results")
        if isinstance(agents, dict):
            for name, result in agents.items():
                if not isinstance(result, dict):
                    continue
                steps.append(
                    f"{name}: {result.get('model', 'unknown')} / API候选 {result.get('raw_api_count', 0)}"
                )
    return steps


def missing_core_fields(payload: dict[str, Any]) -> list[str]:
    missing = []
    if not payload.get("city"):
        missing.append("目的地")
    return missing


def trip_board_props(
    response: dict[str, Any],
    runtime_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cards = [
        _normalize_trip_card(item)
        for item in response.get("display_cards") or []
        if isinstance(item, dict)
    ]
    map_view = response.get("map_view")
    map_view = map_view if isinstance(map_view, dict) else {}
    runtime_config = runtime_config or {}
    google_maps_api_key = str(runtime_config.get("google_maps_api_key") or "").strip()
    google_maps_map_id = str(runtime_config.get("google_maps_map_id") or "").strip()
    fallback_provider = str(map_view.get("provider") or "photo_agent_map")
    provider = "google_maps" if google_maps_api_key else "google_maps_missing_key"
    mode = "google_maps_js" if google_maps_api_key else "fallback_panel"
    return {
        "title": str(response.get("summary") or "Trip Board"),
        "google_maps_key": google_maps_api_key,
        "cards": cards,
        "map": {
            "center": map_view.get("center") or _default_center(cards),
            "pins": [
                pin for pin in map_view.get("pins", []) if isinstance(pin, dict)
            ],
            "selected_pin_id": map_view.get("selected_pin_id") or (cards[0]["id"] if cards else ""),
            "provider": provider,
            "fallback_provider": fallback_provider,
            "mode": mode,
            "status": map_view.get("status") or ("ready" if cards else "empty"),
            "api_key": google_maps_api_key,
            "browser_key": google_maps_api_key,
            "map_id": google_maps_map_id,
            "libraries": ["marker", "places"],
        },
    }


def response_message_sequence(
    response: dict[str, Any],
    runtime_config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    sequence: list[dict[str, Any]] = []
    board = trip_board_props(response, runtime_config=runtime_config)
    if board.get("cards"):
        sequence.append({"type": "trip_board", "props": board})
    markdown = markdown_from_response(response)
    if markdown.strip():
        sequence.append({"type": "markdown", "content": markdown})
    return sequence


def _first_alias(text: str, aliases: dict[str, str]) -> str | None:
    lowered = text.lower()
    for alias, value in aliases.items():
        if alias.lower() in lowered:
            return value
    return None


def _origin_from_text(text: str) -> str | None:
    lowered = text.lower()
    for alias, value in ORIGIN_ALIASES.items():
        if alias.lower() not in lowered:
            continue
        marker_patterns = [
            f"从{alias}",
            f"{alias}出发",
            f"from {alias.lower()}",
        ]
        if any(pattern in lowered for pattern in marker_patterns):
            return value
    return None


def _travelers_from_text(text: str) -> int | None:
    match = re.search(r"(\d+)\s*(?:个人|人|位|traveler|travelers)", text, flags=re.I)
    if match:
        return max(1, int(match.group(1)))
    return None


def _travelers_from_setting(value: Any) -> int | None:
    if value in (None, "", []):
        return None
    match = re.search(r"\d+", str(value))
    if not match:
        return None
    return max(1, int(match.group(0)))


def _budget_from_text(text: str) -> str:
    amount = re.search(r"(?:预算|budget)\s*([0-9][0-9,]*(?:\.\d+)?)", text, flags=re.I)
    if amount:
        suffix = ""
        tail = text[amount.end() : amount.end() + 8]
        if "人民币" in tail or "元" in tail:
            suffix = "人民币"
        elif "日元" in tail or "円" in tail:
            suffix = "日元"
        elif "usd" in tail.lower() or "美元" in tail:
            suffix = "美元"
        return amount.group(1).replace(",", "") + suffix
    for token in ["低预算", "中等预算", "高预算", "奢华", "省钱", "性价比"]:
        if token in text:
            return token
    return ""


def _budget_from_setting(value: Any) -> str:
    return str(value or "").strip()


def _requested_categories_from_text(text: str) -> list[str]:
    explicit_scope = any(token in text for token in ["只", "仅", "只要", "只推荐", "不用", "别的先不用"])
    matches = [
        category
        for category, aliases in CATEGORY_ALIASES.items()
        if any(alias.lower() in text.lower() for alias in aliases)
    ]
    if explicit_scope or (matches and not _is_broad_trip_request(text)):
        return list(dict.fromkeys(matches))
    return []


def _intent_tags_from_text(text: str) -> list[str]:
    lowered = text.lower()
    tags: list[str] = []
    markers = [
        ("日料", ["日料", "日本料理", "japanese food", "寿司", "天妇罗", "居酒屋"]),
        ("香水", ["香水", "perfume", "fragrance", "parfum"]),
        ("好玩", ["好玩", "玩什么", "去哪玩", "游玩", "景点", "things to do", "attraction"]),
        ("屋台", ["屋台", "yatai"]),
        ("拉面", ["拉面", "ramen", "ラーメン"]),
    ]
    for label, aliases in markers:
        if any(alias.lower() in lowered for alias in aliases):
            tags.append(label)
    return tags


def _is_broad_trip_request(text: str) -> bool:
    lowered = text.lower()
    return any(
        token in lowered
        for token in [
            "行程",
            "自由行",
            "几天",
            "两天",
            "三天",
            "完整",
            "安排",
            "itinerary",
            "trip",
            "plan",
        ]
    )


def _settings_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,，、\n]", value) if part.strip()]
    return []


def _header_chip(id_: str, value: str) -> dict[str, Any]:
    value = str(value or "").strip()
    return {
        "id": id_,
        "label": value or id_,
        "value": value,
        "empty": not bool(value),
    }


def _date_range_label(value: Any) -> str:
    if isinstance(value, list):
        values = [str(item).strip() for item in value if str(item).strip()]
        if len(values) >= 2:
            return f"{values[0]} - {values[1]}"
        if values:
            return values[0]
    if isinstance(value, str):
        return value.strip()
    return ""


def _who_label(value: Any) -> str:
    if isinstance(value, int) and value > 1:
        return f"{value} people"
    if isinstance(value, int) and value == 1:
        return ""
    return str(value or "").strip()


def _list_label(value: Any) -> str:
    values = _string_list(value)
    return ", ".join(values)


def _share_text(context: dict[str, Any], response: dict[str, Any]) -> str:
    city = str(context.get("city") or "").strip()
    title = str(response.get("summary") or "").strip() or (f"Trip to {city}" if city else "新的旅行推荐")
    items = [
        str(item.get("title") or "")
        for item in response.get("display_cards", [])
        if isinstance(item, dict) and item.get("title")
    ][:5]
    if not items:
        items = [str(item.get("title") or "") for item in _trip_items(context)[:5] if item.get("title")]
    suffix = "\n".join(f"- {item}" for item in items if item)
    return f"{title}\n{suffix}".strip()


def _trip_items(context: dict[str, Any]) -> list[dict[str, Any]]:
    items = context.get("trip_items") if isinstance(context, dict) else []
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _has_card(items: list[dict[str, Any]], card: dict[str, Any]) -> bool:
    card_id = str(card.get("id") or "")
    title = str(card.get("title") or "").strip().lower()
    return any(
        (bool(card_id) and str(item.get("id") or "") == card_id)
        or (bool(title) and str(item.get("title") or "").strip().lower() == title)
        for item in items
    )


def _upsert_card(items: list[dict[str, Any]], card: dict[str, Any]) -> list[dict[str, Any]]:
    existing = [item for item in items if not _has_card([item], card)]
    return [*existing, card]


def _normalize_trip_card(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "title": str(item.get("title") or ""),
        "category": str(item.get("category") or ""),
        "subcategory": str(item.get("subcategory") or ""),
        "subtitle": str(item.get("subtitle") or ""),
        "description": str(item.get("description") or item.get("reason") or ""),
        "rating": item.get("rating"),
        "review_count": item.get("review_count"),
        "price": str(item.get("price") or ""),
        "address": str(item.get("address") or ""),
        "image_url": str(item.get("image_url") or ""),
        "image_urls": _normalized_image_urls(item),
        "image_status": str(item.get("image_status") or "missing"),
        "source_url": str(item.get("source_url") or ""),
        "source_provider": str(item.get("source_provider") or ""),
        "place_id": str(item.get("place_id") or item.get("placeId") or ""),
        "photo_attributions": _string_list(item.get("photo_attributions") or item.get("photoAttributions")),
        "reason": str(item.get("reason") or ""),
        "lat": item.get("lat"),
        "lng": item.get("lng"),
        "tags": _string_list(item.get("tags")),
        "trip_state": str(item.get("trip_state") or "none"),
        "google_maps_uri": str(item.get("google_maps_uri") or ""),
        "directions_uri": str(item.get("directions_uri") or ""),
    }


def _normalized_image_urls(item: dict[str, Any]) -> list[str]:
    values = _string_list(item.get("image_urls"))
    image_url = str(item.get("image_url") or "").strip()
    if image_url:
        values = [image_url, *values]
    return list(dict.fromkeys([value for value in values if value.startswith("http")]))


def _default_center(cards: list[dict[str, Any]]) -> dict[str, float]:
    points = [
        (card.get("lat"), card.get("lng"))
        for card in cards
        if isinstance(card.get("lat"), int | float) and isinstance(card.get("lng"), int | float)
    ]
    if not points:
        return {"lat": 35.6812, "lng": 139.7671}
    return {
        "lat": sum(float(lat) for lat, _ in points) / len(points),
        "lng": sum(float(lng) for _, lng in points) / len(points),
    }


def _previous_context(previous_payload: dict[str, Any]) -> dict[str, Any]:
    allowed = [
        "city",
        "origin_city",
        "date_range",
        "budget",
        "travelers",
        "interest_tags",
        "avoid",
        "requested_categories",
        "last_summary",
        "last_recommended_items",
        "last_not_recommended",
        "trip_items",
        "liked_items",
    ]
    return {
        key: previous_payload[key]
        for key in allowed
        if previous_payload.get(key) not in (None, "", [])
    }


def _response_group_items(response: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for group in response.get("category_groups") or []:
        if not isinstance(group, dict):
            continue
        for item in group.get("items") or []:
            if str(item).strip():
                items.append(str(item))
    return list(dict.fromkeys(items))[:12]


def _response_not_recommended(response: dict[str, Any]) -> list[str]:
    names = []
    for item in response.get("not_recommended") or []:
        if not isinstance(item, dict):
            continue
        place = item.get("place")
        if isinstance(place, dict) and place.get("name"):
            names.append(str(place["name"]))
    return names[:8]


def _items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _workflow_summary_markdown(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return ""
    counts = value.get("candidate_counts")
    counts = counts if isinstance(counts, dict) else {}
    lines = ["## 过程摘要"]
    tool_summary = str(value.get("tool_summary") or "").strip()
    if tool_summary:
        lines.append(f"- {tool_summary}")
    lines.append(
        "- "
        f"工具 {counts.get('tool_count', 0)} 个；"
        f"候选 {counts.get('total_items', 0)} 条；"
        f"Agent {counts.get('agent_count', 0)} 个；"
        f"置信度 {value.get('confidence', 'unknown')}。"
    )
    critic_notes = _string_list(value.get("critic_notes"))
    if critic_notes:
        lines.append(f"- Critic: {critic_notes[0]}")
    missing = _string_list(value.get("missing_but_non_blocking"))
    if missing:
        lines.append(f"- 补充后更准: {'；'.join(missing[:2])}")
    return "\n".join(lines)

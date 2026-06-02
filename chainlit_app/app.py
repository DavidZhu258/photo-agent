from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values

import chainlit as cl

from chainlit_app.renderer import (
    apply_trip_card_action,
    apply_trip_header_update,
    build_travel_payload,
    merge_travel_context,
    missing_core_fields,
    response_message_sequence,
    trip_header_props,
)


BACKEND_ENV_PATH = Path(__file__).resolve().parents[1] / "backend" / ".env"


def _config_value(name: str) -> str:
    backend_env = dotenv_values(BACKEND_ENV_PATH)
    return str(os.getenv(name) or backend_env.get(name) or "")


API_BASE_URL = os.getenv("PHOTO_AGENT_API_BASE_URL", "http://127.0.0.1:8768")


def _trip_runtime_config() -> dict[str, str]:
    return {
        "google_maps_api_key": _config_value("GOOGLE_MAPS_API_KEY"),
        "google_maps_map_id": _config_value("GOOGLE_MAPS_MAP_ID"),
    }


@cl.on_chat_start
async def on_chat_start() -> None:
    cl.user_session.set("travel_context", {})
    cl.user_session.set("travel_settings", {})
    await _send_or_update_trip_header({})


@cl.on_settings_update
async def on_settings_update(settings: dict[str, Any]) -> None:
    cl.user_session.set("travel_settings", dict(settings or {}))


@cl.action_callback("trip_header_update")
async def on_trip_header_update(action) -> dict[str, Any]:
    context = cl.user_session.get("travel_context") or {}
    updated = apply_trip_header_update(context, action.payload or {})
    cl.user_session.set("travel_context", updated)
    props = trip_header_props(updated)
    await _send_or_update_trip_header(updated)
    return props


@cl.action_callback("trip_card_action")
async def on_trip_card_action(action) -> dict[str, Any]:
    context = cl.user_session.get("travel_context") or {}
    updated = apply_trip_card_action(context, action.payload or {})
    cl.user_session.set("travel_context", updated)
    props = trip_header_props(updated, cl.user_session.get("last_travel_response") or {})
    await _send_or_update_trip_header(updated, cl.user_session.get("last_travel_response") or {})
    return props


@cl.on_message
async def on_message(message: cl.Message) -> None:
    previous_context = cl.user_session.get("travel_context") or {}
    chat_settings = cl.user_session.get("travel_settings") or {}
    payload = build_travel_payload(
        message.content,
        previous_payload=previous_context,
        chat_settings=chat_settings,
    )
    missing = missing_core_fields(payload)
    if missing:
        await cl.Message(
            content=(
                "我还缺这些关键信息："
                + "、".join(missing)
                + "。可以直接补一句，例如：去福冈，偏美食和摄影。"
            )
        ).send()
        return

    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{API_BASE_URL}/v1/travel/plan",
            json=payload,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        cl.user_session.set(
            "travel_context",
            merge_travel_context(previous_context, payload, last_response=data),
        )
        await _send_or_update_trip_header(
            cl.user_session.get("travel_context") or {},
            data,
        )
        cl.user_session.set("last_travel_response", data)

    for item in response_message_sequence(data, runtime_config=_trip_runtime_config()):
        if item["type"] == "trip_board":
            await cl.Message(
                content="",
                elements=[cl.CustomElement(name="TripBoard", props=item["props"], display="inline")],
            ).send()
            continue
        if item["type"] == "markdown":
            msg = cl.Message(content="")
            await msg.send()
            for token in _stream_chunks(str(item["content"])):
                await msg.stream_token(token)
            await msg.update()


def _stream_chunks(markdown: str, chunk_size: int = 2) -> list[str]:
    return [markdown[index : index + chunk_size] for index in range(0, len(markdown), chunk_size)]


async def _send_or_update_trip_header(
    context: dict[str, Any],
    response: dict[str, Any] | None = None,
) -> None:
    props = trip_header_props(context, response)
    element = cl.user_session.get("trip_header_element")
    if element is not None:
        element.props = props
        element.content = json.dumps(props, ensure_ascii=False)
        await element.update()
        return
    element = cl.CustomElement(name="TripHeader", props=props, display="inline")
    await cl.Message(content="", elements=[element]).send()
    cl.user_session.set("trip_header_element", element)

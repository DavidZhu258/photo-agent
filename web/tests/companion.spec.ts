import { expect, test } from "@playwright/test";

import {
  buildAssistantMessageFromPlan,
  buildTravelPayload,
  mergeContextFromPlan,
  mergeContextFromText,
} from "../src/lib/travel-chat";

const tripResponse = {
  id: "assistant-1",
  role: "assistant",
  parts: [
    {
      type: "text",
      text:
        "福冈好玩的地方建议先按海边、城市观景和在地街区来选。下面这些是可直接放进地图的地点，先看你喜欢的氛围，再决定要不要加进 Trip。",
    },
    {
      type: "trip-header",
      title: "福冈本地体验推荐",
      subtitle: "Trip to Fukuoka",
      chips: [
        { id: "Where", label: "Where", value: "Fukuoka" },
        { id: "When", label: "When", value: "" },
        { id: "Who", label: "Who", value: "" },
        { id: "Budget", label: "Budget", value: "" },
        { id: "Preferences", label: "Preferences", value: "好玩" },
      ],
      trip_count: 0,
    },
    {
      type: "trip-cards",
      cards: [
        {
          id: "card-1",
          title: "Momochihama Beach",
          category: "本地体验",
          subcategory: "景点活动",
          subtitle: "Waterfront",
          description: "适合散步、看海和顺路去福冈塔，第一次来福冈也不容易踩雷。",
          rating: 4.3,
          review_count: 1220,
          price: "",
          address: "Momochihama, Sawara Ward, Fukuoka",
          image_urls: [
            "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee",
            "https://images.unsplash.com/photo-1507525428034-b723cf961d3e",
          ],
          image_status: "source_item",
          place_id: "ChIJMomochi",
          lat: 33.594997,
          lng: 130.35313,
          google_maps_uri: "https://www.google.com/maps/search/?api=1&query=Momochihama%20Beach",
          directions_uri: "https://www.google.com/maps/dir/?api=1&destination=Momochihama%20Beach",
          trip_state: "none",
        },
        {
          id: "card-2",
          title: "Fukuoka Tower",
          category: "本地体验",
          subcategory: "景点活动",
          subtitle: "Observation deck",
          description: "天气好时看城市和海岸线，适合傍晚前后安排。",
          rating: 4.2,
          review_count: 5400,
          price: "¥",
          address: "2 Chome-3-26 Momochihama, Sawara Ward, Fukuoka",
          image_urls: ["https://images.unsplash.com/photo-1494526585095-c41746248156"],
          image_status: "source_item",
          place_id: "ChIJTower",
          lat: 33.593332,
          lng: 130.351432,
          google_maps_uri: "https://www.google.com/maps/search/?api=1&query=Fukuoka%20Tower",
          directions_uri: "https://www.google.com/maps/dir/?api=1&destination=Fukuoka%20Tower",
          trip_state: "none",
        },
      ],
    },
    {
      type: "trip-map",
      map: {
        provider: "google_maps",
        mode: "google_maps_js",
        center: { lat: 33.594, lng: 130.352 },
        selected_pin_id: "card-1",
        pins: [
          {
            id: "card-1",
            title: "Momochihama Beach",
            category: "本地体验",
            subcategory: "景点活动",
            lat: 33.594997,
            lng: 130.35313,
            place_id: "ChIJMomochi",
          },
          {
            id: "card-2",
            title: "Fukuoka Tower",
            category: "本地体验",
            subcategory: "景点活动",
            lat: 33.593332,
            lng: 130.351432,
            place_id: "ChIJTower",
          },
        ],
      },
    },
    {
      type: "runtime-warnings",
      warnings: [],
    },
  ],
};

test.beforeEach(async ({ page }) => {
  await page.route("**/api/mapbox/tile/**", async (route) => {
    await route.fulfill({
      contentType: "image/svg+xml",
      body:
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e8efeb"/><path d="M0 140 C70 120 130 170 256 130" stroke="#94c5dd" stroke-width="18" fill="none"/><path d="M30 0 L210 256" stroke="#ffffff" stroke-width="10"/></svg>',
    });
  });
  await page.route("**/api/mapbox/static-map**", async (route) => {
    await route.fulfill({
      contentType: "image/svg+xml",
      body:
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900"><rect width="1200" height="900" fill="#e8efeb"/><circle cx="520" cy="420" r="30" fill="#0369a1"/><circle cx="650" cy="460" r="22" fill="#111827"/></svg>',
    });
  });
});

async function visibleLeafletZoom(page: import("@playwright/test").Page) {
  return page.locator("img.leaflet-tile").evaluateAll((tiles) => {
    const zooms = tiles
      .map((tile) => {
        const src = (tile as HTMLImageElement).src;
        const match = src.match(/\/api\/mapbox\/tile\/(\d+)\//);
        return match ? Number.parseInt(match[1], 10) : 0;
      })
      .filter((zoom) => Number.isFinite(zoom) && zoom > 0);
    return zooms.length ? Math.max(...zooms) : 0;
  });
}

async function zIndexOf(page: import("@playwright/test").Page, selector: string) {
  return page.locator(selector).first().evaluate((element) => {
    const value = window.getComputedStyle(element).zIndex;
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) ? parsed : 0;
  });
}

async function maxMapLayerZIndex(page: import("@playwright/test").Page) {
  return page
    .locator(".leaflet-pane, .leaflet-marker-icon, .mapboxgl-marker, .mapboxgl-control-container")
    .evaluateAll((elements) =>
      elements.reduce((max, element) => {
        const value = window.getComputedStyle(element).zIndex;
        const parsed = Number.parseInt(value, 10);
        return Number.isFinite(parsed) ? Math.max(max, parsed) : max;
      }, 0),
    );
}

test("frontend leaves category understanding to the backend semantic workflow", () => {
  const context = mergeContextFromText({}, "福冈有什么好玩的?");
  const payload = buildTravelPayload("福冈有什么好玩的?", context);

  expect(context.city).toBe("Fukuoka");
  expect(context.preferences).toEqual([]);
  expect(payload.requested_categories).toEqual([]);
  expect(payload.interest_tags).toEqual([]);
});

test("session context keeps Hiroshima and outdoor preferences across follow-up", () => {
  const context = mergeContextFromText({}, "广岛有什么好玩的?");
  expect(context.city).toBe("Hiroshima");

  const followupContext = mergeContextFromText(context, "我喜欢户外风光");
  const payload = buildTravelPayload("我喜欢户外风光", followupContext);

  expect(followupContext.city).toBe("Hiroshima");
  expect(followupContext.preferences).toContain("户外风光");
  expect(payload.city).toBe("Hiroshima");
  expect(payload.previous_context.city).toBe("Hiroshima");
  expect(payload.previous_context.interest_tags).toContain("户外风光");
});

test("backend plan updates session memory for the next turn", () => {
  const context = mergeContextFromPlan(
    {},
    {
      narrative_answer: "广岛可以按历史公园、岛屿海景和庭园慢慢玩。",
      answer_mode: "place_cards",
      resolved_intent: {
        city: "Hiroshima",
        destination: "Hiroshima",
        category: "本地体验",
      },
      display_cards: [
        {
          id: "shukkeien",
          title: "Shukkeien Garden",
          category: "自然与摄影",
          subcategory: "庭园",
          address: "2-11 Kaminoboricho, Hiroshima",
          lat: 34.4006,
          lng: 132.4672,
        },
      ],
      map_view: {
        selected_pin_id: "shukkeien",
        pins: [
          {
            id: "shukkeien",
            title: "Shukkeien Garden",
            lat: 34.4006,
            lng: 132.4672,
          },
        ],
      },
    },
    "广岛有什么好玩的?",
  );
  const followupContext = mergeContextFromText(context, "我喜欢户外风光");
  const payload = buildTravelPayload("我喜欢户外风光", followupContext);

  expect(context.city).toBe("Hiroshima");
  expect(context.activeQuery).toBe("广岛有什么好玩的?");
  expect(context.lastQuery).toBe("广岛有什么好玩的?");
  expect(context.lastCards?.[0]?.title).toBe("Shukkeien Garden");
  expect(payload.query).toBe("Hiroshima 我喜欢户外风光");
  expect(payload.question).toBe("我喜欢户外风光");
  expect(payload.previous_context.active_query).toBe("广岛有什么好玩的?");
  expect(payload.previous_context.last_query).toBe("广岛有什么好玩的?");
  expect(payload.previous_context.last_cards?.[0]?.title).toBe("Shukkeien Garden");
  expect(payload.previous_context.map_pins?.[0]?.title).toBe("Shukkeien Garden");
  expect(payload.previous_context.selected_card_id).toBe("shukkeien");
});

test("new answer-only questions keep city memory without inheriting stale map cards", () => {
  const context = mergeContextFromPlan(
    {},
    {
      answer_mode: "place_cards",
      resolved_intent: { city: "Fukuoka", destination: "Fukuoka" },
      display_cards: [
        {
          id: "ohori",
          title: "大濠公园",
          category: "自然与摄影",
          lat: 33.586,
          lng: 130.376,
        },
      ],
      map_view: {
        selected_pin_id: "ohori",
        pins: [{ id: "ohori", title: "大濠公园", lat: 33.586, lng: 130.376 }],
      },
    },
    "福冈有哪些好玩的日本其他地方没有?",
  );

  const payload = buildTravelPayload("天神屋台本地人会常去吗?还是说是游客去的?", context);

  expect(payload.city).toBe("Fukuoka");
  expect(payload.query).toBe("天神屋台本地人会常去吗?还是说是游客去的?");
  expect(payload.previous_context.city).toBe("Fukuoka");
  expect(payload.previous_context.last_cards).toEqual([]);
  expect(payload.previous_context.map_pins).toEqual([]);
  expect(payload.previous_context.selected_card_id).toBe("");
});

test("assistant plan converts markdown answer framework into typed sections", () => {
  const message = buildAssistantMessageFromPlan(
    {
      narrative_answer:
        [
          "## 怎么选",
          "先按天气和移动距离选：晴天优先海边，雨天优先室内观景或街区。",
          "- 海边适合慢节奏散步。",
          "- 街区适合半天灵活安排。",
          "## 去哪儿",
          "优先看百道海滨、福冈塔和大濠公园这类容易落地的选择。",
          "- Momochihama Beach",
          "- Fukuoka Tower",
          "## 怎么排/地图",
          "把同一区域串在一起，不要把海边和市中心来回折返。",
          "- 下午去海边，傍晚接福冈塔。",
        ].join("\n"),
      summary: "旧摘要不应该优先展示。",
      display_cards: [
        {
          id: "card-1",
          title: "Momochihama Beach",
          category: "本地体验",
          subcategory: "景点活动",
          display_reason: "海边散步和福冈塔可以顺路安排。",
          lat: 33.594997,
          lng: 130.35313,
        },
      ],
      map_view: { pins: [] },
      resolved_intent: {
        category: "本地体验",
      },
    },
    { city: "Fukuoka" },
    "福冈有什么好玩的?",
  );

  const textPart = message.parts.find((part) => part.type === "text");
  const sectionsPart = message.parts.find((part) => part.type === "trip-answer-sections");
  expect(textPart?.type).toBe("text");
  const text = textPart?.type === "text" ? textPart.text : "";
  expect(text).toContain("先按天气和移动距离选");
  expect(text).not.toContain("我把这次推荐拆成");
  expect(text).not.toContain("下面卡片和地图");
  expect(text).not.toContain("##");
  expect(text).not.toContain("Momochihama Beach");
  expect(sectionsPart?.type).toBe("trip-answer-sections");
  expect(sectionsPart?.type === "trip-answer-sections" ? sectionsPart.sections.map((section) => section.title) : []).toEqual([
    "怎么选",
    "去哪儿",
    "怎么排/地图",
  ]);
  expect(sectionsPart?.type === "trip-answer-sections" ? sectionsPart.sections[1].bullets : []).toContain("Fukuoka Tower");
});

test("assistant plan preserves multimodal answer sections from backend contract", () => {
  const message = buildAssistantMessageFromPlan(
    {
      answer_sections: [
        {
          id: "compare",
          title: "候选对比",
          body: "先看真实地点，再决定地图动线。",
          bullets: ["Hakata Old Town Area", "Ohori Park"],
          card_ids: ["card-1"],
          pin_ids: ["card-1"],
          tables: [
            {
              caption: "地点怎么选",
              columns: ["地点", "适合谁"],
              rows: [["Hakata Old Town Area", "想看街区和寺社的人"]],
            },
          ],
          images: [
            {
              url: "https://example.com/hakata-old-town.jpg",
              caption: "博多旧市街",
              source: "serper_images",
            },
          ],
        },
      ],
      summary: "旧摘要不应该覆盖结构化 section。",
      display_cards: [
        {
          id: "card-1",
          title: "Hakata Old Town Area",
          category: "本地体验",
          subcategory: "街区",
          lat: 33.595,
          lng: 130.413,
        },
      ],
      map_view: {
        pins: [
          {
            id: "card-1",
            title: "Hakata Old Town Area",
            lat: 33.595,
            lng: 130.413,
          },
        ],
      },
    },
    { city: "Fukuoka" },
    "这次旅行我想要特别一点",
  );

  const sectionsPart = message.parts.find((part) => part.type === "trip-answer-sections");
  expect(sectionsPart?.type).toBe("trip-answer-sections");
  const first = sectionsPart?.type === "trip-answer-sections" ? sectionsPart.sections[0] : undefined;
  expect(first?.tables?.[0]?.caption).toBe("地点怎么选");
  expect(first?.images?.[0]?.url).toBe("https://example.com/hakata-old-town.jpg");
  expect(first?.card_ids).toEqual(["card-1"]);
  expect(first?.pin_ids).toEqual(["card-1"]);
});

test("itinerary plan text is shown before generic recommendation copy", () => {
  const message = buildAssistantMessageFromPlan(
    {
      narrative_answer: "旧的泛推荐文案不应该盖过逐日行程。",
      itinerary_plan: {
        title: "福冈 2 天自由行",
        summary: "按预算和路线做轻量安排。",
        days: [
          {
            day: 1,
            title: "第1天：市区轻松游",
            time_blocks: [
              {
                title: "上午：大濠公园",
                place_ids: ["card-1"],
                route_note: "先从市区公园开始。",
                budget_note: "免费为主。",
                why: "低成本、节奏轻。",
                alternatives: ["雨天改室内博物馆"],
              },
            ],
          },
          {
            day: 2,
            title: "第2天：海边与街区",
            time_blocks: [
              {
                title: "下午：百道海滨",
                place_ids: ["card-2"],
                route_note: "傍晚顺路去福冈塔。",
                budget_note: "交通和观景台另算。",
                why: "路线集中。",
                alternatives: [],
              },
            ],
          },
        ],
      },
      display_cards: [
        {
          id: "card-1",
          title: "大濠公园",
          category: "自然与摄影",
          subcategory: "公园",
          display_reason: "适合低预算散步。",
          lat: 33.586,
          lng: 130.376,
        },
      ],
      map_view: { pins: [] },
      resolved_intent: { answer_mode: "itinerary", category: "本地体验" },
    },
    { city: "Fukuoka" },
    "福冈2天自由行，预算1000",
  );

  const textPart = message.parts.find((part) => part.type === "text");
  const text = textPart?.type === "text" ? textPart.text : "";
  expect(text).toContain("福冈 2 天自由行");
  expect(text).toContain("第1天：市区轻松游");
  expect(text).toContain("上午：大濠公园");
  expect(text).toContain("先从市区公园开始。");
  expect(text).not.toContain("免费为主。");
  expect(text).not.toContain("低成本、节奏轻。");
  expect(text).not.toContain("可补充信息：");
  expect(text).not.toContain("旧的泛推荐文案");
});

test("assistant message exposes typed hotel and flight offer parts", () => {
  const message = buildAssistantMessageFromPlan(
    {
      narrative_answer: "我先把酒店和航班作为可比较的 offer 给你。",
      hotel_offers: [
        {
          id: "hotel-1",
          title: "Hotel Okura Fukuoka",
          price: "$140",
          rating: 4.4,
          address: "Hakata, Fukuoka",
          display_reason: "位置适合第一次住福冈，价格也有供应商参考。",
        },
      ],
      flight_offers: [
        {
          id: "flight-1",
          title: "HND -> FUK",
          price: "$180",
          duration: "2h",
          display_reason: "直飞时间短，适合作为东京出发的基准选择。",
        },
      ],
      display_cards: [],
      map_view: { pins: [], status: "needs_coordinates" },
      resolved_intent: { category: "住宿" },
    },
    { city: "Fukuoka" },
    "福冈酒店和航班推荐",
  );

  const hotelsPart = message.parts.find((part) => part.type === "trip-hotels");
  const flightsPart = message.parts.find((part) => part.type === "trip-flights");
  expect(hotelsPart?.type).toBe("trip-hotels");
  expect(hotelsPart?.type === "trip-hotels" ? hotelsPart.offers[0].title : "").toBe("Hotel Okura Fukuoka");
  expect(flightsPart?.type).toBe("trip-flights");
  expect(flightsPart?.type === "trip-flights" ? flightsPart.offers[0].title : "").toBe("HND -> FUK");
});

test("initial right panel stays calm until places are available", async ({ page }) => {
  await page.goto("/");

  const map = page.getByTestId("trip-map-panel");
  await expect(map).toBeVisible();
  await expect(page.getByTestId("empty-map-placeholder")).toBeVisible();
  await expect(map).not.toContainText("0 places mapped");
  await expect(page.getByTestId("map-callout")).toHaveCount(0);
});

test("mobile iOS starter panel keeps onboarding copy short", async ({ page }) => {
  await page.setViewportSize({ width: 430, height: 932 });
  await page.goto("/");

  const starter = page.getByTestId("starter-panel");
  await expect(starter).toBeVisible();
  const visibleText = await starter.evaluate((element) => (element as HTMLElement).innerText.trim());
  expect(visibleText).not.toContain("Where / When / Who / Budget / Preferences");
  const textLength = visibleText.length;
  expect(textLength).toBeLessThanOrEqual(60);
});

test("pressing Enter in the composer sends the travel question", async ({ page }) => {
  let requestSeen = false;
  await page.route("**/api/travel/chat", async (route) => {
    const payload = JSON.parse(route.request().postData() ?? "{}");
    requestSeen = payload.messages.at(-1).content === "福冈有什么好玩的?";
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: tripResponse }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByPlaceholder("Ask anything").press("Enter");

  await expect(page.getByTestId("trip-card-card-1")).toBeVisible();
  expect(requestSeen).toBe(true);
});

test("answer-only questions can render without destination cards or map pins", async ({ page }) => {
  await page.route("**/api/travel/chat", async (route) => {
    const payload = JSON.parse(route.request().postData() ?? "{}");
    expect(payload.messages.at(-1).content).toBe("河豚是什么，为什么危险？");
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        message: {
          id: "assistant-answer-only",
          role: "assistant",
          parts: [
            {
              type: "text",
              text: "河豚这个问题不需要先选地点；我先按知识问答处理，不强行生成地图或门店推荐。",
            },
            {
              type: "trip-header",
              title: "Mira",
              subtitle: "识境",
              chips: [
                { id: "Where", label: "Where", value: "" },
                { id: "When", label: "When", value: "" },
                { id: "Who", label: "Who", value: "" },
                { id: "Budget", label: "Budget", value: "" },
                { id: "Preferences", label: "Preferences", value: "" },
              ],
              trip_count: 0,
            },
            { type: "trip-cards", cards: [] },
            { type: "trip-map", map: { pins: [], status: "answer_only" } },
            { type: "runtime-warnings", warnings: [] },
          ],
        },
      }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("河豚是什么，为什么危险？");
  await page.getByPlaceholder("Ask anything").press("Enter");

  await expect(page.getByText("不需要先选地点")).toBeVisible();
  await expect(page.getByTestId("trip-map-panel")).toHaveCount(0);
  await expect(page.locator("[data-testid^='trip-card-']")).toHaveCount(0);
});

test("onsen questions set the current scope instead of inheriting food", async ({ page }) => {
  let contextSeen: Record<string, unknown> | undefined;
  await page.route("**/api/travel/chat", async (route) => {
    const payload = JSON.parse(route.request().postData() ?? "{}");
    contextSeen = payload.context;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: tripResponse }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("别府哪里泡温泉比较好?");
  await page.getByPlaceholder("Ask anything").press("Enter");

  await expect(page.getByTestId("trip-card-card-1")).toBeVisible();
  expect(contextSeen?.city).toBe("Beppu");
  expect(contextSeen?.preferences).toEqual([]);
});

test("Shift+Enter keeps a new line without sending", async ({ page }) => {
  let requests = 0;
  await page.route("**/api/travel/chat", async (route) => {
    requests += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: tripResponse }),
    });
  });

  await page.goto("/");
  const composer = page.getByPlaceholder("Ask anything");
  await composer.fill("福冈");
  await composer.press("Shift+Enter");
  await composer.pressSequentially("有什么好玩的?");

  await expect(composer).toHaveValue("福冈\n有什么好玩的?");
  expect(requests).toBe(0);
});

test("web recommendation chat renders cards first with a fixed right map", async ({ page }) => {
  await page.route("**/api/travel/chat", async (route) => {
    const payload = JSON.parse(route.request().postData() ?? "{}");
    expect(payload.messages.at(-1).content).toBe("福冈有什么好玩的?");
    expect(payload.context.city).toBe("Fukuoka");

    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: tripResponse }),
    });
  });

  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Mira" })).toBeVisible();
  await expect(page.getByText("识境")).toBeVisible();
  await expect(page.getByPlaceholder("Ask anything")).toBeVisible();

  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByText("福冈好玩的地方建议先按海边")).toBeVisible();
  await expect(page.getByTestId("trip-card-card-1")).toBeVisible();
  await expect(page.getByTestId("trip-card-card-2")).toBeVisible();
  await expect(page.getByTestId("trip-card-card-1")).toContainText("Momochihama Beach");
  await expect(page.getByTestId("trip-card-card-2")).toContainText("Fukuoka Tower");
  await expect(page.getByText("景点活动").first()).toBeVisible();
  await expect(page.getByText("拉面")).toHaveCount(0);

  const board = page.getByTestId("trip-board");
  const map = page.getByTestId("trip-map-panel");
  await expect(board).toBeVisible();
  await expect(map).toBeVisible();

  const boardBox = await board.boundingBox();
  const mapBox = await map.boundingBox();
  expect(boardBox).not.toBeNull();
  expect(mapBox).not.toBeNull();
  expect(mapBox!.x).toBeGreaterThan(boardBox!.x + boardBox!.width * 0.48);

  await page.getByTestId("trip-card-card-2").click();
  await expect(page.getByTestId("map-inline-popup")).toContainText("Fukuoka Tower");
  await expect(page.getByTestId("map-callout")).toHaveCount(0);
});

test("structured answer sections render as cards instead of a rich markdown bubble", async ({ page }) => {
  const structuredResponse = structuredClone(tripResponse);
  structuredResponse.parts.splice(1, 0, {
    type: "trip-answer-sections",
    sections: [
      {
        id: "how-to-choose",
        title: "怎么选",
        body: "晴天优先海边，雨天优先室内观景或街区。",
        bullets: ["海边适合慢节奏散步", "街区适合半天灵活安排"],
        tables: [
          {
            caption: "天气选择",
            columns: ["情况", "选择"],
            rows: [["晴天", "海边"]],
          },
        ],
        images: [
          {
            url: "https://example.com/section-photo.jpg",
            caption: "海边参考",
            source: "serper_images",
          },
        ],
      },
      {
        id: "where-to-go",
        title: "去哪儿",
        body: "先看百道海滨和福冈塔这类容易落地的选择。",
        bullets: ["Momochihama Beach", "Fukuoka Tower"],
      },
      {
        id: "map-order",
        title: "怎么排/地图",
        body: "把同一区域串在一起，减少折返。",
        bullets: ["下午去海边", "傍晚接福冈塔"],
      },
    ],
  });
  const textPart = structuredResponse.parts.find((part) => part.type === "text");
  if (textPart?.type === "text") {
    textPart.text = "晴天优先海边和高处视野，雨天选室内街区。";
  }

  await page.route("**/api/travel/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: structuredResponse }),
    });
  });
  await page.route("**/api/travel/chat/jobs", async (route) => {
    const payload = JSON.parse(route.request().postData() ?? "{}");
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "companion-mobile-job-1",
        status: "running",
        query: payload.messages.at(-1).content,
        context: payload.context ?? {},
      }),
    });
  });
  await page.route("**/api/travel/chat/jobs/companion-mobile-job-1", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "companion-mobile-job-1",
        status: "completed",
        message: structuredResponse,
      }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByTestId("trip-answer-sections")).toBeVisible();
  await expect(page.getByTestId("trip-answer-section-how-to-choose")).toContainText("怎么选");
  await expect(page.getByTestId("trip-answer-section-how-to-choose-tables")).toContainText("天气选择");
  await expect(page.getByTestId("trip-answer-section-how-to-choose-images").locator("img")).toHaveAttribute(
    "src",
    "https://example.com/section-photo.jpg",
  );
  await expect(page.getByTestId("trip-answer-section-where-to-go")).toContainText("Momochihama Beach");
  await expect(page.getByTestId("trip-answer-sections")).not.toContainText("Answer");
  await expect(page.getByText("## 怎么选")).toHaveCount(0);
  await expect(page.getByTestId("trip-card-card-1")).toBeVisible();
  await expect(page.getByTestId("trip-map-panel")).toBeVisible();
});

test("mobile iOS layout hides empty precision controls and keeps answer cards quiet", async ({ page }) => {
  await page.setViewportSize({ width: 430, height: 932 });
  const structuredResponse = structuredClone(tripResponse);
  structuredResponse.parts.splice(1, 0, {
    type: "trip-answer-sections",
    sections: [
      {
        id: "how-to-choose",
        title: "怎么选",
        body: "晴天选海边和高处视野，雨天选室内街区。",
        bullets: ["想轻松：百道海滨 + 福冈塔"],
      },
    ],
  });

  await page.route("**/api/travel/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: structuredResponse }),
    });
  });
  await page.route("**/api/travel/chat/jobs", async (route) => {
    const payload = JSON.parse(route.request().postData() ?? "{}");
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "companion-mobile-layout-job-1",
        status: "running",
        query: payload.messages.at(-1).content,
        context: payload.context ?? {},
      }),
    });
  });
  await page.route("**/api/travel/chat/jobs/companion-mobile-layout-job-1", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "companion-mobile-layout-job-1",
        status: "completed",
        message: structuredResponse,
      }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByPlaceholder("Ask anything").press("Enter");

  await expect(page.getByTestId("trip-answer-sections")).toBeVisible();
  await expect(page.getByRole("button", { name: "When" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Who" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Budget" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: /Mira/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /Trip\s+0/ })).toHaveCount(0);
  await expect(page.getByText("Answer").first()).toBeHidden();
  const fontFamily = await page.locator("body").evaluate((element) => getComputedStyle(element).fontFamily);
  expect(fontFamily).toContain("-apple-system");
  const headerBox = await page.locator("header").boundingBox();
  expect(headerBox?.height ?? 999).toBeLessThanOrEqual(96);
});

test("mobile iOS form controls use 16px text to avoid WebKit focus zoom", async ({ page }) => {
  await page.setViewportSize({ width: 430, height: 932 });
  await page.goto("/");

  const composerFontSize = await page
    .getByPlaceholder("Ask anything")
    .evaluate((element) => Number.parseFloat(getComputedStyle(element).fontSize));
  expect(composerFontSize).toBeGreaterThanOrEqual(16);
});

test("image carousel stays attached to the selected recommendation", async ({ page }) => {
  await page.route("**/api/travel/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: tripResponse }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByRole("button", { name: "发送" }).click();

  const firstImage = page.getByTestId("trip-card-card-1").locator("img");
  await expect(firstImage).toHaveAttribute("src", /photo-1500530855697/);

  await page.getByTestId("image-next-card-1").click();
  await expect(firstImage).toHaveAttribute("src", /photo-1507525428034/);

  const secondImage = page.getByTestId("trip-card-card-2").locator("img");
  await expect(secondImage).toHaveAttribute("src", /photo-1494526585095/);
});

test("provider runtime failures are not shown as travel advice", async ({ page }) => {
  await page.route("**/api/travel/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        message: {
          ...tripResponse,
          parts: [
            ...tripResponse.parts,
            {
              type: "runtime-warnings",
              warnings: [
                "Google Places 解析已跳过：HTTP 429 - Quota exceeded",
                "critic 模型调用失败：HTTP 502",
                "formatter 模型调用失败：HTTP 502",
              ],
            },
          ],
        },
      }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByTestId("trip-card-card-1")).toBeVisible();
  await expect(page.getByText("Google Places 解析已跳过")).toHaveCount(0);
  await expect(page.getByText("critic 模型调用失败")).toHaveCount(0);
  await expect(page.getByText("formatter 模型调用失败")).toHaveCount(0);
  await expect(page.getByText("HTTP 502")).toHaveCount(0);
});

test("broken or missing place images are hidden without placeholder copy", async ({ page }) => {
  const brokenResponse = structuredClone(tripResponse);
  const cardsPart = brokenResponse.parts.find((part) => part.type === "trip-cards");
  if (cardsPart?.type === "trip-cards") {
    cardsPart.cards[0].image_urls = ["https://example.com/broken-place-photo.jpg"];
    cardsPart.cards[1].image_urls = [];
    cardsPart.cards[1].image_url = "";
  }

  await page.route("https://example.com/broken-place-photo.jpg", async (route) => {
    await route.abort();
  });
  await page.route("**/api/travel/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: brokenResponse }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByRole("button", { name: "发送" }).click();

  const firstCard = page.getByTestId("trip-card-card-1");
  await expect(firstCard).toBeVisible();
  await expect(firstCard).not.toContainText("No verified place photo");
  await expect(firstCard.locator("img")).toHaveCount(0);

  const secondCard = page.getByTestId("trip-card-card-2");
  await expect(secondCard).not.toContainText("No verified place photo");
  await expect(secondCard.locator("img")).toHaveCount(0);
});

test("generic API placeholder copy is replaced with a recommendation reason", async ({ page }) => {
  const genericResponse = structuredClone(tripResponse);
  const cardsPart = genericResponse.parts.find((part) => part.type === "trip-cards");
  if (cardsPart?.type === "trip-cards") {
    cardsPart.cards[0].description = "API 候选，需要用户确认。";
    cardsPart.cards[0].reason = "API 候选，需要用户确认。";
  }

  await page.route("**/api/travel/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: genericResponse }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByRole("button", { name: "发送" }).click();

  const firstCard = page.getByTestId("trip-card-card-1");
  await expect(firstCard).toBeVisible();
  await expect(firstCard).not.toContainText("API 候选");
  await expect(firstCard).not.toContainText("需要用户确认");
  await expect(firstCard).toContainText("推荐理由");
  await expect(firstCard).toContainText("4.3");
});

test("diagnostic match reasons stay out of cards and map previews", async ({ page }) => {
  const diagnosticResponse = structuredClone(tripResponse);
  const cardsPart = diagnosticResponse.parts.find((part) => part.type === "trip-cards");
  if (cardsPart?.type === "trip-cards") {
    cardsPart.cards[0].display_reason = "评分高、靠近海边，适合把散步和福冈塔顺路安排在一起。";
    cardsPart.cards[0].match_reason = "命中用户核心目标：河豚。";
    cardsPart.cards[1].display_reason = "傍晚视野更好，适合想看城市和海岸线的人。";
    cardsPart.cards[1].match_reason = "API候选，需要用户确认。";
  }

  await page.route("**/api/travel/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: diagnosticResponse }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈去哪吃河豚?");
  await page.getByRole("button", { name: "发送" }).click();

  const firstCard = page.getByTestId("trip-card-card-1");
  await expect(firstCard).toContainText("评分高、靠近海边");
  await expect(page.getByText("命中用户核心目标")).toHaveCount(0);
  await expect(page.getByText("API候选")).toHaveCount(0);
  await expect(page.getByText("需要用户确认")).toHaveCount(0);

  await page.getByTestId("trip-card-card-2").hover();
  await expect(page.getByTestId("map-inline-popup")).toContainText("傍晚视野更好");
  await expect(page.getByTestId("map-callout")).toHaveCount(0);
  await expect(page.getByText("命中用户核心目标")).toHaveCount(0);
});

test("hovering and clicking recommendation cards keeps the map preview above map layers", async ({ page }) => {
  await page.route("**/api/travel/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: tripResponse }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByRole("button", { name: "发送" }).click();

  await page.getByTestId("trip-card-card-2").hover();
  await expect(page.getByTestId("map-inline-popup")).toContainText("Fukuoka Tower");
  await expect(page.getByTestId("map-inline-popup")).toContainText("天气好时看城市和海岸线");
  await page.getByTestId("trip-map-panel").hover({ position: { x: 60, y: 120 } });
  await page.waitForTimeout(550);
  await expect(page.getByTestId("map-inline-popup")).toContainText("Fukuoka Tower");
  expect(await zIndexOf(page, "[data-testid='map-inline-popup']")).toBeGreaterThan(await maxMapLayerZIndex(page));
  const mapPopup = page.locator(".photo-agent-leaflet-popup, .photo-agent-mapbox-popup");
  await expect(mapPopup).toContainText("Fukuoka Tower");
  await expect(mapPopup.getByRole("link")).toHaveCount(0);
  await expect(page.getByTestId("map-callout")).toHaveCount(0);
  await expect(page.locator(".photo-agent-leaflet-popup")).toHaveCount(0);

  await page.getByTestId("trip-card-card-1").click();
  await expect(page.getByTestId("map-inline-popup")).toContainText("Momochihama Beach");
  await expect(page.getByTestId("map-inline-popup")).toContainText("适合散步");
  await expect(page.getByTestId("map-callout")).toHaveCount(0);
});

test("hover preview does not recreate leaflet markers or resize them", async ({ page }) => {
  await page.route("**/api/travel/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: tripResponse }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByRole("button", { name: "发送" }).click();

  const markers = page.locator(".leaflet-marker-icon");
  await expect(markers.first()).toBeVisible();
  const firstMarker = markers.nth(0);
  const secondMarker = markers.nth(1);
  await firstMarker.evaluate((element) => element.setAttribute("data-sticky-marker", "same-node"));
  const beforeHoverWidth = Math.round((await secondMarker.boundingBox())?.width ?? 0);

  await page.getByTestId("trip-card-card-2").hover();
  await page.waitForTimeout(500);

  await expect(firstMarker).toHaveAttribute("data-sticky-marker", "same-node");
  const afterHoverWidth = Math.round((await secondMarker.boundingBox())?.width ?? 0);
  expect(afterHoverWidth).toBe(beforeHoverWidth);
  const secondMarkerHtml = await secondMarker.innerHTML();
  expect(secondMarkerHtml).not.toContain("width:38px");
  expect(secondMarkerHtml).not.toContain("height:38px");
  await expect(page.getByTestId("map-inline-popup")).toContainText("Fukuoka Tower");
  await expect(page.getByTestId("map-callout")).toHaveCount(0);
});

test("hover preview preserves the user's current map zoom", async ({ page }) => {
  await page.route("**/api/travel/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: tripResponse }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.locator(".leaflet-container")).toBeVisible();

  await page.locator(".leaflet-control-zoom-in").click();
  await page.locator(".leaflet-control-zoom-in").click();
  await page.waitForTimeout(350);
  const zoomAfterManualChange = await visibleLeafletZoom(page);
  expect(zoomAfterManualChange).toBeGreaterThan(0);

  await page.getByTestId("trip-card-card-2").hover();
  await page.waitForTimeout(650);
  await expect(page.getByTestId("map-inline-popup")).toContainText("Fukuoka Tower");
  await expect(page.getByTestId("map-callout")).toHaveCount(0);
  expect(await visibleLeafletZoom(page)).toBe(zoomAfterManualChange);
});

test("configured UI renders a draggable Mapbox tile map and keeps map exits", async ({ page }) => {
  let requestedGoogleMaps = false;
  await page.route("https://maps.googleapis.com/maps/api/js**", async (route) => {
    requestedGoogleMaps = true;
    await route.abort();
  });
  await page.route("**/api/travel/chat", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ message: tripResponse }),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的?");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByTestId("leaflet-map")).toBeVisible();
  await expect(page.locator('[data-leaflet-ready="true"]')).toBeVisible();
  await expect(page.locator(".leaflet-container")).toBeVisible();
  await expect(page.getByTestId("trip-card-card-1").getByRole("link", { name: /Mapbox/ })).toBeVisible();
  await expect(page.getByTestId("trip-card-card-1").getByRole("link", { name: /Google Maps/ })).toBeVisible();
  await expect(page.getByTestId("map-callout")).toHaveCount(0);

  await page.locator(".leaflet-marker-icon").nth(1).hover();
  await expect(page.locator(".photo-agent-mapbox-popup")).toContainText("Fukuoka Tower");
  await page.waitForTimeout(550);
  await expect(page.locator(".photo-agent-mapbox-popup")).toContainText("Fukuoka Tower");
  await expect(page.locator(".photo-agent-mapbox-popup img")).toBeVisible();
  await expect(page.locator(".photo-agent-mapbox-popup").getByRole("link")).toHaveCount(0);
  await expect(page.locator(".photo-agent-leaflet-popup")).toHaveCount(0);
  expect(requestedGoogleMaps).toBe(false);
});

test("visual discovery page analyzes a single photo without any text prompt", async ({ page }) => {
  let requestBody: Record<string, unknown> | null = null;
  await page.route("**/v1/visual/discover", async (route) => {
    requestBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        session_id: "snap_visual_story",
        what_it_is: "Eiffel Tower",
        why_it_matters: "它是巴黎和现代铁构工程的象征。",
        why_popular_or_overhyped: "当前没有足够证据判断热度。",
        one_line_answer:
          "这是埃菲尔铁塔；它有意思的地方不只是地标本身，而是工业工程、巴黎城市想象和旅行记忆叠在一起。",
        deep_cards: [
          {
            title: "识别",
            body: "这很可能是巴黎的埃菲尔铁塔。开放式钢铁桁架、塔形轮廓和城市天际线关系都指向这个现代工程地标。",
            supporting_points: ["高耸铁构塔身", "开放式钢铁桁架", "巴黎城市地标"],
            next_action: "如果要完全确认，可以用地图或周边街景核对拍摄点。",
            sections: [
              {
                title: "主体身份",
                body: "巴黎的埃菲尔铁塔，现代铁构工程地标。",
                bullets: ["城市地标", "观景塔"],
                chips: ["Paris"],
              },
              {
                title: "地点/类型",
                body: "法国巴黎的地标建筑。",
                bullets: [],
                chips: ["landmark"],
              },
              {
                title: "核心特征",
                body: "高耸塔身和开放式钢铁桁架最醒目。",
                bullets: ["高耸铁构塔身", "开放式钢铁桁架"],
                chips: [],
              },
            ],
          },
          {
            title: "看点",
            body: "它值得看的地方不是“巴黎打卡”四个字，而是一个原本为世界博览会建造的工程结构，后来变成城市情感和现代审美的符号。",
            supporting_points: ["世界博览会", "现代工程美学", "城市记忆"],
            next_action: "可以继续追问它和巴黎城市天际线、博览会历史的关系。",
            sections: [
              {
                title: "导游视角",
                body: "先把它当作巴黎城市天际线的入口来读。",
                bullets: ["适合从远景理解城市尺度"],
                chips: ["guide"],
              },
              {
                title: "历史视角",
                body: "<b>世界博览会</b>让这座铁构建筑从临时工程变成巴黎记忆。",
                bullets: ["1889 年世界博览会", "现代工程进入城市景观"],
                chips: ["Paris", "1889"],
              },
              {
                title: "文化视角",
                body: "它常被当成抵达巴黎的视觉确认。",
                bullets: [],
                chips: ["城市记忆"],
              },
              {
                title: "风格视角",
                body: "开放式钢铁桁架把巨大尺度处理得轻盈。",
                bullets: [],
                chips: ["铁构", "天际线"],
              },
            ],
          },
          {
            title: "线索",
            body: "先看钢铁结构如何把重量变得轻盈，再看塔身和周边建筑尺度的反差。",
            supporting_points: ["铁构线条", "尺度反差", "观景视线"],
            next_action: "日落前后用远景保留城市层次，比只拍塔身更有故事。",
            sections: [
              {
                title: "画面线索",
                body: "开放式铁构和高耸塔身是最直接的识别线索。",
                bullets: ["高耸塔身", "铁构线条"],
                chips: [],
              },
              {
                title: "判断依据",
                body: "塔身轮廓、钢铁结构和城市地标形象相互吻合。",
                bullets: ["塔形轮廓", "钢铁结构"],
                chips: [],
              },
              {
                title: "继续探索",
                body: "可以找附近桥梁、广场或高处视角继续观察。",
                bullets: [],
                chips: ["怎么拍"],
              },
            ],
          },
        ],
        story_title: "铁塔把城市的天际线变成了记忆",
        narrative:
          "这张照片可以联想到埃菲尔铁塔：它不只是一个观景点，也是工业时代、城市审美和旅行想象叠在一起的符号。",
        visible_clues: [
          {
            clue: "高耸铁构塔身",
            interpretation: "与巴黎埃菲尔铁塔的开放式钢铁桁架高度吻合",
            confidence: 0.86,
          },
        ],
        cultural_hypotheses: [
          {
            name: "Eiffel Tower",
            entity_type: "landmark",
            region: "Paris, France",
            rationale: "塔身轮廓、钢铁结构和城市地标形象相互吻合",
            confidence: 0.86,
            evidence_support: ["开放式铁构", "塔形轮廓"],
            evidence_against: ["单张图仍需排除复制品或模型"],
          },
        ],
        meaning_layers: {
          visual: "铁构、塔形和尺度形成第一层识别线索",
          cultural_history: "它关联巴黎、世界博览会和现代工程美学",
          emotional: "它常被当作抵达巴黎的视觉确认",
          practical: "可以继续查看附近观景点和拍摄角度",
        },
        confidence_notes: ["单张图片识别为高置信，但仍建议用地图或来源确认"],
        followup_questions: ["附近哪里适合拍铁塔全景？"],
        perspective_cards: [
          {
            perspective: "guide",
            title: "导游视角：Eiffel Tower",
            summary: "这是一个非常清晰的城市地标，可以先从它和城市天际线的关系理解。",
            reasons: ["开放式铁构", "塔形轮廓"],
            confidence: 0.86,
            followup_prompt: "附近哪里适合拍铁塔全景？",
          },
          {
            perspective: "history",
            title: "历史视角：Eiffel Tower",
            summary: "它关联世界博览会、现代工程和巴黎的城市形象。",
            reasons: ["工业时代工程美学"],
            confidence: 0.82,
          },
        ],
        visual_memory_item: {
          memory_id: "visual_eiffel",
          title: "Eiffel Tower",
          entity_type: "landmark",
          region_hint: "Paris, France",
          status: "discovered",
        },
        audio_script: "铁塔把城市的天际线变成了记忆。它关联巴黎和现代工程美学。",
        visual_workflow_summary: {
          provider: "gemini",
          model: "gemini-3.1-pro-preview",
          selected_perspectives: ["guide", "history"],
          knowledge_used: true,
          confidence: 0.86,
          uncertainty: ["单张图仍需排除复制品或模型"],
        },
        visual_matches: [
          {
            provider: "serpapi_google_lens",
            title: "Google Lens candidate unavailable for private upload",
            source: "Google Lens",
            match_type: "requires_public_image_url",
            confidence: 0,
          },
        ],
        knowledge_cards: [
          {
            source_type: "exa",
            title: "External knowledge pending",
            snippet: "正式运行时由 Exa 补充背景。",
            score: 0,
            ad_risk: 0,
          },
        ],
        api_sources_used: [
          {
            provider: "serpapi_google_lens",
            name: "SerpAPI Google Lens",
            source_type: "commercial_api",
            format: "Google Lens JSON",
            commercial: true,
            status: "configured",
            url: "https://serpapi.com/google-lens-api",
          },
        ],
        source_breakdown: { commercial_api: 1 },
        thinking_steps: [
          {
            step_id: "visual.pipeline",
            framework: "haystack",
            title: "Haystack Pipeline",
            summary: "Google Lens 候选、VLM 解释、Exa 知识和故事生成按 Pipeline 节点展示。",
            status: "completed",
            metadata: {},
          },
        ],
        cache: { provider: "redis", key: "visual:test", hit: false, ttl_seconds: 900 },
      }),
    });
  });

  await page.goto("/visual");
  await expect(page.getByRole("heading", { name: "Mira" })).toBeVisible();
  await expect(page.getByText("识境")).toBeVisible();
  await expect(page.getByTestId("visual-photo-card")).toBeVisible();
  await page
    .getByTestId("visual-file-input")
    .setInputFiles({
      name: "eiffel-tower.png",
      mimeType: "image/png",
      buffer: Buffer.from("fake-image"),
    });
  await page.getByTestId("visual-submit").click();

  const publicAnswer = page.getByTestId("visual-public-answer");
  await expect(publicAnswer).toContainText("这是埃菲尔铁塔");
  await expect(page.getByTestId("visual-deep-cards")).toContainText("识别");
  await expect(page.getByTestId("visual-deep-cards")).toContainText("看点");
  await expect(page.getByTestId("visual-deep-cards")).toContainText("线索");
  await expect(page.getByTestId("visual-deep-cards")).toContainText("主体身份");
  await expect(page.getByTestId("visual-deep-cards")).toContainText("导游视角");
  await expect(page.getByTestId("visual-deep-cards")).toContainText("历史视角");
  await expect(page.getByTestId("visual-deep-cards")).toContainText("文化视角");
  await expect(page.getByTestId("visual-deep-cards")).toContainText("风格视角");
  await expect(page.getByTestId("visual-deep-cards")).toContainText("画面线索");
  await expect(page.getByTestId("visual-deep-cards")).toContainText("判断依据");
  await expect(page.getByTestId("visual-deep-cards")).toContainText("继续探索");
  await expect(page.getByTestId("visual-framework-card-识别")).toBeVisible();
  await expect(page.getByTestId("visual-framework-card-看点")).toBeVisible();
  await expect(page.getByTestId("visual-framework-card-线索")).toBeVisible();
  await expect(page.getByTestId("visual-section-导游视角")).toContainText(
    "先把它当作巴黎城市天际线的入口来读。",
  );
  await expect(page.getByTestId("visual-section-历史视角")).toContainText(
    "世界博览会",
  );
  await expect(page.getByTestId("visual-deep-cards")).toContainText("世界博览会");
  await expect(page.getByTestId("visual-deep-cards")).not.toContainText("<b>");
  await expect(publicAnswer).not.toContainText("候选");
  await expect(publicAnswer).not.toContainText("置信度");
  await expect(publicAnswer).not.toContainText("不确定");
  await expect(publicAnswer).not.toContainText("模型");
  await expect(page.getByTestId("visual-debug-details")).toBeHidden();
  await page.getByTestId("visual-debug-toggle").click();
  await expect(page.getByTestId("visual-debug-details")).toBeVisible();
  await expect(page.getByTestId("visual-debug-details")).toContainText("高耸铁构塔身");
  await expect(page.getByTestId("visual-debug-details")).toContainText("86%");
  await expect(page.getByTestId("visual-debug-details")).toContainText("单张图片识别为高置信");
  await expect(page.getByTestId("visual-memory")).toContainText("Paris, France");
  await expect(page.getByTestId("visual-audio")).toBeVisible();
  await expect(page.getByTestId("visual-sources")).toContainText("SerpAPI Google Lens");
  expect(requestBody?.user_context_text).toBe("");
  expect(requestBody?.exploration_focus).toBe("auto");
  expect(Array.isArray(requestBody?.images_base64)).toBe(true);
});

test("visual upload surface swaps the designed icon for the selected photo", async ({ page }) => {
  await page.goto("/visual");

  await expect(page.getByTestId("visual-upload-art")).toBeVisible();
  await expect(page.getByTestId("visual-upload-preview")).toHaveCount(0);

  await page.getByTestId("visual-file-input").setInputFiles({
    name: "quiet-stairs.png",
    mimeType: "image/png",
    buffer: Buffer.from("fake-image"),
  });

  await expect(page.getByTestId("visual-upload-preview")).toBeVisible();
  await expect(page.getByTestId("visual-upload-art")).toHaveCount(0);
  await expect(page.getByTestId("visual-photo-card")).not.toContainText("1 张照片已选择");
});

test("visual desktop keeps the upload surface in a web-sized column", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 990 });
  await page.goto("/visual");

  const dropzoneBox = await page.getByTestId("visual-upload-dropzone").boundingBox();
  const cardBox = await page.getByTestId("visual-photo-card").boundingBox();
  const pageMetrics = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    innerHeight: window.innerHeight,
  }));

  expect(cardBox?.width ?? 0).toBeLessThanOrEqual(760);
  expect(dropzoneBox?.height ?? 9999).toBeLessThanOrEqual(460);
  expect(pageMetrics.scrollHeight).toBeGreaterThan(pageMetrics.innerHeight);
});

test("visual discovery renders multimodal section tables and images safely", async ({ page }) => {
  await page.route("**/v1/visual/discover", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        session_id: "snap_multimodal",
        what_it_is: "八坂塔",
        why_it_matters: "它连接京都东山街巷和寺院记忆。",
        why_popular_or_overhyped: "",
        one_line_answer: "这是京都东山区的法观寺八坂塔。",
        deep_cards: [
          {
            title: "识别",
            body: "画面主体是法观寺八坂塔。",
            supporting_points: [],
            next_action: "",
            sections: [
              {
                title: "主体身份",
                body: "法观寺八坂塔。",
                bullets: [],
                chips: ["Kyoto"],
                images: [
                  {
                    url: "https://example.com/yasaka-detail.jpg",
                    caption: "塔身细节",
                    source: "model",
                  },
                ],
              },
            ],
          },
          {
            title: "看点",
            body: "它值得从多个视角理解。",
            supporting_points: [],
            next_action: "",
            sections: [
              {
                title: "视角对比",
                body: "",
                bullets: [],
                chips: [],
                tables: [
                  {
                    caption: "观看方式",
                    columns: ["视角", "看什么"],
                    rows: [
                      ["导游", "坡道尽头的地标"],
                      ["风格", "木构塔身和町屋"],
                    ],
                  },
                ],
              },
            ],
          },
          {
            title: "线索",
            body: "石板坡道与五层塔身相互印证。",
            supporting_points: [],
            next_action: "",
            sections: [],
          },
        ],
        story_title: "塔与街巷",
        narrative: "",
        visible_clues: [],
        cultural_hypotheses: [],
        meaning_layers: {},
        confidence_notes: [],
        followup_questions: [],
        audio_script: "",
        visual_workflow_summary: {
          provider: "deepinfra",
          model: "gpt-5.5",
          selected_perspectives: [],
          knowledge_used: false,
          confidence: 0.8,
          uncertainty: [],
        },
        visual_matches: [],
        knowledge_cards: [],
        api_sources_used: [],
        source_breakdown: {},
        thinking_steps: [],
        cache: { provider: "redis", key: "visual:multi", hit: false, ttl_seconds: 900 },
      }),
    });
  });

  await page.goto("/visual");
  await page
    .getByTestId("visual-file-input")
    .setInputFiles({
      name: "yasaka.png",
      mimeType: "image/png",
      buffer: Buffer.from("fake-image"),
    });
  await page.getByTestId("visual-submit").click();

  await expect(page.getByTestId("visual-section-image-主体身份")).toBeVisible();
  await expect(page.getByTestId("visual-section-image-主体身份").locator("img")).toHaveAttribute(
    "src",
    "https://example.com/yasaka-detail.jpg",
  );
  await expect(page.getByTestId("visual-section-table-视角对比")).toContainText("观看方式");
  await expect(page.getByTestId("visual-section-table-视角对比")).toContainText("坡道尽头的地标");
  await expect(page.getByTestId("visual-deep-cards")).not.toContainText("<table>");
});

test("visual discovery supports single-session image follow-up chat", async ({ page }) => {
  let followupBody: Record<string, unknown> | null = null;
  await page.route("**/v1/visual/discover", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        session_id: "snap_followup",
        what_it_is: "Eiffel Tower",
        why_it_matters: "它是巴黎和现代铁构工程的象征。",
        why_popular_or_overhyped: "",
        one_line_answer: "这是埃菲尔铁塔。",
        deep_cards: [
          { title: "识别", body: "巴黎的埃菲尔铁塔。", supporting_points: [], next_action: "", sections: [] },
          { title: "看点", body: "它关联巴黎城市天际线。", supporting_points: [], next_action: "", sections: [] },
          { title: "线索", body: "开放式铁构是线索。", supporting_points: [], next_action: "", sections: [] },
        ],
        story_title: "铁塔",
        narrative: "",
        visible_clues: [],
        cultural_hypotheses: [],
        meaning_layers: {},
        confidence_notes: [],
        followup_questions: ["附近哪里适合拍铁塔全景？"],
        audio_script: "",
        visual_workflow_summary: {
          provider: "deepinfra",
          model: "gpt-5.5",
          selected_perspectives: [],
          knowledge_used: false,
          confidence: 0.8,
          uncertainty: [],
        },
        visual_matches: [],
        knowledge_cards: [],
        api_sources_used: [],
        source_breakdown: {},
        thinking_steps: [],
        cache: { provider: "redis", key: "visual:followup", hit: false, ttl_seconds: 900 },
      }),
    });
  });
  await page.route("**/v1/visual/followup", async (route) => {
    followupBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        session_id: "snap_followup",
        answer: "可以优先去特罗卡德罗广场，适合把铁塔和城市层次一起拍进去。",
        evidence_cards: [],
        followup_questions: ["日落和夜景哪个更好？"],
      }),
    });
  });

  await page.goto("/visual");
  await page.getByTestId("visual-options-toggle").click();
  await page.getByTestId("visual-context").fill("第一次到巴黎");
  await page.getByTestId("visual-focus-select").selectOption("place");
  await page.getByTestId("visual-interest-input").fill("history viewpoint");
  await page.getByTestId("visual-file-input").setInputFiles({
    name: "eiffel.png",
    mimeType: "image/png",
    buffer: Buffer.from("fake-image"),
  });
  await page.getByTestId("visual-submit").click();

  await expect(page.getByTestId("visual-followup-form")).toBeVisible();
  await page.getByTestId("visual-followup-input").fill("附近哪里适合拍铁塔全景？");
  await page.getByTestId("visual-followup-submit").click();

  await expect(page.getByTestId("visual-followup-messages")).toContainText("附近哪里适合拍铁塔全景？");
  await expect(page.getByTestId("visual-followup-messages")).toContainText("特罗卡德罗广场");
  expect(followupBody?.session_id).toBe("snap_followup");
  expect(followupBody?.question).toBe("附近哪里适合拍铁塔全景？");
  expect(followupBody?.user_context_text).toBe("第一次到巴黎");
  expect(followupBody?.exploration_focus).toBe("place");
  expect(followupBody?.interest_tags).toEqual(["history", "viewpoint"]);
  expect(Array.isArray(followupBody?.images_base64)).toBe(true);
  expect((followupBody?.previous_result as Record<string, unknown>)?.what_it_is).toBe("Eiffel Tower");
});

test("visual discovery compresses large uploads before sending them to the backend", async ({ page }) => {
  let requestBody: Record<string, unknown> | null = null;
  let requestUrl = "";
  await page.route("**/v1/visual/discover", async (route) => {
    requestUrl = route.request().url();
    requestBody = route.request().postDataJSON() as Record<string, unknown>;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        session_id: "compressed_visual_story",
        what_it_is: "Large upload",
        why_it_matters: "",
        why_popular_or_overhyped: "",
        one_line_answer: "这张大图已经在浏览器端压缩后再上传。",
        deep_cards: [
          { title: "识别", body: "压缩上传测试。", supporting_points: [], next_action: "", sections: [] },
          { title: "看点", body: "压缩上传测试。", supporting_points: [], next_action: "", sections: [] },
          { title: "线索", body: "压缩上传测试。", supporting_points: [], next_action: "", sections: [] },
        ],
        visible_clues: [],
        cultural_hypotheses: [],
        meaning_layers: {},
        confidence_notes: [],
        followup_questions: [],
        perspective_cards: [],
        visual_memory_item: null,
        audio_script: "",
        visual_workflow_summary: {
          provider: "test",
          model: "test",
          selected_perspectives: [],
          knowledge_used: false,
          confidence: 0,
          uncertainty: [],
        },
        visual_matches: [],
        knowledge_cards: [],
        api_sources_used: [],
        source_breakdown: {},
        thinking_steps: [],
        cache: { provider: "none", key: "", hit: false, ttl_seconds: 0 },
      }),
    });
  });

  const oversizedSvg = `<svg xmlns="http://www.w3.org/2000/svg" width="3200" height="2400"><rect width="100%" height="100%" fill="#f7efe3"/><circle cx="1600" cy="1200" r="620" fill="#40798c"/><!--${"x".repeat(2_000_000)}--></svg>`;

  await page.goto("/visual");
  await page.getByTestId("visual-file-input").setInputFiles({
    name: "oversized-landmark.svg",
    mimeType: "image/svg+xml",
    buffer: Buffer.from(oversizedSvg),
  });
  await page.getByTestId("visual-submit").click();

  await expect(page.getByTestId("visual-one-line")).toContainText("压缩");
  const imagePayload = Array.isArray(requestBody?.images_base64)
    ? String(requestBody.images_base64[0] ?? "")
    : "";
  expect(imagePayload.length).toBeGreaterThan(0);
  expect(imagePayload.length).toBeLessThan(300_000);
  expect(requestUrl).toContain("/api-backend/v1/visual/discover");
});

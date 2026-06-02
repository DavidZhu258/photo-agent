import { expect, test } from "@playwright/test";

test.use({
  viewport: { width: 390, height: 844 },
  isMobile: true,
  hasTouch: true,
  userAgent:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1 PhotoAgentShell/1.0",
});

const visualResponse = {
  session_id: "ios_visual_smoke",
  what_it_is: "Fukuoka Tower",
  why_it_matters: "它是福冈海滨城市天际线的代表地标。",
  why_popular_or_overhyped: "真正价值在城市、海边和观景动线的关系。",
  one_line_answer: "这是福冈塔；它把海滨、公园和城市观景连接成一个很容易理解的福冈入口。",
  deep_cards: [
    {
      title: "识别",
      body: "照片主体是福冈塔，属于海滨观景塔和城市地标。",
      supporting_points: ["高耸塔身", "海滨位置"],
      next_action: "可以结合百道海滨和福冈市博物馆一起看。",
      sections: [
        { title: "主体身份", body: "福冈塔，海滨观景地标。", bullets: [], chips: ["Fukuoka"] },
        { title: "地点/类型", body: "福冈百道海滨一带的城市地标。", bullets: [], chips: ["landmark"] },
        { title: "核心特征", body: "高耸塔身、玻璃立面和海滨环境最醒目。", bullets: ["塔身", "海滨"], chips: [] },
      ],
    },
    {
      title: "看点",
      body: "它的看点在于把福冈的城市、海边和观景体验集中到一个地点。",
      supporting_points: ["城市天际线", "海滨散步"],
      next_action: "傍晚前后更适合看海岸线和城市灯光。",
      sections: [
        { title: "导游视角", body: "第一次到福冈，可以把这里作为海滨动线的起点。", bullets: [], chips: [] },
        { title: "历史视角", body: "它体现了福冈现代海滨开发和城市观光形象。", bullets: [], chips: [] },
        { title: "文化视角", body: "这里常被当作福冈轻松、开放、靠海气质的视觉符号。", bullets: [], chips: [] },
        { title: "风格视角", body: "细长塔身和玻璃表皮让它在海边显得轻盈。", bullets: [], chips: [] },
      ],
    },
    {
      title: "线索",
      body: "先看塔身比例，再看它和海滨、公园、街区之间的距离。",
      supporting_points: ["塔身比例", "海滨背景"],
      next_action: "沿海边后退一点拍，可以保留塔和城市环境。",
      sections: [
        { title: "画面线索", body: "塔身轮廓、玻璃外立面和开放海滨环境共同指向福冈塔。", bullets: [], chips: [] },
        { title: "判断依据", body: "地标形态与福冈百道海滨的城市景观相互吻合。", bullets: [], chips: [] },
        { title: "继续探索", body: "可以继续看百道海滨、福冈市博物馆和附近海岸线。", bullets: [], chips: [] },
      ],
    },
  ],
  story_title: "海边的城市入口",
  narrative: "福冈塔把城市天际线和海滨散步连接起来。",
  visible_clues: [
    { clue: "tall tower", interpretation: "高耸塔身符合福冈塔形态。", confidence: 0.86 },
  ],
  cultural_hypotheses: [],
  meaning_layers: {
    visual: "塔身和海滨环境形成第一层识别线索。",
    cultural_history: "关联福冈现代海滨开发。",
  },
  confidence_notes: ["移动端 smoke 使用 mock 结果。"],
  followup_questions: ["附近还可以顺路去哪？"],
  perspective_cards: [],
  visual_memory_item: {
    memory_id: "visual_fukuoka_tower",
    title: "Fukuoka Tower",
    entity_type: "landmark",
    region_hint: "Fukuoka, Japan",
    status: "discovered",
  },
  audio_script: "这是福冈塔，适合从海滨和城市观景关系理解。",
  visual_workflow_summary: {
    provider: "mock",
    model: "ios-shell-test",
    selected_perspectives: ["guide", "style"],
    knowledge_used: true,
    confidence: 0.86,
    uncertainty: [],
  },
  visual_matches: [],
  knowledge_cards: [],
  api_sources_used: [],
  source_breakdown: {},
  thinking_steps: [],
  cache: { provider: "mock", key: "ios-visual", hit: false, ttl_seconds: 0 },
};

const placeMessage = {
  id: "assistant-ios-place",
  role: "assistant",
  parts: [
    {
      type: "text",
      text: "福冈好玩的地方先看海边和城市观景，下面这些地点可以直接放进地图比较。",
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
        { id: "Preferences", label: "Preferences", value: "" },
      ],
      trip_count: 0,
    },
    {
      type: "trip-cards",
      cards: [
        {
          id: "ios-card-1",
          title: "Fukuoka Tower",
          category: "本地体验",
          subcategory: "城市观景",
          display_reason: "适合第一次到福冈时理解海滨和城市天际线。",
          rating: 4.2,
          review_count: 5400,
          address: "2 Chome-3-26 Momochihama, Fukuoka",
          image_url: "https://images.unsplash.com/photo-1500530855697-1",
          image_urls: [
            "https://images.unsplash.com/photo-1500530855697-1",
            "https://images.unsplash.com/photo-1507525428034-2",
            "https://images.unsplash.com/photo-1494526585095-3",
          ],
          lat: 33.593332,
          lng: 130.351432,
          google_maps_uri: "https://www.google.com/maps/search/?api=1&query=Fukuoka%20Tower",
          directions_uri: "https://www.google.com/maps/dir/?api=1&destination=Fukuoka%20Tower",
        },
      ],
    },
    {
      type: "trip-map",
      map: {
        provider: "mapbox",
        mode: "mapbox_gl",
        center: { lat: 33.593332, lng: 130.351432 },
        selected_pin_id: "ios-card-1",
        status: "ready",
        pins: [
          {
            id: "ios-card-1",
            title: "Fukuoka Tower",
            lat: 33.593332,
            lng: 130.351432,
            google_maps_uri: "https://www.google.com/maps/search/?api=1&query=Fukuoka%20Tower",
          },
        ],
      },
    },
    { type: "runtime-warnings", warnings: [] },
  ],
};

const placePlan = {
  summary: "福冈好玩的地方建议先看海边和城市观景。",
  answer_mode: "place_cards",
  resolved_intent: { city: "Fukuoka", category: "本地体验" },
  display_cards: [
    {
      id: "ios-card-1",
      title: "Fukuoka Tower",
      category: "本地体验",
      subcategory: "城市观景",
      display_reason: "适合第一次到福冈时理解海滨和城市天际线。",
      rating: 4.2,
      review_count: 5400,
      address: "2 Chome-3-26 Momochihama, Fukuoka",
      image_url: "https://images.unsplash.com/photo-1500530855697-1",
      image_urls: [
        "https://images.unsplash.com/photo-1500530855697-1",
        "https://images.unsplash.com/photo-1507525428034-2",
        "https://images.unsplash.com/photo-1494526585095-3",
      ],
      lat: 33.593332,
      lng: 130.351432,
      google_maps_uri: "https://www.google.com/maps/search/?api=1&query=Fukuoka%20Tower",
      directions_uri: "https://www.google.com/maps/dir/?api=1&destination=Fukuoka%20Tower",
    },
  ],
  map_view: {
    provider: "mapbox",
    mode: "mapbox_gl",
    center: { lat: 33.593332, lng: 130.351432 },
    selected_pin_id: "ios-card-1",
    status: "ready",
    pins: [
      {
        id: "ios-card-1",
        title: "Fukuoka Tower",
        lat: 33.593332,
        lng: 130.351432,
        google_maps_uri: "https://www.google.com/maps/search/?api=1&query=Fukuoka%20Tower",
      },
    ],
  },
  optional_followups: [],
  data_gaps: [],
  raw_provider_refs: {},
};

function answerOnlyMessage() {
  return {
    id: "assistant-ios-answer-only",
    role: "assistant",
    parts: [
      { type: "text", text: "河豚是需要专业处理的鱼类；这个问题不需要地图，我先解释风险和吃法。" },
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
  };
}

async function routeTravelJob(
  page: import("@playwright/test").Page,
  result: { message?: unknown; response?: unknown },
) {
  await page.route("**/api/travel/chat/jobs", async (route) => {
    const payload = JSON.parse(route.request().postData() ?? "{}");
    const query = payload.messages.at(-1).content;
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "ios-travel-job-1",
        status: "running",
        query,
        context: payload.context ?? {},
      }),
    });
  });
  await page.route("**/api/travel/chat/jobs/ios-travel-job-1", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "ios-travel-job-1",
        status: "completed",
        ...result,
      }),
    });
  });
}

async function expectNoHorizontalOverflow(page: import("@playwright/test").Page) {
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.innerWidth + 2);
}

async function expectNoVerticalOverflow(page: import("@playwright/test").Page) {
  const metrics = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    innerHeight: window.innerHeight,
  }));
  expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.innerHeight + 2);
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/mapbox/tile/**", async (route) => {
    await route.fulfill({
      contentType: "image/svg+xml",
      body:
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#e8efeb"/><path d="M0 140 C70 120 130 170 256 130" stroke="#94c5dd" stroke-width="18" fill="none"/></svg>',
    });
  });
  await page.route("**/api/mapbox/static-map**", async (route) => {
    await route.fulfill({
      contentType: "image/svg+xml",
      body:
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="900"><rect width="1200" height="900" fill="#e8efeb"/><circle cx="600" cy="450" r="28" fill="#0369a1"/></svg>',
    });
  });
});

test("Mira visual page works inside an iPhone-sized shell", async ({ page }) => {
  await page.route("**/v1/visual/discover", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(visualResponse),
    });
  });

  await page.goto("/visual");
  await expect(page.getByRole("heading", { name: "Mira" })).toBeVisible();
  await expect(page.getByText("识境")).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.getByTestId("visual-file-input").setInputFiles({
    name: "fukuoka-tower.png",
    mimeType: "image/png",
    buffer: Buffer.from("fake-image"),
  });
  await page.getByTestId("visual-submit").click();

  await expect(page.getByTestId("visual-one-line")).toContainText("这是福冈塔");
  await expect(page.getByTestId("visual-framework-card-识别")).toBeVisible();
  await expect(page.getByTestId("visual-framework-card-看点")).toBeVisible();
  await expect(page.getByTestId("visual-framework-card-线索")).toBeVisible();
  await expect(page.getByTestId("visual-section-导游视角")).toContainText("第一次到福冈");
  await expect(page.getByTestId("visual-followup-form")).toBeVisible();
  await expect(page.getByTestId("visual-followup-input")).toBeVisible();
  await expect(page.getByTestId("visual-debug-details")).toBeHidden();
  await expectNoHorizontalOverflow(page);
});

test("Mira keeps travel and visual headers aligned in an iPhone shell", async ({ page }) => {
  await page.goto("/");
  const travelHeader = page.getByTestId("mira-app-header");
  await expect(travelHeader).toBeVisible();
  const travelMetrics = await travelHeader.evaluate((element) => {
    const title = element.querySelector("[data-testid='mira-app-title']") as HTMLElement;
    const action = element.querySelector("[data-testid='mira-header-primary-action']") as HTMLElement;
    const icon = element.querySelector("[data-testid='mira-header-icon-action']") as HTMLElement;
    return {
      height: Math.round(element.getBoundingClientRect().height),
      titleSize: window.getComputedStyle(title).fontSize,
      actionHeight: Math.round(action.getBoundingClientRect().height),
      iconHeight: Math.round(icon.getBoundingClientRect().height),
    };
  });

  await page.goto("/visual");
  const visualHeader = page.getByTestId("mira-app-header");
  await expect(visualHeader).toBeVisible();
  const visualMetrics = await visualHeader.evaluate((element) => {
    const title = element.querySelector("[data-testid='mira-app-title']") as HTMLElement;
    const action = element.querySelector("[data-testid='mira-header-primary-action']") as HTMLElement;
    const icon = element.querySelector("[data-testid='mira-header-icon-action']") as HTMLElement;
    return {
      height: Math.round(element.getBoundingClientRect().height),
      titleSize: window.getComputedStyle(title).fontSize,
      actionHeight: Math.round(action.getBoundingClientRect().height),
      iconHeight: Math.round(icon.getBoundingClientRect().height),
    };
  });

  expect(visualMetrics.height).toBe(travelMetrics.height);
  expect(visualMetrics.titleSize).toBe(travelMetrics.titleSize);
  expect(visualMetrics.actionHeight).toBe(travelMetrics.actionHeight);
  expect(visualMetrics.iconHeight).toBe(travelMetrics.iconHeight);
});

test("Mira travel home uses a fixed app shell on iPhone 14 Pro Max", async ({ browser }) => {
  const page = await browser.newPage({
    viewport: { width: 430, height: 932 },
    isMobile: true,
    hasTouch: true,
    userAgent:
      "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1 PhotoAgentShell/1.0",
  });

  await page.goto("/");
  await expect(page.getByTestId("mira-app-header")).toBeVisible();
  await expect(page.getByTestId("starter-panel")).toBeVisible();
  await expect(page.getByPlaceholder("Ask anything")).toBeVisible();
  await expectNoVerticalOverflow(page);

  const shell = await page.locator("main").evaluate((element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return {
      height: Math.round(rect.height),
      overflowY: style.overflowY,
      viewportHeight: window.innerHeight,
    };
  });
  const messageViewport = await page.getByTestId("trip-message-viewport").evaluate((element) => {
    const style = window.getComputedStyle(element);
    return {
      minHeight: style.minHeight,
      overflowY: style.overflowY,
    };
  });

  expect(shell.height).toBe(shell.viewportHeight);
  expect(shell.overflowY).toBe("hidden");
  expect(messageViewport.minHeight).toBe("0px");
  expect(messageViewport.overflowY).toBe("auto");
  await page.close();
});

test("Mira visual starts as a fixed upload surface and scrolls only after an answer", async ({ page }) => {
  await page.route("**/v1/visual/discover", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(visualResponse),
    });
  });

  await page.goto("/visual");
  await expect(page.getByTestId("visual-photo-card")).toBeVisible();
  await expect(page.getByText("拍下你想看懂的东西。")).toHaveCount(0);
  await expect(page.getByText("上传后会在这里显示识别结果")).toHaveCount(0);
  await expectNoVerticalOverflow(page);

  await page.getByTestId("visual-file-input").setInputFiles({
    name: "fukuoka-tower.png",
    mimeType: "image/png",
    buffer: Buffer.from("fake-image"),
  });
  await page.getByTestId("visual-submit").click();

  await expect(page.getByTestId("visual-results-region")).toBeVisible();
  await expect(page.getByTestId("visual-one-line")).toContainText("这是福冈塔");
  const afterAnswer = await page.evaluate(() => ({
    scrollHeight: document.documentElement.scrollHeight,
    innerHeight: window.innerHeight,
  }));
  expect(afterAnswer.scrollHeight).toBeGreaterThan(afterAnswer.innerHeight);
});

test("Mira starts photo-first and reveals optional clues on demand in an iPhone shell", async ({ page }) => {
  await page.goto("/visual");

  await expect(page.getByTestId("visual-photo-card")).toBeVisible();
  await expect(page.getByTestId("visual-upload-icon")).toBeVisible();
  await expect(page.getByTestId("visual-upload-dropzone")).not.toContainText("选择一张照片");
  await expect(page.getByTestId("visual-context")).toBeHidden();
  await expect(page.getByTestId("visual-focus-select")).toBeHidden();
  await expect(page.getByTestId("visual-interest-input")).toBeHidden();

  await page.getByTestId("visual-options-toggle").click();
  await expect(page.getByTestId("visual-context")).toBeVisible();
  await expect(page.getByTestId("visual-focus-select")).toBeVisible();
  await expect(page.getByTestId("visual-interest-input")).toBeVisible();

  const contextFontSize = await page
    .getByTestId("visual-context")
    .evaluate((element) => Number.parseFloat(window.getComputedStyle(element).fontSize));
  expect(contextFontSize).toBeGreaterThanOrEqual(16);
  await expectNoHorizontalOverflow(page);
});

test("Mira keeps upload and result surfaces softly rounded in an iPhone shell", async ({ page }) => {
  await page.route("**/v1/visual/discover", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(visualResponse),
    });
  });

  await page.goto("/visual");
  const uploadRadius = await page
    .getByTestId("visual-upload-dropzone")
    .evaluate((element) => Number.parseFloat(window.getComputedStyle(element).borderRadius));
  expect(uploadRadius).toBeGreaterThanOrEqual(28);

  await page.getByTestId("visual-file-input").setInputFiles({
    name: "fukuoka-tower.png",
    mimeType: "image/png",
    buffer: Buffer.from("fake-image"),
  });
  await page.getByTestId("visual-submit").click();

  const publicRadius = await page
    .getByTestId("visual-public-answer")
    .evaluate((element) => Number.parseFloat(window.getComputedStyle(element).borderRadius));
  const frameworkRadius = await page
    .getByTestId("visual-framework-card-识别")
    .evaluate((element) => Number.parseFloat(window.getComputedStyle(element).borderRadius));
  expect(publicRadius).toBeGreaterThanOrEqual(24);
  expect(frameworkRadius).toBeGreaterThanOrEqual(24);
});

test("Mira travel answer-only questions stay text-only in an iPhone shell", async ({ page }) => {
  await routeTravelJob(page, { message: answerOnlyMessage() });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("河豚是什么，为什么危险？");
  await page.getByPlaceholder("Ask anything").press("Enter");

  await expect(page.getByText("不需要地图")).toBeVisible();
  await expect(page.getByTestId("trip-map-panel")).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
});

test("Mira travel place recommendations render cards and map exits in an iPhone shell", async ({ page }) => {
  await routeTravelJob(page, { message: placeMessage });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的？");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByTestId("trip-card-ios-card-1")).toContainText("Fukuoka Tower");
  await expect(page.getByTestId("trip-card-ios-card-1")).toContainText("适合第一次到福冈");
  await expect(page.getByTestId("trip-map-panel")).toBeHidden();
  await expect(page.getByTestId("trip-card-ios-card-1").getByRole("link", { name: /Google Maps/ })).toBeVisible();
  await expectNoHorizontalOverflow(page);
});

test("Mira travel resumes a background recommendation job after the iPhone page reloads", async ({ page }) => {
  let polls = 0;
  await page.route("**/api/travel/chat/jobs", async (route) => {
    const payload = JSON.parse(route.request().postData() ?? "{}");
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        job_id: "ios-resume-job-1",
        status: "running",
        query: payload.messages.at(-1).content,
        context: payload.context ?? {},
      }),
    });
  });
  await page.route("**/api/travel/chat/jobs/ios-resume-job-1", async (route) => {
    polls += 1;
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        polls === 1
          ? { job_id: "ios-resume-job-1", status: "running" }
          : { job_id: "ios-resume-job-1", status: "completed", response: placePlan },
      ),
    });
  });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的？");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByTestId("travel-job-status")).toContainText("后台生成");
  await page.reload();

  await expect(page.getByTestId("trip-card-ios-card-1")).toContainText("Fukuoka Tower");
  await expect(page.getByTestId("travel-job-status")).toHaveCount(0);
  expect(polls).toBeGreaterThanOrEqual(2);
});

test("Mira travel image carousel advances on rapid iPhone taps", async ({ page }) => {
  await routeTravelJob(page, { message: placeMessage });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的？");
  await page.getByRole("button", { name: "发送" }).click();

  const card = page.getByTestId("trip-card-ios-card-1");
  const image = card.locator("img");
  await expect(image).toHaveAttribute("src", /photo-1500530855697/);

  await page.getByTestId("image-next-ios-card-1").evaluate((button) => {
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    button.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });

  await expect(image).toHaveAttribute("src", /photo-1494526585095/);
});

test("Mira travel image carousel dots are tappable on iPhone", async ({ page }) => {
  await routeTravelJob(page, { message: placeMessage });

  await page.goto("/");
  await page.getByPlaceholder("Ask anything").fill("福冈有什么好玩的？");
  await page.getByRole("button", { name: "发送" }).click();

  const image = page.getByTestId("trip-card-ios-card-1").locator("img");
  await expect(image).toHaveAttribute("src", /photo-1500530855697/);

  await page.getByTestId("image-dot-ios-card-1-2").tap();
  await expect(image).toHaveAttribute("src", /photo-1494526585095/);
});

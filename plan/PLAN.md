# DeepSeek-V4 Router And Map Stability Implementation Plan

## Summary
- 新增 `travel-router` 模型别名，语义理解层使用 DeepSeek-V4，Gemma 只保留给自然语言叙事。
- 修复评价类问题误判：`福冈的海滨公园评价怎样?` 应进入 `place_evaluation`，不生成自然摄影推荐。
- 修复地图展示：知识/评价问题不渲染地图；地点选择不再让大详情卡覆盖地图或触发不必要刷新。

## Key Changes
- **LiteLLM 配置**
  - 在 `ops/litellm/config.yaml` 新增：
    - `travel-router -> deepseek/deepseek-v4-pro`
    - `travel-router-fast -> deepseek/deepseek-v4-flash`
  - 若当前 provider 不支持该命名，保留 alias，改由实际可用 DeepSeek/OpenRouter/Vercel AI Gateway provider 映射。

- **Backend Router**
  - 修改 `AgentModelRouter`，新增 `router` 字段。
  - `travel_workflow_graph.py` 的 `route` 节点使用 `model_router.router`，不再用 `summarizer`。
  - 强化 `TravelIntent`：
    - `task_type`: `knowledge_answer | place_evaluation | place_search | itinerary | hotel_search | flight_search`
    - `answer_mode`: `answer_only | place_detail | place_cards | itinerary | route_map`
  - DeepSeek router prompt 必须要求严格 JSON，先判断“用户是在问评价/解释/地点推荐/行程/酒店/航班”。

- **评价类问题处理**
  - `评价怎样 / 怎么样 / 值得去吗 / 口碑如何 / 过誉吗 / 踩雷吗 / 好不好玩` 归入 `place_evaluation`。
  - `place_evaluation` 默认：
    - `requires_place=false`
    - `needs_geo=false`
    - `requested_outputs=["narrative"]`
    - `should_not_answer=["generic_recommendations"]`
  - 若模型高置信度识别为单一 POI，可返回单地点详情，但不展开多推荐列表。

- **Map UI**
  - `answer_only` 和 `place_evaluation` 不渲染右侧地图。
  - `MapInlinePopup` 只作为 hover/preview 小卡。
  - `MapCallout` 默认移除或折叠，不再固定覆盖地图底部。
  - hover 不触发 `panTo`；只有点击卡片/marker 才改变 selected 并移动地图。
  - 地图 zoom 后 hover marker/card 不重置 zoom。

## Test Plan
- Backend:
  - `福冈的海滨公园评价怎样?` -> `task_type=place_evaluation`，无 `display_cards` 推荐列表，无地图 pins。
  - `Momochi Seaside Park值得去吗?` -> 评价总结，不生成自然摄影推荐。
  - `河豚是什么，为什么危险` -> `knowledge_answer`，无地图。
  - `福冈去哪吃河豚` -> `place_search`，返回餐厅卡和地图。
  - `福冈有什么好玩的` -> 本地体验/景点，不混入美食。
  - `福冈酒店推荐` -> hotel capability，不返回普通 POI 卡。
  - `福冈2天自由行，预算1000` -> itinerary，不强制航班/酒店。

- Web:
  - answer-only / place-evaluation 不显示右侧地图。
  - 点击推荐地点后地图不被大详情卡覆盖。
  - hover card/marker 小卡稳定展示，不闪回初始状态。
  - zoom 后 hover 推荐点，地图缩放保持不变。

- Verification:
  - `cd backend && python -m pytest -q`
  - `cd backend && python -m compileall app`
  - `cd web && npm test -- --reporter=list --workers=2`
  - `cd web && npm run lint`
  - `cd web && npm run build`

## CLI Goal Handoff
在 Codex CLI 中执行：

```text
/goal 根据 E:/python_project/photo_agent/docs/superpowers/plans/2026-05-20-deepseek-v4-router-map-fix.md 完成 DeepSeek-V4 语义理解层与地图稳定性修复。要求新增 travel-router，修复 place_evaluation/answer_only/place_search/itinerary/hotel/flight 路由，确保评价类问题不误判为推荐，知识和评价问题不渲染地图，修复右侧地图选择后详情层覆盖和刷新问题，并通过 backend/web 全量测试。
```

## Assumptions
- DeepSeek-V4 通过 LiteLLM alias 接入；具体 provider 可是 DeepSeek 官方、OpenRouter、Vercel AI Gateway 或其他 OpenAI-compatible 服务。
- 如果 `deepseek/deepseek-v4-pro` 暂不可用，保持 `travel-router` alias 不变，只替换 provider mapping。
- 先修工作流和 UI 稳定性，不新增真实酒店/航班供应商。

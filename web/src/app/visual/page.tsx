"use client";

import {
  BookOpen,
  Bookmark,
  Camera,
  Compass,
  ExternalLink,
  Loader2,
  MapPin,
  Send,
  Share2,
  Volume2,
  Sparkles,
  Upload,
} from "lucide-react";
import Image from "next/image";
import { useMemo, useState } from "react";

import { MiraAppHeader } from "@/components/mira-app-header";
import { Button } from "@/components/ui/button";
import { Card, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { exploreVisual, followupVisual, type DeepVisualCard, type VisualExploreResult } from "@/lib/api";

type SelectedImage = {
  name: string;
  dataUrl: string;
  base64: string;
};

type VisualFollowupMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
};

const visualUploadMaxEdge = 1280;
const visualUploadInitialQuality = 0.82;
const visualUploadMinQuality = 0.46;
const visualUploadTargetBase64Length = 280_000;

const focusOptions = [
  { value: "auto", label: "Auto" },
  { value: "place", label: "Place" },
  { value: "object", label: "Object" },
  { value: "history", label: "History" },
  { value: "style", label: "Style" },
  { value: "emotion", label: "Emotion" },
];

export default function VisualDiscoveryPage() {
  const [images, setImages] = useState<SelectedImage[]>([]);
  const [contextText, setContextText] = useState("");
  const [focus, setFocus] = useState("auto");
  const [interestText, setInterestText] = useState("");
  const [showOptions, setShowOptions] = useState(false);
  const [result, setResult] = useState<VisualExploreResult | null>(null);
  const [followupText, setFollowupText] = useState("");
  const [followupMessages, setFollowupMessages] = useState<VisualFollowupMessage[]>([]);
  const [isFollowupLoading, setIsFollowupLoading] = useState(false);
  const [followupError, setFollowupError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");

  const interestTags = useMemo(
    () =>
      interestText
        .split(/,|，|\s+/)
        .map((tag) => tag.trim())
        .filter(Boolean),
    [interestText],
  );
  const primaryImage = images[0];

  async function handleFiles(fileList: FileList | null) {
    const files = Array.from(fileList ?? []).slice(0, 4);
    const loaded = await Promise.all(files.map(readImageFile));
    setImages(loaded);
    setResult(null);
    setFollowupMessages([]);
    setFollowupText("");
    setFollowupError("");
    setError("");
  }

  async function submit() {
    if (images.length === 0 || isLoading) {
      setError("先放一张照片进来。");
      return;
    }
    setIsLoading(true);
    setError("");
    try {
      const response = await exploreVisual({
        imagesBase64: images.map((image) => image.base64),
        userContextText: contextText,
        explorationFocus: focus,
        interestTags,
      });
      setResult(response);
      setFollowupMessages([]);
      setFollowupText("");
      setFollowupError("");
    } catch (caught) {
      setError(formatVisualError(caught));
    } finally {
      setIsLoading(false);
    }
  }

  async function submitFollowup(rawQuestion?: string) {
    const question = (rawQuestion ?? followupText).trim();
    if (!question || !result || images.length === 0 || isFollowupLoading) {
      return;
    }
    const userMessage: VisualFollowupMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      text: question,
    };
    setFollowupMessages((messages) => [...messages, userMessage]);
    setFollowupText("");
    setFollowupError("");
    setIsFollowupLoading(true);
    try {
      const response = await followupVisual({
        sessionId: result.session_id,
        question,
        imagesBase64: images.map((image) => image.base64),
        previousResult: compactVisualResult(result),
        userContextText: contextText,
        explorationFocus: focus,
        interestTags,
      });
      setFollowupMessages((messages) => [
        ...messages,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          text: response.answer || "这次没有拿到有效回答。",
        },
      ]);
    } catch (caught) {
      setFollowupError(formatVisualError(caught));
    } finally {
      setIsFollowupLoading(false);
    }
  }

  return (
    <main className={`bg-[#f8f7f4] text-neutral-950 ${result ? "min-h-screen" : "min-h-screen md:min-h-screen md:overflow-visible max-md:h-dvh max-md:overflow-hidden"}`}>
      <div className={result ? "grid min-h-screen lg:grid-cols-[minmax(320px,30vw)_1fr]" : "flex min-h-screen flex-col md:block max-md:h-full"}>
        <section className={`flex flex-col bg-white ${result ? "border-b border-neutral-200 lg:min-h-screen lg:border-b-0 lg:border-r" : "mx-auto w-full max-w-3xl md:my-6 md:rounded-[34px] md:border md:border-neutral-200 md:shadow-[0_18px_60px_rgba(15,23,42,0.06)] max-md:min-h-0 max-md:flex-1"}`}>
          <MiraAppHeader
            subtitle="识境"
            primaryAction={{
              href: "/",
              label: "旅行",
              icon: <Compass className="h-4 w-4" />,
            }}
            iconAction={{
              label: "分享",
              icon: <Share2 size={15} />,
            }}
          />

          <div className={`flex-1 px-4 py-4 sm:px-6 ${result ? "overflow-y-auto" : "md:overflow-visible max-md:overflow-hidden"}`}>
            <div className="space-y-3 sm:space-y-4">
              <Card data-testid="visual-photo-card" className="space-y-3 rounded-[28px] border-neutral-200 p-4 shadow-none sm:p-5">
                <CardTitle className="flex items-center gap-2">
                  <Camera className="h-4 w-4" />
                  照片
                </CardTitle>
                <label
                  data-testid="visual-upload-dropzone"
                  aria-label="上传图片"
                  className={`relative flex aspect-[4/3] max-h-[440px] cursor-pointer items-center justify-center overflow-hidden rounded-[28px] border bg-[#fbfaf7] text-center transition-colors hover:bg-neutral-100 ${
                    primaryImage ? "border-neutral-200" : "border-dashed border-neutral-300"
                  }`}
                >
                  {primaryImage ? (
                    <>
                      <Image
                        data-testid="visual-upload-preview"
                        src={primaryImage.dataUrl}
                        alt=""
                        fill
                        sizes="(min-width: 1024px) 30vw, 100vw"
                        unoptimized
                        className="object-cover"
                      />
                      <span className="absolute bottom-3 right-3 flex h-10 w-10 items-center justify-center rounded-full bg-white/95 text-neutral-900 shadow-[0_8px_24px_rgba(15,23,42,0.18)]">
                        <Upload className="h-4 w-4" />
                        <span className="sr-only">更换图片</span>
                      </span>
                    </>
                  ) : (
                    <span data-testid="visual-upload-art" className="flex flex-col items-center gap-3">
                      <span
                        data-testid="visual-upload-icon"
                        className="grid h-16 w-16 place-items-center rounded-[22px] border border-neutral-200 bg-white shadow-[0_10px_28px_rgba(15,23,42,0.08)]"
                      >
                        <Camera className="h-6 w-6 text-neutral-900" />
                      </span>
                      <span className="flex items-center gap-2 text-sm font-medium text-neutral-700">
                        <Upload className="h-4 w-4" />
                        添加照片
                      </span>
                    </span>
                  )}
                  <span className="sr-only">
                    {primaryImage ? "更换图片" : "上传图片"}
                  </span>
                  <input
                    data-testid="visual-file-input"
                    className="sr-only"
                    type="file"
                    accept="image/*"
                    multiple
                    onChange={(event) => void handleFiles(event.currentTarget.files)}
                  />
                </label>
                <Button
                  data-testid="visual-submit"
                  className="h-11 w-full rounded-full"
                  onClick={() => void submit()}
                  disabled={isLoading}
                >
                  {isLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                  探索
                </Button>
                {error ? (
                  <div className="rounded-2xl border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                    {error}
                  </div>
                ) : null}
              </Card>

              <div className="rounded-[24px] border border-neutral-200 bg-white shadow-none">
                <button
                  data-testid="visual-options-toggle"
                  type="button"
                  aria-expanded={showOptions}
                  className="flex min-h-11 w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm font-medium text-neutral-700"
                  onClick={() => setShowOptions((open) => !open)}
                >
                  <span className="flex items-center gap-2">
                    <Sparkles className="h-4 w-4" />
                    可选线索
                  </span>
                  <span className="text-xs text-neutral-400">
                    {showOptions ? "收起" : "地点、兴趣、视角"}
                  </span>
                </button>
                {showOptions ? (
                  <div data-testid="visual-optional-settings" className="space-y-4 border-t border-neutral-200 p-4">
                    <Textarea
                      data-testid="visual-context"
                      value={contextText}
                      onChange={(event) => setContextText(event.target.value)}
                      placeholder="比如：位于中国西南山区 / 在福冈街头看到 / 可能是老店门口"
                    />
                    <div className="grid gap-3 sm:grid-cols-2">
                      <div>
                        <label className="mb-1 block text-xs font-medium text-neutral-500">
                          Focus
                        </label>
                        <select
                          data-testid="visual-focus-select"
                          value={focus}
                          onChange={(event) => setFocus(event.target.value)}
                          className="h-11 w-full rounded-2xl border border-neutral-300 bg-white px-3 text-sm outline-none focus:border-neutral-900"
                        >
                          {focusOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label className="mb-1 block text-xs font-medium text-neutral-500">
                          Interests
                        </label>
                        <Input
                          data-testid="visual-interest-input"
                          value={interestText}
                          onChange={(event) => setInterestText(event.target.value)}
                          placeholder="architecture, local craft"
                        />
                      </div>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          </div>
        </section>

        {result ? (
          <section data-testid="visual-results-region" className="overflow-y-auto px-4 py-5 sm:px-8 sm:py-7 lg:min-h-screen">
            <VisualResult
              result={result}
              followupText={followupText}
              followupMessages={followupMessages}
              followupError={followupError}
              isFollowupLoading={isFollowupLoading}
              onFollowupTextChange={setFollowupText}
              onSubmitFollowup={(question) => void submitFollowup(question)}
            />
          </section>
        ) : null}
      </div>
    </main>
  );
}

function VisualResult({
  result,
  followupText,
  followupMessages,
  followupError,
  isFollowupLoading,
  onFollowupTextChange,
  onSubmitFollowup,
}: {
  result: VisualExploreResult;
  followupText: string;
  followupMessages: VisualFollowupMessage[];
  followupError: string;
  isFollowupLoading: boolean;
  onFollowupTextChange: (value: string) => void;
  onSubmitFollowup: (question?: string) => void;
}) {
  const meaningEntries = Object.entries(result.meaning_layers);
  const uncertainty = result.visual_workflow_summary.uncertainty.length
    ? result.visual_workflow_summary.uncertainty
    : result.confidence_notes;
  const memory = result.visual_memory_item;
  const oneLine = publicOneLine(result);
  const deepCards = result.deep_cards.length ? result.deep_cards : fallbackDeepCards(result);

  function playAudio() {
    const script =
      result.audio_script || oneLine || result.narrative || result.why_it_matters || result.story_title;
    if (!script || typeof window === "undefined" || !("speechSynthesis" in window)) {
      return;
    }
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(script));
  }

  return (
    <div className="mx-auto max-w-5xl space-y-5">
      <Card data-testid="visual-public-answer" className="rounded-[32px] border-neutral-900 bg-neutral-950 text-white shadow-[0_22px_70px_rgba(15,23,42,0.22)]">
        <p className="text-xs uppercase tracking-[0.18em] text-neutral-400">Conclusion</p>
        <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
          <h2 data-testid="visual-one-line" className="max-w-3xl text-3xl font-semibold tracking-tight leading-tight">
            {plainText(oneLine)}
          </h2>
          <Button
            data-testid="visual-audio"
            variant="subtle"
            className="bg-white text-neutral-950 hover:bg-neutral-200"
            onClick={playAudio}
          >
            <Volume2 className="h-4 w-4" />
            Listen
          </Button>
        </div>
      </Card>

      <Card data-testid="visual-deep-cards" className="rounded-[32px] shadow-[0_18px_55px_rgba(15,23,42,0.06)]">
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-4 w-4" />
          识别 / 看点 / 线索
        </CardTitle>
        <div className="mt-4 space-y-4">
          {deepCards.map((card) => (
            <article
              key={card.title}
              data-testid={`visual-framework-card-${card.title}`}
              className="rounded-[28px] border border-neutral-200 bg-[#fffdfa] p-5 shadow-[0_14px_40px_rgba(15,23,42,0.05)]"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-neutral-100 pb-3">
                <h3 className="text-xl font-semibold tracking-tight">{plainText(card.title)}</h3>
                <span className="text-xs uppercase tracking-[0.14em] text-neutral-400">
                  Framework
                </span>
              </div>
              <p className="mt-4 text-sm leading-7 text-neutral-700">{plainText(card.body)}</p>
              {card.sections.length ? (
                <div className="mt-5 grid gap-3 lg:grid-cols-2">
                  {card.sections.map((section) => (
                    <section
                      key={`${card.title}-${section.title}`}
                      data-testid={`visual-section-${section.title}`}
                      className="rounded-[22px] bg-neutral-50 p-4"
                    >
                      <h4 className="text-sm font-semibold text-neutral-950">
                        {plainText(section.title)}
                      </h4>
                      {section.body ? (
                        <p className="mt-2 text-sm leading-7 text-neutral-700">
                          {plainText(section.body)}
                        </p>
                      ) : null}
                      {section.bullets.length ? (
                        <ul className="mt-3 space-y-1.5 text-sm leading-6 text-neutral-600">
                          {section.bullets.slice(0, 4).map((bullet) => (
                            <li key={bullet} className="flex gap-2">
                              <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-neutral-400" />
                              <span>{plainText(bullet)}</span>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                      {section.chips.length ? (
                        <div className="mt-3 flex flex-wrap gap-2">
                          {section.chips.slice(0, 5).map((chip) => (
                            <span key={chip} className="rounded-full bg-white px-2.5 py-1 text-xs leading-5 text-neutral-600">
                              {plainText(chip)}
                            </span>
                          ))}
                        </div>
                      ) : null}
                      {section.tables?.length ? (
                        <div className="mt-4 space-y-3">
                          {section.tables.map((table, tableIndex) => (
                            <div
                              key={`${section.title}-table-${tableIndex}`}
                              data-testid={`visual-section-table-${section.title}`}
                              className="overflow-hidden rounded-2xl border border-neutral-200 bg-white"
                            >
                              {table.caption ? (
                                <p className="border-b border-neutral-100 px-3 py-2 text-xs font-medium text-neutral-500">
                                  {plainText(table.caption)}
                                </p>
                              ) : null}
                              <div className="overflow-x-auto">
                                <table className="min-w-full text-left text-xs">
                                  <thead className="bg-neutral-50 text-neutral-500">
                                    <tr>
                                      {table.columns.map((column) => (
                                        <th key={column} className="px-3 py-2 font-medium">
                                          {plainText(column)}
                                        </th>
                                      ))}
                                    </tr>
                                  </thead>
                                  <tbody className="divide-y divide-neutral-100 text-neutral-700">
                                    {table.rows.map((row, rowIndex) => (
                                      <tr key={`${section.title}-row-${rowIndex}`}>
                                        {table.columns.map((column, columnIndex) => (
                                          <td key={`${column}-${columnIndex}`} className="px-3 py-2 align-top">
                                            {plainText(row[columnIndex] ?? "")}
                                          </td>
                                        ))}
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {section.images?.length ? (
                        <div
                          data-testid={`visual-section-image-${section.title}`}
                          className="mt-4 grid gap-3 sm:grid-cols-2"
                        >
                          {section.images.slice(0, 4).map((image) => (
                            <figure key={image.url} className="overflow-hidden rounded-2xl bg-white">
                              {/* eslint-disable-next-line @next/next/no-img-element -- Model-provided URLs are arbitrary; Next Image remote allowlists would drop valid provider media. */}
                              <img
                                src={image.url}
                                alt={plainText(image.caption || section.title)}
                                className="aspect-[4/3] w-full object-cover"
                                loading="lazy"
                                referrerPolicy="no-referrer"
                              />
                              {image.caption || image.source ? (
                                <figcaption className="px-3 py-2 text-xs leading-5 text-neutral-500">
                                  {plainText([image.caption, image.source].filter(Boolean).join(" · "))}
                                </figcaption>
                              ) : null}
                            </figure>
                          ))}
                        </div>
                      ) : null}
                    </section>
                  ))}
                </div>
              ) : null}
              {card.supporting_points.length ? (
                <div className="mt-4 flex flex-wrap gap-2">
                  {card.supporting_points.slice(0, 4).map((point) => (
                    <span key={point} className="rounded-full bg-neutral-100 px-2.5 py-1 text-xs leading-5 text-neutral-600">
                      {plainText(point)}
                    </span>
                  ))}
                </div>
              ) : null}
              {card.next_action ? (
                <p className="mt-4 rounded-2xl bg-neutral-50 p-3 text-xs leading-5 text-neutral-600">
                  {plainText(card.next_action)}
                </p>
              ) : null}
            </article>
          ))}
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card data-testid="visual-sources">
          <CardTitle>Sources</CardTitle>
          <div className="mt-4 space-y-3">
            {result.api_sources_used.map((source) => (
              <a
                key={`${source.provider}-${source.name}`}
                href={source.url ?? "#"}
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-between gap-4 rounded-2xl border border-neutral-200 p-3 text-sm hover:bg-neutral-50"
              >
                <span>
                  <span className="font-medium">{source.name}</span>
                  <span className="ml-2 text-neutral-500">{source.source_type}</span>
                </span>
                <ExternalLink className="h-4 w-4 text-neutral-400" />
              </a>
            ))}
            {result.knowledge_cards.map((card) => (
              <div key={`${card.source_type}-${card.title}`} className="rounded-2xl bg-neutral-50 p-3 text-sm">
                <p className="font-medium">{card.title}</p>
                <p className="mt-1 text-neutral-600">{card.snippet}</p>
              </div>
            ))}
            {!result.api_sources_used.length && !result.knowledge_cards.length ? (
              <p className="text-sm text-neutral-500">这次结果主要来自图像推理，没有额外外部来源。</p>
            ) : null}
          </div>
        </Card>

        <Card>
          <CardTitle className="flex items-center gap-2">
            <MapPin className="h-4 w-4" />
            Memory & Next
          </CardTitle>
          <div className="mt-4 space-y-3">
            {result.related_places.length ? (
              result.related_places.map((place) => (
                <div key={`${place.name}-${place.relation}`} className="rounded-2xl bg-neutral-50 p-3 text-sm">
                  <p className="font-medium">{place.name}</p>
                  <p className="mt-1 text-neutral-600">{place.reason || place.relation}</p>
                </div>
              ))
            ) : (
              <div data-testid="visual-memory" className="rounded-[24px] bg-neutral-50 p-4 text-sm text-neutral-600">
                <div className="flex items-start gap-3">
                  <Bookmark className="mt-0.5 h-4 w-4 text-neutral-500" />
                  <div>
                    <p className="font-medium text-neutral-950">
                      {memory?.title || "Visual memory"}
                    </p>
                    <p className="mt-1">
                      {memory?.region_hint || "这次发现会以 session 形式保留，后续可接入地图记忆和路线规划。"}
                    </p>
                    <div className="mt-3 flex gap-2">
                      {["discovered", "saved", "planned"].map((status) => (
                        <span
                          key={status}
                          className={`rounded-full px-2 py-1 text-xs ${
                            (memory?.status || "discovered") === status
                              ? "bg-neutral-950 text-white"
                              : "bg-white text-neutral-500"
                          }`}
                        >
                          {status}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            )}
            {result.followup_questions.map((question) => (
              <button
                key={question}
                data-testid="visual-followup-suggestion"
                className="block w-full rounded-2xl border border-neutral-200 px-3 py-2 text-left text-sm hover:bg-neutral-50"
                onClick={() => onSubmitFollowup(question)}
              >
                {question}
              </button>
            ))}
          </div>
        </Card>
      </div>

      <Card data-testid="visual-followup-panel" className="rounded-[28px] p-4 shadow-[0_14px_40px_rgba(15,23,42,0.05)] sm:p-5">
        <CardTitle className="flex items-center gap-2 text-base">
          <Sparkles className="h-4 w-4" />
          继续问这张图
        </CardTitle>
        <div data-testid="visual-followup-messages" className="mt-4 space-y-3">
          {followupMessages.length ? (
            followupMessages.map((message) => (
              <div
                key={message.id}
                className={`max-w-[88%] rounded-3xl px-4 py-3 text-sm leading-6 ${
                  message.role === "user"
                    ? "ml-auto bg-neutral-950 text-white"
                    : "bg-neutral-100 text-neutral-800"
                }`}
              >
                {plainText(message.text)}
              </div>
            ))
          ) : (
            <p className="text-sm leading-6 text-neutral-500">
              可以继续问它的历史、拍摄角度、附近路线或画面细节。
            </p>
          )}
        </div>
        <form
          data-testid="visual-followup-form"
          className="mt-4 flex items-center gap-2 rounded-full border border-neutral-200 bg-white p-2"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmitFollowup();
          }}
        >
          <Input
            data-testid="visual-followup-input"
            value={followupText}
            onChange={(event) => onFollowupTextChange(event.target.value)}
            placeholder="追问这张图..."
            className="min-h-11 flex-1 border-0 bg-transparent px-3 text-base shadow-none focus-visible:ring-0"
          />
          <Button
            data-testid="visual-followup-submit"
            type="submit"
            className="h-10 w-10 shrink-0 rounded-full px-0"
            disabled={isFollowupLoading || !followupText.trim()}
            aria-label="发送追问"
          >
            {isFollowupLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </form>
        {followupError ? (
          <p className="mt-3 rounded-2xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {followupError}
          </p>
        ) : null}
      </Card>

      <details className="rounded-[28px] border border-neutral-200 bg-white">
        <summary
          data-testid="visual-debug-toggle"
          className="cursor-pointer px-5 py-4 text-sm font-medium text-neutral-500 hover:text-neutral-950"
        >
          思考过程：专家观点、可见线索、判断假设和意义层次
        </summary>
        <div data-testid="visual-debug-details" className="space-y-5 border-t border-neutral-200 p-5">
          {debugNotes(result, uncertainty).length ? (
            <section>
              <CardTitle>辅助判断</CardTitle>
              <div className="mt-4 space-y-2 rounded-[22px] bg-neutral-50 p-4 text-sm leading-6 text-neutral-600">
                {debugNotes(result, uncertainty).map((note) => (
                  <p key={note}>{note}</p>
                ))}
              </div>
            </section>
          ) : null}

          {result.perspective_cards.length ? (
            <section data-testid="visual-perspectives">
              <CardTitle className="flex items-center gap-2">
                <Sparkles className="h-4 w-4" />
                专家观点
              </CardTitle>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {result.perspective_cards.map((card) => (
                  <div key={`${card.perspective}-${card.title}`} className="rounded-[22px] border border-neutral-200 p-4">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="font-semibold">{card.title}</h3>
                      <span className="rounded-full bg-neutral-100 px-2 py-1 text-xs text-neutral-500">
                        {Math.round(card.confidence * 100)}%
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-neutral-600">{card.summary}</p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}

          <section data-testid="visual-clues">
            <CardTitle className="flex items-center gap-2">
              <Camera className="h-4 w-4" />
              可见线索
            </CardTitle>
            <div className="mt-4 space-y-3">
              {result.visible_clues.length ? (
                result.visible_clues.map((clue) => (
                  <div key={`${clue.clue}-${clue.interpretation}`} className="rounded-[22px] bg-neutral-50 p-4">
                    <div className="flex items-start justify-between gap-4">
                      <p className="font-medium">{clue.clue}</p>
                      <span className="rounded-full bg-white px-2 py-1 text-xs text-neutral-500">
                        {Math.round(clue.confidence * 100)}%
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-neutral-600">{clue.interpretation}</p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-neutral-500">没有足够可见线索。</p>
              )}
            </div>
          </section>

          <section data-testid="visual-hypotheses">
            <CardTitle className="flex items-center gap-2">
              <BookOpen className="h-4 w-4" />
              判断假设
            </CardTitle>
            <div className="mt-4 space-y-3">
              {result.cultural_hypotheses.length ? (
                result.cultural_hypotheses.map((hypothesis) => (
                  <div key={hypothesis.name} className="rounded-[22px] border border-neutral-200 p-4">
                    <div className="flex items-center justify-between gap-4">
                      <h3 className="font-semibold">{hypothesis.name}</h3>
                      <span className="rounded-full bg-neutral-100 px-2 py-1 text-xs text-neutral-500">
                        {hypothesis.entity_type}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-neutral-600">{hypothesis.rationale}</p>
                  </div>
                ))
              ) : (
                <p className="text-sm text-neutral-500">还没有形成可靠假设。</p>
              )}
            </div>
          </section>

          {meaningEntries.length ? (
            <section>
              <CardTitle>意义层次</CardTitle>
              <div className="mt-4 grid gap-3 md:grid-cols-2">
                {meaningEntries.map(([key, value]) => (
                  <div key={key} className="rounded-[22px] bg-neutral-50 p-4">
                    <p className="text-xs uppercase tracking-[0.12em] text-neutral-500">{key}</p>
                    <p className="mt-2 text-sm leading-6">{value}</p>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </div>
      </details>
    </div>
  );
}

function publicOneLine(result: VisualExploreResult) {
  return plainText(
    result.one_line_answer ||
    firstSentence(result.narrative) ||
    firstSentence(result.why_it_matters) ||
    result.story_title ||
    result.what_it_is ||
    "这张照片的主体可以从可见形态、环境和细节先读出一条清晰线索。"
  );
}

function fallbackDeepCards(result: VisualExploreResult): DeepVisualCard[] {
  const cluePoints = result.visible_clues
    .map((clue) => clue.interpretation || clue.clue)
    .filter(Boolean);
  return [
    {
      title: "识别",
      body: result.what_it_is || "这是一个值得从形制、材料和环境关系入手理解的视觉主体。",
      supporting_points: cluePoints.slice(0, 3),
      next_action: "可以查看现场说明、地图位置或周边街景，把名称、位置和画面线索对上。",
      sections: [
        {
          title: "主体身份",
          body: result.what_it_is || "照片中的主要视觉主体。",
          bullets: [],
          chips: [],
        },
        {
          title: "地点/类型",
          body: result.visual_memory_item?.region_hint || result.visual_memory_item?.entity_type || "可结合地图、文字或周边街景继续确认。",
          bullets: [],
          chips: [result.visual_memory_item?.region_hint || ""].filter(Boolean),
        },
        {
          title: "核心特征",
          body:
            cluePoints.length > 0
              ? cluePoints.slice(0, 3).join("；")
              : "可从主体轮廓、材质、尺度和环境关系辨认。",
          bullets: cluePoints.slice(0, 3),
          chips: [],
        },
      ],
    },
    {
      title: "看点",
      body: result.narrative || result.why_it_matters || "它值得看的地方在于画面里的地方气质和可见细节。",
      supporting_points: Object.values(result.meaning_layers).slice(0, 3),
      next_action: "可以继续追问它的历史、文化背景或类似地点。",
      sections: [
        {
          title: "导游视角",
          body: result.meaning_layers.practical || result.narrative || result.why_it_matters,
          bullets: [],
          chips: [],
        },
        {
          title: "历史视角",
          body: result.meaning_layers.cultural_history || result.why_it_matters,
          bullets: [],
          chips: [],
        },
        {
          title: "文化视角",
          body: result.meaning_layers.emotional || result.why_popular_or_overhyped || "它把地点气质、人的路径和观看角度连接起来。",
          bullets: [],
          chips: [],
        },
        {
          title: "风格视角",
          body: result.meaning_layers.visual || "主体轮廓、尺度关系和材料细节构成第一层观看重点。",
          bullets: [],
          chips: [],
        },
      ],
    },
    {
      title: "线索",
      body:
        cluePoints.length > 0
          ? `先看这些线索：${cluePoints.slice(0, 3).join("；")}。`
          : "先看主体与环境、文字、材料、纹样和使用痕迹之间的关系。",
      supporting_points: cluePoints.slice(0, 3),
      next_action: result.followup_questions[0] || "换一个角度再拍，或者补充地点线索。",
      sections: [
        {
          title: "画面线索",
          body:
            cluePoints.length > 0
              ? cluePoints.slice(0, 3).join("；")
              : "观察主体形状、材料、文字、构图、环境和使用痕迹之间的关系。",
          bullets: cluePoints.slice(0, 3),
          chips: [],
        },
        {
          title: "判断依据",
          body:
            result.cultural_hypotheses[0]?.rationale ||
            "把可见形态、材料、环境和地点语境合在一起判断，而不是只看单个物体标签。",
          bullets: result.cultural_hypotheses[0]?.evidence_support?.slice(0, 3) ?? [],
          chips: [],
        },
        {
          title: "继续探索",
          body: result.followup_questions[0] || "换一个角度再拍，或者补充地点线索。",
          bullets: [],
          chips: [],
        },
      ],
    },
  ];
}

function debugNotes(result: VisualExploreResult, uncertainty: string[]) {
  return uniqueStrings([
    ...uncertainty,
    ...result.confidence_notes,
    `provider: ${result.visual_workflow_summary.provider}`,
    `model: ${result.visual_workflow_summary.model}`,
  ]);
}

function uniqueStrings(values: string[]) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const value of values) {
    const text = String(value || "").trim();
    if (!text || seen.has(text)) {
      continue;
    }
    seen.add(text);
    result.push(text);
  }
  return result;
}

function compactVisualResult(result: VisualExploreResult): Partial<VisualExploreResult> {
  return {
    session_id: result.session_id,
    what_it_is: result.what_it_is,
    one_line_answer: result.one_line_answer,
    story_title: result.story_title,
    narrative: result.narrative,
    meaning_layers: result.meaning_layers,
    visible_clues: result.visible_clues.slice(0, 6),
    cultural_hypotheses: result.cultural_hypotheses.slice(0, 4),
    followup_questions: result.followup_questions.slice(0, 4),
    deep_cards: result.deep_cards.slice(0, 3).map((card) => ({
      title: card.title,
      body: card.body,
      supporting_points: card.supporting_points.slice(0, 4),
      next_action: card.next_action,
      sections: [],
    })),
  };
}

function plainText(value: string) {
  return String(value || "")
    .replace(/<[^>]*>/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function firstSentence(value: string) {
  const text = String(value || "").trim();
  if (!text) {
    return "";
  }
  for (const separator of ["。", "！", "？", ".", "!", "?"]) {
    const index = text.indexOf(separator);
    if (index >= 0) {
      return text.slice(0, index + separator.length).trim();
    }
  }
  return text.slice(0, 160).trim();
}

async function readImageFile(file: File): Promise<SelectedImage> {
  const originalDataUrl = await readFileAsDataUrl(file);
  try {
    return await compressImageFile(file, originalDataUrl);
  } catch {
    const base64 = base64FromDataUrl(originalDataUrl);
    return { name: file.name, dataUrl: originalDataUrl, base64 };
  }
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("无法读取图片。"));
    reader.onload = () => {
      resolve(String(reader.result ?? ""));
    };
    reader.readAsDataURL(file);
  });
}

async function compressImageFile(file: File, originalDataUrl: string): Promise<SelectedImage> {
  const image = await loadImage(originalDataUrl);
  const largestEdge = Math.max(image.naturalWidth, image.naturalHeight);
  if (!Number.isFinite(largestEdge) || largestEdge <= 0) {
    throw new Error("无法识别图片尺寸。");
  }
  const scale = Math.min(1, visualUploadMaxEdge / largestEdge);
  const width = Math.max(1, Math.round(image.naturalWidth * scale));
  const height = Math.max(1, Math.round(image.naturalHeight * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("无法压缩图片。");
  }
  context.fillStyle = "#ffffff";
  context.fillRect(0, 0, width, height);
  context.drawImage(image, 0, 0, width, height);

  let quality = visualUploadInitialQuality;
  let dataUrl = canvas.toDataURL("image/jpeg", quality);
  while (
    base64FromDataUrl(dataUrl).length > visualUploadTargetBase64Length &&
    quality > visualUploadMinQuality
  ) {
    quality = Math.max(visualUploadMinQuality, quality - 0.1);
    dataUrl = canvas.toDataURL("image/jpeg", quality);
  }

  const originalBase64 = base64FromDataUrl(originalDataUrl);
  const compressedBase64 = base64FromDataUrl(dataUrl);
  if (
    originalBase64.length <= visualUploadTargetBase64Length &&
    originalBase64.length <= compressedBase64.length
  ) {
    return { name: file.name, dataUrl: originalDataUrl, base64: originalBase64 };
  }
  return { name: file.name, dataUrl, base64: compressedBase64 };
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new window.Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("无法解码图片。"));
    image.src = src;
  });
}

function base64FromDataUrl(dataUrl: string) {
  return dataUrl.includes(",") ? dataUrl.split(",")[1] : dataUrl;
}

function formatVisualError(caught: unknown) {
  const message = caught instanceof Error ? caught.message : "";
  if (/failed to fetch|fetch failed|networkerror/i.test(message)) {
    return "上传或分析请求被中断，请换一张较小图片或稍后重试。";
  }
  if (/413|too large|payload too large|request entity too large/i.test(message)) {
    return "图片太大了，请换一张较小的照片再试。";
  }
  return message || "视觉探索接口暂时不可用。";
}

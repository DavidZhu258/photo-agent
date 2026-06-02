"use client";

import {
  ArrowRight,
  Camera,
  ChevronLeft,
  ChevronRight,
  Heart,
  Loader2,
  Plus,
  Send,
  Share2,
} from "lucide-react";
import {
  useEffect,
  useCallback,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type MouseEvent,
  type ReactNode,
  type RefObject,
  type SetStateAction,
  type KeyboardEvent,
} from "react";

import {
  buildAssistantMessageFromPlan,
  mergeContextFromText,
  mergeContextFromPlan,
  textFromMessage,
  userFacingRuntimeWarnings,
  type RawTravelPlan,
  type TravelChatMessage,
  type TravelChatPart,
  type TripAnswerSection,
  type TripFlightOffer,
  type TripHotelOffer,
  type TripCard,
  type TripContext,
  type TripHeaderPart,
  type TripMap,
} from "@/lib/travel-chat";
import { MiraAppHeader } from "@/components/mira-app-header";

const configuredPublicMapboxToken = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN ?? "";
const mapboxAccessToken = configuredPublicMapboxToken.startsWith("pk.")
  ? configuredPublicMapboxToken
  : "";

type MapboxMapInstance = import("mapbox-gl").Map;
type MapboxMarker = import("mapbox-gl").Marker;
type LeafletModule = typeof import("leaflet");
type LeafletImport = LeafletModule & { default?: LeafletModule };
type LeafletMapInstance = import("leaflet").Map;
type LeafletMarker = import("leaflet").Marker;

const initialHeader: TripHeaderPart = {
  type: "trip-header",
  title: "Mira",
  subtitle: "识境",
  trip_count: 0,
  chips: [
    { id: "Where", label: "Where", value: "" },
    { id: "When", label: "When", value: "" },
    { id: "Who", label: "Who", value: "" },
    { id: "Budget", label: "Budget", value: "" },
    { id: "Preferences", label: "Preferences", value: "" },
  ],
};

const pendingTravelJobStorageKey = "mira.pendingTravelJob";

type PendingTravelJob = {
  jobId: string;
  query: string;
  context: TripContext;
  userMessage: TravelChatMessage;
  startedAt: number;
  lastStatus?: string;
};

type TravelJobStartResponse = {
  job_id?: string;
  status?: string;
  query?: string;
  context?: TripContext;
  message?: TravelChatMessage;
  error?: { message?: string };
};

type TravelJobStatusResponse = {
  job_id?: string;
  status?: "queued" | "running" | "completed" | "failed";
  response?: RawTravelPlan;
  message?: TravelChatMessage;
  context?: TripContext;
  error?: {
    error_type?: string;
    failed_stage?: string;
    model?: string;
    message?: string;
  };
};

export default function Home() {
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const [messages, setMessages] = useState<TravelChatMessage[]>([]);
  const [context, setContext] = useState<TripContext>({});
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [pendingJob, setPendingJob] = useState<PendingTravelJob | null>(null);
  const [error, setError] = useState("");
  const [selectedCardId, setSelectedCardId] = useState("");
  const [previewCardId, setPreviewCardId] = useState("");
  const previewResetTimerRef = useRef<number | null>(null);
  const [tripCards, setTripCards] = useState<Record<string, TripCard>>({});
  const [likedCards, setLikedCards] = useState<Record<string, TripCard>>({});
  const [imageIndexes, setImageIndexes] = useState<Record<string, number>>({});
  const [failedImages, setFailedImages] = useState<Record<string, boolean>>({});
  const pollingJobIdRef = useRef<string | null>(null);

  const latestHeader = useMemo(() => latestPart(messages, "trip-header") ?? initialHeader, [messages]);
  const latestCards = useMemo(() => latestPart(messages, "trip-cards")?.cards ?? [], [messages]);
  const latestAnswerSections = useMemo(
    () => latestPart(messages, "trip-answer-sections")?.sections ?? [],
    [messages],
  );
  const latestHotelOffers = useMemo(() => latestPart(messages, "trip-hotels")?.offers ?? [], [messages]);
  const latestFlightOffers = useMemo(() => latestPart(messages, "trip-flights")?.offers ?? [], [messages]);
  const latestMap = useMemo(() => latestPart(messages, "trip-map")?.map ?? emptyMap(), [messages]);
  const latestWarnings = useMemo(
    () => userFacingRuntimeWarnings(latestPart(messages, "runtime-warnings")?.warnings ?? []),
    [messages],
  );
  const selectedMapCardId =
    latestCards.some((card) => card.id === selectedCardId)
      ? selectedCardId
      : latestMap.selected_pin_id || latestCards[0]?.id || "";
  const previewMapCardId =
    latestCards.some((card) => card.id === previewCardId)
      ? previewCardId
      : selectedMapCardId;
  const shouldRenderMapPanel = shouldShowMapPanel(messages.length, latestMap, latestCards);
  const isBusy = isLoading || pendingJob !== null;

  function clearPreviewReset() {
    if (previewResetTimerRef.current !== null) {
      window.clearTimeout(previewResetTimerRef.current);
      previewResetTimerRef.current = null;
    }
  }

  const previewCard = useCallback((id: string) => {
    clearPreviewReset();
    setPreviewCardId(id);
  }, []);

  const schedulePreviewReset = useCallback(() => {
    clearPreviewReset();
    previewResetTimerRef.current = window.setTimeout(() => {
      setPreviewCardId("");
      previewResetTimerRef.current = null;
    }, 300);
  }, []);

  const finishPendingTravelJob = useCallback(
    (job: PendingTravelJob, data: TravelJobStatusResponse) => {
      const nextContext = data.response
        ? mergeContextFromPlan(data.context ?? job.context, data.response, job.query)
        : data.context ?? job.context;
      const assistantMessage = data.message ??
        (data.response
          ? buildAssistantMessageFromPlan(data.response, nextContext, job.query)
          : travelJobFailureMessage({ message: "后台旅行任务没有返回结果。" }));

      setMessages((current) => {
        const withUser = current.some((message) => message.id === job.userMessage.id)
          ? current
          : [...current, job.userMessage];
        return [...withUser, assistantMessage];
      });
      setContext((current) => ({ ...current, ...nextContext }));
      setSelectedCardId(firstSelectableId(assistantMessage));
      setPreviewCardId("");
      clearPreviewReset();
      clearStoredPendingTravelJob();
      setPendingJob(null);
      setError("");
    },
    [],
  );

  const failPendingTravelJob = useCallback((job: PendingTravelJob, data: TravelJobStatusResponse) => {
    const assistantMessage = travelJobFailureMessage(data.error);
    setMessages((current) => {
      const withUser = current.some((message) => message.id === job.userMessage.id)
        ? current
        : [...current, job.userMessage];
      return [...withUser, assistantMessage];
    });
    clearStoredPendingTravelJob();
    setPendingJob(null);
    setError("");
  }, []);

  const pollTravelJob = useCallback(
    async (job: PendingTravelJob) => {
      if (pollingJobIdRef.current === job.jobId) {
        return;
      }
      pollingJobIdRef.current = job.jobId;
      setIsLoading(true);
      try {
        for (;;) {
          const response = await fetch(`/api/travel/chat/jobs/${encodeURIComponent(job.jobId)}`, {
            cache: "no-store",
          });
          const data = (await response.json().catch(() => ({}))) as TravelJobStatusResponse;
          if (!response.ok) {
            if (response.status === 404) {
              failPendingTravelJob(job, {
                ...data,
                status: "failed",
                error: { message: "后台旅行任务已经不存在，请重新发送一次。" },
              });
              return;
            }
            throw new Error(jobErrorText(data, response.status));
          }
          if (data.status === "completed") {
            finishPendingTravelJob(job, data);
            return;
          }
          if (data.status === "failed") {
            failPendingTravelJob(job, data);
            return;
          }
          setPendingJob((current) => {
            if (!current || current.jobId !== job.jobId) {
              return current;
            }
            const next = { ...current, lastStatus: data.status ?? "running" };
            savePendingTravelJob(next);
            return next;
          });
          await sleep(document.visibilityState === "hidden" ? 8000 : 2500);
        }
      } catch {
        setError("旅行推荐已在后台生成。手机锁屏、网络切换或页面恢复后，会自动继续检查结果。");
      } finally {
        pollingJobIdRef.current = null;
        setIsLoading(false);
      }
    },
    [failPendingTravelJob, finishPendingTravelJob],
  );

  useEffect(() => () => clearPreviewReset(), []);

  useEffect(() => {
    const stored = loadPendingTravelJob();
    if (!stored) {
      return;
    }
    const restoreTimer = window.setTimeout(() => {
      setPendingJob(stored);
      setContext((current) => ({ ...current, ...stored.context }));
      setMessages((current) =>
        current.some((message) => message.id === stored.userMessage.id)
          ? current
          : [...current, stored.userMessage],
      );
    }, 0);
    return () => window.clearTimeout(restoreTimer);
  }, []);

  useEffect(() => {
    if (!pendingJob) {
      return;
    }
    const pollTimer = window.setTimeout(() => {
      savePendingTravelJob(pendingJob);
      void pollTravelJob(pendingJob);
    }, 0);
    return () => window.clearTimeout(pollTimer);
  }, [pendingJob, pollTravelJob]);

  useEffect(() => {
    if (!pendingJob) {
      return;
    }
    const resumePolling = () => {
      if (document.visibilityState === "hidden") {
        return;
      }
      void pollTravelJob(pendingJob);
    };
    window.addEventListener("focus", resumePolling);
    window.addEventListener("online", resumePolling);
    document.addEventListener("visibilitychange", resumePolling);
    return () => {
      window.removeEventListener("focus", resumePolling);
      window.removeEventListener("online", resumePolling);
      document.removeEventListener("visibilitychange", resumePolling);
    };
  }, [pendingJob, pollTravelJob]);

  useEffect(() => {
    viewportRef.current?.scrollTo({
      top: viewportRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, latestCards.length]);

  async function submitMessage() {
    const question = input.trim();
    if (!question || isBusy) return;
    const nextContext = contextWithSessionMemory(
      mergeContextFromText(context, question),
      latestCards,
      latestMap,
      likedCards,
      tripCards,
      selectedMapCardId,
    );
    const userMessage: TravelChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: question,
      parts: [{ type: "text", text: question }],
    };
    const nextMessages = [...messages, userMessage];
    setMessages(nextMessages);
    setContext(nextContext);
    setInput("");
    setError("");
    setIsLoading(true);

    try {
      if (shouldUseTravelBackgroundJobs()) {
        const response = await fetch("/api/travel/chat/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ messages: nextMessages, context: nextContext }),
        });
        const data = (await response.json()) as TravelJobStartResponse;
        if (!response.ok) {
          throw new Error(data.error?.message || "旅行后台任务创建失败。");
        }
        if (data.message) {
          setMessages((current) => [...current, data.message as TravelChatMessage]);
          setContext((current) => ({ ...current, ...(data.context ?? nextContext) }));
          return;
        }
        if (!data.job_id) {
          throw new Error("旅行后台任务没有返回 job id。");
        }
        const pending: PendingTravelJob = {
          jobId: data.job_id,
          query: data.query || question,
          context: data.context ?? nextContext,
          userMessage,
          startedAt: Date.now(),
          lastStatus: data.status ?? "queued",
        };
        savePendingTravelJob(pending);
        setPendingJob(pending);
        void pollTravelJob(pending);
        return;
      }

      const response = await fetch("/api/travel/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: nextMessages, context: nextContext }),
      });
      const data = (await response.json()) as {
        message?: TravelChatMessage;
        context?: TripContext;
      };
      if (!response.ok) {
        throw new Error(textFromMessage(data.message ?? fallbackErrorMessage()));
      }
      if (data.message) {
        setMessages((current) => [...current, data.message as TravelChatMessage]);
        setSelectedCardId(firstSelectableId(data.message));
        setPreviewCardId("");
        clearPreviewReset();
      }
      if (data.context) {
        setContext((current) => ({ ...current, ...data.context }));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "推荐接口暂时不可用。");
    } finally {
      setIsLoading(false);
    }
  }

  function updateContextChip(chipId: string) {
    const current = latestHeader.chips.find((chip) => chip.id === chipId)?.value ?? "";
    const next = window.prompt(chipId, current);
    if (next === null) return;
    setContext((currentContext) => contextWithChip(currentContext, chipId, next));
  }

  function toggleLike(card: TripCard) {
    setLikedCards((current) => {
      const next = { ...current };
      if (next[card.id]) delete next[card.id];
      else next[card.id] = card;
      return next;
    });
  }

  function addToTrip(card: TripCard) {
    setTripCards((current) => ({ ...current, [card.id]: card }));
  }

  const selectCard = useCallback((id: string) => {
    clearPreviewReset();
    setSelectedCardId(id);
    setPreviewCardId(id);
  }, []);

  return (
    <main className="h-dvh overflow-hidden overscroll-none bg-[#f7f6f2] text-neutral-950">
      <div
        className={
          shouldRenderMapPanel
            ? "grid h-full min-h-0 lg:grid-cols-[minmax(460px,42vw)_minmax(520px,1fr)]"
            : "grid h-full min-h-0 lg:grid-cols-[minmax(520px,760px)] lg:justify-center"
        }
        onPointerEnter={clearPreviewReset}
        onPointerLeave={schedulePreviewReset}
      >
        <section className="flex h-full min-h-0 flex-col overflow-hidden border-r border-neutral-200 bg-white">
          <TripHeader
            header={{
              ...latestHeader,
              trip_count: Object.keys(tripCards).length,
              chips: mergeHeaderChips(latestHeader, context),
            }}
            onChipClick={updateContextChip}
          />

          <div
            ref={viewportRef}
            data-testid="trip-message-viewport"
            className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 py-5"
          >
            <div className="mx-auto flex max-w-2xl flex-col gap-5" data-testid="trip-board">
              {messages.length === 0 ? <StarterPanel /> : null}
              {messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}
              {latestAnswerSections.length > 0 ? <AnswerSections sections={latestAnswerSections} /> : null}
              {latestHotelOffers.length > 0 || latestFlightOffers.length > 0 ? (
                <OfferSections hotelOffers={latestHotelOffers} flightOffers={latestFlightOffers} />
              ) : null}
              {latestCards.length > 0 ? (
                <TripCards
                  cards={latestCards}
                  selectedCardId={previewMapCardId}
                  likedCards={likedCards}
                  tripCards={tripCards}
                  imageIndexes={imageIndexes}
                  failedImages={failedImages}
                  onImageIndexChange={setImageIndexes}
                  onImageError={(url) =>
                    setFailedImages((current) => ({ ...current, [url]: true }))
                  }
                  onSelect={selectCard}
                  onPreview={previewCard}
                  onLike={toggleLike}
                  onAddToTrip={addToTrip}
                />
              ) : null}
              {latestWarnings.length > 0 ? <RuntimeWarnings warnings={latestWarnings} /> : null}
              {pendingJob ? (
                <TravelJobStatus
                  job={pendingJob}
                  onRetry={() => void pollTravelJob(pendingJob)}
                />
              ) : null}
              {error ? <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
            </div>
          </div>

          <Composer
            input={input}
            isLoading={isBusy}
            onInput={setInput}
            onSubmit={submitMessage}
          />
        </section>

        {shouldRenderMapPanel ? (
          <TravelMapPanel
            map={latestMap}
            cards={latestCards}
            selectedCardId={selectedMapCardId}
            previewCardId={previewMapCardId}
            onSelect={selectCard}
            onPreview={previewCard}
          />
        ) : null}
      </div>
    </main>
  );
}

function AnswerSections({ sections }: { sections: TripAnswerSection[] }) {
  if (!sections.length) return null;
  return (
    <section
      className="overflow-hidden border-y border-neutral-200 bg-white"
      data-testid="trip-answer-sections"
    >
      {sections.map((section) => (
        <article
          key={section.id}
          data-testid={`trip-answer-section-${section.id}`}
          className="border-b border-neutral-100 px-1 py-4 last:border-b-0"
        >
          <div className="mb-2">
            <h2 className="text-sm font-semibold tracking-normal text-neutral-950">{section.title}</h2>
          </div>
          {section.body ? (
            <p className="text-sm leading-6 text-neutral-800">{section.body}</p>
          ) : null}
          {section.bullets.length > 0 ? (
            <ul className="mt-2 grid gap-1.5">
              {section.bullets.map((bullet) => (
                <li key={bullet} className="flex gap-2 text-sm leading-6 text-neutral-700">
                  <span className="mt-2.5 size-1 shrink-0 rounded-full bg-neutral-400" />
                  <span>{bullet}</span>
                </li>
              ))}
            </ul>
          ) : null}
          {section.tables?.length ? (
            <div className="mt-3 grid gap-3" data-testid={`trip-answer-section-${section.id}-tables`}>
              {section.tables.map((table, tableIndex) => (
                <div key={`${section.id}-table-${tableIndex}`} className="overflow-hidden rounded-md border border-neutral-200">
                  {table.caption ? (
                    <div className="border-b border-neutral-100 bg-neutral-50 px-3 py-2 text-xs font-medium text-neutral-700">
                      {table.caption}
                    </div>
                  ) : null}
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[360px] text-left text-xs text-neutral-700">
                      {table.columns.length ? (
                        <thead className="bg-neutral-50 text-neutral-500">
                          <tr>
                            {table.columns.map((column) => (
                              <th key={column} scope="col" className="px-3 py-2 font-medium">
                                {column}
                              </th>
                            ))}
                          </tr>
                        </thead>
                      ) : null}
                      <tbody>
                        {table.rows.map((row, rowIndex) => (
                          <tr key={`${section.id}-row-${rowIndex}`} className="border-t border-neutral-100">
                            {row.map((cell, cellIndex) => (
                              <td key={`${section.id}-cell-${rowIndex}-${cellIndex}`} className="px-3 py-2 align-top">
                                {cell}
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
            <div className="mt-3 grid grid-cols-2 gap-2" data-testid={`trip-answer-section-${section.id}-images`}>
              {section.images.map((image) => (
                <figure key={image.url} className="overflow-hidden rounded-md border border-neutral-100 bg-neutral-50">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={image.url} alt={image.caption || section.title} className="aspect-[4/3] w-full object-cover" />
                  {image.caption ? (
                    <figcaption className="px-2 py-1.5 text-xs text-neutral-500">{image.caption}</figcaption>
                  ) : null}
                </figure>
              ))}
            </div>
          ) : null}
        </article>
      ))}
    </section>
  );
}

function OfferSections({
  hotelOffers,
  flightOffers,
}: {
  hotelOffers: TripHotelOffer[];
  flightOffers: TripFlightOffer[];
}) {
  return (
    <section className="flex flex-col gap-4" data-testid="trip-offers">
      {hotelOffers.length > 0 ? (
        <OfferGroup title="酒店选择" subtitle="Hotel offers">
          {hotelOffers.map((offer) => (
            <HotelOfferCard key={offer.id} offer={offer} />
          ))}
        </OfferGroup>
      ) : null}
      {flightOffers.length > 0 ? (
        <OfferGroup title="航班选择" subtitle="Flight offers">
          {flightOffers.map((offer) => (
            <FlightOfferCard key={offer.id} offer={offer} />
          ))}
        </OfferGroup>
      ) : null}
    </section>
  );
}

function OfferGroup({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-[28px] border border-neutral-200 bg-white p-4 shadow-[0_16px_45px_rgba(15,23,42,0.06)]">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="text-xs text-neutral-500">{subtitle}</span>
      </div>
      <div className="grid gap-3">{children}</div>
    </div>
  );
}

function HotelOfferCard({ offer }: { offer: TripHotelOffer }) {
  const image = offer.image_urls?.[0] ?? offer.image_url ?? "";
  return (
    <article className="grid gap-3 rounded-[24px] border border-neutral-100 bg-[#fbfaf7] p-3 sm:grid-cols-[1fr_140px]">
      <div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
          {offer.price ? <span>{offer.price}</span> : null}
          {offer.rating ? <span>★ {offer.rating}{offer.review_count ? ` · ${offer.review_count} reviews` : ""}</span> : null}
        </div>
        <h3 className="mt-1 text-sm font-semibold">{offer.title}</h3>
        {offer.address ? <p className="mt-1 text-xs text-neutral-500">{offer.address}</p> : null}
        <p className="mt-3 text-sm leading-6 text-neutral-800">
          {offer.display_reason || "住宿推荐理由：可作为酒店候选，建议结合价格、位置和交通继续比较。"}
        </p>
        <OfferLinks sourceUrl={offer.source_url} bookingUrl={offer.booking_url} />
      </div>
      {image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={image} alt={offer.title} className="h-28 w-full rounded-[20px] object-cover" />
      ) : null}
    </article>
  );
}

function FlightOfferCard({ offer }: { offer: TripFlightOffer }) {
  return (
    <article className="rounded-[24px] border border-neutral-100 bg-[#fbfaf7] p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500">
        {offer.price ? <span>{offer.price}</span> : null}
        {offer.duration ? <span>{offer.duration}</span> : null}
        {offer.airline ? <span>{offer.airline}</span> : null}
      </div>
      <h3 className="mt-1 text-sm font-semibold">{offer.title}</h3>
      {[offer.departure_airport, offer.arrival_airport].filter(Boolean).length > 0 ? (
        <p className="mt-1 text-xs text-neutral-500">
          {[offer.departure_airport, offer.arrival_airport].filter(Boolean).join(" → ")}
        </p>
      ) : null}
      <p className="mt-3 text-sm leading-6 text-neutral-800">
        {offer.display_reason || "航班推荐理由：可作为航班候选，建议结合时间、价格和中转次数继续比较。"}
      </p>
      <OfferLinks sourceUrl={offer.source_url} bookingUrl={offer.booking_url} />
    </article>
  );
}

function OfferLinks({
  sourceUrl,
  bookingUrl,
}: {
  sourceUrl?: string;
  bookingUrl?: string;
}) {
  const links = [
    { label: "Source", href: sourceUrl },
    { label: "Open offer", href: bookingUrl && bookingUrl !== sourceUrl ? bookingUrl : "" },
  ].filter((link): link is { label: string; href: string } => Boolean(link.href));
  if (!links.length) return null;
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {links.map((link) => (
        <a
          key={`${link.label}-${link.href}`}
          href={link.href}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 rounded-full border border-neutral-200 px-3 py-1.5 text-xs text-neutral-700 hover:border-neutral-400"
        >
          {link.label} <ArrowRight size={13} />
        </a>
      ))}
    </div>
  );
}

function TripHeader({
  header,
  onChipClick,
}: {
  header: TripHeaderPart;
  onChipClick: (chipId: string) => void;
}) {
  return (
    <MiraAppHeader
      subtitle={header.subtitle || "识境"}
      chips={header.chips}
      tripCount={header.trip_count}
      primaryAction={{
        href: "/visual",
        label: "Mira",
        icon: <Camera size={14} />,
      }}
      iconAction={{
        label: "分享",
        icon: <Share2 size={15} />,
      }}
      onChipClick={onChipClick}
    />
  );
}

function StarterPanel() {
  return (
    <section data-testid="starter-panel" className="rounded-[28px] border border-neutral-200 bg-[#fbfaf7] p-5 shadow-[0_12px_32px_rgba(15,23,42,0.04)]">
      <p className="text-sm leading-6 text-neutral-700 sm:hidden">
        问 Mira，比如福冈好玩、美食、购物或路线。
      </p>
      <p className="hidden text-sm leading-6 text-neutral-700 sm:block">
        问 Mira，比如“福冈有什么好玩的？”、“福冈有什么好吃的日料？”或“福冈买香水去哪”。需要更精确时，再补 Where / When / Who / Budget / Preferences。
      </p>
    </section>
  );
}

function MessageBubble({ message }: { message: TravelChatMessage }) {
  const text = textFromMessage(message);
  if (!text) return null;
  return (
    <article className={message.role === "user" ? "flex justify-end" : "flex justify-start"}>
      <div
        className={
          message.role === "user"
            ? "max-w-[78%] whitespace-pre-line rounded-[26px] bg-neutral-950 px-4 py-3 text-sm leading-6 text-white"
            : "max-w-[72ch] whitespace-pre-line rounded-[26px] bg-white px-4 py-3 text-sm leading-6 text-neutral-900 shadow-sm ring-1 ring-neutral-200"
        }
      >
        {text}
      </div>
    </article>
  );
}

function TripCards({
  cards,
  selectedCardId,
  likedCards,
  tripCards,
  imageIndexes,
  failedImages,
  onImageIndexChange,
  onImageError,
  onSelect,
  onPreview,
  onLike,
  onAddToTrip,
}: {
  cards: TripCard[];
  selectedCardId: string;
  likedCards: Record<string, TripCard>;
  tripCards: Record<string, TripCard>;
  imageIndexes: Record<string, number>;
  failedImages: Record<string, boolean>;
  onImageIndexChange: Dispatch<SetStateAction<Record<string, number>>>;
  onImageError: (url: string) => void;
  onSelect: (id: string) => void;
  onPreview: (id: string) => void;
  onLike: (card: TripCard) => void;
  onAddToTrip: (card: TripCard) => void;
}) {
  return (
    <section className="flex flex-col gap-3">
      {cards.map((card) => {
        const images = cardImages(card).filter((url) => !failedImages[url]);
        const index = imageIndexes[card.id] ?? 0;
        const currentImage = images[index] ?? "";
        const hasImage = Boolean(currentImage);
        const active = selectedCardId === card.id;
        const liked = Boolean(likedCards[card.id]);
        const planned = Boolean(tripCards[card.id]);
        const changeImageBy = (delta: number) => {
          onImageIndexChange((current) => {
            const currentIndex = current[card.id] ?? 0;
            return {
              ...current,
              [card.id]: (currentIndex + delta + images.length) % images.length,
            };
          });
        };
        const selectImageIndex = (nextIndex: number) => {
          onImageIndexChange((current) => ({
            ...current,
            [card.id]: nextIndex,
          }));
        };
        return (
          <article
            key={card.id}
            data-testid={`trip-card-${card.id}`}
            role="button"
            tabIndex={0}
            onClick={() => onSelect(card.id)}
            onPointerEnter={() => onPreview(card.id)}
            onFocus={() => onPreview(card.id)}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") onSelect(card.id);
            }}
            className={`grid gap-4 border-b border-neutral-200 py-5 outline-none transition ${
              hasImage ? "sm:grid-cols-[1fr_220px]" : ""
            } ${
              active ? "bg-sky-50/45" : "bg-white"
            }`}
          >
            <div className="min-w-0 px-1">
              <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-neutral-500">
                {card.category ? <span>{card.category}</span> : null}
                {card.subcategory ? <span>{card.subcategory}</span> : null}
                {card.price ? <span>{card.price}</span> : null}
                {ratingText(card) ? <span>★ {ratingText(card)}</span> : null}
              </div>
              <h2 className="text-base font-semibold tracking-normal">{card.title}</h2>
              {card.subtitle ? <p className="mt-1 text-sm text-neutral-500">{card.subtitle}</p> : null}
              <p className="mt-4 text-sm leading-6 text-neutral-800">
                {recommendationText(card)}
              </p>
              {card.address ? <p className="mt-3 text-xs text-neutral-500">{card.address}</p> : null}
              <div className="mt-4 flex flex-wrap gap-2">
                <IconButton active={liked} label="Like" onClick={(event) => actionClick(event, () => onLike(card))}>
                  <Heart size={15} />
                </IconButton>
                <IconButton active={planned} label="Add to Trip" onClick={(event) => actionClick(event, () => onAddToTrip(card))}>
                  <Plus size={15} />
                </IconButton>
                {card.google_maps_uri ? (
                  <a
                    href={card.google_maps_uri}
                    target="_blank"
                    rel="noreferrer"
                    onClick={(event) => event.stopPropagation()}
                    className="inline-flex items-center gap-1 rounded-full border border-neutral-200 px-3 py-1.5 text-xs text-neutral-700 hover:border-neutral-400"
                  >
                    Google Maps <ArrowRight size={13} />
                  </a>
                ) : null}
                <a
                  href={mapboxPlaceUri(card)}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(event) => event.stopPropagation()}
                  className="inline-flex items-center gap-1 rounded-full border border-neutral-200 px-3 py-1.5 text-xs text-neutral-700 hover:border-neutral-400"
                >
                  Mapbox <ArrowRight size={13} />
                </a>
              </div>
            </div>

            {hasImage ? (
              <div className="relative h-44 overflow-hidden rounded-[24px] bg-neutral-100 sm:h-40">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={currentImage}
                  alt={card.title}
                  className="h-full w-full object-cover"
                  onError={() => onImageError(currentImage)}
                />
                {images.length > 1 ? (
                  <>
                    <button
                      type="button"
                      aria-label={`${card.title} 上一张图片`}
                      data-testid={`image-prev-${card.id}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        changeImageBy(-1);
                      }}
                      className="absolute left-2 top-1/2 grid size-11 -translate-y-1/2 touch-manipulation place-items-center rounded-full bg-white/90 shadow sm:size-8"
                    >
                      <ChevronLeft size={16} />
                    </button>
                    <button
                      type="button"
                      aria-label={`${card.title} 下一张图片`}
                      data-testid={`image-next-${card.id}`}
                      onClick={(event) => {
                        event.stopPropagation();
                        changeImageBy(1);
                      }}
                      className="absolute right-2 top-1/2 grid size-11 -translate-y-1/2 touch-manipulation place-items-center rounded-full bg-white/90 shadow sm:size-8"
                    >
                      <ChevronRight size={16} />
                    </button>
                    <div className="absolute bottom-2 left-0 right-0 flex justify-center gap-1.5">
                      {images.map((image, dotIndex) => (
                        <button
                          key={image}
                          type="button"
                          aria-label={`${card.title} 第 ${dotIndex + 1} 张图片`}
                          data-testid={`image-dot-${card.id}-${dotIndex}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            selectImageIndex(dotIndex);
                          }}
                          className="grid size-5 touch-manipulation place-items-center rounded-full"
                        >
                          <span
                            className={`size-1.5 rounded-full ${
                              dotIndex === index ? "bg-white" : "bg-white/50"
                            }`}
                          />
                        </button>
                      ))}
                    </div>
                  </>
                ) : null}
              </div>
            ) : null}
          </article>
        );
      })}
    </section>
  );
}

function TravelMapPanel({
  map,
  cards,
  selectedCardId,
  previewCardId,
  onSelect,
  onPreview,
}: {
  map: TripMap;
  cards: TripCard[];
  selectedCardId: string;
  previewCardId: string;
  onSelect: (id: string) => void;
  onPreview: (id: string) => void;
}) {
  const mapboxRef = useRef<HTMLDivElement | null>(null);
  const leafletRef = useRef<HTMLDivElement | null>(null);
  const pins = map.pins ?? [];
  const hasPins = pins.length > 0;
  const selectedPin = pins.find((pin) => pin.id === selectedCardId) ?? pins[0];
  const previewPin = pins.find((pin) => pin.id === previewCardId) ?? selectedPin;
  const selectedCard = cards.find((card) => card.id === previewPin?.id) ?? cards.find((card) => card.id === selectedPin?.id) ?? cards[0];
  const staticMapKey = `${pins.length}:${selectedCardId || selectedPin?.id || ""}`;
  const [failedTileMapKey, setFailedTileMapKey] = useState("");
  const tileMapFailed = failedTileMapKey === staticMapKey;

  useMapboxMap(mapboxRef, map, selectedCardId, previewCardId, onSelect, onPreview);
  useLeafletMap(
    leafletRef,
    map,
    selectedCardId,
    previewCardId,
    onSelect,
    onPreview,
    hasPins && !mapboxAccessToken && !tileMapFailed,
    () => setFailedTileMapKey(staticMapKey),
  );

  return (
    <aside className="sticky top-0 isolate hidden h-screen bg-[#f4f1ea] lg:block" data-testid="trip-map-panel">
      {hasPins && mapboxAccessToken ? (
        <div ref={mapboxRef} data-testid="mapbox-map" className="relative z-0 h-full w-full" />
      ) : hasPins && !tileMapFailed ? (
        <div ref={leafletRef} data-testid="leaflet-map" className="relative z-0 h-full w-full" />
      ) : hasPins ? (
        <MapboxStaticMap
          map={map}
          activeCardId={selectedCardId}
          onError={() => undefined}
        />
      ) : (
        <EmptyMapPlaceholder />
      )}
      {hasPins ? (
        <div className="pointer-events-none absolute left-4 top-4 z-[1100] rounded-full bg-white/95 px-3 py-2 text-xs font-medium text-neutral-700 shadow">
          {pins.length} places mapped
        </div>
      ) : null}
      {hasPins && selectedCard ? <MapInlinePopup card={selectedCard} /> : null}
    </aside>
  );
}

function MapboxStaticMap({
  map,
  activeCardId,
  onError,
}: {
  map: TripMap;
  activeCardId: string;
  onError: () => void;
}) {
  return (
    <div className="absolute inset-0 z-0 overflow-hidden bg-[#e8efeb]">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        data-testid="mapbox-static-map"
        src={mapboxStaticMapUri(map, activeCardId)}
        alt="Mapbox map preview"
        className="h-full w-full object-cover"
        onError={onError}
      />
    </div>
  );
}

function EmptyMapPlaceholder() {
  return (
    <div
      data-testid="empty-map-placeholder"
      className="grid h-full w-full place-items-center bg-[#f4f1ea]"
    >
      <div className="w-64 rounded-[24px] border border-neutral-200 bg-white/80 p-5 text-center shadow-sm">
        <p className="text-sm font-medium text-neutral-800">地图待生成</p>
        <p className="mt-2 text-xs leading-5 text-neutral-500">问一个目的地后，推荐会落到右侧地图。</p>
      </div>
    </div>
  );
}

function MapInlinePopup({ card }: { card: TripCard }) {
  const image = cardImages(card)[0] ?? "";
  return (
    <div
      data-testid="map-inline-popup"
      className="photo-agent-mapbox-popup pointer-events-none absolute right-5 top-20 z-[1200] w-64 overflow-hidden rounded-[24px] bg-white shadow-xl ring-1 ring-neutral-200"
    >
      {image ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={image} alt="" className="h-24 w-full object-cover" />
      ) : null}
      <div className="p-3">
        <p className="text-sm font-semibold text-neutral-950">{card.title}</p>
        <p className="mt-1 text-xs text-neutral-500">
          {[card.category, card.subcategory, ratingText(card)].filter(Boolean).join(" · ")}
        </p>
        <p className="mt-2 line-clamp-3 text-xs leading-5 text-neutral-700">{recommendationText(card)}</p>
      </div>
    </div>
  );
}

function Composer({
  input,
  isLoading,
  onInput,
  onSubmit,
}: {
  input: string;
  isLoading: boolean;
  onInput: (value: string) => void;
  onSubmit: () => void;
}) {
  const [isComposing, setIsComposing] = useState(false);

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    const composing =
      isComposing ||
      event.nativeEvent.isComposing ||
      ("keyCode" in event.nativeEvent && event.nativeEvent.keyCode === 229);
    if (event.key === "Enter" && !event.shiftKey && !composing) {
      event.preventDefault();
      onSubmit();
    }
  }

  return (
    <div className="shrink-0 border-t border-neutral-200 bg-white px-6 py-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
      <form
        className="mx-auto flex max-w-3xl items-end gap-2 rounded-3xl border border-neutral-200 bg-white p-2 shadow-sm"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <button type="button" aria-label="添加" className="grid size-9 place-items-center rounded-full hover:bg-neutral-100">
          <Plus size={18} />
        </button>
        <textarea
          placeholder="Ask anything"
          value={input}
          onChange={(event) => onInput(event.target.value)}
          onCompositionStart={() => setIsComposing(true)}
          onCompositionEnd={() => setIsComposing(false)}
          onKeyDown={handleKeyDown}
          rows={1}
          className="max-h-32 min-h-9 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none"
        />
        <button
          type="submit"
          aria-label="发送"
          disabled={isLoading}
          className="grid size-9 place-items-center rounded-full bg-neutral-950 text-white disabled:opacity-50"
        >
          {isLoading ? <Loader2 size={17} className="animate-spin" /> : <Send size={16} />}
        </button>
      </form>
    </div>
  );
}

function TravelJobStatus({
  job,
  onRetry,
}: {
  job: PendingTravelJob;
  onRetry: () => void;
}) {
  return (
    <section
      data-testid="travel-job-status"
      className="rounded-[24px] border border-sky-200 bg-sky-50 p-4 text-sm leading-6 text-sky-900"
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="font-medium">旅行推荐正在后台生成</p>
          <p className="mt-1 text-xs text-sky-800">
            锁屏或切换网络后，回到页面会继续检查结果。
            {job.lastStatus ? ` 当前状态：${job.lastStatus}` : ""}
          </p>
        </div>
        <button
          type="button"
          onClick={onRetry}
          className="shrink-0 rounded-full border border-sky-300 px-3 py-1.5 text-xs font-medium hover:bg-white"
        >
          继续检查
        </button>
      </div>
    </section>
  );
}

function RuntimeWarnings({ warnings }: { warnings: string[] }) {
  return (
    <section className="rounded-[24px] border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-800">
      {warnings.map((warning) => (
        <p key={warning}>{warning}</p>
      ))}
    </section>
  );
}

function IconButton({
  active,
  label,
  children,
  onClick,
}: {
  active: boolean;
  label: string;
  children: ReactNode;
  onClick: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className={`inline-flex items-center gap-1 rounded-full border px-3 py-1.5 text-xs ${
        active
          ? "border-sky-700 bg-sky-700 text-white"
          : "border-neutral-200 text-neutral-700 hover:border-neutral-400"
      }`}
    >
      {children}
      {label}
    </button>
  );
}

function useMapboxMap(
  mapRef: RefObject<HTMLDivElement | null>,
  map: TripMap,
  selectedCardId: string,
  previewCardId: string,
  onSelect: (id: string) => void,
  onPreview: (id: string) => void,
) {
  const mapInstanceRef = useRef<MapboxMapInstance | null>(null);
  const markersRef = useRef<Array<{ id: string; element: HTMLButtonElement; marker: MapboxMarker }>>([]);
  const onSelectRef = useRef(onSelect);
  const onPreviewRef = useRef(onPreview);
  const pins = useMemo(() => map.pins ?? [], [map.pins]);
  const pinKey = useMemo(
    () => pins.map((pin) => `${pin.id}:${pin.lat}:${pin.lng}`).join("|"),
    [pins],
  );
  const initialCenter = useMemo(
    () => map.center ?? { lat: pins[0]?.lat ?? 0, lng: pins[0]?.lng ?? 0 },
    [map.center, pins],
  );

  useEffect(() => {
    onSelectRef.current = onSelect;
    onPreviewRef.current = onPreview;
  }, [onPreview, onSelect]);

  useEffect(() => {
    if (!mapboxAccessToken || !mapRef.current || !pins.length) return;
    let cancelled = false;
    const container = mapRef.current;
    container.dataset.mapboxReady = "loading";

    import("mapbox-gl")
      .then((loadedMapbox) => {
        if (cancelled || !container) return;
        const mapboxgl = loadedMapbox.default;
        mapboxgl.accessToken = mapboxAccessToken;
        container.innerHTML = "";
        const mapboxMap = new mapboxgl.Map({
          container,
          style: "mapbox://styles/mapbox/streets-v12",
          center: [initialCenter.lng, initialCenter.lat],
          zoom: pins.length === 1 ? 14 : 12,
          attributionControl: false,
        });
        mapboxMap.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "bottom-right");
        mapInstanceRef.current = mapboxMap;
        container.dataset.mapboxReady = "true";

        const bounds = new mapboxgl.LngLatBounds();
        markersRef.current = pins.map((pin, index) => {
          const element = document.createElement("button");
          element.type = "button";
          element.textContent = String(index + 1);
          element.title = pin.title;
          element.setAttribute("aria-label", pin.title);
          element.setAttribute("data-testid", `mapbox-marker-${pin.id}`);
          styleMapboxMarker(element, false);
          element.addEventListener("click", () => onSelectRef.current(pin.id));
          element.addEventListener("mouseenter", () => onPreviewRef.current(pin.id));
          const marker = new mapboxgl.Marker({ element, anchor: "center" })
            .setLngLat([pin.lng, pin.lat])
            .addTo(mapboxMap);
          bounds.extend([pin.lng, pin.lat]);
          return { id: pin.id, element, marker };
        });

        mapboxMap.once("load", () => {
          if (pins.length > 1) {
            mapboxMap.fitBounds(bounds, { padding: 86, maxZoom: 14, duration: 0 });
          }
        });
      })
      .catch((error) => {
        container.dataset.mapboxReady = "error";
        container.dataset.mapboxError = error instanceof Error ? error.message : String(error);
      });

    return () => {
      cancelled = true;
      markersRef.current.forEach(({ marker }) => marker.remove());
      markersRef.current = [];
      mapInstanceRef.current?.remove();
      mapInstanceRef.current = null;
      container.dataset.mapboxReady = "";
    };
  }, [initialCenter, mapRef, pinKey, pins]);

  useEffect(() => {
    const mapboxMap = mapInstanceRef.current;
    if (!mapboxMap || !pins.length) return;
    const selected = pins.find((pin) => pin.id === selectedCardId) ?? pins[0];
    mapboxMap.panTo([selected.lng, selected.lat], { duration: 260 });
  }, [selectedCardId, pins]);

  useEffect(() => {
    if (!pins.length) return;
    const preview = pins.find((pin) => pin.id === previewCardId) ?? pins.find((pin) => pin.id === selectedCardId) ?? pins[0];
    markersRef.current.forEach(({ id, element }) => styleMapboxMarker(element, id === preview.id));
  }, [previewCardId, selectedCardId, pins]);
}

function useLeafletMap(
  mapRef: RefObject<HTMLDivElement | null>,
  map: TripMap,
  selectedCardId: string,
  previewCardId: string,
  onSelect: (id: string) => void,
  onPreview: (id: string) => void,
  enabled: boolean,
  onError: () => void,
) {
  const mapInstanceRef = useRef<LeafletMapInstance | null>(null);
  const leafletModuleRef = useRef<LeafletImport | null>(null);
  const markersRef = useRef<Array<{ id: string; index: number; marker: LeafletMarker }>>([]);
  const onSelectRef = useRef(onSelect);
  const onPreviewRef = useRef(onPreview);
  const onErrorRef = useRef(onError);
  const pins = useMemo(() => map.pins ?? [], [map.pins]);
  const pinKey = useMemo(
    () => pins.map((pin) => `${pin.id}:${pin.lat}:${pin.lng}`).join("|"),
    [pins],
  );
  const initialCenter = useMemo(
    () => map.center ?? { lat: pins[0]?.lat ?? 0, lng: pins[0]?.lng ?? 0 },
    [map.center, pins],
  );

  useEffect(() => {
    onSelectRef.current = onSelect;
    onPreviewRef.current = onPreview;
    onErrorRef.current = onError;
  }, [onError, onPreview, onSelect]);

  useEffect(() => {
    if (!enabled || !mapRef.current || !pins.length) return;
    let cancelled = false;
    const container = mapRef.current;
    container.dataset.leafletReady = "loading";

    import("leaflet")
      .then((loadedLeaflet) => {
        if (cancelled || !container) return;
        const leafletImport = loadedLeaflet as LeafletImport;
        const leaflet = leafletImport.default ?? leafletImport;
        leafletModuleRef.current = leafletImport;
        container.innerHTML = "";
        const leafletMap = leaflet.map(container, {
          attributionControl: false,
          zoomControl: false,
          scrollWheelZoom: true,
        });
        leafletMap.setView([initialCenter.lat, initialCenter.lng], pins.length === 1 ? 14 : 12);
        leaflet
          .tileLayer("/api/mapbox/tile/{z}/{x}/{y}", {
            tileSize: 256,
            minZoom: 2,
            maxZoom: 18,
          })
          .addTo(leafletMap);
        leaflet.control.zoom({ position: "bottomright" }).addTo(leafletMap);

        const bounds = leaflet.latLngBounds([]);
        markersRef.current = pins.map((pin, index) => {
          const marker = leaflet
            .marker([pin.lat, pin.lng], {
              icon: leafletMarkerIcon(leaflet, index, false),
              keyboard: true,
              title: pin.title,
            })
            .on("click", () => {
              onSelectRef.current(pin.id);
            })
            .on("mouseover", () => {
              onPreviewRef.current(pin.id);
            })
            .addTo(leafletMap);
          bounds.extend([pin.lat, pin.lng]);
          return { id: pin.id, index, marker };
        });
        if (pins.length > 1 && bounds.isValid()) {
          leafletMap.fitBounds(bounds, { padding: [86, 86], maxZoom: 14, animate: false });
        }
        mapInstanceRef.current = leafletMap;
        container.dataset.leafletReady = "true";
      })
      .catch((error) => {
        container.dataset.leafletReady = "error";
        container.dataset.leafletError = error instanceof Error ? error.message : String(error);
        onErrorRef.current();
      });

    return () => {
      cancelled = true;
      markersRef.current.forEach(({ marker }) => marker.remove());
      markersRef.current = [];
      mapInstanceRef.current?.remove();
      mapInstanceRef.current = null;
      container.dataset.leafletReady = "";
    };
  }, [enabled, initialCenter, mapRef, pinKey, pins]);

  useEffect(() => {
    const leafletMap = mapInstanceRef.current;
    if (!enabled || !leafletMap || !pins.length) return;
    const selected = pins.find((pin) => pin.id === selectedCardId) ?? pins[0];
    leafletMap.panTo([selected.lat, selected.lng], { animate: true, duration: 0.25 });
  }, [selectedCardId, enabled, pins]);

  useEffect(() => {
    const loadedLeaflet = leafletModuleRef.current;
    if (!enabled || !loadedLeaflet || !pins.length) return;
    const leaflet = loadedLeaflet.default ?? loadedLeaflet;
    const preview = pins.find((pin) => pin.id === previewCardId) ?? pins.find((pin) => pin.id === selectedCardId) ?? pins[0];
    markersRef.current.forEach(({ id, index, marker }) =>
      marker.setIcon(leafletMarkerIcon(leaflet, index, id === preview.id)),
    );
  }, [previewCardId, selectedCardId, enabled, pins]);
}

function leafletMarkerIcon(leaflet: LeafletModule, index: number, active: boolean) {
  const size = 32;
  return leaflet.divIcon({
    className: "",
    html: `<div style="
      display:grid;place-items:center;width:${size}px;height:${size}px;
      border-radius:999px;border:${active ? 4 : 3}px solid ${active ? "#e0f2fe" : "#ffffff"};
      background:${active ? "#0369a1" : "#111827"};color:#fff;font-size:${active ? 13 : 12}px;
      font-weight:700;box-shadow:${active ? "0 16px 30px rgba(3,105,161,.28)" : "0 10px 20px rgba(17,24,39,.2)"};
    ">${index + 1}</div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
}

function styleMapboxMarker(element: HTMLButtonElement, active: boolean) {
  element.style.width = "32px";
  element.style.height = "32px";
  element.style.borderRadius = "999px";
  element.style.border = active ? "4px solid #e0f2fe" : "3px solid #ffffff";
  element.style.background = active ? "#0369a1" : "#111827";
  element.style.color = "#ffffff";
  element.style.fontSize = active ? "13px" : "12px";
  element.style.fontWeight = "700";
  element.style.boxShadow = active
    ? "0 16px 30px rgba(3,105,161,.28)"
    : "0 10px 20px rgba(17,24,39,.2)";
  element.style.cursor = "pointer";
}

function latestPart<T extends TravelChatPart["type"]>(
  messages: TravelChatMessage[],
  type: T,
): Extract<TravelChatPart, { type: T }> | undefined {
  for (const message of [...messages].reverse()) {
    if (message.role !== "assistant") continue;
    const part = [...message.parts].reverse().find((item) => item.type === type);
    if (part) return part as Extract<TravelChatPart, { type: T }>;
  }
  return undefined;
}

function firstSelectableId(message: TravelChatMessage): string {
  const mapPart = message.parts.find((part) => part.type === "trip-map");
  if (mapPart?.type === "trip-map" && mapPart.map.selected_pin_id) {
    return mapPart.map.selected_pin_id;
  }
  const cardsPart = message.parts.find((part) => part.type === "trip-cards");
  if (cardsPart?.type === "trip-cards") {
    return cardsPart.cards[0]?.id ?? "";
  }
  return "";
}

function emptyMap(): TripMap {
  return {
    provider: "mapbox",
    mode: "mapbox_gl",
    center: { lat: 33.5902, lng: 130.4017 },
    selected_pin_id: "",
    status: "empty",
    pins: [],
  };
}

function shouldShowMapPanel(messageCount: number, map: TripMap, cards: TripCard[]): boolean {
  if (messageCount === 0) return true;
  if (map.status === "answer_only") return false;
  const pins = map.pins ?? [];
  if (pins.length > 0) return true;
  return cards.some(
    (card) =>
      typeof card.lat === "number" &&
      Number.isFinite(card.lat) &&
      typeof card.lng === "number" &&
      Number.isFinite(card.lng),
  );
}

function mapboxPlaceUri(card: TripCard): string {
  if (card.mapbox_uri) {
    return card.mapbox_uri;
  }
  const lat = Number(card.lat);
  const lng = Number(card.lng);
  if (Number.isFinite(lat) && Number.isFinite(lng) && mapboxAccessToken) {
    return `https://api.mapbox.com/styles/v1/mapbox/streets-v12.html?${new URLSearchParams({
      title: "false",
      zoomwheel: "true",
      access_token: mapboxAccessToken,
    })}#15/${lat}/${lng}`;
  }
  const query = [card.title, card.address].filter(Boolean).join(" ");
  return `https://www.mapbox.com/search/?query=${encodeURIComponent(query || card.title)}`;
}

function mapboxStaticMapUri(map: TripMap, activeCardId: string): string {
  const pins = (map.pins ?? []).slice(0, 12);
  const selectedIndex = Math.max(
    0,
    pins.findIndex((pin) => pin.id === activeCardId),
  );
  const params = new URLSearchParams({
    pins: pins.map((pin) => `${pin.lat},${pin.lng}`).join("|"),
    selected: String(selectedIndex),
    width: "1200",
    height: "900",
  });
  return `/api/mapbox/static-map?${params}`;
}

function fallbackErrorMessage(): TravelChatMessage {
  return {
    id: "error",
    role: "assistant",
    parts: [{ type: "text", text: "推荐接口暂时不可用。" }],
  };
}

function travelJobFailureMessage(error?: TravelJobStatusResponse["error"]): TravelChatMessage {
  return {
    id: `assistant-${Date.now()}`,
    role: "assistant",
    parts: [
      {
        type: "text",
        text: "这次旅行推荐后台任务没有完成。我保留了你的问题，可以稍后重试。",
      },
      {
        type: "runtime-warnings",
        warnings: [jobErrorText({ error }, 502)],
      },
    ],
  };
}

function jobErrorText(data: Pick<TravelJobStatusResponse, "error">, status?: number): string {
  const error = data.error;
  return [
    status ? `Backend HTTP ${status}` : "",
    error?.failed_stage ? `stage=${error.failed_stage}` : "",
    error?.model ? `model=${error.model}` : "",
    error?.message ? `message=${error.message}` : "",
  ]
    .filter(Boolean)
    .join(" | ") || "旅行推荐后台任务失败。";
}

function shouldUseTravelBackgroundJobs(): boolean {
  if (typeof window === "undefined") {
    return false;
  }
  const userAgent = window.navigator.userAgent;
  return (
    /iPhone|iPad|Android|Mobile|PhotoAgentShell/i.test(userAgent) ||
    window.innerWidth < 768 ||
    window.matchMedia("(pointer: coarse)").matches
  );
}

function savePendingTravelJob(job: PendingTravelJob): void {
  try {
    window.localStorage.setItem(pendingTravelJobStorageKey, JSON.stringify(job));
  } catch {
    // Best-effort resume state; live React state still carries the job.
  }
}

function loadPendingTravelJob(): PendingTravelJob | null {
  try {
    const raw = window.localStorage.getItem(pendingTravelJobStorageKey);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as PendingTravelJob;
    if (!parsed.jobId || !parsed.query || !parsed.userMessage) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function clearStoredPendingTravelJob(): void {
  try {
    window.localStorage.removeItem(pendingTravelJobStorageKey);
  } catch {
    // Nothing to clean up if storage is unavailable.
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function mergeHeaderChips(header: TripHeaderPart, context: TripContext) {
  return header.chips.map((chip) => {
    if (chip.id === "Where") return { ...chip, value: context.city || chip.value };
    if (chip.id === "When") return { ...chip, value: context.when || chip.value };
    if (chip.id === "Who") return { ...chip, value: context.who || chip.value };
    if (chip.id === "Budget") return { ...chip, value: context.budget || chip.value };
    if (chip.id === "Preferences") {
      const value = (context.preferences ?? []).join(", ");
      return { ...chip, value: value || chip.value };
    }
    return chip;
  });
}

function contextWithChip(context: TripContext, chipId: string, value: string): TripContext {
  if (chipId === "Where") return { ...context, city: value, where: value };
  if (chipId === "When") return { ...context, when: value };
  if (chipId === "Who") return { ...context, who: value };
  if (chipId === "Budget") return { ...context, budget: value };
  if (chipId === "Preferences") {
    return {
      ...context,
      preferences: value
        .split(/,|，|、/)
        .map((item) => item.trim())
        .filter(Boolean),
    };
  }
  return context;
}

function contextWithSessionMemory(
  context: TripContext,
  cards: TripCard[],
  map: TripMap,
  likedCards: Record<string, TripCard>,
  tripCards: Record<string, TripCard>,
  selectedCardId: string,
): TripContext {
  const likedItems = Object.values(likedCards);
  const tripItems = Object.values(tripCards);
  return {
    ...context,
    likedItems,
    tripItems,
    lastCards: cards.length > 0 ? cards : context.lastCards,
    lastMapPins: map.pins.length > 0 ? map.pins : context.lastMapPins,
    selectedCardId: selectedCardId || context.selectedCardId,
  };
}

function cardImages(card: TripCard): string[] {
  return Array.from(
    new Set(
      [card.image_url, ...(Array.isArray(card.image_urls) ? card.image_urls : [])].filter(
        (url): url is string => typeof url === "string" && url.startsWith("http"),
      ),
    ),
  );
}

function recommendationText(card: TripCard): string {
  const sourceText = [card.display_reason, card.description, card.reason]
    .map((value) => String(value ?? "").trim())
    .find((value) => value && !isDiagnosticRecommendationText(value));
  if (sourceText) {
    return sourceText;
  }

  const details = [];
  const score = ratingText(card);
  if (score) details.push(`评分 ${score}`);
  if (card.address) details.push(`位置在 ${card.address}`);
  if (card.subcategory) details.push(`属于${card.subcategory}`);
  if (details.length > 0) {
    return `推荐理由：${details.join("；")}，适合结合地图距离和当天路线优先考虑。`;
  }
  return "推荐理由：这个地点与当前问题匹配，适合作为地图上的备选点继续比较。";
}

function isDiagnosticRecommendationText(value: string): boolean {
  return /命中用户核心目标|没有命中|候选自身|semantic|API\s*候选|API候选|API\s*推荐|需要用户确认|debug|matched requirement/i.test(
    value,
  );
}

function ratingText(card: TripCard): string {
  const parts = [];
  if (card.rating) parts.push(String(card.rating));
  if (card.review_count) parts.push(`${card.review_count} reviews`);
  return parts.join(" · ");
}

function actionClick(event: MouseEvent<HTMLButtonElement>, callback: () => void) {
  event.stopPropagation();
  callback();
}

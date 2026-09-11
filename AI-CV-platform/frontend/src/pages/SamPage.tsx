import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Download, Sparkles, Wand2 } from "lucide-react";
import { api } from "../api/client";
import type { ImageAsset, SamPredictResult } from "../api/types";
import { Badge, EmptyState, SectionTitle, Spinner, formatBytes } from "../components/ui";
import { useApp } from "../store/app";

const PAGE_SIZE = 60;

type Mode = "point" | "box";
type PointKind = "fg" | "bg";
type NormPoint = [number, number];
type NormBox = [number, number, number, number];

export default function SamPage() {
  const { project, toast, reportError } = useApp();
  const projectId = project?.id ?? "";
  const labels = project?.labels ?? [];

  const [images, setImages] = useState<ImageAsset[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("point");
  const [pointKind, setPointKind] = useState<PointKind>("fg");
  const [saveLabel, setSaveLabel] = useState("");
  const [points, setPoints] = useState<NormPoint[]>([]);
  const [pointLabels, setPointLabels] = useState<number[]>([]);
  const [box, setBox] = useState<NormBox | null>(null);
  const [draftBox, setDraftBox] = useState<NormBox | null>(null);
  const [maskUrl, setMaskUrl] = useState<string | null>(null);
  const [maskPng, setMaskPng] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<SamPredictResult | null>(null);
  const [info, setInfo] = useState("在左侧图上点击目标，右侧会显示叠加结果");
  const [busy, setBusy] = useState(false);
  const [hasMask, setHasMask] = useState(false);
  const [ready, setReady] = useState(true);
  const [hint, setHint] = useState("");
  const [downloadOpen, setDownloadOpen] = useState(false);
  const downloadRef = useRef<HTMLDivElement>(null);
  const polygonRef = useRef<[number, number][] | null>(null);
  const predictSeq = useRef(0);

  const active = images.find((image) => image.id === activeId) ?? null;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  useEffect(() => {
    if (!downloadOpen) return;
    const onPointer = (event: MouseEvent) => {
      if (!downloadRef.current?.contains(event.target as Node)) setDownloadOpen(false);
    };
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [downloadOpen]);

  const fetchImages = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const data = await api.listImages(projectId, { page, pageSize: PAGE_SIZE });
      setImages(data.images);
      setTotal(data.total);
      setActiveId((current) => {
        if (current && data.images.some((image) => image.id === current)) return current;
        return data.images[0]?.id ?? null;
      });
    } catch (error) {
      reportError(error, "图片列表加载失败");
    } finally {
      setLoading(false);
    }
  }, [projectId, page, reportError]);

  useEffect(() => {
    void fetchImages();
  }, [fetchImages]);

  useEffect(() => {
    if (!projectId) return;
    void api
      .samStatus(projectId)
      .then((status) => {
        setReady(status.available);
        setHint(status.hint);
      })
      .catch(() => {
        setReady(false);
        setHint("SAM 接口不可用");
      });
  }, [projectId]);

  useEffect(() => {
    if (!labels.length) return;
    setSaveLabel((current) => current || labels[0].name);
  }, [labels]);

  const resetPrompts = () => {
    setPoints([]);
    setPointLabels([]);
    setBox(null);
    setDraftBox(null);
    setMaskUrl(null);
    setMaskPng(null);
    setLastResult(null);
    polygonRef.current = null;
    setHasMask(false);
    setInfo("在左侧图上点击目标，右侧会显示叠加结果");
  };

  useEffect(() => {
    resetPrompts();
  }, [activeId]);

  const runPredict = async (
    nextPoints: NormPoint[],
    nextLabels: number[],
    nextBox: NormBox | null,
  ) => {
    if (!projectId || !active) return;
    if (!nextPoints.length && !nextBox) return;
    const seq = ++predictSeq.current;
    setBusy(true);
    setInfo("正在分割…首次加载模型会稍慢，请看右侧叠加图");
    try {
      const result = await api.samPredict(projectId, {
        imageId: active.id,
        points: nextPoints,
        labels: nextLabels,
        box: nextBox ?? undefined,
      });
      if (seq !== predictSeq.current) return;
      polygonRef.current = result.polygon;
      setHasMask(true);
      setMaskUrl(result.overlayPng);
      setMaskPng(result.maskPng);
      setLastResult(result);
      setInfo(`Mask 面积 ${result.area} 像素 · 可下载 Mask / COCO，或写入数据集`);
    } catch (error) {
      if (seq !== predictSeq.current) return;
      reportError(error, "SAM 分割失败");
      setInfo("分割失败，换个点或框再试");
    } finally {
      if (seq === predictSeq.current) setBusy(false);
    }
  };

  const addPoint = (point: NormPoint) => {
    if (!active || busy) return;
    const nextPoints = [...points, point];
    const nextLabels = [...pointLabels, pointKind === "fg" ? 1 : 0];
    setPoints(nextPoints);
    setPointLabels(nextLabels);
    setInfo(pointKind === "fg" ? "已标前景点，正在分割…" : "已标背景点，正在分割…");
    void runPredict(nextPoints, nextLabels, box);
  };

  const commitBox = (nextBox: NormBox) => {
    if (!active || busy) return;
    const [x1, y1, x2, y2] = nextBox;
    if (Math.abs(x2 - x1) < 0.01 || Math.abs(y2 - y1) < 0.01) {
      setInfo("框太小，请按住拖出更大的框");
      return;
    }
    const ordered: NormBox = [Math.min(x1, x2), Math.min(y1, y2), Math.max(x1, x2), Math.max(y1, y2)];
    setBox(ordered);
    setDraftBox(null);
    setInfo("已画出提示框，正在分割…");
    void runPredict(points, pointLabels, ordered);
  };

  const saveToDataset = async () => {
    if (!projectId || !active) return;
    const polygon = polygonRef.current;
    if (!polygon || polygon.length < 3) {
      toast("还没有可保存的 Mask", "error");
      return;
    }
    try {
      const existing = active.annotation?.shapes ?? [];
      await api.saveAnnotation(projectId, {
        imageId: active.id,
        label: active.annotation?.label ?? saveLabel,
        shapes: [
          ...existing,
          { id: `sam${Date.now().toString(36)}`, type: "polygon", label: saveLabel, points: polygon },
        ],
      });
      toast("已写入数据页标注", "success");
      await fetchImages();
    } catch (error) {
      reportError(error, "保存失败");
    }
  };

  const stem = active?.filename.replace(/\.[^.]+$/, "") ?? "sam";

  const downloadMask = () => {
    if (!maskPng) {
      toast("还没有可下载的 Mask", "error");
      return;
    }
    triggerDownload(`${stem}_mask.png`, maskPng);
  };

  const downloadOverlay = () => {
    if (!maskUrl) {
      toast("还没有可下载的叠加图", "error");
      return;
    }
    triggerDownload(`${stem}_overlay.jpg`, maskUrl);
  };

  const downloadCurrentCoco = () => {
    if (!active || !lastResult || !polygonRef.current || polygonRef.current.length < 3) {
      toast("还没有可导出的标注", "error");
      return;
    }
    const width = lastResult.width || active.width;
    const height = lastResult.height || active.height;
    const polygon = polygonRef.current;
    const flat = polygon.flatMap(([x, y]) => [round(x * width, 2), round(y * height, 2)]);
    const box = lastResult.box;
    const bbox = box
      ? [
          round(box[0] * width, 2),
          round(box[1] * height, 2),
          round((box[2] - box[0]) * width, 2),
          round((box[3] - box[1]) * height, 2),
        ]
      : [0, 0, width, height];
    const coco = {
      info: { description: `${active.filename} SAM`, version: "1.0" },
      images: [{ id: 1, file_name: active.filename, width, height }],
      categories: [{ id: 1, name: saveLabel || "object" }],
      annotations: [
        {
          id: 1,
          image_id: 1,
          category_id: 1,
          bbox,
          area: lastResult.area,
          iscrowd: 0,
          segmentation: [flat],
        },
      ],
    };
    triggerDownloadJson(`${stem}_coco.json`, coco);
  };

  const exportDatasetCoco = async () => {
    if (!projectId) return;
    try {
      const result = await api.exportAnnotations(projectId, "coco");
      triggerDownloadJson(`${project?.name || "dataset"}_coco.json`, result.data);
      toast("已导出数据集 COCO JSON", "success");
    } catch (error) {
      reportError(error, "COCO 导出失败");
    }
  };

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-[220px] shrink-0 flex-col border-r border-line">
        <SectionTitle title="数据集图片" hint={`${total} 张`} />
        <div className="scroll-y flex-1 p-2">
          {loading ? (
            <div className="flex items-center gap-2 p-2 text-[12px] text-mute">
              <Spinner /> 加载中…
            </div>
          ) : images.length === 0 ? (
            <EmptyState title="暂无图片" hint="请先到「数据」页上传图片。" />
          ) : (
            <div className="grid grid-cols-2 gap-1.5">
              {images.map((image) => (
                <button
                  key={image.id}
                  onClick={() => setActiveId(image.id)}
                  className={`relative aspect-square overflow-hidden rounded-md border ${
                    image.id === activeId ? "border-brand" : "border-line hover:border-brand/40"
                  }`}
                  title={image.filename}
                >
                  <img src={image.thumbUrl} alt="" className="h-full w-full object-cover" />
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex items-center justify-between border-t border-line px-2 py-1.5 text-[11px] text-mute">
          <button className="btn-subtle px-1.5 py-0.5" disabled={page <= 1} onClick={() => setPage((v) => v - 1)}>
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          {page} / {pageCount}
          <button
            className="btn-subtle px-1.5 py-0.5"
            disabled={page >= pageCount}
            onClick={() => setPage((v) => Math.min(pageCount, v + 1))}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <SectionTitle
          title="SAM 智能标注"
          hint="左侧点一下标位置，右侧立刻看叠加效果。不改数据页原有框选/多边形。"
          actions={
            ready ? <Badge tone="ok">SAM 可用</Badge> : <Badge tone="warn">{hint || "未就绪"}</Badge>
          }
        />

        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
          <span className="text-[11.5px] text-mute">标注模式</span>
          <select
            className="field w-auto py-1"
            value={mode}
            onChange={(event) => {
              setMode(event.target.value as Mode);
              setDraftBox(null);
            }}
          >
            <option value="point">点选（单击）</option>
            <option value="box">框选（按住拖拽）</option>
          </select>
          {mode === "point" ? (
            <>
              <span className="text-[11.5px] text-mute">点类型</span>
              <select
                className="field w-auto py-1"
                value={pointKind}
                onChange={(event) => setPointKind(event.target.value as PointKind)}
              >
                <option value="fg">前景点（目标）</option>
                <option value="bg">背景点（排除）</option>
              </select>
            </>
          ) : (
            <span className="text-[11.5px] text-mute">在左图按住鼠标拖出提示框</span>
          )}
          {labels.length ? (
            <>
              <span className="text-[11.5px] text-mute">写入类别</span>
              <select
                className="field w-auto py-1"
                value={saveLabel}
                onChange={(event) => setSaveLabel(event.target.value)}
              >
                {labels.map((label) => (
                  <option key={label.id} value={label.name}>
                    {label.name}
                  </option>
                ))}
              </select>
            </>
          ) : null}
          <button className="btn-subtle py-1" onClick={resetPrompts}>
            清除重来
          </button>
          <button className="btn-primary py-1" disabled={busy || !hasMask} onClick={() => void saveToDataset()}>
            <Wand2 className="h-3.5 w-3.5" /> 写入数据集
          </button>
          <div className="relative" ref={downloadRef}>
            <button
              className="btn-subtle py-1"
              onClick={() => setDownloadOpen((open) => !open)}
            >
              <Download className="h-3.5 w-3.5" /> 下载
              <ChevronDown className={`h-3.5 w-3.5 transition ${downloadOpen ? "rotate-180" : ""}`} />
            </button>
            {downloadOpen ? (
              <div className="absolute left-0 top-full z-20 mt-1 min-w-[200px] rounded-md border border-line bg-panel py-1 shadow-lg">
                <button
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] hover:bg-panel-2 disabled:text-mute"
                  disabled={!hasMask}
                  onClick={() => {
                    downloadMask();
                    setDownloadOpen(false);
                  }}
                >
                  Mask PNG
                  <span className="ml-auto text-[10.5px] text-mute">当前图</span>
                </button>
                <button
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] hover:bg-panel-2 disabled:text-mute"
                  disabled={!hasMask}
                  onClick={() => {
                    downloadOverlay();
                    setDownloadOpen(false);
                  }}
                >
                  叠加图
                  <span className="ml-auto text-[10.5px] text-mute">当前图</span>
                </button>
                <button
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] hover:bg-panel-2 disabled:text-mute"
                  disabled={!hasMask}
                  onClick={() => {
                    downloadCurrentCoco();
                    setDownloadOpen(false);
                  }}
                >
                  COCO JSON
                  <span className="ml-auto text-[10.5px] text-mute">当前图</span>
                </button>
                <div className="my-1 border-t border-line" />
                <button
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12px] hover:bg-panel-2"
                  onClick={() => {
                    void exportDatasetCoco();
                    setDownloadOpen(false);
                  }}
                >
                  全部 COCO JSON
                  <span className="ml-auto text-[10.5px] text-mute">数据集</span>
                </button>
              </div>
            ) : null}
          </div>
          <div className="flex-1" />
          {active ? (
            <span className="mono truncate text-[11px] text-mute">
              {active.filename} · {formatBytes(active.sizeBytes)}
            </span>
          ) : null}
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-2">
          <PreviewPane
            title="标注位置"
            src={active?.previewUrl}
            fallback={active ? "在图上点击目标" : "从左侧选择一张图片"}
            interactive={Boolean(active) && !busy && ready}
            mode={mode}
            points={points}
            pointLabels={pointLabels}
            box={box}
            draftBox={draftBox}
            onPoint={addPoint}
            onBoxDraft={setDraftBox}
            onBoxCommit={commitBox}
          />
          <PreviewPane
            title="叠加结果"
            src={maskUrl}
            fallback={busy ? "正在分割，请稍候…" : "点选或框选后，这里显示 Mask 叠加"}
            interactive={false}
            busy={busy}
            dimFallbackSrc={active?.previewUrl}
          />
        </div>

        <div className="flex h-9 shrink-0 items-center gap-2 border-t border-line px-3 text-[12px] text-mute">
          {busy ? <Spinner /> : <Sparkles className="h-3.5 w-3.5" />}
          <span className="truncate">{info}</span>
          {!ready ? <span className="text-warn">{hint}</span> : null}
        </div>
      </div>
    </div>
  );
}

function clientToNorm(event: { clientX: number; clientY: number }, image: HTMLImageElement): NormPoint | null {
  const rect = image.getBoundingClientRect();
  const nw = image.naturalWidth;
  const nh = image.naturalHeight;
  if (nw <= 0 || nh <= 0 || rect.width <= 0 || rect.height <= 0) return null;
  const scale = Math.min(rect.width / nw, rect.height / nh);
  const dw = nw * scale;
  const dh = nh * scale;
  const left = rect.left + (rect.width - dw) / 2;
  const top = rect.top + (rect.height - dh) / 2;
  const x = (event.clientX - left) / dw;
  const y = (event.clientY - top) / dh;
  if (x < 0 || y < 0 || x > 1 || y > 1) return null;
  return [x, y];
}

function containedBox(image: HTMLImageElement) {
  const nw = image.naturalWidth;
  const nh = image.naturalHeight;
  const width = image.clientWidth;
  const height = image.clientHeight;
  if (nw <= 0 || nh <= 0 || width <= 0 || height <= 0) {
    return { left: 0, top: 0, width, height };
  }
  const scale = Math.min(width / nw, height / nh);
  const dw = nw * scale;
  const dh = nh * scale;
  return { left: (width - dw) / 2, top: (height - dh) / 2, width: dw, height: dh };
}

function PreviewPane({
  title,
  src,
  fallback,
  interactive,
  mode = "point",
  points = [],
  pointLabels = [],
  box,
  draftBox,
  onPoint,
  onBoxDraft,
  onBoxCommit,
  busy = false,
  dimFallbackSrc,
}: {
  title: string;
  src?: string | null;
  fallback: string;
  interactive: boolean;
  mode?: Mode;
  points?: NormPoint[];
  pointLabels?: number[];
  box?: NormBox | null;
  draftBox?: NormBox | null;
  onPoint?: (point: NormPoint) => void;
  onBoxDraft?: (box: NormBox | null) => void;
  onBoxCommit?: (box: NormBox) => void;
  busy?: boolean;
  dimFallbackSrc?: string | null;
}) {
  const imgRef = useRef<HTMLImageElement>(null);
  const dragOrigin = useRef<NormPoint | null>(null);
  const [markBox, setMarkBox] = useState({ left: 0, top: 0, width: 0, height: 0 });

  const displaySrc = src ?? (busy ? dimFallbackSrc : null);

  useEffect(() => {
    const image = imgRef.current;
    if (!image) return;
    const update = () => setMarkBox(containedBox(image));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(image);
    image.addEventListener("load", update);
    return () => {
      observer.disconnect();
      image.removeEventListener("load", update);
    };
  }, [displaySrc]);

  const handleMouseDown = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!interactive || !imgRef.current) return;
    const point = clientToNorm(event, imgRef.current);
    if (!point) return;
    event.preventDefault();
    if (mode === "point") {
      onPoint?.(point);
      return;
    }
    dragOrigin.current = point;
    onBoxDraft?.([point[0], point[1], point[0], point[1]]);
  };

  const handleMouseMove = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!interactive || mode !== "box" || !dragOrigin.current || !imgRef.current) return;
    const point = clientToNorm(event, imgRef.current);
    if (!point) return;
    const origin = dragOrigin.current;
    onBoxDraft?.([origin[0], origin[1], point[0], point[1]]);
  };

  const finishBox = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!interactive || mode !== "box" || !dragOrigin.current || !imgRef.current) return;
    const point = clientToNorm(event, imgRef.current) ?? dragOrigin.current;
    const origin = dragOrigin.current;
    dragOrigin.current = null;
    onBoxCommit?.([origin[0], origin[1], point[0], point[1]]);
  };

  return (
    <div className="flex h-full min-h-0 flex-col border-r border-line last:border-r-0">
      <div className="flex items-center justify-between border-b border-line px-3 py-1.5">
        <span className="text-[12px] font-medium">{title}</span>
        {busy ? (
          <span className="flex items-center gap-1 text-[11px] text-mute">
            <Spinner /> 分割中
          </span>
        ) : null}
      </div>
      <div
        className={`relative min-h-0 flex-1 bg-[#080b11] ${interactive ? "cursor-crosshair" : ""}`}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={finishBox}
        onMouseLeave={() => {
          if (dragOrigin.current) {
            dragOrigin.current = null;
            onBoxDraft?.(null);
          }
        }}
      >
        {displaySrc ? (
          <>
            <img
              ref={imgRef}
              src={displaySrc}
              alt={title}
              className={`absolute inset-0 h-full w-full object-contain ${busy && !src ? "opacity-40" : ""}`}
              draggable={false}
            />
            {interactive || points.length || box || draftBox ? (
              <svg
                className="pointer-events-none absolute"
                style={{
                  left: markBox.left,
                  top: markBox.top,
                  width: markBox.width,
                  height: markBox.height,
                }}
              >
                {points.map((point, index) => (
                  <g key={`p${index}`}>
                    <circle
                      cx={`${point[0] * 100}%`}
                      cy={`${point[1] * 100}%`}
                      r="9"
                      fill={pointLabels[index] ? "#84cc16" : "#ef4444"}
                      stroke="#111"
                      strokeWidth="2"
                    />
                    <circle
                      cx={`${point[0] * 100}%`}
                      cy={`${point[1] * 100}%`}
                      r="3"
                      fill="#fff"
                    />
                  </g>
                ))}
                {[box, draftBox].map((item, index) =>
                  item ? (
                    <rect
                      key={`b${index}`}
                      x={`${Math.min(item[0], item[2]) * 100}%`}
                      y={`${Math.min(item[1], item[3]) * 100}%`}
                      width={`${Math.abs(item[2] - item[0]) * 100}%`}
                      height={`${Math.abs(item[3] - item[1]) * 100}%`}
                      fill="rgba(37, 99, 235, 0.16)"
                      stroke="#2563eb"
                      strokeWidth="3"
                    />
                  ) : null,
                )}
              </svg>
            ) : null}
            {busy && src ? (
              <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/25">
                <span className="rounded-md bg-black/70 px-2 py-1 text-[12px] text-white">更新叠加中…</span>
              </div>
            ) : null}
          </>
        ) : (
          <div className="flex h-full items-center justify-center px-6 text-center text-[12px] text-mute">
            {fallback}
          </div>
        )}
      </div>
    </div>
  );
}

function round(value: number, digits: number) {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function triggerDownload(filename: string, href: string) {
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  link.click();
}

function triggerDownloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  triggerDownload(filename, url);
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

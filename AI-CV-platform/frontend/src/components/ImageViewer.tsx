import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Crosshair, Maximize2, Minus, Plus, Scan } from "lucide-react";
import type { AnnotationShape } from "../api/types";

export type ViewerTool = "pan" | "bbox" | "polygon" | "point" | "rect" | "sam";

interface Props {
  src?: string | null;
  shapes?: AnnotationShape[];
  tool?: ViewerTool;
  labelColors?: Record<string, string>;
  activeLabel?: string;
  selectedShapeId?: string | null;
  onSelectShape?: (id: string | null) => void;
  onCreateShape?: (shape: Omit<AnnotationShape, "id">) => void;
  onCreateRect?: (rect: [number, number, number, number]) => void;
  samMode?: "point" | "box";
  samPointKind?: "fg" | "bg";
  onSamPoint?: (point: [number, number]) => void;
  onSamBox?: (box: [number, number, number, number]) => void;
  overlaySrc?: string | null;
  overlayOpacity?: number;
  showProbe?: boolean;
  toolbarExtra?: ReactNode;
  emptyHint?: string;
  className?: string;
}

interface Probe {
  x: number;
  y: number;
  rgb: [number, number, number] | null;
}

const DEFAULT_COLOR = "#38bdf8";
// Shared empty defaults: fresh literals would give every render a new identity
// and invalidate the memoized painters below.
const NO_SHAPES: AnnotationShape[] = [];
const NO_COLORS: Record<string, string> = {};

export function ImageViewer({
  src,
  shapes = NO_SHAPES,
  tool = "pan",
  labelColors = NO_COLORS,
  activeLabel = "",
  selectedShapeId = null,
  onSelectShape,
  onCreateShape,
  onCreateRect,
  samMode = "point",
  onSamPoint,
  onSamBox,
  overlaySrc,
  overlayOpacity = 0.55,
  showProbe = true,
  toolbarExtra,
  emptyHint = "选择一张图片查看",
  className = "",
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imageRef = useRef<HTMLImageElement | null>(null);
  const overlayRef = useRef<HTMLImageElement | null>(null);
  const pixelsRef = useRef<ImageData | null>(null);
  const viewRef = useRef({ scale: 1, ox: 0, oy: 0 });
  const dragRef = useRef<{ mode: "pan" | "draw"; sx: number; sy: number; ix: number; iy: number } | null>(
    null,
  );
  const rafRef = useRef(0);

  const [size, setSize] = useState({ width: 0, height: 0 });
  const [ready, setReady] = useState(false);
  const [probe, setProbe] = useState<Probe | null>(null);
  const [scaleLabel, setScaleLabel] = useState(1);
  const [draft, setDraft] = useState<[number, number][] | null>(null);
  const [polygon, setPolygon] = useState<[number, number][]>([]);

  const colorOf = useCallback(
    (label: string) => labelColors[label] ?? DEFAULT_COLOR,
    [labelColors],
  );

  const paint = useCallback(() => {
    const canvas = canvasRef.current;
    const image = imageRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const { clientWidth: cw, clientHeight: ch } = canvas;
    if (canvas.width !== Math.floor(cw * dpr) || canvas.height !== Math.floor(ch * dpr)) {
      canvas.width = Math.floor(cw * dpr);
      canvas.height = Math.floor(ch * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cw, ch);
    ctx.fillStyle = "#080b11";
    ctx.fillRect(0, 0, cw, ch);
    if (!image) return;

    const { scale, ox, oy } = viewRef.current;
    ctx.save();
    ctx.setTransform(dpr * scale, 0, 0, dpr * scale, dpr * ox, dpr * oy);
    ctx.imageSmoothingEnabled = scale < 1;
    ctx.drawImage(image, 0, 0);
    if (overlayRef.current) {
      ctx.globalAlpha = overlayOpacity;
      ctx.drawImage(overlayRef.current, 0, 0, image.naturalWidth, image.naturalHeight);
      ctx.globalAlpha = 1;
    }
    ctx.restore();

    // overlays in screen space so line widths stay crisp
    const toImagePt = (x: number, y: number): [number, number] => {
      if (x >= 0 && x <= 1 && y >= 0 && y <= 1) {
        return [x * image.naturalWidth, y * image.naturalHeight];
      }
      return [x, y];
    };
    const toScreen = (x: number, y: number): [number, number] => {
      const [px, py] = toImagePt(x, y);
      return [px * scale + ox, py * scale + oy];
    };
    ctx.lineJoin = "round";

    const drawShape = (shape: AnnotationShape, selected: boolean) => {
      const color = colorOf(shape.label);
      ctx.strokeStyle = color;
      ctx.fillStyle = `${color}22`;
      ctx.lineWidth = selected ? 2.5 : 1.5;
      if (shape.type === "bbox" && shape.points.length >= 2) {
        const [p0, p1] = [toScreen(...shape.points[0]), toScreen(...shape.points[1])];
        const x = Math.min(p0[0], p1[0]);
        const y = Math.min(p0[1], p1[1]);
        const w = Math.abs(p1[0] - p0[0]);
        const h = Math.abs(p1[1] - p0[1]);
        ctx.fillRect(x, y, w, h);
        ctx.strokeRect(x, y, w, h);
        if (shape.label) {
          ctx.fillStyle = color;
          ctx.font = "11px ui-monospace, monospace";
          ctx.fillText(shape.label, x + 2, Math.max(10, y - 3));
        }
      } else if (shape.type === "polygon" && shape.points.length >= 2) {
        ctx.beginPath();
        shape.points.forEach((point, index) => {
          const [x, y] = toScreen(...point);
          if (index === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      } else if (shape.type === "point" && shape.points.length) {
        const [x, y] = toScreen(...shape.points[0]);
        ctx.beginPath();
        ctx.arc(x, y, selected ? 6 : 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      }
    };

    shapes.forEach((shape) => drawShape(shape, shape.id === selectedShapeId));

    if (draft && draft.length >= 2) {
      ctx.setLineDash([4, 3]);
      drawShape(
        { id: "__draft", type: tool === "polygon" ? "polygon" : "bbox", label: activeLabel, points: draft },
        true,
      );
      ctx.setLineDash([]);
    }
    if (polygon.length) {
      ctx.setLineDash([4, 3]);
      drawShape({ id: "__poly", type: "polygon", label: activeLabel, points: polygon }, true);
      ctx.setLineDash([]);
    }
  }, [activeLabel, colorOf, draft, overlayOpacity, polygon, selectedShapeId, shapes, tool]);

  // `paint` is rebuilt whenever shapes/draft/tool change. Reaching it through a
  // ref keeps `schedule` (and everything depending on it) referentially stable,
  // so effects below don't re-run — and re-trigger themselves — on every render.
  const paintRef = useRef(paint);
  paintRef.current = paint;

  const schedule = useCallback(() => {
    if (rafRef.current) return;
    rafRef.current = window.requestAnimationFrame(() => {
      rafRef.current = 0;
      paintRef.current();
    });
  }, []);

  const fit = useCallback(() => {
    const canvas = canvasRef.current;
    const image = imageRef.current;
    if (!canvas || !image) return;
    const scale = Math.min(
      canvas.clientWidth / image.naturalWidth,
      canvas.clientHeight / image.naturalHeight,
    );
    const value = Number.isFinite(scale) && scale > 0 ? scale * 0.96 : 1;
    viewRef.current = {
      scale: value,
      ox: (canvas.clientWidth - image.naturalWidth * value) / 2,
      oy: (canvas.clientHeight - image.naturalHeight * value) / 2,
    };
    setScaleLabel(value);
    schedule();
  }, [schedule]);

  // load image
  useEffect(() => {
    pixelsRef.current = null;
    setReady(false);
    setDraft(null);
    setPolygon((current) => (current.length ? [] : current));
    if (!src) {
      imageRef.current = null;
      setSize((current) => (current.width || current.height ? { width: 0, height: 0 } : current));
      schedule();
      return;
    }
    const image = new Image();
    image.crossOrigin = "anonymous";
    let cancelled = false;
    image.onload = () => {
      if (cancelled) return;
      imageRef.current = image;
      setSize({ width: image.naturalWidth, height: image.naturalHeight });
      setReady(true);
      fit();
    };
    image.onerror = () => {
      if (cancelled) return;
      imageRef.current = null;
      setReady(false);
      schedule();
    };
    image.src = src;
    return () => {
      cancelled = true;
    };
  }, [src, fit, schedule]);

  useEffect(() => {
    if (!overlaySrc) {
      overlayRef.current = null;
      schedule();
      return;
    }
    const image = new Image();
    image.crossOrigin = "anonymous";
    image.onload = () => {
      overlayRef.current = image;
      schedule();
    };
    image.src = overlaySrc;
    return () => {
      overlayRef.current = null;
    };
  }, [overlaySrc, schedule]);

  // repaint whenever what we draw changes (shapes, draft, tool, colors)
  useEffect(() => {
    schedule();
  }, [paint, schedule]);

  // resize observer
  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap) return;
    const observer = new ResizeObserver(() => schedule());
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [schedule]);

  const toImage = (event: { clientX: number; clientY: number }): [number, number] => {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const { scale, ox, oy } = viewRef.current;
    return [(event.clientX - rect.left - ox) / scale, (event.clientY - rect.top - oy) / scale];
  };

  const samplePixel = (x: number, y: number): [number, number, number] | null => {
    const image = imageRef.current;
    if (!image) return null;
    if (x < 0 || y < 0 || x >= image.naturalWidth || y >= image.naturalHeight) return null;
    if (!pixelsRef.current) {
      try {
        const off = document.createElement("canvas");
        off.width = image.naturalWidth;
        off.height = image.naturalHeight;
        const ctx = off.getContext("2d", { willReadFrequently: true });
        if (!ctx) return null;
        ctx.drawImage(image, 0, 0);
        pixelsRef.current = ctx.getImageData(0, 0, off.width, off.height);
      } catch {
        return null;
      }
    }
    const data = pixelsRef.current;
    if (!data) return null;
    const index = (Math.floor(y) * data.width + Math.floor(x)) * 4;
    return [data.data[index], data.data[index + 1], data.data[index + 2]];
  };

  const zoomBy = (factor: number, anchor?: [number, number]) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const view = viewRef.current;
    const next = Math.min(40, Math.max(0.02, view.scale * factor));
    const [ax, ay] = anchor ?? [canvas.clientWidth / 2, canvas.clientHeight / 2];
    const ratio = next / view.scale;
    viewRef.current = {
      scale: next,
      ox: ax - (ax - view.ox) * ratio,
      oy: ay - (ay - view.oy) * ratio,
    };
    setScaleLabel(next);
    schedule();
  };

  const onWheel = (event: React.WheelEvent) => {
    event.preventDefault();
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    zoomBy(event.deltaY < 0 ? 1.12 : 1 / 1.12, [event.clientX - rect.left, event.clientY - rect.top]);
  };

  const onMouseDown = (event: React.MouseEvent) => {
    if (!imageRef.current) return;
    const [ix, iy] = toImage(event);
    const drawing = tool !== "pan" && event.button === 0 && !event.altKey;
    if (tool === "sam" && samMode === "point" && drawing) {
      const image = imageRef.current;
      onSamPoint?.([ix / image.naturalWidth, iy / image.naturalHeight]);
      return;
    }
    if (tool === "point" && drawing) {
      onCreateShape?.({ type: "point", label: activeLabel, points: [[Math.round(ix), Math.round(iy)]] });
      return;
    }
    if (tool === "polygon" && drawing) {
      setPolygon((current) => [...current, [Math.round(ix), Math.round(iy)]]);
      return;
    }
    dragRef.current = {
      mode: drawing ? "draw" : "pan",
      sx: event.clientX,
      sy: event.clientY,
      ix,
      iy,
    };
    if (drawing) setDraft([[Math.round(ix), Math.round(iy)], [Math.round(ix), Math.round(iy)]]);
    else if (tool === "pan") onSelectShape?.(hitTest(ix, iy));
  };

  const hitTest = (x: number, y: number): string | null => {
    for (let index = shapes.length - 1; index >= 0; index -= 1) {
      const shape = shapes[index];
      if (shape.type === "bbox" && shape.points.length >= 2) {
        const [[x0, y0], [x1, y1]] = shape.points;
        if (x >= Math.min(x0, x1) && x <= Math.max(x0, x1) && y >= Math.min(y0, y1) && y <= Math.max(y0, y1))
          return shape.id;
      } else if (shape.type === "point" && shape.points.length) {
        const [px, py] = shape.points[0];
        if (Math.hypot(px - x, py - y) < 8 / viewRef.current.scale) return shape.id;
      }
    }
    return null;
  };

  const onMouseMove = (event: React.MouseEvent) => {
    const [ix, iy] = toImage(event);
    if (showProbe && imageRef.current) {
      const inside =
        ix >= 0 && iy >= 0 && ix < imageRef.current.naturalWidth && iy < imageRef.current.naturalHeight;
      setProbe(
        inside
          ? { x: Math.floor(ix), y: Math.floor(iy), rgb: samplePixel(ix, iy) }
          : null,
      );
    }
    const drag = dragRef.current;
    if (!drag) return;
    if (drag.mode === "pan") {
      const view = viewRef.current;
      viewRef.current = {
        ...view,
        ox: view.ox + (event.clientX - drag.sx),
        oy: view.oy + (event.clientY - drag.sy),
      };
      dragRef.current = { ...drag, sx: event.clientX, sy: event.clientY };
      schedule();
    } else {
      setDraft([
        [Math.round(drag.ix), Math.round(drag.iy)],
        [Math.round(ix), Math.round(iy)],
      ]);
    }
  };

  const onMouseUp = () => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || drag.mode !== "draw" || !draft) return;
    const [[x0, y0], [x1, y1]] = draft;
    setDraft(null);
    const x = Math.min(x0, x1);
    const y = Math.min(y0, y1);
    const w = Math.abs(x1 - x0);
    const h = Math.abs(y1 - y0);
    if (w < 3 || h < 3) return;
    const image = imageRef.current;
    if (tool === "sam") {
      if (image) {
        onSamBox?.([
          x / image.naturalWidth,
          y / image.naturalHeight,
          (x + w) / image.naturalWidth,
          (y + h) / image.naturalHeight,
        ]);
      }
      return;
    }
    if (tool === "rect") onCreateRect?.([x, y, w, h]);
    else if (tool === "bbox")
      onCreateShape?.({
        type: "bbox",
        label: activeLabel,
        points: [
          [x, y],
          [x + w, y + h],
        ],
      });
  };

  const finishPolygon = () => {
    if (!polygon.length) return;
    if (polygon.length >= 3) onCreateShape?.({ type: "polygon", label: activeLabel, points: polygon });
    setPolygon([]);
  };

  const finishRef = useRef(finishPolygon);
  finishRef.current = finishPolygon;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPolygon((current) => (current.length ? [] : current));
        setDraft(null);
      }
      if (event.key === "Enter") finishRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const cursor = useMemo(() => {
    if (tool === "pan") return "grab";
    if (tool === "point") return "crosshair";
    return "crosshair";
  }, [tool]);

  return (
    <div ref={wrapRef} className={`relative flex min-h-0 flex-col bg-[#080b11] ${className}`}>
      <div className="absolute top-2 left-2 z-10 flex items-center gap-1 rounded-md border border-line-solid bg-panel/85 px-1 py-1 backdrop-blur">
        <button className="btn-subtle px-1.5 py-1" title="缩小" onClick={() => zoomBy(1 / 1.25)}>
          <Minus className="h-3.5 w-3.5" />
        </button>
        <span className="mono w-12 text-center text-[11px] text-mute">
          {(scaleLabel * 100).toFixed(0)}%
        </span>
        <button className="btn-subtle px-1.5 py-1" title="放大" onClick={() => zoomBy(1.25)}>
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button className="btn-subtle px-1.5 py-1" title="适应窗口" onClick={fit}>
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
        <button
          className="btn-subtle px-1.5 py-1"
          title="1:1"
          onClick={() => {
            const canvas = canvasRef.current;
            const image = imageRef.current;
            if (!canvas || !image) return;
            viewRef.current = {
              scale: 1,
              ox: (canvas.clientWidth - image.naturalWidth) / 2,
              oy: (canvas.clientHeight - image.naturalHeight) / 2,
            };
            setScaleLabel(1);
            schedule();
          }}
        >
          <Scan className="h-3.5 w-3.5" />
        </button>
        {toolbarExtra ? (
          <>
            <div className="mx-0.5 h-4 w-px bg-line-solid" />
            {toolbarExtra}
          </>
        ) : null}
      </div>

      {polygon.length ? (
        <div className="absolute top-2 left-1/2 z-10 -translate-x-1/2 rounded-md border border-brand/40 bg-panel/90 px-2 py-1 text-[11px] text-brand">
          多边形 {polygon.length} 点 · Enter 完成 · Esc 取消
          <button className="btn-subtle ml-2 px-1.5 py-0.5 text-[11px]" onClick={finishPolygon}>
            完成
          </button>
        </div>
      ) : null}

      <canvas
        ref={canvasRef}
        className="h-full w-full flex-1"
        style={{ cursor }}
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={() => {
          setProbe(null);
          onMouseUp();
        }}
        onDoubleClick={() => (polygon.length >= 3 ? finishPolygon() : fit())}
      />

      {!src || !ready ? (
        <div className="pointer-events-none absolute inset-0 grid place-items-center text-[12px] text-mute">
          {src ? "" : emptyHint}
        </div>
      ) : null}

      <div className="flex h-7 shrink-0 items-center gap-3 border-t border-line bg-panel px-2 text-[11px] text-mute">
        <span className="mono">
          {size.width} × {size.height}
        </span>
        {probe ? (
          <>
            <span className="mono flex items-center gap-1">
              <Crosshair className="h-3 w-3" /> {probe.x}, {probe.y}
            </span>
            {probe.rgb ? (
              <span className="mono flex items-center gap-1.5">
                <span
                  className="inline-block h-3 w-3 rounded-sm border border-line-solid"
                  style={{ background: `rgb(${probe.rgb.join(",")})` }}
                />
                RGB {probe.rgb.join(", ")}
                <span className="text-mute/70">
                  GRAY {Math.round(0.299 * probe.rgb[0] + 0.587 * probe.rgb[1] + 0.114 * probe.rgb[2])}
                </span>
              </span>
            ) : null}
          </>
        ) : (
          <span className="text-mute/60">滚轮缩放 · 拖拽平移 · 双击适应窗口</span>
        )}
      </div>
    </div>
  );
}

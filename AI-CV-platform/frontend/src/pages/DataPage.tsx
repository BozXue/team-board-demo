import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  BarChart3,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  Download,
  FolderInput,
  MousePointer2,
  PenLine,
  Shuffle,
  Square,
  Tag,
  Trash2,
  Triangle,
  Upload,
} from "lucide-react";
import { api } from "../api/client";
import type { AnnotationShape, DatasetStats, Diagnosis, ImageAsset } from "../api/types";
import { Histogram } from "../components/Histogram";
import { DiagnosisPanel } from "../components/DiagnosisPanel";
import { ImageViewer, type ViewerTool } from "../components/ImageViewer";
import {
  Badge,
  Confirm,
  EmptyState,
  Modal,
  SectionTitle,
  Spinner,
  Tabs,
  formatBytes,
  formatNumber,
  useDebounced,
} from "../components/ui";
import { useApp } from "../store/app";

const SPLITS = ["unassigned", "train", "val", "test"];
const SPLIT_LABELS: Record<string, string> = {
  unassigned: "未分配",
  train: "训练",
  val: "验证",
  test: "测试",
};

const TOOLS: { value: ViewerTool; label: string; icon: typeof Square }[] = [
  { value: "pan", label: "浏览", icon: MousePointer2 },
  { value: "bbox", label: "矩形框", icon: Square },
  { value: "polygon", label: "多边形", icon: Triangle },
  { value: "point", label: "打点", icon: PenLine },
];

const PAGE_SIZE = 60;

export default function DataPage() {
  const { project, loadProject, toast, reportError } = useApp();
  const projectId = project?.id ?? "";
  const fileInput = useRef<HTMLInputElement>(null);

  const [images, setImages] = useState<ImageAsset[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState<{ split: string; label: string; annotated: string; search: string }>(
    { split: "", label: "", annotated: "", search: "" },
  );
  const debouncedSearch = useDebounced(filters.search, 300);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [tool, setTool] = useState<ViewerTool>("pan");
  const [activeLabel, setActiveLabel] = useState("");
  const [shapes, setShapes] = useState<AnnotationShape[]>([]);
  const [selectedShape, setSelectedShape] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [imageLabel, setImageLabel] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<"annotate" | "quality" | "stats">("annotate");
  const [histogram, setHistogram] = useState<Record<string, number[]> | null>(null);
  const [histStats, setHistStats] = useState<Record<string, number> | null>(null);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [stats, setStats] = useState<DatasetStats | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [importPath, setImportPath] = useState("");
  const [importRecursive, setImportRecursive] = useState(true);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [newLabel, setNewLabel] = useState("");

  const labels = project?.labels ?? [];
  const labelColors = useMemo(() => {
    const map: Record<string, string> = {};
    labels.forEach((label) => {
      map[label.name] = label.color;
    });
    return map;
  }, [labels]);

  const active = images.find((image) => image.id === activeId) ?? null;

  const fetchImages = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    try {
      const data = await api.listImages(projectId, {
        page,
        pageSize: PAGE_SIZE,
        split: filters.split || undefined,
        label: filters.label || undefined,
        annotated: filters.annotated === "" ? undefined : filters.annotated === "yes",
        search: debouncedSearch || undefined,
      });
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
  }, [projectId, page, filters.split, filters.label, filters.annotated, debouncedSearch, reportError]);

  useEffect(() => {
    void fetchImages();
  }, [fetchImages]);

  const fetchStats = useCallback(async () => {
    if (!projectId) return;
    try {
      setStats(await api.datasetStats(projectId));
    } catch {
      /* ignore */
    }
  }, [projectId]);

  useEffect(() => {
    void fetchStats();
  }, [fetchStats]);

  useEffect(() => {
    if (!labels.length) return;
    setActiveLabel((current) => current || labels[labels.length - 1].name);
  }, [labels]);

  // sync annotation editor with active image
  useEffect(() => {
    setShapes(active?.annotation?.shapes ?? []);
    setImageLabel(active?.annotation?.label ?? null);
    setNote(active?.annotation?.note ?? "");
    setSelectedShape(null);
    setHistogram(null);
    setHistStats(null);
    setDiagnosis(null);
  }, [active?.id, active?.annotation]);

  useEffect(() => {
    if (!active || rightTab !== "quality") return;
    let cancelled = false;
    void (async () => {
      try {
        const [hist, diag] = await Promise.all([
          api.imageHistogram(active.id),
          api.imageDiagnose(active.id),
        ]);
        if (cancelled) return;
        setHistogram(hist.channels);
        setHistStats(hist.stats);
        setDiagnosis(diag);
      } catch (error) {
        if (!cancelled) reportError(error, "图像质量分析失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [active, rightTab, reportError]);

  const refreshProject = () => {
    if (projectId) void loadProject(projectId);
  };

  const persist = async (patch: {
    label?: string | null;
    shapes?: AnnotationShape[];
    note?: string;
    reviewed?: boolean;
  }) => {
    if (!projectId || !active) return;
    try {
      const response = await api.saveAnnotation(projectId, {
        imageId: active.id,
        label: patch.label !== undefined ? patch.label : imageLabel,
        shapes: patch.shapes ?? shapes,
        note: patch.note ?? note,
        reviewed: patch.reviewed,
      });
      setImages((current) =>
        current.map((image) =>
          image.id === active.id ? { ...image, annotation: response.annotation } : image,
        ),
      );
      refreshProject();
      void fetchStats();
    } catch (error) {
      reportError(error, "标注保存失败");
    }
  };

  const onCreateShape = (shape: Omit<AnnotationShape, "id">) => {
    const created: AnnotationShape = { ...shape, id: `s${Date.now().toString(36)}` };
    const next = [...shapes, created];
    setShapes(next);
    void persist({ shapes: next });
  };

  const removeShape = (id: string) => {
    const next = shapes.filter((shape) => shape.id !== id);
    setShapes(next);
    void persist({ shapes: next });
  };

  const upload = async (files: FileList | null) => {
    if (!files?.length || !projectId) return;
    setBusy(true);
    try {
      const result = await api.uploadImages(projectId, Array.from(files));
      toast(`导入 ${result.imported} 张图片${result.failed.length ? `，${result.failed.length} 张失败` : ""}`, "success");
      await fetchImages();
      await fetchStats();
      refreshProject();
    } catch (error) {
      reportError(error, "导入失败");
    } finally {
      setBusy(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const importFolder = async () => {
    if (!projectId || !importPath.trim()) return;
    setBusy(true);
    try {
      const result = await api.importFolder(projectId, importPath.trim(), importRecursive);
      toast(`从目录导入 ${result.imported} 张图片`, "success");
      setImportOpen(false);
      await fetchImages();
      await fetchStats();
      refreshProject();
    } catch (error) {
      reportError(error, "目录导入失败");
    } finally {
      setBusy(false);
    }
  };

  const selectedIds = Array.from(selected);

  const applyBulkLabel = async (label: string) => {
    if (!projectId || !selectedIds.length) return;
    try {
      const result = await api.bulkLabel(projectId, selectedIds, label);
      toast(`已标注 ${result.updated} 张为 ${label}`, "success");
      setSelected(new Set());
      await fetchImages();
      await fetchStats();
      refreshProject();
    } catch (error) {
      reportError(error, "批量标注失败");
    }
  };

  const applySplit = async (split: string) => {
    if (!projectId || !selectedIds.length) return;
    try {
      await api.setSplit(projectId, selectedIds, split);
      toast(`已移动 ${selectedIds.length} 张到 ${SPLIT_LABELS[split]}`, "success");
      setSelected(new Set());
      await fetchImages();
      await fetchStats();
    } catch (error) {
      reportError(error, "划分失败");
    }
  };

  const autoSplit = async () => {
    if (!projectId) return;
    try {
      const result = await api.autoSplit(projectId);
      toast(
        `自动划分完成：训练 ${result.split.train ?? 0} / 验证 ${result.split.val ?? 0} / 测试 ${result.split.test ?? 0}`,
        "success",
      );
      await fetchImages();
      await fetchStats();
    } catch (error) {
      reportError(error, "自动划分失败");
    }
  };

  const exportCoco = async () => {
    if (!projectId) return;
    try {
      const result = await api.exportAnnotations(projectId, "coco");
      const blob = new Blob([JSON.stringify(result.data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${project?.name || "dataset"}_coco.json`;
      link.click();
      URL.revokeObjectURL(url);
      toast("已导出 COCO JSON", "success");
    } catch (error) {
      reportError(error, "COCO 导出失败");
    }
  };

  const removeSelected = async () => {
    if (!projectId || !selectedIds.length) return;
    try {
      const result = await api.deleteImages(projectId, selectedIds);
      toast(`已删除 ${result.deleted} 张图片`, "success");
      setSelected(new Set());
      setConfirmDelete(false);
      await fetchImages();
      await fetchStats();
      refreshProject();
    } catch (error) {
      reportError(error, "删除失败");
    }
  };

  const addLabel = async () => {
    if (!projectId || !newLabel.trim()) return;
    try {
      await api.createLabel(projectId, newLabel.trim());
      setNewLabel("");
      refreshProject();
    } catch (error) {
      reportError(error, "新增类别失败");
    }
  };

  const toggleSelect = (id: string, event: React.MouseEvent) => {
    event.stopPropagation();
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex h-full min-h-0">
      {/* dataset browser */}
      <div className="flex w-[320px] shrink-0 flex-col border-r border-line">
        <SectionTitle
          title="数据集"
          hint={`${total} 张图片${stats ? ` · ${formatBytes(stats.diskBytes)}` : ""}`}
          actions={
            <>
              <button
                className="btn-subtle px-1.5 py-1"
                title="上传图片"
                onClick={() => fileInput.current?.click()}
              >
                <Upload className="h-3.5 w-3.5" />
              </button>
              <button
                className="btn-subtle px-1.5 py-1"
                title="从服务器目录导入"
                onClick={() => setImportOpen(true)}
              >
                <FolderInput className="h-3.5 w-3.5" />
              </button>
              <button className="btn-subtle px-1.5 py-1" title="自动划分数据集" onClick={autoSplit}>
                <Shuffle className="h-3.5 w-3.5" />
              </button>
              <button className="btn-subtle px-1.5 py-1" title="导出 COCO JSON" onClick={() => void exportCoco()}>
                <Download className="h-3.5 w-3.5" />
              </button>
            </>
          }
        />
        <input
          ref={fileInput}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={(event) => void upload(event.target.files)}
        />

        <div className="space-y-1.5 border-b border-line px-2.5 py-2">
          <input
            className="field"
            placeholder="按文件名搜索"
            value={filters.search}
            onChange={(event) => {
              setPage(1);
              setFilters({ ...filters, search: event.target.value });
            }}
          />
          <div className="grid grid-cols-3 gap-1.5">
            <select
              className="field px-1.5"
              value={filters.split}
              onChange={(event) => {
                setPage(1);
                setFilters({ ...filters, split: event.target.value });
              }}
            >
              <option value="">全部划分</option>
              {SPLITS.map((split) => (
                <option key={split} value={split}>
                  {SPLIT_LABELS[split]}
                </option>
              ))}
            </select>
            <select
              className="field px-1.5"
              value={filters.label}
              onChange={(event) => {
                setPage(1);
                setFilters({ ...filters, label: event.target.value });
              }}
            >
              <option value="">全部类别</option>
              {labels.map((label) => (
                <option key={label.id} value={label.name}>
                  {label.name}
                </option>
              ))}
            </select>
            <select
              className="field px-1.5"
              value={filters.annotated}
              onChange={(event) => {
                setPage(1);
                setFilters({ ...filters, annotated: event.target.value });
              }}
            >
              <option value="">标注状态</option>
              <option value="yes">已标注</option>
              <option value="no">未标注</option>
            </select>
          </div>
        </div>

        {selected.size > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5 border-b border-line bg-brand-dim/10 px-2.5 py-2 text-[11.5px]">
            <span className="text-brand">已选 {selected.size} 张</span>
            {labels.map((label) => (
              <button
                key={label.id}
                className="btn-ghost px-1.5 py-0.5 text-[11px]"
                onClick={() => void applyBulkLabel(label.name)}
              >
                <Tag className="h-3 w-3" style={{ color: label.color }} /> {label.name}
              </button>
            ))}
            <select
              className="field w-auto px-1.5 py-0.5 text-[11px]"
              value=""
              onChange={(event) => event.target.value && void applySplit(event.target.value)}
            >
              <option value="">移动到…</option>
              {SPLITS.map((split) => (
                <option key={split} value={split}>
                  {SPLIT_LABELS[split]}
                </option>
              ))}
            </select>
            <button className="btn-subtle px-1.5 py-0.5 text-[11px]" onClick={() => setSelected(new Set())}>
              取消
            </button>
            <button
              className="btn-subtle px-1.5 py-0.5 text-[11px] hover:text-ng"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="h-3 w-3" /> 删除
            </button>
          </div>
        ) : null}

        <div className="scroll-y flex-1 p-2">
          {loading ? (
            <div className="flex items-center gap-2 p-2 text-[12px] text-mute">
              <Spinner /> 加载中…
            </div>
          ) : images.length === 0 ? (
            <EmptyState
              title="暂无图片"
              hint="上传图片或从服务器目录导入，支持 png/jpg/bmp/tif。"
              action={
                <button className="btn-ghost" onClick={() => fileInput.current?.click()}>
                  <Upload className="h-3.5 w-3.5" /> 上传图片
                </button>
              }
            />
          ) : (
            <div className="grid grid-cols-3 gap-1.5">
              {images.map((image) => {
                const isActive = image.id === activeId;
                const label = image.annotation?.label;
                return (
                  <button
                    key={image.id}
                    onClick={() => setActiveId(image.id)}
                    className={`group relative aspect-square overflow-hidden rounded-md border transition ${
                      isActive ? "border-brand" : "border-line hover:border-brand/40"
                    }`}
                    title={image.filename}
                  >
                    <img
                      src={image.thumbUrl}
                      alt={image.filename}
                      loading="lazy"
                      className="h-full w-full object-cover"
                    />
                    <span
                      className={`absolute top-1 left-1 h-3.5 w-3.5 rounded-sm border ${
                        selected.has(image.id)
                          ? "border-brand bg-brand"
                          : "border-white/50 bg-black/40 opacity-0 group-hover:opacity-100"
                      }`}
                      onClick={(event) => toggleSelect(image.id, event)}
                    />
                    {label ? (
                      <span
                        className="absolute right-1 bottom-1 rounded px-1 text-[10px] font-medium text-black/80"
                        style={{ background: labelColors[label] ?? "#38bdf8" }}
                      >
                        {label}
                      </span>
                    ) : null}
                    {image.annotation?.shapes?.length ? (
                      <span className="absolute top-1 right-1 rounded bg-black/60 px-1 text-[10px] text-brand">
                        {image.annotation.shapes.length}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-line px-2.5 py-1.5 text-[11.5px] text-mute">
          <button
            className="btn-subtle px-1.5 py-1"
            disabled={page <= 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
          >
            <ChevronLeft className="h-3.5 w-3.5" />
          </button>
          <span className="mono">
            {page} / {pageCount}
          </span>
          <button
            className="btn-subtle px-1.5 py-1"
            disabled={page >= pageCount}
            onClick={() => setPage((value) => Math.min(pageCount, value + 1))}
          >
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      {/* viewer */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-9 shrink-0 items-center gap-1.5 border-b border-line px-2">
          {TOOLS.map((item) => (
            <button
              key={item.value}
              className={`btn-subtle px-2 py-1 text-[12px] ${
                tool === item.value ? "bg-panel-3 text-ink" : ""
              }`}
              onClick={() => setTool(item.value)}
            >
              <item.icon className="h-3.5 w-3.5" /> {item.label}
            </button>
          ))}
          <div className="mx-1 h-4 w-px bg-line-solid" />
          <span className="text-[11.5px] text-mute">标注类别</span>
          <select
            className="field w-auto py-1"
            value={activeLabel}
            onChange={(event) => setActiveLabel(event.target.value)}
          >
            {labels.map((label) => (
              <option key={label.id} value={label.name}>
                {label.name}
              </option>
            ))}
          </select>
          <div className="flex-1" />
          {active ? (
            <span className="mono truncate text-[11.5px] text-mute">
              {active.filename} · {SPLIT_LABELS[active.split] ?? active.split} ·{" "}
              {formatBytes(active.sizeBytes)}
            </span>
          ) : null}
        </div>

        <ImageViewer
          className="flex-1"
          src={active?.previewUrl ?? null}
          shapes={shapes}
          tool={tool}
          labelColors={labelColors}
          activeLabel={activeLabel}
          selectedShapeId={selectedShape}
          onSelectShape={setSelectedShape}
          onCreateShape={onCreateShape}
          emptyHint="从左侧选择一张图片"
        />
      </div>

      {/* right panel */}
      <div className="flex w-[300px] shrink-0 flex-col border-l border-line">
        <Tabs
          value={rightTab}
          onChange={setRightTab}
          tabs={[
            { value: "annotate", label: "标注" },
            { value: "quality", label: "图像质量" },
            { value: "stats", label: "统计" },
          ]}
        />

        <div className="scroll-y flex-1 p-2.5">
          {rightTab === "annotate" ? (
            !active ? (
              <EmptyState title="未选择图片" />
            ) : (
              <div className="space-y-3">
                <div>
                  <label className="label-text">整图类别</label>
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {labels.map((label) => (
                      <button
                        key={label.id}
                        className={`chip border ${
                          imageLabel === label.name
                            ? "border-transparent text-black"
                            : "border-line-solid text-mute hover:text-ink"
                        }`}
                        style={
                          imageLabel === label.name ? { background: label.color } : { background: "transparent" }
                        }
                        onClick={() => {
                          const next = imageLabel === label.name ? null : label.name;
                          setImageLabel(next);
                          void persist({ label: next });
                        }}
                      >
                        {label.name}
                      </button>
                    ))}
                  </div>
                  <div className="mt-2 flex gap-1.5">
                    <input
                      className="field"
                      placeholder="新增类别"
                      value={newLabel}
                      onChange={(event) => setNewLabel(event.target.value)}
                      onKeyDown={(event) => event.key === "Enter" && void addLabel()}
                    />
                    <button className="btn-ghost" onClick={addLabel}>
                      添加
                    </button>
                  </div>
                </div>

                <div>
                  <div className="flex items-center justify-between">
                    <label className="label-text">形状标注 ({shapes.length})</label>
                    <button
                      className="btn-subtle px-1.5 py-0.5 text-[11px]"
                      onClick={() => void persist({ reviewed: true })}
                    >
                      <CheckCheck className="h-3 w-3" /> 标记已复核
                    </button>
                  </div>
                  <div className="mt-1.5 space-y-1">
                    {shapes.length === 0 ? (
                      <div className="rounded-md border border-dashed border-line-solid px-2 py-3 text-center text-[11.5px] text-mute">
                        用上方工具在图中框选目标
                      </div>
                    ) : (
                      shapes.map((shape) => (
                        <div
                          key={shape.id}
                          className={`flex items-center gap-2 rounded-md border px-2 py-1 text-[11.5px] ${
                            selectedShape === shape.id ? "border-brand bg-brand/10" : "border-line bg-panel-2"
                          }`}
                          onMouseEnter={() => setSelectedShape(shape.id)}
                        >
                          <span
                            className="h-2.5 w-2.5 rounded-sm"
                            style={{ background: labelColors[shape.label] ?? "#38bdf8" }}
                          />
                          <span className="flex-1 truncate">
                            {shape.label || "未命名"} · {shape.type}
                          </span>
                          <span className="mono text-mute">
                            {shape.type === "bbox" && shape.points.length >= 2
                              ? `${Math.abs(shape.points[1][0] - shape.points[0][0])}×${Math.abs(
                                  shape.points[1][1] - shape.points[0][1],
                                )}`
                              : `${shape.points.length}pt`}
                          </span>
                          <button
                            className="btn-subtle px-1 py-0.5 hover:text-ng"
                            onClick={() => removeShape(shape.id)}
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </div>
                      ))
                    )}
                  </div>
                </div>

                <div>
                  <label className="label-text">备注</label>
                  <textarea
                    className="field mt-1 h-16 resize-none"
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    onBlur={() => void persist({ note })}
                  />
                </div>

                <div className="rounded-md border border-line bg-panel-2 px-2 py-1.5 text-[11.5px] text-mute">
                  <div className="mono">
                    {active.width} × {active.height} · {active.channels} 通道 · {active.format}
                  </div>
                  <div className="mt-1 flex items-center gap-1.5">
                    划分
                    <select
                      className="field w-auto px-1.5 py-0.5 text-[11px]"
                      value={active.split}
                      onChange={async (event) => {
                        await api.setSplit(projectId, [active.id], event.target.value);
                        await fetchImages();
                        await fetchStats();
                      }}
                    >
                      {SPLITS.map((split) => (
                        <option key={split} value={split}>
                          {SPLIT_LABELS[split]}
                        </option>
                      ))}
                    </select>
                    {active.annotation?.reviewed ? <Badge tone="ok">已复核</Badge> : null}
                  </div>
                </div>
              </div>
            )
          ) : rightTab === "quality" ? (
            !active ? (
              <EmptyState title="未选择图片" />
            ) : (
              <div className="space-y-3">
                <div>
                  <div className="label-text mb-1 flex items-center gap-1">
                    <BarChart3 className="h-3 w-3" /> 直方图
                  </div>
                  {histogram ? (
                    <Histogram channels={histogram} />
                  ) : (
                    <div className="flex items-center gap-2 py-4 text-[12px] text-mute">
                      <Spinner /> 计算中…
                    </div>
                  )}
                  {histStats ? (
                    <div className="mono mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-mute">
                      <span>min {formatNumber(histStats.min, 0)}</span>
                      <span>max {formatNumber(histStats.max, 0)}</span>
                      <span>mean {formatNumber(histStats.mean, 1)}</span>
                      <span>std {formatNumber(histStats.std, 1)}</span>
                    </div>
                  ) : null}
                </div>
                <div>
                  <div className="label-text mb-1 flex items-center gap-1">
                    <Activity className="h-3 w-3" /> 成像诊断
                  </div>
                  {diagnosis ? <DiagnosisPanel diagnosis={diagnosis} /> : null}
                </div>
              </div>
            )
          ) : (
            <div className="space-y-3">
              {stats ? (
                <>
                  <div className="grid grid-cols-2 gap-1.5">
                    {[
                      ["图片总数", stats.total],
                      ["已标注", stats.annotated],
                      ["未标注", stats.unannotated],
                      ["形状数", stats.shapeCount],
                    ].map(([label, value]) => (
                      <div key={String(label)} className="rounded-md border border-line bg-panel-2 px-2 py-1.5">
                        <div className="text-[10.5px] text-mute">{label}</div>
                        <div className="mono text-[14px]">{String(value)}</div>
                      </div>
                    ))}
                  </div>
                  <div>
                    <div className="label-text mb-1">数据划分</div>
                    {SPLITS.map((split) => (
                      <div key={split} className="flex items-center gap-2 py-0.5 text-[12px]">
                        <span className="w-14 text-mute">{SPLIT_LABELS[split]}</span>
                        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-panel-3">
                          <div
                            className="h-full bg-brand-dim"
                            style={{
                              width: `${((stats.bySplit[split] ?? 0) / Math.max(1, stats.total)) * 100}%`,
                            }}
                          />
                        </div>
                        <span className="mono w-8 text-right text-mute">{stats.bySplit[split] ?? 0}</span>
                      </div>
                    ))}
                  </div>
                  <div>
                    <div className="label-text mb-1">类别分布</div>
                    {Object.entries(stats.byLabel).length === 0 ? (
                      <div className="text-[11.5px] text-mute">暂无标注</div>
                    ) : (
                      Object.entries(stats.byLabel).map(([label, count]) => (
                        <div key={label} className="flex items-center gap-2 py-0.5 text-[12px]">
                          <span
                            className="h-2.5 w-2.5 rounded-sm"
                            style={{ background: labelColors[label] ?? "#38bdf8" }}
                          />
                          <span className="flex-1 truncate">{label}</span>
                          <span className="mono text-mute">{count}</span>
                        </div>
                      ))
                    )}
                  </div>
                </>
              ) : (
                <Spinner />
              )}
            </div>
          )}
        </div>
      </div>

      <Modal
        open={importOpen}
        title="从服务器目录导入"
        onClose={() => setImportOpen(false)}
        footer={
          <>
            <button className="btn-ghost" onClick={() => setImportOpen(false)}>
              取消
            </button>
            <button className="btn-primary" disabled={busy} onClick={importFolder}>
              {busy ? <Spinner /> : null} 导入
            </button>
          </>
        }
      >
        <label className="label-text">目录绝对路径</label>
        <input
          className="field mt-1"
          placeholder="/opt/AI-CV-platform/ipsc_texture_classifier/data"
          value={importPath}
          onChange={(event) => setImportPath(event.target.value)}
        />
        <label className="mt-3 flex items-center gap-2 text-[12.5px] text-mute">
          <input
            type="checkbox"
            checked={importRecursive}
            onChange={(event) => setImportRecursive(event.target.checked)}
          />
          包含子目录
        </label>
      </Modal>

      <Confirm
        open={confirmDelete}
        title="删除图片"
        message={`将删除选中的 ${selected.size} 张图片及其标注。`}
        confirmText="删除"
        onCancel={() => setConfirmDelete(false)}
        onConfirm={removeSelected}
      />
    </div>
  );
}

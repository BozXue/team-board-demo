import { useCallback, useEffect, useRef, useState } from "react";
import { Brain, GraduationCap, Trash2, Upload } from "lucide-react";
import { api } from "../api/client";
import type { ModelAsset, ModelTrainer } from "../api/types";
import { Badge, EmptyState, SectionTitle, Spinner, formatNumber, formatTime, useDebounced } from "../components/ui";
import { useApp } from "../store/app";

interface SampleInfo {
  sampleCount: number;
  classes: string[];
  distribution: Record<string, number>;
  stats: Record<string, unknown>;
  trainable: boolean;
}

const DEFAULT_TRAINERS: ModelTrainer[] = [
  { id: "lbp_svm", name: "LBP + SVM", family: "classical", available: true, hint: "纹理特征，小样本可用" },
  { id: "efficientnet", name: "EfficientNet-B0", family: "deep", available: false, hint: "需要 PyTorch" },
  { id: "yolo", name: "YOLO 分类", family: "deep", available: false, hint: "需要 Ultralytics" },
];

export default function ModelsPage() {
  const { project, toast, reportError } = useApp();
  const projectId = project?.id ?? "";
  const [models, setModels] = useState<ModelAsset[]>([]);
  const [samples, setSamples] = useState<SampleInfo | null>(null);
  const [trainers, setTrainers] = useState<ModelTrainer[]>(DEFAULT_TRAINERS);
  const [training, setTraining] = useState(false);
  const [importing, setImporting] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const [form, setForm] = useState({
    name: "",
    arch: "lbp_svm",
    kernel: "rbf",
    c: 1,
    splits: "",
    epochs: 8,
    imgsz: 384,
    batch: 8,
    yoloBase: "yolo11n-cls.pt",
  });
  const debouncedSplits = useDebounced(form.splits, 300);
  const selected = trainers.find((item) => item.id === form.arch) ?? trainers[0];
  const isDeep = selected?.family === "deep";

  const refresh = useCallback(async () => {
    if (!projectId) return;
    try {
      const [modelData, sampleData, trainerData] = await Promise.all([
        api.listModels(projectId),
        api.trainingSamples(projectId, debouncedSplits.trim() || undefined),
        api.listTrainers(),
      ]);
      setModels(modelData.models);
      setSamples(sampleData);
      if (trainerData.trainers.length) setTrainers(trainerData.trainers);
    } catch (error) {
      reportError(error, "模型信息加载失败");
    }
  }, [projectId, reportError, debouncedSplits]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const train = async () => {
    if (!projectId) return;
    if (!selected?.available) {
      toast(selected?.hint || "该训练后端不可用", "error");
      return;
    }
    setTraining(true);
    try {
      const parsed = form.splits
        .split(/[,，]/)
        .map((item) => item.trim())
        .filter(Boolean);
      const model = await api.trainModel(projectId, {
        name: form.name.trim() || undefined,
        arch: form.arch,
        kernel: form.kernel,
        c: form.c,
        epochs: form.epochs,
        imgsz: form.imgsz,
        batch: form.batch,
        yoloBase: form.yoloBase,
        splits: parsed.length ? parsed : undefined,
      });
      const score = model.metrics.cvAccuracy ?? model.metrics.valAccuracy ?? model.metrics.accuracy;
      toast(
        `训练完成：${model.name}${
          typeof score === "number" ? `，验证准确率 ${(Number(score) * 100).toFixed(1)}%` : ""
        }`,
        "success",
      );
      await refresh();
    } catch (error) {
      reportError(error, "训练失败");
    } finally {
      setTraining(false);
    }
  };

  const importFromFile = async (files: FileList | null) => {
    if (!files?.length || !projectId) return;
    setImporting(true);
    try {
      for (const file of Array.from(files)) {
        const isSam = /sam/i.test(file.name);
        await api.importModel(file, {
          name: file.name.replace(/\.[^.]+$/, ""),
          task: isSam ? "segmentation" : "classification",
          projectId,
        });
      }
      toast(`已上传 ${files.length} 个模型`, "success");
      await refresh();
    } catch (error) {
      reportError(error, "模型上传失败");
    } finally {
      setImporting(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  return (
    <div className="flex h-full min-h-0">
      <div className="flex w-[300px] shrink-0 flex-col border-r border-line">
        <SectionTitle title="训练分类模型" hint={selected?.hint ?? "选择一种架构后开始训练"} />
        <div className="scroll-y flex-1 p-2.5">
          {samples ? (
            <>
              <div className="grid grid-cols-2 gap-1.5">
                <div className="rounded-md border border-line bg-panel-2 px-2 py-1.5">
                  <div className="text-[10.5px] text-mute">可用样本</div>
                  <div className="mono text-[15px]">{samples.sampleCount}</div>
                </div>
                <div className="rounded-md border border-line bg-panel-2 px-2 py-1.5">
                  <div className="text-[10.5px] text-mute">类别数</div>
                  <div className="mono text-[15px]">{samples.classes.length}</div>
                </div>
              </div>
              <div className="mt-2 space-y-1">
                {Object.entries(samples.distribution).map(([label, count]) => (
                  <div key={label} className="flex items-center gap-2 text-[12px]">
                    <span className="flex-1 truncate">{label}</span>
                    <span className="mono text-mute">{count}</span>
                  </div>
                ))}
              </div>
              {samples.stats.bySplit && typeof samples.stats.bySplit === "object" ? (
                <div className="mt-1.5 text-[11px] text-mute">
                  标注所在划分：
                  {Object.entries(samples.stats.bySplit as Record<string, number>)
                    .map(([split, count]) => `${split} ${count}`)
                    .join(" · ") || "无"}
                </div>
              ) : null}
              {!samples.trainable ? (
                <div className="mt-2 rounded-md border border-warn/40 bg-warn/10 px-2 py-1.5 text-[11.5px] text-warn">
                  {form.splits.trim()
                    ? `当前划分「${form.splits}」里没有足够样本。留空使用全部已标注图。`
                    : "样本不足：至少需要 2 个类别、4 张已标注图片。"}
                </div>
              ) : null}

              <div className="mt-3 space-y-2">
                <div>
                  <label className="label-text">模型架构</label>
                  <select
                    className="field mt-1 py-1"
                    value={form.arch}
                    onChange={(event) => setForm({ ...form, arch: event.target.value })}
                  >
                    {trainers.map((trainer) => (
                      <option key={trainer.id} value={trainer.id}>
                        {trainer.name}
                        {trainer.available ? "" : "（未安装依赖）"}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label-text">模型名称</label>
                  <input
                    className="field mt-1 py-1"
                    placeholder="自动命名"
                    value={form.name}
                    onChange={(event) => setForm({ ...form, name: event.target.value })}
                  />
                </div>
                <div>
                  <label className="label-text">参与训练的划分</label>
                  <input
                    className="field mt-1 py-1"
                    placeholder="留空 = 全部已标注"
                    value={form.splits}
                    onChange={(event) => setForm({ ...form, splits: event.target.value })}
                  />
                </div>
                {form.arch === "lbp_svm" ? (
                  <div className="grid grid-cols-2 gap-1.5">
                    <div>
                      <label className="label-text">核函数</label>
                      <select
                        className="field mt-1 py-1"
                        value={form.kernel}
                        onChange={(event) => setForm({ ...form, kernel: event.target.value })}
                      >
                        <option value="rbf">rbf</option>
                        <option value="linear">linear</option>
                        <option value="poly">poly</option>
                      </select>
                    </div>
                    <div>
                      <label className="label-text">C</label>
                      <input
                        className="field mt-1 py-1"
                        type="number"
                        step={0.1}
                        min={0.01}
                        value={form.c}
                        onChange={(event) => setForm({ ...form, c: parseFloat(event.target.value) || 1 })}
                      />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="grid grid-cols-3 gap-1.5">
                      <div>
                        <label className="label-text">轮数</label>
                        <input
                          className="field mt-1 py-1"
                          type="number"
                          min={1}
                          max={200}
                          value={form.epochs}
                          onChange={(event) =>
                            setForm({ ...form, epochs: parseInt(event.target.value, 10) || 8 })
                          }
                        />
                      </div>
                      <div>
                        <label className="label-text">边长</label>
                        <input
                          className="field mt-1 py-1"
                          type="number"
                          min={64}
                          step={32}
                          value={form.imgsz}
                          onChange={(event) =>
                            setForm({ ...form, imgsz: parseInt(event.target.value, 10) || 384 })
                          }
                        />
                      </div>
                      <div>
                        <label className="label-text">batch</label>
                        <input
                          className="field mt-1 py-1"
                          type="number"
                          min={1}
                          value={form.batch}
                          onChange={(event) =>
                            setForm({ ...form, batch: parseInt(event.target.value, 10) || 8 })
                          }
                        />
                      </div>
                    </div>
                    {form.arch === "yolo" ? (
                      <div>
                        <label className="label-text">YOLO 底座</label>
                        <select
                          className="field mt-1 py-1"
                          value={form.yoloBase}
                          onChange={(event) => setForm({ ...form, yoloBase: event.target.value })}
                        >
                          <option value="yolo11n-cls.pt">yolo11n-cls（快）</option>
                          <option value="yolo11s-cls.pt">yolo11s-cls</option>
                          <option value="yolo11m-cls.pt">yolo11m-cls</option>
                        </select>
                      </div>
                    ) : null}
                    <p className="text-[10.5px] leading-relaxed text-mute">
                      深度模型用整图（或框标注裁块）微调，训完导出 ONNX，可直接接到流程的「AI 分类」节点。
                    </p>
                  </div>
                )}
                <button
                  className="btn-primary w-full"
                  disabled={training || !samples.trainable || !selected?.available}
                  onClick={train}
                >
                  {training ? <Spinner /> : <GraduationCap className="h-3.5 w-3.5" />}
                  {training ? (isDeep ? "训练中，请稍候…" : "训练中") : "开始训练"}
                </button>
                {!selected?.available ? (
                  <p className="text-[11px] leading-relaxed text-warn">{selected?.hint}</p>
                ) : (
                  <p className="text-[10.5px] leading-relaxed text-mute">
                    训练完成的模型可在流程里通过「AI 分类」节点调用。
                  </p>
                )}
              </div>
            </>
          ) : (
            <Spinner />
          )}
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <SectionTitle
          title="模型库"
          hint={`${models.length} 个模型 · SAM 权重请上传 sam2_b.pt`}
          actions={
            <>
              <input
                ref={fileInput}
                type="file"
                className="hidden"
                accept=".pt,.onnx,.joblib,.pkl"
                onChange={(event) => void importFromFile(event.target.files)}
              />
              <button className="btn-subtle py-1" disabled={importing} onClick={() => fileInput.current?.click()}>
                {importing ? <Spinner /> : <Upload className="h-3.5 w-3.5" />}
                {importing ? "上传中…" : "上传模型"}
              </button>
            </>
          }
        />
        <div className="scroll-y flex-1 p-3">
          {models.length === 0 ? (
            <EmptyState
              icon={<Brain className="h-6 w-6" />}
              title="还没有模型"
              hint="可上传本地 .pt / ONNX，或左侧训练。SAM 请上传 sam2_b.pt。"
            />
          ) : (
            <div className="grid grid-cols-1 gap-2 lg:grid-cols-2 xl:grid-cols-3">
              {models.map((model) => (
                <div key={model.id} className="panel p-3">
                  <div className="flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-[13px] font-medium">{model.name}</div>
                      <div className="mono truncate text-[10.5px] text-mute">{model.id}</div>
                    </div>
                    <Badge tone={model.available ? "ok" : "ng"}>{model.available ? "可用" : "文件缺失"}</Badge>
                    <button
                      className="btn-subtle px-1.5 py-1 hover:text-ng"
                      onClick={async () => {
                        await api.deleteModel(model.id);
                        await refresh();
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <Badge>{model.task}</Badge>
                    <Badge>{model.framework}</Badge>
                    <Badge>{String(model.meta?.arch ?? model.framework)}</Badge>
                    <Badge>{model.inputSize}px</Badge>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {model.classes.map((cls) => (
                      <span key={cls} className="chip bg-panel-3 text-mute">
                        {cls}
                      </span>
                    ))}
                  </div>
                  <div className="mono mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px] text-mute">
                    {Object.entries(model.metrics ?? {}).map(([key, value]) => (
                      <span key={key} className="truncate">
                        {key}: <span className="text-ink/90">{formatNumber(value, 3)}</span>
                      </span>
                    ))}
                  </div>
                  <div className="mt-2 text-[10.5px] text-mute/70">{formatTime(model.createdAt)}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

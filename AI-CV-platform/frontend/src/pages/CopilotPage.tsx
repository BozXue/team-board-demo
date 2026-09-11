import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Check, MessageSquare, Send, Sparkles, Stethoscope, Trash2, Wand2 } from "lucide-react";
import { api } from "../api/client";
import type { CopilotPlanResponse, Diagnosis, ImageAsset } from "../api/types";
import { DiagnosisPanel } from "../components/DiagnosisPanel";
import { Badge, EmptyState, SectionTitle, Spinner, formatTime } from "../components/ui";
import { useApp } from "../store/app";
import { usePipeline } from "../store/pipeline";

const EXAMPLES = [
  "显微图像里找出纹理致密的 iPSC 克隆区域，算出面积占比，低于 10% 报警",
  "检查布面上的深色污渍，超过 500 像素的算 NG",
  "统计视野内的圆形颗粒数量，少于 20 个报警",
  "判断零件是否装配到位（有/无检测）",
];

export default function CopilotPage() {
  const navigate = useNavigate();
  const { project, loadProject, meta, toast, reportError } = useApp();
  const projectId = project?.id ?? "";
  const load = usePipeline((s) => s.load);

  const [text, setText] = useState("");
  const [imageId, setImageId] = useState<string>("");
  const [images, setImages] = useState<ImageAsset[]>([]);
  const [planning, setPlanning] = useState(false);
  const [plan, setPlan] = useState<CopilotPlanResponse | null>(null);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [diagnosing, setDiagnosing] = useState(false);
  const [applying, setApplying] = useState(false);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [history, setHistory] = useState<
    { id: string; role: string; content: string; createdAt: string }[]
  >([]);

  useEffect(() => {
    if (!projectId) return;
    setText(project?.requirement ?? "");
    void api
      .listImages(projectId, { pageSize: 100 })
      .then((data) => {
        setImages(data.images);
        setImageId((current) => current || data.images[0]?.id || "");
      })
      .catch(() => undefined);
  }, [projectId, project?.requirement]);

  const refreshHistory = useCallback(async () => {
    if (!projectId) return;
    try {
      const data = await api.copilotHistory(projectId);
      setHistory(data.messages);
    } catch {
      /* ignore */
    }
  }, [projectId]);

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory]);

  const diagnose = async () => {
    if (!projectId) return;
    setDiagnosing(true);
    try {
      setDiagnosis(await api.diagnose(projectId, imageId || null));
    } catch (error) {
      reportError(error, "成像诊断失败");
    } finally {
      setDiagnosing(false);
    }
  };

  const generate = async () => {
    if (!projectId) return;
    if (!text.trim()) {
      toast("先用一句话描述检测需求", "error");
      return;
    }
    setPlanning(true);
    try {
      const response = await api.plan(projectId, text.trim(), imageId || null);
      setPlan(response);
      setDiagnosis(response.diagnosis);
      await refreshHistory();
    } catch (error) {
      reportError(error, "方案生成失败");
    } finally {
      setPlanning(false);
    }
  };

  const apply = async () => {
    if (!projectId || !plan) return;
    setApplying(true);
    try {
      const response = await api.applyPlan(projectId, plan.plan.graph, plan.plan.taskType);
      const detail = await loadProject(projectId);
      if (detail) load(detail.id, response.graph, detail.issues);
      toast("流程已生成，进入流程页微调参数", "success");
      navigate(`/projects/${projectId}/pipeline`);
    } catch (error) {
      reportError(error, "应用流程失败");
    } finally {
      setApplying(false);
    }
  };

  const ask = async () => {
    if (!projectId || !question.trim()) return;
    setAsking(true);
    try {
      await api.ask(projectId, question.trim());
      setQuestion("");
      await refreshHistory();
    } catch (error) {
      reportError(error, "提问失败");
    } finally {
      setAsking(false);
    }
  };

  return (
    <div className="flex h-full min-h-0">
      {/* left: requirement + plan */}
      <div className="flex min-w-0 flex-1 flex-col border-r border-line">
        <SectionTitle
          title="AI 引导"
          hint={
            meta?.llm.enabled
              ? `已接入 ${meta.llm.model}，会结合成像诊断给出方案`
              : "未配置大模型，当前使用内置规则引擎（结论同样可用）"
          }
        />

        <div className="scroll-y flex-1 p-3">
          <div className="panel p-3">
            <label className="label-text">用一句话描述你要检测什么</label>
            <textarea
              className="field mt-1.5 h-24 resize-none"
              value={text}
              placeholder="例如：显微图像里找出纹理致密的克隆区域，统计面积占比，低于 10% 报警"
              onChange={(event) => setText(event.target.value)}
            />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {EXAMPLES.map((example) => (
                <button
                  key={example}
                  className="chip bg-panel-3 text-mute hover:text-ink"
                  onClick={() => setText(example)}
                >
                  {example.slice(0, 18)}…
                </button>
              ))}
            </div>
            <div className="mt-3 flex items-center gap-2">
              <select
                className="field w-52 py-1"
                value={imageId}
                onChange={(event) => setImageId(event.target.value)}
              >
                <option value="">（用数据集抽样诊断）</option>
                {images.map((image) => (
                  <option key={image.id} value={image.id}>
                    {image.filename}
                  </option>
                ))}
              </select>
              <button className="btn-ghost" onClick={diagnose} disabled={diagnosing}>
                {diagnosing ? <Spinner /> : <Stethoscope className="h-3.5 w-3.5" />} 成像诊断
              </button>
              <div className="flex-1" />
              <button className="btn-primary" onClick={generate} disabled={planning}>
                {planning ? <Spinner /> : <Wand2 className="h-3.5 w-3.5" />} 生成方案
              </button>
            </div>
          </div>

          {plan ? (
            <div className="panel mt-3 p-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <Badge tone="brand">{plan.intent.taskLabel}</Badge>
                <span className="text-[11.5px] text-mute">
                  置信度 {(plan.intent.confidence * 100).toFixed(0)}%
                </span>
                <Badge tone={plan.plan.route === "ai" ? "warn" : "ok"}>
                  {plan.plan.route === "ai" ? "AI 模型路线" : plan.plan.route === "hybrid" ? "混合路线" : "传统算法路线"}
                </Badge>
                <Badge>{plan.plan.source === "llm" ? "大模型生成" : "规则引擎生成"}</Badge>
                <div className="flex-1" />
                <button className="btn-primary" onClick={apply} disabled={applying}>
                  {applying ? <Spinner /> : <Check className="h-3.5 w-3.5" />} 应用到流程
                </button>
              </div>

              <p className="mt-2 text-[12.5px] leading-relaxed text-ink/90">{plan.plan.summary}</p>
              <p className="mt-1 text-[11.5px] leading-relaxed text-mute">{plan.plan.routeReason}</p>

              {plan.intent.keywords.length ? (
                <div className="mt-2 flex flex-wrap gap-1">
                  {plan.intent.keywords.map((keyword) => (
                    <span key={keyword} className="chip bg-panel-3 text-mute">
                      {keyword}
                    </span>
                  ))}
                </div>
              ) : null}

              <div className="mt-3">
                <div className="label-text mb-1.5">方案步骤（{plan.plan.steps.length}）</div>
                <ol className="space-y-1">
                  {plan.plan.steps.map((step, index) => (
                    <li
                      key={step.nodeId}
                      className="flex gap-2 rounded-md border border-line bg-panel-2 px-2 py-1.5 text-[12px]"
                    >
                      <span className="mono w-4 shrink-0 text-mute/70">{index + 1}</span>
                      <span className="mono w-28 shrink-0 truncate text-brand">{step.nodeId}</span>
                      <span className="flex-1 leading-relaxed text-mute">{step.reason}</span>
                    </li>
                  ))}
                </ol>
              </div>

              {plan.plan.warnings.length ? (
                <div className="mt-2 space-y-1">
                  {plan.plan.warnings.map((warning, index) => (
                    <div
                      key={index}
                      className="rounded-md border border-warn/40 bg-warn/10 px-2 py-1 text-[11.5px] text-warn"
                    >
                      {warning}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {diagnosis ? (
            <div className="panel mt-3 p-3">
              <div className="label-text mb-2 flex items-center gap-1.5">
                <Stethoscope className="h-3 w-3" /> 成像诊断
                {diagnosis.sampleCount ? (
                  <span className="text-mute/70">（抽样 {diagnosis.sampleCount} 张）</span>
                ) : null}
              </div>
              <DiagnosisPanel diagnosis={diagnosis} />
            </div>
          ) : null}
        </div>
      </div>

      {/* right: conversation */}
      <div className="flex w-[330px] shrink-0 flex-col">
        <SectionTitle
          title="问答记录"
          hint="可以问算子怎么选、参数怎么调"
          actions={
            <button
              className="btn-subtle px-1.5 py-1"
              title="清空记录"
              onClick={async () => {
                if (!projectId) return;
                await api.clearCopilotHistory(projectId);
                await refreshHistory();
              }}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          }
        />
        <div className="scroll-y flex-1 space-y-2 p-2.5">
          {history.length === 0 ? (
            <EmptyState
              icon={<MessageSquare className="h-5 w-5" />}
              title="还没有对话"
              hint="例如：为什么这里要用自适应阈值？最小面积应该设多少？"
            />
          ) : (
            history.map((message) => (
              <div
                key={message.id}
                className={`rounded-md px-2 py-1.5 text-[12px] leading-relaxed ${
                  message.role === "user"
                    ? "border border-line-solid bg-panel-2"
                    : "border border-brand/25 bg-brand/10"
                }`}
              >
                <div className="mb-1 flex items-center gap-1.5 text-[10.5px] text-mute">
                  {message.role === "user" ? (
                    <>我</>
                  ) : (
                    <>
                      <Bot className="h-3 w-3 text-brand" /> AI 助手
                    </>
                  )}
                  <span className="ml-auto">{formatTime(message.createdAt)}</span>
                </div>
                <div className="whitespace-pre-wrap">{message.content}</div>
              </div>
            ))
          )}
        </div>
        <div className="border-t border-line p-2">
          <div className="flex items-end gap-1.5">
            <textarea
              className="field h-16 resize-none"
              placeholder="向 AI 助手提问…"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void ask();
                }
              }}
            />
            <button className="btn-primary h-8" onClick={ask} disabled={asking}>
              {asking ? <Spinner /> : <Send className="h-3.5 w-3.5" />}
            </button>
          </div>
          <div className="mt-1 flex items-center gap-1 text-[10.5px] text-mute">
            <Sparkles className="h-3 w-3" /> Enter 发送 · Shift+Enter 换行
          </div>
        </div>
      </div>
    </div>
  );
}

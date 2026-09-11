import { useEffect, useState } from "react";
import { NavLink, Outlet, useParams } from "react-router-dom";
import {
  Bot,
  Boxes,
  Brain,
  Images,
  MonitorPlay,
  Rocket,
  Sparkles,
  TestTubes,
  Workflow,
} from "lucide-react";
import { api } from "../../api/client";
import { useApp } from "../../store/app";
import { usePipeline } from "../../store/pipeline";
import { Badge, Modal, Spinner } from "../ui";

const NAV = [
  { to: "data", label: "数据", icon: Images },
  { to: "sam", label: "SAM智能标注", icon: Sparkles },
  { to: "copilot", label: "AI 助手", icon: Bot },
  { to: "pipeline", label: "流程", icon: Workflow },
  { to: "batch", label: "批量测试", icon: TestTubes },
  { to: "models", label: "模型", icon: Brain },
  { to: "runtime", label: "运行", icon: MonitorPlay },
];

export function ProjectShell() {
  const { projectId } = useParams();
  const { project, loadProject, clearProject, toast, reportError } = useApp();
  const resetPipeline = usePipeline((s) => s.reset);
  const [publishing, setPublishing] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [note, setNote] = useState("");

  useEffect(() => {
    if (!projectId) return;
    clearProject();
    resetPipeline();
    void loadProject(projectId);
    return () => clearProject();
  }, [projectId, loadProject, clearProject, resetPipeline]);

  const publish = async () => {
    if (!projectId) return;
    setPublishing(true);
    try {
      const result = await api.publishProject(projectId, note);
      toast(`已发布 v${result.version}，操作员模式可运行`, "success");
      setPublishOpen(false);
      setNote("");
      await loadProject(projectId);
    } catch (error) {
      reportError(error, "发布失败");
    } finally {
      setPublishing(false);
    }
  };

  if (!project || project.id !== projectId) {
    return (
      <div className="flex h-full items-center justify-center gap-2 text-[13px] text-mute">
        <Spinner /> 加载项目…
      </div>
    );
  }

  const errorCount = project.issues.filter((issue) => issue.level === "error").length;

  return (
    <div className="flex h-full">
      <aside className="flex w-[74px] shrink-0 flex-col items-center gap-1 border-r border-line bg-panel py-2">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) =>
              `flex w-[62px] flex-col items-center gap-1 rounded-md py-2 text-[11px] transition ${
                isActive ? "bg-brand-dim/15 text-brand" : "text-mute hover:bg-panel-2 hover:text-ink"
              }`
            }
          >
            <item.icon className="h-4 w-4" />
            {item.label}
          </NavLink>
        ))}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center gap-2 border-b border-line bg-panel-2/60 px-3">
          <Boxes className="h-4 w-4 text-mute" />
          <div className="truncate text-[13px] font-medium">{project.name}</div>
          <Badge>{project.taskType}</Badge>
          <span className="text-[11px] text-mute">
            {project.imageCount} 图 · {project.nodeCount} 节点 · {project.annotationCount} 标注
          </span>
          {errorCount > 0 ? <Badge tone="ng">{errorCount} 个流程错误</Badge> : null}
          {project.publishedVersionId ? <Badge tone="ok">已发布</Badge> : <Badge tone="warn">未发布</Badge>}
          <div className="flex-1" />
          <button className="btn-primary" onClick={() => setPublishOpen(true)}>
            <Rocket className="h-3.5 w-3.5" /> 发布
          </button>
        </div>

        <div className="min-h-0 flex-1">
          <Outlet />
        </div>
      </div>

      <Modal
        open={publishOpen}
        title="发布流程"
        onClose={() => setPublishOpen(false)}
        footer={
          <>
            <button className="btn-ghost" onClick={() => setPublishOpen(false)}>
              取消
            </button>
            <button className="btn-primary" disabled={publishing} onClick={publish}>
              {publishing ? <Spinner /> : <Rocket className="h-3.5 w-3.5" />} 发布
            </button>
          </>
        }
      >
        <p className="mb-3 text-[12.5px] leading-relaxed text-mute">
          发布会锁定当前流程为新版本，并把标记为“业务参数”的项暴露给操作员界面。发布后可在「运行」页试运行。
        </p>
        <label className="label-text">版本说明</label>
        <input
          className="field mt-1"
          value={note}
          placeholder="例如：调整最小面积阈值至 800px"
          onChange={(event) => setNote(event.target.value)}
        />
        {errorCount > 0 ? (
          <div className="mt-3 rounded-md border border-ng/40 bg-ng/10 px-2.5 py-2 text-[12px] text-ng">
            当前流程存在 {errorCount} 个错误，发布后运行时会失败，建议先到「流程」页修复。
          </div>
        ) : null}
      </Modal>
    </div>
  );
}

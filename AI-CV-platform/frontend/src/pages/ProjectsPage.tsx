import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Copy, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { api } from "../api/client";
import type { PipelineTemplate, ProjectSummary } from "../api/types";
import { Badge, Confirm, EmptyState, Modal, Spinner, formatTime, useDebounced } from "../components/ui";
import { useApp } from "../store/app";

export default function ProjectsPage() {
  const navigate = useNavigate();
  const { projects, refreshProjects, toast, reportError, booting } = useApp();
  const [search, setSearch] = useState("");
  const debounced = useDebounced(search, 300);
  const [templates, setTemplates] = useState<PipelineTemplate[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<ProjectSummary | null>(null);
  const [editTarget, setEditTarget] = useState<ProjectSummary | null>(null);
  const [editForm, setEditForm] = useState({ name: "", description: "" });
  const [form, setForm] = useState({
    name: "",
    description: "",
    templateId: "blank",
    requirement: "",
    labels: "OK, NG",
  });

  useEffect(() => {
    void refreshProjects(debounced);
  }, [debounced, refreshProjects]);

  useEffect(() => {
    api
      .templates()
      .then((data) => setTemplates(data.templates))
      .catch(() => undefined);
  }, []);

  const create = async () => {
    if (!form.name.trim()) {
      toast("请填写项目名称", "error");
      return;
    }
    setPending(true);
    try {
      const project = await api.createProject({
        name: form.name.trim(),
        description: form.description.trim(),
        templateId: form.templateId,
        requirement: form.requirement.trim(),
        labels: form.labels
          .split(/[,，]/)
          .map((item) => item.trim())
          .filter(Boolean),
      });
      toast("项目已创建", "success");
      setCreateOpen(false);
      navigate(`/projects/${project.id}/data`);
    } catch (error) {
      reportError(error, "项目创建失败");
    } finally {
      setPending(false);
    }
  };

  const openEdit = (project: ProjectSummary) => {
    setEditTarget(project);
    setEditForm({ name: project.name, description: project.description || "" });
  };

  const saveEdit = async () => {
    if (!editTarget) return;
    if (!editForm.name.trim()) {
      toast("请填写项目名称", "error");
      return;
    }
    setPending(true);
    try {
      await api.updateProject(editTarget.id, {
        name: editForm.name.trim(),
        description: editForm.description.trim(),
      });
      toast("项目信息已更新", "success");
      setEditTarget(null);
      await refreshProjects(debounced);
    } catch (error) {
      reportError(error, "保存失败");
    } finally {
      setPending(false);
    }
  };

  const duplicate = async (project: ProjectSummary) => {
    try {
      await api.duplicateProject(project.id);
      toast("已复制项目", "success");
      await refreshProjects(debounced);
    } catch (error) {
      reportError(error, "复制失败");
    }
  };

  const remove = async () => {
    if (!removeTarget) return;
    try {
      await api.deleteProject(removeTarget.id);
      toast("项目已删除", "success");
      setRemoveTarget(null);
      await refreshProjects(debounced);
    } catch (error) {
      reportError(error, "删除失败");
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <div className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold">项目</h1>
          <p className="mt-0.5 text-[12.5px] text-mute">
            一个项目 = 一套检测方案：数据集 + 视觉流程 + 标注 + 发布版本
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute top-2 left-2 h-3.5 w-3.5 text-mute" />
            <input
              className="field w-56 pl-7"
              placeholder="搜索项目"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <button className="btn-primary" onClick={() => setCreateOpen(true)}>
            <Plus className="h-3.5 w-3.5" /> 新建项目
          </button>
        </div>
      </div>

      {booting ? (
        <div className="flex items-center gap-2 text-[13px] text-mute">
          <Spinner /> 加载中…
        </div>
      ) : projects.length === 0 ? (
        <div className="panel h-72">
          <EmptyState
            title="还没有项目"
            hint="从模板新建一个项目，导入图片后让 AI 助手生成检测流程。"
            action={
              <button className="btn-primary" onClick={() => setCreateOpen(true)}>
                <Plus className="h-3.5 w-3.5" /> 新建项目
              </button>
            }
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {projects.map((project) => (
            <div
              key={project.id}
              className="panel group cursor-pointer p-3.5 transition hover:border-brand/40"
              onClick={() => navigate(`/projects/${project.id}/data`)}
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate text-[13.5px] font-semibold">{project.name}</div>
                  <div className="mt-0.5 line-clamp-2 h-8 text-[12px] leading-4 text-mute">
                    {project.description || project.requirement || "暂无描述"}
                  </div>
                </div>
                <div className="flex shrink-0 items-start gap-1">
                  <button
                    className="btn-subtle px-1.5 py-1"
                    title="编辑名称和描述"
                    onClick={(event) => {
                      event.stopPropagation();
                      openEdit(project);
                    }}
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <div className="flex gap-1 opacity-0 transition group-hover:opacity-100">
                    <button
                      className="btn-subtle px-1.5 py-1"
                      title="复制"
                      onClick={(event) => {
                        event.stopPropagation();
                        void duplicate(project);
                      }}
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                    <button
                      className="btn-subtle px-1.5 py-1 hover:text-ng"
                      title="删除"
                      onClick={(event) => {
                        event.stopPropagation();
                        setRemoveTarget(project);
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <Badge>{project.taskType}</Badge>
                {project.publishedVersionId ? <Badge tone="ok">已发布</Badge> : null}
                <span className="mono text-[11px] text-mute">
                  {project.imageCount} 图 · {project.nodeCount} 节点 · {project.annotationCount} 标注
                </span>
              </div>
              <div className="mt-2 text-[11px] text-mute/70">更新于 {formatTime(project.updatedAt)}</div>
            </div>
          ))}
        </div>
      )}

      <Modal
        open={createOpen}
        title="新建项目"
        onClose={() => setCreateOpen(false)}
        footer={
          <>
            <button className="btn-ghost" onClick={() => setCreateOpen(false)}>
              取消
            </button>
            <button className="btn-primary" disabled={pending} onClick={create}>
              {pending ? <Spinner /> : null} 创建
            </button>
          </>
        }
      >
        <div className="space-y-3">
          <div>
            <label className="label-text">项目名称</label>
            <input
              className="field mt-1"
              value={form.name}
              placeholder="例如：iPSC 克隆识别"
              onChange={(event) => setForm({ ...form, name: event.target.value })}
            />
          </div>
          <div>
            <label className="label-text">检测需求（AI 助手会据此推荐流程）</label>
            <textarea
              className="field mt-1 h-20 resize-none"
              value={form.requirement}
              placeholder="例如：显微图像里找出纹理致密的克隆区域，统计面积占比，占比低于 10% 报警"
              onChange={(event) => setForm({ ...form, requirement: event.target.value })}
            />
          </div>
          <div>
            <label className="label-text">起始模板</label>
            <select
              className="field mt-1"
              value={form.templateId}
              onChange={(event) => setForm({ ...form, templateId: event.target.value })}
            >
              {templates.map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}（{template.nodeCount} 节点）
                </option>
              ))}
            </select>
            <div className="mt-1 text-[11px] text-mute">
              {templates.find((item) => item.id === form.templateId)?.description}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label-text">标注类别</label>
              <input
                className="field mt-1"
                value={form.labels}
                onChange={(event) => setForm({ ...form, labels: event.target.value })}
              />
            </div>
            <div>
              <label className="label-text">备注</label>
              <input
                className="field mt-1"
                value={form.description}
                onChange={(event) => setForm({ ...form, description: event.target.value })}
              />
            </div>
          </div>
        </div>
      </Modal>

      <Modal
        open={Boolean(editTarget)}
        title="编辑项目"
        onClose={() => setEditTarget(null)}
        footer={
          <>
            <button className="btn-ghost" onClick={() => setEditTarget(null)}>
              取消
            </button>
            <button className="btn-primary" disabled={pending} onClick={() => void saveEdit()}>
              {pending ? <Spinner /> : null} 保存
            </button>
          </>
        }
      >
        <div className="space-y-3">
          <div>
            <label className="label-text">项目名称</label>
            <input
              className="field mt-1"
              value={editForm.name}
              onChange={(event) => setEditForm({ ...editForm, name: event.target.value })}
            />
          </div>
          <div>
            <label className="label-text">项目描述</label>
            <textarea
              className="field mt-1 h-24 resize-none"
              value={editForm.description}
              placeholder="显示在首页项目卡片上的简介"
              onChange={(event) => setEditForm({ ...editForm, description: event.target.value })}
            />
            <div className="mt-1 text-[11px] text-mute">首页卡片会显示这段文字；留空则改用检测需求。</div>
          </div>
        </div>
      </Modal>

      <Confirm
        open={Boolean(removeTarget)}
        title="删除项目"
        message={`将删除「${removeTarget?.name}」及其所有图片、标注和运行记录，且不可恢复。`}
        confirmText="删除"
        onCancel={() => setRemoveTarget(null)}
        onConfirm={remove}
      />
    </div>
  );
}

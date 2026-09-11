import type {
  Annotation,
  BatchResultRow,
  BatchRunSummary,
  CopilotPlanResponse,
  DatasetStats,
  DebugSuggestion,
  DeviceStatus,
  Diagnosis,
  GraphIssue,
  ImageAsset,
  InferenceRecord,
  ModelAsset,
  ModelTrainer,
  MonitoringOverview,
  NodeCategory,
  NodeExplanation,
  PipelineGraph,
  PipelineTemplate,
  PlatformMeta,
  ProjectDetail,
  ProjectSummary,
  RunResult,
  RuntimeRecord,
  RuntimeStatus,
  SamPredictResult,
  UserParamSpec,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status: number, detail?: unknown) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: init?.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  let payload: any = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      const snippet = text.replace(/\s+/g, " ").trim().slice(0, 180);
      throw new ApiError(
        snippet || `请求失败 (${response.status})`,
        response.status,
        snippet,
      );
    }
  }
  if (!response.ok) {
    const message =
      payload?.error ??
      (Array.isArray(payload?.detail) ? payload.detail[0]?.msg : payload?.detail) ??
      `请求失败 (${response.status})`;
    throw new ApiError(String(message), response.status, payload?.detail);
  }
  return payload as T;
}

const get = <T>(path: string) => request<T>(path);
const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const put = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) });
const patch = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const del = <T>(path: string) => request<T>(path, { method: "DELETE" });

function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  meta: () => get<PlatformMeta>("/meta"),
  nodes: () => get<{ catalog: NodeCategory[] }>("/nodes"),
  templates: () => get<{ templates: PipelineTemplate[] }>("/templates"),
  explainNode: (nodeType: string, params?: Record<string, unknown>) =>
    post<NodeExplanation>("/nodes/explain", { nodeType, params }),

  // -- projects
  listProjects: (search?: string) =>
    get<{ projects: ProjectSummary[] }>(`/projects${query({ search })}`),
  createProject: (body: {
    name: string;
    description?: string;
    templateId?: string;
    requirement?: string;
    labels?: string[];
  }) => post<ProjectDetail>("/projects", body),
  getProject: (id: string) => get<ProjectDetail>(`/projects/${id}`),
  updateProject: (
    id: string,
    body: Partial<{
      name: string;
      description: string;
      taskType: string;
      requirement: string;
      graph: PipelineGraph;
      userParams: Record<string, unknown>;
      meta: Record<string, unknown>;
    }>,
  ) => patch<ProjectDetail>(`/projects/${id}`, body),
  duplicateProject: (id: string, name?: string) =>
    post<ProjectDetail>(`/projects/${id}/duplicate${query({ name })}`),
  deleteProject: (id: string) => del<void>(`/projects/${id}`),

  // -- pipeline
  getPipeline: (id: string) =>
    get<{ graph: PipelineGraph; issues: GraphIssue[]; userParams: Record<string, UserParamSpec> }>(
      `/projects/${id}/pipeline`,
    ),
  savePipeline: (id: string, graph: PipelineGraph) =>
    put<{ graph: PipelineGraph; issues: GraphIssue[] }>(`/projects/${id}/pipeline`, { graph }),
  validatePipeline: (id: string, graph: PipelineGraph) =>
    post<{ issues: GraphIssue[]; order: string[] }>(`/projects/${id}/pipeline/validate`, { graph }),
  runPipeline: (
    id: string,
    body: {
      graph?: PipelineGraph;
      imageId?: string | null;
      targetNode?: string | null;
      previewNodes?: string[];
      saveGraph?: boolean;
    },
  ) => post<RunResult>(`/projects/${id}/pipeline/run`, body),
  clearPipelineCache: (id: string) => post<{ cleared: number }>(`/projects/${id}/pipeline/cache/clear`),

  // -- versions
  listVersions: (id: string) =>
    get<{
      versions: { id: string; version: number; note: string; published: boolean; createdAt: string; nodeCount: number }[];
      publishedVersionId: string | null;
    }>(`/projects/${id}/versions`),
  createVersion: (id: string, note: string, publish = false) =>
    post<{ id: string; version: number; published: boolean }>(`/projects/${id}/versions`, {
      note,
      publish,
    }),
  restoreVersion: (id: string, versionId: string) =>
    post<ProjectDetail>(`/projects/${id}/versions/${versionId}/restore`),
  publishProject: (id: string, note = "") =>
    post<{ id: string; version: number; userParams: Record<string, UserParamSpec> }>(
      `/projects/${id}/publish`,
      { note },
    ),

  // -- dataset
  listImages: (
    id: string,
    params: {
      page?: number;
      pageSize?: number;
      split?: string;
      label?: string;
      annotated?: boolean;
      search?: string;
      source?: string;
    } = {},
  ) =>
    get<{ images: ImageAsset[]; total: number; page: number; pageSize: number }>(
      `/projects/${id}/images${query(params)}`,
    ),
  uploadImages: (id: string, files: File[], split = "unassigned") => {
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    return request<{ imported: number; images: ImageAsset[]; failed: { filename: string; error: string }[] }>(
      `/projects/${id}/images${query({ split })}`,
      { method: "POST", body: form },
    );
  },
  importFolder: (id: string, path: string, recursive = false, limit = 500) =>
    post<{ imported: number; images: ImageAsset[] }>(`/projects/${id}/images/import-folder`, {
      path,
      recursive,
      limit,
    }),
  deleteImages: (id: string, imageIds: string[]) =>
    post<{ deleted: number }>(`/projects/${id}/images/delete`, { imageIds }),
  setSplit: (id: string, imageIds: string[], split: string) =>
    post<{ updated: number }>(`/projects/${id}/images/split`, { imageIds, split }),
  autoSplit: (id: string, train = 0.7, val = 0.2, seed = 42) =>
    post<{ split: Record<string, number> }>(`/projects/${id}/images/auto-split`, { train, val, seed }),
  datasetStats: (id: string) => get<DatasetStats>(`/projects/${id}/dataset/stats`),
  imageHistogram: (imageId: string) =>
    get<{
      bins: number;
      channels: Record<string, number[]>;
      stats: Record<string, number>;
    }>(`/images/${imageId}/histogram`),
  imageDiagnose: (imageId: string) => get<Diagnosis>(`/images/${imageId}/diagnose`),

  // -- annotation
  listLabels: (id: string) =>
    get<{ labels: { id: string; name: string; color: string; order: number }[] }>(
      `/projects/${id}/labels`,
    ),
  createLabel: (id: string, name: string, color?: string) =>
    post<{ id: string; name: string; color: string }>(`/projects/${id}/labels`, { name, color }),
  deleteLabel: (id: string, labelId: string) => del<void>(`/projects/${id}/labels/${labelId}`),
  saveAnnotation: (
    id: string,
    body: {
      imageId: string;
      label?: string | null;
      shapes?: Annotation["shapes"];
      reviewed?: boolean;
      note?: string;
    },
  ) => put<{ annotation: Annotation }>(`/projects/${id}/annotations`, body),
  bulkLabel: (id: string, imageIds: string[], label: string) =>
    post<{ updated: number }>(`/projects/${id}/annotations/bulk-label`, { imageIds, label }),
  exportAnnotations: (id: string, fmt: string) =>
    get<{ format: string; path: string; labels: string[]; data: unknown }>(
      `/projects/${id}/annotations/export/${fmt}`,
    ),
  importAnnotations: (id: string, format: string, data: unknown) =>
    post<{ imported: number; skipped: number }>(`/projects/${id}/annotations/import`, {
      format,
      data,
    }),
  samStatus: (id: string) =>
    get<{ available: boolean; hint: string; weights?: string }>(`/projects/${id}/sam/status`),
  samPredict: (
    id: string,
    body: { imageId: string; points?: number[][]; labels?: number[]; box?: number[] | null },
  ) => post<SamPredictResult>(`/projects/${id}/sam/predict`, body),

  // -- copilot
  diagnose: (id: string, imageId?: string | null) =>
    get<Diagnosis>(`/projects/${id}/copilot/diagnose${query({ imageId })}`),
  plan: (id: string, text: string, imageId?: string | null, useLlm = true) =>
    post<CopilotPlanResponse>(`/projects/${id}/copilot/plan`, { text, imageId, useLlm }),
  applyPlan: (id: string, graph: PipelineGraph, taskType?: string) =>
    post<{ graph: PipelineGraph; warnings: string[] }>(`/projects/${id}/copilot/apply`, {
      graph,
      taskType,
    }),
  ask: (id: string, question: string, nodeType?: string, params?: Record<string, unknown>) =>
    post<{ answer: string; nodeExplanation: NodeExplanation | null }>(
      `/projects/${id}/copilot/ask`,
      { question, nodeType, params },
    ),
  copilotHistory: (id: string) =>
    get<{ messages: { id: string; role: string; content: string; payload: Record<string, unknown>; createdAt: string }[] }>(
      `/projects/${id}/copilot/history`,
    ),
  clearCopilotHistory: (id: string) => del<{ removed: number }>(`/projects/${id}/copilot/history`),

  // -- batch
  startBatch: (
    id: string,
    body: { split?: string; limit?: number; ngLabels?: string[]; fullResolution?: boolean } = {},
  ) => post<BatchRunSummary>(`/projects/${id}/batch`, body),
  listBatches: (id: string) => get<{ runs: BatchRunSummary[] }>(`/projects/${id}/batch`),
  getBatch: (runId: string) => get<BatchRunSummary>(`/batch/${runId}`),
  batchResults: (runId: string, params: { verdict?: string; outcome?: string; pageSize?: number } = {}) =>
    get<{ results: BatchResultRow[]; total: number }>(`/batch/${runId}/results${query(params)}`),
  cancelBatch: (runId: string) => post<{ cancelled: boolean }>(`/batch/${runId}/cancel`),
  batchAdvice: (runId: string) =>
    get<{ suggestions: DebugSuggestion[]; counts: Record<string, number> }>(`/batch/${runId}/advice`),
  reflowBatch: (runId: string, split = "train", resultIds?: string[]) =>
    post<{ moved: number; split: string }>(`/batch/${runId}/reflow`, { split, resultIds }),
  batchCsvUrl: (runId: string) => `${BASE}/batch/${runId}/export.csv`,

  // -- runtime
  runtimeStatus: (id: string) => get<RuntimeStatus>(`/projects/${id}/runtime`),
  runtimeStart: (id: string, body: { source?: string; intervalMs?: number; deviceId?: string }) =>
    post<RuntimeStatus>(`/projects/${id}/runtime/start`, body),
  runtimeStop: (id: string) => post<RuntimeStatus>(`/projects/${id}/runtime/stop`),
  runtimeTrigger: (id: string, deviceId?: string) =>
    post<{ record: RuntimeRecord; status: RuntimeStatus }>(
      `/projects/${id}/runtime/trigger${query({ deviceId })}`,
    ),
  runtimeParams: (id: string, values: Record<string, unknown>) =>
    post<{ userParams: Record<string, UserParamSpec> }>(`/projects/${id}/runtime/params`, { values }),
  runtimeResetParams: (id: string) =>
    post<{ userParams: Record<string, UserParamSpec> }>(`/projects/${id}/runtime/params/reset`),
  runtimeReset: (id: string) => post<RuntimeStatus>(`/projects/${id}/runtime/reset`),

  // -- models
  listModels: (projectId?: string) =>
    get<{ models: ModelAsset[] }>(`/models${query({ projectId })}`),
  listTrainers: () => get<{ trainers: ModelTrainer[] }>("/models/trainers"),
  trainingSamples: (id: string, splits?: string) =>
    get<{
      sampleCount: number;
      classes: string[];
      distribution: Record<string, number>;
      stats: Record<string, unknown>;
      trainable: boolean;
    }>(`/projects/${id}/models/samples${query({ splits })}`),
  trainModel: (
    id: string,
    body: {
      name?: string;
      splits?: string[];
      kernel?: string;
      c?: number;
      arch?: string;
      epochs?: number;
      imgsz?: number;
      batch?: number;
      yoloBase?: string;
    },
  ) => post<ModelAsset>(`/projects/${id}/models/train`, body),
  deleteModel: (modelId: string) => del<void>(`/models/${modelId}`),
  importModel: (file: File, opts?: { name?: string; task?: string; projectId?: string }) => {
    const body = new FormData();
    body.append("file", file);
    if (opts?.name) body.append("name", opts.name);
    body.append("task", opts?.task ?? "classification");
    if (opts?.projectId) body.append("projectId", opts.projectId);
    return request<ModelAsset>("/models/import", { method: "POST", body });
  },

  // -- monitoring
  monitoringOverview: (hours = 24) =>
    get<MonitoringOverview>(`/monitoring/overview${query({ hours })}`),
  monitoringRecords: (
    params: {
      hours?: number;
      projectId?: string;
      deviceId?: string;
      modelId?: string;
      verdict?: string;
      lowConfidence?: boolean;
      page?: number;
      pageSize?: number;
    } = {},
  ) =>
    get<{ records: InferenceRecord[]; total: number; page: number; pageSize: number }>(
      `/monitoring/records${query(params)}`,
    ),

  // -- devices
  listDevices: () =>
    get<{ devices: DeviceStatus[]; implementedCount: number; note: string }>("/devices"),
  connectDevice: (deviceId: string, settings: Record<string, unknown> = {}) =>
    post<DeviceStatus>(`/devices/${deviceId}/connect`, { settings }),
  disconnectDevice: (deviceId: string) => post<DeviceStatus>(`/devices/${deviceId}/disconnect`),
  configureDevice: (deviceId: string, settings: Record<string, unknown>) =>
    post<DeviceStatus>(`/devices/${deviceId}/configure`, { settings }),
  grabDevice: (deviceId: string, projectId?: string, split = "unassigned") =>
    post<{
      deviceId: string;
      width: number;
      height: number;
      image?: { id: string; filename: string; previewUrl: string };
    }>(`/devices/${deviceId}/grab`, { projectId, saveToDataset: Boolean(projectId), split }),
};

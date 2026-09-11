export type ParamLevel = "engineer" | "business" | "locked";
export type PortType =
  | "image"
  | "mask"
  | "roi"
  | "regions"
  | "value"
  | "result"
  | "any";

export interface PortSpec {
  name: string;
  type: PortType;
  label: string;
  required: boolean;
  description: string;
}

export interface ParamSpec {
  name: string;
  type: "int" | "float" | "bool" | "str" | "enum" | "text" | "rect" | "color" | "label";
  default: unknown;
  label: string;
  min: number | null;
  max: number | null;
  step: number | null;
  options: (string | number)[];
  level: ParamLevel;
  unit: string;
  description: string;
  dependsOn: { param: string; values: unknown[] } | null;
}

export interface NodeSpec {
  type: string;
  label: string;
  category: string;
  description: string;
  tags: string[];
  inputs: PortSpec[];
  outputs: PortSpec[];
  params: ParamSpec[];
}

export interface NodeCategory {
  category: string;
  nodes: NodeSpec[];
}

export interface GraphNode {
  id: string;
  type: string;
  label: string;
  params: Record<string, unknown>;
  position: { x: number; y: number };
  enabled: boolean;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle: string;
  targetHandle: string;
}

export interface PipelineGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphIssue {
  level: "error" | "warning" | "info";
  message: string;
  nodeId?: string;
  edgeId?: string;
}

export interface ProjectSummary {
  id: string;
  name: string;
  description: string;
  taskType: string;
  requirement: string;
  nodeCount: number;
  imageCount: number;
  annotationCount: number;
  publishedVersionId: string | null;
  createdAt: string;
  updatedAt: string;
  meta: Record<string, unknown>;
}

export interface UserParamSpec {
  nodeId: string;
  nodeType: string;
  nodeLabel: string;
  param: string;
  label: string;
  type: ParamSpec["type"];
  unit: string;
  options: (string | number)[];
  min: number | null;
  max: number | null;
  step: number | null;
  description: string;
  default: unknown;
  value: unknown;
}

export interface ProjectDetail extends ProjectSummary {
  graph: PipelineGraph;
  userParams: Record<string, UserParamSpec>;
  labels: { id: string; name: string; color: string; order: number }[];
  versions: {
    id: string;
    version: number;
    note: string;
    published: boolean;
    createdAt: string;
  }[];
  batchRunCount: number;
  issues: GraphIssue[];
}

export interface AnnotationShape {
  id: string;
  type: "bbox" | "polygon" | "point";
  label: string;
  points: [number, number][];
}

export interface Annotation {
  imageId: string;
  label: string | null;
  shapes: AnnotationShape[];
  reviewed: boolean;
  note: string;
  updatedAt: string;
}

export interface SamPredictResult {
  polygon: [number, number][];
  box: [number, number, number, number] | null;
  area: number;
  markedPng: string;
  overlayPng: string;
  maskPng: string;
  width: number;
  height: number;
}

export interface ImageAsset {
  id: string;
  projectId: string;
  filename: string;
  width: number;
  height: number;
  channels: number;
  sizeBytes: number;
  format: string;
  split: string;
  source: string;
  meta: Record<string, unknown>;
  createdAt: string;
  thumbUrl: string;
  previewUrl: string;
  rawUrl: string;
  annotation: Annotation | null;
}

export interface PreviewRef {
  url: string;
  width: number;
  height: number;
}

export interface NodeRunInfo {
  nodeId: string;
  nodeType: string;
  status: "pending" | "success" | "error" | "skipped";
  durationMs: number;
  cached: boolean;
  error: string | null;
  params: Record<string, unknown>;
  inputs: Record<string, Record<string, unknown>>;
  outputs: Record<
    string,
    {
      type: PortType;
      summary: Record<string, unknown>;
      preview?: PreviewRef;
      previewKind?: string;
    }
  >;
  logs: string[];
}

export interface RunResult {
  order: string[];
  totalMs: number;
  verdict: string;
  reason: string;
  measurements: Record<string, unknown>;
  artifacts: Record<string, string>;
  errors: { nodeId?: string; nodeType?: string; message: string }[];
  cache: { hits: number; misses: number };
  nodes: Record<string, NodeRunInfo>;
  issues?: GraphIssue[];
  imageId?: string | null;
  targetNode?: string | null;
}

export interface DiagnosisFinding {
  key: string;
  level: "ok" | "info" | "warning" | "critical";
  title: string;
  detail: string;
  advice: string;
  value: number | null;
}

export interface Diagnosis {
  level: string;
  metrics: Record<string, number>;
  findings: DiagnosisFinding[];
  sampleCount?: number;
  images?: string[];
}

export interface CopilotPlan {
  graph: PipelineGraph;
  taskType: string;
  route: "traditional" | "ai" | "hybrid";
  routeReason: string;
  summary: string;
  steps: { nodeId: string; reason: string }[];
  warnings: string[];
  source: "rules" | "llm";
}

export interface CopilotPlanResponse {
  intent: {
    text: string;
    taskType: string;
    taskLabel: string;
    confidence: number;
    keywords: string[];
    targetPolarity: string;
    backgroundPolarity: string;
    targetHint: string;
    constraints: Record<string, unknown>;
    colorRelevant: boolean;
  };
  diagnosis: Diagnosis;
  plan: CopilotPlan;
  llm: { enabled: boolean; model: string | null };
}

export interface BatchRunSummary {
  id: string;
  projectId: string;
  status: "pending" | "running" | "finished" | "failed" | "cancelled";
  split: string;
  total: number;
  done: number;
  okCount: number;
  ngCount: number;
  errorCount: number;
  durationMs: number;
  metrics: {
    counts?: Record<string, number>;
    accuracy?: number;
    precision?: number | null;
    recall?: number | null;
    f1?: number;
    missRate?: number | null;
    falseAlarmRate?: number | null;
    avgDurationMs?: number;
    maxDurationMs?: number;
    labelledCount?: number;
  };
  message: string;
  createdAt: string;
  updatedAt: string;
  yieldPercent: number;
}

export interface BatchResultRow {
  id: string;
  imageId: string;
  imageName: string;
  verdict: string;
  gtLabel: string | null;
  outcome: string | null;
  measurements: Record<string, unknown>;
  artifacts: { preview?: string };
  durationMs: number;
  error: string | null;
}

export interface RuntimeRecord {
  id: string;
  seq: number;
  imageId: string | null;
  imageName: string;
  verdict: string;
  source: string;
  deviceId: string | null;
  modelId: string | null;
  confidence: number | null;
  measurements: Record<string, unknown>;
  preview: string | null;
  durationMs: number;
  error: string | null;
  createdAt: string;
}

export interface RuntimeStatus {
  sessionId: string;
  projectId: string;
  projectName: string;
  status: "stopped" | "running" | "error";
  source: "dataset" | "camera";
  published: boolean;
  version: number | null;
  total: number;
  okCount: number;
  ngCount: number;
  errorCount: number;
  yieldPercent: number;
  avgDurationMs: number;
  alarm: string;
  userParams: Record<string, UserParamSpec>;
  records: RuntimeRecord[];
}

export interface ModelTrainer {
  id: string;
  name: string;
  family: string;
  available: boolean;
  hint: string;
}

export interface ModelAsset {
  id: string;
  projectId: string | null;
  name: string;
  task: string;
  framework: string;
  classes: string[];
  inputSize: number;
  metrics: Record<string, unknown>;
  meta: Record<string, unknown>;
  createdAt: string;
  available: boolean;
}

export interface DeviceStatus {
  id: string;
  name: string;
  kind: string;
  vendor: string;
  model: string;
  implemented: boolean;
  capabilities: string[];
  settings: Record<string, unknown>;
  note: string;
  state: string;
  lastError: string;
}

export interface DatasetStats {
  total: number;
  annotated: number;
  unannotated: number;
  shapeCount: number;
  bySplit: Record<string, number>;
  byLabel: Record<string, number>;
  diskBytes: number;
}

export interface PlatformMeta {
  appName: string;
  version: string;
  nodeCount: number;
  categories: string[];
  taskTypes: { value: string; label: string }[];
  llm: { enabled: boolean; model: string | null; fallback: string };
  limits: { maxPreviewSide: number; thumbnailSide: number };
}

export interface PipelineTemplate {
  id: string;
  name: string;
  taskType: string;
  description: string;
  nodeCount: number;
}

export interface NodeExplanation {
  nodeType: string;
  found: boolean;
  label?: string;
  category?: string;
  description?: string;
  inputs?: PortSpec[];
  outputs?: PortSpec[];
  params?: {
    name: string;
    label: string;
    level: ParamLevel;
    current: unknown;
    default: unknown;
    range: { min: number | null; max: number | null; options: unknown[] };
    description: string;
    advice: string;
  }[];
  message?: string;
}

export interface DebugSuggestion {
  level: string;
  title: string;
  detail: string;
  action: string;
}

// -- monitoring

/** Aggregates shared by every monitoring row (device / model / project). */
export interface InferenceStats {
  total: number;
  okCount: number;
  ngCount: number;
  errorCount: number;
  yieldPercent: number;
  avgDurationMs: number;
  p95DurationMs: number;
  maxDurationMs: number;
  avgConfidence: number;
  minConfidence: number | null;
  lowConfidenceCount: number;
  lastAt: string | null;
}

export interface MonitoredDevice extends DeviceStatus, InferenceStats {
  online: boolean;
}

export interface MonitoredModel extends InferenceStats {
  id: string;
  name: string;
  task: string;
  framework: string;
  classes: string[];
  projectId: string | null;
  projectName: string | null;
  cvAccuracy: number | null;
  trainedAt: string;
  confidenceBuckets: number[];
}

export interface MonitoredProject extends InferenceStats {
  projectId: string;
  projectName: string;
  taskType: string;
  status: "stopped" | "running" | "error";
  source: string;
  alarm: string;
}

export interface TimelineBucket {
  ts: string;
  total: number;
  okCount: number;
  ngCount: number;
  errorCount: number;
  avgDurationMs: number;
}

export interface MonitoringAlert {
  level: "error" | "warning" | "info";
  target: string;
  message: string;
}

export interface MonitoringOverview {
  hours: number;
  since: string;
  generatedAt: string;
  summary: InferenceStats & {
    projectCount: number;
    deviceCount: number;
    modelCount: number;
    onlineDevices: number;
    totalDevices: number;
    datasetInferences: number;
    runningSessions: number;
  };
  devices: MonitoredDevice[];
  models: MonitoredModel[];
  projects: MonitoredProject[];
  timeline: TimelineBucket[];
  alerts: MonitoringAlert[];
  retentionNote: string;
}

export interface InferenceRecord extends RuntimeRecord {
  projectId: string | null;
  projectName: string;
  modelName: string | null;
}

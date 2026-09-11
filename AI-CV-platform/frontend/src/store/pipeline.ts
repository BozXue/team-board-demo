import { create } from "zustand";
import { api } from "../api/client";
import type {
  GraphEdge,
  GraphIssue,
  GraphNode,
  NodeSpec,
  PipelineGraph,
  RunResult,
} from "../api/types";
import { useApp } from "./app";

const EMPTY: PipelineGraph = { nodes: [], edges: [] };

interface PipelineState {
  projectId: string | null;
  graph: PipelineGraph;
  issues: GraphIssue[];
  selectedId: string | null;
  imageId: string | null;
  result: RunResult | null;
  running: boolean;
  saving: boolean;
  dirty: boolean;
  autoRun: boolean;
  targetNode: string | null;

  load: (projectId: string, graph: PipelineGraph, issues?: GraphIssue[]) => void;
  reset: () => void;
  select: (id: string | null) => void;
  setImage: (id: string | null) => void;
  setAutoRun: (value: boolean) => void;
  setTargetNode: (id: string | null) => void;
  setGraph: (graph: PipelineGraph, dirty?: boolean) => void;
  addNode: (spec: NodeSpec, position: { x: number; y: number }) => string;
  removeNodes: (ids: string[]) => void;
  updateParams: (id: string, patch: Record<string, unknown>) => void;
  renameNode: (id: string, label: string) => void;
  toggleNode: (id: string) => void;
  moveNode: (id: string, position: { x: number; y: number }) => void;
  addEdge: (edge: Omit<GraphEdge, "id">) => void;
  removeEdges: (ids: string[]) => void;
  save: () => Promise<void>;
  run: (options?: { target?: string | null; imageId?: string | null }) => Promise<RunResult | null>;
}

function nextNodeId(graph: PipelineGraph, type: string): string {
  const used = new Set(graph.nodes.map((node) => node.id));
  for (let index = 1; index < 1000; index += 1) {
    const candidate = index === 1 ? type : `${type}_${index}`;
    if (!used.has(candidate)) return candidate;
  }
  return `${type}_${Date.now()}`;
}

function defaultParams(spec: NodeSpec): Record<string, unknown> {
  const params: Record<string, unknown> = {};
  spec.params.forEach((param) => {
    params[param.name] = param.default;
  });
  return params;
}

export const usePipeline = create<PipelineState>((set, get) => ({
  projectId: null,
  graph: EMPTY,
  issues: [],
  selectedId: null,
  imageId: null,
  result: null,
  running: false,
  saving: false,
  dirty: false,
  autoRun: true,
  targetNode: null,

  load: (projectId, graph, issues = []) =>
    set({
      projectId,
      graph,
      issues,
      dirty: false,
      result: null,
      selectedId: graph.nodes.length ? graph.nodes[graph.nodes.length - 1].id : null,
    }),

  reset: () =>
    set({
      projectId: null,
      graph: EMPTY,
      issues: [],
      selectedId: null,
      imageId: null,
      result: null,
      dirty: false,
      targetNode: null,
    }),

  select: (id) => set({ selectedId: id }),
  setImage: (id) => set({ imageId: id }),
  setAutoRun: (autoRun) => set({ autoRun }),
  setTargetNode: (targetNode) => set({ targetNode }),
  setGraph: (graph, dirty = true) => set({ graph, dirty }),

  addNode: (spec, position) => {
    const graph = get().graph;
    const id = nextNodeId(graph, spec.type);
    const node: GraphNode = {
      id,
      type: spec.type,
      label: spec.label,
      params: defaultParams(spec),
      position,
      enabled: true,
    };
    set({ graph: { ...graph, nodes: [...graph.nodes, node] }, dirty: true, selectedId: id });
    return id;
  },

  removeNodes: (ids) => {
    const set_ = new Set(ids);
    const graph = get().graph;
    set({
      graph: {
        nodes: graph.nodes.filter((node) => !set_.has(node.id)),
        edges: graph.edges.filter((edge) => !set_.has(edge.source) && !set_.has(edge.target)),
      },
      dirty: true,
      selectedId: get().selectedId && set_.has(get().selectedId!) ? null : get().selectedId,
    });
  },

  updateParams: (id, patch) => {
    const graph = get().graph;
    set({
      graph: {
        ...graph,
        nodes: graph.nodes.map((node) =>
          node.id === id ? { ...node, params: { ...node.params, ...patch } } : node,
        ),
      },
      dirty: true,
    });
  },

  renameNode: (id, label) => {
    const graph = get().graph;
    set({
      graph: {
        ...graph,
        nodes: graph.nodes.map((node) => (node.id === id ? { ...node, label } : node)),
      },
      dirty: true,
    });
  },

  toggleNode: (id) => {
    const graph = get().graph;
    set({
      graph: {
        ...graph,
        nodes: graph.nodes.map((node) =>
          node.id === id ? { ...node, enabled: !node.enabled } : node,
        ),
      },
      dirty: true,
    });
  },

  moveNode: (id, position) => {
    const graph = get().graph;
    set({
      graph: {
        ...graph,
        nodes: graph.nodes.map((node) => (node.id === id ? { ...node, position } : node)),
      },
      dirty: true,
    });
  },

  addEdge: (edge) => {
    const graph = get().graph;
    const id = `${edge.source}:${edge.sourceHandle}->${edge.target}:${edge.targetHandle}`;
    // one upstream per input port
    const edges = graph.edges.filter(
      (item) => !(item.target === edge.target && item.targetHandle === edge.targetHandle),
    );
    if (edges.some((item) => item.id === id)) return;
    set({ graph: { ...graph, edges: [...edges, { ...edge, id }] }, dirty: true });
  },

  removeEdges: (ids) => {
    const set_ = new Set(ids);
    const graph = get().graph;
    set({ graph: { ...graph, edges: graph.edges.filter((edge) => !set_.has(edge.id)) }, dirty: true });
  },

  save: async () => {
    const { projectId, graph } = get();
    if (!projectId) return;
    set({ saving: true });
    try {
      const response = await api.savePipeline(projectId, graph);
      set({ issues: response.issues, dirty: false });
      const app = useApp.getState();
      if (app.project?.id === projectId) {
        app.setProject({
          ...app.project,
          graph: response.graph,
          issues: response.issues,
          nodeCount: response.graph.nodes.length,
        });
      }
    } catch (error) {
      useApp.getState().reportError(error, "流程保存失败");
    } finally {
      set({ saving: false });
    }
  },

  run: async (options = {}) => {
    const { projectId, graph, imageId } = get();
    if (!projectId) return null;
    if (!graph.nodes.length) {
      useApp.getState().toast("流程为空，请先添加节点", "error");
      return null;
    }
    set({ running: true });
    try {
      const result = await api.runPipeline(projectId, {
        graph,
        imageId: options.imageId ?? imageId,
        targetNode: options.target ?? null,
        saveGraph: false,
      });
      set({ result, issues: result.issues ?? get().issues });
      return result;
    } catch (error) {
      useApp.getState().reportError(error, "流程执行失败");
      return null;
    } finally {
      set({ running: false });
    }
  },
}));

export function selectedNode(state: PipelineState): GraphNode | null {
  if (!state.selectedId) return null;
  return state.graph.nodes.find((node) => node.id === state.selectedId) ?? null;
}

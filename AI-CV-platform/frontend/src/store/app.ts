import { create } from "zustand";
import { api, ApiError } from "../api/client";
import type { NodeCategory, NodeSpec, PlatformMeta, ProjectDetail, ProjectSummary } from "../api/types";

export type UiMode = "engineer" | "business";

export interface Toast {
  id: number;
  level: "info" | "success" | "error";
  message: string;
}

interface AppState {
  meta: PlatformMeta | null;
  catalog: NodeCategory[];
  nodeSpecs: Record<string, NodeSpec>;
  projects: ProjectSummary[];
  project: ProjectDetail | null;
  mode: UiMode;
  toasts: Toast[];
  booting: boolean;

  boot: () => Promise<void>;
  refreshProjects: (search?: string) => Promise<void>;
  loadProject: (id: string) => Promise<ProjectDetail | null>;
  setProject: (project: ProjectDetail) => void;
  clearProject: () => void;
  setMode: (mode: UiMode) => void;
  toast: (message: string, level?: Toast["level"]) => void;
  dismissToast: (id: number) => void;
  reportError: (error: unknown, fallback?: string) => void;
}

export function errorMessage(error: unknown, fallback = "操作失败"): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message || fallback;
  return fallback;
}

let toastSeq = 0;

export const useApp = create<AppState>((set, get) => ({
  meta: null,
  catalog: [],
  nodeSpecs: {},
  projects: [],
  project: null,
  mode: (localStorage.getItem("aicv.mode") as UiMode) ?? "engineer",
  toasts: [],
  booting: true,

  boot: async () => {
    try {
      const [meta, nodes, projects] = await Promise.all([
        api.meta(),
        api.nodes(),
        api.listProjects(),
      ]);
      const specs: Record<string, NodeSpec> = {};
      nodes.catalog.forEach((group) =>
        group.nodes.forEach((spec) => {
          specs[spec.type] = spec;
        }),
      );
      set({
        meta,
        catalog: nodes.catalog,
        nodeSpecs: specs,
        projects: projects.projects,
        booting: false,
      });
    } catch (error) {
      set({ booting: false });
      get().reportError(error, "无法连接后端服务，请确认 API 已启动");
    }
  },

  refreshProjects: async (search) => {
    try {
      const { projects } = await api.listProjects(search);
      set({ projects });
    } catch (error) {
      get().reportError(error, "项目列表加载失败");
    }
  },

  loadProject: async (id) => {
    try {
      const project = await api.getProject(id);
      set({ project });
      return project;
    } catch (error) {
      get().reportError(error, "项目加载失败");
      return null;
    }
  },

  setProject: (project) => set({ project }),
  clearProject: () => set({ project: null }),

  setMode: (mode) => {
    localStorage.setItem("aicv.mode", mode);
    set({ mode });
  },

  toast: (message, level = "info") => {
    const id = ++toastSeq;
    set((state) => ({ toasts: [...state.toasts, { id, level, message }] }));
    window.setTimeout(() => get().dismissToast(id), level === "error" ? 6000 : 3200);
  },

  dismissToast: (id) => set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),

  reportError: (error, fallback) => get().toast(errorMessage(error, fallback), "error"),
}));

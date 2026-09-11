/**
 * Renders every route server-side and asserts each page's key content shows up.
 *
 * The stores are pre-filled with real data from a running backend, so the
 * project pages render their populated state (node canvas, dataset browser,
 * results dock) instead of just their loading skeletons. Effects don't run
 * during SSR, so anything a page fetches on mount stays empty here.
 *
 * Set DUMP=1 to also write each page's HTML to dist-ssr/ for inspection.
 *
 *   npx vite build --ssr scripts/render-check.tsx --outDir dist-ssr
 *   node dist-ssr/render-check.js [http://127.0.0.1:8000]
 */
import { writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { createElement } from "react";

const BASE = process.argv[2] ?? "http://127.0.0.1:8000";

const store = new Map<string, string>();
(globalThis as Record<string, unknown>).localStorage = {
  getItem: (key: string) => store.get(key) ?? null,
  setItem: (key: string, value: string) => void store.set(key, value),
  removeItem: (key: string) => void store.delete(key),
  clear: () => store.clear(),
  key: () => null,
  length: 0,
};

/** route -> text that must appear once the page renders with real data */
const ROUTES: [string, string][] = [
  ["/", "新建项目"],
  ["/monitor", "模型监控"],
  ["/devices", "设备与采集"],
  ["/projects/:id/data", "数据集"],
  ["/projects/:id/copilot", "成像诊断"],
  ["/projects/:id/pipeline", "算子库"],
  ["/projects/:id/batch", "开始测试"],
  ["/projects/:id/models", "训练分类模型"],
  ["/projects/:id/runtime", "加载运行状态"],
];

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) throw new Error(`${path} -> HTTP ${response.status}`);
  return (await response.json()) as T;
}

async function main() {
  // React feeds `useSyncExternalStore` the *initial* store snapshot while
  // rendering on the server, which would show every page as a skeleton. Read
  // the live snapshot instead so the seeded data below actually renders.
  const react = createRequire(import.meta.url)("react") as Record<string, unknown>;
  react.useSyncExternalStore = (_subscribe: unknown, getSnapshot: () => unknown) => getSnapshot();

  const { renderToString } = await import("react-dom/server");
  const { MemoryRouter } = await import("react-router-dom");
  const App = (await import("../src/App")).default;
  const { useApp } = await import("../src/store/app");
  const { usePipeline } = await import("../src/store/pipeline");

  const [meta, nodes, projects] = await Promise.all([
    get<Record<string, unknown>>("/api/meta"),
    get<{ catalog: { category: string; nodes: { type: string }[] }[] }>("/api/nodes"),
    get<{ projects: { id: string; imageCount: number }[] }>("/api/projects"),
  ]);
  const target = projects.projects.find((item) => item.imageCount > 0) ?? projects.projects[0];
  if (!target) throw new Error("后端没有项目，先运行 scripts/seed.sh");
  const detail = await get<Record<string, unknown>>(`/api/projects/${target.id}`);
  const result = await fetch(`${BASE}/api/projects/${target.id}/pipeline/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ saveGraph: false }),
  }).then((response) => (response.ok ? response.json() : null));

  const nodeSpecs: Record<string, unknown> = {};
  nodes.catalog.forEach((group) =>
    group.nodes.forEach((spec) => {
      nodeSpecs[spec.type] = spec;
    }),
  );

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  useApp.setState({
    meta,
    catalog: nodes.catalog,
    nodeSpecs,
    projects: projects.projects,
    project: detail,
    booting: false,
  } as never);
  usePipeline.getState().load(
    String(detail.id),
    detail.graph as never,
    (detail.issues ?? []) as never,
  );
  if (result) usePipeline.setState({ result } as never);

  let failed = 0;
  for (const [route, marker] of ROUTES) {
    const path = route.replace(":id", String(target.id));
    try {
      const html = renderToString(
        createElement(MemoryRouter, { initialEntries: [path] }, createElement(App)),
      );
      if (process.env.DUMP) writeFileSync(`dist-ssr/${route.replace(/[/:]/g, "_")}.html`, html);
      if (!html.includes(marker)) throw new Error(`页面未包含「${marker}」`);
      console.log(`ok   ${path.padEnd(42)} ${html.length} chars`);
    } catch (error) {
      failed += 1;
      console.log(`FAIL ${path}`);
      console.log(String(error instanceof Error ? error.stack : error).slice(0, 1200));
    }
  }
  if (failed) {
    console.log(`\n${failed} 个路由渲染失败`);
    process.exit(1);
  }
  console.log("\n所有路由首屏渲染通过");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});

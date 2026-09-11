/**
 * Mounts every route in jsdom against a running backend, so effects, data
 * fetching and store updates actually run. Catches what the SSR check can't:
 * render loops ("Maximum update depth exceeded"), effect crashes and failed
 * requests. Any console.error counts as a failure.
 *
 *   npx vite build --ssr scripts/client-check.tsx --outDir dist-ssr
 *   node dist-ssr/client-check.js [http://127.0.0.1:8000]
 */
import { createElement } from "react";
import { JSDOM } from "jsdom";

const BASE = process.argv[2] ?? "http://127.0.0.1:8000";

const ROUTES = [
  "/",
  "/monitor",
  "/devices",
  "/projects/:id/data",
  "/projects/:id/copilot",
  "/projects/:id/pipeline",
  "/projects/:id/batch",
  "/projects/:id/models",
  "/projects/:id/runtime",
];

const dom = new JSDOM("<!doctype html><html><body><div id=root></div></body></html>", {
  url: "http://localhost:5173/",
  pretendToBeVisual: true,
});
const win = dom.window as unknown as Record<string, unknown> & { document: Document };

// jsdom has no canvas backend and no layout, so anything the viewer/react-flow
// asks for has to be stubbed before the app mounts.
(win.HTMLCanvasElement.prototype as unknown as Record<string, unknown>).getContext = () => ({
  clearRect() {},
  fillRect() {},
  strokeRect() {},
  drawImage() {},
  beginPath() {},
  moveTo() {},
  lineTo() {},
  arc() {},
  stroke() {},
  fill() {},
  closePath() {},
  save() {},
  restore() {},
  setTransform() {},
  translate() {},
  scale() {},
  putImageData() {},
  createImageData: () => ({ data: new Uint8ClampedArray(4) }),
  getImageData: () => ({ data: new Uint8ClampedArray(4) }),
  measureText: () => ({ width: 0 }),
  setLineDash() {},
});
win.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};
win.matchMedia = () => ({
  matches: false,
  addEventListener() {},
  removeEventListener() {},
  addListener() {},
  removeListener() {},
});

for (const key of [
  "window",
  "document",
  "navigator",
  "HTMLElement",
  "SVGElement",
  "Element",
  "Node",
  "Image",
  "MouseEvent",
  "KeyboardEvent",
  "Event",
  "DOMRect",
  "getComputedStyle",
  "requestAnimationFrame",
  "cancelAnimationFrame",
  "ResizeObserver",
  "matchMedia",
  "localStorage",
  "devicePixelRatio",
]) {
  (globalThis as Record<string, unknown>)[key] = win[key];
}

const errors: string[] = [];
const seen = new Set<string>();
const realError = console.error;
console.error = (...args: unknown[]) => {
  const text = args.map((arg) => (arg instanceof Error ? arg.message : String(arg))).join(" ");
  // React repeats the same loop warning thousands of times; one line is enough.
  const key = text.slice(0, 120);
  if (!seen.has(key)) {
    seen.add(key);
    errors.push(text.slice(0, 800));
  }
  if (process.env.VERBOSE) realError(...args);
};

// The app calls the API with root-relative paths, which Node's fetch rejects.
// Point them at the backend, the same way the Vite dev proxy does.
const nodeFetch = globalThis.fetch;
let requests = 0;
let failedRequests = 0;
globalThis.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const url = typeof input === "string" && input.startsWith("/") ? `${BASE}${input}` : input;
  requests += 1;
  return nodeFetch(url as RequestInfo, init).then((response) => {
    if (!response.ok) {
      failedRequests += 1;
      errors.push(`${response.status} ${typeof url === "string" ? url : String(url)}`);
    }
    return response;
  });
};

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}${path}`);
  if (!response.ok) throw new Error(`${path} -> HTTP ${response.status}`);
  return (await response.json()) as T;
}

/** Mounts one route; a render loop spins forever here, hence the child process. */
async function checkRoute(path: string) {
  const { createRoot } = await import("react-dom/client");
  const { act } = await import("react");
  const { MemoryRouter } = await import("react-router-dom");
  const App = (await import("../src/App")).default;

  (globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
  const host = win.document.createElement("div");
  win.document.body.appendChild(host);
  const root = createRoot(host);
  await act(async () => {
    root.render(createElement(MemoryRouter, { initialEntries: [path] }, createElement(App)));
  });
  // let fetches settle and their state updates flush
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 1500));
  });
  const text = (host.textContent ?? "").replace(/\s+/g, " ").trim();
  const chars = text.length;
  if (process.env.DUMP) console.log(text);
  await act(async () => {
    root.unmount();
  });
  if (errors.length) {
    console.log(`FAIL ${path}`);
    errors.slice(0, 6).forEach((error) => console.log(`     ${error}`));
    process.exit(1);
  }
  console.log(`ok   ${path.padEnd(42)} ${String(chars).padStart(5)} chars · ${requests} 次请求`);
  process.exit(0);
}

async function main() {
  const single = process.argv[3];
  if (single) return checkRoute(single);

  const projects = await get<{ projects: { id: string; imageCount: number }[] }>("/api/projects");
  const target = projects.projects.find((item) => item.imageCount > 0) ?? projects.projects[0];
  if (!target) throw new Error("后端没有项目，先运行 scripts/seed.sh");

  const { spawnSync } = await import("node:child_process");
  let failed = 0;
  for (const route of ROUTES) {
    const path = route.replace(":id", target.id);
    const child = spawnSync(process.execPath, [process.argv[1], BASE, path], {
      encoding: "utf8",
      timeout: 60_000,
    });
    process.stdout.write(child.stdout ?? "");
    if (child.signal || child.status !== 0) {
      failed += 1;
      if (child.signal) console.log(`FAIL ${path}\n     渲染未在 60s 内稳定（疑似无限重渲染循环）`);
      process.stdout.write(child.stderr ?? "");
    }
  }

  if (failed) {
    console.log(`\n${failed} 个路由挂载失败`);
    process.exit(1);
  }
  console.log("\n所有路由挂载与副作用执行通过");
}

main().catch((error) => {
  realError(error);
  process.exit(1);
});

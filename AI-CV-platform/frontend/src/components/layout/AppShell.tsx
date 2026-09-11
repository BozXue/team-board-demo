import { Link, Outlet, useLocation } from "react-router-dom";
import { Activity, Cpu, LayoutGrid, Sparkles } from "lucide-react";
import { useApp } from "../../store/app";
import { Badge, Spinner, Toggle } from "../ui";

export function AppShell() {
  const { meta, booting, mode, setMode } = useApp();
  const location = useLocation();
  const inProject = location.pathname.startsWith("/projects/");

  return (
    <div className="flex h-full flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-panel px-3">
        <Link to="/" className="flex items-center gap-2">
          <div className="grid h-7 w-7 place-items-center rounded-md bg-brand-dim/20 text-brand">
            <Sparkles className="h-4 w-4" />
          </div>
          <div className="leading-tight">
            <div className="text-[13px] font-semibold">{meta?.appName ?? "戴纳 AI 引导式视觉平台"}</div>
            <div className="text-[10px] text-mute">
              {meta ? `v${meta.version} · ${meta.nodeCount} 个算子` : "连接中…"}
            </div>
          </div>
        </Link>

        <nav className="ml-3 flex items-center gap-1">
          <Link
            to="/"
            className={`btn-subtle ${location.pathname === "/" ? "bg-panel-2 text-ink" : ""}`}
          >
            <LayoutGrid className="h-3.5 w-3.5" /> 项目
          </Link>
          <Link
            to="/monitor"
            className={`btn-subtle ${location.pathname === "/monitor" ? "bg-panel-2 text-ink" : ""}`}
          >
            <Activity className="h-3.5 w-3.5" /> 监控
          </Link>
          <Link
            to="/devices"
            className={`btn-subtle ${location.pathname === "/devices" ? "bg-panel-2 text-ink" : ""}`}
          >
            <Cpu className="h-3.5 w-3.5" /> 设备
          </Link>
        </nav>

        <div className="flex-1" />

        {booting ? <Spinner className="text-mute" /> : null}
        {meta ? (
          <Badge tone={meta.llm.enabled ? "brand" : "neutral"}>
            {meta.llm.enabled ? `LLM ${meta.llm.model}` : "LLM 未配置 · 规则引擎"}
          </Badge>
        ) : null}
        <div className="mx-1 h-5 w-px bg-line-solid" />
        <Toggle
          checked={mode === "engineer"}
          onChange={(value) => setMode(value ? "engineer" : "business")}
          label={mode === "engineer" ? "工程师模式" : "操作员模式"}
        />
      </header>

      <div className={`min-h-0 flex-1 ${inProject ? "" : "scroll-y"}`}>
        <Outlet />
      </div>
    </div>
  );
}

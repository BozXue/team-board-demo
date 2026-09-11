import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Search } from "lucide-react";
import type { NodeSpec } from "../../api/types";
import { useApp } from "../../store/app";

export function NodeLibrary({ onAdd }: { onAdd: (spec: NodeSpec) => void }) {
  const catalog = useApp((s) => s.catalog);
  const [search, setSearch] = useState("");
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const filtered = useMemo(() => {
    const keyword = search.trim().toLowerCase();
    if (!keyword) return catalog;
    return catalog
      .map((group) => ({
        ...group,
        nodes: group.nodes.filter((node) =>
          [node.label, node.type, node.description, ...(node.tags ?? [])]
            .join(" ")
            .toLowerCase()
            .includes(keyword),
        ),
      }))
      .filter((group) => group.nodes.length > 0);
  }, [catalog, search]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="relative px-2 py-2">
        <Search className="absolute top-4 left-4 h-3.5 w-3.5 text-mute" />
        <input
          className="field pl-7"
          placeholder="搜索算子"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>
      <div className="scroll-y flex-1 px-1.5 pb-2">
        {filtered.map((group) => {
          const isCollapsed = collapsed[group.category] && !search;
          return (
            <div key={group.category} className="mb-1">
              <button
                className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-[11.5px] font-medium text-mute hover:bg-panel-2 hover:text-ink"
                onClick={() =>
                  setCollapsed((current) => ({ ...current, [group.category]: !current[group.category] }))
                }
              >
                {isCollapsed ? (
                  <ChevronRight className="h-3.5 w-3.5" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5" />
                )}
                {group.category}
                <span className="ml-auto text-[10.5px] text-mute/70">{group.nodes.length}</span>
              </button>
              {!isCollapsed
                ? group.nodes.map((node) => (
                    <div
                      key={node.type}
                      draggable
                      onDragStart={(event) => {
                        event.dataTransfer.setData("application/aicv-node", node.type);
                        event.dataTransfer.effectAllowed = "move";
                      }}
                      onDoubleClick={() => onAdd(node)}
                      className="group cursor-grab rounded px-2 py-1 hover:bg-panel-2"
                      title={node.description}
                    >
                      <div className="flex items-center gap-1.5">
                        <span className="truncate text-[12px]">{node.label}</span>
                        <button
                          className="ml-auto hidden text-[10.5px] text-brand group-hover:block"
                          onClick={() => onAdd(node)}
                        >
                          添加
                        </button>
                      </div>
                      <div className="mono truncate text-[9.5px] text-mute/70">{node.type}</div>
                    </div>
                  ))
                : null}
            </div>
          );
        })}
        {filtered.length === 0 ? (
          <div className="px-2 py-6 text-center text-[12px] text-mute">没有匹配的算子</div>
        ) : null}
      </div>
      <div className="border-t border-line px-2 py-1.5 text-[10.5px] leading-relaxed text-mute">
        拖拽到画布或双击添加。连线时同类型端口才能相连。
      </div>
    </div>
  );
}

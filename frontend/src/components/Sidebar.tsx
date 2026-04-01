"use client";

import { useEffect, useRef } from "react";
import { imageUrl } from "@/lib/api";

export function Sidebar({ studio }: { studio: any }) {
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [studio.logs]);

  return (
    <div className="w-[300px] shrink-0 border-l flex flex-col h-screen" style={{ borderColor: "var(--border)" }}>

      {/* History */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-3 pb-1">
          <div className="label">History</div>
        </div>
        <div className="px-3 pb-3 space-y-1">
          {studio.generations.length === 0 && (
            <div style={{ fontSize: "10px", color: "var(--text-faint)" }}>no generations yet</div>
          )}
          {studio.generations.map((g: any) => (
            <div
              key={g.id}
              className="flex items-center gap-2 p-1.5 cursor-pointer transition-all group"
              style={{
                border: `1px solid ${studio.currentGen?.id === g.id ? "var(--accent)" : "var(--border)"}`,
                background: studio.currentGen?.id === g.id ? "rgba(200,164,78,0.04)" : "transparent",
              }}
              onClick={() => studio.loadGeneration(g.id)}
            >
              {g.image_path ? (
                <img
                  src={imageUrl(g.image_path.replace(".png", "_preview.png").replace("_preview_preview", "_preview"))}
                  alt=""
                  style={{ width: 36, height: 36, imageRendering: "pixelated" as any }}
                  onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                />
              ) : (
                <div style={{ width: 36, height: 36, background: "var(--surface)" }} />
              )}
              <div className="flex-1 min-w-0">
                <div className="truncate" style={{ fontSize: "10px" }}>{g.prompt}</div>
                <div style={{ fontSize: "9px", color: "var(--text-faint)" }}>
                  {g.size}x{g.size} · {g.model?.split("-").slice(-2).join("-") || "?"} · {g.iterations || 0}st
                </div>
              </div>
              <button
                className="opacity-0 group-hover:opacity-100 transition-opacity"
                style={{ fontSize: "10px", color: "var(--danger)", padding: "2px 4px", background: "none", border: "none", cursor: "pointer" }}
                onClick={(e) => { e.stopPropagation(); studio.deleteGeneration(g.id); }}
              >
                x
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Divider */}
      <div style={{ borderTop: "1px solid var(--border)" }} />

      {/* Agent Log */}
      <div className="h-[40%] flex flex-col overflow-hidden">
        <div className="p-3 pb-1 shrink-0">
          <div className="label">Agent Log</div>
        </div>
        <div className="flex-1 overflow-y-auto px-3 pb-3">
          {studio.logs.length === 0 && (
            <div style={{ fontSize: "10px", color: "var(--text-faint)" }}>waiting for generation...</div>
          )}
          {studio.logs.map((l: any, i: number) => (
            <div key={i} style={{
              fontSize: "10px",
              padding: "2px 0",
              borderBottom: "1px solid rgba(26,22,16,0.5)",
              lineHeight: 1.4,
            }}>
              <span style={{
                color: l.step?.includes("error") ? "var(--danger)" :
                       l.step?.includes("complete") ? "var(--success)" : "var(--accent)",
              }}>
                {l.step}
              </span>{" "}
              <span style={{ color: "var(--text-dim)" }}>{l.message}</span>
            </div>
          ))}
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  );
}

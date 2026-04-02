"use client";

import { useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { imageUrl } from "@/lib/api";

export function Sidebar({ studio }: { studio: any }) {
  const logEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    logEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [studio.logs]);

  return (
    <div
      className="w-[300px] shrink-0 flex flex-col h-screen"
      style={{ borderLeft: "1px solid var(--border)" }}
    >
      {/* ── History ── */}
      <div className="flex-1 overflow-hidden flex flex-col">
        <div className="px-3.5 py-3" style={{ borderBottom: "1px solid var(--border)" }}>
          <div className="label" style={{ marginBottom: 0 }}>
            History
            {studio.generations.length > 0 && (
              <span style={{ color: "var(--text-faint)", marginLeft: 6, fontWeight: 400 }}>
                {studio.generations.length}
              </span>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
          {studio.generations.length === 0 && (
            <div className="px-2 py-4 text-center" style={{ fontSize: "10px", color: "var(--text-faint)" }}>
              no generations yet
            </div>
          )}
          <AnimatePresence initial={false}>
            {studio.generations.map((g: any) => {
              const isActive = studio.currentGen?.id === g.id;
              return (
                <motion.div
                  key={g.id}
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -8 }}
                  layout
                  className="flex items-center gap-2.5 p-2 cursor-pointer transition-colors group"
                  style={{
                    border: `1px solid ${isActive ? "var(--accent)" : "var(--border)"}`,
                    background: isActive ? "rgba(200,164,78,0.04)" : "transparent",
                  }}
                  onClick={() => studio.loadGeneration(g.id)}
                >
                  {/* Thumbnail */}
                  {g.image_path ? (
                    <img
                      src={imageUrl(g.image_path.replace(".png", "_preview.png").replace("_preview_preview", "_preview"))}
                      alt=""
                      style={{
                        width: 36,
                        height: 36,
                        imageRendering: "pixelated",
                        flexShrink: 0,
                      }}
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = "none";
                      }}
                    />
                  ) : (
                    <div
                      style={{
                        width: 36,
                        height: 36,
                        background: "var(--surface)",
                        border: "1px solid var(--border)",
                        flexShrink: 0,
                      }}
                    />
                  )}

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="truncate" style={{ fontSize: "10px", lineHeight: 1.3 }}>
                      {g.prompt}
                    </div>
                    <div style={{ fontSize: "9px", color: "var(--text-faint)", marginTop: 1 }}>
                      {g.size}x{g.size}
                      {" \u00B7 "}
                      {g.model?.split("-").slice(-2).join("-") || "?"}
                      {" \u00B7 "}
                      {g.iterations || 0} steps
                    </div>
                  </div>

                  {/* Delete */}
                  <button
                    className="opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
                    style={{
                      fontSize: "10px",
                      color: "var(--danger)",
                      padding: "2px 4px",
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      studio.deleteGeneration(g.id);
                    }}
                  >
                    x
                  </button>
                </motion.div>
              );
            })}
          </AnimatePresence>
        </div>
      </div>

      {/* ── Agent Log ── */}
      <div className="flex flex-col" style={{ height: "40%", borderTop: "1px solid var(--border)" }}>
        <div className="px-3.5 py-2.5 shrink-0">
          <div className="label" style={{ marginBottom: 0 }}>Agent Log</div>
        </div>

        <div className="flex-1 overflow-y-auto px-3 pb-3">
          {studio.logs.length === 0 && (
            <div style={{ fontSize: "10px", color: "var(--text-faint)", padding: "8px 0" }}>
              waiting for generation...
            </div>
          )}
          <AnimatePresence initial={false}>
            {studio.logs.map((l: any, i: number) => (
              <motion.div
                key={i}
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.15 }}
                style={{
                  fontSize: "10px",
                  padding: "3px 0",
                  borderBottom: "1px solid rgba(26,22,16,0.6)",
                  lineHeight: 1.4,
                }}
              >
                <span
                  style={{
                    color: l.step?.includes("error")
                      ? "var(--danger)"
                      : l.step?.includes("complete")
                        ? "var(--success)"
                        : "var(--accent)",
                    fontWeight: 500,
                  }}
                >
                  {l.step}
                </span>{" "}
                <span style={{ color: "var(--text-dim)" }}>{l.message}</span>
              </motion.div>
            ))}
          </AnimatePresence>
          <div ref={logEndRef} />
        </div>
      </div>
    </div>
  );
}

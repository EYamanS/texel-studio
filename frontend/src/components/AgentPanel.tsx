"use client";

import { useState } from "react";

/**
 * "Paint with an agent" panel: shows whether the live link is up, lets you follow what a coding agent paints
 * (Claude Code via the texel_paint CLI), and gives copy-paste commands for first-time setup.
 */
export function AgentPanel({ studio }: { studio: any }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const info = studio.agentInfo;
  const command = info?.cli_command ?? "python -m texel_paint";
  const folder = info?.project_dir ?? "<your texel-studio folder>";

  const copy = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(key);
      setTimeout(() => setCopied((c) => (c === key ? null : c)), 1200);
    } catch {}
  };

  const Row = ({ id, label, text }: { id: string; label: string; text: string }) => (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: "9px", color: "var(--text-faint)", marginBottom: 3 }}>{label}</div>
      <div className="flex gap-1 items-stretch">
        <code
          style={{
            flex: 1,
            fontSize: "9px",
            lineHeight: 1.4,
            padding: "4px 6px",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            color: "var(--text-dim)",
            overflowX: "auto",
            whiteSpace: "pre-wrap",
            wordBreak: "break-all",
          }}
        >
          {text}
        </code>
        <button className="btn" style={{ fontSize: "9px", padding: "2px 6px" }} onClick={() => copy(id, text)}>
          {copied === id ? "copied" : "copy"}
        </button>
      </div>
    </div>
  );

  return (
    <div style={{ borderBottom: "1px solid var(--border)" }}>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between"
        // inline padding: the global button reset in globals.css would override Tailwind padding utilities
        style={{ background: "none", border: "none", cursor: "pointer", textAlign: "left", padding: "10px 14px" }}
      >
        <span className="label" style={{ marginBottom: 0 }}>
          Paint with an agent
        </span>
        <span style={{ fontSize: "9px", color: studio.agentLive ? "var(--success)" : "var(--text-faint)" }}>
          {studio.agentLive ? "● live" : "○ offline"} {open ? "▴" : "▾"}
        </span>
      </button>

      {open && (
        <div className="px-3.5 pb-3" style={{ fontSize: "10px", color: "var(--text-dim)", lineHeight: 1.5 }}>
          <div>
            Run a coding agent such as <b>Claude Code</b> in the project folder. It paints with the{" "}
            <code>texel_paint</code> tool, no API key needed, and every design shows up here while it works.
          </div>

          <label className="flex items-center gap-2" style={{ marginTop: 8, cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={studio.followAgent}
              onChange={(e) => studio.setFollowAgent(e.target.checked)}
            />
            <span>Open designs the agent paints</span>
          </label>

          <Row id="cd" label="1. open a terminal in the project folder" text={`cd "${folder}"`} />
          <Row id="claude" label="2. start Claude Code" text="claude" />
          <Row
            id="ask"
            label="3. ask for a sprite"
            text="Paint a 32x32 iron sword with texel_paint, check it with lint, then show me the result."
          />
          <Row id="doctor" label="check your setup any time" text={`${command} doctor`} />
          {info?.cli_version && (
            <div style={{ fontSize: "9px", color: "var(--text-faint)", marginTop: 8 }}>
              texel_paint {info.cli_version} {"·"} data: {info.data_dir}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

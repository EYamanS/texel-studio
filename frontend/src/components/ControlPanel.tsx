"use client";

import { useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { referenceUrl } from "@/lib/api";

export function ControlPanel({ studio }: { studio: any }) {
  const [addHex, setAddHex] = useState("#8B5E3C");
  const [palName, setPalName] = useState("");
  const [isGenRef, setIsGenRef] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const s = studio.settings;

  const promptRef = useRef<HTMLTextAreaElement>(null);
  const typeRef = useRef<HTMLSelectElement>(null);
  const sizeRef = useRef<HTMLSelectElement>(null);
  const modelRef = useRef<HTMLSelectElement>(null);
  const sysRef = useRef<HTMLTextAreaElement>(null);
  const refModelRef = useRef<HTMLSelectElement>(null);

  const handleGenerate = async () => {
    const prompt = promptRef.current?.value?.trim();
    if (!prompt || !studio.currentPalette) return;
    await studio.generate({
      prompt,
      size: parseInt(sizeRef.current?.value || "16"),
      model: modelRef.current?.value || s.default_model,
      spriteType: typeRef.current?.value || "block",
      systemPrompt: sysRef.current?.value,
    });
  };

  const handleGenRef = async () => {
    const prompt = promptRef.current?.value?.trim();
    if (!prompt) return;
    setIsGenRef(true);
    try {
      await studio.generateReference(
        prompt,
        refModelRef.current?.value || s.default_image_model,
        typeRef.current?.value || "block"
      );
    } catch (e: any) {
      alert(e.message);
    }
    setIsGenRef(false);
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await studio.uploadReference(file);
    } catch (err: any) {
      alert(err.message);
    }
    e.target.value = "";
  };

  const handleRevise = async () => {
    const fb = window.prompt("What should change?");
    if (!fb) return;
    try {
      await studio.reviseReference(
        promptRef.current?.value || "",
        fb,
        refModelRef.current?.value || s.default_image_model,
        typeRef.current?.value || "block"
      );
    } catch (e: any) {
      alert(e.message);
    }
  };

  return (
    <div className="w-[280px] shrink-0 flex flex-col h-screen overflow-hidden" style={{ borderRight: "1px solid var(--border)" }}>

      {/* Header */}
      <div className="px-3.5 py-3 flex items-center gap-2" style={{ borderBottom: "1px solid var(--border)" }}>
        <div style={{ width: 6, height: 6, background: "var(--accent)", transform: "rotate(45deg)" }} />
        <span style={{ fontSize: "11px", fontWeight: 600, letterSpacing: "0.05em" }}>TEXEL STUDIO</span>
      </div>

      <div className="flex-1 overflow-y-auto">

        {/* ── Palette ── */}
        <div className="panel-section">
          <div className="label">Palette</div>
          <select
            value={studio.currentPalette?.id || ""}
            onChange={(e) => studio.selectPalette(parseInt(e.target.value))}
          >
            {studio.palettes.map((p: any) => (
              <option key={p.id} value={p.id}>{p.name} ({p.colors.length})</option>
            ))}
          </select>

          {/* Swatches */}
          <div className="flex flex-wrap gap-[2px] mt-2.5">
            {studio.currentPalette?.colors.map((c: string, i: number) => (
              <motion.button
                key={i}
                whileHover={{ scale: 1.15 }}
                whileTap={{ scale: 0.95 }}
                className="relative"
                style={{
                  width: 22,
                  height: 22,
                  background: c,
                  border: "none",
                  cursor: "pointer",
                  outline: i === studio.selectedColorIdx ? "2px solid var(--accent)" : "1px solid var(--border)",
                  outlineOffset: i === studio.selectedColorIdx ? "1px" : "0",
                  zIndex: i === studio.selectedColorIdx ? 2 : 1,
                }}
                onClick={() => studio.setSelectedColorIdx(i)}
                title={`${i}: ${c}`}
              />
            ))}
          </div>

          {/* Add color */}
          <div className="flex gap-1 mt-2">
            <input
              type="color"
              value={addHex}
              onChange={(e) => setAddHex(e.target.value)}
              style={{
                width: 28,
                height: 28,
                padding: 0,
                border: "1px solid var(--border)",
                background: "transparent",
                cursor: "pointer",
                borderRadius: 0,
              }}
            />
            <input
              type="text"
              value={addHex}
              onChange={(e) => setAddHex(e.target.value)}
              maxLength={7}
              style={{ fontSize: "10px", flex: 1 }}
            />
            <button className="btn" onClick={() => studio.addColor(addHex)}>+</button>
          </div>

          {/* Save palette as */}
          <div className="flex gap-1 mt-1.5">
            <input
              type="text"
              value={palName}
              onChange={(e) => setPalName(e.target.value)}
              placeholder="save palette as..."
              style={{ fontSize: "10px" }}
            />
            <button
              className="btn"
              onClick={() => {
                if (palName.trim()) {
                  studio.savePaletteAs(palName.trim());
                  setPalName("");
                }
              }}
            >
              save
            </button>
          </div>
        </div>

        {/* ── Prompt & Settings ── */}
        <div className="panel-section">
          <div className="label">Generate</div>
          <textarea
            ref={promptRef}
            placeholder="a dirt block with embedded pebbles and thin root fragments..."
            rows={4}
          />

          <div className="grid grid-cols-2 gap-1.5 mt-2.5">
            <div>
              <div style={{ fontSize: "9px", color: "var(--text-faint)", marginBottom: 3 }}>type</div>
              <select ref={typeRef} defaultValue="block">
                {Object.entries(s.sprite_types || {}).map(([k, v]: [string, any]) => (
                  <option key={k} value={k}>{v.label}</option>
                ))}
              </select>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: "var(--text-faint)", marginBottom: 3 }}>size</div>
              <select ref={sizeRef} defaultValue="16">
                {[8, 16, 32, 64].map((n) => (
                  <option key={n} value={n}>{n}x{n}</option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ fontSize: "9px", color: "var(--text-faint)", marginBottom: 3, marginTop: 8 }}>model</div>
          <select ref={modelRef} defaultValue={s.default_model}>
            {s.models.map((m: string) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>

          <details className="mt-2.5" style={{ color: "var(--text-dim)", fontSize: "10px" }}>
            <summary className="cursor-pointer select-none" style={{ transition: "color 0.15s" }}>
              system prompt
            </summary>
            <textarea
              ref={sysRef}
              defaultValue={s.system_prompt}
              rows={3}
              className="mt-1.5"
              style={{ fontSize: "10px", minHeight: 40 }}
            />
          </details>
        </div>

        {/* ── Reference Image ── */}
        <div className="panel-section">
          <div className="label">Reference</div>
          <div style={{ fontSize: "9px", color: "var(--text-faint)", marginBottom: 3 }}>concept model</div>
          <select ref={refModelRef} defaultValue={s.default_image_model}>
            {s.image_models.map((m: string) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>

          <div className="flex gap-1 mt-2">
            <button className="btn flex-1" onClick={handleGenRef} disabled={isGenRef}>
              {isGenRef ? "generating..." : "generate"}
            </button>
            <button className="btn flex-1" onClick={() => fileRef.current?.click()}>upload</button>
            <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleUpload} />
          </div>

          {/* Reference preview */}
          <AnimatePresence>
            {studio.referenceId && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                className="mt-2 overflow-hidden"
              >
                <img
                  src={referenceUrl(studio.referenceId)}
                  alt="reference"
                  className="w-full"
                  style={{ border: "1px solid var(--border)", display: "block" }}
                />
                <div className="flex gap-1 mt-1.5">
                  <button
                    className={`btn flex-1 ${studio.refConfirmed ? "btn-primary" : ""}`}
                    onClick={studio.confirmReference}
                  >
                    {studio.refConfirmed ? "confirmed" : "confirm"}
                  </button>
                  <button className="btn flex-1" onClick={handleRevise}>revise</button>
                  <button className="btn btn-danger" onClick={studio.clearReference}>x</button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>

      {/* ── Bottom: Generate Button ── */}
      <div className="p-3" style={{ borderTop: "1px solid var(--border)" }}>
        <div className="flex gap-1">
          <button
            className="btn btn-primary flex-1"
            onClick={handleGenerate}
            disabled={studio.isGenerating}
          >
            {studio.isGenerating ? "painting..." : "generate sprite"}
          </button>
          {studio.isGenerating && (
            <motion.button
              initial={{ opacity: 0, width: 0 }}
              animate={{ opacity: 1, width: "auto" }}
              className="btn"
              onClick={studio.skipAndFinalize}
            >
              skip
            </motion.button>
          )}
        </div>

        {/* Status */}
        <AnimatePresence>
          {studio.status.message && (
            <motion.div
              initial={{ opacity: 0, y: 4 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              style={{
                fontSize: "10px",
                marginTop: 6,
                wordBreak: "break-word",
                lineHeight: 1.4,
                color:
                  studio.status.type === "generating" ? "var(--accent)" :
                  studio.status.type === "complete" ? "var(--success)" :
                  studio.status.type === "error" ? "var(--danger)" :
                  "var(--text-dim)",
              }}
            >
              {studio.status.message}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

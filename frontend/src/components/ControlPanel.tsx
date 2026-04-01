"use client";

import { useState, useRef } from "react";
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
      paletteId: studio.currentPalette.id,
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
    } catch (e: any) { alert(e.message); }
    setIsGenRef(false);
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try { await studio.uploadReference(file); } catch (err: any) { alert(err.message); }
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
    } catch (e: any) { alert(e.message); }
  };

  return (
    <div className="w-[280px] shrink-0 border-r overflow-y-auto" style={{ borderColor: "var(--border)" }}>
      <div className="p-3 space-y-4">

        {/* ── Palette ── */}
        <section>
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
          <div className="flex flex-wrap gap-px mt-2">
            {studio.currentPalette?.colors.map((c: string, i: number) => (
              <button
                key={i}
                className="w-[22px] h-[22px] relative transition-transform hover:scale-110"
                style={{
                  background: c,
                  outline: i === studio.selectedColorIdx ? "2px solid var(--accent)" : "1px solid var(--border)",
                  outlineOffset: i === studio.selectedColorIdx ? "1px" : "0",
                  zIndex: i === studio.selectedColorIdx ? 1 : 0,
                }}
                onClick={() => studio.setSelectedColorIdx(i)}
                title={`${i}: ${c}`}
              />
            ))}
          </div>

          {/* Add color */}
          <div className="flex gap-1 mt-2">
            <input type="color" value={addHex} onChange={(e) => setAddHex(e.target.value)}
              className="w-7 h-7 p-0 border cursor-pointer" style={{ borderColor: "var(--border)", background: "transparent" }} />
            <input type="text" value={addHex} onChange={(e) => setAddHex(e.target.value)} maxLength={7}
              className="flex-1" style={{ fontSize: "10px" }} />
            <button className="btn" onClick={() => studio.addColor(addHex)}>+</button>
          </div>

          {/* Save as */}
          <div className="flex gap-1 mt-1">
            <input type="text" value={palName} onChange={(e) => setPalName(e.target.value)} placeholder="Save as..." />
            <button className="btn" onClick={() => { studio.savePaletteAs(palName); setPalName(""); }}>Save</button>
          </div>
        </section>

        <hr style={{ border: "none", borderTop: "1px solid var(--border)" }} />

        {/* ── Prompt & Settings ── */}
        <section>
          <div className="label">Generate</div>
          <textarea ref={promptRef} placeholder="A dirt block with embedded pebbles and thin root fragments..." rows={4} />

          <div className="grid grid-cols-2 gap-1 mt-2">
            <div>
              <div style={{ fontSize: "9px", color: "var(--text-faint)", marginBottom: 2 }}>type</div>
              <select ref={typeRef} defaultValue="block">
                {Object.entries(s.sprite_types || {}).map(([k, v]: [string, any]) => (
                  <option key={k} value={k}>{v.label}</option>
                ))}
              </select>
            </div>
            <div>
              <div style={{ fontSize: "9px", color: "var(--text-faint)", marginBottom: 2 }}>size</div>
              <select ref={sizeRef} defaultValue="16">
                {[8, 16, 32, 64].map(n => <option key={n} value={n}>{n}x{n}</option>)}
              </select>
            </div>
          </div>

          <div style={{ fontSize: "9px", color: "var(--text-faint)", marginBottom: 2, marginTop: 6 }}>model</div>
          <select ref={modelRef} defaultValue={s.default_model}>
            {s.models.map((m: string) => <option key={m} value={m}>{m}</option>)}
          </select>

          <details className="mt-2" style={{ color: "var(--text-dim)", fontSize: "10px" }}>
            <summary className="cursor-pointer hover:text-[var(--text)]">system prompt</summary>
            <textarea ref={sysRef} defaultValue={s.system_prompt} rows={3} className="mt-1" style={{ fontSize: "10px", minHeight: 40 }} />
          </details>
        </section>

        <hr style={{ border: "none", borderTop: "1px solid var(--border)" }} />

        {/* ── Reference Image ── */}
        <section>
          <div className="label">Reference (optional)</div>
          <div style={{ fontSize: "9px", color: "var(--text-faint)", marginBottom: 2 }}>concept model</div>
          <select ref={refModelRef} defaultValue={s.default_image_model}>
            {s.image_models.map((m: string) => <option key={m} value={m}>{m}</option>)}
          </select>

          <div className="flex gap-1 mt-2">
            <button className="btn flex-1" onClick={handleGenRef} disabled={isGenRef}>
              {isGenRef ? "generating..." : "generate"}
            </button>
            <button className="btn flex-1" onClick={() => fileRef.current?.click()}>upload</button>
            <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={handleUpload} />
          </div>

          {/* Preview */}
          {studio.referenceId && (
            <div className="mt-2">
              <img src={referenceUrl(studio.referenceId)} alt="ref" className="w-full" style={{ border: "1px solid var(--border)" }} />
              <div className="flex gap-1 mt-1">
                <button
                  className={`btn flex-1 ${studio.refConfirmed ? "btn-primary" : ""}`}
                  onClick={studio.confirmReference}
                >
                  {studio.refConfirmed ? "confirmed" : "confirm"}
                </button>
                <button className="btn flex-1" onClick={handleRevise}>revise</button>
                <button className="btn btn-danger" onClick={studio.clearReference}>x</button>
              </div>
            </div>
          )}
        </section>

        <hr style={{ border: "none", borderTop: "1px solid var(--border)" }} />

        {/* ── Generate Button ── */}
        <div className="flex gap-1">
          <button className="btn btn-primary flex-1" onClick={handleGenerate} disabled={studio.isGenerating}>
            {studio.isGenerating ? "painting..." : "generate sprite"}
          </button>
          {studio.isGenerating && (
            <button className="btn" onClick={studio.skipAndFinalize}>skip</button>
          )}
        </div>

        {/* Status */}
        {studio.status.message && (
          <div style={{
            fontSize: "10px",
            color: studio.status.type === "generating" ? "var(--accent)" :
                   studio.status.type === "complete" ? "var(--success)" :
                   studio.status.type === "error" ? "var(--danger)" : "var(--text-dim)",
            wordBreak: "break-word",
          }}>
            {studio.status.message}
          </div>
        )}
      </div>
    </div>
  );
}

"use client";

import { useState, useCallback, useRef } from "react";
import { api, apiRaw } from "@/lib/api";
import type { Palette, Generation, Settings, LogEntry } from "@/lib/types";

export function useStudio() {
  // Settings
  const [settings, setSettings] = useState<Settings | null>(null);

  // Palettes
  const [palettes, setPalettes] = useState<Palette[]>([]);
  const [currentPalette, setCurrentPalette] = useState<Palette | null>(null);
  const [selectedColorIdx, setSelectedColorIdx] = useState(0);

  // Generation
  const [pixelData, setPixelData] = useState<number[][] | null>(null);
  const [spriteSize, setSpriteSize] = useState(16);
  const [isGenerating, setIsGenerating] = useState(false);
  const [logs, setLogs] = useState<{ step: string; message: string }[]>([]);
  const [status, setStatus] = useState<{ type: "idle" | "generating" | "complete" | "error"; message: string }>({ type: "idle", message: "" });
  const [activeGenId, setActiveGenId] = useState<number | null>(null);
  const [currentGen, setCurrentGen] = useState<Generation | null>(null);

  // History
  const [generations, setGenerations] = useState<Generation[]>([]);

  // Reference
  const [referenceId, setReferenceId] = useState<string | null>(null);
  const [refConfirmed, setRefConfirmed] = useState(false);

  // Abort
  const abortRef = useRef<AbortController | null>(null);

  // ── Init ──
  const loadSettings = useCallback(async () => {
    const s = await api<Settings>("/settings");
    setSettings(s);
    return s;
  }, []);

  const loadPalettes = useCallback(async () => {
    const p = await api<Palette[]>("/palettes");
    setPalettes(p);
    if (p.length > 0 && !currentPalette) {
      setCurrentPalette(p[0]);
    }
    return p;
  }, [currentPalette]);

  const loadHistory = useCallback(async () => {
    const g = await api<Generation[]>("/generations");
    setGenerations(g);
  }, []);

  // ── Palette ──
  const selectPalette = useCallback((id: number) => {
    const p = palettes.find((p) => p.id === id);
    if (p) {
      setCurrentPalette(p);
      setSelectedColorIdx(0);
    }
  }, [palettes]);

  const addColor = useCallback(async (hex: string) => {
    if (!currentPalette) return;
    const updated = [...currentPalette.colors, hex];
    await api(`/palettes/${currentPalette.id}`, { method: "PUT", body: JSON.stringify({ colors: updated }) });
    setCurrentPalette({ ...currentPalette, colors: updated });
  }, [currentPalette]);

  const savePaletteAs = useCallback(async (name: string) => {
    if (!currentPalette) return;
    const result = await api<Palette>("/palettes", { method: "POST", body: JSON.stringify({ name, colors: currentPalette.colors }) });
    await loadPalettes();
    setCurrentPalette(result);
  }, [currentPalette, loadPalettes]);

  // ── Reference ──
  const generateReference = useCallback(async (prompt: string, model: string, spriteType: string) => {
    const res = await fetch("http://localhost:8500/api/reference", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt, feedback: null, model, sprite_type: spriteType }),
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    setReferenceId(data.reference_id);
    setRefConfirmed(false);
    return data.reference_id;
  }, []);

  const reviseReference = useCallback(async (prompt: string, feedback: string, model: string, spriteType: string) => {
    const res = await api<{ reference_id: string }>("/reference", {
      method: "POST",
      body: JSON.stringify({ prompt, feedback, model, sprite_type: spriteType }),
    });
    setReferenceId(res.reference_id);
    setRefConfirmed(false);
    return res.reference_id;
  }, []);

  const uploadReference = useCallback(async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("http://localhost:8500/api/reference/upload", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
    setReferenceId(data.reference_id);
    setRefConfirmed(false);
    return data.reference_id;
  }, []);

  const confirmReference = useCallback(() => setRefConfirmed(true), []);
  const clearReference = useCallback(() => {
    setReferenceId(null);
    setRefConfirmed(false);
  }, []);

  // ── Generation (SSE) ──
  const generate = useCallback(async (opts: {
    prompt: string;
    size: number;
    model: string;
    spriteType: string;
    systemPrompt?: string;
  }) => {
    if (!currentPalette?.colors?.length) {
      setStatus({ type: "error", message: "No palette selected" });
      return;
    }

    setSpriteSize(opts.size);
    setPixelData(Array.from({ length: opts.size }, () => Array(opts.size).fill(-1)));
    setLogs([]);
    setStatus({ type: "generating", message: "Starting..." });
    setIsGenerating(true);

    abortRef.current = new AbortController();

    try {
      const res = await fetch("http://localhost:8500/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal: abortRef.current.signal,
        body: JSON.stringify({
          prompt: opts.prompt,
          colors: currentPalette?.colors || [],
          size: opts.size,
          system_prompt: opts.systemPrompt || null,
          model: opts.model,
          reference_id: refConfirmed && referenceId ? referenceId : null,
          sprite_type: opts.spriteType,
        }),
      });

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop()!;

        let eventType = "";
        let eventData = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) eventType = line.slice(7);
          else if (line.startsWith("data: ")) eventData = line.slice(6);
          else if (line === "" && eventType && eventData) {
            const data = JSON.parse(eventData);
            handleSSE(eventType, data);
            eventType = "";
            eventData = "";
          }
        }
      }
      await loadHistory();
    } catch (e: any) {
      if (e.name !== "AbortError") {
        setStatus({ type: "error", message: e.message });
      }
    }
    setIsGenerating(false);
    abortRef.current = null;
  }, [refConfirmed, referenceId, currentPalette, loadHistory]);

  const handleSSE = useCallback((event: string, data: any) => {
    switch (event) {
      case "log":
        setStatus({ type: "generating", message: data.message });
        setLogs((prev) => [...prev, { step: data.step, message: data.message }]);
        break;
      case "pixels":
        setPixelData(data.pixel_data);
        if (data.gen_id) setActiveGenId(data.gen_id);
        break;
      case "complete":
        setStatus({ type: "complete", message: "Complete! Use chat to request edits." });
        setCurrentGen({ id: data.id, image_path: data.image_path } as Generation);
        setActiveGenId(data.id);
        break;
      case "error":
        setStatus({ type: "error", message: data.message });
        setLogs((prev) => [...prev, { step: "error", message: data.message }]);
        break;
    }
  }, []);

  // ── Chat ──
  const sendChat = useCallback(async (message: string) => {
    if (!activeGenId) return;
    setStatus({ type: "generating", message: "Agent editing..." });

    try {
      const res = await fetch("http://localhost:8500/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ generation_id: activeGenId, message }),
      });

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split("\n");
        buffer = lines.pop()!;

        let eventType = "";
        let eventData = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) eventType = line.slice(7);
          else if (line.startsWith("data: ")) eventData = line.slice(6);
          else if (line === "" && eventType && eventData) {
            handleSSE(eventType, JSON.parse(eventData));
            eventType = "";
            eventData = "";
          }
        }
      }
      await loadHistory();
    } catch (e: any) {
      setStatus({ type: "error", message: e.message });
    }
  }, [activeGenId, handleSSE, loadHistory]);

  // ── Skip ──
  const skipAndFinalize = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort();
    if (!activeGenId) return;
    try {
      const res = await api<{ id: number; image_path: string }>(`/generations/${activeGenId}/finalize`, { method: "POST" });
      setStatus({ type: "complete", message: "Finalized with current state." });
      setCurrentGen({ id: res.id, image_path: res.image_path } as Generation);
      await loadHistory();
    } catch {}
    setIsGenerating(false);
  }, [activeGenId, loadHistory]);

  // ── History ──
  const loadGeneration = useCallback(async (id: number) => {
    const gen = await api<Generation>(`/generations/${id}`);
    setCurrentGen(gen);
    if (gen.pixel_data) setPixelData(gen.pixel_data);
    if (gen.size) setSpriteSize(gen.size);
    if (gen.palette) setCurrentPalette((prev) => prev ? { ...prev, colors: gen.palette! } : prev);
    if (gen.logs) setLogs(gen.logs.map((l) => ({ step: l.step, message: l.message || "" })));
    setActiveGenId(gen.id);
  }, []);

  const deleteGeneration = useCallback(async (id: number) => {
    await api(`/generations/${id}`, { method: "DELETE" });
    if (activeGenId === id) {
      setCurrentGen(null);
      setPixelData(Array.from({ length: spriteSize }, () => Array(spriteSize).fill(-1)));
      setLogs([]);
    }
    await loadHistory();
  }, [activeGenId, spriteSize, loadHistory]);

  // ── Canvas edit ──
  const setPixel = useCallback((x: number, y: number, color: number) => {
    setPixelData((prev) => {
      if (!prev) return prev;
      const next = prev.map((row) => [...row]);
      if (y >= 0 && y < next.length && x >= 0 && x < next[0].length) {
        next[y][x] = color;
      }
      return next;
    });
  }, []);

  return {
    // State
    settings, palettes, currentPalette, selectedColorIdx,
    pixelData, spriteSize, isGenerating, logs, status,
    activeGenId, currentGen, generations,
    referenceId, refConfirmed,

    // Actions
    loadSettings, loadPalettes, loadHistory,
    selectPalette, setSelectedColorIdx, addColor, savePaletteAs,
    generateReference, reviseReference, uploadReference, confirmReference, clearReference,
    generate, sendChat, skipAndFinalize,
    loadGeneration, deleteGeneration,
    setPixel, setSpriteSize, setPixelData,
  };
}

"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { api, apiRaw, liveUrl, API_BASE } from "@/lib/api";
import type { Palette, Generation, Settings, LogEntry, AgentInfo } from "@/lib/types";

const FOLLOW_KEY = "texel.followAgent";

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
  // Usable rectangle of the open design (differs from spriteSize for non-square designs such as 52x72 cards)
  const [spriteRect, setSpriteRect] = useState<{ w: number; h: number } | null>(null);
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

  // Agent bridge (designs painted from outside the UI, e.g. by Claude Code through the texel_paint CLI)
  const [agentLive, setAgentLive] = useState(false);
  const [followAgent, setFollowAgentState] = useState(true);
  const [agentInfo, setAgentInfo] = useState<AgentInfo | null>(null);
  const [agentActivity, setAgentActivity] = useState<{ id: number; at: number } | null>(null);

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
    const res = await fetch(`${API_BASE}/reference`, {
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
    const res = await fetch(`${API_BASE}/reference/upload`, { method: "POST", body: formData });
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

  const extractReferencePalette = useCallback(async () => {
    if (!referenceId) return;
    try {
      const data = await api<{ colors: string[] }>(`/reference/${referenceId}/palette`);
      if (data?.colors?.length) {
        const palName = `Ref Palette (${data.colors.length}c)`;
        const newPal = await api<Palette>("/palettes", {
          method: "POST",
          body: JSON.stringify({ name: palName, colors: data.colors }),
        });
        await loadPalettes();
        setCurrentPalette(newPal);
        setSelectedColorIdx(0);
      }
    } catch (e) {
      console.error("Failed to extract palette from reference:", e);
    }
  }, [referenceId, loadPalettes]);

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
    setSpriteRect(null);
    setPixelData(Array.from({ length: opts.size }, () => Array(opts.size).fill(-1)));
    setLogs([]);
    setStatus({ type: "generating", message: "Starting..." });
    setIsGenerating(true);

    abortRef.current = new AbortController();

    try {
      const res = await fetch(`${API_BASE}/generate`, {
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
      const res = await fetch(`${API_BASE}/chat`, {
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
    setSpriteRect(gen.size ? { w: gen.width ?? gen.size, h: gen.height ?? gen.size } : null);
    // Each design stores its own palette (the API returns it as `colors`).
    const designColors = gen.colors ?? gen.palette;
    if (designColors) setCurrentPalette((prev) => prev ? { ...prev, colors: designColors } : prev);
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

  // ── Live updates from outside the UI (SSE) ──
  // Refs keep the event handlers current without re-subscribing.
  const latest = useRef({ activeGenId, isGenerating, followAgent, loadGeneration, loadHistory });
  latest.current = { activeGenId, isGenerating, followAgent, loadGeneration, loadHistory };

  const setFollowAgent = useCallback((value: boolean) => {
    setFollowAgentState(value);
    try { window.localStorage.setItem(FOLLOW_KEY, value ? "1" : "0"); } catch {}
  }, []);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(FOLLOW_KEY);
      if (stored !== null) setFollowAgentState(stored === "1");
    } catch {}
    api<AgentInfo>("/agent").then(setAgentInfo).catch(() => {});

    const source = new EventSource(liveUrl);
    source.addEventListener("hello", () => setAgentLive(true));
    source.onerror = () => setAgentLive(false);   // EventSource reconnects by itself
    source.addEventListener("generation", (event) => {
      const info = JSON.parse((event as MessageEvent).data) as { id: number; model?: string; created: boolean };
      const { activeGenId, isGenerating, followAgent, loadGeneration, loadHistory } = latest.current;
      loadHistory();
      if (isGenerating) return;                    // the UI's own stream is already drawing
      const fromAgent = info.model === "texel-paint";
      if (fromAgent) setAgentActivity({ id: info.id, at: Date.now() });
      if (activeGenId === info.id || (fromAgent && followAgent)) loadGeneration(info.id);
    });
    source.addEventListener("deleted", () => latest.current.loadHistory());
    return () => source.close();
  }, []);

  return {
    // State
    settings, palettes, currentPalette, selectedColorIdx,
    pixelData, spriteSize, spriteW: spriteRect?.w ?? spriteSize, spriteH: spriteRect?.h ?? spriteSize,
    agentLive, followAgent, setFollowAgent, agentInfo, agentActivity,
    isGenerating, logs, status,
    activeGenId, currentGen, generations,
    referenceId, refConfirmed,

    // Actions
    loadSettings, loadPalettes, loadHistory,
    selectPalette, setSelectedColorIdx, addColor, savePaletteAs,
    generateReference, reviseReference, uploadReference, confirmReference, clearReference,
    extractReferencePalette,
    generate, sendChat, skipAndFinalize,
    loadGeneration, deleteGeneration,
    setPixel, setSpriteSize, setPixelData,
  };
}

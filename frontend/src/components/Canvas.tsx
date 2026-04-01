"use client";

import { useRef, useEffect, useState, useCallback } from "react";
import { api, tilesetUrl } from "@/lib/api";

export function Canvas({ studio }: { studio: any }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [pixelInfo, setPixelInfo] = useState("");
  const [isPainting, setIsPainting] = useState(false);
  const [chatMsg, setChatMsg] = useState("");
  const [tilesetPreview, setTilesetPreview] = useState<{ name: string; files: string[] } | null>(null);
  const [canvasDisplaySize, setCanvasDisplaySize] = useState(512);

  const { pixelData, spriteSize, currentPalette, selectedColorIdx, status } = studio;

  // Calculate canvas display size based on container
  useEffect(() => {
    const resize = () => {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const available = Math.min(rect.width - 48, rect.height - 160);
      const maxSize = Math.max(256, Math.min(available, 640));
      // Snap to pixel-perfect multiple of spriteSize
      const scale = Math.floor(maxSize / spriteSize);
      setCanvasDisplaySize(scale * spriteSize);
    };
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, [spriteSize]);

  // Render
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !pixelData || !currentPalette) return;
    const ctx = canvas.getContext("2d")!;
    ctx.imageSmoothingEnabled = false;

    const scale = Math.floor(canvasDisplaySize / spriteSize);
    canvas.width = spriteSize * scale;
    canvas.height = spriteSize * scale;

    // Checkerboard
    for (let y = 0; y < spriteSize; y++) {
      for (let x = 0; x < spriteSize; x++) {
        ctx.fillStyle = (x + y) % 2 === 0 ? "#18160f" : "#13110c";
        ctx.fillRect(x * scale, y * scale, scale, scale);
      }
    }

    // Pixels
    for (let y = 0; y < pixelData.length; y++) {
      for (let x = 0; x < (pixelData[y]?.length || 0); x++) {
        const idx = pixelData[y][x];
        if (idx >= 0 && idx < currentPalette.colors.length) {
          ctx.fillStyle = currentPalette.colors[idx];
          ctx.fillRect(x * scale, y * scale, scale, scale);
        }
      }
    }

    // Grid (only if scale > 4)
    if (scale > 4) {
      ctx.strokeStyle = "rgba(255,255,255,0.04)";
      ctx.lineWidth = 1;
      for (let i = 0; i <= spriteSize; i++) {
        ctx.beginPath(); ctx.moveTo(i * scale, 0); ctx.lineTo(i * scale, canvas.height); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(0, i * scale); ctx.lineTo(canvas.width, i * scale); ctx.stroke();
      }
    }
  }, [pixelData, spriteSize, currentPalette, canvasDisplaySize]);

  // Mouse
  const getPixel = useCallback((e: React.MouseEvent) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const scale = canvasDisplaySize / spriteSize;
    const x = Math.floor((e.clientX - rect.left) / scale);
    const y = Math.floor((e.clientY - rect.top) / scale);
    if (x < 0 || x >= spriteSize || y < 0 || y >= spriteSize) return null;
    return { x, y };
  }, [spriteSize, canvasDisplaySize]);

  const paint = (e: React.MouseEvent) => {
    const p = getPixel(e);
    if (!p || !pixelData) return;
    const color = (e.buttons === 2 || e.button === 2) ? -1 : selectedColorIdx;
    studio.setPixel(p.x, p.y, color);
  };

  const handleMouseDown = (e: React.MouseEvent) => { setIsPainting(true); paint(e); };
  const handleMouseMove = (e: React.MouseEvent) => {
    const p = getPixel(e);
    if (p && pixelData) {
      const idx = pixelData[p.y]?.[p.x] ?? -1;
      const cn = idx >= 0 && currentPalette ? currentPalette.colors[idx] : "transparent";
      setPixelInfo(`(${p.x}, ${p.y}) idx:${idx} ${cn}`);
    }
    if (isPainting) paint(e);
  };
  const handleMouseUp = () => setIsPainting(false);

  // Export
  const exportPng = (upscale: boolean) => {
    if (!pixelData || !currentPalette) return;
    const sz = upscale ? 512 : spriteSize;
    const sc = upscale ? Math.floor(512 / spriteSize) : 1;
    const c = document.createElement("canvas"); c.width = sz; c.height = sz;
    const ctx = c.getContext("2d")!; ctx.imageSmoothingEnabled = false;
    for (let y = 0; y < pixelData.length; y++)
      for (let x = 0; x < pixelData[y].length; x++) {
        const idx = pixelData[y][x];
        if (idx >= 0 && idx < currentPalette.colors.length) {
          ctx.fillStyle = currentPalette.colors[idx];
          ctx.fillRect(x * sc, y * sc, sc, sc);
        }
      }
    const a = document.createElement("a");
    a.download = `sprite_${spriteSize}x${spriteSize}${upscale ? "_512" : ""}.png`;
    a.href = c.toDataURL("image/png"); a.click();
  };

  // Tileset
  const genTileset = async () => {
    if (!studio.currentGen || !pixelData) return;
    const name = window.prompt("Block name (e.g. Dirt):");
    if (!name?.trim()) return;
    try {
      const res = await api<{ name: string; files: string[] }>("/tileset", {
        method: "POST",
        body: JSON.stringify({ generation_id: studio.currentGen.id, name: name.trim() }),
      });
      setTilesetPreview({ name: name.trim(), files: res.files });
    } catch (e: any) { alert(e.message); }
  };

  // Chat
  const handleChat = async () => {
    if (!chatMsg.trim()) return;
    const msg = chatMsg.trim();
    setChatMsg("");
    await studio.sendChat(msg);
  };

  return (
    <div ref={containerRef} className="flex-1 flex flex-col items-center justify-center overflow-hidden" style={{ minWidth: 0 }}>

      {/* Toolbar */}
      <div className="flex items-center gap-2 mb-3">
        <span style={{ fontSize: "10px", color: "var(--text-faint)" }}>{spriteSize}x{spriteSize}</span>
        <button className="btn" onClick={() => exportPng(false)}>export png</button>
        <button className="btn" onClick={() => exportPng(true)}>export 512</button>
        <button className="btn" onClick={genTileset}>tileset</button>
      </div>

      {/* Canvas */}
      <canvas
        ref={canvasRef}
        style={{
          imageRendering: "pixelated",
          width: canvasDisplaySize,
          height: canvasDisplaySize,
          border: "1px solid var(--border)",
          cursor: "crosshair",
        }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={() => setIsPainting(false)}
        onContextMenu={(e) => e.preventDefault()}
      />

      {/* Info bar */}
      <div className="flex items-center gap-4 mt-2" style={{ fontSize: "10px", color: "var(--text-faint)", height: 16 }}>
        <span>{pixelInfo}</span>
        <span>click: paint · right-click: erase</span>
      </div>

      {/* Chat (after generation) */}
      {status.type === "complete" && (
        <div className="flex gap-1 mt-3" style={{ width: Math.min(canvasDisplaySize, 480) }}>
          <input
            type="text"
            value={chatMsg}
            onChange={(e) => setChatMsg(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleChat()}
            placeholder="tell the agent what to change..."
            style={{ flex: 1 }}
          />
          <button className="btn" onClick={handleChat}>send</button>
        </div>
      )}

      {/* Tileset preview */}
      {tilesetPreview && (
        <div className="mt-3" style={{ maxWidth: canvasDisplaySize }}>
          <div className="label">tileset: {tilesetPreview.name}</div>
          <div className="flex flex-wrap gap-1">
            {tilesetPreview.files.map((f) => (
              <div key={f} className="text-center">
                <img src={tilesetUrl(tilesetPreview.name, f)} alt={f}
                  style={{ width: 48, height: 48, imageRendering: "pixelated", border: "1px solid var(--border)" }} />
                <div style={{ fontSize: "8px", color: "var(--text-faint)" }}>{f.split("_").pop()?.replace(".png", "")}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

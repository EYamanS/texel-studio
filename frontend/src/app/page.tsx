"use client";

import { useEffect } from "react";
import { useStudio } from "@/hooks/useStudio";
import { ControlPanel } from "@/components/ControlPanel";
import { Canvas } from "@/components/Canvas";
import { Sidebar } from "@/components/Sidebar";

export default function Home() {
  const studio = useStudio();

  useEffect(() => {
    studio.loadSettings();
    studio.loadPalettes();
    studio.loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!studio.settings) {
    return (
      <div className="h-screen flex items-center justify-center" style={{ color: "var(--text-dim)" }}>
        connecting to server...
      </div>
    );
  }

  return (
    <div className="h-screen flex overflow-hidden">
      <ControlPanel studio={studio} />
      <Canvas studio={studio} />
      <Sidebar studio={studio} />
    </div>
  );
}

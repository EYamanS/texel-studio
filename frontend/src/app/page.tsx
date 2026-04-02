"use client";

import { useEffect } from "react";
import { motion } from "framer-motion";
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
      <div className="h-screen flex flex-col items-center justify-center gap-3">
        <motion.div
          animate={{ rotate: 45, scale: [1, 1.2, 1] }}
          transition={{ duration: 1.5, repeat: Infinity }}
          style={{ width: 8, height: 8, background: "var(--accent)" }}
        />
        <span style={{ fontSize: "11px", color: "var(--text-faint)" }}>
          connecting to engine...
        </span>
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

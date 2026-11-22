"use client";

import { useEffect, useState } from "react";

type Theme = "light" | "dark";

export function useTheme() {
  const [theme, setTheme] = useState<Theme>("light");

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    function sync() {
      let saved: string | null = null;
      try {
        saved = localStorage.getItem("tripworld-theme");
      } catch {}
      const mode =
        saved === "light" || saved === "dark"
          ? saved
          : media.matches
            ? "dark"
            : "light";
      document.documentElement.dataset.theme = mode;
      setTheme(mode);
    }
    sync();
    media.addEventListener("change", sync);
    return () => media.removeEventListener("change", sync);
  }, []);

  function toggle() {
    const mode = theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = mode;
    try {
      localStorage.setItem("tripworld-theme", mode);
    } catch {}
    setTheme(mode);
  }

  return { theme, toggle };
}

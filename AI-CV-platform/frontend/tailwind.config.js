/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        app: "#0a0e15",
        panel: { DEFAULT: "#111823", 2: "#16202e", 3: "#1d2837" },
        line: { DEFAULT: "rgb(36 49 70 / 0.55)", solid: "#243146" },
        ink: "#e8eff9",
        mute: "#8ba0bb",
        brand: { DEFAULT: "#38bdf8", dim: "#0ea5e9" },
        ok: "#34d399",
        ng: "#fb7185",
        warn: "#fbbf24",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "JetBrains Mono", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};

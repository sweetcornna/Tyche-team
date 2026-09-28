/** Design tokens live in src/styles/tokens.css as CSS variables (light + dark). */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class"],
  theme: {
    extend: {
      colors: {
        main: token("bg-main"),
        sidebar: token("bg-sidebar"),
        elevated: token("bg-elevated"),
        subtle: token("bg-subtle"),
        bubble: token("bg-bubble"),
        composer: token("bg-composer"),
        fg: token("fg"),
        muted: token("fg-muted"),
        faint: token("fg-faint"),
        line: token("line"),
        inverse: token("bg-inverse"),
        "on-inverse": token("fg-on-inverse"),
        accent: token("accent"),
        ok: token("ok"),
        warn: token("warn"),
        bad: token("bad"),
        info: token("info"),
      },
      fontFamily: {
        sans: [
          "ui-sans-serif", "-apple-system", "BlinkMacSystemFont", "\"SF Pro Text\"", "\"Segoe UI\"",
          "\"PingFang SC\"", "\"Hiragino Sans GB\"", "\"Microsoft YaHei\"", "Helvetica", "Arial", "sans-serif",
        ],
        mono: ["ui-monospace", "\"SF Mono\"", "Menlo", "Monaco", "Consolas", "\"Liberation Mono\"", "monospace"],
      },
      fontSize: { "2xs": ["11px", "14px"] },
      borderRadius: { "4xl": "28px" },
      boxShadow: {
        composer: "0 0 0 1px rgb(var(--line) / 0.10), 0 4px 18px rgb(0 0 0 / 0.04), 0 1px 3px rgb(0 0 0 / 0.04)",
        menu: "0 0 0 1px rgb(var(--line) / 0.10), 0 8px 28px rgb(0 0 0 / 0.12), 0 2px 6px rgb(0 0 0 / 0.06)",
        card: "0 0 0 1px rgb(var(--line) / 0.10), 0 1px 2px rgb(0 0 0 / 0.04)",
      },
      keyframes: {
        shimmer: { "0%": { backgroundPosition: "200% 0" }, "100%": { backgroundPosition: "-200% 0" } },
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "pop-in": { from: { opacity: "0", transform: "scale(0.97) translateY(2px)" }, to: { opacity: "1", transform: "none" } },
        "slide-in-right": { from: { transform: "translateX(24px)", opacity: "0" }, to: { transform: "none", opacity: "1" } },
        pulse: { "0%,100%": { opacity: "1" }, "50%": { opacity: ".35" } },
        "rise-in": { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "none" } },
        "dot-bounce": { "0%,80%,100%": { opacity: ".25", transform: "translateY(0)" }, "40%": { opacity: "1", transform: "translateY(-2px)" } },
      },
      animation: {
        shimmer: "shimmer 2.2s linear infinite",
        "fade-in": "fade-in 160ms ease-out",
        "pop-in": "pop-in 140ms cubic-bezier(.2,.8,.2,1)",
        "slide-in-right": "slide-in-right 200ms cubic-bezier(.2,.8,.2,1)",
        "pulse-soft": "pulse 1.6s ease-in-out infinite",
        "rise-in": "rise-in 220ms cubic-bezier(.2,.8,.2,1)",
        "dot-bounce": "dot-bounce 1.2s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};

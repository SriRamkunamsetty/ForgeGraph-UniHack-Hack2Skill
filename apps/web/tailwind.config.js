/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        navy: {
          DEFAULT: "#0a192f",
          50: "#e8f0fa",
          100: "#c5d8f5",
          200: "#96b7ee",
          300: "#6695e7",
          400: "#3a74e0",
          500: "#1a5fd0",
          600: "#1246a5",
          700: "#0e3580",
          800: "#0a2260",
          900: "#0a192f",
        },
        cyan: {
          forge: "#00d7e8",
        },
        steel: {
          50: "#f6f9fc",
          100: "#e8eef5",
          200: "#dbe5ef",
          300: "#b0c4d9",
          400: "#7a99b9",
          500: "#4e738e",
          600: "#355669",
          700: "#1e3a4e",
          800: "#102b4e",
          900: "#0a192f",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      animation: {
        "fade-in": "fadeIn 0.3s ease-in-out",
        "slide-up": "slideUp 0.4s ease-out",
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "spin-slow": "spin 8s linear infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { transform: "translateY(10px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" },
        },
      },
    },
  },
  plugins: [],
};

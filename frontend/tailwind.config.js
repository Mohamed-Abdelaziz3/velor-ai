/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        velor: {
          deep: '#020206',
          bg: '#06060f',
          canvas: '#09091a',
          surface: '#0e0e1e',
          panel: '#0e0e1e',
          elevated: '#121228',
          border: 'rgba(130,120,220,0.14)',
          text: '#f0eeff',
          secondary: '#b0aacb',
          muted: '#6b6585',
          // Brand
          purple: '#8b5cf6',
          violet: '#c4b5fd',
          indigo: '#6366f1',
          blue: '#38bdf8',
          cyan: '#22d3ee',
          green: '#34d399',
          emerald: '#10b981',
          amber: '#f59e0b',
          orange: '#fb923c',
          red: '#f87171',
          rose: '#fb7185',
          pink: '#f472b6',
        },
      },
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'Inter', 'Segoe UI', 'Arial', 'sans-serif'],
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }],
      },
      boxShadow: {
        'velor-card': '0 1px 0 0 rgba(255,255,255,0.04) inset, 0 30px 80px rgba(0,0,0,0.4)',
        'velor-glow': '0 0 0 1px rgba(139,92,246,0.3), 0 20px 60px rgba(88,52,214,0.25)',
        'velor-glow-sm': '0 0 0 1px rgba(139,92,246,0.2), 0 8px 24px rgba(88,52,214,0.15)',
        'velor-panel': '0 1px 0 0 rgba(255,255,255,0.05) inset, 0 40px 120px rgba(0,0,0,0.5)',
        'velor-focus': '0 0 0 3px rgba(139,92,246,0.35), 0 0 0 1px rgba(139,92,246,0.6)',
      },
      animation: {
        'velor-in': 'velor-in 560ms cubic-bezier(0.16,1,0.3,1) both',
        'signal-pulse': 'signal-pulse 2.4s ease-in-out infinite',
        'float': 'float 6s ease-in-out infinite',
        'aurora': 'aurora 12s ease-in-out infinite alternate',
        'glow-pulse': 'glow-pulse 3s ease-in-out infinite',
        'spin-slow': 'spin 8s linear infinite',
        'ping-slow': 'ping-slow 3s cubic-bezier(0,0,0.2,1) infinite',
        'shimmer': 'shimmer 2.8s ease-in-out infinite',
      },
      backdropBlur: {
        '4xl': '64px',
      },
      borderRadius: {
        '4xl': '2rem',
        '5xl': '2.5rem',
      },
      backgroundImage: {
        'velor-gradient': 'linear-gradient(135deg, #c084fc 0%, #8b5cf6 45%, #6366f1 100%)',
        'velor-gradient-vivid': 'linear-gradient(135deg, #e879f9 0%, #a855f7 40%, #6366f1 80%, #3b82f6 100%)',
        'velor-mesh': 'radial-gradient(ellipse at 0% 0%, rgba(139,92,246,0.15) 0%, transparent 50%), radial-gradient(ellipse at 100% 100%, rgba(99,102,241,0.1) 0%, transparent 50%)',
      },
    },
  },
  plugins: [],
};

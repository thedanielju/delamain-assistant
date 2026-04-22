'use client'

import { cn } from '@/lib/utils'
import { THEMES } from '@/lib/sample-data'
import type { ThemeName } from '@/lib/types'

interface ThemePanelProps {
  current: ThemeName
  onChange: (theme: ThemeName) => void
}

export function ThemePanel({ current, onChange }: ThemePanelProps) {
  const themeList = Object.values(THEMES)

  return (
    <div className="flex flex-col gap-4 py-2">
      <p className="text-[10px] font-mono text-[#555555] uppercase tracking-wider">Accent palette</p>

      <div className="grid grid-cols-2 gap-2">
        {themeList.map((theme) => {
          const isActive = theme.name === current
          return (
            <button
              key={theme.name}
              onClick={() => onChange(theme.name)}
              className={cn(
                'relative flex flex-col gap-2 p-3 rounded-xl border transition-all text-left',
                isActive
                  ? 'border-white/20 bg-white/[0.04]'
                  : 'border-white/[0.06] bg-[#0d0d0d] hover:border-white/[0.12] hover:bg-white/[0.02]'
              )}
              aria-pressed={isActive}
              aria-label={`${theme.label} theme`}
            >
              {/* Color swatches */}
              <div className="flex items-center gap-1">
                <span
                  className="w-5 h-5 rounded-full border border-white/10 flex-shrink-0"
                  style={{ backgroundColor: theme.primary }}
                />
                <span
                  className="w-3.5 h-3.5 rounded-full border border-white/10 flex-shrink-0"
                  style={{ backgroundColor: theme.accentGreen }}
                />
                <span
                  className="w-3.5 h-3.5 rounded-full border border-white/10 flex-shrink-0"
                  style={{ backgroundColor: theme.accentPink }}
                />
                <span
                  className="w-3.5 h-3.5 rounded-full border border-white/10 flex-shrink-0"
                  style={{ backgroundColor: theme.accentPurple }}
                />
              </div>

              <span className="text-[11px] font-sans text-[#cccccc]">{theme.label}</span>

              {isActive && (
                <span
                  className="absolute top-2 right-2 w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: theme.primary }}
                />
              )}
            </button>
          )
        })}
      </div>

      {/* Preview strip */}
      <div className="flex flex-col gap-2 mt-1 pt-3 border-t border-white/[0.04]">
        <p className="text-[10px] font-mono text-[#555555] uppercase tracking-wider">Preview</p>
        <div className="flex items-center gap-2">
          {(['primary', 'accentGreen', 'accentPink', 'accentPurple'] as const).map((key) => (
            <div
              key={key}
              className="flex-1 h-6 rounded-md border border-white/[0.08]"
              style={{ backgroundColor: THEMES[current][key] }}
            />
          ))}
        </div>
        <div className="flex items-center gap-2 flex-wrap mt-1">
          {(['primary', 'accentGreen', 'accentPink'] as const).map((key) => (
            <span
              key={key}
              className="px-2.5 py-0.5 rounded-full border text-[10px] font-mono"
              style={{
                borderColor: THEMES[current][key],
                color: THEMES[current][key],
                backgroundColor: `${THEMES[current][key]}18`,
              }}
            >
              sample tag
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

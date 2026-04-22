interface BudgetBarProps {
  used: number
  total: number
}

export function BudgetBar({ used, total }: BudgetBarProps) {
  const pct = Math.min((used / total) * 100, 100)
  const color =
    pct > 80 ? '#f4a0b0' : pct > 60 ? '#f4d4a0' : '#7ec8a0'

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center justify-between">
        <span className="text-[10px] text-[#888888] font-mono">Copilot premium</span>
        <span className="text-[10px] font-mono" style={{ color }}>
          {used} / {total}
        </span>
      </div>
      <div className="h-1 w-full bg-[#1a1a1a] rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-300"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
    </div>
  )
}

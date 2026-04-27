interface ModelBadgeProps {
  model: string
  options?: string[]
  onChange?: (model: string) => void
}

export function ModelBadge({ model, options = [], onChange }: ModelBadgeProps) {
  if (options.length > 0 && onChange) {
    return (
      <select
        value={model}
        onChange={(event) => onChange(event.target.value)}
        className="max-w-[260px] bg-[#7ec8a0]/10 border border-[#7ec8a0]/30 text-[#7ec8a0] text-[10px] font-mono tracking-tight rounded-full px-2 py-0.5 outline-none hover:border-[#7ec8a0]/50 transition-colors"
        aria-label="Active model route"
        title="Active model route"
      >
        {options.map((option) => (
          <option key={option} value={option} className="bg-[#111111] text-[#cccccc]">
            {option}
          </option>
        ))}
      </select>
    )
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-[#7ec8a0]/10 border border-[#7ec8a0]/30 text-[#7ec8a0] text-[10px] font-mono tracking-tight whitespace-nowrap">
      {model}
    </span>
  )
}

interface ModelBadgeProps {
  model: string
}

export function ModelBadge({ model }: ModelBadgeProps) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-[#7ec8a0]/10 border border-[#7ec8a0]/30 text-[#7ec8a0] text-[10px] font-mono tracking-tight whitespace-nowrap">
      {model}
    </span>
  )
}

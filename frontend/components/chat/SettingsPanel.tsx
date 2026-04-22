'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import { BudgetBar } from './BudgetBar'
import { ThemePanel } from './ThemePanel'
import { ConfirmModal } from './ConfirmModal'
import { PanelHeader } from './ChatLayout'
import type {
  ContextMode, Tool, ContextFile, Worker, ThemeName,
} from '@/lib/types'

// ── Accordion ────────────────────────────────────────────────────────────────

function AccordionSection({
  title, children, defaultOpen = true,
}: {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border-b border-white/[0.05]">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/[0.02] transition-colors"
        aria-expanded={open}
      >
        <span className="text-[10px] font-mono font-semibold text-[#555555] uppercase tracking-wider">
          {title}
        </span>
        <span className="text-[#444444]">
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        </span>
      </button>
      {open && <div className="px-4 pb-4">{children}</div>}
    </div>
  )
}

// ── Toggle ───────────────────────────────────────────────────────────────────

function MiniToggle({ enabled, onToggle, label }: { enabled: boolean; onToggle: () => void; label: string }) {
  return (
    <button
      onClick={onToggle}
      className={cn(
        'flex-shrink-0 w-8 h-4 rounded-full relative transition-colors mt-0.5',
        enabled ? 'bg-[var(--accent-green)]/20' : 'bg-[#2a2a2a]'
      )}
      aria-pressed={enabled}
      aria-label={label}
    >
      <span
        className={cn('absolute top-0.5 w-3 h-3 rounded-full transition-all', enabled ? 'left-4' : 'left-0.5 bg-[#555555]')}
        style={enabled ? { left: '1rem', backgroundColor: 'var(--accent-green)' } : {}}
      />
    </button>
  )
}

// ── Props ─────────────────────────────────────────────────────────────────────

type SettingsTabId = 'settings' | 'theme'

interface SettingsPanelProps {
  model: string
  defaultModel: string
  budgetUsed: number
  budgetTotal: number
  contextMode: ContextMode
  contextFiles: ContextFile[]
  tools: Tool[]
  workers: Worker[]
  theme: ThemeName
  titleGeneration: boolean
  systemContext: string
  shortTermContinuity: string
  activeTab: SettingsTabId
  onClose?: () => void
  onToggleTool: (id: string) => void
  onChangeModel: (model: string) => void
  onChangeDefaultModel: (model: string) => void
  onChangeTheme: (theme: ThemeName) => void
  onToggleTitleGeneration: () => void
  onChangeSystemContext: (v: string) => void
  onChangeShortTermContinuity: (v: string) => void
  onSetTab: (tab: SettingsTabId) => void
}

const MODEL_OPTIONS = [
  'github_copilot/gpt-4.1',
  'github_copilot/gpt-4o',
  'github_copilot/claude-opus-4.5',
  'openai/gpt-5-mini',
  'anthropic/claude-opus-4.6',
]

const TABS: { id: SettingsTabId; label: string }[] = [
  { id: 'settings', label: 'Settings' },
  { id: 'theme', label: 'Theme' },
]

// ── Component ─────────────────────────────────────────────────────────────────

export function SettingsPanel({
  model, defaultModel, budgetUsed, budgetTotal, contextMode, contextFiles,
  tools, theme, titleGeneration, systemContext, shortTermContinuity,
  activeTab, onClose, onToggleTool, onChangeModel, onChangeDefaultModel,
  onChangeTheme, onToggleTitleGeneration, onChangeSystemContext,
  onChangeShortTermContinuity, onSetTab,
}: SettingsPanelProps) {
  const [confirmPending, setConfirmPending] = useState<null | {
    title: string; description: string; onConfirm: () => void
  }>(null)
  const [sysCtxDraft, setSysCtxDraft] = useState(systemContext)
  const [continuityDraft, setContinuityDraft] = useState(shortTermContinuity)

  const requireConfirm = (title: string, description: string, action: () => void) => {
    setConfirmPending({ title, description, onConfirm: action })
  }

  return (
    <>
      {confirmPending && (
        <ConfirmModal
          title={confirmPending.title}
          description={confirmPending.description}
          onConfirm={() => { confirmPending.onConfirm(); setConfirmPending(null) }}
          onCancel={() => setConfirmPending(null)}
        />
      )}

      <div className="flex flex-col h-full w-full">
        {/* Header — uses shared PanelHeader so close icon is consistent */}
        {onClose && <PanelHeader title="Settings" onClose={onClose} />}

        {/* Tabs */}
        <div className="flex border-b border-white/[0.06] flex-shrink-0">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => onSetTab(tab.id)}
              className={cn(
                'flex-1 py-2.5 text-[10px] font-mono transition-all relative',
                activeTab === tab.id ? 'text-white' : 'text-[#555555] hover:text-[#888888]'
              )}
              aria-selected={activeTab === tab.id}
            >
              {tab.label}
              {activeTab === tab.id && (
                <span className="absolute bottom-0 left-3 right-3 h-px" style={{ backgroundColor: 'var(--accent-blue)' }} />
              )}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {activeTab === 'settings' && (
            <>
              <AccordionSection title="Model">
                <div className="flex flex-col gap-3">
                  <div>
                    <p className="text-[10px] font-mono text-[#444444] uppercase tracking-wider mb-1.5">Active route</p>
                    <select
                      value={model}
                      onChange={(e) => onChangeModel(e.target.value)}
                      className="w-full bg-[#111111] border border-white/[0.08] rounded-md px-2.5 py-1.5 text-xs font-mono outline-none hover:border-white/[0.14] transition-colors"
                      style={{ color: 'var(--accent-green)' }}
                    >
                      {MODEL_OPTIONS.map((m) => (
                        <option key={m} value={m} className="bg-[#111111] text-[#cccccc]">{m}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <p className="text-[10px] font-mono text-[#444444] uppercase tracking-wider mb-1.5">Default model</p>
                    <select
                      value={defaultModel}
                      onChange={(e) => onChangeDefaultModel(e.target.value)}
                      className="w-full bg-[#111111] border border-white/[0.08] rounded-md px-2.5 py-1.5 text-xs font-mono text-[#888888] outline-none hover:border-white/[0.14] transition-colors"
                    >
                      {MODEL_OPTIONS.map((m) => (
                        <option key={m} value={m} className="bg-[#111111] text-[#cccccc]">{m}</option>
                      ))}
                    </select>
                  </div>
                  <BudgetBar used={budgetUsed} total={budgetTotal} />
                </div>
              </AccordionSection>

              <AccordionSection title="Context">
                <div className="flex flex-col gap-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-sans text-[#888888]">Mode</span>
                    <span className="text-xs font-mono" style={{ color: 'var(--accent-blue)' }}>{contextMode}</span>
                  </div>
                  {contextFiles.length > 0 && (
                    <div>
                      <p className="text-[10px] font-mono text-[#444444] uppercase tracking-wider mb-1.5">Loaded files</p>
                      <ul className="flex flex-col gap-1.5">
                        {contextFiles.map((f) => (
                          <li key={f.id} className="flex flex-col gap-0.5">
                            <span className="text-[11px] font-mono text-[#888888] truncate">{f.path}</span>
                            {(f.bytes || f.tokenEstimate) && (
                              <span className="text-[9px] font-mono text-[#3a3a3a]">
                                {f.bytes ? `${f.bytes}B` : ''}{f.bytes && f.tokenEstimate ? ' · ' : ''}{f.tokenEstimate ? `~${f.tokenEstimate} tokens` : ''}
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </AccordionSection>

              <AccordionSection title="Tools">
                <ul className="flex flex-col gap-2.5">
                  {tools.map((tool) => (
                    <li key={tool.id} className="flex items-start justify-between gap-3">
                      <div className="flex flex-col gap-0.5 min-w-0">
                        <span className="text-xs font-mono text-[#cccccc] truncate">{tool.name}</span>
                        <span className="text-[10px] font-sans text-[#555555] leading-tight">{tool.description}</span>
                      </div>
                      <MiniToggle
                        enabled={tool.enabled}
                        label={`${tool.enabled ? 'Disable' : 'Enable'} ${tool.name}`}
                        onToggle={() => {
                          if (tool.enabled) {
                            requireConfirm('Disable tool', `Disable "${tool.name}"? This creates an audit event.`, () => onToggleTool(tool.id))
                          } else {
                            onToggleTool(tool.id)
                          }
                        }}
                      />
                    </li>
                  ))}
                </ul>
              </AccordionSection>

              <AccordionSection title="Behavior" defaultOpen={false}>
                <div className="flex items-center justify-between">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-xs font-mono text-[#cccccc]">Title generation</span>
                    <span className="text-[10px] font-sans text-[#555555]">Auto-generate conversation titles</span>
                  </div>
                  <MiniToggle enabled={titleGeneration} label="Toggle title generation" onToggle={onToggleTitleGeneration} />
                </div>
              </AccordionSection>

              <AccordionSection title="System context" defaultOpen={false}>
                <div className="flex flex-col gap-2">
                  <textarea
                    value={sysCtxDraft}
                    onChange={(e) => setSysCtxDraft(e.target.value)}
                    rows={5}
                    className="w-full bg-[#0d0d0d] border border-white/[0.08] rounded-md px-2.5 py-2 text-[11px] font-mono text-[#888888] outline-none resize-none leading-relaxed hover:border-white/[0.14] focus:border-white/20 transition-colors"
                    placeholder="System context..."
                  />
                  <button
                    onClick={() => requireConfirm('Update system context', 'Saving edits to system-context.md will create an audit event.', () => onChangeSystemContext(sysCtxDraft))}
                    className="self-end text-[10px] font-mono px-2.5 py-1 rounded-md border border-white/[0.08] text-[#888888] hover:text-white hover:border-white/20 transition-all"
                  >
                    Save
                  </button>
                </div>
              </AccordionSection>

              <AccordionSection title="Continuity" defaultOpen={false}>
                <div className="flex flex-col gap-2">
                  <textarea
                    value={continuityDraft}
                    onChange={(e) => setContinuityDraft(e.target.value)}
                    rows={4}
                    className="w-full bg-[#0d0d0d] border border-white/[0.08] rounded-md px-2.5 py-2 text-[11px] font-mono text-[#888888] outline-none resize-none leading-relaxed hover:border-white/[0.14] focus:border-white/20 transition-colors"
                    placeholder="Short-term continuity notes..."
                  />
                  <button
                    onClick={() => onChangeShortTermContinuity(continuityDraft)}
                    className="self-end text-[10px] font-mono px-2.5 py-1 rounded-md border border-white/[0.08] text-[#888888] hover:text-white hover:border-white/20 transition-all"
                  >
                    Save
                  </button>
                </div>
              </AccordionSection>
            </>
          )}

          {activeTab === 'theme' && (
            <div className="px-4 py-4">
              <ThemePanel current={theme} onChange={onChangeTheme} />
            </div>
          )}
        </div>
      </div>
    </>
  )
}

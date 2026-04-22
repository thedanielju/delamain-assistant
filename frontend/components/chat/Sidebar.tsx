'use client'

import { useState } from 'react'
import { Search, Plus, X, MessageSquare } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Conversation } from '@/lib/types'

interface SidebarProps {
  conversations: Conversation[]
  activeId: string
  onSelect: (id: string) => void
  onNew: () => void
  onClose?: () => void
  className?: string
}

export function Sidebar({
  conversations,
  activeId,
  onSelect,
  onNew,
  onClose,
  className,
}: SidebarProps) {
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  const filtered = conversations.filter((c) =>
    searchQuery
      ? c.title.toLowerCase().includes(searchQuery.toLowerCase())
      : true
  )

  return (
    <aside
      className={cn(
        'flex flex-col h-full w-full bg-[#0a0a0a] border-r border-white/[0.06]',
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-3 pt-3 pb-2">
        <span className="font-sans text-xs font-semibold tracking-widest uppercase text-[#888888]">
          Delamain
        </span>
        {onClose && (
          <button
            onClick={onClose}
            className="text-[#888888] hover:text-white transition-colors p-1 rounded"
            aria-label="Close sidebar"
          >
            <X size={14} />
          </button>
        )}
      </div>

      {/* New conversation button */}
      <div className="px-3 pb-2">
        <button
          onClick={onNew}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-md border border-accent-blue/40 text-accent-blue text-xs font-sans hover:bg-accent-blue/10 transition-colors"
        >
          <Plus size={13} />
          New conversation
        </button>
      </div>

      {/* Search */}
      <div className="px-3 pb-2">
        {searchOpen ? (
          <div className="flex items-center gap-2 bg-[#111111] border border-white/[0.08] rounded-md px-2 py-1.5">
            <Search size={12} className="text-[#888888] flex-shrink-0" />
            <input
              autoFocus
              type="text"
              placeholder="Search..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="bg-transparent text-xs text-white placeholder-[#888888] outline-none flex-1 font-mono"
            />
            <button
              onClick={() => {
                setSearchOpen(false)
                setSearchQuery('')
              }}
              className="text-[#888888] hover:text-white"
            >
              <X size={11} />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setSearchOpen(true)}
            className="flex items-center gap-2 text-[#888888] hover:text-white text-xs px-1 transition-colors"
          >
            <Search size={12} />
            Search
          </button>
        )}
      </div>

      {/* Conversation list */}
      <nav className="flex-1 overflow-y-auto px-2 pb-4" aria-label="Conversation history">
        {filtered.length === 0 ? (
          <p className="text-[#888888] text-xs px-2 py-4 text-center">No conversations</p>
        ) : (
          <ul className="flex flex-col gap-0.5">
            {filtered.map((conv) => {
              const isActive = conv.id === activeId
              return (
                <li key={conv.id}>
                  <button
                    onClick={() => onSelect(conv.id)}
                    className={cn(
                      'w-full text-left px-3 py-2.5 rounded-md flex items-start gap-2.5 transition-colors group',
                      isActive
                        ? 'bg-[#111111] border-l-2 border-accent-blue pl-[10px]'
                        : 'hover:bg-[#0f0f0f] border-l-2 border-transparent pl-[10px]'
                    )}
                    aria-current={isActive ? 'page' : undefined}
                  >
                    <MessageSquare
                      size={13}
                      className={cn(
                        'mt-0.5 flex-shrink-0',
                        isActive ? 'text-accent-blue' : 'text-[#888888]'
                      )}
                    />
                    <div className="flex flex-col gap-0.5 min-w-0">
                      <span
                        className={cn(
                          'text-xs font-sans truncate leading-tight',
                          isActive ? 'text-white' : 'text-[#cccccc]'
                        )}
                      >
                        {conv.title}
                      </span>
                      <span className="text-[10px] text-[#888888] font-mono">
                        {conv.timestamp}
                      </span>
                    </div>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </nav>
    </aside>
  )
}

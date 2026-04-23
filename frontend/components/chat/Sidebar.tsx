'use client'

import { useMemo, useState } from 'react'
import {
  Search,
  Plus,
  X,
  MessageSquare,
  FolderPlus,
  Folder as FolderIcon,
  FolderOpen,
  ChevronRight,
  Trash2,
  Pencil,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Conversation, Folder } from '@/lib/types'

interface SidebarProps {
  conversations: Conversation[]
  folders: Folder[]
  activeId: string
  onSelect: (id: string) => void
  onNew: () => void
  onClose?: () => void
  onCreateFolder: (name: string, parentId: string | null) => void
  onRenameFolder: (id: string, name: string) => void
  onMoveFolder: (id: string, parentId: string | null) => void
  onDeleteFolder: (id: string) => void
  onMoveConversation: (conversationId: string, folderId: string | null) => void
  onDeleteConversation: (conversationId: string) => void
  onRenameConversation?: (conversationId: string, title: string) => void
  className?: string
}

type DragKind = 'folder' | 'conversation'
interface DragItem {
  kind: DragKind
  id: string
}

interface TreeNode {
  folder: Folder
  children: TreeNode[]
  conversations: Conversation[]
}

function buildTree(folders: Folder[], conversations: Conversation[]): {
  tree: TreeNode[]
  rootConversations: Conversation[]
} {
  const nodeById = new Map<string, TreeNode>()
  folders.forEach((f) => nodeById.set(f.id, { folder: f, children: [], conversations: [] }))

  const roots: TreeNode[] = []
  nodeById.forEach((node) => {
    const parentId = node.folder.parentId
    if (parentId && nodeById.has(parentId)) {
      nodeById.get(parentId)!.children.push(node)
    } else {
      roots.push(node)
    }
  })

  const rootConversations: Conversation[] = []
  for (const conv of conversations) {
    const fid = conv.folderId ?? null
    if (fid && nodeById.has(fid)) {
      nodeById.get(fid)!.conversations.push(conv)
    } else {
      rootConversations.push(conv)
    }
  }

  const sortNode = (node: TreeNode) => {
    node.children.sort((a, b) => a.folder.name.localeCompare(b.folder.name))
    node.children.forEach(sortNode)
  }
  roots.sort((a, b) => a.folder.name.localeCompare(b.folder.name))
  roots.forEach(sortNode)

  return { tree: roots, rootConversations }
}

function isDescendant(folders: Folder[], candidateParentId: string, folderId: string): boolean {
  // Is `candidateParentId` a descendant of `folderId`? (used to prevent cycles)
  let cursor: string | null = candidateParentId
  const byId = new Map(folders.map((f) => [f.id, f]))
  const seen = new Set<string>()
  while (cursor) {
    if (cursor === folderId) return true
    if (seen.has(cursor)) return false
    seen.add(cursor)
    cursor = byId.get(cursor)?.parentId ?? null
  }
  return false
}

export function Sidebar({
  conversations,
  folders,
  activeId,
  onSelect,
  onNew,
  onClose,
  onCreateFolder,
  onRenameFolder,
  onMoveFolder,
  onDeleteFolder,
  onMoveConversation,
  onDeleteConversation,
  onRenameConversation,
  className,
}: SidebarProps) {
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [renamingFolderId, setRenamingFolderId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [drag, setDrag] = useState<DragItem | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null) // folderId or 'root'
  const [creatingFolder, setCreatingFolder] = useState(false)
  const [newFolderDraft, setNewFolderDraft] = useState('')

  const queryLower = searchQuery.toLowerCase()
  const filteredConversations = useMemo(
    () =>
      conversations.filter((c) =>
        queryLower ? c.title.toLowerCase().includes(queryLower) : true
      ),
    [conversations, queryLower]
  )

  const { tree, rootConversations } = useMemo(
    () => buildTree(folders, filteredConversations),
    [folders, filteredConversations]
  )

  const toggleExpand = (folderId: string) => {
    setExpanded((e) => ({ ...e, [folderId]: !e[folderId] }))
  }

  const commitRename = () => {
    if (renamingFolderId) {
      const name = renameDraft.trim()
      if (name) onRenameFolder(renamingFolderId, name)
    }
    setRenamingFolderId(null)
    setRenameDraft('')
  }

  const commitNewFolder = () => {
    const name = newFolderDraft.trim()
    if (name) onCreateFolder(name, null)
    setCreatingFolder(false)
    setNewFolderDraft('')
  }

  const handleDrop = (targetFolderId: string | null) => {
    if (!drag) return
    if (drag.kind === 'conversation') {
      onMoveConversation(drag.id, targetFolderId)
    } else if (drag.kind === 'folder') {
      if (targetFolderId === drag.id) return
      if (targetFolderId && isDescendant(folders, targetFolderId, drag.id)) return
      onMoveFolder(drag.id, targetFolderId)
    }
    setDrag(null)
    setDropTarget(null)
  }

  const renderConversation = (conv: Conversation, depth: number) => {
    const isActive = conv.id === activeId
    return (
      <li key={conv.id}>
        <button
          draggable
          onDragStart={(e) => {
            e.dataTransfer.effectAllowed = 'move'
            setDrag({ kind: 'conversation', id: conv.id })
          }}
          onDragEnd={() => {
            setDrag(null)
            setDropTarget(null)
          }}
          onClick={() => onSelect(conv.id)}
          onContextMenu={(e) => {
            e.preventDefault()
            const action = window.prompt(
              `Conversation: "${conv.title}"\n\nType: rename / delete / move (or empty to cancel)`,
              ''
            )
            if (!action) return
            const trimmed = action.trim().toLowerCase()
            if (trimmed === 'rename' && onRenameConversation) {
              const next = window.prompt('New title', conv.title)
              if (next && next.trim()) onRenameConversation(conv.id, next.trim())
            } else if (trimmed === 'delete') {
              if (window.confirm(`Delete "${conv.title}"?`)) onDeleteConversation(conv.id)
            } else if (trimmed === 'move') {
              const options = folders.map((f) => `${f.id} — ${f.name}`).join('\n')
              const fid = window.prompt(
                `Move to folder id (empty = root):\n${options || '(no folders)'}`,
                conv.folderId ?? ''
              )
              onMoveConversation(conv.id, fid && fid.trim() ? fid.trim() : null)
            }
          }}
          className={cn(
            'w-full text-left py-2 rounded-md flex items-start gap-2 transition-colors group',
            isActive
              ? 'bg-[#111111] border-l-2 border-accent-blue'
              : 'hover:bg-[#0f0f0f] border-l-2 border-transparent'
          )}
          style={{ paddingLeft: 10 + depth * 12, paddingRight: 10 }}
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
            <span className="text-[10px] text-[#888888] font-mono">{conv.timestamp}</span>
          </div>
        </button>
      </li>
    )
  }

  const renderFolderNode = (node: TreeNode, depth: number) => {
    const isExpanded = expanded[node.folder.id] ?? true
    const isDropTarget = dropTarget === node.folder.id
    const isRenaming = renamingFolderId === node.folder.id
    return (
      <li key={node.folder.id}>
        <div
          onDragOver={(e) => {
            if (!drag) return
            e.preventDefault()
            e.dataTransfer.dropEffect = 'move'
            setDropTarget(node.folder.id)
          }}
          onDragLeave={() => {
            if (dropTarget === node.folder.id) setDropTarget(null)
          }}
          onDrop={(e) => {
            e.preventDefault()
            handleDrop(node.folder.id)
          }}
          draggable={!isRenaming}
          onDragStart={(e) => {
            e.dataTransfer.effectAllowed = 'move'
            setDrag({ kind: 'folder', id: node.folder.id })
          }}
          onDragEnd={() => {
            setDrag(null)
            setDropTarget(null)
          }}
          className={cn(
            'flex items-center gap-1 py-1 rounded-md group cursor-pointer',
            isDropTarget ? 'bg-accent-blue/20 ring-1 ring-accent-blue/60' : 'hover:bg-[#0f0f0f]'
          )}
          style={{ paddingLeft: 6 + depth * 12, paddingRight: 6 }}
        >
          <button
            onClick={() => toggleExpand(node.folder.id)}
            className="text-[#888888] hover:text-white transition-colors p-0.5 rounded"
            aria-label={isExpanded ? 'Collapse folder' : 'Expand folder'}
          >
            <ChevronRight
              size={11}
              className={cn('transition-transform', isExpanded && 'rotate-90')}
            />
          </button>
          {isExpanded ? (
            <FolderOpen size={12} className="text-[#888888] flex-shrink-0" />
          ) : (
            <FolderIcon size={12} className="text-[#888888] flex-shrink-0" />
          )}
          {isRenaming ? (
            <input
              autoFocus
              value={renameDraft}
              onChange={(e) => setRenameDraft(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => {
                if (e.key === 'Enter') commitRename()
                if (e.key === 'Escape') {
                  setRenamingFolderId(null)
                  setRenameDraft('')
                }
              }}
              className="flex-1 bg-[#0a0a0a] border border-white/[0.12] text-xs text-white font-sans outline-none px-1.5 py-0.5 rounded"
            />
          ) : (
            <button
              onDoubleClick={() => {
                setRenamingFolderId(node.folder.id)
                setRenameDraft(node.folder.name)
              }}
              onClick={() => toggleExpand(node.folder.id)}
              className="flex-1 text-left text-xs font-sans text-[#cccccc] truncate"
            >
              {node.folder.name}
            </button>
          )}
          <button
            onClick={(e) => {
              e.stopPropagation()
              setRenamingFolderId(node.folder.id)
              setRenameDraft(node.folder.name)
            }}
            className="text-[#555555] hover:text-white opacity-0 group-hover:opacity-100 transition-opacity p-0.5"
            aria-label="Rename folder"
          >
            <Pencil size={10} />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (window.confirm(`Delete folder "${node.folder.name}"? Conversations inside move to root.`)) {
                onDeleteFolder(node.folder.id)
              }
            }}
            className="text-[#555555] hover:text-accent-pink opacity-0 group-hover:opacity-100 transition-opacity p-0.5"
            aria-label="Delete folder"
          >
            <Trash2 size={10} />
          </button>
        </div>
        {isExpanded && (
          <ul className="flex flex-col gap-0.5">
            {node.children.map((child) => renderFolderNode(child, depth + 1))}
            {node.conversations.map((conv) => renderConversation(conv, depth + 1))}
          </ul>
        )}
      </li>
    )
  }

  return (
    <aside
      className={cn(
        'flex flex-col h-full w-full bg-[#0a0a0a] border-r border-white/[0.06]',
        className
      )}
    >
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

      <div className="flex items-center gap-1.5 px-3 pb-2">
        <button
          onClick={onNew}
          className="flex-1 flex items-center justify-center gap-2 px-3 py-2 rounded-md border border-accent-blue/40 text-accent-blue text-xs font-sans hover:bg-accent-blue/10 transition-colors"
        >
          <Plus size={13} />
          New chat
        </button>
        <button
          onClick={() => {
            setCreatingFolder(true)
            setNewFolderDraft('')
          }}
          className="flex items-center justify-center px-2.5 py-2 rounded-md border border-white/[0.08] text-[#aaaaaa] hover:text-white hover:border-white/[0.18] transition-colors"
          aria-label="New folder"
          title="New folder"
        >
          <FolderPlus size={13} />
        </button>
      </div>

      {creatingFolder && (
        <div className="px-3 pb-2">
          <input
            autoFocus
            value={newFolderDraft}
            onChange={(e) => setNewFolderDraft(e.target.value)}
            onBlur={commitNewFolder}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitNewFolder()
              if (e.key === 'Escape') {
                setCreatingFolder(false)
                setNewFolderDraft('')
              }
            }}
            placeholder="Folder name..."
            className="w-full bg-[#111111] border border-white/[0.12] text-xs text-white font-sans outline-none px-2 py-1.5 rounded"
          />
        </div>
      )}

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

      <nav
        className="flex-1 overflow-y-auto px-2 pb-4"
        aria-label="Conversation history"
        onDragOver={(e) => {
          if (!drag) return
          e.preventDefault()
          setDropTarget('root')
        }}
        onDragLeave={() => {
          if (dropTarget === 'root') setDropTarget(null)
        }}
        onDrop={(e) => {
          e.preventDefault()
          if (dropTarget === 'root') handleDrop(null)
        }}
      >
        {tree.length === 0 && rootConversations.length === 0 ? (
          <p className="text-[#888888] text-xs px-2 py-4 text-center">No conversations</p>
        ) : (
          <ul
            className={cn(
              'flex flex-col gap-0.5 rounded-md py-1',
              dropTarget === 'root' && 'bg-accent-blue/10 ring-1 ring-accent-blue/40'
            )}
          >
            {tree.map((node) => renderFolderNode(node, 0))}
            {rootConversations.map((conv) => renderConversation(conv, 0))}
          </ul>
        )}
      </nav>
    </aside>
  )
}

'use client'

import { useCallback, useMemo, useState } from 'react'
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
  MoreVertical,
  ArrowRightLeft,
  CheckSquare,
  Square,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ConfirmModal } from './ConfirmModal'
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
  const [renamingConvoId, setRenamingConvoId] = useState<string | null>(null)
  const [convoRenameDraft, setConvoRenameDraft] = useState('')
  const [drag, setDrag] = useState<DragItem | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null) // folderId or 'root'
  const [creatingFolder, setCreatingFolder] = useState(false)
  const [newFolderDraft, setNewFolderDraft] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<
    | { kind: 'conversation'; id: string; name: string }
    | { kind: 'folder'; id: string; name: string }
    | { kind: 'bulk-conversations'; ids: string[] }
    | null
  >(null)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [lastClickedId, setLastClickedId] = useState<string | null>(null)
  const [bulkMoveOpen, setBulkMoveOpen] = useState(false)

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

  // Depth-first order of visible conversations — used by shift-click range
  // select so the user gets the same span they visually see.
  const visibleOrder: string[] = useMemo(() => {
    const out: string[] = []
    const walk = (node: TreeNode) => {
      node.children.forEach(walk)
      node.conversations.forEach((c) => out.push(c.id))
    }
    tree.forEach(walk)
    rootConversations.forEach((c) => out.push(c.id))
    return out
  }, [tree, rootConversations])

  const clearSelection = useCallback(() => {
    setSelectedIds(new Set())
    setLastClickedId(null)
  }, [])

  const handleConversationClick = useCallback(
    (id: string, e: React.MouseEvent) => {
      const cmd = e.metaKey || e.ctrlKey
      const shift = e.shiftKey

      if (cmd) {
        // Toggle selection; keep single-active behavior independent
        setSelectedIds((prev) => {
          const next = new Set(prev)
          if (next.has(id)) next.delete(id)
          else next.add(id)
          return next
        })
        setLastClickedId(id)
        return
      }
      if (shift && lastClickedId) {
        const a = visibleOrder.indexOf(lastClickedId)
        const b = visibleOrder.indexOf(id)
        if (a >= 0 && b >= 0) {
          const [lo, hi] = a < b ? [a, b] : [b, a]
          const range = visibleOrder.slice(lo, hi + 1)
          setSelectedIds((prev) => {
            const next = new Set(prev)
            range.forEach((rid) => next.add(rid))
            return next
          })
        }
        return
      }

      // Plain click: clear multi-select and open the conversation
      if (selectedIds.size > 0) clearSelection()
      onSelect(id)
      setLastClickedId(id)
    },
    [lastClickedId, visibleOrder, selectedIds.size, clearSelection, onSelect]
  )

  const bulkMoveTo = useCallback(
    (folderId: string | null) => {
      Array.from(selectedIds).forEach((id) => onMoveConversation(id, folderId))
      setBulkMoveOpen(false)
      clearSelection()
    },
    [selectedIds, onMoveConversation, clearSelection]
  )

  const executeBulkDelete = useCallback(() => {
    Array.from(selectedIds).forEach((id) => onDeleteConversation(id))
    clearSelection()
  }, [selectedIds, onDeleteConversation, clearSelection])

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

  const startConvoRename = (conv: Conversation) => {
    setRenamingConvoId(conv.id)
    setConvoRenameDraft(conv.title)
  }

  const commitConvoRename = () => {
    if (renamingConvoId && onRenameConversation) {
      const name = convoRenameDraft.trim()
      if (name) onRenameConversation(renamingConvoId, name)
    }
    setRenamingConvoId(null)
    setConvoRenameDraft('')
  }

  const confirmDeleteMessage = (() => {
    if (!confirmDelete) return ''
    if (confirmDelete.kind === 'conversation') {
      return `Delete conversation "${confirmDelete.name}"? Messages, runs, and events are deleted server-side and cannot be recovered.`
    }
    if (confirmDelete.kind === 'folder') {
      return `Delete folder "${confirmDelete.name}"? Conversations inside move to root; child folders are re-parented to root.`
    }
    return `Delete ${confirmDelete.ids.length} conversation${confirmDelete.ids.length === 1 ? '' : 's'}? Messages, runs, and events for each are deleted server-side and cannot be recovered.`
  })()

  const executeConfirmDelete = () => {
    if (!confirmDelete) return
    if (confirmDelete.kind === 'conversation') onDeleteConversation(confirmDelete.id)
    else if (confirmDelete.kind === 'folder') onDeleteFolder(confirmDelete.id)
    else executeBulkDelete()
    setConfirmDelete(null)
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
    const isRenaming = renamingConvoId === conv.id
    const isSelected = selectedIds.has(conv.id)
    return (
      <li key={conv.id}>
        <div
          draggable={!isRenaming}
          onDragStart={(e) => {
            e.dataTransfer.effectAllowed = 'move'
            setDrag({ kind: 'conversation', id: conv.id })
          }}
          onDragEnd={() => {
            setDrag(null)
            setDropTarget(null)
          }}
          className={cn(
            'relative py-2 rounded-md flex items-start gap-2 transition-colors group cursor-pointer',
            isSelected
              ? 'bg-accent-blue/15 border-l-2 border-accent-blue/70'
              : isActive
                ? 'bg-[#111111] border-l-2 border-accent-blue'
                : 'hover:bg-[#0f0f0f] border-l-2 border-transparent'
          )}
          style={{ paddingLeft: 10 + depth * 12, paddingRight: 6 }}
          onClick={(e) => {
            if (isRenaming) return
            handleConversationClick(conv.id, e)
          }}
          role="button"
          tabIndex={0}
          aria-selected={isSelected}
          onKeyDown={(e) => {
            if (isRenaming) return
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onSelect(conv.id)
            }
          }}
          aria-current={isActive ? 'page' : undefined}
        >
          {isSelected ? (
            <CheckSquare
              size={13}
              className="mt-0.5 flex-shrink-0 text-accent-blue"
            />
          ) : selectedIds.size > 0 ? (
            <Square
              size={13}
              className="mt-0.5 flex-shrink-0 text-[#555555]"
            />
          ) : (
            <MessageSquare
              size={13}
              className={cn(
                'mt-0.5 flex-shrink-0',
                isActive ? 'text-accent-blue' : 'text-[#888888]'
              )}
            />
          )}
          <div className="flex flex-col gap-0.5 min-w-0 flex-1">
            {isRenaming ? (
              <input
                autoFocus
                value={convoRenameDraft}
                onChange={(e) => setConvoRenameDraft(e.target.value)}
                onBlur={commitConvoRename}
                onKeyDown={(e) => {
                  e.stopPropagation()
                  if (e.key === 'Enter') commitConvoRename()
                  if (e.key === 'Escape') {
                    setRenamingConvoId(null)
                    setConvoRenameDraft('')
                  }
                }}
                onClick={(e) => e.stopPropagation()}
                className="bg-[#0a0a0a] border border-white/[0.12] text-xs text-white font-sans outline-none px-1.5 py-0.5 rounded"
              />
            ) : (
              <span
                className={cn(
                  'text-xs font-sans truncate leading-tight',
                  isActive ? 'text-white' : 'text-[#cccccc]'
                )}
              >
                {conv.title}
              </span>
            )}
            <span className="text-[10px] text-[#888888] font-mono">{conv.timestamp}</span>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                onClick={(e) => e.stopPropagation()}
                className={cn(
                  'flex-shrink-0 self-start mt-0.5 p-1 rounded text-[#555555] hover:text-white hover:bg-white/[0.06] transition-colors',
                  'opacity-0 group-hover:opacity-100 focus:opacity-100 data-[state=open]:opacity-100'
                )}
                aria-label={`Actions for ${conv.title}`}
              >
                <MoreVertical size={12} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="min-w-[180px] bg-[#0f0f0f] border-white/[0.08] text-[#cccccc]"
              onClick={(e) => e.stopPropagation()}
            >
              <DropdownMenuItem
                onSelect={() => startConvoRename(conv)}
                className="text-xs"
              >
                <Pencil size={11} /> Rename
              </DropdownMenuItem>
              <DropdownMenuSub>
                <DropdownMenuSubTrigger className="text-xs">
                  <ArrowRightLeft size={11} /> Move to…
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent className="min-w-[180px] bg-[#0f0f0f] border-white/[0.08] text-[#cccccc]">
                  <DropdownMenuItem
                    className="text-xs"
                    onSelect={() => onMoveConversation(conv.id, null)}
                    disabled={!conv.folderId}
                  >
                    <FolderIcon size={11} /> Root
                  </DropdownMenuItem>
                  {folders.length > 0 && <DropdownMenuSeparator />}
                  {folders.map((f) => (
                    <DropdownMenuItem
                      key={f.id}
                      className="text-xs"
                      onSelect={() => onMoveConversation(conv.id, f.id)}
                      disabled={conv.folderId === f.id}
                    >
                      <FolderIcon size={11} /> {f.name}
                    </DropdownMenuItem>
                  ))}
                  {folders.length === 0 && (
                    <div className="px-2 py-1.5 text-[10px] font-mono text-[#555555]">
                      No folders yet
                    </div>
                  )}
                </DropdownMenuSubContent>
              </DropdownMenuSub>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                className="text-xs"
                onSelect={() =>
                  setConfirmDelete({ kind: 'conversation', id: conv.id, name: conv.title })
                }
              >
                <Trash2 size={11} /> Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
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
            e.stopPropagation()
            e.dataTransfer.dropEffect = 'move'
            setDropTarget(node.folder.id)
          }}
          onDragLeave={(e) => {
            e.stopPropagation()
            if (dropTarget === node.folder.id) setDropTarget(null)
          }}
          onDrop={(e) => {
            e.preventDefault()
            e.stopPropagation()
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
              setConfirmDelete({ kind: 'folder', id: node.folder.id, name: node.folder.name })
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

      {/* Bulk selection action bar */}
      {selectedIds.size > 0 && (
        <div className="mx-3 mb-2 rounded-md border border-accent-blue/40 bg-accent-blue/10 px-2 py-1.5 flex items-center gap-1.5">
          <span className="text-[10px] font-mono text-accent-blue flex-shrink-0">
            {selectedIds.size} selected
          </span>
          <div className="flex-1" />
          <DropdownMenu open={bulkMoveOpen} onOpenChange={setBulkMoveOpen}>
            <DropdownMenuTrigger asChild>
              <button
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono text-[#cccccc] hover:text-white hover:bg-white/[0.06]"
                title="Move selected to folder"
              >
                <ArrowRightLeft size={10} />
                Move
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="min-w-[180px] bg-[#0f0f0f] border-white/[0.08] text-[#cccccc]"
            >
              <DropdownMenuItem
                className="text-xs"
                onSelect={() => bulkMoveTo(null)}
              >
                <FolderIcon size={11} /> Root
              </DropdownMenuItem>
              {folders.length > 0 && <DropdownMenuSeparator />}
              {folders.map((f) => (
                <DropdownMenuItem
                  key={f.id}
                  className="text-xs"
                  onSelect={() => bulkMoveTo(f.id)}
                >
                  <FolderIcon size={11} /> {f.name}
                </DropdownMenuItem>
              ))}
              {folders.length === 0 && (
                <div className="px-2 py-1.5 text-[10px] font-mono text-[#555555]">
                  No folders yet
                </div>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
          <button
            onClick={() =>
              setConfirmDelete({ kind: 'bulk-conversations', ids: Array.from(selectedIds) })
            }
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono text-[var(--accent-pink)] hover:bg-[var(--accent-pink)]/10"
            title="Delete selected"
          >
            <Trash2 size={10} />
            Delete
          </button>
          <button
            onClick={clearSelection}
            className="inline-flex items-center p-0.5 rounded text-[#888888] hover:text-white"
            title="Clear selection"
            aria-label="Clear selection"
          >
            <X size={11} />
          </button>
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

      {confirmDelete && (
        <ConfirmModal
          title={confirmDelete.kind === 'conversation' ? 'Delete conversation' : 'Delete folder'}
          description={confirmDeleteMessage}
          confirmLabel="Delete"
          onConfirm={executeConfirmDelete}
          onCancel={() => setConfirmDelete(null)}
        />
      )}
    </aside>
  )
}

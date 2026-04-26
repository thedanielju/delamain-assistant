'use client'

import { useCallback, useEffect, useMemo, useRef, useState, useTransition } from 'react'
import {
  AlertCircle,
  Check,
  FileText,
  FolderPlus,
  GitBranch,
  Layers,
  Link2,
  Network,
  Pin,
  Play,
  RefreshCw,
  Search,
  ShieldOff,
  Sparkles,
  Wrench,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { api, BackendError } from '@/lib/api'
import { VaultGraphCanvas } from './VaultGraphCanvas'
import type {
  VaultContextItem,
  VaultEnrichmentBatchStatus,
  VaultEnrichmentStatus,
  VaultGraph,
  VaultGraphNeighborhood,
  VaultGeneratedRelation,
  VaultMaintenanceProposalDiffResponse,
  VaultMaintenanceProposal,
  VaultNode,
  VaultNoteDetail,
  VaultPolicyExclusion,
  VaultFolderKind,
} from '@/lib/types'

interface VaultPanelProps {
  conversationId: string
  pinnedItems?: VaultContextItem[]
  onPinToContext?: (items: Array<VaultContextItem | VaultNoteDetail | string>) => void
}

type VaultTab = 'graph' | 'list' | 'preview' | 'review' | 'maintenance' | 'atlas'
type SpecialFilter = 'pinned' | 'needs_review' | null
type RelationDecision = 'accepted' | 'rejected'
type LoadState =
  | { kind: 'idle' }
  | { kind: 'loading' }
  | { kind: 'error'; status: number | null; message: string }
  | { kind: 'loaded'; graph: VaultGraph }

const MAX_LIST_NODES = 80

function titleFromPath(path: string) {
  const parts = path.split('/')
  return parts[parts.length - 1] || path
}

function sourceLabel(value?: string | null) {
  if (value === 'workspace_syllabus') return 'Syllabi'
  if (value === 'workspace_reference') return 'Reference'
  if (value === 'vault_note') return 'Vault Notes'
  return value || 'Unknown'
}

function folderForNode(node: VaultNode) {
  if (node.folder) return node.folder
  const parts = node.path.split('/')
  return parts.length > 1 ? parts.slice(0, -1).join('/') : '/'
}

function archiveStateForNode(node: VaultNode) {
  if (node.archive_state) return node.archive_state
  return node.path.toLowerCase().includes('/archive/') ? 'archive' : 'active'
}

function allTagsForNode(node: VaultNode) {
  return Array.from(new Set([...(node.tags ?? []), ...(node.generated_tags ?? [])]))
}

function needsReview(node: VaultNode) {
  const values = [
    node.status,
    node.placement,
    node.archive_state,
    node.staleness_status,
    node.sync_status,
    ...(node.warnings ?? []),
    ...(node.stale_reasons ?? []),
  ].filter(Boolean).map((value) => String(value).toLowerCase())
  return values.some((value) =>
    value.includes('stale') ||
    value.includes('review') ||
    value.includes('failed') ||
    value.includes('conflict') ||
    value.includes('ocr') ||
    value.includes('reprocess')
  )
}

function normalizeExclusions(raw: unknown): VaultPolicyExclusion[] {
  if (!raw || typeof raw !== 'object') return []
  const r = raw as { exclusions?: unknown[]; items?: unknown[]; paths?: string[] }
  const values = r.exclusions ?? r.items ?? r.paths ?? []
  return values.flatMap((item) => {
    if (typeof item === 'string') return [{ id: item, path: item }]
    if (!item || typeof item !== 'object') return []
    const value = item as { id?: string; path?: string; reason?: string | null; created_at?: string | null; createdAt?: string | null }
    if (!value.path) return []
    return [{
      id: value.id ?? value.path,
      path: value.path,
      reason: value.reason ?? null,
      createdAt: value.createdAt ?? value.created_at ?? null,
    }]
  })
}

function countBy<T extends string>(nodes: VaultNode[], valueForNode: (node: VaultNode) => T | null | undefined) {
  const counts = new Map<T, number>()
  for (const node of nodes) {
    const value = valueForNode(node)
    if (!value) continue
    counts.set(value, (counts.get(value) ?? 0) + 1)
  }
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
}

function normalizeProposals(raw: unknown): VaultMaintenanceProposal[] {
  if (!raw) return []
  const values = Array.isArray(raw)
    ? raw
    : typeof raw === 'object'
      ? ((raw as { proposals?: unknown[]; items?: unknown[] }).proposals ??
        (raw as { proposals?: unknown[]; items?: unknown[] }).items ??
        [])
      : []
  return values.flatMap((item, index) => {
    if (!item || typeof item !== 'object') return []
    const value = item as Partial<VaultMaintenanceProposal>
    return [{
      id: value.id ?? `proposal-${index}`,
      title: value.title ?? value.summary ?? 'Vault maintenance proposal',
      summary: value.summary ?? value.description ?? undefined,
      description: value.description,
      kind: value.kind,
      path: value.path,
      paths: value.paths,
      risk: value.risk,
      status: value.status,
      command: value.command,
      payload: value.payload,
    }]
  })
}

function normalizeRelations(raw: unknown): VaultGeneratedRelation[] {
  if (!raw || typeof raw !== 'object') return []
  const values = Array.isArray(raw)
    ? raw
    : (raw as { relations?: unknown[]; items?: unknown[] }).relations ??
      (raw as { relations?: unknown[]; items?: unknown[] }).items ??
      []
  return values.flatMap((item) => {
    if (!item || typeof item !== 'object') return []
    const value = item as Partial<VaultGeneratedRelation>
    if (!value.from_path || !value.to_path) return []
    const relationType = value.relation_type ?? 'related'
    return [{
      from_path: value.from_path,
      to_path: value.to_path,
      relation_type: relationType,
      reason: value.reason ?? null,
      confidence: value.confidence ?? null,
      decision: value.decision ?? 'candidate',
      key: value.key ?? `${value.from_path}\u001f${value.to_path}\u001f${relationType}`,
    }]
  }).sort((a, b) => {
    const decisionRank = (decision: string) => decision === 'candidate' ? 0 : decision === 'accepted' ? 1 : 2
    const byDecision = decisionRank(a.decision) - decisionRank(b.decision)
    if (byDecision !== 0) return byDecision
    return (b.confidence ?? 0) - (a.confidence ?? 0)
  })
}

function relationLabel(path: string, nodesByPath: Map<string, VaultNode>) {
  return nodesByPath.get(path)?.title ?? titleFromPath(path)
}

function candidatePath(value: unknown) {
  if (typeof value === 'string') return value
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  return typeof item.path === 'string'
    ? item.path
    : typeof item.to_path === 'string'
      ? item.to_path
      : typeof item.note_path === 'string'
        ? item.note_path
        : null
}

function candidateLabel(value: unknown) {
  const path = candidatePath(value)
  if (!path) return null
  if (!value || typeof value !== 'object') return titleFromPath(path)
  const item = value as Record<string, unknown>
  return typeof item.title === 'string' ? item.title : titleFromPath(path)
}

function TabButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean
  icon: React.ReactNode
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center justify-center gap-1 rounded-md border px-2 py-1 text-[10px] font-mono transition-colors',
        active
          ? 'border-[var(--accent-blue)]/40 bg-[var(--accent-blue)]/10 text-[var(--accent-blue)]'
          : 'border-white/[0.07] text-[#777777] hover:border-white/20 hover:text-[#cccccc]'
      )}
      aria-pressed={active}
    >
      {icon}
      {label}
    </button>
  )
}

function FilterChip({
  active,
  label,
  count,
  onClick,
}: {
  active: boolean
  label: string
  count?: number
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[9px] font-mono',
        active
          ? 'border-[var(--accent-blue)]/40 bg-[var(--accent-blue)]/10 text-[var(--accent-blue)]'
          : 'border-white/[0.08] text-[#888888] hover:border-white/20 hover:text-white'
      )}
      title={label}
    >
      <span className="max-w-[120px] truncate">{label}</span>
      {count != null && <span className="text-[#444444]">{count}</span>}
    </button>
  )
}

function FilterGroup({
  label,
  values,
  selected,
  onSelect,
  limit = 18,
}: {
  label: string
  values: Array<[string, number]>
  selected: string | null
  onSelect: (value: string | null) => void
  limit?: number
}) {
  if (!values.length) return null
  return (
    <div className="flex min-w-0 items-center gap-1">
      <span className="flex-shrink-0 text-[9px] font-mono text-[#444444]">{label}</span>
      <div className="flex min-w-0 flex-wrap gap-1">
        {values.slice(0, limit).map(([value, count]) => (
          <FilterChip
            key={value}
            active={selected === value}
            label={value}
            count={count}
            onClick={() => onSelect(selected === value ? null : value)}
          />
        ))}
      </div>
    </div>
  )
}

export function VaultPanel({ conversationId, pinnedItems = [], onPinToContext }: VaultPanelProps) {
  const [tab, setTab] = useState<VaultTab>('graph')
  const [state, setState] = useState<LoadState>({ kind: 'idle' })
  const [selectedPath, setSelectedPath] = useState<string | null>(null)
  const [note, setNote] = useState<VaultNoteDetail | null>(null)
  const [noteLoading, setNoteLoading] = useState(false)
  const [neighborhood, setNeighborhood] = useState<VaultGraphNeighborhood | null>(null)
  const [neighborhoodStatus, setNeighborhoodStatus] = useState<'idle' | 'loading' | 'error'>('idle')
  const [tagFilter, setTagFilter] = useState<string | null>(null)
  const [sourceFilter, setSourceFilter] = useState<string | null>(null)
  const [folderFilter, setFolderFilter] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<string | null>(null)
  const [placementFilter, setPlacementFilter] = useState<string | null>(null)
  const [archiveFilter, setArchiveFilter] = useState<string | null>(null)
  const [stalenessFilter, setStalenessFilter] = useState<string | null>(null)
  const [syncFilter, setSyncFilter] = useState<string | null>(null)
  const [generatedFilter, setGeneratedFilter] = useState<string | null>(null)
  const [specialFilter, setSpecialFilter] = useState<SpecialFilter>(null)
  const [query, setQuery] = useState('')
  const [exclusions, setExclusions] = useState<VaultPolicyExclusion[]>([])
  const [proposals, setProposals] = useState<VaultMaintenanceProposal[]>([])
  const [relations, setRelations] = useState<VaultGeneratedRelation[]>([])
  const [enrichmentStatus, setEnrichmentStatus] = useState<VaultEnrichmentStatus | null>(null)
  const [batchStatus, setBatchStatus] = useState<VaultEnrichmentBatchStatus | null>(null)
  const [relationBusy, setRelationBusy] = useState<Record<string, RelationDecision | 'loading'>>({})
  const [enrichmentBusy, setEnrichmentBusy] = useState(false)
  const [proposalDiffs, setProposalDiffs] = useState<Record<string, VaultMaintenanceProposalDiffResponse | { error: string }>>({})
  const [metadataStatus, setMetadataStatus] = useState<'idle' | 'loading' | 'degraded'>('idle')
  const [newFolderKind, setNewFolderKind] = useState<VaultFolderKind>('project')
  const [newFolderName, setNewFolderName] = useState('')
  const [folderInitStatus, setFolderInitStatus] = useState<'idle' | 'running' | 'done' | 'error'>('idle')
  const [folderInitMessage, setFolderInitMessage] = useState<string | null>(null)
  const [isPending, startTransition] = useTransition()
  const noteRequestRef = useRef(0)

  const pinnedPaths = useMemo(() => new Set(pinnedItems.map((item) => item.path)), [pinnedItems])
  const excludedPaths = useMemo(() => new Set(exclusions.map((item) => item.path)), [exclusions])

  const load = useCallback(async () => {
    setState({ kind: 'loading' })
    setMetadataStatus('loading')
    try {
      const [
        graph,
        exclusionResult,
        proposalResult,
        enrichmentResult,
        batchResult,
        relationResult,
      ] = await Promise.all([
        api.getVaultGraph({ limit: 2500 }),
        api.listVaultPolicyExclusions().catch((err) => err),
        api.listVaultMaintenanceProposals().catch((err) => err),
        api.getVaultEnrichmentStatus().catch((err) => err),
        api.getVaultEnrichmentBatchStatus().catch((err) => err),
        api.listVaultGeneratedRelations().catch((err) => err),
      ])
      setState({ kind: 'loaded', graph })
      if (!(exclusionResult instanceof Error)) setExclusions(normalizeExclusions(exclusionResult))
      if (!(proposalResult instanceof Error)) setProposals(normalizeProposals(proposalResult))
      if (!(enrichmentResult instanceof Error)) setEnrichmentStatus(enrichmentResult)
      if (!(batchResult instanceof Error)) setBatchStatus(batchResult)
      if (!(relationResult instanceof Error)) setRelations(normalizeRelations(relationResult))
      setMetadataStatus(
        exclusionResult instanceof Error ||
          proposalResult instanceof Error ||
          enrichmentResult instanceof Error ||
          batchResult instanceof Error ||
          relationResult instanceof Error
          ? 'degraded'
          : 'idle'
      )
    } catch (err) {
      const status = err instanceof BackendError ? err.status : null
      const message = err instanceof Error ? err.message : 'Failed to load vault graph'
      setState({ kind: 'error', status, message })
      setMetadataStatus('degraded')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const loadNote = useCallback((path: string) => {
    const requestId = noteRequestRef.current + 1
    noteRequestRef.current = requestId
    setSelectedPath(path)
    setTab('preview')
    setNoteLoading(true)
    setNeighborhood(null)
    setNeighborhoodStatus('idle')
    api.getVaultNote(path)
      .then((note) => {
        if (noteRequestRef.current !== requestId) return
        setNote(note)
      })
      .catch(() => {
        if (noteRequestRef.current !== requestId) return
        setNote({
          path,
          title: titleFromPath(path),
          content: '',
          tags: [],
          backlinks: [],
        })
      })
      .finally(() => {
        if (noteRequestRef.current !== requestId) return
        setNoteLoading(false)
      })
  }, [])

  const loadNeighborhood = useCallback(async (path: string, hops: 1 | 2) => {
    setNeighborhoodStatus('loading')
    try {
      const result = await api.getVaultGraphNeighborhood(path, hops, hops === 1 ? 80 : 140)
      setNeighborhood(result)
      setNeighborhoodStatus('idle')
    } catch {
      setNeighborhood(null)
      setNeighborhoodStatus('error')
    }
  }, [])

  const tagCounts = useMemo(() => {
    if (state.kind !== 'loaded') return [] as Array<[string, number]>
    const counts = new Map<string, number>()
    for (const node of state.graph.nodes) {
      for (const tag of allTagsForNode(node)) counts.set(tag, (counts.get(tag) ?? 0) + 1)
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
  }, [state])

  const sourceCounts = useMemo(() => {
    if (state.kind !== 'loaded') return [] as Array<[string, number]>
    const counts = new Map<string, number>()
    for (const node of state.graph.nodes) {
      const source = node.source_type ?? 'vault_note'
      counts.set(source, (counts.get(source) ?? 0) + 1)
    }
    const order = ['vault_note', 'workspace_syllabus', 'workspace_reference']
    return Array.from(counts.entries()).sort((a, b) => {
      const aIndex = order.indexOf(a[0])
      const bIndex = order.indexOf(b[0])
      if (aIndex !== -1 || bIndex !== -1) return (aIndex === -1 ? 99 : aIndex) - (bIndex === -1 ? 99 : bIndex)
      return a[0].localeCompare(b[0])
    })
  }, [state])

  const folderCounts = useMemo(() => {
    if (state.kind !== 'loaded') return [] as Array<[string, number]>
    return countBy(state.graph.nodes, folderForNode)
  }, [state])

  const categoryCounts = useMemo(() => {
    if (state.kind !== 'loaded') return [] as Array<[string, number]>
    return countBy(state.graph.nodes, (node) => node.category || null)
  }, [state])

  const statusCounts = useMemo(() => {
    if (state.kind !== 'loaded') return [] as Array<[string, number]>
    return countBy(state.graph.nodes, (node) => node.status || null)
  }, [state])

  const placementCounts = useMemo(() => {
    if (state.kind !== 'loaded') return [] as Array<[string, number]>
    return countBy(state.graph.nodes, (node) => node.placement || null)
  }, [state])

  const archiveCounts = useMemo(() => {
    if (state.kind !== 'loaded') return [] as Array<[string, number]>
    return countBy(state.graph.nodes, archiveStateForNode)
  }, [state])

  const stalenessCounts = useMemo(() => {
    if (state.kind !== 'loaded') return [] as Array<[string, number]>
    return countBy(state.graph.nodes, (node) => node.staleness_status || null)
  }, [state])

  const syncCounts = useMemo(() => {
    if (state.kind !== 'loaded') return [] as Array<[string, number]>
    return countBy(state.graph.nodes, (node) => node.sync_status || null)
  }, [state])

  const generatedCounts = useMemo(() => {
    if (state.kind !== 'loaded') return [] as Array<[string, number]>
    return countBy(state.graph.nodes, (node) => node.generated_metadata_state || node.summary_status || null)
  }, [state])

  const nodesByPath = useMemo(() => {
    if (state.kind !== 'loaded') return new Map<string, VaultNode>()
    return new Map(state.graph.nodes.map((node) => [node.path, node]))
  }, [state])

  const relationCounts = useMemo(() => ({
    candidate: relations.filter((relation) => relation.decision === 'candidate').length,
    accepted: relations.filter((relation) => relation.decision === 'accepted').length,
    rejected: relations.filter((relation) => relation.decision === 'rejected').length,
  }), [relations])

  const clearGraphFilters = useCallback(() => {
    setSourceFilter(null)
    setTagFilter(null)
    setFolderFilter(null)
    setCategoryFilter(null)
    setStatusFilter(null)
    setPlacementFilter(null)
    setArchiveFilter(null)
    setStalenessFilter(null)
    setSyncFilter(null)
    setGeneratedFilter(null)
    setSpecialFilter(null)
  }, [])

  const nodes = useMemo(() => {
    if (state.kind !== 'loaded') return [] as VaultNode[]
    const q = query.trim().toLowerCase()
    const list = state.graph.nodes.filter((node) => {
      if (sourceFilter && (node.source_type ?? 'vault_note') !== sourceFilter) return false
      if (tagFilter && !allTagsForNode(node).includes(tagFilter)) return false
      if (folderFilter && folderForNode(node) !== folderFilter) return false
      if (categoryFilter && node.category !== categoryFilter) return false
      if (statusFilter && node.status !== statusFilter) return false
      if (placementFilter && node.placement !== placementFilter) return false
      if (archiveFilter && archiveStateForNode(node) !== archiveFilter) return false
      if (stalenessFilter && node.staleness_status !== stalenessFilter) return false
      if (syncFilter && node.sync_status !== syncFilter) return false
      if (generatedFilter && (node.generated_metadata_state ?? node.summary_status) !== generatedFilter) return false
      if (specialFilter === 'pinned' && !(pinnedPaths.has(node.path) || node.pinned)) return false
      if (specialFilter === 'needs_review' && !needsReview(node)) return false
      if (!q) return true
      return (
        node.title.toLowerCase().includes(q) ||
        node.path.toLowerCase().includes(q) ||
        sourceLabel(node.source_type).toLowerCase().includes(q) ||
        (node.category ?? '').toLowerCase().includes(q) ||
        folderForNode(node).toLowerCase().includes(q) ||
        (node.status ?? '').toLowerCase().includes(q) ||
        (node.placement ?? '').toLowerCase().includes(q) ||
        (node.staleness_status ?? '').toLowerCase().includes(q) ||
        (node.sync_status ?? '').toLowerCase().includes(q) ||
        (node.generated_metadata_state ?? '').toLowerCase().includes(q) ||
        (node.summary_status ?? '').toLowerCase().includes(q) ||
        allTagsForNode(node).some((tag) => tag.toLowerCase().includes(q)) ||
        (node.note_type ?? '').toLowerCase().includes(q) ||
        (node.generated_summary ?? '').toLowerCase().includes(q) ||
        (node.stale_reasons ?? []).some((reason) => reason.toLowerCase().includes(q)) ||
        (node.owner_notes ?? []).some((path) => path.toLowerCase().includes(q)) ||
        (node.decisions ?? []).some((decision) => decision.toLowerCase().includes(q)) ||
        (node.open_questions ?? []).some((question) => question.toLowerCase().includes(q))
      )
    })
    return [...list].sort((a, b) => a.title.localeCompare(b.title))
  }, [
    archiveFilter,
    categoryFilter,
    folderFilter,
    generatedFilter,
    pinnedPaths,
    placementFilter,
    query,
    sourceFilter,
    specialFilter,
    state,
    statusFilter,
    stalenessFilter,
    syncFilter,
    tagFilter,
  ])

  const selectedNode = useMemo(() => {
    if (state.kind !== 'loaded' || !selectedPath) return null
    return state.graph.nodes.find((node) => node.path === selectedPath) ?? null
  }, [selectedPath, state])

  const listNodes = useMemo(() => nodes.slice(0, MAX_LIST_NODES), [nodes])

  const selectedRelations = useMemo(() => {
    if (state.kind !== 'loaded' || !selectedNode) return { incoming: [], outgoing: [] } as {
      incoming: Array<{ edge: string; node: VaultNode }>
      outgoing: Array<{ edge: string; node: VaultNode }>
    }
    const keys = new Set([selectedNode.id, selectedNode.path])
    const byIdOrPath = new Map<string, VaultNode>()
    for (const node of state.graph.nodes) {
      byIdOrPath.set(node.id, node)
      byIdOrPath.set(node.path, node)
    }
    const incoming: Array<{ edge: string; node: VaultNode }> = []
    const outgoing: Array<{ edge: string; node: VaultNode }> = []
    for (const edge of state.graph.edges) {
      if (keys.has(edge.from)) {
        const node = byIdOrPath.get(edge.to)
        if (node) outgoing.push({ edge: edge.kind, node })
      }
      if (keys.has(edge.to)) {
        const node = byIdOrPath.get(edge.from)
        if (node) incoming.push({ edge: edge.kind, node })
      }
    }
    return {
      incoming: incoming.slice(0, 12),
      outgoing: outgoing.slice(0, 12),
    }
  }, [selectedNode, state])

  const pinSelected = useCallback(() => {
    if (!selectedPath || !onPinToContext) return
    if (note?.path === selectedPath) onPinToContext([note])
    else onPinToContext([selectedPath])
  }, [note, onPinToContext, selectedPath])

  const toggleExclusion = useCallback(async (path: string) => {
    const exists = excludedPaths.has(path)
    setExclusions((current) =>
      exists ? current.filter((item) => item.path !== path) : [...current, { id: path, path }]
    )
    try {
      if (exists) await api.deleteVaultPolicyExclusion(path)
      else await api.createVaultPolicyExclusion(path, 'Excluded from composer vault context')
    } catch {
      setMetadataStatus('degraded')
    }
  }, [excludedPaths])

  const applyProposal = useCallback(async (proposalId: string) => {
    setProposals((current) =>
      current.map((proposal) =>
        proposal.id === proposalId ? { ...proposal, status: 'running' } : proposal
      )
    )
    try {
      await api.runVaultMaintenanceProposal(proposalId)
      setProposals((current) =>
        current.map((proposal) =>
          proposal.id === proposalId ? { ...proposal, status: 'applied' } : proposal
        )
      )
      await load()
    } catch {
      setProposals((current) =>
        current.map((proposal) =>
          proposal.id === proposalId ? { ...proposal, status: 'error' } : proposal
        )
      )
      setMetadataStatus('degraded')
    }
  }, [load])

  const previewProposalDiff = useCallback(async (proposalId: string) => {
    setProposalDiffs((current) => ({ ...current, [proposalId]: { error: 'Loading diff...' } }))
    try {
      const diff = await api.previewVaultMaintenanceProposalDiff(proposalId)
      setProposalDiffs((current) => ({ ...current, [proposalId]: diff }))
    } catch (err) {
      setProposalDiffs((current) => ({
        ...current,
        [proposalId]: { error: err instanceof Error ? err.message : 'Diff unavailable' },
      }))
      setMetadataStatus('degraded')
    }
  }, [])

  const rejectProposal = useCallback(async (proposalId: string) => {
    setProposals((current) =>
      current.map((proposal) =>
        proposal.id === proposalId ? { ...proposal, status: 'running' } : proposal
      )
    )
    try {
      await api.rejectVaultMaintenanceProposal(proposalId)
      setProposals((current) =>
        current.map((proposal) =>
          proposal.id === proposalId ? { ...proposal, status: 'rejected' } : proposal
        )
      )
      await load()
    } catch {
      setProposals((current) =>
        current.map((proposal) =>
          proposal.id === proposalId ? { ...proposal, status: 'error' } : proposal
        )
      )
      setMetadataStatus('degraded')
    }
  }, [load])

  const revertProposal = useCallback(async (proposalId: string) => {
    setProposals((current) =>
      current.map((proposal) =>
        proposal.id === proposalId ? { ...proposal, status: 'running' } : proposal
      )
    )
    try {
      await api.revertVaultMaintenanceProposal(proposalId)
      setProposals((current) =>
        current.map((proposal) =>
          proposal.id === proposalId ? { ...proposal, status: 'reverted' } : proposal
        )
      )
      await load()
    } catch {
      setProposals((current) =>
        current.map((proposal) =>
          proposal.id === proposalId ? { ...proposal, status: 'error' } : proposal
        )
      )
      setMetadataStatus('degraded')
    }
  }, [load])

  const refreshGeneratedMetadata = useCallback(async () => {
    setMetadataStatus('loading')
    try {
      const [statusResult, batchResult, relationResult] = await Promise.all([
        api.getVaultEnrichmentStatus().catch((err) => err),
        api.getVaultEnrichmentBatchStatus().catch((err) => err),
        api.listVaultGeneratedRelations().catch((err) => err),
      ])
      if (!(statusResult instanceof Error)) setEnrichmentStatus(statusResult)
      if (!(batchResult instanceof Error)) setBatchStatus(batchResult)
      if (!(relationResult instanceof Error)) setRelations(normalizeRelations(relationResult))
      setMetadataStatus(
        statusResult instanceof Error || batchResult instanceof Error || relationResult instanceof Error
          ? 'degraded'
          : 'idle'
      )
    } catch {
      setMetadataStatus('degraded')
    }
  }, [])

  const startEnrichmentBatch = useCallback(async () => {
    setEnrichmentBusy(true)
    setMetadataStatus('loading')
    try {
      const result = await api.startVaultEnrichmentBatch({
        limit: 12,
        create_proposals: true,
      })
      setBatchStatus(result)
      await refreshGeneratedMetadata()
    } catch {
      setMetadataStatus('degraded')
    } finally {
      setEnrichmentBusy(false)
    }
  }, [refreshGeneratedMetadata])

  const setRelationDecision = useCallback(async (
    relation: VaultGeneratedRelation,
    decision: RelationDecision
  ) => {
    setRelationBusy((current) => ({ ...current, [relation.key]: decision }))
    try {
      const result = await api.setVaultGeneratedRelationFeedback({
        from_path: relation.from_path,
        to_path: relation.to_path,
        relation_type: relation.relation_type,
        decision,
      })
      setRelations(normalizeRelations(result))
      await load()
    } catch {
      setMetadataStatus('degraded')
    } finally {
      setRelationBusy((current) => {
        const next = { ...current }
        delete next[relation.key]
        return next
      })
    }
  }, [load])

  const initStructuredFolder = useCallback(async () => {
    const name = newFolderName.trim()
    if (!name) {
      setFolderInitStatus('error')
      setFolderInitMessage('Name required')
      return
    }
    setFolderInitStatus('running')
    setFolderInitMessage(null)
    try {
      const result = await api.initVaultFolder(newFolderKind, name)
      setFolderInitStatus('done')
      setFolderInitMessage(
        result.changed_paths?.length
          ? `${result.changed_paths.length} paths updated`
          : result.message ?? result.status ?? 'Folder initialized'
      )
      setNewFolderName('')
      await load()
    } catch (err) {
      setFolderInitStatus('error')
      setFolderInitMessage(err instanceof Error ? err.message : 'Folder initialization failed')
      setMetadataStatus('degraded')
    }
  }, [load, newFolderKind, newFolderName])

  const handleQuery = useCallback((value: string) => {
    startTransition(() => setQuery(value))
  }, [])

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex flex-col gap-2 border-b border-white/[0.05] p-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-[10px] font-mono text-[#555555]">
            <Network size={11} style={{ color: 'var(--accent-blue)' }} />
            <span>
              {state.kind === 'loaded'
                ? `${state.graph.nodes.length} nodes · ${state.graph.edges.length} links`
                : 'vault index'}
            </span>
            {state.kind === 'loaded' && state.graph.index?.workspace_bundle_count ? (
              <span>{state.graph.index.workspace_bundle_count} docs</span>
            ) : null}
            {state.kind === 'loaded' && state.graph.index?.stale && (
              <span className="text-[var(--accent-pink)]">stale</span>
            )}
            {metadataStatus === 'degraded' && (
              <span className="text-[var(--accent-pink)]">partial</span>
            )}
            {relationCounts.candidate > 0 && (
              <span className="text-[var(--accent-blue)]">{relationCounts.candidate} relation candidates</span>
            )}
            {batchStatus?.running && (
              <span className="text-[var(--accent-green)]">enriching</span>
            )}
          </div>
          <button
            onClick={load}
            className="rounded p-1 text-[#555555] transition-colors hover:text-[var(--accent-blue)]"
            title="Reload vault data"
            aria-label="Reload vault data"
          >
            <RefreshCw
              size={12}
              className={cn((state.kind === 'loading' || metadataStatus === 'loading') && 'animate-spin')}
            />
          </button>
        </div>

        <div className="flex gap-1 overflow-x-auto scrollbar-none">
          <TabButton active={tab === 'graph'} icon={<Network size={10} />} label="Graph" onClick={() => setTab('graph')} />
          <TabButton active={tab === 'list'} icon={<FileText size={10} />} label="List" onClick={() => setTab('list')} />
          <TabButton active={tab === 'preview'} icon={<Layers size={10} />} label="Preview" onClick={() => setTab('preview')} />
          <TabButton active={tab === 'review'} icon={<GitBranch size={10} />} label="Review" onClick={() => setTab('review')} />
          <TabButton active={tab === 'maintenance'} icon={<Wrench size={10} />} label="Maint" onClick={() => setTab('maintenance')} />
          <TabButton active={tab === 'atlas'} icon={<Sparkles size={10} />} label="Atlas" onClick={() => setTab('atlas')} />
        </div>
      </div>

      {state.kind === 'loading' && (
        <p className="py-6 text-center text-xs font-mono text-[#555555]">Loading vault graph...</p>
      )}

      {state.kind === 'error' && (
        <div className="m-4 flex flex-col gap-2 rounded-md border border-white/[0.07] bg-[#0d0d0d] p-3">
          <div className="flex items-center gap-2">
            <AlertCircle size={12} style={{ color: 'var(--accent-pink)' }} />
            <span className="text-xs font-mono text-[var(--accent-pink)]">
              Vault endpoints unavailable
            </span>
          </div>
          <p className="text-[10px] font-mono leading-relaxed text-[#888888]">
            Backend returned{state.status != null ? ` ${state.status}` : ' a network error'}: {state.message}
          </p>
        </div>
      )}

      {state.kind === 'loaded' && (
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden p-3">
          {(tab === 'graph' || tab === 'list') && (
            <>
              <div className="flex items-center gap-1.5 rounded-md border border-white/[0.07] bg-[#0d0d0d] px-2 py-1.5">
                <Search size={11} className={cn('text-[#555555]', isPending && 'animate-pulse')} />
                <input
                  value={query}
                  onChange={(event) => handleQuery(event.target.value)}
                  placeholder="Filter notes, paths, tags"
                  className="min-w-0 flex-1 bg-transparent text-[11px] font-mono text-[#cccccc] outline-none placeholder:text-[#444444]"
                />
              </div>

              <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-white/[0.04] bg-[#080808] p-2">
                <div className="flex flex-wrap items-center gap-1">
                  <FilterChip
                    active={
                      !sourceFilter &&
                      !tagFilter &&
                      !folderFilter &&
                      !categoryFilter &&
                      !statusFilter &&
                      !placementFilter &&
                      !archiveFilter &&
                      !stalenessFilter &&
                      !syncFilter &&
                      !generatedFilter &&
                      !specialFilter
                    }
                    label="all"
                    count={state.graph.nodes.length}
                    onClick={clearGraphFilters}
                  />
                  <FilterChip
                    active={specialFilter === 'pinned'}
                    label="pinned"
                    count={state.graph.nodes.filter((node) => pinnedPaths.has(node.path) || node.pinned).length}
                    onClick={() => setSpecialFilter(specialFilter === 'pinned' ? null : 'pinned')}
                  />
                  <FilterChip
                    active={specialFilter === 'needs_review'}
                    label="needs review"
                    count={state.graph.nodes.filter(needsReview).length}
                    onClick={() => setSpecialFilter(specialFilter === 'needs_review' ? null : 'needs_review')}
                  />
                </div>
                <FilterGroup label="source" values={sourceCounts.map(([source, count]) => [sourceLabel(source), count])} selected={sourceFilter ? sourceLabel(sourceFilter) : null} onSelect={(value) => {
                  const match = sourceCounts.find(([source]) => sourceLabel(source) === value)?.[0] ?? null
                  setSourceFilter(match)
                }} />
                <FilterGroup label="folder" values={folderCounts} selected={folderFilter} onSelect={setFolderFilter} limit={12} />
                <FilterGroup label="category" values={categoryCounts} selected={categoryFilter} onSelect={setCategoryFilter} />
                <FilterGroup label="status" values={statusCounts} selected={statusFilter} onSelect={setStatusFilter} />
                <FilterGroup label="placement" values={placementCounts} selected={placementFilter} onSelect={setPlacementFilter} />
                <FilterGroup label="archive" values={archiveCounts} selected={archiveFilter} onSelect={setArchiveFilter} />
                <FilterGroup label="stale" values={stalenessCounts} selected={stalenessFilter} onSelect={setStalenessFilter} />
                <FilterGroup label="sync" values={syncCounts} selected={syncFilter} onSelect={setSyncFilter} />
                <FilterGroup label="generated" values={generatedCounts} selected={generatedFilter} onSelect={setGeneratedFilter} />
                <div className="flex min-w-0 items-center gap-1">
                  <span className="flex-shrink-0 text-[9px] font-mono text-[#444444]">tag</span>
                  <div className="flex min-w-0 flex-wrap gap-1">
                    {tagCounts.slice(0, 36).map(([tag, count]) => (
                      <FilterChip
                        key={tag}
                        active={tagFilter === tag}
                        label={tag}
                        count={count}
                        onClick={() => setTagFilter(tag === tagFilter ? null : tag)}
                      />
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}

          {tab === 'graph' && (
            <VaultGraphCanvas
              nodes={nodes}
              edges={state.graph.edges}
              selectedPath={selectedPath}
              onSelect={loadNote}
            />
          )}

          {tab === 'list' && (
            <div className="min-h-0 flex-1 overflow-y-auto rounded-md border border-white/[0.05] bg-[#0a0a0a] p-1">
              {nodes.length === 0 ? (
                <p className="py-4 text-center text-[11px] font-mono text-[#3a3a3a]">
                  No notes match the current filters
                </p>
              ) : (
                <>
                {nodes.length > MAX_LIST_NODES && (
                  <div className="px-2 py-1.5 text-[9px] font-mono text-[#444444]">
                    showing {MAX_LIST_NODES} / {nodes.length}
                  </div>
                )}
                {listNodes.map((node) => {
                  const isSelected = selectedPath === node.path
                  return (
                    <div
                      key={node.id}
                      className={cn(
                        'group flex items-start gap-2 rounded px-2 py-1.5 transition-colors',
                        isSelected ? 'bg-[var(--accent-blue)]/15 text-white' : 'text-[#cccccc] hover:bg-white/[0.04]'
                      )}
                    >
                      <button
                        onClick={() => loadNote(node.path)}
                        className="flex min-w-0 flex-1 items-start gap-2 text-left"
                      >
                        <FileText size={11} className="mt-0.5 flex-shrink-0 text-[#666666]" />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-[11px] font-mono">{node.title}</span>
                          <span className="block truncate text-[9px] font-mono text-[#555555]">
                            {sourceLabel(node.source_type)} · {node.path}
                          </span>
                          {(node.status || node.placement || node.staleness_status || node.sync_status || node.incoming_link_count != null) && (
                            <span className="block truncate text-[9px] font-mono text-[#444444]">
                              {[
                                node.status,
                                node.placement,
                                node.staleness_status,
                                node.sync_status && node.sync_status !== 'ok' ? node.sync_status : null,
                                node.incoming_link_count != null ? `${node.incoming_link_count} in` : null,
                              ].filter(Boolean).join(' / ')}
                            </span>
                          )}
                        </span>
                      </button>
                      <button
                        onClick={() => onPinToContext?.([node.path])}
                        className={cn(
                          'rounded p-1 transition-colors',
                          pinnedPaths.has(node.path)
                            ? 'text-[var(--accent-green)]'
                            : 'text-[#555555] hover:text-[var(--accent-blue)]'
                        )}
                        title={pinnedPaths.has(node.path) ? 'Pinned to composer context' : 'Pin to composer context'}
                        aria-label={`Pin ${node.title}`}
                      >
                        {pinnedPaths.has(node.path) ? <Check size={11} /> : <Pin size={11} />}
                      </button>
                      <button
                        onClick={() => toggleExclusion(node.path)}
                        className={cn(
                          'rounded p-1 transition-colors',
                          excludedPaths.has(node.path)
                            ? 'text-[var(--accent-pink)]'
                            : 'text-[#555555] hover:text-[var(--accent-pink)]'
                        )}
                        title={excludedPaths.has(node.path) ? 'Remove policy exclusion' : 'Exclude from vault context'}
                        aria-label={`Toggle policy exclusion for ${node.title}`}
                      >
                        <ShieldOff size={11} />
                      </button>
                    </div>
                  )
                })}
                </>
              )}
            </div>
          )}

          {tab === 'preview' && (
            <div className="min-h-0 flex-1 overflow-hidden rounded-md border border-white/[0.07] bg-[#0d0d0d]">
              {!selectedPath ? (
                <div className="flex h-full items-center justify-center p-6 text-center text-[11px] font-mono text-[#555555]">
                  Select a note from the graph or list.
                </div>
              ) : (
                <div className="flex h-full flex-col">
                  <div className="flex items-center justify-between gap-2 border-b border-white/[0.06] px-3 py-2">
                    <div className="min-w-0">
                      <p className="truncate text-xs font-mono text-[#d8d8d8]">
                        {note?.title ?? selectedNode?.title ?? titleFromPath(selectedPath)}
                      </p>
                      <p className="truncate text-[9px] font-mono text-[#555555]">{selectedPath}</p>
                      {selectedNode && (
                        <p className="truncate text-[9px] font-mono text-[#444444]">
                          {sourceLabel(selectedNode.source_type)}
                          {selectedNode.status ? ` / ${selectedNode.status}` : ''}
                          {selectedNode.staleness_status ? ` / ${selectedNode.staleness_status}` : ''}
                          {selectedNode.converter ? ` / ${selectedNode.converter}` : ''}
                        </p>
                      )}
                    </div>
                    <div className="flex flex-shrink-0 items-center gap-1">
                      <button
                        onClick={() => void loadNeighborhood(selectedPath, 1)}
                        className="rounded border border-white/[0.08] px-2 py-1 text-[10px] font-mono text-[#777777] hover:text-white"
                        title="Load 1-hop graph neighborhood"
                      >
                        1-hop
                      </button>
                      <button
                        onClick={() => void loadNeighborhood(selectedPath, 2)}
                        className="rounded border border-white/[0.08] px-2 py-1 text-[10px] font-mono text-[#777777] hover:text-white"
                        title="Load 2-hop graph neighborhood"
                      >
                        2-hop
                      </button>
                      {onPinToContext && conversationId && (
                        <button
                          onClick={pinSelected}
                          className="inline-flex items-center gap-1 rounded border border-[var(--accent-blue)]/40 px-2 py-1 text-[10px] font-mono text-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/10"
                          title="Pin this note into composer context"
                        >
                          <Link2 size={10} /> Pin
                        </button>
                      )}
                      <button
                        onClick={() => toggleExclusion(selectedPath)}
                        className={cn(
                          'rounded border px-2 py-1 text-[10px] font-mono transition-colors',
                          excludedPaths.has(selectedPath)
                            ? 'border-[var(--accent-pink)]/40 text-[var(--accent-pink)]'
                            : 'border-white/[0.08] text-[#777777] hover:text-[var(--accent-pink)]'
                        )}
                      >
                        Exclude
                      </button>
                    </div>
                  </div>
                  {noteLoading ? (
                    <p className="p-4 text-[11px] font-mono text-[#555555]">Loading note...</p>
                  ) : (
                    <div className="min-h-0 flex-1 overflow-y-auto p-3">
                      {selectedNode?.generated_metadata_state && selectedNode.generated_metadata_state !== 'missing' && (
                        <div className="mb-3 rounded border border-white/[0.06] bg-[#090909] p-2">
                          <div className="mb-1 flex flex-wrap items-center gap-1">
                            <span className="text-[9px] font-mono text-[#555555]">
                              generated metadata: {selectedNode.generated_metadata_state}
                            </span>
                            {selectedNode.note_type && (
                              <span className="rounded border border-white/[0.08] px-1.5 py-0.5 text-[8px] font-mono text-[#777777]">
                                {selectedNode.note_type}
                              </span>
                            )}
                            {(selectedNode.generated_tags ?? []).slice(0, 8).map((tag) => (
                              <span
                                key={tag}
                                className="rounded border border-[var(--accent-blue)]/25 px-1.5 py-0.5 text-[8px] font-mono text-[var(--accent-blue)]"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                          {selectedNode.generated_summary && (
                            <p className="line-clamp-4 text-[10px] font-mono leading-relaxed text-[#888888]">
                              {selectedNode.generated_summary}
                            </p>
                          )}
                          {(selectedNode.stale_reasons?.length || selectedNode.relation_candidate_count || selectedNode.open_questions?.length) ? (
                            <div className="mt-2 flex flex-wrap gap-1">
                              {selectedNode.stale_reasons?.slice(0, 5).map((reason) => (
                                <span
                                  key={reason}
                                  className="rounded border border-[var(--accent-pink)]/25 px-1.5 py-0.5 text-[8px] font-mono text-[var(--accent-pink)]"
                                >
                                  {reason}
                                </span>
                              ))}
                              {selectedNode.relation_candidate_count ? (
                                <span className="rounded border border-white/[0.08] px-1.5 py-0.5 text-[8px] font-mono text-[#777777]">
                                  {selectedNode.relation_candidate_count} relation candidates
                                </span>
                              ) : null}
                              {selectedNode.open_questions?.length ? (
                                <span className="rounded border border-white/[0.08] px-1.5 py-0.5 text-[8px] font-mono text-[#777777]">
                                  {selectedNode.open_questions.length} open questions
                                </span>
                              ) : null}
                            </div>
                          ) : null}
                          {(selectedNode.owner_notes?.length || selectedNode.duplicate_candidates?.length) ? (
                            <div className="mt-2 grid gap-1 border-t border-white/[0.05] pt-2">
                              {selectedNode.owner_notes?.slice(0, 5).map((path) => (
                                <button
                                  key={`owner-${path}`}
                                  onClick={() => loadNote(path)}
                                  className="flex min-w-0 items-center gap-2 rounded bg-[#070707] px-2 py-1 text-left text-[9px] font-mono text-[#888888] hover:text-white"
                                  title={path}
                                >
                                  <span className="flex-shrink-0 text-[#444444]">owner</span>
                                  <span className="min-w-0 flex-1 truncate">{titleFromPath(path)}</span>
                                </button>
                              ))}
                              {selectedNode.duplicate_candidates?.slice(0, 5).map((candidate, index) => {
                                const path = candidatePath(candidate)
                                const label = candidateLabel(candidate)
                                if (!path || !label) return null
                                return (
                                  <button
                                    key={`duplicate-${path}-${index}`}
                                    onClick={() => loadNote(path)}
                                    className="flex min-w-0 items-center gap-2 rounded bg-[#070707] px-2 py-1 text-left text-[9px] font-mono text-[#888888] hover:text-white"
                                    title={path}
                                  >
                                    <span className="flex-shrink-0 text-[#444444]">duplicate</span>
                                    <span className="min-w-0 flex-1 truncate">{label}</span>
                                  </button>
                                )
                              })}
                            </div>
                          ) : null}
                          {(selectedNode.decisions?.length || selectedNode.open_questions?.length) ? (
                            <div className="mt-2 grid gap-1 border-t border-white/[0.05] pt-2">
                              {selectedNode.decisions?.slice(0, 4).map((decision, index) => (
                                <p key={`decision-${index}`} className="line-clamp-2 text-[9px] font-mono leading-relaxed text-[#777777]">
                                  decision: {decision}
                                </p>
                              ))}
                              {selectedNode.open_questions?.slice(0, 4).map((question, index) => (
                                <p key={`question-${index}`} className="line-clamp-2 text-[9px] font-mono leading-relaxed text-[#666666]">
                                  question: {question}
                                </p>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      )}
                      <pre className="whitespace-pre-wrap break-words text-[11px] font-mono leading-relaxed text-[#999999]">
                        {note?.content || 'Preview unavailable.'}
                      </pre>
                      {note?.backlinks?.length ? (
                        <div className="mt-3 border-t border-white/[0.06] pt-2 text-[9px] font-mono text-[#555555]">
                          backlinks: {note.backlinks.slice(0, 8).join(', ')}
                          {note.backlinks.length > 8 && ` +${note.backlinks.length - 8}`}
                        </div>
                      ) : null}
                      {(selectedRelations.incoming.length > 0 || selectedRelations.outgoing.length > 0) && (
                        <div className="mt-3 grid gap-2 border-t border-white/[0.06] pt-2">
                          {selectedRelations.outgoing.length > 0 && (
                            <div>
                              <p className="mb-1 text-[9px] font-mono text-[#555555]">outlinks</p>
                              <div className="space-y-1">
                                {selectedRelations.outgoing.map(({ edge, node }) => (
                                  <button
                                    key={`out-${edge}-${node.path}`}
                                    onClick={() => loadNote(node.path)}
                                    className="flex w-full items-center gap-2 rounded bg-[#090909] px-2 py-1 text-left hover:bg-white/[0.04]"
                                  >
                                    <span className="min-w-0 flex-1 truncate text-[10px] font-mono text-[#aaaaaa]">{node.title}</span>
                                    <span className="flex-shrink-0 text-[8px] font-mono text-[#444444]">{edge}</span>
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                          {selectedRelations.incoming.length > 0 && (
                            <div>
                              <p className="mb-1 text-[9px] font-mono text-[#555555]">inlinks</p>
                              <div className="space-y-1">
                                {selectedRelations.incoming.map(({ edge, node }) => (
                                  <button
                                    key={`in-${edge}-${node.path}`}
                                    onClick={() => loadNote(node.path)}
                                    className="flex w-full items-center gap-2 rounded bg-[#090909] px-2 py-1 text-left hover:bg-white/[0.04]"
                                  >
                                    <span className="min-w-0 flex-1 truncate text-[10px] font-mono text-[#aaaaaa]">{node.title}</span>
                                    <span className="flex-shrink-0 text-[8px] font-mono text-[#444444]">{edge}</span>
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      )}
                      {(neighborhoodStatus !== 'idle' || neighborhood) && (
                        <div className="mt-3 border-t border-white/[0.06] pt-2">
                          <div className="mb-1 flex items-center justify-between gap-2">
                            <p className="text-[9px] font-mono text-[#555555]">
                              neighborhood{neighborhood?.hops ? ` / ${neighborhood.hops} hop` : ''}
                            </p>
                            {neighborhood?.omitted && (
                              <p className="text-[8px] font-mono text-[#444444]">
                                omitted {[
                                  neighborhood.omitted.nodes ? `${neighborhood.omitted.nodes} nodes` : null,
                                  neighborhood.omitted.edges ? `${neighborhood.omitted.edges} links` : null,
                                  neighborhood.omitted.policy ? `${neighborhood.omitted.policy} policy` : null,
                                ].filter(Boolean).join(' / ')}
                              </p>
                            )}
                          </div>
                          {neighborhoodStatus === 'loading' && (
                            <p className="text-[10px] font-mono text-[#555555]">Loading neighborhood...</p>
                          )}
                          {neighborhoodStatus === 'error' && (
                            <p className="text-[10px] font-mono text-[var(--accent-pink)]">Neighborhood unavailable.</p>
                          )}
                          {neighborhood && neighborhood.nodes.length > 0 && (
                            <div className="grid gap-1">
                              {neighborhood.nodes
                                .filter((node) => node.path !== selectedPath)
                                .slice(0, 16)
                                .map((node) => (
                                  <div key={`neighbor-${node.id}`} className="flex items-center gap-1 rounded bg-[#090909] px-2 py-1">
                                    <button
                                      onClick={() => loadNote(node.path)}
                                      className="min-w-0 flex-1 truncate text-left text-[10px] font-mono text-[#aaaaaa] hover:text-white"
                                    >
                                      {node.title}
                                    </button>
                                    <button
                                      onClick={() => onPinToContext?.([node.path])}
                                      className={cn(
                                        'rounded p-0.5',
                                        pinnedPaths.has(node.path) ? 'text-[var(--accent-green)]' : 'text-[#555555] hover:text-[var(--accent-blue)]'
                                      )}
                                      title="Pin neighbor to composer context"
                                      aria-label={`Pin ${node.title}`}
                                    >
                                      {pinnedPaths.has(node.path) ? <Check size={10} /> : <Pin size={10} />}
                                    </button>
                                  </div>
                                ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {tab === 'review' && (
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
              <section className="rounded-md border border-white/[0.07] bg-[#0d0d0d] p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2 text-[10px] font-mono text-[#777777]">
                    <Sparkles size={11} style={{ color: 'var(--accent-blue)' }} />
                    generated metadata
                  </div>
                  <div className="flex flex-shrink-0 items-center gap-1">
                    <button
                      type="button"
                      onClick={() => void refreshGeneratedMetadata()}
                      className="rounded p-1 text-[#555555] transition-colors hover:text-[var(--accent-blue)]"
                      title="Refresh generated metadata status"
                      aria-label="Refresh generated metadata status"
                    >
                      <RefreshCw
                        size={11}
                        className={cn(metadataStatus === 'loading' && 'animate-spin')}
                      />
                    </button>
                    <button
                      type="button"
                      onClick={() => void startEnrichmentBatch()}
                      disabled={enrichmentBusy || batchStatus?.running}
                      className="inline-flex items-center gap-1 rounded border border-[var(--accent-blue)]/35 px-2 py-1 text-[9px] font-mono text-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/10 disabled:opacity-50"
                    >
                      <Play size={9} />
                      {batchStatus?.running ? 'running' : 'batch'}
                    </button>
                  </div>
                </div>
                <div className="mb-2 flex flex-wrap gap-1">
                  {Object.entries(enrichmentStatus?.counts ?? {}).map(([key, value]) => (
                    <span
                      key={key}
                      className="rounded border border-white/[0.08] px-1.5 py-0.5 text-[9px] font-mono text-[#777777]"
                    >
                      {key} {value}
                    </span>
                  ))}
                  {batchStatus && (
                    <span
                      className={cn(
                        'rounded border px-1.5 py-0.5 text-[9px] font-mono',
                        batchStatus.status.includes('error') || batchStatus.status === 'failed'
                          ? 'border-[var(--accent-pink)]/35 text-[var(--accent-pink)]'
                          : batchStatus.running
                            ? 'border-[var(--accent-green)]/35 text-[var(--accent-green)]'
                            : 'border-white/[0.08] text-[#777777]'
                      )}
                    >
                      {batchStatus.status}
                    </span>
                  )}
                </div>
                {batchStatus?.error && (
                  <p className="mb-2 line-clamp-2 text-[9px] font-mono leading-relaxed text-[var(--accent-pink)]">
                    {batchStatus.error}
                  </p>
                )}
                {batchStatus?.result && (
                  <p className="mb-2 text-[9px] font-mono text-[#555555]">
                    processed {batchStatus.result.processed.length} / skipped {batchStatus.result.skipped.length} / errors {batchStatus.result.errors.length}
                  </p>
                )}
                {enrichmentStatus?.next_candidates?.length ? (
                  <div className="grid gap-1">
                    {enrichmentStatus.next_candidates.slice(0, 8).map((candidate) => (
                      <button
                        key={candidate.path}
                        type="button"
                        onClick={() => loadNote(candidate.path)}
                        className="flex min-w-0 items-center gap-2 rounded bg-[#090909] px-2 py-1 text-left hover:bg-white/[0.04]"
                      >
                        <span className="min-w-0 flex-1 truncate text-[10px] font-mono text-[#aaaaaa]">
                          {candidate.title}
                        </span>
                        <span className="flex-shrink-0 text-[8px] font-mono text-[#444444]">
                          {candidate.state} / {candidate.staleness_status}
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <p className="text-[10px] font-mono text-[#444444]">No enrichment candidates reported.</p>
                )}
              </section>

              <section className="rounded-md border border-white/[0.07] bg-[#0d0d0d] p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-[10px] font-mono text-[#777777]">
                    <GitBranch size={11} style={{ color: 'var(--accent-green)' }} />
                    relation candidates
                  </div>
                  <div className="flex flex-wrap justify-end gap-1">
                    <span className="rounded border border-white/[0.08] px-1.5 py-0.5 text-[8px] font-mono text-[#777777]">
                      candidate {relationCounts.candidate}
                    </span>
                    <span className="rounded border border-[var(--accent-green)]/25 px-1.5 py-0.5 text-[8px] font-mono text-[var(--accent-green)]">
                      accepted {relationCounts.accepted}
                    </span>
                    <span className="rounded border border-[var(--accent-pink)]/25 px-1.5 py-0.5 text-[8px] font-mono text-[var(--accent-pink)]">
                      rejected {relationCounts.rejected}
                    </span>
                  </div>
                </div>
                {relations.length === 0 ? (
                  <p className="text-[10px] font-mono text-[#444444]">No generated relations reported.</p>
                ) : (
                  <div className="space-y-2">
                    {relations.slice(0, 80).map((relation) => {
                      const busy = relationBusy[relation.key]
                      return (
                        <div key={relation.key} className="rounded border border-white/[0.06] bg-[#090909] p-2">
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0">
                              <p className="truncate text-[10px] font-mono text-[#cccccc]">
                                {relationLabel(relation.from_path, nodesByPath)}{' -> '}{relationLabel(relation.to_path, nodesByPath)}
                              </p>
                              <p className="mt-0.5 truncate text-[8px] font-mono text-[#444444]">
                                {relation.relation_type}
                                {relation.confidence != null ? ` / ${(relation.confidence * 100).toFixed(0)}%` : ''}
                              </p>
                            </div>
                            <span
                              className={cn(
                                'flex-shrink-0 rounded border px-1.5 py-0.5 text-[8px] font-mono',
                                relation.decision === 'accepted'
                                  ? 'border-[var(--accent-green)]/35 text-[var(--accent-green)]'
                                  : relation.decision === 'rejected'
                                    ? 'border-[var(--accent-pink)]/35 text-[var(--accent-pink)]'
                                    : 'border-white/[0.08] text-[#777777]'
                              )}
                            >
                              {relation.decision}
                            </span>
                          </div>
                          {relation.reason && (
                            <p className="mt-1 line-clamp-2 text-[9px] font-mono leading-relaxed text-[#666666]">
                              {relation.reason}
                            </p>
                          )}
                          <div className="mt-2 flex flex-wrap gap-1">
                            <button
                              type="button"
                              onClick={() => loadNote(relation.from_path)}
                              className="rounded border border-white/[0.08] px-2 py-1 text-[9px] font-mono text-[#777777] hover:text-white"
                            >
                              source
                            </button>
                            <button
                              type="button"
                              onClick={() => loadNote(relation.to_path)}
                              className="rounded border border-white/[0.08] px-2 py-1 text-[9px] font-mono text-[#777777] hover:text-white"
                            >
                              target
                            </button>
                            <button
                              type="button"
                              onClick={() => void setRelationDecision(relation, 'accepted')}
                              disabled={Boolean(busy) || relation.decision === 'accepted'}
                              className="inline-flex items-center gap-1 rounded border border-[var(--accent-green)]/30 px-2 py-1 text-[9px] font-mono text-[var(--accent-green)] hover:bg-[var(--accent-green)]/10 disabled:opacity-50"
                            >
                              <Check size={9} />
                              {busy === 'accepted' ? 'saving' : 'accept'}
                            </button>
                            <button
                              type="button"
                              onClick={() => void setRelationDecision(relation, 'rejected')}
                              disabled={Boolean(busy) || relation.decision === 'rejected'}
                              className="inline-flex items-center gap-1 rounded border border-white/[0.08] px-2 py-1 text-[9px] font-mono text-[#777777] hover:text-[var(--accent-pink)] disabled:opacity-50"
                            >
                              <X size={9} />
                              {busy === 'rejected' ? 'saving' : 'reject'}
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </section>
            </div>
          )}

          {tab === 'maintenance' && (
            <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">
              <section className="rounded-md border border-white/[0.07] bg-[#0d0d0d] p-3">
                <div className="mb-2 flex items-center gap-2 text-[10px] font-mono text-[#777777]">
                  <FolderPlus size={11} style={{ color: 'var(--accent-green)' }} />
                  new structured folder
                </div>
                <div className="mb-2 flex flex-wrap gap-1">
                  {(['project', 'course', 'reference'] as VaultFolderKind[]).map((kind) => (
                    <button
                      key={kind}
                      type="button"
                      onClick={() => setNewFolderKind(kind)}
                      className={cn(
                        'rounded border px-1.5 py-0.5 text-[9px] font-mono',
                        newFolderKind === kind
                          ? 'border-[var(--accent-green)]/40 bg-[var(--accent-green)]/10 text-[var(--accent-green)]'
                          : 'border-white/[0.08] text-[#888888] hover:border-white/20 hover:text-white'
                      )}
                    >
                      {kind}
                    </button>
                  ))}
                </div>
                <div className="flex items-center gap-1.5">
                  <input
                    value={newFolderName}
                    onChange={(event) => setNewFolderName(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') void initStructuredFolder()
                    }}
                    placeholder="Name"
                    className="min-w-0 flex-1 rounded border border-white/[0.07] bg-[#090909] px-2 py-1.5 text-[11px] font-mono text-[#cccccc] outline-none placeholder:text-[#444444] focus:border-[var(--accent-green)]/40"
                  />
                  <button
                    type="button"
                    onClick={() => void initStructuredFolder()}
                    disabled={folderInitStatus === 'running'}
                    className="inline-flex items-center gap-1 rounded border border-[var(--accent-green)]/35 px-2 py-1.5 text-[10px] font-mono text-[var(--accent-green)] hover:bg-[var(--accent-green)]/10 disabled:opacity-50"
                  >
                    <FolderPlus size={10} />
                    {folderInitStatus === 'running' ? 'creating' : 'create'}
                  </button>
                </div>
                {folderInitMessage && (
                  <p
                    className={cn(
                      'mt-2 truncate text-[9px] font-mono',
                      folderInitStatus === 'error' ? 'text-[var(--accent-pink)]' : 'text-[#666666]'
                    )}
                  >
                    {folderInitMessage}
                  </p>
                )}
              </section>

              <section className="rounded-md border border-white/[0.07] bg-[#0d0d0d] p-3">
                <div className="mb-2 flex items-center gap-2 text-[10px] font-mono text-[#777777]">
                  <ShieldOff size={11} style={{ color: 'var(--accent-pink)' }} />
                  policy exclusions
                </div>
                {exclusions.length === 0 ? (
                  <p className="text-[10px] font-mono text-[#444444]">No exclusions reported.</p>
                ) : (
                  <div className="space-y-1">
                    {exclusions.map((item) => (
                      <div key={item.id} className="flex items-center gap-2 rounded bg-[#090909] px-2 py-1">
                        <span className="min-w-0 flex-1 truncate text-[10px] font-mono text-[#aaaaaa]">{item.path}</span>
                        <button
                          onClick={() => toggleExclusion(item.path)}
                          className="text-[9px] font-mono text-[#555555] hover:text-white"
                        >
                          remove
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </section>

              <section className="rounded-md border border-white/[0.07] bg-[#0d0d0d] p-3">
                <div className="mb-2 flex items-center gap-2 text-[10px] font-mono text-[#777777]">
                  <Wrench size={11} style={{ color: 'var(--accent-blue)' }} />
                  maintenance proposals
                </div>
                {proposals.length === 0 ? (
                  <p className="text-[10px] font-mono text-[#444444]">No proposals reported.</p>
                ) : (
                  <div className="space-y-2">
                    {proposals.map((proposal) => (
                      <div key={proposal.id} className="rounded border border-white/[0.06] bg-[#090909] p-2">
                        <div className="flex items-start justify-between gap-2">
                          <div className="min-w-0">
                            <p className="truncate text-[11px] font-mono text-[#cccccc]">{proposal.title}</p>
                            {proposal.summary && (
                              <p className="mt-1 line-clamp-3 text-[10px] font-mono leading-relaxed text-[#777777]">
                                {proposal.summary}
                              </p>
                            )}
                          </div>
                          <span
                            className={cn(
                              'rounded border px-1.5 py-0.5 text-[8px] font-mono',
                              proposal.status === 'applied' || proposal.status === 'reverted'
                                ? 'border-[var(--accent-green)]/35 text-[var(--accent-green)]'
                                : proposal.status === 'rejected' || proposal.status === 'error'
                                  ? 'border-[var(--accent-pink)]/35 text-[var(--accent-pink)]'
                                  : 'border-white/[0.08] text-[#555555]'
                            )}
                          >
                            {proposal.status ?? 'proposed'}
                          </span>
                        </div>
                        {(proposal.kind || proposal.risk || proposal.path) && (
                          <p className="mt-1 truncate text-[9px] font-mono text-[#444444]">
                            {[proposal.kind, proposal.risk, proposal.path].filter(Boolean).join(' / ')}
                          </p>
                        )}
                        <div className="mt-2 flex flex-wrap gap-1">
                          <button
                            onClick={() => void previewProposalDiff(proposal.id)}
                            className="rounded border border-white/[0.08] px-2 py-1 text-[9px] font-mono text-[#777777] hover:text-white"
                          >
                            diff
                          </button>
                          <button
                            onClick={() => void applyProposal(proposal.id)}
                            disabled={proposal.status === 'running' || proposal.status === 'applied' || proposal.status === 'reverted' || proposal.status === 'rejected'}
                            className="rounded border border-[var(--accent-blue)]/30 px-2 py-1 text-[9px] font-mono text-[var(--accent-blue)] hover:bg-[var(--accent-blue)]/10 disabled:opacity-50"
                          >
                            {proposal.status === 'running' ? 'running' : 'apply'}
                          </button>
                          <button
                            onClick={() => void rejectProposal(proposal.id)}
                            disabled={proposal.status === 'running' || proposal.status === 'rejected' || proposal.status === 'applied' || proposal.status === 'reverted'}
                            className="rounded border border-white/[0.08] px-2 py-1 text-[9px] font-mono text-[#777777] hover:text-[var(--accent-pink)] disabled:opacity-50"
                          >
                            reject
                          </button>
                          <button
                            onClick={() => void revertProposal(proposal.id)}
                            disabled={proposal.status !== 'applied'}
                            className="rounded border border-white/[0.08] px-2 py-1 text-[9px] font-mono text-[#777777] hover:text-[var(--accent-green)] disabled:opacity-50"
                          >
                            revert
                          </button>
                        </div>
                        {proposalDiffs[proposal.id] && (() => {
                          const proposalDiff = proposalDiffs[proposal.id]
                          return (
                            <div className="mt-2 rounded border border-white/[0.06] bg-[#050505] p-2">
                              {'error' in proposalDiff ? (
                                <p
                                  className={cn(
                                    'text-[9px] font-mono',
                                    proposalDiff.error === 'Loading diff...'
                                      ? 'text-[#555555]'
                                      : 'text-[var(--accent-pink)]'
                                  )}
                                >
                                  {proposalDiff.error}
                                </p>
                              ) : (
                                <>
                                  <div className="mb-1 flex items-center justify-between gap-2">
                                    <span className={cn(
                                      'text-[9px] font-mono',
                                      proposalDiff.applicable ? 'text-[var(--accent-green)]' : 'text-[var(--accent-pink)]'
                                    )}>
                                      {proposalDiff.applicable ? 'applicable' : 'blocked'}
                                    </span>
                                    {proposalDiff.reason && (
                                      <span className="min-w-0 truncate text-[8px] font-mono text-[#555555]">
                                        {proposalDiff.reason}
                                      </span>
                                    )}
                                  </div>
                                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words text-[9px] font-mono leading-relaxed text-[#888888]">
                                    {proposalDiff.diff || 'No file diff for this proposal.'}
                                  </pre>
                                </>
                              )}
                            </div>
                          )
                        })()}
                      </div>
                    ))}
                  </div>
                )}
              </section>
            </div>
          )}

          {tab === 'atlas' && (
            <div className="flex min-h-0 flex-1 items-center justify-center rounded-md border border-white/[0.07] bg-[#0d0d0d] p-6 text-center">
              <div className="max-w-xs">
                <Sparkles size={18} className="mx-auto mb-2 text-[#555555]" />
                <p className="text-xs font-mono text-[#777777]">Atlas is reserved for the spatial vault map.</p>
                <p className="mt-1 text-[10px] font-mono leading-relaxed text-[#444444]">
                  The current slice keeps the working graph in 2D Cytoscape and leaves Atlas as a placeholder.
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

'use client'

import { useEffect, useMemo, useRef } from 'react'
import type cytoscape from 'cytoscape'
import type { VaultEdge, VaultNode } from '@/lib/types'

interface VaultGraphCanvasProps {
  nodes: VaultNode[]
  edges: VaultEdge[]
  selectedPath: string | null
  onSelect: (path: string) => void
}

const MAX_CANVAS_NODES = 350

export function VaultGraphCanvas({ nodes, edges, selectedPath, onSelect }: VaultGraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<cytoscape.Core | null>(null)
  const onSelectRef = useRef(onSelect)

  onSelectRef.current = onSelect

  const nodeSlice = useMemo(() => nodes.slice(0, MAX_CANVAS_NODES), [nodes])
  const elements = useMemo(() => {
    const visibleIds = new Set(nodeSlice.map((node) => node.id))
    const byId = new Map(nodeSlice.map((node) => [node.id, node]))
    const byPath = new Map(nodeSlice.map((node) => [node.path, node]))
    const graphEdges = edges
      .map((edge, index) => {
        const from = byId.get(edge.from) ?? byPath.get(edge.from)
        const to = byId.get(edge.to) ?? byPath.get(edge.to)
        if (!from || !to || !visibleIds.has(from.id) || !visibleIds.has(to.id)) return null
        return {
          data: {
            id: `edge-${index}-${from.id}-${to.id}`,
            source: from.id,
            target: to.id,
            kind: edge.kind,
          },
        }
      })
      .filter((edge): edge is { data: { id: string; source: string; target: string; kind: string } } => Boolean(edge))

    return [
      ...nodeSlice.map((node) => ({
        data: {
          id: node.id,
          label: node.title || node.path,
          path: node.path,
          tags: node.tags,
          sourceType: node.source_type ?? 'vault_note',
          status: node.status ?? '',
          archiveState: node.archive_state ?? (node.path.toLowerCase().includes('/archive/') ? 'archive' : 'active'),
        },
      })),
      ...graphEdges,
    ]
  }, [edges, nodeSlice])

  useEffect(() => {
    let disposed = false

    async function mount() {
      if (!containerRef.current) return
      const cytoscapeModule = await import('cytoscape')
      if (disposed || !containerRef.current) return
      const cytoscapeFactory = cytoscapeModule.default
      cyRef.current?.destroy()
      const cy = cytoscapeFactory({
        container: containerRef.current,
        elements,
        minZoom: 0.35,
        maxZoom: 2.4,
        style: [
          {
            selector: 'node',
            style: {
              'background-color': '#7eb8da',
              color: '#d8d8d8',
              label: 'data(label)',
              'font-family': 'ui-monospace, SFMono-Regular, Menlo, monospace',
              'font-size': 7,
              'text-max-width': '90px',
              'text-wrap': 'wrap',
              'text-valign': 'bottom',
              'text-margin-y': 5,
              width: 12,
              height: 12,
              'border-width': 1,
              'border-color': 'rgba(255,255,255,0.13)',
            },
          },
          {
            selector: 'node:selected',
            style: {
              'background-color': '#7ec8a0',
              'border-width': 2,
              'border-color': 'rgba(255,255,255,0.67)',
            },
          },
          {
            selector: 'node[sourceType = "workspace_syllabus"]',
            style: {
              'background-color': '#d8b46a',
            },
          },
          {
            selector: 'node[sourceType = "workspace_reference"]',
            style: {
              'background-color': '#b8a0e8',
            },
          },
          {
            selector: 'node[archiveState = "archive"]',
            style: {
              opacity: 0.55,
            },
          },
          {
            selector: 'node[status *= "failed"], node[status *= "conflict"], node[status *= "ocr"], node[status *= "review"]',
            style: {
              'border-width': 2,
              'border-color': 'rgba(255,120,168,0.67)',
            },
          },
          {
            selector: 'edge',
            style: {
              width: 1,
              'line-color': 'rgba(255,255,255,0.09)',
              'target-arrow-color': 'rgba(255,255,255,0.09)',
              'curve-style': 'bezier',
            },
          },
          {
            selector: 'edge[kind = "tag"]',
            style: {
              'line-color': 'rgba(184,160,232,0.2)',
            },
          },
        ],
        layout: {
          name: 'cose',
          animate: false,
          fit: true,
          padding: 24,
          nodeRepulsion: 5200,
          idealEdgeLength: 80,
        },
      })

      cy.on('tap', 'node', (event) => {
        const path = event.target.data('path')
        if (typeof path === 'string') onSelectRef.current(path)
      })
      cyRef.current = cy
    }

    mount()
    return () => {
      disposed = true
      cyRef.current?.destroy()
      cyRef.current = null
    }
  }, [elements])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().unselect()
    if (!selectedPath) return
    const node = cy.nodes().filter((item) => item.data('path') === selectedPath)
    node.select()
    if (node.length) cy.animate({ center: { eles: node }, zoom: Math.max(cy.zoom(), 1.05) }, { duration: 180 })
  }, [selectedPath])

  return (
    <div className="relative h-full min-h-[280px] rounded-md border border-white/[0.06] bg-[#050505] overflow-hidden">
      <div ref={containerRef} className="absolute inset-0" />
      {nodes.length > MAX_CANVAS_NODES && (
        <div className="absolute bottom-2 left-2 rounded border border-white/[0.08] bg-black/70 px-2 py-1 text-[9px] font-mono text-[#777777]">
          showing {MAX_CANVAS_NODES} / {nodes.length}
        </div>
      )}
    </div>
  )
}

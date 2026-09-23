import { useEffect, useState } from 'react'
import { getRouteGraph, getRouteNodes } from '../api/fmsApi'

export type MapPoint = {
  x: number
  y: number
  worldX: number
  worldY: number
}

export type MapEdge = {
  id: string
  from: string
  to: string
}

export type RouteNodeItem = {
  id: string
  label: string
  mapNodeId: string
}

export function useRouteGraph() {
  const [nodes, setNodes] = useState<Record<string, MapPoint>>({})
  const [edges, setEdges] = useState<MapEdge[]>([])
  const [nodeItems, setNodeItems] = useState<RouteNodeItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)

      try {
        const [nodeList, graph] = await Promise.all([getRouteNodes(), getRouteGraph()])
        if (cancelled) return

        const nextNodes: Record<string, MapPoint> = {}
        const nextItems: RouteNodeItem[] = []

        for (const node of nodeList) {
          if (node.pixel_x == null || node.pixel_y == null) continue
          const id = String(node.id)
          nextNodes[id] = {
            x: Number(node.pixel_x),
            y: Number(node.pixel_y),
            worldX: Number(node.x),
            worldY: Number(node.y),
          }
          nextItems.push({ id, label: `Node ${id}`, mapNodeId: id })
        }

        const nextEdges: MapEdge[] = []
        for (const feature of graph.features ?? []) {
          const geometryType = feature.geometry?.type
          if (geometryType !== 'LineString' && geometryType !== 'MultiLineString') continue

          const props = feature.properties ?? {}
          const startId = props.startid
          const endId = props.endid
          if (startId == null || endId == null) continue

          const from = String(startId)
          const to = String(endId)
          if (!nextNodes[from] || !nextNodes[to]) continue

          nextEdges.push({
            id: String(props.id ?? `${from}-${to}`),
            from,
            to,
          })
        }

        nextItems.sort((a, b) => Number(a.id) - Number(b.id))
        setNodes(nextNodes)
        setEdges(nextEdges)
        setNodeItems(nextItems)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err))
          setNodes({})
          setEdges([])
          setNodeItems([])
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [])

  return { nodes, edges, nodeItems, loading, error }
}

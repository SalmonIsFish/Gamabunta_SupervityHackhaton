'use client'

import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { Card, CardContent } from '@/components/ui/card'
import { CardWatermark } from '@/components/ui/card-watermark'
import { Icons } from '@/components/ui/icons'
import {
  WorkItemCard,
  PRIORITY_META,
  type WorkbenchItem,
  type WorkItemListResponse,
  type WorkItemStatus,
  type ExceptionType,
  type WorkItemPriority,
  type WorkItemResolution,
} from '@/components/workbench/WorkItemCard'
import { WorkItemDetailModal } from '@/components/workbench/WorkItemDetailModal'

const containerVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.05 } },
}

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 },
}

type StatusFilter = 'all' | WorkItemStatus
type ExceptionFilter = 'all' | ExceptionType
type PriorityFilter = 'all' | WorkItemPriority

export default function WorkbenchPage() {
  const [items, setItems] = useState<WorkbenchItem[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [statusFilter, setStatusFilter] = useState<StatusFilter>('pending')
  const [exceptionFilter, setExceptionFilter] = useState<ExceptionFilter>('all')
  const [priorityFilter, setPriorityFilter] = useState<PriorityFilter>('all')

  const [selectedItem, setSelectedItem] = useState<WorkbenchItem | null>(null)
  const [isDetailOpen, setIsDetailOpen] = useState(false)

  const loadItems = useCallback(async () => {
    setIsLoading(true)
    setLoadError(null)
    try {
      const params = new URLSearchParams({ page_size: '50' })
      if (statusFilter !== 'all') params.set('status', statusFilter)
      if (exceptionFilter !== 'all') params.set('exception_type', exceptionFilter)
      if (priorityFilter !== 'all') params.set('priority', priorityFilter)

      const data = await apiClient.get<WorkItemListResponse>(`/api/workbench?${params.toString()}`)
      setItems(data.items)
      setTotal(data.total)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load the Workbench queue.')
    } finally {
      setIsLoading(false)
    }
  }, [statusFilter, exceptionFilter, priorityFilter])

  useEffect(() => {
    loadItems()
  }, [loadItems])

  const handleCardClick = useCallback((item: WorkbenchItem) => {
    setSelectedItem(item)
    setIsDetailOpen(true)
  }, [])

  const handleResolve = useCallback(
    async (id: number, resolution: WorkItemResolution, notes: string) => {
      await apiClient.post(`/api/workbench/${id}/resolve`, {
        resolution,
        resolution_notes: notes || undefined,
      })
      await loadItems()
    },
    [loadItems]
  )

  const pendingCount = items.filter((i) => i.status === 'pending').length
  const criticalCount = items.filter((i) => i.priority === 'critical').length

  return (
    <motion.div className="space-y-6" variants={containerVariants} initial="hidden" animate="visible">
      {/* Header */}
      <motion.div variants={itemVariants} className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-display-3 font-bold tracking-tight text-brand-navy lg:text-display-2">Workbench</h1>
          <p className="mt-1 text-lg text-muted-foreground">
            The human queue — exceptions the agent couldn&apos;t resolve alone, with full context and a recommendation.
          </p>
        </div>
      </motion.div>

      {/* Stats */}
      <motion.div variants={itemVariants} className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        {[
          { value: total, label: 'In Queue', icon: Icons.workbench, bg: 'bg-brand-navy/10', color: 'text-brand-navy' },
          { value: pendingCount, label: 'Pending', icon: Icons.clock, bg: 'bg-amber-100', color: 'text-amber-600' },
          { value: criticalCount, label: 'Critical', icon: Icons.alertTriangle, bg: 'bg-red-100', color: 'text-red-600' },
        ].map((stat) => (
          <div
            key={stat.label}
            className="bg-white rounded-xl border border-gray-200 p-4 hover:border-gray-300 hover:shadow-md transition-all"
          >
            <div className="flex items-center gap-3">
              <div className={cn('p-2 rounded-lg', stat.bg)}>
                <stat.icon className={cn('h-5 w-5', stat.color)} />
              </div>
              <div>
                <p className={cn('text-2xl font-bold', stat.color)}>{stat.value}</p>
                <p className="text-xs text-muted-foreground">{stat.label}</p>
              </div>
            </div>
          </div>
        ))}
      </motion.div>

      {/* Filters */}
      <motion.div variants={itemVariants} className="flex flex-wrap gap-4">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground whitespace-nowrap">Status:</span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className="px-3 py-2.5 rounded-lg border border-input bg-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-cornflower/50"
          >
            <option value="all">All</option>
            <option value="pending">Pending</option>
            <option value="in_review">In Review</option>
            <option value="resolved">Resolved</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground whitespace-nowrap">Exception:</span>
          <select
            value={exceptionFilter}
            onChange={(e) => setExceptionFilter(e.target.value as ExceptionFilter)}
            className="px-3 py-2.5 rounded-lg border border-input bg-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-cornflower/50"
          >
            <option value="all">All</option>
            <option value="low_confidence">Low Confidence</option>
            <option value="policy_conflict">Policy Conflict</option>
            <option value="missing_data">Missing Data</option>
            <option value="high_stakes">High Stakes</option>
            <option value="novel_scenario">Novel Scenario</option>
          </select>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground whitespace-nowrap">Priority:</span>
          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value as PriorityFilter)}
            className="px-3 py-2.5 rounded-lg border border-input bg-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-cornflower/50"
          >
            <option value="all">All</option>
            {Object.entries(PRIORITY_META).map(([value, meta]) => (
              <option key={value} value={value}>
                {meta.label}
              </option>
            ))}
          </select>
        </div>
      </motion.div>

      {/* Queue */}
      <motion.div variants={itemVariants}>
        {isLoading ? (
          <div className="flex items-center justify-center py-16">
            <Icons.loader className="h-8 w-8 animate-spin text-brand-cornflower" />
          </div>
        ) : loadError ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-16 text-center">
              <Icons.alertCircle className="h-8 w-8 text-red-500 mb-3" />
              <p className="text-sm text-red-600">{loadError}</p>
            </CardContent>
          </Card>
        ) : items.length === 0 ? (
          <Card className="relative overflow-hidden">
            <CardWatermark opacity={3} scale={1} />
            <CardContent className="relative z-10 flex flex-col items-center justify-center py-16 text-center">
              <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-cornflower/20 to-brand-purple/20">
                <Icons.checkCircle className="h-8 w-8 text-brand-cornflower" strokeWidth={1.5} />
              </div>
              <h3 className="font-display text-lg font-semibold text-brand-navy">Nothing waiting on you</h3>
              <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                No exceptions match this filter. When an agent can&apos;t proceed alone, it lands here.
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((item) => (
              <WorkItemCard key={item.id} item={item} onClick={handleCardClick} />
            ))}
          </div>
        )}
      </motion.div>

      <WorkItemDetailModal
        item={selectedItem}
        isOpen={isDetailOpen}
        onClose={() => {
          setIsDetailOpen(false)
          setSelectedItem(null)
        }}
        onResolve={handleResolve}
      />
    </motion.div>
  )
}

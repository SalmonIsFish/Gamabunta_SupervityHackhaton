'use client'

import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import { Icons, type Icon } from '@/components/ui/icons'

// ============================================================================
// Types — mirrors app/schemas/work_item.py exactly
// ============================================================================

export type ExceptionType =
  | 'low_confidence'
  | 'policy_conflict'
  | 'missing_data'
  | 'high_stakes'
  | 'novel_scenario'

export type WorkItemStatus = 'pending' | 'in_review' | 'resolved' | 'rejected'
export type WorkItemPriority = 'low' | 'medium' | 'high' | 'critical'
export type WorkItemResolution = 'approved' | 'rejected' | 'modified'

export interface WorkbenchItem {
  id: number
  title: string
  description: string | null
  exception_type: ExceptionType
  status: WorkItemStatus
  priority: WorkItemPriority
  source_agent: string | null
  ai_recommendation: string | null
  confidence_score: number | null
  resource_type: string | null
  resource_id: string | null
  context: Record<string, unknown> | null
  resolution: WorkItemResolution | null
  resolution_notes: string | null
  resolved_by: string | null
  resolved_at: string | null
  created_at: string
  updated_at: string | null
}

export interface WorkItemListResponse {
  items: WorkbenchItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

interface WorkItemCardProps {
  item: WorkbenchItem
  onClick: (item: WorkbenchItem) => void
}

// ============================================================================
// Display maps
// ============================================================================

export const EXCEPTION_TYPE_META: Record<ExceptionType, { label: string; icon: Icon }> = {
  low_confidence: { label: 'Low Confidence', icon: Icons.helpCircle },
  policy_conflict: { label: 'Policy Conflict', icon: Icons.flag },
  missing_data: { label: 'Missing Data', icon: Icons.alertCircle },
  high_stakes: { label: 'High Stakes', icon: Icons.alertTriangle },
  novel_scenario: { label: 'Novel Scenario', icon: Icons.lightbulb },
}

export const PRIORITY_META: Record<WorkItemPriority, { label: string; bg: string; text: string }> = {
  critical: { label: 'Critical', bg: 'bg-red-100', text: 'text-red-700' },
  high: { label: 'High', bg: 'bg-orange-100', text: 'text-orange-700' },
  medium: { label: 'Medium', bg: 'bg-blue-100', text: 'text-blue-700' },
  low: { label: 'Low', bg: 'bg-gray-100', text: 'text-gray-600' },
}

export const STATUS_META: Record<WorkItemStatus, { label: string; dot: string; pulse?: boolean }> = {
  pending: { label: 'Pending', dot: 'bg-amber-500', pulse: true },
  in_review: { label: 'In Review', dot: 'bg-blue-500', pulse: true },
  resolved: { label: 'Resolved', dot: 'bg-emerald-500' },
  rejected: { label: 'Rejected', dot: 'bg-rose-500' },
}

const formatDate = (dateStr: string) =>
  new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })

// ============================================================================
// Card
// ============================================================================

export function WorkItemCard({ item, onClick }: WorkItemCardProps) {
  const exceptionMeta = EXCEPTION_TYPE_META[item.exception_type]
  const priorityMeta = PRIORITY_META[item.priority]
  const statusMeta = STATUS_META[item.status]
  const ExceptionIcon = exceptionMeta.icon

  return (
    <motion.div
      onClick={() => onClick(item)}
      className={cn(
        'relative h-[200px] rounded-xl border cursor-pointer',
        'bg-white flex flex-col group'
      )}
      whileHover={{
        y: -4,
        boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.05)',
        borderColor: 'rgba(156, 163, 175, 0.5)',
      }}
      whileTap={{ scale: 0.98 }}
      transition={{ type: 'spring', stiffness: 400, damping: 25 }}
    >
      <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-transparent to-gray-50/50 opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none" />

      {/* Header */}
      <div className="relative flex items-start justify-between gap-2 p-4 pb-2">
        <div className="flex items-start gap-2 flex-1 min-w-0">
          <div className="relative mt-1.5 flex-shrink-0">
            <div className={cn('h-2.5 w-2.5 rounded-full', statusMeta.dot)} />
            {statusMeta.pulse && (
              <div className={cn('absolute inset-0 h-2.5 w-2.5 rounded-full animate-ping opacity-40', statusMeta.dot)} />
            )}
          </div>
          <h3 className="font-semibold text-brand-navy line-clamp-1 text-sm group-hover:text-brand-cornflower transition-colors duration-200">
            {item.title}
          </h3>
        </div>

        <motion.div
          className={cn('flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold uppercase flex-shrink-0', priorityMeta.bg, priorityMeta.text)}
          whileHover={{ scale: 1.05 }}
        >
          {priorityMeta.label}
        </motion.div>
      </div>

      {/* Description */}
      <div className="relative px-4 pb-2 flex-shrink-0">
        <p className="text-sm text-muted-foreground line-clamp-2 h-[40px]">
          {item.description || 'No additional context provided.'}
        </p>
      </div>

      {/* Chips */}
      <div className="relative px-4 pb-2 flex-1 min-h-0 overflow-hidden">
        <div className="flex flex-wrap gap-1.5">
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-purple-50 text-purple-700 border border-purple-100">
            <ExceptionIcon className="h-2.5 w-2.5" />
            {exceptionMeta.label}
          </span>
          {item.source_agent && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] bg-gray-50 text-gray-600 border border-gray-100">
              <Icons.bot className="h-2.5 w-2.5" />
              {item.source_agent}
            </span>
          )}
        </div>
      </div>

      {/* Footer */}
      <div className="relative flex items-center justify-between px-4 py-3 border-t border-gray-100 mt-auto bg-gray-50/50 rounded-b-xl">
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>{formatDate(item.created_at)}</span>
          <span className="flex items-center gap-1">
            <span className={cn('w-1.5 h-1.5 rounded-full', statusMeta.dot)} />
            {statusMeta.label}
          </span>
        </div>
        <motion.div
          className="flex items-center gap-1 text-xs text-muted-foreground group-hover:text-brand-cornflower transition-colors duration-200"
          initial={{ x: 0 }}
          whileHover={{ x: 2 }}
        >
          <span>Review</span>
          <Icons.chevronRight className="h-3.5 w-3.5 group-hover:translate-x-0.5 transition-transform duration-200" />
        </motion.div>
      </div>
    </motion.div>
  )
}

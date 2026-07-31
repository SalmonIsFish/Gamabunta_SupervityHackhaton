'use client'

import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { createPortal } from 'react-dom'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Icons } from '@/components/ui/icons'
import {
  EXCEPTION_TYPE_META,
  PRIORITY_META,
  STATUS_META,
  type WorkbenchItem,
  type WorkItemResolution,
} from './WorkItemCard'

// ============================================================================
// Types
// ============================================================================

interface WorkItemDetailModalProps {
  item: WorkbenchItem | null
  isOpen: boolean
  onClose: () => void
  onResolve: (id: number, resolution: WorkItemResolution, notes: string) => Promise<void>
}

const RESOLUTION_OPTIONS: { value: WorkItemResolution; label: string; hint: string }[] = [
  { value: 'approved', label: 'Approve', hint: "Accept the AI's recommendation as-is" },
  { value: 'modified', label: 'Modify', hint: 'Apply a different outcome than recommended' },
  { value: 'rejected', label: 'Reject', hint: "Decline the AI's recommendation outright" },
]

const TERMINAL_STATUSES = new Set(['resolved', 'rejected'])

// ============================================================================
// Helpers
// ============================================================================

const formatDateTime = (dateStr: string) =>
  new Date(dateStr).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })

// ============================================================================
// Animation variants (mirrors PolicyDetailModal for visual consistency)
// ============================================================================

const overlayVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0.2 } },
  exit: { opacity: 0, transition: { duration: 0.15 } },
}

const modalVariants = {
  hidden: { opacity: 0, scale: 0.92, y: 30 },
  visible: { opacity: 1, scale: 1, y: 0, transition: { type: 'spring', stiffness: 400, damping: 30, mass: 0.8 } },
  exit: { opacity: 0, scale: 0.95, y: 20, transition: { duration: 0.15 } },
}

// ============================================================================
// Component
// ============================================================================

export function WorkItemDetailModal({ item, isOpen, onClose, onResolve }: WorkItemDetailModalProps) {
  const [mounted, setMounted] = useState(false)
  const [resolution, setResolution] = useState<WorkItemResolution>('approved')
  const [notes, setNotes] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => setMounted(true), [])

  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (isOpen) {
      window.addEventListener('keydown', handleEscape)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      window.removeEventListener('keydown', handleEscape)
      document.body.style.overflow = ''
    }
  }, [isOpen, onClose])

  useEffect(() => {
    if (!isOpen) {
      setResolution('approved')
      setNotes('')
      setError(null)
    }
  }, [isOpen])

  const handleSubmit = useCallback(async () => {
    if (!item) return
    setIsSubmitting(true)
    setError(null)
    try {
      await onResolve(item.id, resolution, notes)
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resolve this item.')
    } finally {
      setIsSubmitting(false)
    }
  }, [item, resolution, notes, onResolve, onClose])

  if (!mounted) return null

  const modalContent = (
    <AnimatePresence mode="wait">
      {isOpen && item && (
        <motion.div
          key="workitem-overlay"
          className="fixed inset-0 flex items-center justify-center p-4"
          style={{ zIndex: 9999, backgroundColor: 'rgba(26, 35, 64, 0.6)', backdropFilter: 'blur(8px)' }}
          variants={overlayVariants}
          initial="hidden"
          animate="visible"
          exit="exit"
          onClick={onClose}
        >
          <motion.div
            key="workitem-content"
            className="relative w-full max-w-2xl max-h-[85vh] bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col"
            variants={modalVariants}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start justify-between px-6 py-5 border-b border-gray-100 bg-gradient-to-r from-gray-50 to-white">
              <div className="flex-1 pr-4">
                <h2 className="text-xl font-semibold text-brand-navy mb-2">{item.title}</h2>
                <div className="flex flex-wrap items-center gap-2">
                  <span className={cn('inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold', PRIORITY_META[item.priority].bg, PRIORITY_META[item.priority].text)}>
                    {PRIORITY_META[item.priority].label} priority
                  </span>
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-purple-100 text-purple-700">
                    {(() => {
                      const ExceptionIcon = EXCEPTION_TYPE_META[item.exception_type].icon
                      return <ExceptionIcon className="h-3 w-3" />
                    })()}
                    {EXCEPTION_TYPE_META[item.exception_type].label}
                  </span>
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-gray-100 text-gray-700">
                    <span className={cn('w-1.5 h-1.5 rounded-full', STATUS_META[item.status].dot)} />
                    {STATUS_META[item.status].label}
                  </span>
                </div>
              </div>
              <Button variant="ghost" size="icon" onClick={onClose} className="flex-shrink-0">
                <Icons.close className="h-5 w-5" />
              </Button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {item.description && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <div className="p-1.5 rounded-lg bg-gray-100">
                      <Icons.fileText className="h-4 w-4 text-gray-600" />
                    </div>
                    <span className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Context</span>
                  </div>
                  <div className="bg-gray-50 rounded-xl border border-gray-200 p-4">
                    <p className="text-sm text-gray-700 leading-relaxed">{item.description}</p>
                  </div>
                </div>
              )}

              {item.ai_recommendation && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <div className="p-1.5 rounded-lg bg-blue-100">
                      <Icons.brain className="h-4 w-4 text-blue-600" />
                    </div>
                    <span className="text-sm font-semibold text-blue-700 uppercase tracking-wide">AI Recommendation</span>
                    {item.confidence_score != null && (
                      <span className="text-xs text-muted-foreground">
                        ({Math.round(item.confidence_score * 100)}% confidence)
                      </span>
                    )}
                  </div>
                  <div className="bg-blue-50 rounded-xl border border-blue-100 p-4">
                    <p className="text-sm text-blue-900 leading-relaxed">{item.ai_recommendation}</p>
                  </div>
                </div>
              )}

              {(item.resource_type || item.source_agent) && (
                <div className="grid grid-cols-2 gap-4 pt-2">
                  {item.source_agent && (
                    <div className="text-center p-3 bg-gray-50 rounded-xl">
                      <p className="text-sm font-medium text-brand-navy truncate">{item.source_agent}</p>
                      <p className="text-xs text-muted-foreground">Raised by</p>
                    </div>
                  )}
                  {item.resource_type && (
                    <div className="text-center p-3 bg-gray-50 rounded-xl">
                      <p className="text-sm font-medium text-brand-navy truncate">
                        {item.resource_type}
                        {item.resource_id ? ` #${item.resource_id}` : ''}
                      </p>
                      <p className="text-xs text-muted-foreground">Affected resource</p>
                    </div>
                  )}
                </div>
              )}

              {item.context && Object.keys(item.context).length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-3">
                    <div className="p-1.5 rounded-lg bg-amber-100">
                      <Icons.info className="h-4 w-4 text-amber-600" />
                    </div>
                    <span className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Full Context</span>
                  </div>
                  <pre className="bg-gray-900 text-gray-100 rounded-xl p-4 text-xs overflow-x-auto max-h-64">
                    {JSON.stringify(item.context, null, 2)}
                  </pre>
                </div>
              )}

              {item.status === 'resolved' || item.status === 'rejected' ? (
                <div className="pt-2 border-t border-gray-100">
                  <div className="flex items-center gap-2 mb-2">
                    <Icons.checkCircle className="h-4 w-4 text-emerald-600" />
                    <span className="text-sm font-semibold text-gray-700">
                      Resolved as {item.resolution} {item.resolved_by ? `by ${item.resolved_by}` : ''}
                    </span>
                  </div>
                  {item.resolution_notes && (
                    <p className="text-sm text-muted-foreground">{item.resolution_notes}</p>
                  )}
                  {item.resolved_at && (
                    <p className="text-xs text-muted-foreground mt-1">{formatDateTime(item.resolved_at)}</p>
                  )}
                </div>
              ) : (
                <div className="pt-2 border-t border-gray-100">
                  <div className="flex items-center gap-2 mb-3">
                    <div className="p-1.5 rounded-lg bg-emerald-100">
                      <Icons.check className="h-4 w-4 text-emerald-600" />
                    </div>
                    <span className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Your Decision</span>
                  </div>
                  <div className="flex flex-col gap-2 mb-3">
                    {RESOLUTION_OPTIONS.map((opt) => (
                      <label
                        key={opt.value}
                        className={cn(
                          'flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors',
                          resolution === opt.value ? 'border-brand-cornflower bg-brand-cornflower/5' : 'border-gray-200 hover:border-gray-300'
                        )}
                      >
                        <input
                          type="radio"
                          name="resolution"
                          value={opt.value}
                          checked={resolution === opt.value}
                          onChange={() => setResolution(opt.value)}
                          className="mt-1"
                        />
                        <div>
                          <p className="text-sm font-medium text-brand-navy">{opt.label}</p>
                          <p className="text-xs text-muted-foreground">{opt.hint}</p>
                        </div>
                      </label>
                    ))}
                  </div>
                  <textarea
                    value={notes}
                    onChange={(e) => setNotes(e.target.value)}
                    placeholder="Notes for the audit trail (optional)..."
                    rows={3}
                    maxLength={2000}
                    className="w-full px-3 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-brand-cornflower/50"
                  />
                  {error && (
                    <p className="mt-2 text-sm text-red-600 flex items-center gap-1">
                      <Icons.alertCircle className="h-4 w-4" />
                      {error}
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* Footer */}
            {!TERMINAL_STATUSES.has(item.status) && (
              <div className="flex items-center justify-end gap-2 px-6 py-4 border-t border-gray-100 bg-gray-50">
                <Button variant="outline" size="sm" onClick={onClose} disabled={isSubmitting}>
                  Cancel
                </Button>
                <Button variant="gradient" size="sm" onClick={handleSubmit} loading={isSubmitting}>
                  <Icons.check className="h-4 w-4 mr-1.5" />
                  Submit Decision
                </Button>
              </div>
            )}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )

  return createPortal(modalContent, document.body)
}

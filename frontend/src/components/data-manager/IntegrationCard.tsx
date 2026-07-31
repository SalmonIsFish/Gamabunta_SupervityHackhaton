'use client'

import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import { Icons } from '@/components/ui/icons'

// ============================================================================
// Types — mirrors app/routers/data_manager.py's IntegrationStatus exactly
// ============================================================================

export type IntegrationHealthStatus = 'healthy' | 'unhealthy' | 'configured' | 'not_configured' | 'external'

export interface IntegrationStatusItem {
  name: string
  category: string
  purpose: string
  status: IntegrationHealthStatus
  checked_live: boolean
  detail: string | null
  last_checked_at: string
}

export interface DataManagerStatusResponse {
  integrations: IntegrationStatusItem[]
}

const STATUS_META: Record<IntegrationHealthStatus, { label: string; dot: string; bg: string; text: string }> = {
  healthy: { label: 'Healthy', dot: 'bg-emerald-500', bg: 'bg-emerald-100', text: 'text-emerald-700' },
  configured: { label: 'Configured', dot: 'bg-blue-500', bg: 'bg-blue-100', text: 'text-blue-700' },
  external: { label: 'Managed Externally', dot: 'bg-gray-400', bg: 'bg-gray-100', text: 'text-gray-600' },
  not_configured: { label: 'Not Configured', dot: 'bg-amber-500', bg: 'bg-amber-100', text: 'text-amber-700' },
  unhealthy: { label: 'Unhealthy', dot: 'bg-red-500', bg: 'bg-red-100', text: 'text-red-700' },
}

const CATEGORY_LABELS: Record<string, string> = {
  system_of_record: 'System of Record',
  channel: 'Channel',
  orchestration: 'Orchestration',
}

const formatTime = (iso: string) =>
  new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

export function IntegrationCard({ integration }: { integration: IntegrationStatusItem }) {
  const meta = STATUS_META[integration.status]

  return (
    <motion.div
      className="relative rounded-xl border bg-white p-5 flex flex-col gap-3"
      whileHover={{ y: -2, boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.1)' }}
      transition={{ type: 'spring', stiffness: 400, damping: 25 }}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="font-semibold text-brand-navy text-sm">{integration.name}</h3>
          <span className="text-[11px] text-muted-foreground">
            {CATEGORY_LABELS[integration.category] || integration.category}
          </span>
        </div>
        <span className={cn('inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold', meta.bg, meta.text)}>
          <span className={cn('w-1.5 h-1.5 rounded-full', meta.dot, integration.status === 'healthy' && 'animate-pulse')} />
          {meta.label}
        </span>
      </div>

      <p className="text-xs text-muted-foreground leading-relaxed">{integration.purpose}</p>

      {integration.detail && (
        <div className="flex items-start gap-1.5 text-xs text-gray-500 bg-gray-50 rounded-lg p-2">
          <Icons.info className="h-3.5 w-3.5 flex-shrink-0 mt-0.5" />
          <span>{integration.detail}</span>
        </div>
      )}

      <div className="flex items-center justify-between mt-1 pt-2 border-t border-gray-100 text-[11px] text-muted-foreground">
        <span className="flex items-center gap-1">
          <Icons.clock className="h-3 w-3" />
          {formatTime(integration.last_checked_at)}
        </span>
        <span className="flex items-center gap-1">
          {integration.checked_live ? (
            <>
              <Icons.zap className="h-3 w-3 text-brand-cornflower" />
              Live check
            </>
          ) : (
            <>
              <Icons.eye className="h-3 w-3" />
              Config check
            </>
          )}
        </span>
      </div>
    </motion.div>
  )
}

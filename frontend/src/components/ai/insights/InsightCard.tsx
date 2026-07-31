'use client'

import { useState } from 'react'
import { cn } from '@/lib/utils'
import { Icons } from '@/components/ui/icons'
import { Button } from '@/components/ui/button'

// Mirrors app/models/insight.py's InsightSeverity/InsightType/InsightStatus exactly —
// the backend only ever returns these three severities and three types.
export type InsightSeverity = 'critical' | 'warning' | 'info'
export type InsightType = 'pattern' | 'anomaly' | 'recommendation'
export type InsightStatus = 'new' | 'reviewed' | 'actioned' | 'dismissed'

export interface Insight {
  id: string
  insight_type: InsightType
  severity: InsightSeverity
  title: string
  description: string | null
  extra_data?: Record<string, unknown> | null
  suggested_action?: string | null
  confidence?: number | null
  status: InsightStatus
  generated_by?: string | null
  created_at: string
}

interface InsightCardProps {
  insight: Insight
  onDismiss?: (id: string) => void
}

/**
 * Get severity configuration for consistent styling across the app.
 * Supports both old severity names and new ones.
 */
export function getSeverityConfig(severity: InsightSeverity) {
  const configs = {
    critical: {
      icon: Icons.alertCircle,
      bg: 'bg-red-50',
      border: 'border-red-200',
      accent: 'border-l-red-500',
      iconBg: 'bg-red-100',
      iconColor: 'text-red-600',
      badge: 'bg-red-100 text-red-700',
      textColor: 'text-red-700',
    },
    warning: {
      icon: Icons.alertTriangle,
      bg: 'bg-amber-50',
      border: 'border-amber-200',
      accent: 'border-l-amber-500',
      iconBg: 'bg-amber-100',
      iconColor: 'text-amber-600',
      badge: 'bg-amber-100 text-amber-700',
      textColor: 'text-amber-700',
    },
    info: {
      icon: Icons.info,
      bg: 'bg-blue-50',
      border: 'border-blue-200',
      accent: 'border-l-blue-500',
      iconBg: 'bg-blue-100',
      iconColor: 'text-blue-600',
      badge: 'bg-blue-100 text-blue-700',
      textColor: 'text-blue-700',
    },
  }
  return configs[severity] || configs.info
}

const typeConfig: Record<InsightType, { label: string; icon: typeof Icons.activity }> = {
  pattern: { label: 'Pattern', icon: Icons.activity },
  anomaly: { label: 'Anomaly', icon: Icons.alertTriangle },
  recommendation: { label: 'Recommendation', icon: Icons.lightbulb },
}

export function InsightCard({ insight, onDismiss }: InsightCardProps) {
  const [showRaw, setShowRaw] = useState(false)
  const severity = getSeverityConfig(insight.severity)
  const type = typeConfig[insight.insight_type] || typeConfig.recommendation
  const SeverityIcon = severity.icon
  const isDismissed = insight.status === 'dismissed'
  const hasExtraData = !!insight.extra_data && Object.keys(insight.extra_data).length > 0

  return (
    <div className={cn(
      'rounded-xl border p-4',
      'transition-all duration-200 hover:shadow-soft',
      severity.bg,
      severity.border,
      isDismissed && 'opacity-50'
    )}>
      <div className="flex gap-4">
        {/* Icon */}
        <div className={cn(
          'flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg',
          severity.iconBg
        )}>
          <SeverityIcon className={cn('h-5 w-5', severity.iconColor)} strokeWidth={1.5} />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h4 className="font-semibold text-foreground">{insight.title}</h4>
                <span className={cn(
                  'rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase',
                  severity.badge
                )}>
                  {insight.severity}
                </span>
                {insight.confidence != null && (
                  <span className="text-xs text-muted-foreground">
                    {Math.round(insight.confidence * 100)}% confident
                  </span>
                )}
                {isDismissed && (
                  <span className="rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase bg-gray-100 text-gray-500">
                    Dismissed
                  </span>
                )}
              </div>
              <div className="flex items-center gap-2 mt-1">
                <type.icon className="h-3 w-3 text-muted-foreground" strokeWidth={1.5} />
                <span className="text-xs text-muted-foreground">{type.label}</span>
                <span className="text-xs text-muted-foreground">•</span>
                <span className="text-xs text-muted-foreground">
                  {new Date(insight.created_at).toLocaleDateString()}
                </span>
                {insight.generated_by && (
                  <>
                    <span className="text-xs text-muted-foreground">•</span>
                    <span className="text-xs text-muted-foreground">{insight.generated_by}</span>
                  </>
                )}
              </div>
            </div>

            {onDismiss && !isDismissed && (
              <Button
                variant="ghost"
                size="icon-sm"
                onClick={() => onDismiss(insight.id)}
                className="text-muted-foreground hover:text-foreground"
                title="Dismiss"
              >
                <Icons.close className="h-4 w-4" />
              </Button>
            )}
          </div>

          {insight.description && (
            <p className="mt-2 text-sm text-muted-foreground">
              {insight.description}
            </p>
          )}

          {/* Suggested action — the "actionable next step," shown as text since
              the backend gives no structured routing target to auto-click into */}
          {insight.suggested_action && (
            <div className={cn('mt-3 flex items-start gap-2 rounded-lg px-3 py-2 text-sm', 'bg-white/60', severity.textColor)}>
              <Icons.arrowRight className="h-4 w-4 flex-shrink-0 mt-0.5" strokeWidth={1.5} />
              <span>{insight.suggested_action}</span>
            </div>
          )}

          {/* Raw numbers behind the claim — auditability */}
          {hasExtraData && (
            <div className="mt-3">
              <button
                onClick={() => setShowRaw((v) => !v)}
                className="text-xs font-medium text-muted-foreground hover:text-foreground flex items-center gap-1"
              >
                <Icons.chevronRight className={cn('h-3 w-3 transition-transform', showRaw && 'rotate-90')} />
                {showRaw ? 'Hide' : 'Show'} the numbers behind this
              </button>
              {showRaw && (
                <pre className="mt-2 rounded-lg bg-gray-900 text-gray-100 p-3 text-xs overflow-x-auto">
                  {JSON.stringify(insight.extra_data, null, 2)}
                </pre>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}


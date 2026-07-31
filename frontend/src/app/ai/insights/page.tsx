'use client'

import { useState, useEffect, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { CardWatermark } from '@/components/ui/card-watermark'
import { Icons } from '@/components/ui/icons'
import { InsightCard, type Insight, type InsightSeverity, type InsightType } from '@/components/ai/insights/InsightCard'

// ============================================================================
// Types
// ============================================================================

interface InsightListResponse {
  items: Insight[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

interface InsightGenerateResponse {
  generated_count: number
  insights: Insight[]
}

type TypeFilter = 'all' | InsightType
type SeverityFilter = 'all' | InsightSeverity

const containerVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.1 } },
}

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 },
}

const TYPE_FILTERS: { value: TypeFilter; label: string }[] = [
  { value: 'all', label: 'All types' },
  { value: 'pattern', label: 'Pattern' },
  { value: 'anomaly', label: 'Anomaly' },
  { value: 'recommendation', label: 'Recommendation' },
]

const SEVERITY_FILTERS: { value: SeverityFilter; label: string }[] = [
  { value: 'all', label: 'All severities' },
  { value: 'critical', label: 'Critical' },
  { value: 'warning', label: 'Warning' },
  { value: 'info', label: 'Info' },
]

// ============================================================================
// Page
// ============================================================================

export default function AIInsightsPage() {
  const [insights, setInsights] = useState<Insight[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analyzeError, setAnalyzeError] = useState<string | null>(null)

  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all')
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all')

  const fetchInsights = useCallback(async () => {
    setIsLoading(true)
    setLoadError(null)
    try {
      const params = new URLSearchParams({ page_size: '100' })
      if (typeFilter !== 'all') params.set('insight_type', typeFilter)
      if (severityFilter !== 'all') params.set('severity', severityFilter)
      const data = await apiClient.get<InsightListResponse>(`/api/ai/insights?${params.toString()}`)
      setInsights(data.items)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load insights.')
    } finally {
      setIsLoading(false)
    }
  }, [typeFilter, severityFilter])

  useEffect(() => {
    fetchInsights()
  }, [fetchInsights])

  const handleAnalyze = useCallback(async () => {
    setIsAnalyzing(true)
    setAnalyzeError(null)
    try {
      await apiClient.post<InsightGenerateResponse>('/api/ai/insights/generate?domain=procurement')
      await fetchInsights()
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : 'Failed to generate insights.')
    } finally {
      setIsAnalyzing(false)
    }
  }, [fetchInsights])

  const handleDismissInsight = useCallback(async (id: string) => {
    const previous = insights
    setInsights((prev) => prev.map((i) => (i.id === id ? { ...i, status: 'dismissed' } : i)))
    try {
      await apiClient.post(`/api/ai/insights/${id}/dismiss`)
    } catch {
      setInsights(previous)
    }
  }, [insights])

  const criticalCount = insights.filter((i) => i.severity === 'critical').length
  const warningCount = insights.filter((i) => i.severity === 'warning').length
  const infoCount = insights.filter((i) => i.severity === 'info').length

  return (
    <motion.div className="space-y-6" variants={containerVariants} initial="hidden" animate="visible">
      {/* Header */}
      <motion.div variants={itemVariants} className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-display-3 font-bold tracking-tight text-brand-navy lg:text-display-2">AI Insights</h1>
          <p className="mt-2 text-lg text-muted-foreground">
            Patterns, anomalies, and recommendations computed from the data your agent actually processed.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Button variant="gradient" onClick={handleAnalyze} disabled={isAnalyzing}>
            {isAnalyzing ? (
              <>
                <Icons.loader className="mr-2 h-4 w-4 animate-spin" />
                Analyzing...
              </>
            ) : (
              <>
                <Icons.sparkles className="mr-2 h-4 w-4" strokeWidth={1.5} />
                Run Analysis
              </>
            )}
          </Button>
          {analyzeError && <p className="text-xs text-red-600">{analyzeError}</p>}
        </div>
      </motion.div>

      {/* Stats Cards */}
      <motion.div variants={itemVariants} className="grid gap-4 sm:grid-cols-3">
        <Card className="relative overflow-hidden">
          <CardWatermark opacity={2} scale={0.8} />
          <CardContent className="relative z-10 flex items-center gap-4 py-6">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-red-100">
              <Icons.alertCircle className="h-6 w-6 text-red-600" strokeWidth={1.5} />
            </div>
            <div>
              <p className="text-2xl font-bold text-brand-navy">{criticalCount}</p>
              <p className="text-sm text-muted-foreground">Critical</p>
            </div>
          </CardContent>
        </Card>

        <Card className="relative overflow-hidden">
          <CardWatermark opacity={2} scale={0.8} />
          <CardContent className="relative z-10 flex items-center gap-4 py-6">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-amber-100">
              <Icons.alertTriangle className="h-6 w-6 text-amber-600" strokeWidth={1.5} />
            </div>
            <div>
              <p className="text-2xl font-bold text-brand-navy">{warningCount}</p>
              <p className="text-sm text-muted-foreground">Warnings</p>
            </div>
          </CardContent>
        </Card>

        <Card className="relative overflow-hidden">
          <CardWatermark opacity={2} scale={0.8} />
          <CardContent className="relative z-10 flex items-center gap-4 py-6">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-100">
              <Icons.lightbulb className="h-6 w-6 text-blue-600" strokeWidth={1.5} />
            </div>
            <div>
              <p className="text-2xl font-bold text-brand-navy">{infoCount}</p>
              <p className="text-sm text-muted-foreground">Info</p>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* Filters */}
      <motion.div variants={itemVariants} className="flex flex-wrap gap-4">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground whitespace-nowrap">Type:</span>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
            className="px-3 py-2.5 rounded-lg border border-input bg-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-cornflower/50"
          >
            {TYPE_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground whitespace-nowrap">Severity:</span>
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value as SeverityFilter)}
            className="px-3 py-2.5 rounded-lg border border-input bg-white text-sm focus:outline-none focus:ring-2 focus:ring-brand-cornflower/50"
          >
            {SEVERITY_FILTERS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
      </motion.div>

      {/* List */}
      <AnimatePresence mode="wait">
        <motion.div key="insights-list" initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -10 }} transition={{ duration: 0.2 }}>
          <Card className="relative overflow-hidden">
            <CardWatermark opacity={2} scale={1} />
            <CardHeader className="relative z-10">
              <CardTitle>Insights</CardTitle>
              <CardDescription>{insights.length} insight(s) currently on record.</CardDescription>
            </CardHeader>
            <CardContent className="relative z-10 space-y-4">
              {isLoading ? (
                <div className="flex items-center justify-center py-12">
                  <Icons.loader className="h-8 w-8 animate-spin text-brand-cornflower" />
                </div>
              ) : loadError ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <Icons.alertCircle className="h-8 w-8 text-red-500 mb-3" />
                  <p className="text-sm text-red-600">{loadError}</p>
                </div>
              ) : insights.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 text-center">
                  <div className={cn('mb-4 flex h-16 w-16 items-center justify-center rounded-2xl', 'bg-gradient-to-br from-brand-cornflower/20 to-brand-purple/20')}>
                    <Icons.lightbulb className="h-8 w-8 text-brand-cornflower" strokeWidth={1.5} />
                  </div>
                  <h3 className="font-display text-lg font-semibold text-brand-navy">No insights yet</h3>
                  <p className="mt-1 max-w-sm text-sm text-muted-foreground">
                    Run an analysis to discover patterns, anomalies, and recommendations from real data.
                  </p>
                  <Button variant="gradient" className="mt-6" onClick={handleAnalyze} disabled={isAnalyzing}>
                    <Icons.sparkles className="mr-2 h-4 w-4" strokeWidth={1.5} />
                    Generate Insights
                  </Button>
                </div>
              ) : (
                insights.map((insight) => (
                  <InsightCard key={insight.id} insight={insight} onDismiss={handleDismissInsight} />
                ))
              )}
            </CardContent>
          </Card>
        </motion.div>
      </AnimatePresence>
    </motion.div>
  )
}

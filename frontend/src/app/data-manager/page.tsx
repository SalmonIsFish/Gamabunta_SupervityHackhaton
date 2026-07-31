'use client'

import { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import { cn } from '@/lib/utils'
import { apiClient } from '@/lib/api-client'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Icons } from '@/components/ui/icons'
import { IntegrationCard, type DataManagerStatusResponse, type IntegrationStatusItem } from '@/components/data-manager/IntegrationCard'

const containerVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.05 } },
}

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 },
}

export default function DataManagerPage() {
  const [integrations, setIntegrations] = useState<IntegrationStatusItem[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  const loadStatus = useCallback(async (isRefresh = false) => {
    if (isRefresh) setIsRefreshing(true)
    else setIsLoading(true)
    setLoadError(null)
    try {
      const data = await apiClient.get<DataManagerStatusResponse>('/api/data-manager/status')
      setIntegrations(data.integrations)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load integration status.')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [])

  useEffect(() => {
    loadStatus()
  }, [loadStatus])

  const healthyCount = integrations.filter((i) => i.status === 'healthy' || i.status === 'configured').length
  const liveCount = integrations.filter((i) => i.checked_live).length
  const categories = new Set(integrations.map((i) => i.category)).size

  return (
    <motion.div className="space-y-6" variants={containerVariants} initial="hidden" animate="visible">
      {/* Header */}
      <motion.div variants={itemVariants} className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-display-3 font-bold tracking-tight text-brand-navy lg:text-display-2">Data Manager</h1>
          <p className="mt-1 text-lg text-muted-foreground">
            Every system this build is connected to, what it&apos;s used for, and whether it&apos;s healthy.
          </p>
        </div>
        <Button variant="outline" onClick={() => loadStatus(true)} disabled={isRefreshing}>
          <Icons.refresh className={cn('mr-2 h-4 w-4', isRefreshing && 'animate-spin')} />
          Refresh
        </Button>
      </motion.div>

      {/* Stats */}
      <motion.div variants={itemVariants} className="grid grid-cols-3 gap-4">
        {[
          { value: integrations.length, label: 'Connected Systems', icon: Icons.network, bg: 'bg-brand-navy/10', color: 'text-brand-navy' },
          { value: healthyCount, label: 'Healthy / Configured', icon: Icons.checkCircle, bg: 'bg-emerald-100', color: 'text-emerald-600' },
          { value: `${liveCount}/${integrations.length || 0}`, label: 'Live-Checked', icon: Icons.zap, bg: 'bg-blue-100', color: 'text-blue-600' },
        ].map((stat) => (
          <div key={stat.label} className="bg-white rounded-xl border border-gray-200 p-4 hover:border-gray-300 hover:shadow-md transition-all">
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

      {categories > 0 && categories < 2 && (
        <motion.div variants={itemVariants} className="flex items-center gap-2 text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-4 py-2.5">
          <Icons.alertTriangle className="h-4 w-4 flex-shrink-0" />
          Only one integration category is represented — the Round 2 floor requires at least two (a channel and a system of record).
        </motion.div>
      )}

      {/* Grid */}
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
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {integrations.map((integration) => (
              <IntegrationCard key={integration.name} integration={integration} />
            ))}
          </div>
        )}
      </motion.div>
    </motion.div>
  )
}

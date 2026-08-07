'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { motion, useInView } from 'framer-motion'
import { apiClient } from '@/lib/api-client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CardWatermark } from '@/components/ui/card-watermark'
import { Icons } from '@/components/ui/icons'
import { ActivityChart, type ActivityDatum } from '@/components/ActivityChart'
import { cn } from '@/lib/utils'

// Animation variants
const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.1,
      delayChildren: 0.1,
    },
  },
}

const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.5,
      ease: [0.25, 0.46, 0.45, 0.94],
    },
  },
}

// Animated number component
function AnimatedNumber({
  value,
  suffix = '',
  duration = 1000,
}: {
  value: number
  suffix?: string
  duration?: number
}) {
  const [displayValue, setDisplayValue] = useState(0)
  const ref = useRef<HTMLSpanElement>(null)
  const isInView = useInView(ref, { once: true, amount: 0.5 })
  const hasAnimated = useRef(false)

  useEffect(() => {
    if (!isInView || hasAnimated.current) return
    hasAnimated.current = true

    const startTime = performance.now()

    const animate = (currentTime: number) => {
      const elapsed = currentTime - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = 1 - Math.pow(2, -10 * progress)

      setDisplayValue(Math.round(eased * value))

      if (progress < 1) {
        requestAnimationFrame(animate)
      } else {
        setDisplayValue(value)
      }
    }

    requestAnimationFrame(animate)
  }, [value, duration, isInView])

  const formatValue = (num: number): string => {
    if (num >= 1000) {
      return (num / 1000).toFixed(1) + 'K'
    }
    return num.toString()
  }

  return (
    <span ref={ref}>
      {formatValue(displayValue)}
      {suffix}
    </span>
  )
}

// Stats Card Component with Bento styling
interface StatCardProps {
  title: string
  value: number
  suffix?: string
  icon: React.ElementType
  subtitle?: string
  colorClass: string
  delay?: number
}

function StatCard({
  title,
  value,
  suffix = '',
  icon: Icon,
  subtitle,
  colorClass,
  delay = 0,
}: StatCardProps) {
  return (
    <motion.div
      variants={itemVariants}
      initial='hidden'
      animate='visible'
      transition={{ delay }}
      whileHover={{ y: -4 }}
    >
      <Card className='group relative h-full cursor-default overflow-hidden'>
        {/* Branded watermark texture */}
        <CardWatermark opacity={3} scale={0.9} />
        <CardContent className='relative z-10 p-5'>
          <div className='flex items-start justify-between'>
            <div className='space-y-2'>
              {/* Micro label */}
              <p className='text-micro uppercase text-brand-muted transition-colors duration-200 group-hover:text-brand-cornflower'>
                {title}
              </p>
              {/* Display number */}
              <p className='font-display text-[2.25rem] font-bold leading-none tracking-tight text-brand-navy'>
                <AnimatedNumber value={value} suffix={suffix} />
              </p>
              {/* Real, honestly-labeled context — no fabricated trend % */}
              {subtitle && (
                <motion.p
                  className='flex items-center gap-1 text-xs font-medium text-muted-foreground'
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: delay + 0.3 }}
                >
                  {subtitle}
                </motion.p>
              )}
            </div>
            {/* Icon */}
            <motion.div
              className={cn(
                'rounded-xl p-2.5 text-white',
                'shadow-lg',
                colorClass
              )}
              whileHover={{ scale: 1.15, rotate: 5 }}
              transition={{ type: 'spring', stiffness: 400, damping: 17 }}
            >
              <Icon className='h-5 w-5' strokeWidth={1.5} />
            </motion.div>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  )
}

// Hero Section
function HeroSection({ userName }: { userName?: string }) {
  const firstName = userName?.split(' ')[0] || 'there'

  return (
    <motion.div
      className='col-span-12 py-2'
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: [0.25, 0.46, 0.45, 0.94] }}
    >
      <h1 className='text-display-3 font-bold tracking-tight text-brand-navy lg:text-display-2'>
        Where Intelligence <br className='hidden sm:block' />
        <span className='text-gradient'>Meets Human.</span>
      </h1>
      <p className='mt-4 text-lg font-light text-muted-foreground'>
        Welcome back, {firstName}. Your AI Command Center is ready.
      </p>
    </motion.div>
  )
}

// Diagnostics Card
function DiagnosticsCard() {
  const [apiResponse, setApiResponse] = useState<string>('')
  const [adminResponse, setAdminResponse] = useState<string>('')
  const [isLoading, setIsLoading] = useState(false)

  const callApi = async (
    endpoint: string,
    setter: React.Dispatch<React.SetStateAction<string>>
  ) => {
    setIsLoading(true)
    setter('Loading...')
    try {
      const data = await apiClient.get(endpoint)
      setter(JSON.stringify(data, null, 2))
    } catch (error) {
      setter(
        `Error: ${error instanceof Error ? error.message : 'Unknown error'}`
      )
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card className='relative col-span-12 h-full overflow-hidden'>
      <CardWatermark opacity={3} scale={1.1} />
      <CardHeader className='relative z-10'>
        <CardTitle className='flex items-center gap-2'>
          <Icons.activity
            className='h-5 w-5 text-brand-cornflower'
            strokeWidth={1.5}
          />
          System Diagnostics
        </CardTitle>
      </CardHeader>
      <CardContent className='relative z-10 space-y-6'>
        <div className='space-y-3'>
          <div className='flex items-center justify-between'>
            <div>
              <p className='text-sm font-medium text-foreground'>
                Standard Authorization
              </p>
              <p className='mt-0.5 font-mono text-xs text-muted-foreground'>
                /api/test
              </p>
            </div>
          </div>
          <Button
            onClick={() => callApi('/api/test', setApiResponse)}
            disabled={isLoading}
            variant='outline'
            className='w-full'
          >
            {isLoading ? 'Running...' : 'Run Diagnostics'}
          </Button>
          {apiResponse && (
            <div className='rounded-xl border border-border/50 bg-muted/30 p-4'>
              <pre className='overflow-x-auto font-mono text-xs text-muted-foreground'>
                <code>{apiResponse}</code>
              </pre>
            </div>
          )}
        </div>

        <div className='h-px bg-border/50' />

        <div className='space-y-3'>
          <div className='flex items-center justify-between'>
            <div>
              <p className='text-sm font-medium text-foreground'>
                Admin Verification
              </p>
              <p className='mt-0.5 font-mono text-xs text-muted-foreground'>
                /api/admin/dashboard
              </p>
            </div>
          </div>
          <Button
            onClick={() => callApi('/api/admin/dashboard', setAdminResponse)}
            disabled={isLoading}
            variant='gradient'
            className='w-full'
          >
            {isLoading ? 'Verifying...' : 'Verify Admin Access'}
            <Icons.arrowRight className='ml-2 h-4 w-4' />
          </Button>
          {adminResponse && (
            <div className='rounded-xl border border-border/50 bg-muted/30 p-4'>
              <pre className='overflow-x-auto font-mono text-xs text-muted-foreground'>
                <code>{adminResponse}</code>
              </pre>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ============================================================================
// Dashboard data — live counts from the real backend, not the template's demo
// numbers. /api/admin/audit and /api/data-manager/status both resolve via
// AUTH_BYPASS's dev user with no token when auth is bypassed (same as
// DiagnosticsCard's existing unauthenticated calls on this page) — if
// AUTH_BYPASS is ever turned off, these fetches would need a session gate.
// ============================================================================

interface DashboardStats {
  pendingWorkbench: number
  criticalPendingWorkbench: number
  newInsights: number
  criticalNewInsights: number
  activePolicies: number
  integrationsHealthy: number
  integrationsTotal: number
  integrationsLiveChecked: number
}

interface ListTotal {
  total: number
}

interface IntegrationStatusItem {
  status: 'healthy' | 'unhealthy' | 'configured' | 'not_configured' | 'external'
  checked_live: boolean
}

const CHART_ACTIONS = {
  chatTurns: 'ai_manager.chat',
  workbenchItems: 'workbench.create',
  policyEvaluations: 'policy.evaluate',
} as const

async function fetchDailyActivity(): Promise<ActivityDatum[]> {
  const days = Array.from({ length: 7 }, (_, i) => {
    const end = new Date()
    end.setUTCHours(0, 0, 0, 0)
    end.setUTCDate(end.getUTCDate() - (6 - i) + 1)
    const start = new Date(end)
    start.setUTCDate(start.getUTCDate() - 1)
    return { start, end, name: start.toLocaleDateString('en-US', { weekday: 'short' }) }
  })

  const actionEntries = Object.entries(CHART_ACTIONS) as [keyof typeof CHART_ACTIONS, string][]

  const results = await Promise.all(
    days.flatMap(({ start, end }, dayIndex) =>
      actionEntries.map(([key, action]) =>
        apiClient
          .get<ListTotal>(
            `/api/admin/audit?action=${encodeURIComponent(action)}&start_date=${start.toISOString()}&end_date=${end.toISOString()}&page_size=1`
          )
          .then((r) => ({ dayIndex, key, total: r.total }))
          .catch(() => ({ dayIndex, key, total: 0 }))
      )
    )
  )

  return days.map((d, dayIndex) => {
    const dayResults = results.filter((r) => r.dayIndex === dayIndex)
    const byKey = Object.fromEntries(dayResults.map((r) => [r.key, r.total])) as Record<
      keyof typeof CHART_ACTIONS,
      number
    >
    return {
      name: d.name,
      chatTurns: byKey.chatTurns ?? 0,
      workbenchItems: byKey.workbenchItems ?? 0,
      policyEvaluations: byKey.policyEvaluations ?? 0,
    }
  })
}

// Main Dashboard
export default function HomePage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [activityData, setActivityData] = useState<ActivityDatum[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  const loadDashboard = useCallback(async () => {
    setIsLoading(true)
    setLoadError(null)
    try {
      const [pending, criticalPending, insights, criticalInsights, policies, dataManager, activity] =
        await Promise.all([
          apiClient.get<ListTotal>('/api/workbench?status=pending&page_size=1'),
          apiClient.get<ListTotal>('/api/workbench?status=pending&priority=critical&page_size=1'),
          apiClient.get<ListTotal>('/api/ai/insights?status=new&page_size=1'),
          apiClient.get<ListTotal>('/api/ai/insights?status=new&severity=critical&page_size=1'),
          apiClient.get<ListTotal>('/api/ai/policies?status=active&page_size=1'),
          apiClient.get<{ integrations: IntegrationStatusItem[] }>('/api/data-manager/status'),
          fetchDailyActivity(),
        ])

      const integrations = dataManager.integrations
      setStats({
        pendingWorkbench: pending.total,
        criticalPendingWorkbench: criticalPending.total,
        newInsights: insights.total,
        criticalNewInsights: criticalInsights.total,
        activePolicies: policies.total,
        integrationsHealthy: integrations.filter(
          (i) => i.status === 'healthy' || i.status === 'configured'
        ).length,
        integrationsTotal: integrations.length,
        integrationsLiveChecked: integrations.filter((i) => i.checked_live).length,
      })
      setActivityData(activity)
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load dashboard data.')
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDashboard()
  }, [loadDashboard])

  return (
    <motion.div
      className='space-y-6'
      variants={containerVariants}
      initial='hidden'
      animate='visible'
    >
      {/* Hero Section */}
      <HeroSection userName='Developer' />

      {loadError && (
        <div className='rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700'>
          Couldn&apos;t load live dashboard data: {loadError}
        </div>
      )}

      {isLoading ? (
        <div className='flex items-center justify-center py-16'>
          <Icons.loader className='h-8 w-8 animate-spin text-brand-cornflower' />
        </div>
      ) : (
        <>
          {/* Stats Grid - Bento style, backed by real data */}
          <div className='grid grid-cols-2 gap-4 lg:grid-cols-4'>
            <StatCard
              title='Workbench Queue'
              value={stats?.pendingWorkbench ?? 0}
              icon={Icons.workbench}
              subtitle={`${stats?.criticalPendingWorkbench ?? 0} critical`}
              colorClass='bg-brand-navy'
              delay={0.1}
            />
            <StatCard
              title='New Insights'
              value={stats?.newInsights ?? 0}
              icon={Icons.lightbulb}
              subtitle={`${stats?.criticalNewInsights ?? 0} critical`}
              colorClass='bg-brand-cornflower'
              delay={0.2}
            />
            <StatCard
              title='Active Policies'
              value={stats?.activePolicies ?? 0}
              icon={Icons.shield}
              subtitle='governing live traffic'
              colorClass='bg-brand-purple'
              delay={0.3}
            />
            <StatCard
              title='Integrations Healthy'
              value={stats?.integrationsHealthy ?? 0}
              suffix={`/${stats?.integrationsTotal ?? 0}`}
              icon={Icons.network}
              subtitle={`${stats?.integrationsLiveChecked ?? 0} live-checked`}
              colorClass='bg-gradient-to-br from-brand-navy to-brand-purple'
              delay={0.4}
            />
          </div>

          {/* Activity Chart - Full Width */}
          <motion.div variants={itemVariants}>
            <ActivityChart className='col-span-12' data={activityData} />
          </motion.div>
        </>
      )}

      {/* System Diagnostics */}
      <motion.div
        className='grid gap-6 lg:grid-cols-12'
        variants={itemVariants}
      >
        <DiagnosticsCard />
      </motion.div>
    </motion.div>
  )
}

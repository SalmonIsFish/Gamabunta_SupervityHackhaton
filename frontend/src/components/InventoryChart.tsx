'use client'

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { CardWatermark } from '@/components/ui/card-watermark'
import { Icons } from '@/components/ui/icons'
import { cn } from '@/lib/utils'

export interface InventoryDatum {
  item_number: string
  description: string
  location: string
  on_hand_qty: number
  committed_qty: number
  safety_stock: number
  available_qty: number
  at_risk: boolean
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string; payload: InventoryDatum }>
  label?: string
}) {
  if (!active || !payload || !payload.length) return null
  const datum = payload[0]?.payload

  return (
    <div className="rounded-xl border border-white/60 bg-white/95 p-3 shadow-float backdrop-blur-sm">
      <p className="mb-1 text-xs font-medium text-brand-navy">{label}</p>
      {datum && <p className="mb-2 text-[11px] text-muted-foreground">{datum.description} &middot; {datum.location}</p>}
      <div className="space-y-1">
        {payload.map((entry, index) => (
          <div key={index} className="flex items-center gap-2 text-xs">
            <div className="h-2 w-2 rounded-full" style={{ backgroundColor: entry.color }} />
            <span className="capitalize text-muted-foreground">{entry.name}:</span>
            <span className="font-semibold text-brand-navy">{entry.value.toLocaleString()}</span>
          </div>
        ))}
      </div>
      {datum?.at_risk && (
        <p className="mt-2 text-[11px] font-medium text-red-600">Below safety stock</p>
      )}
    </div>
  )
}

interface InventoryChartProps {
  data: InventoryDatum[]
  className?: string
}

export function InventoryChart({ data, className }: InventoryChartProps) {
  const atRiskCount = data.filter((d) => d.at_risk).length
  // At-risk items first so the most urgent bars are visible without scrolling.
  const sorted = [...data].sort((a, b) => Number(b.at_risk) - Number(a.at_risk))
  const chartWidth = Math.max(sorted.length * 70, 600)

  return (
    <Card className={cn('relative overflow-hidden', className)}>
      <CardWatermark opacity={4} scale={1.2} />

      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Icons.archive className="h-5 w-5 text-brand-cornflower" strokeWidth={1.5} />
              Inventory Position
            </CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              Available stock (on-hand minus committed) vs. safety stock, across every node
            </p>
          </div>
          {atRiskCount > 0 && (
            <div className="flex items-center gap-1.5 rounded-full bg-red-50 px-3 py-1 text-xs font-medium text-red-600">
              <Icons.alertTriangle className="h-3.5 w-3.5" />
              {atRiskCount} at risk
            </div>
          )}
        </div>
      </CardHeader>

      <CardContent className="pt-0">
        {data.length === 0 ? (
          <div className="flex h-[240px] items-center justify-center text-sm text-muted-foreground">
            No inventory data available.
          </div>
        ) : (
          <div className="mt-4 h-[280px] w-full overflow-x-auto">
            <div style={{ width: chartWidth, height: '100%' }}>
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={sorted} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(20, 26, 66, 0.06)" vertical={false} />
                  <XAxis
                    dataKey="item_number"
                    axisLine={false}
                    tickLine={false}
                    tick={{ fill: '#7B8AB8', fontSize: 10, fontWeight: 500 }}
                    interval={0}
                    angle={-35}
                    textAnchor="end"
                    height={50}
                  />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#7B8AB8', fontSize: 11 }} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="available_qty" name="Available" radius={[4, 4, 0, 0]}>
                    {sorted.map((entry, index) => (
                      <Cell key={index} fill={entry.at_risk ? '#dc2626' : '#5B8DEF'} />
                    ))}
                  </Bar>
                  <Bar dataKey="safety_stock" name="Safety Stock" fill="#141A42" fillOpacity={0.15} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        <div className="mt-4 flex items-center justify-center gap-6 border-t border-border/30 pt-4">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-brand-cornflower" />
            <span className="text-xs text-muted-foreground">Available (healthy)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-red-600" />
            <span className="text-xs text-muted-foreground">Available (at risk)</span>
          </div>
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-brand-navy/20" />
            <span className="text-xs text-muted-foreground">Safety Stock</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

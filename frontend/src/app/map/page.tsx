'use client'

import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { apiClient } from '@/lib/api-client'
import { Card, CardContent } from '@/components/ui/card'
import { Icons } from '@/components/ui/icons'
import type { Map as LeafletMap } from 'leaflet'

interface GeoLocation {
  location_type: 'warehouse' | 'supplier_country' | 'construction_site'
  location_key: string
  city: string
  country: string
  lat: number
  lng: number
}

interface DecisionPoint {
  lat: number
  lng: number
  label: string
}

interface Decision {
  entity_type: string
  origin: DecisionPoint | null
  destinations: DecisionPoint[]
  summary: string
  reason: string
  created_at: string | null
}

const TYPE_COLORS: Record<GeoLocation['location_type'], string> = {
  warehouse: '#2563eb', // blue
  supplier_country: '#ea580c', // orange
  construction_site: '#059669', // green
}

const TYPE_LABELS: Record<GeoLocation['location_type'], string> = {
  warehouse: 'Warehouse',
  supplier_country: 'Supplier Country',
  construction_site: 'Construction Site',
}

const containerVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.05 } },
}
const itemVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: { opacity: 1, y: 0 },
}

export default function MapPage() {
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<LeafletMap | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [locationCount, setLocationCount] = useState(0)
  const [decisionCount, setDecisionCount] = useState(0)

  useEffect(() => {
    let cancelled = false

    async function init() {
      // Leaflet touches window/document at import time — must only load
      // client-side, never at module top level (breaks `next build`).
      const L = (await import('leaflet')).default

      if (cancelled || !mapContainerRef.current || mapRef.current) return

      const map = L.map(mapContainerRef.current, {
        center: [3.5, 108],
        zoom: 4,
      })
      mapRef.current = map

      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxZoom: 18,
      }).addTo(map)

      // The CDN leaflet.css load is async and doesn't block this script, so
      // the map can initialize before its stylesheet (and therefore its
      // true container size) has actually applied — markers/lines added
      // right after would get the wrong pixel position baked in. Force a
      // recalculation now, and again after the data loads below, so
      // everything added lines up with the visible tiles.
      requestAnimationFrame(() => map.invalidateSize())

      try {
        setIsLoading(true)
        setLoadError(null)

        const [locationsRes, decisionsRes] = await Promise.all([
          apiClient.get<{ locations: GeoLocation[] }>('/api/geo/locations'),
          apiClient.get<{ decisions: Decision[] }>('/api/geo/recent-decisions?limit=10'),
        ])

        if (cancelled) return

        const locations = locationsRes.locations || []
        const decisions = decisionsRes.decisions || []
        setLocationCount(locations.length)
        setDecisionCount(decisions.length)

        for (const loc of locations) {
          if (typeof loc.lat !== 'number' || typeof loc.lng !== 'number') continue
          L.circleMarker([loc.lat, loc.lng], {
            radius: 8,
            color: TYPE_COLORS[loc.location_type] || '#6b7280',
            fillColor: TYPE_COLORS[loc.location_type] || '#6b7280',
            fillOpacity: 0.85,
            weight: 2,
          })
            .addTo(map)
            .bindPopup(
              `<strong>${loc.city}</strong><br/>${TYPE_LABELS[loc.location_type] || loc.location_type}<br/><span style="color:#6b7280">${loc.location_key}</span>`
            )
        }

        for (const decision of decisions) {
          if (!decision.origin) continue
          for (const dest of decision.destinations) {
            const line = L.polyline(
              [
                [decision.origin.lat, decision.origin.lng],
                [dest.lat, dest.lng],
              ],
              { color: '#7c3aed', weight: 2.5, opacity: 0.7, dashArray: '6 4' }
            ).addTo(map)
            line.bindPopup(
              `<strong>${decision.summary}</strong><br/><span style="color:#6b7280">${decision.reason}</span>`
            )
          }
        }

        // See the invalidateSize() call above — the CSS may have finished
        // loading only just now, so recompute once more after everything's
        // been added rather than assume the earlier call was enough.
        map.invalidateSize()
      } catch (err) {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : 'Failed to load map data.')
        }
      } finally {
        if (!cancelled) setIsLoading(false)
      }
    }

    init()

    return () => {
      cancelled = true
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
    }
  }, [])

  return (
    <>
      {/* Leaflet CSS via CDN, not bundled — Next.js/React 19 hoists this into <head> */}
      <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossOrigin="" />

      <motion.div className="space-y-6" variants={containerVariants} initial="hidden" animate="visible">
        <motion.div variants={itemVariants} className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <h1 className="text-display-3 font-bold tracking-tight text-brand-navy lg:text-display-2">Operational Map</h1>
            <p className="mt-1 text-lg text-muted-foreground">
              Warehouses, supplier origins, and construction sites — with the actual routes recent Operator decisions chose.
            </p>
          </div>
          <div className="flex gap-3 text-sm text-muted-foreground">
            <span>{locationCount} locations</span>
            <span>&middot;</span>
            <span>{decisionCount} recent decisions</span>
          </div>
        </motion.div>

        {loadError && (
          <motion.div variants={itemVariants}>
            <Card>
              <CardContent className="flex items-center gap-2 py-4 text-sm text-red-600">
                <Icons.alertCircle className="h-4 w-4 flex-shrink-0" />
                Couldn&apos;t load map data: {loadError}
              </CardContent>
            </Card>
          </motion.div>
        )}

        <motion.div variants={itemVariants} className="flex flex-wrap gap-4 text-sm">
          {(Object.keys(TYPE_COLORS) as GeoLocation['location_type'][]).map((type) => (
            <div key={type} className="flex items-center gap-2">
              <span
                className="inline-block h-3 w-3 rounded-full"
                style={{ backgroundColor: TYPE_COLORS[type] }}
              />
              <span className="text-muted-foreground">{TYPE_LABELS[type]}</span>
            </div>
          ))}
          <div className="flex items-center gap-2">
            <span className="inline-block h-0.5 w-5 border-t-2 border-dashed" style={{ borderColor: '#7c3aed' }} />
            <span className="text-muted-foreground">Decision route (click for details)</span>
          </div>
        </motion.div>

        <motion.div variants={itemVariants}>
          <Card className="overflow-hidden">
            <CardContent className="relative p-0">
              {isLoading && (
                <div className="absolute inset-0 z-[1000] flex items-center justify-center bg-white/60">
                  <Icons.loader className="h-8 w-8 animate-spin text-brand-cornflower" />
                </div>
              )}
              <div ref={mapContainerRef} className="h-[65vh] w-full" />
            </CardContent>
          </Card>
        </motion.div>
      </motion.div>
    </>
  )
}

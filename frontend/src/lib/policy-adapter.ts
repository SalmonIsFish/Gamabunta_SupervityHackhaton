// frontend/src/lib/policy-adapter.ts
//
// Translation layer between the Command Center's richer Policy UI
// (frontend/src/components/ai/policies/PolicyCard.tsx's `Policy`/`PolicyDSL`
// types) and the real backend schema (app/schemas/policy.py). The backend
// was extended to support most of the UI's shape directly (tags, entity_name,
// multi-action `actions`, policy_scope, etc.) — the one deliberate mismatch
// left is `PolicyCondition.operator` (frontend) vs the backend condition
// DSL's `op` key, translated here rather than renamed everywhere the
// frontend type is used, since the backend's structured-condition tree
// ({all|any:[...]}) also has no frontend equivalent and needs its own
// conversion regardless.
//
// The backend also has no concept of `is_active` — that's `status`
// (draft/active/paused/archived), changed only via the activate/deactivate
// endpoints, never via create/update. `syncActiveStatus` below is what
// actually flips it after a save.

import { apiClient } from './api-client'
import type { Policy, PolicyDSL, PolicyCondition } from '@/components/ai/policies/PolicyCard'

// ============================================================================
// Backend shapes (app/schemas/policy.py)
// ============================================================================

export interface BackendPolicyAction {
  type: string
  value?: unknown
  params?: Record<string, unknown> | null
}

export interface BackendPolicy {
  id: number
  name: string
  description: string | null
  policy_type: 'structured' | 'natural_language'
  domain: string | null
  condition: Record<string, unknown> | null
  natural_language_rule: string | null
  action: string | null
  action_params: Record<string, unknown> | null
  actions: BackendPolicyAction[] | null
  tags: string[]
  entity_name: string | null
  policy_scope: string
  summary: string | null
  refined_instruction: string | null
  ai_instruction: string | null
  source: string | null
  priority: number
  status: 'draft' | 'active' | 'paused' | 'archived'
  trigger_count: number
  last_evaluated_at: string | null
  created_by: string | null
  created_at: string
  updated_at: string | null
}

export interface BackendPolicyListResponse {
  items: BackendPolicy[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

// This build's working domain — see CLAUDE.md / NEXT_STEPS.md. New policies
// created through the UI default here since none of the create flows
// (Structured Builder, Create with AI) currently collect a domain field.
export const DEFAULT_POLICY_DOMAIN = 'procurement'

// ============================================================================
// Value coercion
// ============================================================================

/**
 * The Structured Builder stores every condition value as a raw string
 * (it's a plain <input type="text">). Sent as-is, a numeric comparison like
 * `gt`/`lt` against `entity_data.amount` (a real number) would always fail —
 * policy_engine.py's `_apply_op` catches the resulting TypeError and treats
 * it as a silent non-match. Coerce to number/boolean where the string
 * unambiguously represents one; leave everything else as a string.
 */
function coerceConditionValue(raw: unknown): unknown {
  if (typeof raw !== 'string') return raw
  const trimmed = raw.trim()
  if (trimmed === '') return raw
  if (trimmed === 'true') return true
  if (trimmed === 'false') return false
  if (trimmed !== '' && !Number.isNaN(Number(trimmed))) return Number(trimmed)
  return raw
}

// ============================================================================
// Frontend DSL -> backend condition/actions
// ============================================================================

function dslToBackendCondition(dsl: PolicyDSL | null): Record<string, unknown> | null {
  if (!dsl || dsl.conditions.length === 0) return null
  const leaves = dsl.conditions.map((c) => ({
    field: c.field,
    op: c.operator,
    value: coerceConditionValue(c.value),
  }))
  if (leaves.length === 1) return leaves[0]
  return { [dsl.match_mode === 'any' ? 'any' : 'all']: leaves }
}

function dslToBackendActions(dsl: PolicyDSL | null): BackendPolicyAction[] | null {
  if (!dsl || dsl.actions.length === 0) return null
  return dsl.actions.map((a) => ({ type: a.type, value: a.value ?? null, params: a.params ?? null }))
}

// ============================================================================
// Backend condition -> frontend DSL
// ============================================================================

function backendConditionToDsl(condition: Record<string, unknown> | null): {
  conditions: PolicyCondition[]
  match_mode: 'all' | 'any'
} {
  if (!condition) return { conditions: [], match_mode: 'all' }

  const match_mode: 'all' | 'any' = Array.isArray(condition.any) ? 'any' : 'all'
  const rawLeaves = Array.isArray(condition.all)
    ? condition.all
    : Array.isArray(condition.any)
      ? condition.any
      : [condition]

  const conditions = (rawLeaves as Record<string, unknown>[])
    .filter((leaf) => typeof leaf.field === 'string' && typeof leaf.op === 'string')
    .map((leaf) => ({ field: leaf.field as string, operator: leaf.op as string, value: leaf.value }))

  return { conditions, match_mode }
}

// ============================================================================
// Public: BackendPolicy -> frontend Policy
// ============================================================================

export function fromBackendPolicy(p: BackendPolicy): Policy {
  const { conditions, match_mode } = backendConditionToDsl(p.condition)

  const actions: PolicyDSL['actions'] =
    p.actions && p.actions.length > 0
      ? p.actions.map((a) => ({ type: a.type, value: a.value, params: a.params ?? undefined }))
      : p.action
        ? [{ type: p.action, value: undefined, params: p.action_params ?? undefined }]
        : []

  const isLogical = p.policy_type === 'structured'

  return {
    id: String(p.id),
    name: p.name,
    description: p.description || '',
    summary: p.summary,
    natural_language: p.natural_language_rule || '',
    policy_type: isLogical ? 'logical' : 'natural_language',
    policy_scope: (p.policy_scope as Policy['policy_scope']) || 'custom',
    dsl: isLogical && (conditions.length > 0 || actions.length > 0) ? { conditions, actions, match_mode } : null,
    refined_instruction: p.refined_instruction,
    ai_instruction: p.ai_instruction,
    entity_name: p.entity_name,
    is_active: p.status === 'active',
    priority: p.priority,
    tags: p.tags || [],
    source: p.source || undefined,
    created_at: p.created_at,
    updated_at: p.updated_at || p.created_at,
    execution_count: p.trigger_count,
    last_executed_at: p.last_evaluated_at,
    domain: p.domain,
  }
}

// ============================================================================
// Public: frontend form data -> backend create/update payload
// ============================================================================

export interface PolicySaveInput {
  name: string
  description: string
  natural_language: string
  policy_type: 'logical' | 'natural_language'
  refined_instruction: string | null
  entity_name: string | null
  priority: number
  tags: string[]
  dsl: PolicyDSL | null
}

export function toBackendPayload(form: PolicySaveInput, domain: string = DEFAULT_POLICY_DOMAIN) {
  const isLogical = form.policy_type === 'logical'
  return {
    name: form.name,
    description: form.description || null,
    policy_type: isLogical ? 'structured' : 'natural_language',
    domain,
    condition: isLogical ? dslToBackendCondition(form.dsl) : null,
    natural_language_rule: form.natural_language || null,
    actions: isLogical ? dslToBackendActions(form.dsl) : null,
    tags: form.tags,
    entity_name: form.entity_name || null,
    priority: form.priority,
    refined_instruction: form.policy_type === 'natural_language' ? form.refined_instruction : null,
    ai_instruction: form.policy_type === 'natural_language' ? form.natural_language || null : null,
  }
}

// ============================================================================
// Public: lifecycle sync (create/update never touch status)
// ============================================================================

/** After a create/update, flip status via the real lifecycle endpoints if it doesn't already match. */
export async function syncActiveStatus(policyId: number, currentStatus: string, desiredActive: boolean): Promise<void> {
  if (desiredActive && currentStatus !== 'active') {
    await apiClient.post(`/api/ai/policies/${policyId}/activate`)
  } else if (!desiredActive && currentStatus === 'active') {
    await apiClient.post(`/api/ai/policies/${policyId}/deactivate`)
  }
}

/** Delete a policy, deactivating it first if the backend rejects the delete because it's still active. */
export async function deletePolicySafely(policyId: string): Promise<void> {
  try {
    await apiClient.delete(`/api/ai/policies/${policyId}`)
  } catch {
    await apiClient.post(`/api/ai/policies/${policyId}/deactivate`)
    await apiClient.delete(`/api/ai/policies/${policyId}`)
  }
}

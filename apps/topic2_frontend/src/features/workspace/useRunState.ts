/** Server-state hooks: ApplicationRun + artifact queries (spec §27).
 * The backend run is the single source of truth; hooks are read-only queries.
 */

import { useQuery } from '@tanstack/react-query'
import type { ArtifactSnapshot } from '../../domain/artifact'
import { selectLatestByType } from '../../domain/artifact'
import { runsApi } from '../../api/runs'

export function useApplicationRun(runId: string | null) {
  return useQuery({
    queryKey: ['application-run', runId],
    queryFn: () => runsApi.getRun(runId as string),
    enabled: Boolean(runId),
    refetchInterval: (query) =>
      query.state.data && query.state.data.status === 'running' ? 2000 : false,
    retry: 1,
  })
}

export function useRunEvents(runId: string | null, afterSequence = 0) {
  return useQuery({
    queryKey: ['application-run-events', runId, afterSequence],
    queryFn: () => runsApi.getEvents(runId as string, afterSequence),
    enabled: Boolean(runId),
    refetchInterval: (query) =>
      query.state.data && query.state.data.items.some((e) => e.type === 'RUN_COMPLETED' || e.type === 'RUN_FAILED')
        ? false
        : 2000,
    retry: 1,
  })
}

/** Latest physics-to-planning artifact per kind, with full content payloads. */
export function useRunArtifacts(runId: string | null) {
  return useQuery({
    queryKey: ['application-run-artifacts', runId],
    queryFn: async () => {
      const { items } = await runsApi.getArtifacts(runId as string)
      const latest = selectLatestByType(items)
      const snapshots = new Map<string, ArtifactSnapshot<Record<string, unknown>>>()
      await Promise.all(
        [...latest.values()].map(async (meta) => {
          const envelope = await runsApi.getArtifact<Record<string, unknown>>(meta.artifact_id)
          snapshots.set(meta.artifact_type, envelope.content)
        }),
      )
      return snapshots
    },
    enabled: Boolean(runId),
    refetchInterval: 3000,
    retry: 1,
  })
}

export function useAllArtifacts(runId: string | null) {
  return useQuery({
    queryKey: ['application-run-all-artifacts', runId],
    queryFn: () => runsApi.getArtifacts(runId as string),
    enabled: Boolean(runId),
    retry: 1,
  })
}

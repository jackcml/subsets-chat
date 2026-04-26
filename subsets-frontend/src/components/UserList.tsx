import { useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { $api, PRESENCE_QUERY_KEY, type UserResponse } from '@/api/client'
import { useAuth } from '@/auth/useAuth'

type UserListTab = 'all' | 'online'

export function UserList() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<UserListTab>('all')

  const usersQuery = $api.useQuery('get', '/users')
  const followQuery = $api.useQuery('get', '/me/set')

  const presenceQuery = useQuery<Set<number>>({
    queryKey: PRESENCE_QUERY_KEY,
    queryFn: () => new Set<number>(),
    staleTime: Infinity,
    gcTime: Infinity,
  })
  const onlineIds = presenceQuery.data ?? new Set<number>()

  const followedIds = useMemo(
    () => new Set((followQuery.data ?? []).map((entry) => entry.id)),
    [followQuery.data]
  )

  // Local toggles — flipped against the server state. Cleared on save success.
  const [pending, setPending] = useState<Set<number>>(() => new Set())

  const replaceSet = $api.useMutation('put', '/me/set', {
    onSuccess: (data) => {
      queryClient.setQueryData(['get', '/me/set'], data)
      setPending(new Set())
    },
  })

  const candidates = useMemo(
    () => (usersQuery.data ?? []).filter((entry) => entry.id !== user?.id),
    [usersQuery.data, user?.id]
  )

  const onlineCount = useMemo(
    () => candidates.filter((entry) => onlineIds.has(entry.id)).length,
    [candidates, onlineIds]
  )

  const visibleCandidates = useMemo(
    () =>
      tab === 'online'
        ? candidates.filter((entry) => onlineIds.has(entry.id))
        : candidates,
    [tab, candidates, onlineIds]
  )

  const isChecked = (id: number) => {
    const inServer = followedIds.has(id)
    return pending.has(id) ? !inServer : inServer
  }

  const draftIds = useMemo(() => {
    const next = new Set(followedIds)
    for (const id of pending) {
      if (next.has(id)) next.delete(id)
      else next.add(id)
    }
    return next
  }, [followedIds, pending])

  const dirty = pending.size > 0

  const toggle = (target: UserResponse) => {
    setPending((current) => {
      const next = new Set(current)
      if (next.has(target.id)) next.delete(target.id)
      else next.add(target.id)
      return next
    })
  }

  const onSave = () => {
    replaceSet.mutate({ body: { followed_user_ids: Array.from(draftIds) } })
  }

  const isLoading = usersQuery.isLoading || followQuery.isLoading

  return (
    <div className="flex h-full flex-col">
      <div className="px-4 py-3 border-b border-border">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Your set
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          Pick whose messages you want to see in your feed.
        </p>
      </div>
      <div
        role="tablist"
        aria-label="Filter users"
        className="flex border-b border-border px-2"
      >
        <TabButton
          active={tab === 'all'}
          onClick={() => setTab('all')}
          label="All"
          count={candidates.length}
        />
        <TabButton
          active={tab === 'online'}
          onClick={() => setTab('online')}
          label="Online"
          count={onlineCount}
        />
      </div>
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {isLoading && (
          <div className="px-2 py-4 text-sm text-muted-foreground">Loading...</div>
        )}
        {!isLoading && visibleCandidates.length === 0 && (
          <div className="px-2 py-4 text-sm text-muted-foreground">
            {tab === 'online' ? 'Nobody else is online.' : 'No other users yet.'}
          </div>
        )}
        <ul className="flex flex-col gap-0.5">
          {visibleCandidates.map((candidate) => {
            const isOnline = onlineIds.has(candidate.id)
            return (
              <li key={candidate.id}>
                <label className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-muted">
                  <input
                    type="checkbox"
                    checked={isChecked(candidate.id)}
                    onChange={() => toggle(candidate)}
                    className="size-4 accent-primary"
                  />
                  <span className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-sm font-medium">
                      {candidate.display_name}
                    </span>
                    <span className="truncate text-xs text-muted-foreground">
                      @{candidate.username}
                    </span>
                  </span>
                  <span
                    aria-label={isOnline ? 'Online' : 'Offline'}
                    title={isOnline ? 'Online' : 'Offline'}
                    className={cn(
                      'size-2 shrink-0 rounded-full',
                      isOnline ? 'bg-emerald-500' : 'bg-muted-foreground/30'
                    )}
                  />
                </label>
              </li>
            )
          })}
        </ul>
      </div>
      <div className="border-t border-border px-4 py-3">
        <Button
          className="w-full"
          disabled={!dirty || replaceSet.isPending}
          onClick={onSave}
        >
          {replaceSet.isPending ? 'Saving...' : 'Save set'}
        </Button>
        {replaceSet.error && (
          <p className="mt-2 text-xs text-destructive" role="alert">
            Could not save changes.
          </p>
        )}
      </div>
    </div>
  )
}

function TabButton({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean
  onClick: () => void
  label: string
  count: number
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        'flex-1 border-b-2 px-2 py-2 text-xs font-medium transition-colors',
        active
          ? 'border-primary text-foreground'
          : 'border-transparent text-muted-foreground hover:text-foreground'
      )}
    >
      {label}
      <span className="ml-1 text-muted-foreground">({count})</span>
    </button>
  )
}

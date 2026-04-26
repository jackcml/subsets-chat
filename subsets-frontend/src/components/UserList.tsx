import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/ui/button'
import { $api, type UserResponse } from '@/api/client'
import { useAuth } from '@/auth/useAuth'

export function UserList() {
  const { user } = useAuth()
  const queryClient = useQueryClient()

  const usersQuery = $api.useQuery('get', '/users')
  const followQuery = $api.useQuery('get', '/me/set')

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
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {isLoading && (
          <div className="px-2 py-4 text-sm text-muted-foreground">Loading...</div>
        )}
        {!isLoading && candidates.length === 0 && (
          <div className="px-2 py-4 text-sm text-muted-foreground">
            No other users yet.
          </div>
        )}
        <ul className="flex flex-col gap-0.5">
          {candidates.map((candidate) => (
            <li key={candidate.id}>
              <label className="flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 hover:bg-muted">
                <input
                  type="checkbox"
                  checked={isChecked(candidate.id)}
                  onChange={() => toggle(candidate)}
                  className="size-4 accent-primary"
                />
                <span className="flex min-w-0 flex-col">
                  <span className="truncate text-sm font-medium">
                    {candidate.display_name}
                  </span>
                  <span className="truncate text-xs text-muted-foreground">
                    @{candidate.username}
                  </span>
                </span>
              </label>
            </li>
          ))}
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

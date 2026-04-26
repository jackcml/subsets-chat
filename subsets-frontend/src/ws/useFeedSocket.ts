import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  buildWebSocketUrl,
  PRESENCE_QUERY_KEY,
  type FeedMessageResponse,
  type UserResponse,
  type WebSocketServerMessage,
} from '@/api/client'

const FEED_QUERY_KEY = ['get', '/feed'] as const
const USERS_QUERY_KEY = ['get', '/users'] as const
const PING_INTERVAL_MS = 30_000
const RECONNECT_BASE_MS = 1_000
const RECONNECT_MAX_MS = 30_000

export function useFeedSocket(token: string | null): void {
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!token) return

    let socket: WebSocket | null = null
    let reconnectAttempts = 0
    let reconnectTimer: number | null = null
    let pingTimer: number | null = null
    let cancelled = false

    const clearTimers = () => {
      if (reconnectTimer !== null) {
        window.clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      if (pingTimer !== null) {
        window.clearInterval(pingTimer)
        pingTimer = null
      }
    }

    const handleMessage = (incoming: FeedMessageResponse) => {
      queryClient.setQueryData<FeedMessageResponse[] | undefined>(
        FEED_QUERY_KEY,
        (current) => {
          if (!current) {
            queryClient.invalidateQueries({ queryKey: FEED_QUERY_KEY })
            return current
          }
          if (current.some((message) => message.id === incoming.id)) {
            return current
          }
          return [...current, incoming]
        }
      )
    }

    const handleUserJoined = (incoming: UserResponse) => {
      queryClient.setQueryData<UserResponse[] | undefined>(
        USERS_QUERY_KEY,
        (current) => {
          if (!current) {
            queryClient.invalidateQueries({ queryKey: USERS_QUERY_KEY })
            return current
          }
          if (current.some((entry) => entry.id === incoming.id)) {
            return current
          }
          return [...current, incoming]
        }
      )
    }

    const setPresence = (updater: (current: Set<number>) => Set<number>) => {
      queryClient.setQueryData<Set<number>>(PRESENCE_QUERY_KEY, (current) =>
        updater(new Set(current ?? []))
      )
    }

    const handlePresenceInit = (userIds: number[]) => {
      queryClient.setQueryData<Set<number>>(PRESENCE_QUERY_KEY, new Set(userIds))
    }

    const handleUserOnline = (userId: number) => {
      setPresence((next) => {
        next.add(userId)
        return next
      })
    }

    const handleUserOffline = (userId: number) => {
      setPresence((next) => {
        next.delete(userId)
        return next
      })
    }

    const connect = () => {
      if (cancelled) return
      const next = new WebSocket(buildWebSocketUrl())
      socket = next

      next.addEventListener('open', () => {
        reconnectAttempts = 0
        next.send(JSON.stringify({ type: 'auth', access_token: token }))
        pingTimer = window.setInterval(() => {
          if (next.readyState === WebSocket.OPEN) {
            next.send('ping')
          }
        }, PING_INTERVAL_MS)
      })

      next.addEventListener('message', (event) => {
        try {
          const payload = JSON.parse(event.data as string) as WebSocketServerMessage
          if (payload.type === 'message' && payload.message) {
            handleMessage(payload.message)
          } else if (payload.type === 'user_joined' && payload.user) {
            handleUserJoined(payload.user)
          } else if (payload.type === 'presence_init') {
            handlePresenceInit(payload.user_ids)
          } else if (payload.type === 'user_online') {
            handleUserOnline(payload.user_id)
          } else if (payload.type === 'user_offline') {
            handleUserOffline(payload.user_id)
          }
        } catch {
          // Ignore malformed frames
        }
      })

      next.addEventListener('close', () => {
        clearTimers()
        queryClient.setQueryData<Set<number>>(PRESENCE_QUERY_KEY, new Set())
        if (cancelled) return
        const delay = Math.min(
          RECONNECT_MAX_MS,
          RECONNECT_BASE_MS * 2 ** reconnectAttempts
        )
        reconnectAttempts += 1
        reconnectTimer = window.setTimeout(connect, delay)
      })

      next.addEventListener('error', () => {
        next.close()
      })
    }

    connect()

    return () => {
      cancelled = true
      clearTimers()
      if (socket && socket.readyState <= WebSocket.OPEN) {
        socket.close()
      }
    }
  }, [token, queryClient])
}

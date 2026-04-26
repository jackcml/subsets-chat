import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  API_BASE_URL,
  fetchClient,
  getStoredToken,
  onUnauthorized,
  setStoredToken,
  type UserResponse,
} from '@/api/client'
import { AuthContext, type AuthContextValue } from './AuthContextDef'

type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>(() =>
    getStoredToken() ? 'loading' : 'anonymous'
  )
  const [user, setUser] = useState<UserResponse | null>(null)
  const queryClient = useQueryClient()
  const hydratedRef = useRef(false)

  const clearSession = useCallback(() => {
    setStoredToken(null)
    setUser(null)
    setStatus('anonymous')
    queryClient.clear()
  }, [queryClient])

  useEffect(() => {
    if (hydratedRef.current) return
    hydratedRef.current = true
    const token = getStoredToken()
    if (!token) return

    let cancelled = false
    fetchClient
      .GET('/me')
      .then((result) => {
        if (cancelled) return
        if (result.error || !result.data) {
          clearSession()
          return
        }
        setUser(result.data)
        setStatus('authenticated')
      })
      .catch(() => {
        if (!cancelled) clearSession()
      })

    return () => {
      cancelled = true
    }
  }, [clearSession])

  useEffect(() => onUnauthorized(clearSession), [clearSession])

  const acceptToken = useCallback(
    (token: string, nextUser: UserResponse) => {
      setStoredToken(token)
      setUser(nextUser)
      setStatus('authenticated')
      queryClient.clear()
    },
    [queryClient]
  )

  const login = useCallback(
    async (username: string, password: string) => {
      const body = new URLSearchParams({
        grant_type: 'password',
        username,
        password,
      })
      const response = await fetch(`${API_BASE_URL}/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body,
      })
      if (!response.ok) {
        const detail = await response
          .json()
          .then((data) => data?.detail)
          .catch(() => null)
        throw new Error(typeof detail === 'string' ? detail : 'Sign-in failed')
      }
      const data = (await response.json()) as {
        access_token: string
        user: UserResponse
      }
      acceptToken(data.access_token, data.user)
    },
    [acceptToken]
  )

  const register = useCallback(
    async (username: string, displayName: string, password: string) => {
      const result = await fetchClient.POST('/auth/register', {
        body: { username, display_name: displayName, password },
      })
      if (result.error || !result.data) {
        const detail = (result.error as { detail?: unknown } | undefined)?.detail
        throw new Error(
          typeof detail === 'string' ? detail : 'Registration failed'
        )
      }
      acceptToken(result.data.access_token, result.data.user)
    },
    [acceptToken]
  )

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, register, logout: clearSession }),
    [status, user, login, register, clearSession]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

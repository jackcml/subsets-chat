import { createContext } from 'react'
import type { UserResponse } from '@/api/client'

type AuthStatus = 'loading' | 'authenticated' | 'anonymous'

export interface AuthContextValue {
  status: AuthStatus
  user: UserResponse | null
  login: (username: string, password: string) => Promise<void>
  register: (
    username: string,
    displayName: string,
    password: string
  ) => Promise<void>
  logout: () => void
}

export const AuthContext = createContext<AuthContextValue | null>(null)

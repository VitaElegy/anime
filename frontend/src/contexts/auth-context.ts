import { createContext } from 'react'
import type { UserPublic } from '@/types'

export interface AuthContextValue {
  user: UserPublic | null
  loading: boolean
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<UserPublic>
  register: (username: string, password: string) => Promise<UserPublic>
  logout: () => Promise<void>
  refreshUser: () => Promise<UserPublic | null>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

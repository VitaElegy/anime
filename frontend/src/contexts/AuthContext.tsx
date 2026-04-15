import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { getCurrentUser, getStoredAuthToken, loginAccount, logoutAccount, persistAuthToken, registerAccount } from '@/api'
import type { AuthResponse, UserPublic } from '@/types'
import { AuthContext, type AuthContextValue } from './auth-context'

function applyAuth(response: AuthResponse): UserPublic {
  persistAuthToken(response.token)
  return response.user
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserPublic | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshUser = async (): Promise<UserPublic | null> => {
    const token = getStoredAuthToken()
    if (!token) {
      setUser(null)
      return null
    }
    try {
      const nextUser = await getCurrentUser()
      setUser(nextUser)
      return nextUser
    } catch {
      persistAuthToken('')
      setUser(null)
      return null
    }
  }

  useEffect(() => {
    void refreshUser().finally(() => setLoading(false))
  }, [])

  const login = async (username: string, password: string) => {
    const user = applyAuth(await loginAccount(username, password))
    setUser(user)
    return user
  }

  const register = async (username: string, password: string) => {
    const user = applyAuth(await registerAccount(username, password))
    setUser(user)
    return user
  }

  const logout = async () => {
    try {
      await logoutAccount()
    } finally {
      persistAuthToken('')
      setUser(null)
    }
  }

  const value = useMemo<AuthContextValue>(() => ({
    user,
    loading,
    isAuthenticated: Boolean(user),
    login,
    register,
    logout,
    refreshUser,
  }), [user, loading])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

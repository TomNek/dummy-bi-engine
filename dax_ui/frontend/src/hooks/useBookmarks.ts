import { useState, useCallback } from 'react'
import { useAppStore, useReportStore } from '@/stores'
import {
  getBookmarks,
  saveBookmarks,
  createBookmark,
  updateBookmark,
  deleteBookmark,
  applyBookmark,
  type Bookmark,
  type BookmarkApplyResponse,
} from '@/lib/api'

/** Capture options for creating/updating a bookmark */
export interface BookmarkCaptureOptions {
  capture_page: boolean
  capture_data: boolean
  capture_display: boolean
  capture_visual_layout: boolean
  capture_visual_design: boolean
}

interface UseBookmarksReturn {
  // State
  bookmarks: Bookmark[]
  loading: boolean
  error: string | null

  // Load
  loadBookmarks: () => Promise<void>

  // CRUD
  create: (bookmark: Omit<Bookmark, 'id'>) => Promise<{ success: boolean; bookmark?: Bookmark; error?: string }>
  update: (bookmarkId: string, fields: Partial<Bookmark>) => Promise<{ success: boolean; error?: string }>
  remove: (bookmarkId: string) => Promise<{ success: boolean; error?: string }>
  saveAll: (items: Bookmark[]) => Promise<{ success: boolean; error?: string }>

  // Apply
  apply: (bookmarkId: string) => Promise<{ success: boolean; data?: BookmarkApplyResponse; error?: string }>

  // Helpers
  getById: (bookmarkId: string) => Bookmark | undefined

  /** Get the current visual visibility map from the report store */
  getCurrentVisibility: () => Record<string, boolean>
}

export function useBookmarks(): UseBookmarksReturn {
  const projectPath = useAppStore(s => s.projectPath)

  const [bookmarks, setBookmarks] = useState<Bookmark[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadBookmarks = useCallback(async () => {
    if (!projectPath) return
    setLoading(true)
    setError(null)
    const result = await getBookmarks(projectPath)
    if (result.error) {
      setError(result.error)
      setBookmarks([])
    } else {
      setBookmarks(result.data?.bookmarks || [])
    }
    setLoading(false)
  }, [projectPath])

  const create = useCallback(async (bookmark: Omit<Bookmark, 'id'>) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    setError(null)
    const result = await createBookmark(bookmark, projectPath)
    if (result.error) {
      setError(result.error)
      return { success: false, error: result.error }
    }
    // Server returns full bookmarks list; update local state
    const all = result.data?.bookmarks || []
    setBookmarks(all)
    const created = all[all.length - 1]
    return { success: true, bookmark: created }
  }, [projectPath])

  const update = useCallback(async (bookmarkId: string, fields: Partial<Bookmark>) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    setError(null)
    const result = await updateBookmark(bookmarkId, fields, projectPath)
    if (result.error) {
      setError(result.error)
      return { success: false, error: result.error }
    }
    setBookmarks(result.data?.bookmarks || [])
    return { success: true }
  }, [projectPath])

  const remove = useCallback(async (bookmarkId: string) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    setError(null)
    const result = await deleteBookmark(bookmarkId, projectPath)
    if (result.error) {
      setError(result.error)
      return { success: false, error: result.error }
    }
    setBookmarks(result.data?.bookmarks || [])
    return { success: true }
  }, [projectPath])

  const saveAll = useCallback(async (items: Bookmark[]) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    setError(null)
    const result = await saveBookmarks({ bookmarks: items }, projectPath)
    if (result.error) {
      setError(result.error)
      return { success: false, error: result.error }
    }
    setBookmarks(result.data?.bookmarks || items)
    return { success: true }
  }, [projectPath])

  const apply = useCallback(async (bookmarkId: string) => {
    if (!projectPath) return { success: false, error: 'No project loaded' }
    setError(null)
    const result = await applyBookmark(bookmarkId, projectPath)
    if (result.error) {
      setError(result.error)
      return { success: false, error: result.error }
    }
    return { success: true, data: result.data }
  }, [projectPath])

  const getById = useCallback((bookmarkId: string) => {
    return bookmarks.find(b => b.id === bookmarkId)
  }, [bookmarks])

  const getCurrentVisibility = useCallback((): Record<string, boolean> => {
    return useReportStore.getState().visualVisibility
  }, [])

  return {
    bookmarks,
    loading,
    error,
    loadBookmarks,
    create,
    update,
    remove,
    saveAll,
    apply,
    getById,
    getCurrentVisibility,
  }
}

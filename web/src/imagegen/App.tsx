import { useEffect, useState } from 'react'
import { initStore } from './store'
import { useStore } from './store'
import { buildSettingsFromUrlParams, clearUrlSettingParams, hasUrlSettingParams } from './lib/urlSettings'
import { useDockerApiUrlMigrationNotice } from './hooks/useDockerApiUrlMigrationNotice'
import Header from './components/Header'
import AmazonPlanner from './components/AmazonPlanner'
import ImageEditorPage from './components/ImageEditorPage'
import SyntheticPerformerTaggerPage from './components/SyntheticPerformerTaggerPage'
import SearchBar from './components/SearchBar'
import TaskGrid from './components/TaskGrid'
import InputBar from './components/InputBar'
import DetailModal from './components/DetailModal'
import Lightbox from './components/Lightbox'
import SettingsModal from './components/SettingsModal'
import ConfirmDialog from './components/ConfirmDialog'
import Toast from './components/Toast'
import MaskEditorModal from './components/MaskEditorModal'
import ImageContextMenu from './components/ImageContextMenu'
import { useGlobalClickSuppression } from './lib/clickSuppression'

// The studio is mounted under a react-router *path* route, so the hash is free
// for the studio's own sub-view routing (upstream routes its views the same way).
export type AppView = 'home' | 'editor' | 'tagger'

function getAppViewFromHash(): AppView {
  const route = window.location.hash.replace(/^#\/?/, '')
  if (route === 'editor' || route === 'seedream-pro') return 'editor'
  if (route === 'tagger') return 'tagger'
  return 'home'
}

export default function App() {
  const setSettings = useStore((s) => s.setSettings)
  const [view, setView] = useState<AppView>(getAppViewFromHash)
  useDockerApiUrlMigrationNotice()
  useGlobalClickSuppression()

  // Keep the view in sync with back/forward navigation and manual hash edits.
  useEffect(() => {
    const syncViewFromHash = () => setView(getAppViewFromHash())
    window.addEventListener('hashchange', syncViewFromHash)
    return () => window.removeEventListener('hashchange', syncViewFromHash)
  }, [])

  useEffect(() => {
    const searchParams = new URLSearchParams(window.location.search)
    const nextSettings = buildSettingsFromUrlParams(useStore.getState().settings, searchParams)

    setSettings(nextSettings)

    if (hasUrlSettingParams(searchParams)) {
      clearUrlSettingParams(searchParams)

      const nextSearch = searchParams.toString()
      const nextUrl = `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ''}${window.location.hash}`
      window.history.replaceState(null, '', nextUrl)
    }

    initStore()
    useStore.getState().setAppMode('gallery')
  }, [setSettings])

  useEffect(() => {
    const preventPageImageDrag = (e: DragEvent) => {
      if ((e.target as HTMLElement | null)?.closest('img')) {
        e.preventDefault()
      }
    }

    document.addEventListener('dragstart', preventPageImageDrag)
    return () => document.removeEventListener('dragstart', preventPageImageDrag)
  }, [])

  const navigate = (nextView: AppView) => {
    setView(nextView)
    if (nextView !== 'home') {
      const hash = `#/${nextView}`
      if (window.location.hash !== hash) window.location.hash = `/${nextView}`
      return
    }
    if (window.location.hash) {
      // Drop the hash without pushing a history entry or jump-scrolling the page.
      const { pathname, search } = window.location
      window.history.replaceState(null, '', `${pathname}${search}`)
    }
  }

  return (
    <>
      <Header activeView={view} onNavigate={navigate} />
      <main data-home-main data-drag-select-surface className="home-main-with-dock pb-48 lg:pb-10">
        <div className={`safe-area-x mx-auto lg:!px-6 ${view === 'editor' ? 'max-w-[96rem]' : 'max-w-7xl'}`}>
          {view === 'editor' ? (
            <ImageEditorPage />
          ) : view === 'tagger' ? (
            <SyntheticPerformerTaggerPage />
          ) : (
            <>
              <AmazonPlanner />
              <SearchBar />
              <TaskGrid />
            </>
          )}
        </div>
      </main>
      {view === 'home' && <InputBar />}
      <DetailModal />
      <Lightbox />
      <SettingsModal />
      <ConfirmDialog />
      <Toast />
      <MaskEditorModal />
      <ImageContextMenu />
    </>
  )
}

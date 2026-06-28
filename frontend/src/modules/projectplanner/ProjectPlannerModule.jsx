import { useRef, useState } from 'react'
import { ds } from '../../utils/ds'
import { useIsMobile } from '../../hooks/useIsMobile'
import { FolderKanban, Plus, FolderOpen, ChevronLeft, AlertTriangle } from 'lucide-react'

const TOOL_URL = '/tools/project-planner.html'

export default function ProjectPlannerModule() {
  const fileInputRef = useRef(null)
  const isMobile = useIsMobile()
  // planSource drives the iframe declaratively — avoids any ref-timing issue
  // where the iframe doesn't exist yet when we'd try to set its src/srcDoc.
  //   null                          -> show the start screen
  //   { type: 'url', value }        -> iframe src = value (fresh blank tool)
  //   { type: 'doc', value }        -> iframe srcDoc = value (a previously saved plan)
  const [planSource, setPlanSource] = useState(null)
  const [error, setError] = useState('')

  function startNewPlan() {
    setError('')
    setPlanSource({ type: 'url', value: TOOL_URL })
  }

  function openFilePicker() {
    setError('')
    fileInputRef.current?.click()
  }

  function handleFilePicked(e) {
    const file = e.target.files && e.target.files[0]
    if (!file) return

    if (!file.name.toLowerCase().endsWith('.html')) {
      setError('That doesn\'t look like a saved plan file. Choose the .html file you downloaded from "Save plan as file".')
      e.target.value = ''
      return
    }

    const reader = new FileReader()
    reader.onload = () => {
      setPlanSource({ type: 'doc', value: reader.result })
    }
    reader.onerror = () => setError('Could not read that file. Please try again.')
    reader.readAsText(file)
    e.target.value = ''
  }

  function backToStart() {
    setPlanSource(null)
    setError('')
  }

  if (planSource) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', minHeight: 'calc(100vh - 60px)' }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          padding: isMobile ? '12px 16px' : '14px 24px',
          background: ds.white, borderBottom: `1px solid ${ds.border}`,
        }}>
          <button
            onClick={backToStart}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              background: 'none', border: 'none', cursor: 'pointer',
              color: ds.teal, fontFamily: ds.fontDm, fontSize: 13.5, fontWeight: 500,
              padding: '6px 4px', minHeight: 44,
            }}
          >
            <ChevronLeft size={16} strokeWidth={2.2} />
            Choose a different plan
          </button>
        </div>
        <iframe
          key={planSource.type === 'url' ? planSource.value : 'saved-plan'}
          title="Project Planner"
          src={planSource.type === 'url' ? planSource.value : undefined}
          srcDoc={planSource.type === 'doc' ? planSource.value : undefined}
          style={{ flex: 1, width: '100%', border: 'none', minHeight: isMobile ? '70vh' : '80vh' }}
        />
      </div>
    )
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      minHeight: 'calc(100vh - 60px)', padding: isMobile ? '32px 20px' : '40px 28px',
      textAlign: 'center', background: ds.light,
    }}>
      <div style={{
        marginBottom: 16, width: 64, height: 64, borderRadius: ds.radius.lg,
        background: ds.mint, display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <FolderKanban size={30} color={ds.teal} strokeWidth={1.7} />
      </div>

      <h1 style={{
        fontFamily: ds.fontSyne, fontWeight: 700, fontSize: isMobile ? 19 : 22,
        color: ds.dark, margin: '0 0 8px',
      }}>
        Project Planner
      </h1>
      <p style={{
        fontFamily: ds.fontDm, fontSize: 14, color: ds.gray, lineHeight: 1.6,
        maxWidth: 420, margin: '0 0 28px',
      }}>
        Build a project timeline with execution plans, approvals, and attached
        documents. Your plan lives in a file you save and keep — start fresh,
        or continue one you've already saved.
      </p>

      <div style={{
        display: 'flex', flexDirection: isMobile ? 'column' : 'row',
        gap: 12, width: isMobile ? '100%' : 'auto', maxWidth: isMobile ? 320 : undefined,
      }}>
        <button
          onClick={startNewPlan}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            background: ds.teal, color: ds.white, border: 'none',
            borderRadius: ds.radius.md, padding: '13px 22px',
            fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 14,
            cursor: 'pointer', minHeight: 44, boxShadow: ds.cardShadow,
            transition: 'background 0.15s',
          }}
        >
          <Plus size={16} strokeWidth={2.4} />
          Start a new plan
        </button>
        <button
          onClick={openFilePicker}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
            background: ds.white, color: ds.dark, border: `1px solid ${ds.border}`,
            borderRadius: ds.radius.md, padding: '13px 22px',
            fontFamily: ds.fontSyne, fontWeight: 600, fontSize: 14,
            cursor: 'pointer', minHeight: 44,
            transition: 'background 0.15s',
          }}
        >
          <FolderOpen size={16} strokeWidth={1.9} />
          Continue an existing plan
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".html"
          style={{ display: 'none' }}
          onChange={handleFilePicked}
        />
      </div>

      {error && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: 8,
          marginTop: 20, maxWidth: 420, textAlign: 'left',
          background: '#FFF3F0', border: `1px solid ${ds.red}33`,
          borderRadius: ds.radius.sm, padding: '10px 14px',
        }}>
          <AlertTriangle size={15} color={ds.red} strokeWidth={2} style={{ flexShrink: 0, marginTop: 2 }} />
          <p style={{ fontFamily: ds.fontDm, fontSize: 13, color: ds.red, margin: 0, lineHeight: 1.5 }}>
            {error}
          </p>
        </div>
      )}
    </div>
  )
}

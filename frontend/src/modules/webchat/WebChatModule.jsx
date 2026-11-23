/**
 * frontend/src/modules/webchat/WebChatModule.jsx — WEBCHAT-RESULTS-1 / WEBCHAT-CHATS-1
 * The Web chat page in the left menu (under Conversations): Results (how the chat is doing) and Chats (every chat, including visitors
 * who left no contact). Owner, operations manager and admin only; the server checks again on every call.
 */
import { useState } from 'react'
import { ds } from '../../utils/ds'
import WebChatResults from './WebChatResults'
import WebChatChats from './WebChatChats'

const TABS = [['results', 'Results'], ['chats', 'Chats']]

export default function WebChatModule() {
  const [tab, setTab] = useState('results')
  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: ds.dark, margin: '0 0 4px', fontFamily: ds.fontDm }}>Web chat</h1>
      <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 12px' }}>How visitors find and use Chioma on your website, store page and ads.</p>
      <div role="tablist" style={{ display: 'flex', gap: 4, borderBottom: `1px solid ${ds.border}`, marginBottom: 16 }}>
        {TABS.map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            style={{ minHeight: 44, padding: '8px 16px', border: 0, background: 'none', cursor: 'pointer', fontSize: 14, fontWeight: tab === k ? 700 : 500,
              color: tab === k ? ds.teal : ds.gray, borderBottom: `2px solid ${tab === k ? ds.teal : 'transparent'}`, marginBottom: -1 }}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'results' ? <WebChatResults /> : <WebChatChats />}
    </div>
  )
}

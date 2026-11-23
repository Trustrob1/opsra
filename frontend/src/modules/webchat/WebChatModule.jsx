/**
 * frontend/src/modules/webchat/WebChatModule.jsx — WEBCHAT-RESULTS-1
 * The Web chat page in the left menu (under Conversations): how the website chat is doing. Results now; the Chats tab (every chat, including
 * visitors who left no contact) is the next step. Owner, operations manager and admin only; the server checks again on every call.
 */
import { ds } from '../../utils/ds'
import WebChatResults from './WebChatResults'

export default function WebChatModule() {
  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ fontSize: 22, fontWeight: 700, color: ds.dark, margin: '0 0 4px', fontFamily: ds.fontDm }}>Web chat</h1>
      <p style={{ fontSize: 13, color: ds.gray, margin: '0 0 16px' }}>How visitors find and use Chioma on your website, store page and ads.</p>
      <WebChatResults />
    </div>
  )
}

/*!
 * Opsra chat bubble (WEBCHAT-EMBED-1)
 * Add to a website:
 *   <script src="https://opsra.com.ng/widget.js" data-key="wc_XXXXXXXX" async></script>
 * Optional attributes: data-source="homepage" (shows up in your chat stats), data-api="https://..." (testing only).
 * Page controls: window.OpsraChat.open(), .close(), .toggle().
 * The bubble and the panel live in a shadow root so the website's own styles cannot break them.
 */
(function () {
  'use strict'
  if (window.__opsraChatLoaded) return
  var script = document.currentScript
  if (!script) return
  var key = script.getAttribute('data-key')
  if (!key || !/^wc_[A-Za-z0-9_-]{8,40}$/.test(key)) return
  window.__opsraChatLoaded = true

  var chatBase = new URL(script.src, location.href).origin
  var api = (script.getAttribute('data-api') || 'https://api.opsra.com.ng/api/v1').replace(/\/+$/, '')
  var source = (script.getAttribute('data-source') || 'website').replace(/[^A-Za-z0-9_-]/g, '').slice(0, 30) || 'website'

  function start() {
    fetch(api + '/public/webchat/' + key + '/widget', { credentials: 'omit' })
      .then(function (r) { return r.json() })
      .then(function (j) { var d = j && j.data; if (d && d.allowed) build(d) })
      .catch(function () { /* the website keeps working without the bubble */ })
  }

  function build(d) {
    var brand = /^#[0-9a-fA-F]{6}$/.test(d.brand_color || '') ? d.brand_color : '#028090'
    var name = String(d.business_name || 'us').slice(0, 80)
    var left = d.side === 'left'

    var host = document.createElement('div')
    host.setAttribute('data-opsra-chat', '')
    host.style.cssText = 'all:initial;position:fixed;z-index:2147483000;bottom:0;' + (left ? 'left:0;' : 'right:0;') + 'width:0;height:0'
    var root = host.attachShadow({ mode: 'open' })
    root.innerHTML =
      '<style>' +
      ':host{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}' +
      '*{box-sizing:border-box}' +
      '.btn{position:fixed;bottom:20px;' + (left ? 'left' : 'right') + ':20px;width:60px;height:60px;border:0;border-radius:999px;background:' + brand + ';color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;box-shadow:0 6px 20px rgba(20,34,43,.28);transition:transform .15s ease}' +
      '.btn:hover{transform:scale(1.06)}.btn:focus-visible{outline:3px solid #fff;box-shadow:0 0 0 5px ' + brand + '}' +
      '.btn svg{width:28px;height:28px}.btn .x{display:none}.open .btn .c{display:none}.open .btn .x{display:block}' +
      '.panel{position:fixed;bottom:92px;' + (left ? 'left' : 'right') + ':20px;width:380px;height:min(640px,calc(100dvh - 112px));background:#fff;border-radius:18px;overflow:hidden;box-shadow:0 12px 40px rgba(20,34,43,.3);opacity:0;transform:translateY(12px) scale(.98);pointer-events:none;visibility:hidden;transition:opacity .15s ease,transform .15s ease,visibility 0s .15s}' +
      '.open .panel{opacity:1;transform:none;pointer-events:auto;visibility:visible;transition:opacity .15s ease,transform .15s ease}' +
      'iframe{width:100%;height:100%;border:0;background:#fff;display:block}' +
      '@media (max-width:480px){.panel{inset:0;width:100%;height:100dvh;border-radius:0}.open .btn{display:none}}' +
      '@media (prefers-reduced-motion:reduce){.btn,.panel{transition:none}}' +
      '</style>' +
      '<div class="wrap">' +
      '<div class="panel" role="dialog" aria-label="Chat with ' + name.replace(/[<>"&]/g, '') + '"></div>' +
      '<button class="btn" type="button" aria-expanded="false">' +
      '<svg class="c" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 5.5h16v11H9.5L5 20v-3.5H4z"/></svg>' +
      '<svg class="x" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
      '</button></div>'

    var wrap = root.querySelector('.wrap')
    var panel = root.querySelector('.panel')
    var btn = root.querySelector('.btn')
    btn.setAttribute('aria-label', 'Chat with ' + name)
    var frame = null
    var isOpen = false

    function ensureFrame() {
      if (frame) return
      frame = document.createElement('iframe')
      frame.title = 'Chat with ' + name
      frame.setAttribute('allow', 'microphone; clipboard-write')
      frame.src = chatBase + '/c/' + key + '?embed=1&s=' + encodeURIComponent(source) + '&po=' + encodeURIComponent(location.origin)
      panel.appendChild(frame)
    }
    function setOpen(v) {
      isOpen = !!v
      if (isOpen) ensureFrame()
      wrap.classList.toggle('open', isOpen)
      btn.setAttribute('aria-expanded', String(isOpen))
      btn.setAttribute('aria-label', isOpen ? 'Close chat' : 'Chat with ' + name)
      if (isOpen && frame) setTimeout(function () { try { frame.focus() } catch (e) { /* ignore */ } }, 160)
      if (!isOpen) { try { btn.focus() } catch (e) { /* ignore */ } }
    }
    btn.addEventListener('click', function () { setOpen(!isOpen) })
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && isOpen) setOpen(false) })
    window.addEventListener('message', function (e) {
      if (e.origin !== chatBase || !e.data || e.data.source !== 'opsra-chat') return
      if (e.data.type === 'close') setOpen(false)
    })
    window.OpsraChat = { open: function () { setOpen(true) }, close: function () { setOpen(false) }, toggle: function () { setOpen(!isOpen) } }
    document.body.appendChild(host)
  }

  if (document.body) start()
  else document.addEventListener('DOMContentLoaded', start)
})()

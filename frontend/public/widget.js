/*!
 * Opsra chat launcher (WEBCHAT-EMBED-1, WEBCHAT-BUBBLE-1: Chioma)
 * Add to a website:
 *   <script src="https://opsra.com.ng/widget.js" data-key="wc_XXXXXXXX" async></script>
 * Optional attributes: data-source="homepage" (shows up in your chat stats), data-api="https://..." (testing only).
 * Page controls: window.OpsraChat.open(), .close(), .toggle(), .ask('a question').
 * Buttons: data-chioma="open" opens the chat, data-chioma-ask="What do you charge?" opens it with that question,
 *   data-chioma-menu="<button id>" opens it with one of the chat buttons already tapped,
 *   data-chioma-open="shop" opens it with the Shop panel showing (no typed sentence, so nothing can be misread).
 * Ask bar (ASKBAR-1, when switched on in Settings): put <div data-chioma-slot></div> where it should sit (add data-chioma-theme="dark" on a dark section);
 *   without one it docks at the bottom of the screen. It wears the same look as the chat; data-chioma-theme="dark" or "light" forces one.
 *   Visitors can minimize it into the round launcher.
 * The launcher and the panel live in a shadow root so the website's own styles cannot break them.
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
      .catch(function () { /* the website keeps working without the launcher */ })
  }

  // What the visitor is looking at, worked out in the browser only (nothing is sent anywhere).
  function pageHint() {
    var p = (location.pathname || '').toLowerCase()
    if (/cart|basket|checkout/.test(p)) return 'cart'
    if (/book|appointment|schedule|reserv/.test(p)) return 'booking'
    if (/product|item|\/p\/|\/shop\/.+/.test(p)) return 'product'
    return 'home'
  }
  // WEBCHAT-CATALOG-1c: the real product name when the page declares one (schema.org Product or an og:type "product" page).
  // Read in the browser only, shown as plain text, cut to 40 characters; if the page says nothing, the fixed line is used.
  function pageProduct() {
    var name = ''
    try {
      var nodes = document.querySelectorAll('script[type="application/ld+json"]')
      for (var i = 0; i < nodes.length && !name; i++) {
        var j = JSON.parse(nodes[i].textContent || 'null')
        var list = Array.isArray(j) ? j : (j && j['@graph'] ? j['@graph'] : [j])
        for (var k = 0; k < list.length && !name; k++) {
          var t = list[k] && list[k]['@type']
          if (t && (t === 'Product' || (Array.isArray(t) && t.indexOf('Product') >= 0)) && typeof list[k].name === 'string') name = list[k].name
        }
      }
      if (!name) {
        var ty = document.querySelector('meta[property="og:type"]'), ti = document.querySelector('meta[property="og:title"]')
        if (ty && /product/i.test(ty.content || '') && ti) name = ti.content || ''
      }
    } catch (e) { name = '' }
    name = String(name).replace(/\s+/g, ' ').trim()
    return name.length > 40 ? name.slice(0, 39).replace(/\s+$/, '') + '\u2026' : name
  }
  var GREETING = {
    home: 'Hi, I’m Chioma. Ask me anything about {n}.',
    product: 'Questions about this item? I can help.',
    cart: 'Need a hand with your order? I’m here.',
    booking: 'Want to book? I can find a time for you.'
  }

  function store(k, v) { try { if (v === undefined) return sessionStorage.getItem(k); sessionStorage.setItem(k, v) } catch (e) { /* storage can be blocked */ } return null }

  function build(d) {
    var brand = /^#[0-9a-fA-F]{6}$/.test(d.brand_color || '') ? d.brand_color : '#028090'
    // The same look as the chat the business chose (webchatTheme.js): its theme colours, and the Opsra blue accent when the old default colour was never changed.
    var THEMES = {
      classic: { dark: false, surface: '#FFFFFF', ink: '#14222B', muted: '#566770', line: '#DCE4E8', field: '#F4F7F8', fieldLine: '#B9C6CC' },
      blue: { dark: false, surface: '#FFFFFF', ink: '#1B1F28', muted: '#5B6270', line: '#E1E5EC', field: '#F4F6FB', fieldLine: '#B4BBC8' },
      midnight: { dark: true, surface: '#1B2029', ink: '#F2F4F8', muted: '#A5ADBB', line: '#2A303B', field: '#14181F', fieldLine: '#3A4252' },
      ink: { dark: false, surface: '#FFFFFF', ink: '#1B1F28', muted: '#5B6270', line: '#E9ECF2', field: '#F1F3F7', fieldLine: '#B4BBC8' }
    }
    var themeId = THEMES[d.chat_theme] ? d.chat_theme : 'classic'
    var T = THEMES[themeId]
    if (themeId !== 'classic' && brand.toLowerCase() === '#028090') brand = '#2467E3'
    var name = String(d.business_name || 'us').slice(0, 80)
    var left = d.side === 'left'
    var online = !!d.online
    var side = left ? 'left' : 'right'
    var img = chatBase + '/chioma/chioma-face-'
    var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches

    var host = document.createElement('div')
    host.setAttribute('data-opsra-chat', '')
    host.style.cssText = 'all:initial;position:fixed;z-index:2147483000;bottom:0;' + side + ':0;width:0;height:0'
    var root = host.attachShadow({ mode: 'open' })
    root.innerHTML =
      '<style>' +
      '.wrap,.wrap *{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}' +
      '*{box-sizing:border-box}' +
      '.btn{position:fixed;bottom:calc(20px + env(safe-area-inset-bottom,0px));' + side + ':20px;height:60px;min-width:60px;border:0;border-radius:999px;background:' + brand + ';color:#fff;cursor:pointer;display:flex;align-items:center;padding:0 8px;gap:0;box-shadow:0 6px 20px rgba(20,34,43,.28);transition:transform .15s ease}' +
      '.btn:hover{transform:scale(1.04)}.btn:focus-visible{outline:3px solid #fff;box-shadow:0 0 0 5px ' + brand + '}' +
      '.av{display:block;position:relative;width:44px;height:44px;flex:none;border-radius:50%;border:2px solid #fff;background:#e7edf2;overflow:hidden}' +
      '.av img{width:100%;height:100%;object-fit:cover;display:block}' +
      '.av b{position:absolute;inset:0;display:none;align-items:center;justify-content:center;font:600 18px system-ui,sans-serif;color:' + brand + '}' +
      '.wrapav{display:block;position:relative;flex:none;width:44px;height:44px}' +
      '.dot{position:absolute;right:0;bottom:1px;width:12px;height:12px;border-radius:50%;background:#22c55e;border:2px solid #fff;display:none}' +
      '.on .dot{display:block}' +
      '.lbl{display:block;max-width:0;overflow:hidden;white-space:nowrap;font-size:15px;font-weight:600;letter-spacing:.1px;transition:max-width .3s ease,margin .3s ease,opacity .2s ease;opacity:0;margin:0}' +
      '.show .lbl{max-width:190px;margin:0 12px 0 10px;opacity:1}' +
      '.hidebtn:not(.open) .btn,.hidebtn:not(.open) .card{display:none}' +
      '.x{display:none;width:26px;height:26px;margin:0 11px}' +
      '.open .x{display:block}.open .wrapav,.open .lbl{display:none}' +
      '.panel{position:fixed;bottom:calc(92px + env(safe-area-inset-bottom,0px));' + side + ':20px;width:380px;height:min(640px,calc(100dvh - 112px));background:' + T.surface + ';border-radius:18px;overflow:hidden;box-shadow:0 12px 40px rgba(20,34,43,.3);opacity:0;transform:translateY(12px) scale(.98);pointer-events:none;visibility:hidden;transition:opacity .15s ease,transform .15s ease,visibility 0s .15s}' +
      '.open .panel{opacity:1;transform:none;pointer-events:auto;visibility:visible;transition:opacity .15s ease,transform .15s ease}' +
      '.grab{display:none}' +
      '.panel:before{content:"";position:absolute;left:50%;top:50%;width:28px;height:28px;margin:-14px 0 0 -14px;border-radius:50%;border:3px solid ' + T.line + ';border-top-color:' + brand + ';box-sizing:border-box}' +
      '@media (prefers-reduced-motion:no-preference){.panel:before{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}}' +
      'iframe{position:relative;width:100%;height:100%;border:0;background:transparent;display:block}' +
      '.card{position:fixed;bottom:calc(92px + env(safe-area-inset-bottom,0px));' + side + ':20px;max-width:260px;background:#fff;color:#14222b;border-radius:14px;padding:12px 34px 12px 14px;font-size:14px;line-height:1.35;box-shadow:0 8px 28px rgba(20,34,43,.25);cursor:pointer;display:none;border:0;text-align:left;font-family:inherit}' +
      '.card.in{display:block;animation:rise .25s ease}' +
      '.card .cx{position:absolute;top:4px;right:4px;width:28px;height:28px;border:0;background:transparent;color:#5b6b76;font-size:18px;line-height:1;cursor:pointer;border-radius:50%}' +
      '@keyframes rise{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}' +
      '.open .card{display:none}' +
      '@media (max-width:480px){.panel{inset:0;width:100%;height:100dvh;border-radius:0;transform:translateY(24px)}' +
      '.open .panel{transform:none}.open .btn{display:none}.card{left:16px;right:16px;max-width:none;bottom:calc(92px + env(safe-area-inset-bottom,0px))}}' +
      '@media (prefers-color-scheme:dark){.card{background:#1d2a33;color:#eef3f6}.card .cx{color:#a9b7c1}.panel{box-shadow:0 12px 40px rgba(0,0,0,.6)}.grab{background:linear-gradient(#1d2a33,rgba(29,42,51,0))}.grab::after{background:#566872}}' +
      '@media (prefers-reduced-motion:reduce){.btn,.panel,.lbl,.card.in{transition:none;animation:none}}' +
      '</style>' +
      '<div class="wrap">' +
      '<div class="panel" role="dialog"><div class="grab" aria-hidden="true"></div></div>' +
      '<div class="card" role="button" tabindex="0"><span class="ct"></span><button class="cx" type="button" aria-label="Dismiss">×</button></div>' +
      '<button class="btn" type="button" aria-expanded="false">' +
      '<span class="wrapav"><span class="av"><img alt="" width="44" height="44"><b>C</b></span><span class="dot"></span></span>' +
      '<span class="lbl">Chat with Chioma</span>' +
      '<svg class="x" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>' +
      '</button></div>'

    var wrap = root.querySelector('.wrap')
    var panel = root.querySelector('.panel')
    var btn = root.querySelector('.btn')
    var card = root.querySelector('.card')
    var grab = root.querySelector('.grab')
    var avImg = root.querySelector('.av img')
    var label = 'Chat with Chioma. Virtual assistant for ' + name
    btn.setAttribute('aria-label', label)
    panel.setAttribute('aria-label', label)
    avImg.src = img + '64.webp'
    avImg.srcset = img + '64.webp 1x, ' + img + '128.webp 2x'
    avImg.addEventListener('error', function () { avImg.style.display = 'none'; root.querySelector('.av b').style.display = 'flex' })
    if (online) wrap.classList.add('on')
    wrap.classList.add('show')                       // the label shows first, then folds into the avatar
    if (!reduce) setTimeout(function () { if (!isOpen) wrap.classList.remove('show') }, 4000)

    var frame = null
    var isOpen = false
    var pending = null                               // ASKBAR-1: the first question or button tap, used when the chat is first opened
    var onOpenChange = function () {}

    function ensureFrame() {
      if (frame) return
      frame = document.createElement('iframe')
      frame.title = 'Chat with Chioma. Virtual assistant for ' + name
      frame.setAttribute('allow', 'microphone; clipboard-write')
      frame.src = chatBase + '/c/' + key + '?embed=1&s=' + encodeURIComponent(source) + '&po=' + encodeURIComponent(location.origin) +
        (pending && pending.menu_id ? '&m=' + encodeURIComponent(pending.menu_id) : '') + (pending && pending.text ? '&q=' + encodeURIComponent(pending.text) : '') +
        (pending && pending.open === 'menu' ? '&o=menu' : '') + (pending && pending.open === 'shop' ? '&o=shop' : '') + '&th=' + themeId
      pending = null
      panel.appendChild(frame)
    }
    // WEBCHAT-WARM-1: once the website has finished loading, load the chat page once in a hidden frame (it starts no chat) so the
    // first open comes from the browser cache instead of a blank panel.
    function warmUp() {
      try {
        if (frame || window.__opsraWarm) return
        window.__opsraWarm = true
        var w = document.createElement('iframe')
        w.setAttribute('aria-hidden', 'true'); w.tabIndex = -1; w.title = ''
        w.style.cssText = 'position:absolute;width:0;height:0;border:0;visibility:hidden'
        w.src = chatBase + '/c/' + key + '?embed=1&warm=1&th=' + themeId
        w.addEventListener('load', function () { setTimeout(function () { try { w.remove() } catch (e) { /* ignore */ } }, 3000) })
        root.appendChild(w)
      } catch (e) { /* the chat still opens normally */ }
    }
    function warmSoon() { (window.requestIdleCallback || function (f) { setTimeout(f, 1500) })(warmUp) }
    if (document.readyState === 'complete') warmSoon(); else window.addEventListener('load', warmSoon)
    function setOpen(v) {
      isOpen = !!v
      if (isOpen) { ensureFrame(); card.classList.remove('in'); store('opsra_chioma_greeted_' + key, '1') }
      wrap.classList.toggle('open', isOpen)
      btn.setAttribute('aria-expanded', String(isOpen))
      btn.setAttribute('aria-label', isOpen ? 'Close chat' : label)
      if (isOpen && frame) setTimeout(function () { try { frame.focus() } catch (e) { /* ignore */ } }, 160)
      if (!isOpen) { try { btn.focus() } catch (e) { /* ignore */ } }
      onOpenChange()
    }
    btn.addEventListener('click', function () { setOpen(!isOpen) })

    // Greeting card: one short line, once per visit, as the label folds (about 4 seconds in), dismissible. Fixed copy, no AI.
    if (!store('opsra_chioma_greeted_' + key)) {
      setTimeout(function () {
        if (isOpen || store('opsra_chioma_greeted_' + key)) return
        var prod = pageProduct()
        root.querySelector('.ct').textContent = prod ? 'Questions about ' + prod + '? I can help.' : (GREETING[pageHint()] || GREETING.home).replace('{n}', name)
        card.classList.add('in')
        store('opsra_chioma_greeted_' + key, '1')
      }, 4000)                                   // the same moment the label folds into the photo
    }
    card.addEventListener('click', function () { setOpen(true) })
    card.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(true) } })
    root.querySelector('.cx').addEventListener('click', function (e) { e.stopPropagation(); card.classList.remove('in') })

    // Phone: the chat fills the whole screen (its own close button is in the chat header); the drag handle is not used.
    var startY = null
    grab.addEventListener('touchstart', function (e) { startY = e.touches[0].clientY }, { passive: true })
    grab.addEventListener('touchend', function (e) {
      if (startY !== null && e.changedTouches[0].clientY - startY > 70) setOpen(false)
      startY = null
    })

    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && isOpen) setOpen(false) })
    window.addEventListener('message', function (e) {
      if (e.origin !== chatBase || !e.data || e.data.source !== 'opsra-chat') return
      if (e.data.type === 'close') setOpen(false)
    })
    // ASKBAR-1: open the chat with a question typed by the visitor, or with one of the chat buttons already tapped.
    function ask(o) {
      o = o || {}
      var msg = { menu_id: /^[A-Za-z0-9_-]{1,40}$/.test(o.menu_id || '') ? o.menu_id : '', text: String(o.text || '').replace(/\s+/g, ' ').trim().slice(0, 500), open: o.open === 'menu' || o.open === 'shop' ? o.open : '' }
      var fresh = !frame
      if (msg.menu_id || msg.text || msg.open) pending = msg
      setOpen(true)
      if (!fresh && (msg.menu_id || msg.text || msg.open)) {
        try { frame.contentWindow.postMessage({ source: 'opsra-host', type: 'ask', menu_id: msg.menu_id, text: msg.text, open: msg.open }, chatBase) } catch (e) { /* ignore */ }
        pending = null
      }
    }
    window.OpsraChat = { open: function () { setOpen(true) }, close: function () { setOpen(false) }, toggle: function () { setOpen(!isOpen) },
      ask: function (text) { ask({ text: text }) } }
    document.addEventListener('click', function (e) {
      var el = e.target && e.target.closest ? e.target.closest('[data-chioma],[data-chioma-ask],[data-chioma-menu],[data-chioma-open]') : null
      if (!el) return
      e.preventDefault()
      ask({ text: el.getAttribute('data-chioma-ask') || '', menu_id: el.getAttribute('data-chioma-menu') || '', open: el.getAttribute('data-chioma-open') || '' })
    })

    // The ask bar: inline where the website put <div data-chioma-slot>, else docked at the bottom. Minimizing it brings back the launcher.
    var bar = d.bar && typeof d.bar === 'object' ? d.bar : null
    var minKey = 'opsra_chioma_bar_min_' + key
    function lstore(k, v) { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v) } catch (e) { /* storage can be blocked */ } return null }
    function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c] }) }
    function showLauncher(v) { wrap.classList.toggle('hidebtn', !v) }
    function buildBar() {
      if (!bar || lstore(minKey) === '1') return
      var slot = document.querySelector('[data-chioma-slot]')
      var docked = !slot
      var over = slot ? slot.getAttribute('data-chioma-theme') : ''
      var P = THEMES[over === 'dark' ? 'midnight' : over === 'light' ? 'classic' : themeId]
      var chips = (Array.isArray(bar.chips) ? bar.chips : []).slice(0, 3)
      var host2 = document.createElement('div')
      host2.setAttribute('data-opsra-chat-bar', '')
      host2.style.cssText = docked ? 'all:initial;position:fixed;z-index:2147482990;left:0;right:0;bottom:0;height:0' : 'all:initial;display:block;width:100%'
      var r = host2.attachShadow({ mode: 'open' })
      r.innerHTML =
        '<style>' +
        '*{box-sizing:border-box;font-family:"Hanken Grotesk",system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}' +
        '.bar{' + (docked ? 'position:fixed;left:50%;transform:translateX(-50%);bottom:calc(20px + env(safe-area-inset-bottom,0px));width:min(460px,calc(100vw - 24px));box-shadow:0 12px 36px rgba(0,0,0,' + (P.dark ? '.5' : '.22') + ');' : 'position:relative;width:100%;max-width:640px;') +
        'border-radius:18px;padding:10px 12px 12px;background:' + P.surface + ';color:' + P.ink + ';border:1px solid ' + P.line + '}' +
        '.top{display:flex;align-items:center;justify-content:space-between;min-height:24px}' +
        '.who{font-size:13px;font-weight:500;color:' + P.muted + '}' +
        '.min{width:44px;height:44px;margin:-10px -8px -10px 0;border:0;background:transparent;color:' + P.muted + ';font-size:24px;line-height:1;cursor:pointer;border-radius:50%}' +
        '.min:focus-visible,.go:focus-visible,.chip:focus-visible{outline:3px solid ' + brand + ';outline-offset:2px}' +
        'form{display:flex;align-items:center;gap:10px;background:' + P.field + ';border-radius:14px;padding:6px 6px 6px 8px;border:1px solid ' + P.fieldLine + '}' +
        'form:focus-within{border-color:' + brand + ';box-shadow:0 0 0 3px ' + brand + '40}' +
        '.av{position:relative;width:40px;height:40px;flex:none}.av img{width:40px;height:40px;border-radius:50%;object-fit:cover;display:block;background:' + P.line + '}' +
        '.dot{position:absolute;right:-1px;bottom:-1px;width:11px;height:11px;border-radius:50%;background:#22c55e;border:2px solid ' + P.surface + ';display:none}.on .dot{display:block}' +
        'input{flex:1;min-width:0;border:0;outline:0;box-shadow:none;background:transparent;font:inherit;font-size:16px;color:' + P.ink + ';padding:8px 0;text-overflow:ellipsis}input::placeholder{color:' + P.muted + ';opacity:1}' +
        '.go{width:40px;height:40px;flex:none;border:0;border-radius:50%;background:' + brand + ';color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center}' +
        '.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}' +
        '.chip{font:inherit;font-size:13px;font-weight:500;color:' + P.ink + ';background:transparent;border:1px solid ' + P.fieldLine + ';border-radius:999px;padding:9px 13px;cursor:pointer;min-height:36px}' +
        '.chip.p{background:' + brand + ';border-color:' + brand + ';color:#fff;font-weight:600}' +
        '.chip.m{color:' + P.muted + '}' +
        '@media (prefers-reduced-motion:no-preference){.bar{animation:up .3s ease}@keyframes up{from{opacity:0;margin-top:8px}to{opacity:1;margin-top:0}}}' +
        '</style>' +
        '<div class="bar' + (online ? ' on' : '') + '" role="region" aria-label="Ask Chioma">' +
        '<div class="top"><span class="who">Chioma' + (online ? ' · online now' : '') + '</span>' +
        '<button class="min" type="button" aria-label="Minimize Chioma to the corner">–</button></div>' +
        '<form><span class="av"><img alt="" width="40" height="40"><span class="dot"></span></span>' +
        '<input type="text" maxlength="500" aria-label="Ask Chioma a question" placeholder="' + esc(bar.text || 'Ask me anything…') + '" autocomplete="off">' +
        '<button class="go" type="submit" aria-label="Ask"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button></form>' +
        (chips.length || bar.more ? '<div class="chips">' + chips.map(function (c) { return '<button class="chip' + (c.primary ? ' p' : '') + '" type="button" data-id="' + esc(c.id) + '">' + esc(c.label) + '</button>' }).join('') +
          (bar.more ? '<button class="chip m" type="button" data-more="1" aria-label="More options">More \u203a</button>' : '') + '</div>' : '') +
        '</div>'
      var im = r.querySelector('.av img')
      im.src = img + '64.webp'
      im.srcset = img + '64.webp 1x, ' + img + '128.webp 2x'
      im.addEventListener('error', function () { im.style.visibility = 'hidden' })
      var inp = r.querySelector('input')
      r.querySelector('form').addEventListener('submit', function (e) { e.preventDefault(); ask({ text: inp.value }); inp.value = '' })
      Array.prototype.forEach.call(r.querySelectorAll('.chip'), function (b) { b.addEventListener('click', function () { if (b.getAttribute('data-more')) ask({ open: 'menu' }); else ask({ menu_id: b.getAttribute('data-id') }) }) })
      var io = null
      r.querySelector('.min').addEventListener('click', function () {
        lstore(minKey, '1')
        if (io) io.disconnect()
        host2.remove()
        onOpenChange = function () {}
        showLauncher(true)
        wrap.classList.add('show')
        if (!reduce) setTimeout(function () { if (!isOpen) wrap.classList.remove('show') }, 4000)
      })
      showLauncher(false)                                  // one Chioma on screen: the launcher waits while the bar is in view
      if (docked) {
        host2.style.display = 'none'
        document.body.appendChild(host2)
        setTimeout(function () { if (host2.isConnected) host2.style.display = '' }, reduce ? 0 : 1500)
        onOpenChange = function () { host2.style.visibility = isOpen ? 'hidden' : '' }
      } else {
        slot.appendChild(host2)
        if ('IntersectionObserver' in window) {
          io = new IntersectionObserver(function (en) { showLauncher(!en[0].isIntersecting) }, { threshold: 0.1 })
          io.observe(host2)
        } else {
          showLauncher(true)
        }
      }
    }
    buildBar()
    document.body.appendChild(host)
  }

  if (document.body) start()
  else document.addEventListener('DOMContentLoaded', start)
})()

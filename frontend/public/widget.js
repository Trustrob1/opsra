/*!
 * Opsra chat launcher (WEBCHAT-EMBED-1, WEBCHAT-BUBBLE-1: Chioma)
 * Add to a website:
 *   <script src="https://opsra.com.ng/widget.js" data-key="wc_XXXXXXXX" async></script>
 * Optional attributes: data-source="homepage" (shows up in your chat stats), data-api="https://..." (testing only).
 * Page controls: window.OpsraChat.open(), .close(), .toggle().
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
      '.x{display:none;width:26px;height:26px;margin:0 11px}' +
      '.open .x{display:block}.open .wrapav,.open .lbl{display:none}' +
      '.panel{position:fixed;bottom:calc(92px + env(safe-area-inset-bottom,0px));' + side + ':20px;width:380px;height:min(640px,calc(100dvh - 112px));background:#fff;border-radius:18px;overflow:hidden;box-shadow:0 12px 40px rgba(20,34,43,.3);opacity:0;transform:translateY(12px) scale(.98);pointer-events:none;visibility:hidden;transition:opacity .15s ease,transform .15s ease,visibility 0s .15s}' +
      '.open .panel{opacity:1;transform:none;pointer-events:auto;visibility:visible;transition:opacity .15s ease,transform .15s ease}' +
      '.grab{display:none}' +
      'iframe{width:100%;height:100%;border:0;background:#fff;display:block}' +
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

    function ensureFrame() {
      if (frame) return
      frame = document.createElement('iframe')
      frame.title = 'Chat with Chioma. Virtual assistant for ' + name
      frame.setAttribute('allow', 'microphone; clipboard-write')
      frame.src = chatBase + '/c/' + key + '?embed=1&s=' + encodeURIComponent(source) + '&po=' + encodeURIComponent(location.origin)
      panel.appendChild(frame)
    }
    function setOpen(v) {
      isOpen = !!v
      if (isOpen) { ensureFrame(); card.classList.remove('in'); store('opsra_chioma_greeted_' + key, '1') }
      wrap.classList.toggle('open', isOpen)
      btn.setAttribute('aria-expanded', String(isOpen))
      btn.setAttribute('aria-label', isOpen ? 'Close chat' : label)
      if (isOpen && frame) setTimeout(function () { try { frame.focus() } catch (e) { /* ignore */ } }, 160)
      if (!isOpen) { try { btn.focus() } catch (e) { /* ignore */ } }
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
    window.OpsraChat = { open: function () { setOpen(true) }, close: function () { setOpen(false) }, toggle: function () { setOpen(!isOpen) } }
    document.body.appendChild(host)
  }

  if (document.body) start()
  else document.addEventListener('DOMContentLoaded', start)
})()

// Copy buttons for the install commands. Without JavaScript the commands stay as plain text.
document.querySelectorAll('pre[data-copy]').forEach((pre) => {
  const box = pre.parentElement
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'copy'
  button.textContent = 'Copy'
  button.setAttribute('aria-label', 'Copy these commands')
  box.classList.add('has-copy')
  box.appendChild(button)

  let timer
  const flash = (text) => {
    button.textContent = text
    clearTimeout(timer)
    timer = setTimeout(() => (button.textContent = 'Copy'), 1800)
  }

  // file:// is not always a secure context, so fall back to selecting the text and execCommand.
  const fallback = () => {
    const range = document.createRange()
    range.selectNodeContents(pre)
    const selection = window.getSelection()
    selection.removeAllRanges()
    selection.addRange(range)
    const ok = document.execCommand && document.execCommand('copy')
    flash(ok ? 'Copied' : 'Press Ctrl+C')
  }

  button.addEventListener('click', () => {
    const text = pre.textContent
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(() => flash('Copied'), fallback)
    } else {
      fallback()
    }
  })
})

// The one ModHost the app uses. A mod that errors or never starts is switched
// off on the server (host.ts), so the cached list is refreshed to drop it.
import { modsApi } from './api'
import { ModHost } from './host'
import { refreshMods } from './store'

export const modHost = new ModHost({
  api: modsApi,
  onEvent: event => {
    if (event.what === 'mod-error') {
      void refreshMods()
    }
  },
  theme: () => (document.documentElement.classList.contains('dark') ? 'dark' : 'light')
})

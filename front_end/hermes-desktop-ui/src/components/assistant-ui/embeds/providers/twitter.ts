import { bareHost, type EmbedMatcher } from './types'

export const twitter: EmbedMatcher = url => {
  const host = bareHost(url.hostname)

  if (host !== 'twitter.com' && host !== 'x.com') {
    return null
  }

  const segments = url.pathname.split('/').filter(Boolean)
  const statusIndex = segments.indexOf('status')
  const id = statusIndex >= 0 ? segments[statusIndex + 1] : ''

  if (!/^\d+$/.test(id || '')) {
    return null
  }

  return {
    // The iframe endpoint, not widgets.js: that script would run inside this origin.
    embedUrl: `https://platform.twitter.com/embed/Tweet.html?dnt=true&id=${id}`,
    height: 520,
    id: `twitter:${id}`,
    label: 'X',
    maxWidth: 480,
    provider: 'twitter',
    renderer: 'frame',
    sourceUrl: url.toString()
  }
}

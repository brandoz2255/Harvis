import { beforeEach, describe, expect, it } from 'vitest'

import { $webSearch, setWebSearch, toggleWebSearch, webSearchParam } from './web-search'

describe('web search toggle', () => {
  beforeEach(() => {
    window.localStorage.clear()
    $webSearch.set(false)
  })

  it('starts off and flips with the globe', () => {
    expect($webSearch.get()).toBe(false)
    expect(toggleWebSearch()).toBe(true)
    expect($webSearch.get()).toBe(true)
    expect(toggleWebSearch()).toBe(false)
  })

  it('remembers the choice across reloads', () => {
    setWebSearch(true)

    expect(window.localStorage.getItem('harvis.composer.webSearch.v1')).toBe('1')
    setWebSearch(false)
    expect(window.localStorage.getItem('harvis.composer.webSearch.v1')).toBe('0')
  })

  it('stays out of prompt.submit until the globe has been on, then reports both states', () => {
    expect(webSearchParam()).toEqual({})
    setWebSearch(true)
    expect(webSearchParam()).toEqual({ web_search: true })
    setWebSearch(false)
    expect(webSearchParam()).toEqual({ web_search: false })
  })
})

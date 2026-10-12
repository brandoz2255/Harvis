import { describe, expect, it } from 'vitest'

import { isCloudModel } from './harvis-api'

describe('isCloudModel', () => {
  it.each(['kimi-k2.6:cloud', 'qwen3-coder:480b-cloud', 'GPT-OSS:120B-Cloud', 'library/foo:cloud'])('hides %s', name =>
    expect(isCloudModel({ name })).toBe(true)
  )

  it('hides a row Ollama marks as remote', () => {
    expect(isCloudModel({ name: 'plain:latest', remote_host: 'https://ollama.com:443' })).toBe(true)
  })

  it.each(['qwen3:8b', 'cloud:latest', 'cloudy-model:7b', 'my-cloud/llama:8b', 'tiny', 'hf.co/org/Model-GGUF:Q4_K_M'])(
    'keeps %s',
    name => expect(isCloudModel({ name })).toBe(false)
  )
})

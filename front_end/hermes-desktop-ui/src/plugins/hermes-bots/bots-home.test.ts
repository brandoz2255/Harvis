// Every Bot Mode surface has an exit: the office steps out to the chats, and any bot or
// group chat steps back to the office.
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { hostMock, bumpMock } = vi.hoisted(() => ({
  bumpMock: vi.fn(),
  hostMock: { navigate: vi.fn(), revealPane: vi.fn() }
}))

vi.mock('@hermes/plugin-sdk', async () => ({ atom: (await import('nanostores')).atom, host: hostMock }))
vi.mock('./shared', () => ({ bumpBotOpenGeneration: bumpMock }))
vi.mock('./group-chat', async () => ({ $groupChatWorkspace: (await import('nanostores')).atom<null | string>(null) }))
vi.mock('./bot-state', async () => ({ $openBotChat: (await import('nanostores')).atom<unknown>(null) }))

import { $openBotChat } from './bot-state'
import { goBotsHome, leaveBotsForChats } from './bots-home'
import { $groupChatWorkspace } from './group-chat'

describe('bots home routing', () => {
  beforeEach(() => vi.clearAllMocks())

  it('leaves an open bot chat for the office', () => {
    $openBotChat.set({ key: 'legacy::hermes', openedRegistryId: 'r1', openedSessionId: 's1' } as never)
    goBotsHome()
    expect($openBotChat.get()).toBeNull()
    expect(bumpMock).toHaveBeenCalledOnce()
    expect(hostMock.revealPane).toHaveBeenCalledWith('workspace')
    expect(hostMock.navigate).toHaveBeenCalledWith('/')
  })

  it('leaves a group chat for the office', () => {
    $groupChatWorkspace.set('team')
    goBotsHome()
    expect($groupChatWorkspace.get()).toBeNull()
  })

  it('steps out of the office to the sessions list', () => {
    leaveBotsForChats()
    expect(hostMock.revealPane).toHaveBeenCalledWith('sessions')
    expect(hostMock.navigate).not.toHaveBeenCalled()
  })
})

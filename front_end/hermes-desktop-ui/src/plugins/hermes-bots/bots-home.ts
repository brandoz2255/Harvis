// Every Bot Mode surface has a way in and a way out. The office is the Bots home: any bot
// or group chat can step back to it, and the office itself can step out to the chats.
import { host } from '@hermes/plugin-sdk'

import { $openBotChat } from './bot-state'
import { $groupChatWorkspace } from './group-chat'
import { bumpBotOpenGeneration } from './shared'

/** Leave whichever bot or group chat holds the center and show the office. The chat's tab
 *  stays open; only the center changes. */
export function goBotsHome(): void {
  // A bot open still dialing must not land on top of the office after we left.
  bumpBotOpenGeneration()
  $openBotChat.set(null)
  $groupChatWorkspace.set(null)
  host.revealPane?.('workspace')
  host.navigate('/')
}

/** Step out of Bot Mode to the sessions list and whatever chat it holds. */
export function leaveBotsForChats(): void {
  host.revealPane?.('sessions')
}

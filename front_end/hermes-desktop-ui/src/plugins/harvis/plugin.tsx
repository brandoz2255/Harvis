/**
 * Harvis — surfaces the Harvis backend's own features inside the Hermes UI.
 * Workspace runs belong to the chat: a mode pill beside the model picker picks
 * how the next message is handled (Auto / Chat / Agent / Team), and a running
 * job docks above the composer with its live steps, Stop, and approvals.
 * Deep Research, Notebooks and the watchable Browser get their own pages over
 * `/api/research/*`, `/api/notebooks/*` and `/api/agents/computer/*`. Reuses the existing Harvis routers as-is.
 */

import {
  CHAT_EMPTY_AREA,
  type ChatEmptyContribution,
  COMPOSER_AREAS,
  type HermesPlugin,
  type RouteContribution,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  SIDEBAR_SECTION_AREA,
  type SidebarNavContribution
} from '@hermes/plugin-sdk'

import { BotChatEmpty, BotChatHeader } from './bot-chat'
import { BotsPage } from './bots-page'
import { BotsSidebarSection } from './bots-sidebar'
import { BrowserPage } from './browser'
import { ChatModePill } from './chat-mode'
import { NotebooksPage } from './notebooks'
import { ResearchPage } from './research'
import { RunDock } from './run-dock'

const plugin: HermesPlugin = {
  id: 'harvis',
  name: 'Harvis',
  description: 'Harvis workspace runs inside the chat, plus the Deep Research, Notebooks and Browser pages.',
  defaultEnabled: true,
  register(ctx) {
    ctx.registerMany([
      { id: 'chat-mode', area: COMPOSER_AREAS.actions, order: 10, render: () => <ChatModePill /> },
      { id: 'run-dock', area: COMPOSER_AREAS.top, order: 10, render: () => <RunDock /> },
      // Bots: a saved assistant (instructions, model, knowledge) you start chats with from the sidebar.
      { id: 'bot-header', area: COMPOSER_AREAS.top, order: 5, render: () => <BotChatHeader /> },
      {
        id: 'bot-empty',
        area: CHAT_EMPTY_AREA,
        data: { render: props => <BotChatEmpty sessionId={props.sessionId} /> } satisfies ChatEmptyContribution
      },
      { id: 'bots-section', area: SIDEBAR_SECTION_AREA, order: 10, render: () => <BotsSidebarSection /> },
      {
        id: 'bots-page',
        area: ROUTES_AREA,
        data: { path: '/bots' } satisfies RouteContribution,
        render: () => <BotsPage />
      },
      {
        id: 'bots-nav',
        area: SIDEBAR_NAV_AREA,
        order: 43,
        data: { codicon: 'hubot', label: 'Bots', path: '/bots' } satisfies SidebarNavContribution
      },
      {
        id: 'research-page',
        area: ROUTES_AREA,
        data: { path: '/research' } satisfies RouteContribution,
        render: () => <ResearchPage />
      },
      {
        id: 'research-nav',
        area: SIDEBAR_NAV_AREA,
        order: 40,
        data: { codicon: 'telescope', label: 'Deep Research', path: '/research' } satisfies SidebarNavContribution
      },
      {
        id: 'notebooks-page',
        area: ROUTES_AREA,
        data: { path: '/notebooks' } satisfies RouteContribution,
        render: () => <NotebooksPage />
      },
      {
        id: 'notebooks-nav',
        area: SIDEBAR_NAV_AREA,
        order: 41,
        data: { codicon: 'notebook', label: 'Notebooks', path: '/notebooks' } satisfies SidebarNavContribution
      },
      {
        id: 'browser-page',
        area: ROUTES_AREA,
        data: { path: '/browser' } satisfies RouteContribution,
        render: () => <BrowserPage />
      },
      {
        id: 'browser-nav',
        area: SIDEBAR_NAV_AREA,
        order: 42,
        data: { codicon: 'globe', label: 'Browser', path: '/browser' } satisfies SidebarNavContribution
      }
    ])
  }
}

export default plugin

/**
 * Harvis — surfaces the Harvis backend's own features inside the Hermes UI.
 * Workspace runs belong to the chat: Harvis decides per message whether to
 * answer or start a run (the message can also ask for one), and a running
 * job docks above the composer with its live steps, Stop, and approvals.
 * Deep Research and Notebooks get their own pages over `/api/research/*` and
 * `/api/notebooks/*`. The watchable Browser (`/api/agents/computer/*`) has no nav
 * tab: it docks above the composer while something is browsing, with /browser as
 * its full view. Reuses the existing Harvis routers as-is.
 */

import {
  CHAT_EMPTY_AREA,
  type ChatEmptyContribution,
  COMPOSER_AREAS,
  type ComposerAttachmentProvider,
  type HermesPlugin,
  type RouteContribution,
  ROUTES_AREA,
  SIDEBAR_NAV_AREA,
  type SidebarNavContribution
} from '@hermes/plugin-sdk'

import { BotChatEmpty, BotChatHeader } from './bot-chat'
import { BotsPage } from './bots-page'
import { BrowserPage } from './browser'
import { BrowserDock } from './browser-dock'
import { RecentRunsButton } from './chat-mode'
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
      // No mode pill: Harvis picks chat vs workspace run per message (or follows
      // what the message asks for). Only reopening a recent run stays here.
      { id: 'recent-runs', area: COMPOSER_AREAS.actions, order: 10, render: () => <RecentRunsButton /> },
      // Deep Research from the chat's "+" menu, so it isn't only on its own page.
      // The anchored phrase is research_bridge's explicit trigger: the backend
      // takes everything after "on" as the topic and runs the research inline
      // (a leading "/deep-research" would be eaten by the composer's slash router).
      {
        id: 'deep-research-attach',
        area: COMPOSER_AREAS.attachments,
        data: {
          label: 'Deep research',
          icon: 'telescope',
          run: ctx => ctx.insertText('Deep research on ')
        } satisfies ComposerAttachmentProvider
      },
      { id: 'run-dock', area: COMPOSER_AREAS.top, order: 10, render: () => <RunDock /> },
      // Bots: a saved assistant (instructions, model, knowledge) you start chats with from the sidebar.
      { id: 'bot-header', area: COMPOSER_AREAS.top, order: 5, render: () => <BotChatHeader /> },
      {
        id: 'bot-empty',
        area: CHAT_EMPTY_AREA,
        data: { render: props => <BotChatEmpty sessionId={props.sessionId} /> } satisfies ChatEmptyContribution
      },
      // No sidebar section or nav row for these bots any more: the SESSIONS | BOTS
      // tab (hermes-bots) is the one bot surface, and the backend adopts every
      // bot made here into its roster. The page stays routable so old links work.
      {
        id: 'bots-page',
        area: ROUTES_AREA,
        data: { path: '/bots' } satisfies RouteContribution,
        render: () => <BotsPage />
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
      // The Browser pops up above the composer while something is browsing
      // (browser-dock) instead of sitting in the nav as a tab. The page remains
      // as the dock's "Open full view" target.
      {
        id: 'browser-page',
        area: ROUTES_AREA,
        data: { path: '/browser' } satisfies RouteContribution,
        render: () => <BrowserPage />
      },
      { id: 'browser-dock', area: COMPOSER_AREAS.top, order: 11, render: () => <BrowserDock /> }
    ])
  }
}

export default plugin

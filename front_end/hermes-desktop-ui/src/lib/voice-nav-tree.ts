/**
 * The tabs inside each page, for spoken navigation: "open Discord" is
 * Messaging → Discord, "go to voice settings" is Settings → Voice. Every leaf
 * is a deep link the page already reads from its URL (`useRouteEnumParam`), so
 * opening one needs nothing from the page itself.
 */

export interface VoiceNavChild {
  id: string
  label: string
  /** Query string the page reads, without the leading "?". */
  query: string
  names: string[]
}

// Messaging platforms (python_back_end/plugins/hermes_ui/messaging_catalog.json).
// Names include what speech-to-text tends to hear instead: "Discord" often
// comes back as "this code".
const PLATFORMS: [id: string, label: string, names: string[]][] = [
  ['telegram', 'Telegram', ['telegram']],
  ['discord', 'Discord', ['discord', 'discord bot', 'this code', 'the score', 'disc cord', 'discourse', 'discard']],
  ['slack', 'Slack', ['slack']],
  ['mattermost', 'Mattermost', ['mattermost', 'matter most']],
  ['matrix', 'Matrix', ['matrix', 'element']],
  ['whatsapp', 'WhatsApp', ['whatsapp', 'whats app', "what's app"]],
  ['signal', 'Signal', ['signal']],
  ['bluebubbles', 'BlueBubbles (iMessage)', ['bluebubbles', 'blue bubbles', 'imessage', 'i message']],
  ['homeassistant', 'Home Assistant', ['home assistant']],
  ['email', 'Email', ['email', 'e-mail', 'e mail', 'mail', 'gmail', 'inbox', 'outlook']],
  ['sms', 'SMS (Twilio)', ['sms', 'text messages', 'texts', 'twilio']],
  ['dingtalk', 'DingTalk', ['dingtalk', 'ding talk']],
  ['feishu', 'Feishu / Lark', ['feishu', 'lark']],
  ['google_chat', 'Google Chat', ['google chat', 'hangouts']],
  ['wecom', 'WeCom', ['wecom', 'we com']],
  ['weixin', 'WeChat', ['wechat', 'we chat', 'weixin']],
  ['qqbot', 'QQ Bot', ['qq', 'qq bot']],
  ['yuanbao', 'Yuanbao', ['yuanbao']],
  ['api_server', 'API server', ['api server']],
  ['webhook', 'Webhooks', ['messaging webhooks']],
  ['a2a', 'A2A', ['a2a', 'agent to agent']],
  ['buzz', 'Buzz', ['buzz']],
  ['photon', 'iMessage via Photon', ['photon']],
  ['irc', 'IRC', ['irc']],
  ['line', 'LINE', ['line app', 'line messenger']],
  ['msgraph_webhook', 'Microsoft Graph', ['microsoft graph', 'graph webhook']],
  ['teams', 'Microsoft Teams', ['teams', 'microsoft teams']],
  ['ntfy', 'ntfy', ['ntfy', 'notify app']],
  ['raft', 'Raft', ['raft']],
  ['relay', 'Relay', ['relay']],
  ['simplex', 'SimpleX Chat', ['simplex', 'simple x']],
  ['whatsapp_cloud', 'WhatsApp Cloud API', ['whatsapp cloud', 'whatsapp business']]
]

const SETTINGS: VoiceNavChild[] = [
  { id: 'model', label: 'Model', query: 'tab=config:model', names: ['model', 'main model', 'model settings'] },
  {
    id: 'fallback',
    label: 'Fallback models',
    query: 'tab=config:model&mview=fallback',
    names: ['fallback', 'fallback models', 'fallbacks']
  },
  { id: 'moa', label: 'Mixture of agents', query: 'tab=config:model&mview=moa', names: ['mixture of agents', 'moa'] },
  {
    id: 'auxiliary',
    label: 'Auxiliary task models',
    query: 'tab=config:model&mview=auxiliary',
    names: ['auxiliary', 'auxiliary models', 'task models']
  },
  { id: 'chat', label: 'Chat', query: 'tab=config:chat', names: ['chat settings', 'personality', 'timezone'] },
  {
    id: 'appearance',
    label: 'Appearance',
    query: 'tab=config:appearance',
    names: ['appearance', 'theme', 'dark mode', 'light mode', 'colors']
  },
  {
    id: 'voice',
    label: 'Voice',
    query: 'tab=config:voice',
    names: ['voice', 'voice settings', 'speech', 'microphone', 'mic']
  },
  {
    id: 'providers',
    label: 'Providers',
    query: 'tab=providers',
    names: ['providers', 'model providers', 'models list', 'ollama']
  },
  {
    id: 'engines',
    label: 'Coding engines',
    query: 'tab=providers&pview=engines',
    names: ['coding engines', 'engines', 'claude code', 'codex', 'opencode']
  },
  {
    id: 'endpoints',
    label: 'Custom endpoints',
    query: 'tab=providers&pview=custom-endpoints',
    names: ['custom endpoints', 'endpoints']
  },
  {
    id: 'memory',
    label: 'Memory & skills',
    query: 'tab=harvis-memory',
    names: ['memory', 'memories', 'memory settings']
  },
  { id: 'gateway', label: 'Gateway', query: 'tab=gateway', names: ['gateway', 'gateways', 'connections'] },
  { id: 'keybinds', label: 'Keyboard shortcuts', query: 'tab=keybinds', names: ['keybinds', 'shortcuts', 'hotkeys'] },
  { id: 'notifications', label: 'Notifications', query: 'tab=notifications', names: ['notifications', 'alerts'] },
  { id: 'archived', label: 'Archived chats', query: 'tab=sessions', names: ['archived chats', 'archive', 'archived'] },
  { id: 'about', label: 'About', query: 'tab=about', names: ['about', 'version'] }
]

const SKILLS: VoiceNavChild[] = [
  { id: 'toolsets', label: 'Toolsets', query: 'tab=toolsets', names: ['toolsets', 'tool sets'] },
  { id: 'mcp', label: 'MCP servers', query: 'tab=mcp', names: ['mcp', 'mcp servers', 'servers'] }
]

const COMMAND_CENTER: VoiceNavChild[] = [
  { id: 'sessions', label: 'Sessions', query: 'section=sessions', names: ['sessions'] },
  { id: 'system', label: 'System', query: 'section=system', names: ['system', 'system status', 'health'] },
  { id: 'usage', label: 'Usage', query: 'section=usage', names: ['usage', 'token usage', 'costs'] },
  { id: 'maintenance', label: 'Maintenance', query: 'section=maintenance', names: ['maintenance'] }
]

const ARTIFACTS: VoiceNavChild[] = [
  { id: 'images', label: 'Images', query: 'tab=image', names: ['images', 'pictures'] },
  { id: 'links', label: 'Links', query: 'tab=link', names: ['links'] }
]

/** Tabs by page path. */
export const VOICE_NAV_CHILDREN: Record<string, VoiceNavChild[]> = {
  '/messaging': PLATFORMS.map(([id, label, names]) => ({ id, label, query: `platform=${id}`, names })),
  '/settings': SETTINGS,
  '/skills': SKILLS,
  '/command-center': COMMAND_CENTER,
  '/artifacts': ARTIFACTS
}

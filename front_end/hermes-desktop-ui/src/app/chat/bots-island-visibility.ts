// Only the primary workspace's idle Bots tab owns the island, and only while the account's
// "Show the island" setting is on. Opening a session (or sending from the island's composer,
// which opens one) gives the space back to the thread so the reply is not hidden under it.
export function showBotsIsland(
  primary: boolean,
  botsVisible: boolean,
  botChatOpen: boolean,
  groupChatOpen: boolean,
  enabled: boolean,
  sessionOpen = false
): boolean {
  return enabled && primary && botsVisible && !botChatOpen && !groupChatOpen && !sessionOpen
}

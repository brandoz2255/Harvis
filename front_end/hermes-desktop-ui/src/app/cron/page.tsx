import { useNavigate } from 'react-router'

import { openSession } from '../open-session'
import { NEW_CHAT_ROUTE } from '../routes'

import { CronView } from '.'

/** Scheduled jobs as a workspace page or side tile — never a full-screen pop-up. */
export function CronPage() {
  const navigate = useNavigate()

  return (
    <CronView
      inline
      onClose={() => navigate(NEW_CHAT_ROUTE)}
      onOpenSession={sessionId => openSession(sessionId, navigate)}
    />
  )
}

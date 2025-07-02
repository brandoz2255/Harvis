/* -------------------------------------------------------------------------- */
/* components/SettingsModal.tsx – dark-themed modal (screenshot accurate)     */
/* -------------------------------------------------------------------------- */

"use client"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select"
import clsx from "clsx"
import { FC, Fragment, useState } from "react"
import {
  User,
  BrainCircuit,
  Palette,
  Bell,
  Shield,
  Mic,
  Monitor,
  Globe,
  Download,
  Upload,
  Undo2,
} from "lucide-react"

/* -------------------------------- Props ---------------------------------- */

interface SettingsModalProps {
  isOpen: boolean
  onClose: () => void
  context?: "dashboard" | "agent" | "global"
}

/* ------------------------- Sidebar configuration ------------------------- */

type SectionId =
  | "general"
  | "models"
  | "appearance"
  | "notifications"
  | "security"
  | "voice"
  | "screen"
  | "research"

const sections: { id: SectionId; label: string; icon: React.ElementType }[] = [
  { id: "general", label: "General", icon: User },
  { id: "models", label: "AI Models", icon: BrainCircuit },
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "security", label: "Security", icon: Shield },
  { id: "voice", label: "Voice", icon: Mic },
  { id: "screen", label: "Screen", icon: Monitor },
  { id: "research", label: "Research", icon: Globe },
]

/* -------------------------------- Styles --------------------------------- */
/* Tailwind colors used:
   - Dark navy panels:      #0F172A  (slate-900)
   - Slightly lighter bg:   #111827  (slate-800)
   - Border lines:          #1E293B  (slate-700)
   - Text main:             slate-100
   - Muted text:            slate-400
   - Accent blue (active):  #2563EB  (blue-600)
*/

const WRAP_BG   = "bg-[#0F172A] text-slate-100"
const PANEL_BG  = "bg-[#111827]"
const BORDER    = "border border-[#1E293B]"
const SIDEBAR_BG= "bg-[#111827]"

/* ------------------------------ Component --------------------------------- */

const SettingsModal: FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  context = "dashboard",
}) => {
  /* ------------------------- Example state -------------------------- */
  const [activeSection, setActiveSection] = useState<SectionId>("general")

  const [name, setName]       = useState("User")
  const [email, setEmail]     = useState("user@example.com")
  const [timezone, setTZ]     = useState("UTC")
  const [language, setLang]   = useState("en")

  const resetDefaults = () => {
    setName("User")
    setEmail("user@example.com")
    setTZ("UTC")
    setLang("en")
  }

  const save = () => {
    // TODO: API / localStorage
    onClose()
  }

  /* --------------------- Section renderer -------------------------- */
  const renderSection = () => {
    if (activeSection !== "general")
      return (
        <div className="flex items-center justify-center h-full text-slate-400">
          <p className="text-sm">
            {sections.find(s => s.id === activeSection)?.label} settings coming soon…
          </p>
        </div>
      )

    return (
      <Fragment>
        <h3 className="text-xl font-semibold mb-6">User Profile</h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Name */}
          <div className="flex flex-col space-y-2">
            <label htmlFor="name" className="text-sm font-medium">
              Name
            </label>
            <Input
              id="name"
              value={name}
              onChange={e => setName(e.target.value)}
              className={`${PANEL_BG} ${BORDER} placeholder:text-slate-500`}
            />
          </div>

          {/* Email */}
          <div className="flex flex-col space-y-2">
            <label htmlFor="email" className="text-sm font-medium">
              Email
            </label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              className={`${PANEL_BG} ${BORDER} placeholder:text-slate-500`}
            />
          </div>

          {/* Timezone */}
          <div className="flex flex-col space-y-2">
            <label className="text-sm font-medium">Timezone</label>
            <Select value={timezone} onValueChange={setTZ}>
              <SelectTrigger className={`${PANEL_BG} ${BORDER} text-left`}>
                <SelectValue placeholder="Select timezone" />
              </SelectTrigger>
              <SelectContent className={WRAP_BG}>
                <SelectItem value="UTC">UTC</SelectItem>
                <SelectItem value="EST">EST (GMT-5)</SelectItem>
                <SelectItem value="PST">PST (GMT-8)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Language */}
          <div className="flex flex-col space-y-2">
            <label className="text-sm font-medium">Language</label>
            <Select value={language} onValueChange={setLang}>
              <SelectTrigger className={`${PANEL_BG} ${BORDER} text-left`}>
                <SelectValue placeholder="Select language" />
              </SelectTrigger>
              <SelectContent className={WRAP_BG}>
                <SelectItem value="en">English</SelectItem>
                <SelectItem value="es">Spanish</SelectItem>
                <SelectItem value="fr">French</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </Fragment>
    )
  }

  /* ------------------------------- UI -------------------------------- */

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent
        className={clsx(
          WRAP_BG,
          BORDER,
          "w-full max-w-5xl p-0 overflow-hidden"
        )}
      >
        {/* Header */}
        <DialogHeader className="px-6 pt-6">
          <DialogTitle className="text-2xl">Settings</DialogTitle>
          <DialogDescription className="text-slate-400">
            Dashboard Configuration
          </DialogDescription>
        </DialogHeader>

        <div className="flex h-[540px] divide-x divide-[#1E293B]">
          {/* Sidebar */}
          <aside className={`${SIDEBAR_BG} w-56 border-r border-[#1E293B]`}>
            <nav className="flex flex-col p-4 space-y-1">
              {sections.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setActiveSection(id)}
                  className={clsx(
                    "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                    activeSection === id
                      ? "bg-[#2563EB] text-white"
                      : "text-slate-300 hover:bg-[#1E293B]"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  <span>{label}</span>
                </button>
              ))}
            </nav>
          </aside>

          {/* Content */}
          <section className="flex-1 p-8 overflow-y-auto">{renderSection()}</section>
        </div>

        {/* Footer */}
        <div
          className={`flex items-center justify-between ${SIDEBAR_BG} border-t border-[#1E293B] px-6 py-4`}
        >
          <div className="space-x-2">
            <Button
              variant="outline"
              size="sm"
              className={`${BORDER} bg-[#0F172A] text-slate-300 hover:bg-[#1E293B]`}
            >
              <Download className="w-4 h-4 mr-1.5" />
              Export
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={`${BORDER} bg-[#0F172A] text-slate-300 hover:bg-[#1E293B]`}
            >
              <Upload className="w-4 h-4 mr-1.5" />
              Import
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={resetDefaults}
              className={`${BORDER} text-red-400 hover:bg-red-400/10`}
            >
              <Undo2 className="w-4 h-4 mr-1.5" />
              Reset
            </Button>
          </div>

          <div className="space-x-2">
            <DialogClose asChild>
              <Button
                variant="outline"
                className={`${BORDER} bg-[#0F172A] text-slate-300 hover:bg-[#1E293B]`}
                size="sm"
              >
                Cancel
              </Button>
            </DialogClose>
            <Button
              onClick={save}
              size="sm"
              className="bg-[#2563EB] hover:bg-[#1D4ED8] text-white"
            >
              Save Changes
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default SettingsModal


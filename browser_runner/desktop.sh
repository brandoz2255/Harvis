#!/usr/bin/env bash
# A full Xfce desktop for one headed session, served over RFB on a localhost port.
#
# Started by display.py in place of the Xvfb + x11vnc pair when a session asks
# for a desktop. TigerVNC's Xvnc is the X server and the VNC server in one
# process, so websockify's token file points at it exactly as it points at
# x11vnc. Adapted from the Hermes Bot Screen launcher
# (hermes-agent tools/bot_desktop/launcher.sh).
#
# Why not startxfce4 / xfce4-session: outside a logind session it spawns polkit
# agents with empty dialogs and a screensaver that locks a user with no
# password. Starting xfsettingsd -> xfwm4 -> xfdesktop -> xfce4-panel directly
# is the shape every headless-VNC recipe converges on.
#
# What the desktop deliberately does NOT offer: a terminal, an applications
# menu, or a desktop right-click menu. Anyone watching can take over this
# screen, and a shell here runs as `runner`, which can read every teammate's
# Firefox profile under /profiles. The desktop is windows, a taskbar and a
# clock — enough to move, resize and switch windows, nothing to launch.
#
# display.py starts this in its own process group and stops it by killing the
# group, so Xvnc and every Xfce component go down together.
set -euo pipefail

: "${HARVIS_DT_DISPLAY_NUM:?}"   # X display number, allocated by display.py
: "${HARVIS_DT_RFB_PORT:?}"      # localhost RFB port the token file points at
: "${HARVIS_DT_HOME:?}"          # per-session XDG config home (xfconf lives here)
GEOM="${HARVIS_DT_GEOMETRY:-1280x800}"

export XDG_CONFIG_HOME="$HARVIS_DT_HOME/config"
export XDG_CACHE_HOME="$HARVIS_DT_HOME/cache"
export XDG_DATA_HOME="$HARVIS_DT_HOME/data"
export XDG_SESSION_TYPE=x11 XDG_CURRENT_DESKTOP=XFCE
export GDK_BACKEND=x11 NO_AT_BRIDGE=1 GTK_A11Y=none
export LANG="${LANG:-C.UTF-8}"
unset SESSION_MANAGER DBUS_SESSION_BUS_ADDRESS DISPLAY XAUTHORITY WAYLAND_DISPLAY

X="$XDG_CONFIG_HOME/xfce4/xfconf/xfce-perchannel-xml"
mkdir -p "$X" "$XDG_CACHE_HOME" "$XDG_DATA_HOME"
export DISPLAY=":$HARVIS_DT_DISPLAY_NUM"

# A lock left by a crashed server blocks a restart on this number. A lock whose
# pid is alive belongs to a running server and is never touched.
xlock="/tmp/.X${HARVIS_DT_DISPLAY_NUM}-lock"
if [[ -e "$xlock" ]] && ! kill -0 "$(tr -d ' ' < "$xlock" 2>/dev/null)" 2>/dev/null; then
  rm -f "$xlock" "/tmp/.X11-unix/X${HARVIS_DT_DISPLAY_NUM}"
fi

# ---- pre-seed xfconf before xfconfd starts (it caches; later edits are overwritten) ----
cat > "$X/xfwm4.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfwm4" version="1.0">
  <property name="general" type="empty">
    <property name="use_compositing" type="bool" value="false"/>
    <property name="workspace_count" type="int" value="1"/>
    <property name="focus_new" type="bool" value="true"/>
    <property name="title_font" type="string" value="DejaVu Sans Bold 9"/>
  </property>
</channel>
EOF
cat > "$X/xsettings.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xsettings" version="1.0">
  <property name="Net" type="empty">
    <property name="EnableEventSounds" type="bool" value="false"/>
  </property>
  <property name="Gtk" type="empty">
    <property name="FontName" type="string" value="DejaVu Sans 10"/>
    <property name="MonospaceFontName" type="string" value="DejaVu Sans Mono 10"/>
  </property>
  <property name="Xft" type="empty">
    <property name="DPI" type="int" value="96"/>
    <property name="Antialias" type="int" value="1"/>
  </property>
</channel>
EOF
cat > "$X/xfce4-desktop.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="backdrop" type="empty">
    <property name="screen0" type="empty">
      <property name="monitorVNC-0" type="empty">
        <property name="workspace0" type="empty">
          <property name="color-style" type="int" value="0"/>
          <property name="image-style" type="int" value="0"/>
          <property name="rgba1" type="array">
            <value type="double" value="0.11"/><value type="double" value="0.12"/>
            <value type="double" value="0.16"/><value type="double" value="1"/>
          </property>
        </property>
      </property>
    </property>
  </property>
  <property name="desktop-icons" type="empty">
    <property name="style" type="int" value="0"/>
  </property>
  <property name="desktop-menu" type="empty">
    <property name="show" type="bool" value="false"/>
  </property>
  <property name="windowlist-menu" type="empty">
    <property name="show" type="bool" value="false"/>
  </property>
</channel>
EOF
# A layout on disk also suppresses the panel's first-run "Welcome" dialog.
cat > "$X/xfce4-panel.xml" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-panel" version="1.0">
  <property name="configver" type="int" value="2"/>
  <property name="panels" type="array">
    <value type="int" value="1"/>
    <property name="dark-mode" type="bool" value="true"/>
    <property name="panel-1" type="empty">
      <property name="position" type="string" value="p=8;x=0;y=0"/>
      <property name="length" type="uint" value="100"/>
      <property name="position-locked" type="bool" value="true"/>
      <property name="size" type="uint" value="28"/>
      <property name="icon-size" type="uint" value="16"/>
      <property name="plugin-ids" type="array">
        <value type="int" value="1"/><value type="int" value="2"/><value type="int" value="3"/>
      </property>
    </property>
  </property>
  <property name="plugins" type="empty">
    <property name="plugin-1" type="string" value="tasklist">
      <property name="grouping" type="bool" value="true"/>
      <property name="show-labels" type="bool" value="true"/>
    </property>
    <property name="plugin-2" type="string" value="separator">
      <property name="expand" type="bool" value="true"/>
      <property name="style" type="uint" value="0"/>
    </property>
    <property name="plugin-3" type="string" value="clock">
      <property name="digital-time-format" type="string" value="%a %H:%M"/>
    </property>
  </property>
</channel>
EOF

# Tests seed the config tree and stop here (no X server needed).
[[ -n "${HARVIS_DT_SEED_ONLY:-}" ]] && exit 0

# ---- X server + RFB on localhost only ----
# SecurityTypes None is safe only because -localhost keeps the port inside this
# container: websockify is the one client, and its per-session token is the
# credential, exactly as with x11vnc -nopw. -SendCutText=0: a watcher never
# receives the clipboard of whatever the agent copied.
Xvnc "$DISPLAY" -geometry "$GEOM" -depth 24 -dpi 96 \
  -rfbport "$HARVIS_DT_RFB_PORT" -localhost -nolisten tcp \
  -SecurityTypes None -AlwaysShared -AcceptSetDesktopSize -SendCutText=0 \
  -desktop "harvis" -Log '*:stderr:0' &
XVNC_PID=$!
trap 'kill "$XVNC_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 100); do
  xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 && break
  kill -0 "$XVNC_PID" 2>/dev/null || { echo "Xvnc exited during startup" >&2; exit 1; }
  sleep 0.1
done
xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 || { echo "Xvnc did not become ready" >&2; exit 1; }

setxkbmap -display "$DISPLAY" us 2>/dev/null || true   # Selenium keystrokes assume a known layout
xset -display "$DISPLAY" s off -dpms s noblank 2>/dev/null || true

# ---- private session bus + Xfce components (no xfce4-session) ----
# Not exec'd: this script stays the supervisor so the EXIT trap reaps Xvnc if
# the panel dies on its own.
dbus-run-session -- bash -c '
  xfsettingsd --sm-client-disable --daemon 2>/dev/null || true
  xfwm4 --compositor=off --sm-client-disable &
  for _ in $(seq 1 50); do xprop -root _NET_SUPPORTING_WM_CHECK >/dev/null 2>&1 && break; sleep 0.1; done
  xfdesktop --sm-client-disable --disable-wm-check &
  exec xfce4-panel --sm-client-disable --disable-wm-check
' && rc=0 || rc=$?
kill "$XVNC_PID" 2>/dev/null || true
exit "$rc"

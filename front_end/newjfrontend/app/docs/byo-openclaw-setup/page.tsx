export default function ByoOpenClawSetupDocPage() {
  return (
    <main className="min-h-screen bg-background">
      <div className="mx-auto max-w-3xl px-4 py-10 space-y-6">
        <h1 className="text-2xl font-semibold">BYO OpenClaw Setup</h1>
        <p className="text-sm text-muted-foreground">
          Bring-your-own OpenClaw gives you full capabilities, your own gateway token,
          and your own model/runtime choices.
        </p>

        <section className="space-y-2 text-sm">
          <h2 className="font-medium">1) Start OpenClaw locally</h2>
          <p>Run your OpenClaw gateway and note the WebSocket URL (for example `ws://localhost:18789`).</p>
        </section>

        <section className="space-y-2 text-sm">
          <h2 className="font-medium">2) Copy your gateway token</h2>
          <p>Use the same token your local OpenClaw gateway expects for operator connections.</p>
        </section>

        <section className="space-y-2 text-sm">
          <h2 className="font-medium">3) Configure Harvis</h2>
          <p>
            Open <code>/settings/openclaw</code>, paste URL + token, click <strong>Test Connection</strong>,
            then <strong>Save &amp; Switch to BYO</strong>.
          </p>
        </section>

        <section className="space-y-2 text-sm">
          <h2 className="font-medium">4) Verify workspace routing</h2>
          <p>
            Launch a workspace task and confirm it executes against your BYO instance rather than the bundled gateway.
          </p>
        </section>
      </div>
    </main>
  )
}

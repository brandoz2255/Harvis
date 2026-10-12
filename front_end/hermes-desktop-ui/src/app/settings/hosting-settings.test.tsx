import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { $session } from '@/lib/harvis-session'

import type { ClusterWorkloads, HostingStatus } from './harvis-api'
import { HostingSettings } from './hosting-settings'

const commands = {
  enable: './install.sh --k8s',
  disable: './install.sh --k8s-off',
  status: './install.sh --k8s-status',
  join: './install.sh --k8s-join-command'
}

const docker: HostingStatus = {
  mode: 'docker',
  detected_by: 'default',
  namespace: null,
  nodes: [],
  nodes_error: null,
  gpu: { available: false, count: 0 },
  lan_models: { enabled: false, url: null },
  docker_socket: true,
  commands
}

const kubernetes: HostingStatus = {
  mode: 'kubernetes',
  detected_by: 'cluster',
  namespace: 'harvis',
  nodes: [
    {
      name: 'pve-lab',
      ready: true,
      roles: ['control-plane', 'master'],
      gpus: 1,
      cpu: '16',
      memory_gib: 62.7,
      version: 'v1.31.4+k3s1'
    }
  ],
  nodes_error: null,
  gpu: { available: true, count: 1 },
  lan_models: { enabled: true, url: 'http://192.168.1.20:31434/v1' },
  docker_socket: true,
  commands
}

const fetchMock = vi.fn<(path: string, init?: RequestInit) => Promise<Response>>()

function answer(body: unknown, status = 200) {
  fetchMock.mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  )
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  return render(
    <QueryClientProvider client={client}>
      <HostingSettings />
    </QueryClientProvider>
  )
}

beforeEach(() => {
  $session.set({ status: 'checking' })
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('HostingSettings', () => {
  it('asks the backend for the hosting status with the session cookie', async () => {
    answer(docker)
    renderPage()

    await screen.findByText('This Harvis runs on Docker')

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/capabilities/hosting',
      expect.objectContaining({ credentials: 'include' })
    )
  })

  it('shows the Docker status and the four installer commands', async () => {
    answer(docker)
    renderPage()

    expect(await screen.findByText('This Harvis runs on Docker')).toBeTruthy()
    expect(screen.queryByText('Models address on your network')).toBeNull()

    for (const command of Object.values(commands)) {
      expect(screen.getByText(command)).toBeTruthy()
    }

    expect(screen.getByText('What Kubernetes hosting mode is')).toBeTruthy()
    expect(screen.getByText('Turn it on or off')).toBeTruthy()
  })

  it('shows the Kubernetes status with a node row and the LAN models address', async () => {
    answer(kubernetes)
    renderPage()

    expect(await screen.findByText('This Harvis runs on Kubernetes (k3s)')).toBeTruthy()
    expect(screen.getByText('pve-lab')).toBeTruthy()
    expect(screen.getByText('Ready')).toBeTruthy()
    expect(screen.getByText('1 GPU · 16 CPU · 62.7 GiB memory · control-plane, master')).toBeTruthy()
    expect(screen.getByText('v1.31.4+k3s1')).toBeTruthy()
    expect(screen.getByText('http://192.168.1.20:31434/v1')).toBeTruthy()
    expect(screen.getByText('Models address on your network')).toBeTruthy()
    expect(screen.getByText('./install.sh --k8s-off')).toBeTruthy()
  })

  it('shows the plain-English reason when the node listing failed', async () => {
    answer({ ...kubernetes, nodes: [], nodes_error: 'The service account is not allowed to list nodes.' })
    renderPage()

    expect(await screen.findByText('Could not list the machines in the cluster')).toBeTruthy()
    expect(screen.getByText('The service account is not allowed to list nodes.')).toBeTruthy()
    expect(screen.getByText(/GPU count unknown until the machines can be listed/)).toBeTruthy()
    expect(screen.queryByText(/No GPU is visible/)).toBeNull()
    expect(screen.queryByText('pve-lab')).toBeNull()
  })

  it('shows an error card when the request fails', async () => {
    answer({ detail: 'Not authenticated' }, 401)
    renderPage()

    expect(await screen.findByText('Could not read the hosting status')).toBeTruthy()
    expect(screen.getByText('Not authenticated')).toBeTruthy()
  })
})

const signedIn = (role: string) => ({
  status: 'signed-in' as const,
  user: { email: 'a@b.test', id: '1', name: 'A', role }
})

const now = Math.round(Date.now() / 1000)

const workloads: ClusterWorkloads = {
  mode: 'kubernetes',
  namespace: 'harvis',
  services: [
    {
      name: 'backend',
      desired: 1,
      ready: 1,
      updated: 1,
      state: 'ready',
      images: [{ name: 'backend', tag: '1.5' }],
      restarts: 0,
      pods: [
        {
          name: 'backend-abc',
          phase: 'Running',
          reason: null,
          ready: true,
          restarts: 0,
          last_restart: null,
          node: 'pve-lab',
          started: now - 7200,
          containers: ['backend']
        }
      ]
    },
    {
      name: 'ollama',
      desired: 1,
      ready: 0,
      updated: 1,
      state: 'down',
      images: [{ name: 'ollama', tag: '0.12' }],
      restarts: 7,
      pods: [
        {
          name: 'ollama-xyz',
          phase: 'Running',
          reason: 'CrashLoopBackOff',
          ready: false,
          restarts: 7,
          last_restart: now - 60,
          node: 'pve-lab',
          started: now - 3600,
          containers: ['ollama']
        }
      ]
    }
  ],
  unmatched_pods: [],
  events: [
    {
      reason: 'BackOff',
      message: 'Back-off restarting failed container',
      object: 'pod/ollama-xyz',
      count: 12,
      last_seen: now - 30
    }
  ],
  error: null
}

function route(map: Record<string, unknown>) {
  fetchMock.mockImplementation(async (path: string) => {
    const key = Object.keys(map).find(k => path.startsWith(k))
    const body = key ? map[key] : { detail: 'nope' }

    return new Response(JSON.stringify(body), {
      status: key ? 200 : 404,
      headers: { 'Content-Type': 'application/json' }
    })
  })
}

describe('HostingSettings cluster panel', () => {
  it('is hidden from people who are not administrators', async () => {
    $session.set(signedIn('user'))
    route({ '/api/capabilities/hosting/workloads': workloads, '/api/capabilities/hosting': kubernetes })
    renderPage()

    await screen.findByText('This Harvis runs on Kubernetes (k3s)')

    expect(screen.queryByText('Services in the cluster')).toBeNull()
    expect(fetchMock.mock.calls.some(([p]) => String(p).includes('/workloads'))).toBe(false)
  })

  it('is hidden on Docker even for an administrator', async () => {
    $session.set(signedIn('admin'))
    route({ '/api/capabilities/hosting': docker })
    renderPage()

    await screen.findByText('This Harvis runs on Docker')

    expect(screen.queryByText('Services in the cluster')).toBeNull()
  })

  it('shows each service, flags the broken one, and lists warnings for an administrator', async () => {
    $session.set(signedIn('admin'))
    route({ '/api/capabilities/hosting/workloads': workloads, '/api/capabilities/hosting': kubernetes })
    renderPage()

    expect(await screen.findByText('Services in the cluster')).toBeTruthy()
    expect(await screen.findByText(/1 service needs attention: ollama/)).toBeTruthy()
    expect(screen.getByText('Running')).toBeTruthy()
    expect(screen.getByText('Down')).toBeTruthy()
    // The broken service opens by itself so its pod and reason are visible.
    expect(screen.getByText('ollama-xyz')).toBeTruthy()
    expect(screen.getAllByText('CrashLoopBackOff').length).toBeGreaterThan(0)
    expect(screen.queryByText('backend-abc')).toBeNull()
    expect(screen.getByText('BackOff')).toBeTruthy()
    expect(screen.getByText('Back-off restarting failed container')).toBeTruthy()
  })

  it("loads a pod's log lines on demand", async () => {
    $session.set(signedIn('admin'))
    route({
      '/api/capabilities/hosting/logs/ollama-xyz': {
        pod: 'ollama-xyz',
        container: null,
        previous: false,
        lines: ['starting ollama', 'error: out of memory']
      },
      '/api/capabilities/hosting/workloads': workloads,
      '/api/capabilities/hosting': kubernetes
    })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Logs/ }))

    expect(await screen.findByText(/error: out of memory/)).toBeTruthy()
    expect(fetchMock.mock.calls.some(([p]) => String(p) === '/api/capabilities/hosting/logs/ollama-xyz')).toBe(true)
  })

  it('says why when the cluster cannot be read', async () => {
    $session.set(signedIn('admin'))
    route({
      '/api/capabilities/hosting/workloads': { ...workloads, services: [], error: 'not allowed to list pods' },
      '/api/capabilities/hosting': kubernetes
    })
    renderPage()

    expect(await screen.findByText('Could not read the cluster: not allowed to list pods')).toBeTruthy()
  })
})

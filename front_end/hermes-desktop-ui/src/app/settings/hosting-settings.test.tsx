import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { HostingStatus } from './harvis-api'
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

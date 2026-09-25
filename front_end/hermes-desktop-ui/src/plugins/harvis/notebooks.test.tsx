/**
 * The Notebooks home is a grid of notebook cards (NotebookLM / open-notebook
 * style); opening one — or making a new one — puts you in its workspace via
 * `#/notebooks?nb=<id>`, and Back returns to the grid.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { routeApi } from "./notebook-test-utils";

const { harvisApi } = vi.hoisted(() => ({ harvisApi: vi.fn() }));

vi.mock("./api", () => ({ harvisApi }));

const { NotebooksPage } = await import("./notebooks");

const mars = {
  id: "nb-1",
  title: "Mars Rover Exploration Texts",
  description: "Everything about Perseverance",
  emoji: "🪐",
  source_count: 3,
  note_count: 1,
  updated_at: "2026-09-01T00:00:00Z",
};

const fresh = {
  ...mars,
  id: "nb-2",
  title: "Untitled notebook",
  description: null,
  emoji: null,
  source_count: 0,
  note_count: 0,
};

function mockRoutes() {
  harvisApi.mockImplementation(
    routeApi({
      "GET /api/notebooks?": () => ({ notebooks: [mars] }),
      "POST /api/notebooks/search": () => ({ results: [] }),
      "POST /api/notebooks": () => fresh,
      "GET /api/notebooks/nb-2/sources": () => [],
      "GET /api/notebooks/nb-2/stats": () => ({
        source_count: 0,
        chunk_count: 0,
        note_count: 0,
        message_count: 0,
        ready_sources: 0,
        processing_sources: 0,
      }),
      "GET /api/notebooks/nb-2/notes": () => ({ notes: [] }),
      "GET /api/notebooks/nb-2": () => fresh,
      "GET /api/notebooks/nb-1/sources": () => [],
      "GET /api/notebooks/nb-1/stats": () => ({
        source_count: 3,
        chunk_count: 9,
        note_count: 1,
        message_count: 0,
        ready_sources: 3,
        processing_sources: 0,
      }),
      "GET /api/notebooks/nb-1/notes": () => ({ notes: [] }),
      "GET /api/notebooks/nb-1": () => mars,
    }),
  );
}

function renderAt(url: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <NotebooksPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  harvisApi.mockReset();
  mockRoutes();
});

afterEach(cleanup);

describe("NotebooksPage", () => {
  it("shows notebooks as cards with a New notebook tile", async () => {
    renderAt("/notebooks");

    const card = await screen.findByRole("button", {
      name: "Open Mars Rover Exploration Texts",
    });
    expect(card.textContent).toContain("Everything about Perseverance");
    expect(card.textContent).toContain("3 sources");
    expect(card.textContent).toContain("1 note");
    expect(screen.getAllByText("New notebook").length).toBeGreaterThan(0);
  });

  it("opens a card into its workspace and Back returns to the grid", async () => {
    renderAt("/notebooks");

    fireEvent.click(
      await screen.findByRole("button", {
        name: "Open Mars Rover Exploration Texts",
      }),
    );
    expect(
      await screen.findByRole("heading", { level: 2, name: /Mars Rover/ }),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "All notebooks" }));
    expect(
      await screen.findByRole("button", {
        name: "Open Mars Rover Exploration Texts",
      }),
    ).toBeTruthy();
  });

  it("opens the notebook a link names", async () => {
    renderAt("/notebooks?nb=nb-1");

    expect(
      await screen.findByRole("heading", { level: 2, name: /Mars Rover/ }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: "Open Mars Rover Exploration Texts",
      }),
    ).toBeNull();
  });

  it("New notebook creates one straight away and opens it", async () => {
    renderAt("/notebooks");

    await screen.findByRole("button", {
      name: "Open Mars Rover Exploration Texts",
    });
    fireEvent.click(screen.getByRole("button", { name: /^New notebook$/ }));

    await waitFor(() =>
      expect(harvisApi).toHaveBeenCalledWith(
        "/api/notebooks",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ title: "Untitled notebook" }),
        }),
      ),
    );
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: /Untitled notebook/,
      }),
    ).toBeTruthy();
  });
});

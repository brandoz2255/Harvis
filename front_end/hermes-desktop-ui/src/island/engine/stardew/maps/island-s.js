// Map preset for the Island_S map. Only coordinates live here — the map and its tilesheets
// come from the user's own game files, imported on their machine.
export const ISLAND_S = {
  map: "Island_S",
  places: {
    plaza: { x: 17, y: 24 },  // open beach in front of the driftwood
    work: { x: 22, y: 23 },   // where agents go while running a task
    dock: { x: 21, y: 40 },
    benchW: { x: 11, y: 24 },
    benchE: { x: 28, y: 22 },
    pools: { x: 36, y: 29 },
    east: { x: 39, y: 12 },
    jungle: { x: 6, y: 12 },
    beach: { x: 26, y: 31 },
    north: { x: 18, y: 9 },
  },
  homeDoors: [{ x: 18, y: 2 }], // everyone goes home up the north stairs
  view: { x: 0, y: 4, w: 43, h: 40 },
};

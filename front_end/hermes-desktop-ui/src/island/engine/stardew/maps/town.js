// Map preset for the Town map (Pelican Town's downtown). Only coordinates live here — the map
// and its tilesheets come from the user's own game files, imported on their machine.
// Every spot is a walkable street tile; door spots are the tile just below a building's door.
export const TOWN = {
  map: "Town",
  places: {
    plaza: { x: 49, y: 64 },     // the square in front of the town mailbox
    work: { x: 43, y: 57 },      // outside the general store; where agents go while running a task
    benchW: { x: 42, y: 62 },
    benchE: { x: 58, y: 66 },
    bridge: { x: 73, y: 53 },    // the plank bridge over the river (row 54 is drawn behind its rail)
    riverside: { x: 68, y: 60 }, // grass on the near bank
    north: { x: 49, y: 51 },     // the road leading out of town
    saloon: { x: 45, y: 72 },
    manor: { x: 58, y: 87 },
  },
  // Doors agents go home through, in the order the sim hands them out.
  homeDoors: [{ x: 57, y: 64 }, { x: 58, y: 86 }, { x: 72, y: 69 }],
  view: { x: 33, y: 49, w: 43, h: 40 },
};

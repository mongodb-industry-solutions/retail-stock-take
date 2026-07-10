export const TALK_TRACK = [
  {
    heading: "Overview",
    content: [
      {
        heading: "Retail Stock-Take, Offline-First",
        body: "A field associate photographs a shelf on a phone or laptop — even with no connectivity. A computer-vision model turns the photo into a structured inventory (product, count, confidence), the raw frame is stored in object storage, and MongoDB holds the inventory plus an asset reference. PowerSync streams every change to all connected clients in real time, and queues writes made while offline until the device reconnects.",
      },
      {
        heading: "What to look for",
        body: [
          "Drop a shelf photo and hit Capture — the CV result appears in seconds.",
          "The Scan Log and the MongoDB document on the right update live via PowerSync, with no page refresh.",
          "The PowerSync badge shows the live/offline sync state; open Pipeline to see the end-to-end data flow.",
        ],
      },
    ],
  },
  {
    heading: "How to Demo",
    content: [
      {
        heading: "Steps",
        body: [
          "Open the app at http://localhost.",
          "Drop or select a shelf photo in the Capture panel and click Capture.",
          "Watch the success banner report the items detected by the model.",
          "See the new entry appear in the Scan Log; select it to inspect the raw MongoDB document.",
          "Toggle the theme, and open Pipeline to walk through browser → FastAPI + CV → MongoDB → PowerSync → clients.",
        ],
      },
    ],
  },
  {
    heading: "Behind the Scenes",
    content: [
      {
        heading: "Architecture",
        body: "The browser posts the photo to a FastAPI backend, which runs the CV model (Ollama / Moondream), writes the inventory document to MongoDB, and persists the raw frame to S3-compatible object storage. MongoDB change streams feed PowerSync, which syncs the data to each client's local SQLite database over a WebSocket. The browser renders directly from that local database, so reads are instant and keep working offline.",
      },
      {
        heading: "Data flow",
        body: [
          "Browser capture → POST /api/inventory/capture",
          "FastAPI + CV model → structured JSON inventory",
          "MongoDB → retail_demo.inventory_captures (+ object-storage asset ref)",
          "PowerSync → global_inventory stream over WebSocket",
          "All clients → local SQLite, live queries",
        ],
      },
    ],
  },
  {
    heading: "Why MongoDB?",
    content: [
      {
        heading: "Change streams power real-time sync",
        body: "PowerSync builds on MongoDB change streams (with pre- and post-images) to capture every write and fan it out to clients — no custom polling or CDC plumbing.",
      },
      {
        heading: "One flexible document model",
        body: "Each capture is a single document holding the inventory items, confidence scores, and a reference to the stored image. The same schema flows unchanged from the backend to every synced client.",
      },
      {
        heading: "Offline-first for the field",
        body: "Retail associates work in stockrooms and stores with unreliable connectivity. PowerSync and MongoDB keep the app fully usable offline and reconcile automatically on reconnect.",
      },
    ],
  },
];

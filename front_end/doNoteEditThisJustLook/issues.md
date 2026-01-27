# State Reconciliation Failure with Optimistic UI in Chat

## Problem

The chat interface exhibits a bug where the user's sent message appears briefly and then disappears, and the user's prompt is sometimes duplicated. This is caused by a **State Reconciliation Failure** with the optimistic UI.

When a user sends a message, the UI optimistically adds the message to the local component state to make the application feel responsive. However, when the authoritative state is received from the server (after the message is persisted in the database), the local and server states are not reconciled correctly. This results in the local (optimistic) state being overwritten by the server state, causing the message to disappear from the UI.

## Root Cause

The core of the issue lies in the lack of a robust mechanism to track messages from their creation on the client to their confirmation on the server. The key missing pieces are:

1.  **Unique Client-Side Identifier:** Without a unique ID generated on the client, it's impossible to reliably find and update the correct message when the server response arrives.
2.  **Message Status:** There is no way to track the status of a message (e.g., `pending`, `sent`, `failed`), which is crucial for rendering the UI correctly and providing feedback to the user.

## Proposed Solution

To fix this, I will implement a more robust optimistic UI pattern based on the recommendations from my research. The solution involves the following steps:

1.  **Introduce a Temporary ID and Status:**
    *   Add a `tempId` (a unique client-side ID) and a `status` (`pending`, `sent`, or `failed`) field to the `Message` interface.

2.  **Modify the `sendMessage` Function:**
    *   When a user sends a message, generate a `tempId` and set the initial `status` to `pending`.
    *   Add the message to the local state optimistically.

3.  **Update the State Reconciliation Logic:**
    *   When the server responds with the confirmed message (which includes the permanent ID from the database), find the corresponding message in the local state using the `tempId`.
    *   Update the message with the permanent ID and set the `status` to `sent`.

4.  **Handle Failures:**
    *   If the server returns an error, update the message's `status` to `failed` to provide feedback to the user.

By implementing this pattern, we can ensure that the local and server states are reconciled correctly, eliminating the race condition and providing a seamless and reliable chat experience.
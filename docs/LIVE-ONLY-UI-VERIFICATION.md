# Live-only UI change

The app entry point opens one persistent `LiveRootView`. There is no initial picker, Choose Video / Import Audio / Split From Link menu, history destination, or Done button dismissing Live. Connection settings expand inline; mixer, transport, output route picker and shared-source links remain. V1 introduces no login screen. Legacy modules and saved data remain intact but are unreachable from the app entry point.

## Routing

The single root receives `onlystems://` URLs and the Shortcut inbox. Old home/history/link routes remain on Live. A source changes the current Live request rather than creating a sheet or player instance. The single-root path no longer needs the former sheet-era one-second URL suppression, so intentionally resharing the same source creates a fresh request.

`LiveSourceRequestGate` consumes one source per request ID after connection setup is ready. It prevents appearance/request callbacks from submitting the same request twice and preserves a first-launch shared source while the user enters an access key. Connect then submits that source instead of silently joining an unrelated stream.

## Validation

- Four focused Swift tests pass: cold callback deduplication, deferred source through key setup, warm repeated same-source requests, and empty-source handling.
- Unsigned iOS Simulator build passes with Xcode 26.3.
- A fresh, headless iPhone 17 Pro / iOS 26.3 simulator launches directly into Live with inline connection setup and mixer. Screenshot: `/private/tmp/live-only-cold.png`.
- OS-level deep-link smoke attempts encountered the system “Open in StemSplitter?” confirmation, so interactive cold/warm deep-link acceptance is not claimed. Request delivery/deduplication is covered by the focused tests; actual Shortcut acceptance remains a device check.
- Model resources are reused through an untracked `Models` symlink to the original checkout; no model copies or credential files were added.

This change does not implement EOF repair, persistent playback recovery/cache, model selection, the three-second startup target or authenticated social-source fetching. Those belong to the playback plan. Existing server-side source-submission races and failure handling also remain outside this UI change. No production deployment or physical-phone installation is performed.

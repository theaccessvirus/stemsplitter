import AppIntents
import SwiftUI
import StemCore
import StemUI

@main
struct StemSplitterApp: App {
    var body: some Scene {
        WindowGroup {
            LiveRootView()
        }
    }
}

/// Shortcuts action that opens the live screen directly. An `Open URLs` step with
/// onlystems:// makes iOS ask "Open in StemSplitter?" first; an app's own intent
/// does not. With a link, the app submits it to the server itself (same path as
/// onlystems://live?src=), so the Shortcut needs no token.
struct PlayInOnlyStemsIntent: AppIntent {
    static let title: LocalizedStringResource = "Play in onlyStems Live"
    static let description = IntentDescription(
        "Opens onlyStems Live and plays the link through the stem server.")
    static let openAppWhenRun = true

    @Parameter(title: "Link")
    var link: URL?

    @MainActor
    func perform() async throws -> some IntentResult {
        var route = URLComponents()
        route.scheme = "onlystems"
        route.host = "live"
        if let link {
            route.queryItems = [URLQueryItem(name: "src", value: link.absoluteString)]
        }
        DeepLinkInbox.shared.pending = route.url
        return .result()
    }
}

struct OnlyStemsShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(
            intent: PlayInOnlyStemsIntent(),
            phrases: ["Open \(.applicationName) Live"],
            shortTitle: "onlyStems Live",
            systemImageName: "waveform")
    }
}

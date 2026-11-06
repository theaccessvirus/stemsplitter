import Foundation
import Combine

/// Hands an onlystems:// route from an App Intent to `AppFlowView`. The intent can
/// run before the view exists (cold launch), so the link waits here until the
/// view subscribes; `@Published` replays the current value to a new subscriber.
@MainActor
public final class DeepLinkInbox: ObservableObject {
    public static let shared = DeepLinkInbox()
    @Published public var pending: URL?
}

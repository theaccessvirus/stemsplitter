import Foundation

/// Consume each shared-source request once, only after connection setup is ready.
/// Keeping an unclaimed request lets first-launch key setup submit it afterwards.
public struct LiveSourceRequestGate {
    private var claimed: UUID?

    public init() {}

    public mutating func claim(request: UUID, source: String?, isReady: Bool) -> String? {
        guard isReady, claimed != request,
              let source = source?.trimmingCharacters(in: .whitespacesAndNewlines),
              !source.isEmpty else { return nil }
        claimed = request
        return source
    }
}

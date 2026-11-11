import XCTest
@testable import StemCore

final class LiveSourceRequestGateTests: XCTestCase {
    func testColdLinkIsSubmittedOnceAcrossAppearanceAndRequestCallbacks() {
        var gate = LiveSourceRequestGate()
        let request = UUID()
        XCTAssertEqual(gate.claim(request: request, source: "https://example.com/song", isReady: true), "https://example.com/song")
        XCTAssertNil(gate.claim(request: request, source: "https://example.com/song", isReady: true))
    }

    func testLinkWaitsForKeySetupInsteadOfBeingLost() {
        var gate = LiveSourceRequestGate()
        let request = UUID()
        XCTAssertNil(gate.claim(request: request, source: "https://example.com/song", isReady: false))
        XCTAssertEqual(gate.claim(request: request, source: "https://example.com/song", isReady: true), "https://example.com/song")
    }

    func testWarmReshareOfSameSourceIsANewRequest() {
        var gate = LiveSourceRequestGate()
        for _ in 0..<2 {
            XCTAssertEqual(gate.claim(request: UUID(), source: "https://example.com/song", isReady: true), "https://example.com/song")
        }
    }

    func testEmptySourceDoesNotConsumeRequest() {
        var gate = LiveSourceRequestGate()
        let request = UUID()
        XCTAssertNil(gate.claim(request: request, source: "  ", isReady: true))
        XCTAssertEqual(gate.claim(request: request, source: "https://example.com/song", isReady: true), "https://example.com/song")
    }
}

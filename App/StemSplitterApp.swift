import SwiftUI
import StemCore
import StemUI

@main
struct StemSplitterApp: App {
    private let engine = DemucsEngine()

    init() {
        // History persists across launches (Application Support). Launch hygiene
        // is orphans only: dead in-progress sessions from an interrupted split.
        SplitStore(baseDirectory: SplitStore.defaultBaseDirectory()).purgeOrphans()
    }

    var body: some Scene {
        WindowGroup {
            AppFlowView(engine: engine)
        }
    }
}

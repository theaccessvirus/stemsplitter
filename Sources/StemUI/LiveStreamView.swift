import SwiftUI
import AVFoundation
import StemCore
import Security
#if os(iOS)
import AVKit
#endif

@MainActor
final class LiveStreamPlayer: ObservableObject {
    @Published var status = "Disconnected"
    @Published var connected = false
    @Published var buffered = 0.0
    @Published var gains: [Float] = [1, 1, 1, 1]
    @Published var muted = [false, false, false, false]
    @Published var solo = [false, false, false, false]
    private var engine = AVAudioEngine()
    private var node = AVAudioPlayerNode()
    private var socket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var pumpTask: Task<Void, Never>?
    private var queue: [LiveStemPacket] = []
    private var queuedFrames = 0
    private var scheduledFrames = 0
    private var expected: UInt64?
    private var started = false
    private var previousLevels: [Float] = [1, 1, 1, 1]
    private var generation = UUID()
    private let rate = 44100.0
    /// Set by connect(), cleared only by a user disconnect: while set, any drop
    /// (network, audio interruption, backgrounding) reconnects on its own.
    private var target: (endpoint: String, token: String)?
    private var retryTask: Task<Void, Never>?
    private var retries = 0
    private var interruptionObserver: NSObjectProtocol?

    init() {
        #if os(iOS)
        interruptionObserver = NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] note in
            guard let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                  AVAudioSession.InterruptionType(rawValue: raw) == .ended else { return }
            Task { @MainActor [weak self] in self?.resumeIfDropped() }
        }
        #endif
    }

    /// Reconnect now if a connection is wanted but not live (app foregrounded,
    /// audio interruption ended).
    func resumeIfDropped() {
        guard let target, !connected else { return }
        retryTask?.cancel(); retryTask = nil
        connect(endpoint: target.endpoint, token: target.token)
    }

    private func dropped(_ message: String) {
        teardown()
        status = message
        guard let target else { return }
        retries += 1
        let delay = min(30, 1 << min(retries, 5))
        status = "\(message) Reconnecting in \(delay) s…"
        retryTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(delay))
            guard !Task.isCancelled, let self, self.target != nil, !self.connected else { return }
            self.connect(endpoint: target.endpoint, token: target.token)
        }
    }

    func connect(endpoint: String, token: String) {
        teardown()
        retryTask?.cancel(); retryTask = nil
        guard let url = URL(string: endpoint), url.scheme == "wss", url.host != nil,
              url.user == nil, url.password == nil, !token.isEmpty else {
            status = "Enter a wss:// server address and access key in Settings."
            target = nil
            return
        }
        target = (endpoint, token)
        let run = generation
        do {
            #if os(iOS)
            try AVAudioSession.sharedInstance().setCategory(.playback, mode: .default)
            try AVAudioSession.sharedInstance().setActive(true)
            #endif
            engine = AVAudioEngine()
            node = AVAudioPlayerNode()
            engine.attach(node)
            engine.connect(node, to: engine.mainMixerNode,
                           format: AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2))
            try engine.start()
        } catch {
            dropped("Audio output: \(error.localizedDescription).")
            return
        }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        let ws = URLSession.shared.webSocketTask(with: request)
        ws.maximumMessageSize = 150_000
        socket = ws
        connected = true
        status = "Connecting…"
        ws.resume()
        receiveTask = Task { [weak self] in
            guard let self else { return }
            do {
                let first = try await ws.receive()
                guard case .string(let text) = first,
                      let data = text.data(using: .utf8),
                      let meta = try JSONSerialization.jsonObject(with: data) as? [String: Any],
                      meta["protocol"] as? String == "OS01",
                      meta["sampleRate"] as? Int == 44100,
                      meta["channelsPerStem"] as? Int == 2,
                      meta["format"] as? String == "float32le",
                      meta["stems"] as? [String] == ["drums", "bass", "other", "vocals"] else {
                    throw StreamError.protocolMismatch
                }
                guard generation == run else { return }
                retries = 0
                status = "Waiting for capture…"
                while !Task.isCancelled {
                    let message = try await ws.receive()
                    guard generation == run else { return }
                    guard case .data(let data) = message else { throw StreamError.protocolMismatch }
                    let packet = try LiveStemPacket(data: data)
                    if let expected, packet.position != expected { throw StreamError.discontinuity }
                    expected = packet.position + UInt64(packet.frames)
                    guard queuedFrames + scheduledFrames + packet.frames <= 44100 * 10 else {
                        throw StreamError.tooFarBehind
                    }
                    queue.append(packet)
                    queuedFrames += packet.frames
                }
            } catch {
                guard generation == run else { return }
                dropped("Stream stopped: \(error.localizedDescription)")
            }
        }
        pumpTask = Task { [weak self] in
            while !Task.isCancelled {
                self?.pump(run: run)
                try? await Task.sleep(for: .milliseconds(50))
            }
        }
    }

    private func pump(run: UUID) {
        guard generation == run, connected else { return }
        buffered = Double(queuedFrames + scheduledFrames) / rate
        guard engine.isRunning else {
            dropped("Audio output interrupted.")
            return
        }
        if !started {
            guard queuedFrames >= 44100 * 4 else {
                if queuedFrames > 0 { status = "Buffering \(buffered.formatted(.number.precision(.fractionLength(1)))) / 4 s" }
                return
            }
            started = true
        }
        while scheduledFrames < 13230, !queue.isEmpty {
            let packet = queue.removeFirst()
            queuedFrames -= packet.frames
            let format = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2)!
            let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: AVAudioFrameCount(packet.frames))!
            buffer.frameLength = AVAudioFrameCount(packet.frames)
            let anySolo = solo.contains(true)
            let levels = (0..<4).map { muted[$0] || (anySolo && !solo[$0]) ? Float(0) : gains[$0] }
            for frame in 0..<packet.frames {
                for channel in 0..<2 {
                    var value: Float = 0
                    for stem in 0..<4 {
                        let ramp = min(1, Float(frame) / 128)
                        let gain = previousLevels[stem] + (levels[stem] - previousLevels[stem]) * ramp
                        value += packet.samples[frame * 8 + stem * 2 + channel] * gain
                    }
                    buffer.floatChannelData![channel][frame] = min(1, max(-1, value))
                }
            }
            previousLevels = levels
            scheduledFrames += packet.frames
            let count = packet.frames
            node.scheduleBuffer(buffer, completionCallbackType: .dataPlayedBack) { [weak self] _ in
                Task { @MainActor [weak self] in
                    guard let self, self.generation == run else { return }
                    self.scheduledFrames = max(0, self.scheduledFrames - count)
                }
            }
        }
        if !node.isPlaying { node.play() }
        if scheduledFrames == 0 {
            node.stop()
            started = false
            status = "Rebuffering…"
        } else {
            status = "Playing · cloud separation"
        }
    }

    /// User-initiated stop: no automatic reconnect afterwards.
    func disconnect() {
        target = nil
        retryTask?.cancel(); retryTask = nil
        retries = 0
        teardown()
    }

    private func teardown() {
        generation = UUID()
        receiveTask?.cancel(); receiveTask = nil
        pumpTask?.cancel(); pumpTask = nil
        socket?.cancel(with: .goingAway, reason: nil); socket = nil
        node.stop(); engine.stop()
        queue.removeAll(); queuedFrames = 0; scheduledFrames = 0
        expected = nil; started = false; previousLevels = [1, 1, 1, 1]; buffered = 0; connected = false
        status = "Disconnected"
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
    }

    enum StreamError: LocalizedError {
        case protocolMismatch, discontinuity, tooFarBehind
        var errorDescription: String? {
            switch self {
            case .protocolMismatch: "Server audio format is incompatible."
            case .discontinuity: "Audio timeline changed."
            case .tooFarBehind: "Playback fell more than 10 seconds behind."
            }
        }
    }
}

public struct LiveStreamView: View {
    @StateObject private var player = LiveStreamPlayer()
    @AppStorage("onlyStemsLiveEndpoint") private var endpoint = "wss://theaccessvir.us/onlystems/listen"
    @State private var token = ""
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @State private var showingSettings = false
    private let names = ["Drums", "Bass", "Other", "Vocals"]
    private let colors: [Color] = [.red, .green, .orange, .cyan]
    /// Opened from the onlystems:// deep link: connect on appear using the saved key.
    private let autoConnect: Bool
    /// A URL shared in from YouTube: submit it to the server, then play.
    private let source: String?
    @State private var sourceTitle = ""
    @State private var sourceDuration = 0
    @State private var submitting = false

    public init(autoConnect: Bool = false, source: String? = nil) {
        self.autoConnect = autoConnect
        self.source = source
    }

    public var body: some View {
        NavigationStack {
            Form {
                if submitting || !sourceTitle.isEmpty {
                    Section("Now playing") {
                        if submitting { HStack { ProgressView(); Text("Sending to server…") } }
                        if !sourceTitle.isEmpty {
                            Text(sourceTitle).font(.headline)
                            if sourceDuration > 0 {
                                Text(durationLabel(sourceDuration)).foregroundStyle(Color.ssTextSecondary)
                            }
                        }
                        if let source, let link = URL(string: source) {
                            Link(destination: link) {
                                Label("Open in YouTube", systemImage: "arrow.up.right.square")
                            }
                        }
                    }
                }
                Section {
                    Text(player.status).accessibilityAddTraits(.updatesFrequently)
                    if player.connected { Text("Buffered: \(player.buffered, specifier: "%.1f") s") }
                }
                Section("Mixer") {
                    ForEach(0..<4, id: \.self) { i in
                        VStack(alignment: .leading) {
                            HStack {
                                Text(names[i]).foregroundStyle(colors[i])
                                Spacer()
                                Toggle("Mute", isOn: $player.muted[i]).toggleStyle(.button)
                                    .accessibilityLabel("Mute \(names[i])")
                                Toggle("Solo", isOn: $player.solo[i]).toggleStyle(.button)
                                    .accessibilityLabel("Solo \(names[i])")
                            }
                            Slider(value: $player.gains[i], in: 0...1)
                                .tint(colors[i]).accessibilityLabel("\(names[i]) volume")
                        }
                    }
                }
                Section("Output") {
                    #if os(iOS)
                    HStack { Text("Choose speakers or headphones"); Spacer(); StreamRoutePicker().frame(width: 44, height: 44) }
                    #else
                    Text("Uses the Mac’s selected audio output.")
                    #endif
                }
                Section {
                    Text("Capture is sent to your separation server. Model weights stay there. This live preview does not save a recording.")
                        .font(.footnote)
                }
            }
            .navigationTitle("onlyStems Live")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button { showingSettings = true } label: { Image(systemName: "gearshape") }
                        .accessibilityLabel("Settings")
                }
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .sheet(isPresented: $showingSettings) { settings }
            .onChange(of: scenePhase) { _, phase in
                // Back from the background: iOS may have dropped the socket or
                // stopped the engine while away. Resume without a tap.
                if phase == .active { player.resumeIfDropped() }
            }
            .onAppear {
                token = LiveStreamKey.load()
                let key = token.trimmingCharacters(in: .whitespacesAndNewlines)
                if key.isEmpty { showingSettings = true }
                // Auto-connect on every open when a key is saved, not only via deep
                // link. A shared URL (deep link) submits first; a plain open connects.
                if !player.connected, !key.isEmpty {
                    if let source, !source.isEmpty {
                        Task { await submitThenConnect(source, key: key) }
                    } else {
                        player.connect(endpoint: endpoint.trimmingCharacters(in: .whitespacesAndNewlines), token: key)
                    }
                }
                #if DEBUG && targetEnvironment(simulator)
                if ProcessInfo.processInfo.arguments.contains("-SSLiveSmokeTest"),
                   let directory = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first,
                   let key = try? String(contentsOf: directory.appendingPathComponent("live-smoke-key.txt"), encoding: .utf8) {
                    token = key.trimmingCharacters(in: .whitespacesAndNewlines)
                    player.connect(endpoint: endpoint, token: token)
                }
                #endif
            }
            .onChange(of: source) { _, newSource in
                // A new shared link arriving while the screen is already open:
                // onAppear fired only once, so resubmit here to swap the track.
                guard let newSource, !newSource.isEmpty else { return }
                let key = token.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !key.isEmpty else { return }
                Task { await submitThenConnect(newSource, key: key) }
            }
            .onDisappear { player.disconnect() }
        }
    }

    private var settings: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    TextField("wss://server/onlystems/listen", text: $endpoint)
                        .autocorrectionDisabled()
                        #if os(iOS)
                        .textInputAutocapitalization(.never)
                        .keyboardType(.URL)
                        #endif
                    SecureField("Access key", text: $token)
                        .autocorrectionDisabled()
                }
                Section {
                    Button(player.connected ? "Disconnect" : "Connect") {
                        if player.connected { player.disconnect() }
                        else { connectFromSettings() }
                    }
                    Text(player.status)
                }
            }
            .navigationTitle("Settings")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { showingSettings = false }
                }
            }
        }
    }

    private func connectFromSettings() {
        let key = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else { return }
        LiveStreamKey.save(key)
        player.connect(endpoint: endpoint.trimmingCharacters(in: .whitespacesAndNewlines), token: key)
    }

    /// POST the shared URL to the server (starts separation), show its title,
    /// then connect to the live stream with the same key.
    private func submitThenConnect(_ url: String, key: String) async {
        submitting = true
        defer { submitting = false }
        if let endpoint = submitEndpoint() {
            var request = URLRequest(url: endpoint)
            request.httpMethod = "POST"
            request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: ["url": url])
            if let (data, response) = try? await URLSession.shared.data(for: request),
               (response as? HTTPURLResponse)?.statusCode == 200,
               let meta = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                sourceTitle = (meta["title"] as? String) ?? ""
                sourceDuration = (meta["duration"] as? Int) ?? 0
            }
        }
        player.connect(endpoint: self.endpoint.trimmingCharacters(in: .whitespacesAndNewlines), token: key)
    }

    /// The submit endpoint is the listen endpoint with ws(s)→http(s) and /listen→/submit.
    private func submitEndpoint() -> URL? {
        var address = endpoint.trimmingCharacters(in: .whitespacesAndNewlines)
        address = address.replacingOccurrences(of: "wss://", with: "https://")
                         .replacingOccurrences(of: "ws://", with: "http://")
        if address.hasSuffix("/listen") { address = String(address.dropLast(7)) + "/submit" }
        return URL(string: address)
    }

    private func durationLabel(_ seconds: Int) -> String {
        let h = seconds / 3600, m = (seconds % 3600) / 60, s = seconds % 60
        return h > 0 ? String(format: "%d:%02d:%02d", h, m, s) : String(format: "%d:%02d", m, s)
    }
}

#if os(iOS)
private struct StreamRoutePicker: UIViewRepresentable {
    func makeUIView(context: Context) -> AVRoutePickerView {
        let view = AVRoutePickerView()
        view.prioritizesVideoDevices = false
        return view
    }
    func updateUIView(_ uiView: AVRoutePickerView, context: Context) {}
}
#endif

// The private stream key stays in this device's Keychain, never UserDefaults.
@MainActor
private enum LiveStreamKey {
    static let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                      kSecAttrService as String: "onlyStems.live",
                                      kSecAttrAccount as String: "stream"]
    static func load() -> String {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(request as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }
    static func save(_ token: String) {
        let data = Data(token.trimmingCharacters(in: .whitespacesAndNewlines).utf8)
        if SecItemUpdate(query as CFDictionary, [kSecValueData as String: data] as CFDictionary) == errSecItemNotFound {
            var item = query
            item[kSecValueData as String] = data
            item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            SecItemAdd(item as CFDictionary, nil)
        }
    }
}

import Foundation

/// OS01: little-endian magic, absolute sample position, frame count, then
/// interleaved drums L/R, bass L/R, other L/R, vocals L/R float32 samples.
public struct LiveStemPacket: Sendable {
    public let position: UInt64
    public let frames: Int
    public let samples: [Float]

    public init(data: Data) throws {
        guard data.count >= 16, data.prefix(4) == Data("OS01".utf8) else {
            throw PacketError.invalid
        }
        position = data.withUnsafeBytes { UInt64(littleEndian: $0.loadUnaligned(fromByteOffset: 4, as: UInt64.self)) }
        frames = Int(data.withUnsafeBytes { UInt32(littleEndian: $0.loadUnaligned(fromByteOffset: 12, as: UInt32.self)) })
        guard frames > 0, frames <= 4410, data.count == 16 + frames * 8 * 4 else {
            throw PacketError.invalid
        }
        let count = frames * 8
        samples = data.withUnsafeBytes { bytes in
            (0..<count).map {
                Float(bitPattern: UInt32(littleEndian: bytes.loadUnaligned(fromByteOffset: 16 + $0 * 4, as: UInt32.self)))
            }
        }
        guard samples.allSatisfy(\.isFinite) else { throw PacketError.invalid }
    }

    public enum PacketError: Error { case invalid }
}

import XCTest
@testable import StemCore

final class LiveStemPacketTests: XCTestCase {
    func testAlignedStereoStemsAndSamplePosition() throws {
        var data = Data("OS01".utf8)
        var position = UInt64(12345).littleEndian
        var frames = UInt32(1).littleEndian
        withUnsafeBytes(of: &position) { data.append(contentsOf: $0) }
        withUnsafeBytes(of: &frames) { data.append(contentsOf: $0) }
        for i in 0..<8 {
            var sample = Float(i).bitPattern.littleEndian
            withUnsafeBytes(of: &sample) { data.append(contentsOf: $0) }
        }
        let packet = try LiveStemPacket(data: data)
        XCTAssertEqual(packet.position, 12345)
        XCTAssertEqual(packet.frames, 1)
        XCTAssertEqual(packet.samples, (0..<8).map(Float.init))
        XCTAssertThrowsError(try LiveStemPacket(data: data.dropLast()))
        var overflow = data
        for i in 4..<12 { overflow[i] = 255 }
        XCTAssertThrowsError(try LiveStemPacket(data: overflow))
        data[0] = 0
        XCTAssertThrowsError(try LiveStemPacket(data: data))
    }
}

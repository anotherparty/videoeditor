import AVFoundation
let IN = CommandLine.arguments[1]
let OUT = CommandLine.arguments[2]
let BR = CommandLine.arguments.count > 3 ? Int(CommandLine.arguments[3])! : 1_200_000
func die(_ m:String)->Never{ FileHandle.standardError.write((m+"\n").data(using:.utf8)!); exit(1) }

let asset = AVURLAsset(url: URL(fileURLWithPath: IN))
guard let vTrack = asset.tracks(withMediaType: .video).first else { die("no video") }
let aTrack = asset.tracks(withMediaType: .audio).first
let sz = vTrack.naturalSize
// optional 4th arg: output width (e.g. 720) to keep small upload copies sharp at low bitrates
let OW = CommandLine.arguments.count > 4 ? Int(CommandLine.arguments[4])! : Int(sz.width)
let OH = Int((CGFloat(OW) * sz.height / sz.width / 2).rounded()) * 2

let reader = try! AVAssetReader(asset: asset)
let vOut = AVAssetReaderTrackOutput(track: vTrack,
  outputSettings: [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange])
reader.add(vOut)
var aOut: AVAssetReaderTrackOutput?
if let a = aTrack {
  let o = AVAssetReaderTrackOutput(track: a, outputSettings: [AVFormatIDKey: kAudioFormatLinearPCM])
  reader.add(o); aOut = o
}

try? FileManager.default.removeItem(atPath: OUT)
let writer = try! AVAssetWriter(outputURL: URL(fileURLWithPath: OUT), fileType: .mp4)
let vIn = AVAssetWriterInput(mediaType: .video, outputSettings: [
  AVVideoCodecKey: AVVideoCodecType.h264,
  AVVideoWidthKey: OW, AVVideoHeightKey: OH, AVVideoScalingModeKey: AVVideoScalingModeResizeAspectFill,
  AVVideoCompressionPropertiesKey: [
    AVVideoAverageBitRateKey: BR, AVVideoMaxKeyFrameIntervalKey: 60,
    AVVideoProfileLevelKey: AVVideoProfileLevelH264HighAutoLevel ]])
vIn.expectsMediaDataInRealTime = false
writer.add(vIn)
var aIn: AVAssetWriterInput?
if aOut != nil {
  let i = AVAssetWriterInput(mediaType: .audio, outputSettings: [
    AVFormatIDKey: kAudioFormatMPEG4AAC, AVNumberOfChannelsKey: 2,
    AVSampleRateKey: 44100, AVEncoderBitRateKey: 96000])
  i.expectsMediaDataInRealTime = false
  writer.add(i); aIn = i
}

guard reader.startReading() else { die("startReading: \(String(describing: reader.error))") }
guard writer.startWriting() else { die("startWriting: \(String(describing: writer.error))") }
writer.startSession(atSourceTime: .zero)

let grp = DispatchGroup()
grp.enter()
vIn.requestMediaDataWhenReady(on: DispatchQueue(label:"v")) {
  while vIn.isReadyForMoreMediaData {
    if let sb = vOut.copyNextSampleBuffer() {
      if !vIn.append(sb) { die("v append: \(String(describing: writer.error))") }
    } else { vIn.markAsFinished(); grp.leave(); break }
  }
}
if let aIn = aIn, let aOut = aOut {
  grp.enter()
  aIn.requestMediaDataWhenReady(on: DispatchQueue(label:"a")) {
    while aIn.isReadyForMoreMediaData {
      if let sb = aOut.copyNextSampleBuffer() {
        if !aIn.append(sb) { die("a append: \(String(describing: writer.error))") }
      } else { aIn.markAsFinished(); grp.leave(); break }
    }
  }
}

let sem = DispatchSemaphore(value: 0)
grp.notify(queue: DispatchQueue(label:"done")) {
  if reader.status == .failed { die("reader: \(String(describing: reader.error))") }
  writer.finishWriting {
    if writer.status == .completed { print("OK") } else { die("writer: \(String(describing: writer.error))") }
    sem.signal()
  }
}
sem.wait()

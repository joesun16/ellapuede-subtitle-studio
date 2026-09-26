import Foundation
import Vision
import ImageIO

// JSON-lines worker. Images stay on this machine; stdout is protocol-only.
while let line = readLine() {
    autoreleasepool {
        do {
            guard let input = line.data(using: .utf8),
                  let args = try JSONSerialization.jsonObject(with: input) as? [String: Any],
                  let encoded = args["image"] as? String,
                  let data = Data(base64Encoded: encoded),
                  let source = CGImageSourceCreateWithData(data as CFData, nil),
                  let image = CGImageSourceCreateImageAtIndex(source, 0, nil)
            else { throw NSError(domain: "OCR", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid image input"]) }
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            let languages = args["languages"] as? [String] ?? ["auto"]
            if languages.contains("auto") {
                request.automaticallyDetectsLanguage = true
            } else {
                request.recognitionLanguages = languages
            }
            request.usesLanguageCorrection = args["correction"] as? Bool ?? false
            request.customWords = args["words"] as? [String] ?? []
            request.minimumTextHeight = 0.015
            let handler = VNImageRequestHandler(cgImage: image, options: [:])
            try handler.perform([request])
            let lines: [[String: Any]] = (request.results ?? []).map { observation in
                let box = observation.boundingBox
                return ["box": [box.minX, 1 - box.maxY, box.width, box.height],
                        "candidates": observation.topCandidates(3).map { ["text": $0.string, "confidence": $0.confidence] }]
            }
            let result = try JSONSerialization.data(withJSONObject: ["lines": lines, "revision": request.revision], options: [.sortedKeys])
            print(String(decoding: result, as: UTF8.self))
        } catch {
            let result = try! JSONSerialization.data(withJSONObject: ["error": error.localizedDescription])
            print(String(decoding: result, as: UTF8.self))
        }
        fflush(stdout)
    }
}

import Foundation

enum LinkExtractor {
    /// The first web link in a piece of text (TikTok and Instagram often share "caption https://…").
    static func firstURL(in text: String) -> URL? {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else { return nil }
        let range = NSRange(text.startIndex..., in: text)
        for match in detector.matches(in: text, options: [], range: range) {
            if let url = match.url, url.scheme == "https" || url.scheme == "http" {
                return url
            }
        }
        return nil
    }
}

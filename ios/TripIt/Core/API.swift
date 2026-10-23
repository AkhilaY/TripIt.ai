import Foundation

struct APIError: LocalizedError {
    let status: Int
    let message: String
    var errorDescription: String? { message }
    var isSignedOut: Bool { status == 401 }
}

/// Talks to the TripIt server with your session (the same API the web app uses).
final class API: @unchecked Sendable {
    static let shared = API()
    /// Sent when the server says the session has ended, so the app goes back to the sign-in screen.
    static let signedOut = Notification.Name("TripItSignedOut")

    private let session: URLSession
    private let decoder: JSONDecoder

    init() {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 150  // AI planning and menu reading can take a minute or two
        config.timeoutIntervalForResource = 300
        config.httpCookieAcceptPolicy = .never  // the session goes in the Authorization header instead
        session = URLSession(configuration: config)
        decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
    }

    var base: URL { AppConfig.baseURL }

    /// A server path such as "/v1/places/abc/photos/0?sig=…" as a full URL.
    func url(_ path: String) -> URL? {
        if path.hasPrefix("http://") || path.hasPrefix("https://") { return URL(string: path) }
        return URL(string: path, relativeTo: base)?.absoluteURL
    }

    func get<T: Decodable>(_ path: String, as type: T.Type = T.self) async throws -> T {
        try decode(await send("GET", path))
    }

    func post<T: Decodable>(_ path: String, _ body: [String: Any?] = [:], as type: T.Type = T.self) async throws -> T {
        try decode(await send("POST", path, body: body))
    }

    func patch<T: Decodable>(_ path: String, _ body: [String: Any?], as type: T.Type = T.self) async throws -> T {
        try decode(await send("PATCH", path, body: body))
    }

    func put<T: Decodable>(_ path: String, _ body: [String: Any?], as type: T.Type = T.self) async throws -> T {
        try decode(await send("PUT", path, body: body))
    }

    /// For calls whose answer isn't needed (or is 204 No Content).
    func call(_ method: String, _ path: String, _ body: [String: Any?]? = nil) async throws {
        _ = try await send(method, path, body: body)
    }

    func delete<T: Decodable>(_ path: String, as type: T.Type = T.self) async throws -> T {
        try decode(await send("DELETE", path))
    }

    private func decode<T: Decodable>(_ data: Data) throws -> T {
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            #if DEBUG
            print("Couldn't decode \(T.self): \(error)")
            #endif
            throw APIError(status: 0, message: "The Travel Edit sent something this version of the app can't read. Try updating the app.")
        }
    }

    private func send(_ method: String, _ path: String, body: [String: Any?]? = nil) async throws -> Data {
        guard let url = self.url(path) else { throw APIError(status: 0, message: "Bad address") }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let token = SessionStore.token {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body.mapValues { $0 ?? NSNull() })
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch {
            throw APIError(status: 0, message: "You're offline, or The Travel Edit can't be reached right now.")
        }
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            if status == 401, SessionStore.token != nil, !path.hasPrefix("/v1/auth/") {
                await MainActor.run { NotificationCenter.default.post(name: API.signedOut, object: nil) }
            }
            throw APIError(status: status, message: Self.detail(in: data) ?? "Something went wrong (\(status)). Try again.")
        }
        return data.isEmpty ? Data("null".utf8) : data
    }

    /// FastAPI's error message: a string, or the first validation error.
    private static func detail(in data: Data) -> String? {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        if let text = json["detail"] as? String { return text }
        if let list = json["detail"] as? [[String: Any]], let first = list.first?["msg"] as? String {
            return first.replacingOccurrences(of: "Value error, ", with: "")
        }
        return nil
    }
}

/// For calls that answer with nothing useful.
struct Empty: Decodable {
    init(from decoder: Decoder) throws {}
}

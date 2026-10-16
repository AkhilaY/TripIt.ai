import Foundation

enum APIError: LocalizedError {
    case notConfigured
    case http(Int, String?)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .notConfigured: return "Set the backend URL in Settings."
        case .http(let code, let detail): return detail ?? "Server error (\(code))"
        case .invalidResponse: return "Unexpected response from the server."
        }
    }
}

struct APIClient {
    var baseURL: URL?
    var apiKey: String
    var session: URLSession

    init(baseURL: URL? = AppConfig.apiBaseURL, apiKey: String = AppConfig.apiKey, timeout: TimeInterval = 60) {
        self.baseURL = baseURL
        self.apiKey = apiKey
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = timeout
        self.session = URLSession(configuration: config)
    }

    func createJob(url: String, sharedText: String?) async throws -> JobDTO {
        try await send("v1/jobs", method: "POST", body: CreateJobRequest(url: url, sharedText: sharedText))
    }

    func job(id: String) async throws -> JobDTO {
        try await send("v1/jobs/\(id)", method: "GET", body: Optional<CreateJobRequest>.none)
    }

    func planItinerary(_ request: PlanRequestDTO) async throws -> PlanResultDTO {
        try await send("v1/itineraries", method: "POST", body: request)
    }

    func health() async throws {
        let _: [String: Bool] = try await send("health", method: "GET", body: Optional<CreateJobRequest>.none)
    }

    private func send<Body: Encodable, Response: Decodable>(_ path: String, method: String, body: Body?) async throws -> Response {
        guard let baseURL else { throw APIError.notConfigured }
        var request = URLRequest(url: baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if !apiKey.isEmpty {
            request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        }
        if let body {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            request.httpBody = try encoder.encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }

        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            throw APIError.http(http.statusCode, Self.errorDetail(from: data))
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Response.self, from: data)
    }

    private static func errorDetail(from data: Data) -> String? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        if let detail = object["detail"] as? String { return detail }
        if let details = object["detail"] as? [[String: Any]], let first = details.first?["msg"] as? String { return first }
        return nil
    }
}

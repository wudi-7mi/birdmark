import Foundation

enum APIError: LocalizedError {
    case invalidURL
    case invalidResponse
    case unauthorized
    case server(status: Int, message: String)
    case decoding(String)
    case transport(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "API 地址无效"
        case .invalidResponse:
            return "服务响应无效"
        case .unauthorized:
            return "登录已失效，请重新登录"
        case .server(_, let message):
            return message
        case .decoding(let message):
            return "数据解析失败：\(message)"
        case .transport(let message):
            return "网络请求失败：\(message)"
        }
    }
}

final class APIClient {
    static let shared = APIClient()

    var accessToken: String?

    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(session: URLSession = .shared) {
        self.session = session
        self.decoder = JSONDecoder()
        self.decoder.keyDecodingStrategy = .convertFromSnakeCase
        self.encoder = JSONEncoder()
        self.encoder.keyEncodingStrategy = .convertToSnakeCase
    }

    func get<Response: Decodable>(
        _ path: String,
        queryItems: [URLQueryItem] = []
    ) async throws -> Response {
        var request = try makeRequest(path: path, queryItems: queryItems)
        request.httpMethod = "GET"
        return try await perform(request)
    }

    func postJSON<Body: Encodable, Response: Decodable>(
        _ path: String,
        body: Body
    ) async throws -> Response {
        var request = try makeRequest(path: path)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try encoder.encode(body)
        return try await perform(request)
    }

    func postEmpty<Response: Decodable>(_ path: String) async throws -> Response {
        var request = try makeRequest(path: path)
        request.httpMethod = "POST"
        return try await perform(request)
    }

    func delete<Response: Decodable>(_ path: String) async throws -> Response {
        var request = try makeRequest(path: path)
        request.httpMethod = "DELETE"
        return try await perform(request)
    }

    func uploadPhoto(
        imageData: Data,
        filename: String = "upload.jpg",
        topK: Int = 5,
        autoAnalyze: Bool = true
    ) async throws -> PhotoDetailResponse {
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = try makeRequest(
            path: "/photos",
            queryItems: [
                URLQueryItem(name: "top_k", value: String(topK)),
                URLQueryItem(name: "auto_analyze", value: autoAnalyze ? "true" : "false")
            ]
        )
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = makeMultipartBody(
            boundary: boundary,
            fieldName: "file",
            filename: filename,
            mimeType: "image/jpeg",
            data: imageData
        )
        return try await perform(request)
    }

    func createManualObservation(
        photoID: Int,
        request body: ManualObservationRequest
    ) async throws -> ObservationResponse {
        try await postJSON("/photos/\(photoID)/observations/manual", body: body)
    }

    func mediaURL(from rawPath: String?) -> URL? {
        guard let rawPath, !rawPath.isEmpty else {
            return nil
        }
        if let url = URL(string: rawPath), url.scheme != nil {
            return url
        }
        if rawPath.hasPrefix("/") {
            return AppConfig.apiBaseURL.appendingPathComponent(String(rawPath.dropFirst()))
        }
        return AppConfig.apiBaseURL.appendingPathComponent(rawPath)
    }

    private func makeRequest(
        path: String,
        queryItems: [URLQueryItem] = []
    ) throws -> URLRequest {
        let cleanedPath = path.hasPrefix("/") ? String(path.dropFirst()) : path
        let baseURL = AppConfig.apiBaseURL.appendingPathComponent(cleanedPath)
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else {
            throw APIError.invalidURL
        }
        if !queryItems.isEmpty {
            components.queryItems = queryItems
        }
        guard let url = components.url else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let accessToken {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func perform<Response: Decodable>(_ request: URLRequest) async throws -> Response {
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw APIError.transport(error.localizedDescription)
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard 200..<300 ~= httpResponse.statusCode else {
            if httpResponse.statusCode == 401 {
                throw APIError.unauthorized
            }
            throw APIError.server(
                status: httpResponse.statusCode,
                message: errorMessage(from: data, statusCode: httpResponse.statusCode)
            )
        }

        do {
            return try decoder.decode(Response.self, from: data)
        } catch {
            throw APIError.decoding(error.localizedDescription)
        }
    }

    private func makeMultipartBody(
        boundary: String,
        fieldName: String,
        filename: String,
        mimeType: String,
        data: Data
    ) -> Data {
        var body = Data()
        body.appendString("--\(boundary)\r\n")
        body.appendString("Content-Disposition: form-data; name=\"\(fieldName)\"; filename=\"\(filename)\"\r\n")
        body.appendString("Content-Type: \(mimeType)\r\n\r\n")
        body.append(data)
        body.appendString("\r\n")
        body.appendString("--\(boundary)--\r\n")
        return body
    }

    private func errorMessage(from data: Data, statusCode: Int) -> String {
        if
            let object = try? JSONSerialization.jsonObject(with: data),
            let dictionary = object as? [String: Any],
            let detail = dictionary["detail"]
        {
            if let message = detail as? String {
                return message
            }
            if let detailDictionary = detail as? [String: Any] {
                if let error = detailDictionary["error"] as? String {
                    return error
                }
                if let photoID = detailDictionary["photo_id"] {
                    return "识别服务暂不可用，照片记录已保留：\(photoID)"
                }
                return String(describing: detailDictionary)
            }
            return String(describing: detail)
        }

        if let text = String(data: data, encoding: .utf8), !text.isEmpty {
            return text
        }
        return "HTTP \(statusCode)"
    }
}

private extension Data {
    mutating func appendString(_ value: String) {
        if let data = value.data(using: .utf8) {
            append(data)
        }
    }
}

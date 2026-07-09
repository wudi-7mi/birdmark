import Foundation

enum AppConfig {
    private static let apiBaseURLKey = "BirdmarkAPIBaseURL"
    static let defaultAPIBaseURLString = "http://127.0.0.1:8100"

    static var apiBaseURL: URL {
        get {
            let rawValue = UserDefaults.standard.string(forKey: apiBaseURLKey) ?? defaultAPIBaseURLString
            return normalizedURL(from: rawValue) ?? URL(string: defaultAPIBaseURLString)!
        }
        set {
            UserDefaults.standard.set(trimTrailingSlash(newValue.absoluteString), forKey: apiBaseURLKey)
        }
    }

    static var apiBaseURLString: String {
        get {
            apiBaseURL.absoluteString
        }
        set {
            if let url = normalizedURL(from: newValue) {
                apiBaseURL = url
            }
        }
    }

    static func resetAPIBaseURL() {
        UserDefaults.standard.removeObject(forKey: apiBaseURLKey)
    }

    static func normalizedURL(from rawValue: String) -> URL? {
        let trimmed = trimTrailingSlash(rawValue.trimmingCharacters(in: .whitespacesAndNewlines))
        guard !trimmed.isEmpty else {
            return nil
        }
        return URL(string: trimmed)
    }

    private static func trimTrailingSlash(_ value: String) -> String {
        var result = value
        while result.count > 1 && result.hasSuffix("/") {
            result.removeLast()
        }
        return result
    }
}

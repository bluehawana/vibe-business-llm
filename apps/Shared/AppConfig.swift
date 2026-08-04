import Foundation

/// Which server and which restaurant this device talks to.
///
/// Kept in UserDefaults and editable on the device, so moving the server to the
/// VPS — or swapping a broken Mac mini — never means rebuilding and re-signing
/// five apps. A signed build that can only be reconfigured in Xcode is a build
/// that fails on a Saturday night.
final class AppConfig: ObservableObject {
    static let shared = AppConfig()

    @Published var serverURL: String {
        didSet { defaults.set(serverURL, forKey: "serverURL") }
    }
    @Published var projectID: String {
        didSet { defaults.set(projectID, forKey: "projectID") }
    }
    /// Zettle Payments SDK client ID from developer.zettle.com. Stored on the
    /// device like the server address, so wiring up the reader is a settings
    /// change, never a rebuild. Empty = no reader, counter flow.
    @Published var zettleClientID: String {
        didSet { defaults.set(zettleClientID, forKey: "zettleClientID") }
    }

    private let defaults = UserDefaults.standard

    private init() {
        serverURL = defaults.string(forKey: "serverURL") ?? "https://order.ichiban.biz"
        projectID = defaults.string(forKey: "projectID") ?? "db3c418e95a6"
        zettleClientID = defaults.string(forKey: "zettleClientID") ?? ""
    }

    var isConfigured: Bool {
        !serverURL.trimmingCharacters(in: .whitespaces).isEmpty
            && !projectID.trimmingCharacters(in: .whitespaces).isEmpty
            && URL(string: serverURL) != nil
    }

    func url(_ path: String) -> URL? {
        let base = serverURL.trimmingCharacters(in: .whitespaces)
            .trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return URL(string: base + path)
    }
}

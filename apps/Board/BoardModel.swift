import Foundation

struct BoardOrder: Decodable, Identifiable, Equatable {
    let order_no: String
    let fulfillment: String

    var id: String { order_no }
}

private struct BoardResponse: Decodable { let orders: [BoardOrder] }

/// Polls the public guest feed. Deliberately the only endpoint this app knows:
/// it carries a number and a state, nothing a room full of strangers shouldn't see.
@MainActor
final class BoardModel: ObservableObject {
    @Published private(set) var preparing: [BoardOrder] = []
    @Published private(set) var ready: [BoardOrder] = []
    /// True once we've failed long enough that the numbers on screen may be
    /// stale. A board that silently freezes is worse than one that admits it —
    /// guests would keep waiting for a number that was already called.
    @Published private(set) var stale = false

    private var task: Task<Void, Never>?
    private var lastSuccess = Date()
    private let staleAfter: TimeInterval = 30
    /// When each number became ready, so "new" can pulse and then settle down.
    private(set) var readySince: [String: Date] = [:]

    func start() {
        task?.cancel()
        task = Task { [weak self] in
            while !Task.isCancelled {
                await self?.refresh()
                try? await Task.sleep(for: .seconds(3))
            }
        }
    }

    func stop() { task?.cancel(); task = nil }

    private func refresh() async {
        guard let url = AppConfig.shared.url("/api/display/\(AppConfig.shared.projectID)") else {
            return
        }
        var request = URLRequest(url: url)
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 10

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
            let orders = try JSONDecoder().decode(BoardResponse.self, from: data).orders

            preparing = orders.filter { $0.fulfillment == "new" || $0.fulfillment == "preparing" }
            let nowReady = orders.filter { $0.fulfillment == "ready" }

            let live = Set(nowReady.map(\.order_no))
            readySince = readySince.filter { live.contains($0.key) }
            for order in nowReady where readySince[order.order_no] == nil {
                readySince[order.order_no] = Date()
            }
            ready = nowReady

            lastSuccess = Date()
            stale = false
        } catch {
            // Keep showing the last known board — a brief server restart or wifi
            // blip must not blank the screen mid-service.
            stale = Date().timeIntervalSince(lastSuccess) > staleAfter
        }
    }

    func isFresh(_ order: BoardOrder) -> Bool {
        guard let since = readySince[order.order_no] else { return false }
        return Date().timeIntervalSince(since) < 45
    }
}

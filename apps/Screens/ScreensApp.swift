import SwiftUI

/// The iPad app. Each iPad in the restaurant does exactly one job, so the app
/// asks which job once and then never gets in the way again — no browser
/// chrome, no address bar, no tabs to wander into.
///
/// iOS has WKWebView, so the screens themselves are the same pages the web
/// serves. That is deliberate: a menu change or a bug fix reaches all four
/// iPads on the next load, with no rebuild, no re-signing and no App Store.
@main
struct ScreensApp: App {
    var body: some Scene {
        WindowGroup {
            RootView()
        }
    }
}

enum Screen: String, CaseIterable, Identifiable {
    case kiosk, sushi, kitchen, reception, pay

    var id: String { rawValue }

    var title: String {
        switch self {
        case .kiosk: "Kiosk — guests order"
        case .sushi: "Kitchen — sushi bar"
        case .kitchen: "Kitchen — hot line"
        case .reception: "Reception — hand-out"
        case .pay: "Pay — Zettle reader"
        }
    }

    var detail: String {
        switch self {
        case .kiosk: "Eat in or take away, pay, get a number"
        case .sushi: "Sushi dishes only"
        case .kitchen: "Hot dishes only"
        case .reception: "To the table, or bag it and call the number"
        case .pay: "Amount to charge, one tap to confirm"
        }
    }

    var symbol: String {
        switch self {
        case .kiosk: "hand.tap"
        case .sushi: "fish"
        case .kitchen: "flame"
        case .reception: "bell"
        case .pay: "creditcard"
        }
    }

    func path(projectID: String) -> String {
        switch self {
        case .kiosk: "/kiosk/\(projectID)"
        case .sushi: "/kitchen/\(projectID)?station=sushi"
        case .kitchen: "/kitchen/\(projectID)?station=kitchen"
        case .reception: "/pass/\(projectID)"
        case .pay: "/counter/\(projectID)"
        }
    }
}

struct RootView: View {
    @ObservedObject private var config = AppConfig.shared
    @AppStorage("screen") private var screenRaw = ""

    var body: some View {
        if let screen = Screen(rawValue: screenRaw) {
            WebScreen(screen: screen) { screenRaw = "" }
                .ignoresSafeArea()
                .statusBarHidden()
        } else {
            ScreenPicker(onPick: { screenRaw = $0.rawValue })
        }
    }
}

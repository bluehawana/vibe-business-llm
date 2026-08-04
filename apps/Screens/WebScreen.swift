import SwiftUI
@preconcurrency import WebKit

/// Full-screen shell around one staff (or kiosk) page.
///
/// Two things it adds over just opening Safari: the screen never sleeps, which
/// matters for a kitchen display nobody touches for an hour; and a reload on
/// wake, so an iPad that slept through a server restart comes back showing live
/// orders instead of an error page a cook might not notice.
struct WebScreen: UIViewRepresentable {
    let screen: Screen
    let onExit: () -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onExit: onExit) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        // The kiosk page posts card-payment requests here; see ZettleReader.swift.
        config.userContentController.add(context.coordinator, name: "zettle")
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        view.scrollView.bounces = false
        view.isOpaque = false
        view.backgroundColor = .black

        // Three fingers held down for a moment returns to the picker. Awkward on
        // purpose: a guest leaning on the kiosk must never trigger it.
        let exit = UILongPressGestureRecognizer(target: context.coordinator,
                                                action: #selector(Coordinator.handleExit))
        exit.numberOfTouchesRequired = 3
        exit.minimumPressDuration = 1.5
        view.addGestureRecognizer(exit)

        UIApplication.shared.isIdleTimerDisabled = true
        context.coordinator.observeWake(view)
        context.coordinator.load(view, screen: screen)
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        func userContentController(_ controller: WKUserContentController,
                                   didReceive message: WKScriptMessage) {
            guard message.name == "zettle",
                  let body = message.body as? [String: Any],
                  let orderId = body["orderId"] as? String,
                  let amount = body["amountMinor"] as? Int,
                  let currency = body["currency"] as? String else { return }
            CardReader.driver.charge(amountMinor: amount, currency: currency,
                                     reference: orderId) { [weak self] ok in
                DispatchQueue.main.async {
                    self?.view?.evaluateJavaScript("window.zettleResult(\(ok))")
                }
            }
        }

        private let onExit: () -> Void
        private weak var view: WKWebView?

        init(onExit: @escaping () -> Void) { self.onExit = onExit }

        func load(_ view: WKWebView, screen: Screen) {
            self.view = view
            guard let url = AppConfig.shared.url(screen.path(projectID: AppConfig.shared.projectID))
            else { return }
            view.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
        }

        func observeWake(_ view: WKWebView) {
            self.view = view
            NotificationCenter.default.addObserver(
                self, selector: #selector(reload),
                name: UIApplication.didBecomeActiveNotification, object: nil)
        }

        @objc func reload() { view?.reload() }

        @objc func handleExit(_ gesture: UILongPressGestureRecognizer) {
            guard gesture.state == .began else { return }
            onExit()
        }

        /// A failed load must not leave a cook staring at a blank screen with no
        /// idea whether the kitchen is quiet or the server is down.
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!,
                     withError error: Error) {
            showFailure(in: webView, error)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                     withError error: Error) {
            showFailure(in: webView, error)
        }

        private func showFailure(in webView: WKWebView, _ error: Error) {
            let message = error.localizedDescription
                .replacingOccurrences(of: "<", with: "&lt;")
            webView.loadHTMLString("""
                <html><body style="background:#14160f;color:#f4f1e8;font:600 22px -apple-system;
                  display:flex;align-items:center;justify-content:center;height:100vh;margin:0">
                  <div style="text-align:center">
                    <p style="font-size:44px">⚠️</p>
                    <p>Can't reach the server</p>
                    <p style="opacity:.5;font-weight:400;font-size:17px">\(message)</p>
                    <p style="opacity:.5;font-weight:400;font-size:17px">Retrying…</p>
                  </div></body></html>
                """, baseURL: nil)
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak webView] in
                webView?.reload()
            }
        }
    }
}
